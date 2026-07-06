// Pure parsing of the backend's `text/event-stream` chat responses.
// Kept free of fetch/DOM access so it's cheaply unit-testable -- the
// network reader (in api.js) just feeds raw chunks through `feedSSEBuffer`
// and gets back fully-parsed event objects plus whatever partial line
// should be carried over into the next chunk.
//
// Wire format (see backend app/claude.py `_sse`): each event is a single
// line `data: {json}` followed by a blank line, e.g.
//   data: {"type":"text","text":"hello"}\n\n
// A frame can arrive split across multiple `fetch` chunks at any byte
// offset (mid-line, mid-`data: `, mid-JSON) -- `feedSSEBuffer` only ever
// treats a `\n\n`-terminated segment as complete, so a split frame simply
// carries over in `remainder` until the rest arrives.

/**
 * @param {string} buffer  leftover text from the previous call (starts '')
 * @param {string} chunk   newly-decoded text from the stream
 * @returns {{ events: object[], remainder: string }}
 *   `events` are parsed in arrival order; `remainder` is the trailing
 *   incomplete segment to pass back in as `buffer` next call.
 */
export function feedSSEBuffer(buffer, chunk) {
  const combined = buffer + chunk;
  const segments = combined.split('\n\n');
  const remainder = segments.pop() ?? '';

  const events = [];
  for (const segment of segments) {
    const event = parseSSESegment(segment);
    if (event) events.push(event);
  }
  return { events, remainder };
}

function parseSSESegment(segment) {
  const dataLine = segment.split('\n').find((line) => line.startsWith('data:'));
  if (!dataLine) return null;
  const jsonStr = dataLine.slice(5).trim();
  if (!jsonStr) return null;
  try {
    return JSON.parse(jsonStr);
  } catch {
    return null; // malformed frame -- drop it rather than crash the stream
  }
}
