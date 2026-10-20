// Reusable chat-panel layout and scroll behaviour -- the Coach tab uses it now; the workout and
// session threads can adopt it later. Two concerns, both kept free of app state:
//
//  1. LAYOUT. `renderChatPanel` emits a full-height column: header band, a message body that is
//     the ONLY thing that scrolls, and a composer pinned at the bottom (above the tab bar). The
//     CSS in index.html (`.chat-panel`) sizes it from `--vv-*` custom properties that
//     `syncViewport` keeps equal to the VISUAL viewport, so the composer rides above the on-screen
//     keyboard on iOS and Android.
//
//  2. SCROLL ANCHORING (`ChatScroll`). The old tab rebuilt the whole app's innerHTML on every
//     streamed delta and then forced the list to the bottom. That collapsed and re-grew the
//     document many times a second (the "bounce") and yanked a reader who had scrolled up back
//     down. `ChatScroll` follows a stream only while the reader is at (or within
//     NEAR_BOTTOM_PX of) the bottom, never moves a reader who scrolled up (a "new" pill offers
//     the jump instead), keeps their place across the full re-renders that do still happen, and
//     lets a send pin the view to the bottom exactly once.

/** How close to the bottom still counts as "at the bottom" (px). */
export const NEAR_BOTTOM_PX = 80;

/** A visual viewport this much shorter than the window means the on-screen keyboard is up. */
const KEYBOARD_MIN_PX = 120;

/** Distance (px) between the visible bottom edge of a scroll container and its content's end. */
export function distanceFromBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight;
}

export function isNearBottom(el, threshold = NEAR_BOTTOM_PX) {
  return distanceFromBottom(el) <= threshold;
}

/** The box the panel should occupy. `vv` is `window.visualViewport` (or null where unsupported). */
export function viewportMetrics({ innerHeight, vv }) {
  if (!vv) return { height: innerHeight, top: 0, keyboardOpen: false };
  return {
    height: vv.height,
    top: vv.offsetTop,
    keyboardOpen: innerHeight - vv.height > KEYBOARD_MIN_PX,
  };
}

/** Pushes the visual-viewport box and the tab bar's height into CSS custom properties and flags
 * an open keyboard on <body>. Cheap and idempotent: call after renders and on viewport events. */
export function syncViewport(win = window, doc = document) {
  const { height, top, keyboardOpen } = viewportMetrics({
    innerHeight: win.innerHeight, vv: win.visualViewport || null,
  });
  const root = doc.documentElement.style;
  root.setProperty('--vv-h', `${Math.round(height)}px`);
  root.setProperty('--vv-top', `${Math.round(top)}px`);
  const tabbar = doc.querySelector('.tabbar');
  root.setProperty('--tabbar-h', `${tabbar ? tabbar.offsetHeight : 64}px`);
  doc.body.classList.toggle('kb-open', keyboardOpen);
}

/** Keeps `syncViewport` current as the keyboard opens/closes, the phone rotates or the browser
 * chrome collapses. Returns a function that removes the listeners. */
export function trackViewport(win = window, doc = document) {
  let queued = false;
  const schedule = () => {
    if (queued) return;
    queued = true;
    win.requestAnimationFrame(() => { queued = false; syncViewport(win, doc); });
  };
  const vv = win.visualViewport;
  win.addEventListener('resize', schedule);
  win.addEventListener('orientationchange', schedule);
  vv?.addEventListener('resize', schedule);
  vv?.addEventListener('scroll', schedule);
  syncViewport(win, doc);
  return () => {
    win.removeEventListener('resize', schedule);
    win.removeEventListener('orientationchange', schedule);
    vv?.removeEventListener('resize', schedule);
    vv?.removeEventListener('scroll', schedule);
  };
}

/** The panel's markup. `body` is whatever fills the middle (normally the message list, or an
 * empty state); `composer` is the already-rendered composer. The pill is part of the body area so
 * it floats just above the composer, and starts hidden. */
export function renderChatPanel({
  header, banner = '', body, composer, pillId, pillAction, pillLabel = '↓ new',
}) {
  return `
    <header class="chat-panel-head">${header}</header>
    ${banner}
    <div class="chat-panel-body">
      ${body}
      <button type="button" class="chat-new-pill" id="${pillId}" data-a="${pillAction}" hidden>${pillLabel}</button>
    </div>
    ${composer}`;
}

/** Scroll anchoring for ONE message list (`listId`), with an optional "new" pill (`pillId`).
 * `getEl` is injectable so the logic is unit-testable without a DOM. */
export class ChatScroll {
  constructor({ listId, pillId, getEl = (id) => document.getElementById(id) }) {
    this.listId = listId;
    this.pillId = pillId;
    this.getEl = getEl;
    this.hadList = false; // was a list on screen before the current render?
    this.stick = true; // was the reader at the bottom?
    this.top = 0; // where they were, if not
    this.unseen = false; // content arrived below the fold: the pill shows
    this.pin = false; // the next render goes to the bottom regardless (a send)
  }

  list() {
    return this.getEl(this.listId);
  }

  pill() {
    return this.pillId ? this.getEl(this.pillId) : null;
  }

  /** Call right before the DOM is rebuilt: remember where the reader is. */
  beforeRender() {
    const el = this.list();
    this.hadList = Boolean(el);
    if (!el) return;
    this.top = el.scrollTop;
    this.stick = this.pin || isNearBottom(el);
  }

  /** Call right after the DOM is rebuilt: put the reader back (or at the bottom if they were
   * there, if this is the list's first appearance, or if a send pinned it). */
  afterRender() {
    const el = this.list();
    if (!el) {
      this.pin = false;
      return;
    }
    if (!this.hadList || this.stick || this.pin) {
      el.scrollTop = el.scrollHeight;
      this.unseen = false;
    } else {
      el.scrollTop = this.top;
    }
    this.pin = false;
    this.showPill();
  }

  /** The next render lands on the bottom whatever the reader's position (they just sent). */
  pinNext() {
    this.pin = true;
    this.unseen = false;
  }

  /** Runs `mutate` (which grows the list's content, e.g. patching the streaming bubble) and then
   * either follows it to the bottom -- only if the reader was within NEAR_BOTTOM_PX of it -- or
   * leaves the view exactly where it was and raises the "new" pill. */
  contentChanged(mutate) {
    const el = this.list();
    if (!el) {
      mutate();
      return;
    }
    const follow = isNearBottom(el);
    const before = el.scrollTop;
    mutate();
    if (follow) {
      el.scrollTop = el.scrollHeight;
      this.unseen = false;
    } else {
      el.scrollTop = before;
      this.unseen = true;
    }
    this.showPill();
  }

  /** Scroll listener: reaching the bottom clears the pill. */
  onScroll(el) {
    if (el.id !== this.listId) return;
    if (isNearBottom(el)) {
      this.unseen = false;
      this.showPill();
    }
  }

  /** The pill was tapped. */
  jumpToBottom() {
    const el = this.list();
    if (el) el.scrollTop = el.scrollHeight;
    this.unseen = false;
    this.showPill();
  }

  showPill() {
    const pill = this.pill();
    if (pill) pill.hidden = !this.unseen;
  }

  /** Starts listening for the reader's own scrolling (scroll events do not bubble, so capture). */
  attach(doc = document) {
    doc.addEventListener('scroll', (e) => {
      if (e.target && e.target.id === this.listId) this.onScroll(e.target);
    }, true);
  }
}
