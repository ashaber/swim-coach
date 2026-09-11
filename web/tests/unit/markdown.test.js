import { describe, it, expect } from 'vitest';
import { renderChatMarkdown } from '../../src/markdown.js';

// Build D: markdown rendering in coach chat. renderChatMarkdown() is the
// pure text-in/HTML-string-out conversion used by views.js's
// renderChatMessage for both the main Coach tab and the workout-detail
// focused chat -- unit-tested in isolation here so the markdown/security
// logic doesn't need a DOM (vitest runs with environment: 'node', see
// vite.config.js) or a rendered chat bubble to exercise.

describe('renderChatMarkdown', () => {
  it('renders bold and italic as real emphasis elements, not literal asterisks', () => {
    const html = renderChatMarkdown('This is **bold** and this is *italic*.');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<em>italic</em>');
    expect(html).not.toContain('**bold**');
  });

  it('renders a header as a heading element', () => {
    const html = renderChatMarkdown('# Week 30 overview');
    expect(html).toMatch(/<h1[^>]*>Week 30 overview<\/h1>/);
  });

  it('renders a GFM pipe table as a real <table> with the right row/column count', () => {
    const md = [
      '| Day | Sport | Distance |',
      '| --- | --- | --- |',
      '| Mon | swim_pool | 3000m |',
      '| Wed | swim_ow | 5000m |',
    ].join('\n');
    const html = renderChatMarkdown(md);
    expect(html).toContain('<table>');
    // 3 header cells (matched as an exact tag, not "<thead>")
    expect((html.match(/<th>/g) || []).length).toBe(3);
    // 2 data rows x 3 cells = 6 <td>
    expect((html.match(/<td>/g) || []).length).toBe(6);
    expect(html).toContain('Mon');
    expect(html).toContain('swim_ow');
    // never leaves raw pipe-table syntax in the output
    expect(html).not.toMatch(/\|\s*Day\s*\|/);
  });

  it('renders unordered and ordered lists with real list items', () => {
    const html = renderChatMarkdown('- one\n- two\n\n1. first\n2. second');
    expect(html).toContain('<ul>');
    expect(html).toContain('<ol>');
    expect((html.match(/<li>/g) || []).length).toBe(4);
  });

  it('does not throw on partial/incomplete markdown mid-stream', () => {
    const partials = [
      '| Day | Sport |\n| --- | --- |\n| Mon | sw',
      'This is **bold that never clos',
      '### Heading that is unfinis',
      '- item one\n- item tw',
      '',
      null,
      undefined,
    ];
    for (const p of partials) {
      expect(() => renderChatMarkdown(p)).not.toThrow();
      expect(typeof renderChatMarkdown(p)).toBe('string');
    }
  });

  it('renders literal "<script>...</script>" text as inert text, never as an executable tag', () => {
    const html = renderChatMarkdown('careful: <script>alert(1)</script> is just an example.');
    // The literal source characters "<script>" must never survive as a raw,
    // openable HTML tag in the output.
    expect(html).not.toMatch(/<script[^>]*>/);
    // It must still be visible to the reader as inert, escaped text.
    expect(html).toMatch(/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  });

  it('neutralizes an img-onerror XSS attempt the same way', () => {
    const html = renderChatMarkdown('<img src=x onerror="alert(1)">');
    expect(html).not.toMatch(/<img[^>]*onerror/);
    expect(html).toContain('&lt;img');
  });

  it('renders a real render_plan_table-shaped weekly table correctly', () => {
    // Verbatim shape from backend/app/tools.py::format_week_plan_table.
    const md = [
      '### Week 2026-W30 -- Base block -- Aerobic development',
      '',
      'Weekly volume target: 18,000 m',
      '',
      '| Day | Date | Sport | Distance | Duration | Intensity | Purpose |',
      '| --- | --- | --- | --- | --- | --- | --- |',
      '| Mon | 2026-07-20 | swim_pool | 3000m | 60min | Z2 | Aerobic base |',
      '| Wed | 2026-07-22 | swim_pool | 3500m | 70min | Z2/Z3 | Threshold intervals |',
      '| Fri | 2026-07-24 | swim_ow | 5000m | 100min | Z2 | Long open-water swim |',
    ].join('\n');
    const html = renderChatMarkdown(md);
    expect(html).toMatch(/<h3[^>]*>Week 2026-W30/);
    expect(html).toContain('<table>');
    expect((html.match(/<th>/g) || []).length).toBe(7);
    expect((html.match(/<tr>/g) || []).length).toBe(4); // 1 header + 3 data rows
    expect(html).toContain('Threshold intervals');
  });
});
