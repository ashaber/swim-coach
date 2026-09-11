// Build D: markdown -> safe HTML for chat bubbles.
//
// The coach's replies (`msg.content` in chat.js's session state) are
// markdown -- bold, headers, lists, and (since backend PR #173's
// render_plan_table tool) full GFM tables -- but before this module existed
// nothing in the app parsed markdown at all (views.js's renderChatMessage
// ran every message through a plain HTML-escaper), so `**bold**` and
// `| Day | Sport |` pipe tables rendered as literal escaped text instead of
// formatting. This module is the one place that turns that markdown into
// real HTML.
//
// Security posture (read this before touching the regex below): `content`
// is LLM-generated text -- untrusted, same as any other model output. The
// baseline this module must not regress is the old one: `esc()`-everything,
// so literal "<script>...</script>" text in a reply can never execute.
// `marked`'s default behavior does NOT preserve that baseline on its own --
// by design, any "<tag>"-shaped run of characters found in the source
// markdown is recognized as inline/block HTML and passed through to the
// output UNESCAPED (this is the "raw HTML passthrough" markdown authors
// rely on to mix HTML into their markdown; marked dropped its `sanitize`
// option years ago and now expects callers to sanitize themselves, e.g.
// with DOMPurify, if the source isn't trusted). Ours isn't trusted.
//
// Rather than add a second dependency (a DOM-based sanitizer) or hand-roll
// an HTML-output sanitizer (easy to get subtly wrong -- attribute-based
// vectors like `onerror=`, `javascript:` hrefs, etc.), this neutralizes the
// attack at the source: every literal "<" in the markdown is replaced with
// its entity ("&lt;") *before* marked ever tokenizes the text. marked's
// HTML-tag recognition requires a raw "<" to even begin matching a tag --
// with none left in the input, no "<...>" run can ever be recognized as
// HTML by marked's lexer, block or inline, no matter what's inside it. The
// escaped text still round-trips correctly through marked (its own text
// escaper leaves already-valid entities like "&lt;" alone -- it only
// escapes bare "&" that isn't already part of an entity), so
// "<script>alert(1)</script>" in a reply renders as the visible, inert
// literal text "<script>alert(1)</script>", exactly like the old esc()
// baseline did.
//
// Only "<" is escaped, not ">" -- GFM blockquotes ("> quoted text") use a
// leading ">" and a lone ">" has no execution surface on its own, so
// leaving it alone keeps blockquote syntax working while still fully
// closing off the HTML-tag vector (a tag needs "<name", not just a
// trailing ">").
import { marked } from 'marked';
import log from './log.js';

marked.use({ gfm: true, breaks: true });

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/**
 * Converts one chat message's markdown content to an HTML string safe to
 * insert via innerHTML. `text` may be partial/incomplete (mid-stream: a
 * half-finished table, an unclosed "**bold" marker, a cut-off heading) --
 * marked's tokenizer is lenient and renders whatever it can parse from a
 * truncated source without throwing, so streaming content gets best-effort
 * formatting rather than a broken bubble. Never throws: any unexpected
 * parser failure is logged and falls back to the old plain-escaped-text
 * rendering so a single bad message can't break the chat UI.
 */
export function renderChatMarkdown(text) {
  const source = String(text ?? '');
  const neutralized = source.replace(/</g, '&lt;');
  try {
    return marked.parse(neutralized);
  } catch (err) {
    log.error('chat markdown render failed, falling back to plain text', {
      error: String((err && err.message) || err),
    });
    return escapeHtml(source);
  }
}
