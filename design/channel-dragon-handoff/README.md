# Handoff: Channel Dragon — Coaching App PWA Refresh

## Overview
A swim-coaching PWA: a workout log with drill-in stats, an AI coach that explains stats and can adapt the daily training plan, and a coach chat. This bundle covers the interactive flow, the selected visual direction ("Bioluminescent Dusk" dark mode), and the app icon.

## About the Design Files
The files in this bundle (`.dc.html`) are **design references built in HTML** — they render directly in a browser but are prototyping tools, not production code. Do not copy their markup/CSS/JS verbatim into the codebase. The task is to **recreate this design in the target codebase's existing environment** (React Native, SwiftUI, native Android, or whatever the app already uses) following its established components, navigation, and state patterns. If no environment exists yet, choose the most appropriate framework and implement there.

## Fidelity
**High-fidelity.** Colors, typography, spacing, copy, and interaction states shown are intended to be close to final — recreate them precisely rather than reinterpreting.

## Files
- `Channel Dragon Prototype.dc.html` — **primary interaction reference.** Fully clickable: 3-tab nav (Plan / Log / Coach), stat drill-ins, an "explain" info-tap into coach chat, and the plan discuss → adapt → accept/discuss/cancel loop. Open it in a browser and click through it — this is the source of truth for flow and state transitions.
- `Channel Dragon Redesign.dc.html` — visual-direction reference ("Bioluminescent Dusk"): 3 static screens (Workout Detail, Plan Adapt, Coach Chat) with slightly more finished visual polish (gradient text/orbs, coach note callouts). Use alongside the Prototype for exact color/type treatment.
- `App Icon.dc.html` — app icon at 512/80/36px, built from `assets/dragonfly-icon-teal.png` (a swimmer/dragonfly mark recolored as cream-on-teal duotone).
- `support.js` — runtime harness for the `.dc.html` files; only needed to view them in a browser, not part of the app.

## Screens / Views

### Tab bar (persistent bottom nav)
Fixed, height 74px, background `#10141b`, top border `1px solid #242f3a`. 4 items, equal width, centered text, `font-size:10.5px; font-weight:700`: **Plan, Log, Coach, Settings** (Settings unbuilt/disabled in this pass). Active tab color `#45afc6`; inactive `#5a8a94`.

### Log tab → Workout Detail (default view)
Header row: back arrow (`#9cc7cf`), centered gradient label "WORKOUT" (uppercase, letter-spacing .08em, `linear-gradient(90deg,#45afc6,#a3e4d7,#f49342)` text), overflow `⋯`.
Title: "Open water · long swim" (Manrope 800, 22px). Subtitle: "Tue Jul 7 · Half Moon Bay" (`#7fa8b0`, 12.5px).
3-up stat grid (`grid-template-columns:1fr 1fr 1fr`, gap 8px), each card `#1c2530` bg, `1px solid #2a3542` border, radius 14px, padding 12px 10px:
- **Pace /100m** → `1:38`, value color `#45afc6`
- **HR decoupling** (with an inline `(i)` info glyph, 13×13 circle, border `#556`) → `4.2%`, value color `#f49342`
- **Distance** → `3,800m`, default text color

Each card tappable → opens a drill-in detail (see below); the `(i)` on decoupling opens a separate "explain" sheet. Helper caption below grid: "Tap any stat to drill in · tap the (i) to have your coach explain it" (`#6d95a0`, 11px).

Chart card below: "Pace & HR over time" header + "last 62 min" label, an inline SVG line chart (pace line = 3-color gradient stroke `#45afc6→#a3e4d7→#f49342`; HR-drift line = dashed `#4a7480`), legend row below.

Coach note callout: gradient dot avatar (26px circle, `linear-gradient(135deg,#45afc6,#a3e4d7,#f49342)`) + "COACH NOTE" label (`#a3e4d7`) + note text, on `#0e3a44` bg / `#1c6478` border.

Footer: "Ask about this swim" label + tappable placeholder row → opens embedded workout-scoped chat.

