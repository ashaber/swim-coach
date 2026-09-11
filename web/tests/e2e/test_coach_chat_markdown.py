"""e2e coverage for Build D: markdown rendering in coach chat.

Same mocked-backend conventions as test_coach_chat.py (SSE body mocked via
Playwright routes with CORS headers, service worker blocked so route
interception sees every fetch -- see that file's module docstring for the
full CORS/preflight rationale). No real backend is ever contacted.

Runs on the same `page` fixture shape as test_coach_chat.py: chromium at
412x915 and webkit at 390x844 (see conftest.BROWSERS) -- the two mobile
viewports this build's task specifically calls out.
"""

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity

BASE_URL = 'https://coach-api.test'
TOKEN = 'test-token-123'

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

PLAN_STUB = '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}'
PLAN_LOAD_STUB = '{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'

# Verbatim shape from backend/app/tools.py::format_week_plan_table (the
# render_plan_table tool, PR #173) -- a "### Week ..." heading, a plain
# target line, then a "| Day | Date | Sport | Distance | Duration |
# Intensity | Purpose |" GFM table. Sent here as the full streamed reply
# text (single SSE "text" event, same as a real turn that completes without
# any intermediate deltas).
WEEK_TABLE_MARKDOWN = (
    '### Week 2026-W30 -- Base block -- Aerobic development\\n\\n'
    'Weekly volume target: 18,000 m\\n\\n'
    '| Day | Date | Sport | Distance | Duration | Intensity | Purpose |\\n'
    '| --- | --- | --- | --- | --- | --- | --- |\\n'
    '| Mon | 2026-07-20 | swim_pool | 3000m | 60min | Z2 | Aerobic base |\\n'
    '| Wed | 2026-07-22 | swim_pool | 3500m | 70min | Z2/Z3 | Threshold intervals |\\n'
    '| Fri | 2026-07-24 | swim_ow | 5000m | 100min | Z2 | Long open-water swim |'
)


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Same shape as test_coach_chat.py's `page` fixture -- see that file's
    docstring for why service workers are blocked and /api/athlete,
    /api/grants, /api/plan, /api/plan/load are all pre-stubbed."""
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
        ctx.route(
            '**/api/athlete*',
            _cors_route(200, 'application/json', '{"slug": "renee", "name": "Renee"}'),
        )
        ctx.route('**/api/grants*', _cors_route(200, 'application/json', '[]'))
        ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
        ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
        pg = ctx.new_page()
        js_errors = []
        pg.on('pageerror', lambda e: js_errors.append(str(e)))
        pg.goto(base_url)
        try:
            yield pg
            real_errors = [e for e in js_errors
                           if 'sw.js load failed' not in e
                           and 'Importing a module script failed' not in e]
            assert not real_errors, f'Uncaught JS errors: {real_errors}'
        finally:
            ctx.close()
            browser.close()


def _configure_backend(page, base_url=BASE_URL, token=TOKEN):
    page.evaluate(
        "(cfg) => window.localStorage.setItem("
        "'swimcoach_settings', JSON.stringify({baseUrl: cfg.baseUrl, token: cfg.token, version: 2}))",
        {'baseUrl': base_url, 'token': token},
    )
    page.reload()
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('.settings-wrap')


def test_coach_chat_renders_markdown_table_as_real_table(page):
    """The core defect this build fixes: a render_plan_table-shaped reply
    must render as a real <table>, not a raw '| Day | Date | ...' pipe
    block, and the table must fit/scroll within the mobile viewport rather
    than blowing out the page's own layout."""
    sse_body = (
        f'data: {{"type":"text","text":"{WEEK_TABLE_MARKDOWN}"}}\n\n'
        'data: {"type":"done","stop_reason":"end_turn"}\n\n'
    )
    page.route('**/api/chat', _cors_route(200, 'text/event-stream', sse_body))

    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')
    page.fill('#chat-input', 'what does next week look like?')
    page.click('[data-a="chat:send"]')

    # A real <table> lands in the coach bubble.
    page.wait_for_selector('.chat-row.coach table', timeout=5000)

    # Raw pipe-table syntax must never be visible as literal text.
    body_text = page.locator('.chat-row.coach .chat-bubble').last.inner_text()
    assert '| Day | Date |' not in body_text
    assert '---' not in body_text

    # Real table structure: 7 header cells, 3 data rows (+ header = 4 <tr>).
    table = page.locator('.chat-row.coach table').last
    assert table.locator('th').count() == 7
    assert table.locator('tr').count() == 4
    assert 'Threshold intervals' in table.inner_text()

    # The heading rendered as a real heading element, not literal "###".
    heading = page.locator('.chat-row.coach h3').last
    assert 'Week 2026-W30' in heading.inner_text()
    assert '###' not in page.locator('.chat-row.coach .chat-bubble').last.inner_text()

    # The table must fit within (or scroll inside) the mobile viewport --
    # never stretch the page's own body past the viewport width.
    viewport = page.viewport_size
    body_box = page.evaluate('() => document.body.getBoundingClientRect().width')
    assert body_box <= viewport['width'] + 1  # +1: sub-pixel rounding tolerance

    # The bubble itself (the visible box) also stays within the viewport --
    # a too-wide table must scroll inside its own box (see index.html's
    # .chat-md:has(table) { overflow-x: auto }), not push the bubble wider
    # than the screen.
    bubble_box = page.locator('.chat-row.coach .chat-bubble').last.bounding_box()
    assert bubble_box['x'] + bubble_box['width'] <= viewport['width'] + 1


def test_coach_chat_renders_bold_and_heading_not_literal_markdown(page):
    sse_body = (
        'data: {"type":"text","text":"This week is **easier** before your long swim."}\n\n'
        'data: {"type":"done","stop_reason":"end_turn"}\n\n'
    )
    page.route('**/api/chat', _cors_route(200, 'text/event-stream', sse_body))

    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')
    page.fill('#chat-input', 'why is this week easier?')
    page.click('[data-a="chat:send"]')

    page.wait_for_selector('.chat-row.coach strong', timeout=5000)
    assert page.locator('.chat-row.coach strong').last.inner_text() == 'easier'
    bubble_text = page.locator('.chat-row.coach .chat-bubble').last.inner_text()
    assert '**easier**' not in bubble_text


def test_coach_chat_script_tag_text_renders_inert_not_executed(page):
    """XSS regression guard at the real-DOM level (unit tests already cover
    this at the string level in tests/unit/markdown.test.js) -- a reply
    containing literal "<script>...</script>" text must never create a real
    script element or fire an error/alert."""
    sse_body = (
        'data: {"type":"text","text":"note: <script>window.__xss = true</script> is just an example."}\n\n'
        'data: {"type":"done","stop_reason":"end_turn"}\n\n'
    )
    page.route('**/api/chat', _cors_route(200, 'text/event-stream', sse_body))

    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')
    page.fill('#chat-input', 'ignore the note below')
    page.click('[data-a="chat:send"]')

    page.wait_for_function(
        "() => { const b = document.querySelectorAll('.chat-row.coach .chat-bubble'); "
        "return b.length > 0 && b[b.length-1].textContent.includes('is just an example'); }",
        timeout=5000,
    )

    assert page.evaluate('() => window.__xss') is None
    assert page.locator('.chat-row.coach script').count() == 0
    bubble_text = page.locator('.chat-row.coach .chat-bubble').last.inner_text()
    assert '<script>' in bubble_text
