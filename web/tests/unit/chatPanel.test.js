import { describe, it, expect } from 'vitest';
import {
  NEAR_BOTTOM_PX, isNearBottom, viewportMetrics, ChatScroll, renderChatPanel,
} from '../../src/chatPanel.js';

function fakeList({ scrollTop = 0, scrollHeight = 1000, clientHeight = 400 } = {}) {
  return { id: 'list', scrollTop, scrollHeight, clientHeight };
}

function fakePill() {
  return { hidden: true };
}

function makeScroll(list, pill = fakePill()) {
  const els = { list, pill };
  const scroll = new ChatScroll({
    listId: 'list', pillId: 'pill', getEl: (id) => els[id] ?? null,
  });
  return { scroll, els, pill };
}

describe('isNearBottom', () => {
  it('is true at the exact bottom', () => {
    expect(isNearBottom(fakeList({ scrollTop: 600 }))).toBe(true);
  });

  it('is true within the 80px threshold and false beyond it', () => {
    expect(NEAR_BOTTOM_PX).toBe(80);
    expect(isNearBottom(fakeList({ scrollTop: 520 }))).toBe(true); // 80px away
    expect(isNearBottom(fakeList({ scrollTop: 519 }))).toBe(false); // 81px away
  });

  it('treats a list that does not overflow as at the bottom', () => {
    expect(isNearBottom(fakeList({ scrollHeight: 300, clientHeight: 400 }))).toBe(true);
  });
});

describe('viewportMetrics', () => {
  it('falls back to the window height when visualViewport is missing', () => {
    expect(viewportMetrics({ innerHeight: 800, vv: null }))
      .toEqual({ height: 800, top: 0, keyboardOpen: false });
  });

  it('reports the visual viewport box and an open keyboard when it is much shorter than the window', () => {
    expect(viewportMetrics({ innerHeight: 844, vv: { height: 520, offsetTop: 0 } }))
      .toEqual({ height: 520, top: 0, keyboardOpen: true });
  });

  it('carries the iOS offsetTop so the panel follows the visible area', () => {
    expect(viewportMetrics({ innerHeight: 844, vv: { height: 500, offsetTop: 44 } }).top).toBe(44);
  });

  it('does not call a small browser-chrome change a keyboard', () => {
    expect(viewportMetrics({ innerHeight: 844, vv: { height: 800, offsetTop: 0 } }).keyboardOpen).toBe(false);
  });
});

describe('ChatScroll', () => {
  it('lands at the bottom the first time a list appears', () => {
    const list = fakeList({ scrollTop: 0 });
    const { scroll } = makeScroll(null);
    scroll.beforeRender(); // no list yet
    scroll.getEl = () => list;
    scroll.afterRender();
    expect(list.scrollTop).toBe(list.scrollHeight);
  });

  it('keeps the reader where they were across a full re-render when scrolled up', () => {
    const list = fakeList({ scrollTop: 100 });
    const { scroll, els } = makeScroll(list);
    scroll.beforeRender();
    els.list = fakeList({ scrollTop: 0 }); // the rebuilt element starts at the top
    scroll.afterRender();
    expect(els.list.scrollTop).toBe(100);
  });

  it('re-sticks to the bottom across a re-render when the reader was at the bottom', () => {
    const list = fakeList({ scrollTop: 600 });
    const { scroll, els } = makeScroll(list);
    scroll.beforeRender();
    els.list = fakeList({ scrollTop: 0, scrollHeight: 1400 });
    scroll.afterRender();
    expect(els.list.scrollTop).toBe(1400);
  });

  it('pinNext forces the bottom once even when scrolled up (sending a message)', () => {
    const list = fakeList({ scrollTop: 100 });
    const { scroll, els } = makeScroll(list);
    scroll.pinNext();
    scroll.beforeRender();
    els.list = fakeList({ scrollTop: 0, scrollHeight: 1400 });
    scroll.afterRender();
    expect(els.list.scrollTop).toBe(1400);
    // ...but only once: the next render honours where the reader is.
    els.list.scrollTop = 200;
    scroll.beforeRender();
    const rebuilt = fakeList({ scrollTop: 0, scrollHeight: 1400 });
    els.list = rebuilt;
    scroll.afterRender();
    expect(rebuilt.scrollTop).toBe(200);
  });

  describe('contentChanged (a streaming delta)', () => {
    it('follows the stream when the reader is at the bottom', () => {
      const list = fakeList({ scrollTop: 600 });
      const { scroll, pill } = makeScroll(list);
      scroll.contentChanged(() => { list.scrollHeight = 1200; });
      expect(list.scrollTop).toBe(1200);
      expect(pill.hidden).toBe(true);
    });

    it('follows the stream when within 80px of the bottom', () => {
      const list = fakeList({ scrollTop: 530 });
      const { scroll } = makeScroll(list);
      scroll.contentChanged(() => { list.scrollHeight = 1100; });
      expect(list.scrollTop).toBe(1100);
    });

    it('never moves the view when the reader scrolled up, and shows the new pill', () => {
      const list = fakeList({ scrollTop: 150 });
      const { scroll, pill } = makeScroll(list);
      scroll.contentChanged(() => { list.scrollHeight = 1300; });
      expect(list.scrollTop).toBe(150);
      expect(pill.hidden).toBe(false);
    });

    it('keeps the pill across a full re-render until the reader gets back to the bottom', () => {
      const list = fakeList({ scrollTop: 150 });
      const { scroll, els, pill } = makeScroll(list);
      scroll.contentChanged(() => { list.scrollHeight = 1300; });
      scroll.beforeRender();
      els.list = fakeList({ scrollTop: 0, scrollHeight: 1300 });
      const rebuiltPill = fakePill();
      els.pill = rebuiltPill;
      scroll.afterRender();
      expect(rebuiltPill.hidden).toBe(false);
      expect(pill.hidden).toBe(false);

      // reaching the bottom clears it
      els.list.scrollTop = 900;
      scroll.onScroll(els.list);
      expect(els.pill.hidden).toBe(true);
    });
  });

  it('jumpToBottom scrolls down and hides the pill', () => {
    const list = fakeList({ scrollTop: 150 });
    const { scroll, pill } = makeScroll(list);
    scroll.contentChanged(() => { list.scrollHeight = 1300; });
    expect(pill.hidden).toBe(false);
    scroll.jumpToBottom();
    expect(list.scrollTop).toBe(1300);
    expect(pill.hidden).toBe(true);
  });
});

describe('renderChatPanel', () => {
  const html = renderChatPanel({
    header: '<h1>Ask</h1>', banner: '<div class="chat-banner">Offline</div>',
    body: '<div class="chat-messages" id="chat-messages"></div>',
    composer: '<div class="chat-composer"></div>', pillId: 'chat-new-pill', pillAction: 'chat:jump-bottom',
  });

  it('lays out header, banner, scrolling body with the pill, then the composer last', () => {
    const order = ['chat-panel-head', 'chat-banner', 'chat-panel-body', 'chat-new-pill', 'chat-composer']
      .map((marker) => html.indexOf(marker));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it('renders the pill hidden with its action', () => {
    expect(html).toMatch(/id="chat-new-pill"[^>]*hidden/);
    expect(html).toContain('data-a="chat:jump-bottom"');
  });
});