### Log tab → Stat drill-in
Back link "← Back to workout" (`#9cc7cf`). Three variants depending on which stat was tapped:
- **Pace**: "Pace by 100m split" + 6 split rows, each a mini progress bar (`#1d2740` track, `linear-gradient(90deg,#45afc6,#a3e4d7)` fill by %) with split number and pace value (`#45afc6`).
- **HR decoupling**: explainer paragraph, then a 2-up "First half / Second half" bpm comparison (second half value in `#f49342`), then a full-width CTA button "Ask coach to explain further →" (`#45afc6` bg, white text, radius 12px).
- **Distance**: Moving/Elapsed time 2-up, then a scrollable lap table (sticky header, columns Lap/Dist/Time/Pace/HR — pace values `#45afc6`), then a "Pauses / transitions" list, then a note about future data sources.

### Log tab → Coach-explain sheet
Triggered by the `(i)` glyph. Back link, then a card: "What's HR decoupling?" (title `#f49342`) + explainer paragraph, then an outlined "Ask coach a follow-up →" button.

### Log tab → Embedded workout chat
Scoped chat tied to one workout ("About: Tue's long swim" label). Message bubbles: incoming `#1c2530` bg, radius `14px 14px 14px 4px`; outgoing `linear-gradient(120deg,#1c4a52,#1c2530)`, radius `14px 14px 4px 14px`. Text input pinned to bottom (`#1c2530` bg, radius 12px) + circular send button (`#45afc6` bg, 34px, `↑` glyph).

### Plan tab → Today (original, unadjusted)
Gradient "TODAY'S PLAN" label, title "Wed · Build week 3". Session card (`#1c2530` bg, radius 14px): title + volume/duration, then Warm-up / Main set / Cool-down rows (label `#7fa8b0` uppercase 10px, value `#eef7f8` 13px), a "Focus" callout row, and a technique-reference link (`#a3e4d7`).
Prompt line: "Life get in the way, or feeling off? Tell your coach…" → outlined button "Discuss today's session →".
Below: "Coming up · Thu, dryland strength" preview card listing exercises with set×rep counts and a video-reference link.

### Plan tab → Today (adjusted state)
Same card shape, but bg `#0e3a44` with `#45afc6` border and a "ADJUSTED WITH YOUR COACH" label; shows the reduced session (2,400m / ~55min) with updated Warm-up/Main set/Cool-down/Focus content.

### Plan tab → Discuss (chat)
Back link "← Back to plan". Same bubble chat pattern as workout chat, contextualized to "About: today's planned session". Ends with full-width CTA "View adjusted session →" pinned to bottom.

### Plan tab → Proposal (adapt review)
Back link "← Back to discussion". Title "Wednesday, adjusted". Original plan shown struck-through/dimmed (opacity .55, `text-decoration:line-through`), a centered `↓` arrow (`#45afc6`), then the proposed-change card (`#0e3a44` bg, `#45afc6` border) with Warm-up/Main set/Cool-down/Focus. Three equal-width buttons: **Accept** (filled `#45afc6`), **Discuss** (outlined), **Cancel** (outlined, muted text).

### Plan tab → Accepted (confirmation)
Centered: gradient checkmark badge (56px circle), "Plan updated" title, confirmation copy, outlined "Back to plan" button.

### Coach tab
Header: gradient avatar dot (34px) + "Coach" name + "● grounded in your plan" status line (`#45afc6`). Scrollable message list, same bubble styling as workout chat; assistant messages may include a pill-shaped source-citation link ("📄 source: …", `#a3e4d7`, radius 999px). Bottom-pinned text input + send button, identical to workout chat.

## Interactions & Behavior
- **Tab switching**: Plan / Log / Coach are mutually exclusive top-level views; switching tabs does not reset each tab's internal navigation state (drill-in, chat, proposal screens persist if you tab away and back, per current prototype state model — confirm desired behavior with product before building, as most apps would reset nested state on tab re-entry).
- **Stat drill-in navigation**: tapping a stat card or the `(i)` glyph pushes a sub-screen with a back link; back returns to Workout Detail.
- **"Ask coach to explain further"** on the decoupling drill-in jumps to the Coach tab and seeds it with a canned Q&A pair.
- **Chat send**: typing in either chat's input and tapping the send button (or presumably Enter) appends the user's message as an outgoing bubble, then appends a canned assistant reply. Input clears after send. Empty input is a no-op.
- **Plan adapt loop**: Today (original) → "Discuss" → chat screen → "View adjusted session" → Proposal screen (diff view) → **Accept** (writes the adjusted plan as the new Today state, shows Accepted confirmation) / **Discuss** (back to chat) / **Cancel** (back to original Today, discarding the proposal).
- No loading or error states are modeled in this pass — assume instant responses for now; flag to product whether real coach responses need a loading/typing indicator.

## State Management
Reference shape (see prototype's `Component` class for exact implementation):
- `tab`: `'plan' | 'log' | 'coach'`
- `logScreen`: `'detail' | 'drill' | 'explain' | 'chat'`, `drillStat`: `'pace' | 'decoupling' | 'distance'`
- `planScreen`: `'today' | 'chat' | 'proposal' | 'accepted'`, `planStatus`: `'original' | 'adjusted'`
- `workoutChatMessages` / `coachChatMessages`: arrays of `{ align, text }` (rendered as chat bubbles), plus per-chat draft input strings
- Static reference data in the prototype (`splits`, `laps`, `pauses`) is placeholder — replace with real workout data from whatever source (watch sync, GPS) the app already integrates.

## Design Tokens

**Colors**
- Background (screen): `#0f3138` (Redesign) / `#14181f` (Prototype shell — pick one; Redesign's is the intended final dark-mode bg)
- Card surface: `#123f4a` (Redesign) / `#1c2530` (Prototype) + border `#1c525d` / `#2a3542`
- Divider: `#1a4550` / `#242f3a`
- Primary text: `#eef7f8`
- Secondary/muted text: `#7fa8b0`, dimmer `#6d95a0`
- Teal accent (primary CTA, pace, active tab): `#45afc6`
- Mint accent (secondary highlight): `#a3e4d7`
- Orange accent (HR/attention values): `#f49342`
- 3-stop brand gradient: `linear-gradient(135deg, #45afc6, #a3e4d7, #f49342)` — used for avatars, gradient labels, checkmark badge
- Outgoing chat bubble: `linear-gradient(120deg, #1c4a52, #123f4a)`
- Deep border (device chrome): `#082329`

**Typography**
- Display/headings/labels: **Manrope** (700/800 weight)
- Body/UI text: **Inter** (400–700 weight)
- Scale in use: 22px (screen titles) / 19–20px (card values, drill titles) / 13–15px (body/buttons) / 10–12.5px (labels, captions)
- Uppercase labels consistently use `letter-spacing: .06em–.08em`

**Radii**: 999px (pills), 16px (chat bubbles, large cards), 14px (cards), 12px (buttons, inputs), 10px (small rows)

**Shadows**: device frame only — `0 30px 60px rgba(10,10,20,.35)` (not applicable inside a real app shell)

## Assets
- `assets/dragonfly-icon-teal.png` — app icon artwork (cream `#f5fbfa` figure on teal `#45afc6` bg), derived from a user-provided dragonfly-swimmer illustration, recolored to match the app's accent palette. Export at whatever platform icon sizes are required (this reference shows 512/80/36px).

## Notes for the developer
- Two visual passes exist (Prototype vs. Redesign) with slightly different neutral bases (`#14181f` vs `#0f3138`/`#123f4a`) — treat Redesign's palette as the intended final one; the Prototype's job is to nail the interaction model.
- Fonts are loaded from Google Fonts in the reference files; use the app's existing font-loading approach.
- All colors above are literal hex values pulled directly from the reference files — use them as-is rather than re-deriving from a different palette.
