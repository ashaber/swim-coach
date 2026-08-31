# Shoulder health and load: injury risk, rehab phases, and swim-training adaptation

Extends `07-strength-dryland.md`'s injury-*prevention* rotator-cuff/
scapular-stabilizer program with the injury-*recovery* side: how shoulder
load relates to injury risk generally, what a real rehab progression looks
like, what adjunct modalities (massage, TENS) are and aren't evidenced to
do, and how to adapt swim training around a shoulder issue. Triggered by a
real acute shoulder injury (overhead-lifting mechanism) this session;
generalized here for any future shoulder-load question, not written as a
one-athlete note. See `00-conventions.md` for the tagging scheme and
`reference_list.md` for full citations.

## Shoulder load and injury risk: total load, not just strength load

`07-strength-dryland.md`'s "Watch total load, not just strength load, when
ramping" section already covers this engine's one shoulder-specific ACWR
citation (Feijen et al. 2021, OR~4.31, `[EVIDENCE: swim]` Confidence: low
(caveat-heavy) — youth cohort, marginal CI, ACWR methodology broadly
criticized) — not re-derived here. The practical takeaway that section
already states is the load-bearing one: when pool volume, the long-swim
ladder, and strength sessions all ramp together, shoulder load is a
whole-week question, not a strength-session-only one.

**This file's addition:** `07`'s "Cut weeks: strength is the first thing
sacrificed" section documents `adapt.py` converting the week's last
strength session to recovery under load — an honest tradeoff for
*prevention* work. **A REHAB-prescribed session is categorically
different**, and this distinction doesn't yet exist anywhere in this
engine: skipping a prevention exercise loses prevention value; skipping a
physio-prescribed rehab exercise during a cut week leaves a diagnosed
injury under-treated at precisely the moment total load (and therefore
re-injury risk) is elevated. **Coach judgment:** until this engine can
distinguish "strength session, prevention" from "strength session,
active rehab prescription," a human (coach or athlete) should manually
protect any rehab-prescribed session from `adapt.py`'s automatic cut-week
substitution rather than trust the automatic rule here.

## Rehab phases: criteria-based, not calendar-based

**[ADAPTED: general-endurance] Confidence: medium.** Desmeules et al.
(2025), "Rotator Cuff Tendinopathy Diagnosis, Nonsurgical Medical Care, and
Rehabilitation: A Clinical Practice Guideline" (*Journal of Orthopaedic &
Sports Physical Therapy*, 55(4):235-274), the current clinical-practice-
guideline anchor in this space (builds on the 2022 JOSPT rotator cuff
disorders CPG). Verified by direct web search this session (full
bibliographic record confirmed via Europe PMC after the publisher page
403'd automated fetch); full text is paywalled, so no specific graded
recommendation is quoted here — only the guideline's existence and scope.
**Test:** if a future rehab-adjacent build wants to cite a specific graded
recommendation from this CPG, get the full text first rather than inferring
it from the abstract/scope alone.

The generic three-phase shape nearly every shoulder-rehab pathway uses,
**Coach judgment** (practitioner convention informed by the guideline
above, not itself a single-source protocol — phase transitions are
criteria-based, not day-count-based):

1. **Acute / symptom modulation** — pain-free passive/active-assisted
   range of motion, scapular setting, relative rest from provoking
   positions. Goal: settle irritability, prevent stiffness.
2. **Subacute / progressive loading** — restore full range, progressive
   resisted rotator-cuff/scapular work. This is where `07`'s already-cited
   exercise vocabulary (internal/external rotation, scapular retraction/Ts,
   retraction-with-upward-rotation/Ys, low rows) becomes applicable to
   *rehab*, not just prevention — same exercises, different entry point and
   dose, set by symptom response rather than a fixed program.
3. **Return to sport / swim-specific loading** — endurance and
   higher-velocity work in swim-relevant positions, then graded stroke-
   volume reintroduction (see RTP criteria below).

**A common assumption worth correcting:** pain-guided isometrics are widely
used in practice as an early analgesic tool, but the evidence for that
specific claim is weaker than the practice suggests. A 2020 systematic
review/meta-analysis of RCTs on isometric exercise in tendinopathy found
isometrics were not superior to isotonic exercise for pain (with only one
rotator-cuff study included, comparing isometrics to cryotherapy); a 2026
review of 13 RCTs found significant pain reduction in only 3. **[ADAPTED:
general-endurance] Confidence: low.** Both verified by direct web search
this session (PubMed/PMC records). **Test:** don't treat "isometrics reduce
pain" as an established claim in future coaching output — it's a popular
practice with a mixed evidence record.

## Adjunct modalities: what they do and don't do

**Massage/manual therapy — [ADAPTED: general-endurance] Confidence:
low-medium**, genuinely conflicting evidence, verified by direct web search
this session:
- The higher-quality signal is negative: Page et al. (2016), "Manual
  therapy and exercise for rotator cuff disease" (*Cochrane Database of
  Systematic Reviews*, Issue 6, CD012224) — the one placebo-controlled
  trial in 60 pooled trials found no clinically meaningful pain/function
  difference vs. placebo, with *more* adverse events (mild, short-lived
  pain) in the treatment group.
- The lower-quality signal is positive: Yeun (2017) ×2, *Journal of
  Physical Therapy Science* 29(5):936-940 and 29(2):365-369 — pooled small
  studies (15/635 and 7/237 participants), mostly active/no-treatment
  comparators, found short-term pain reduction (SMD -1.08) and ROM gains.
- **Reconciled:** a placebo-controlled null result alongside small
  non-placebo-controlled positive pooled studies is the classic signature
  of a non-specific/placebo effect — real for the person experiencing it,
  not evidence of structural treatment. **What it's reasonably evidenced to
  do:** short-term perceived-pain reduction, short-term ROM improvement,
  reduced protective guarding. **What it doesn't do:** heal a torn/strained
  tendon or accelerate tissue repair — no evidence base for structural
  change. **Test:** if massage is ever recommended by this system, frame it
  as short-term symptom management, never as accelerating healing.

**TENS — [ADAPTED: general-endurance] Confidence: low-medium**, also
genuinely conflicting, verified by direct web search this session:
- Shoulder-specific: Page et al. (2016), "Electrotherapy modalities for
  rotator cuff disease" (*Cochrane*, Issue 6, CD012225, 47 RCTs/2,388
  participants) — "we are uncertain whether TENS is superior to placebo."
- Pain-agnostic, broader: Johnson et al. (2022), the meta-TENS study
  (*BMJ Open* 12(2):e051073, 381 RCTs/24,532 participants) — moderate-
  certainty evidence pain is lower during/immediately after TENS vs.
  placebo (SMD -0.96).
- **Reconciled:** TENS plausibly provides short-acting analgesia while
  active and shortly after; rotator-cuff-specific evidence doesn't
  establish a benefit beyond that. **Does not** heal tissue, accelerate
  repair, or strengthen anything. **The real risk with an athlete still in
  a training block is masking**, not the device itself: analgesia can let
  an athlete load a structure that shouldn't be loaded yet — if used, it
  should be for comfort at rest, not to make training feel tolerable.
  **Test:** if TENS use is ever discussed by this system, pair it with the
  masking caveat above every time, not just the analgesia claim alone.
- **A device-class distinction worth remembering generally:** consumer
  "e-stim" devices are often combination units offering both TENS (pain
  modulation, passive) and EMS/electrical muscle stimulation (active
  muscle contraction) modes — these are different interventions with
  different risk profiles on an injured shoulder (EMS involuntarily loads
  the tissue; TENS doesn't). **Coach judgment:** don't assume a named
  consumer device is TENS-only; the specific product's actual modes matter
  before recommending its use around an active shoulder issue.

## Return-to-swimming: criteria, and volume ramp-back

**[ADAPTED: general-endurance] Confidence: medium.** Wilk, Bagwell, Davies
& Arrigo (2020), "Return to Sport Participation Criteria Following Shoulder
Injury: A Clinical Commentary" (*International Journal of Sports Physical
Therapy*, 15(4):624-642). Verified by direct web search this session (full
record via Europe PMC). Core argument: return-to-sport is a **sequential,
criterion-based process**, and overhead athletes (microtrauma pattern, e.g.
swimmers) need different testing than macrotraumatic shoulder injuries —
open-chain testing, internal/external rotation strength in the upper
ranges of elevation. Recurring criteria across sources: full pain-free
active ROM; strength symmetry vs. the uninjured side (commonly cited
~80-90% limb symmetry index, though the exact figure varies by source);
sport-specific endurance/power, not just single-rep strength (especially
relevant for an ultra-distance swimmer, where the failure mode under
fatigue is technique breakdown, not a single maximal effort); progressive
graded exposure to sport-specific loading completed without a symptom
flare; psychological readiness under full demand.

**Swim-specific adaptation, Coach judgment (practitioner convention, not a
cited protocol)** — the weakest-evidenced of this file's sections, stated
plainly as such:
- **Pain ceiling as a stop rule during return:** if pain during a set
  exceeds roughly 4/10, modify (stroke change, kick-only, add fins); stop
  entirely if it persists at that level. The threshold itself is
  convention, not a validated number.
- **Graded volume re-entry** broadly matches this engine's own existing
  `WEEKLY_VOLUME_RAMP_CAP` (+8%/week) philosophy already in
  `03-periodization.md` — a practitioner heuristic (restart meaningfully
  below normal volume, e.g. 25-50% depending on time off, then build) lines
  up directionally with, but is not derived from, that existing safety
  rail. **Test:** if a shoulder-return week's volume ramp is ever
  automated, don't let it exceed the existing +8%/week cap regardless of
  how aggressive practitioner convention for return-to-swim volume looks in
  isolation.
- **Position matters more than stroke label:** a kickboard held with arms
  extended overhead sustains a loaded, flexed shoulder position and is
  often the wrong choice for an irritable shoulder even though "just
  kicking" sounds conservative; kicking on the back/side, or with a
  snorkel and arms at the sides, is generally better tolerated. Backstroke
  still loads the shoulder at end-range; breaststroke arms are generally
  lowest-demand — but any position that reproduces pain is off the list
  regardless of what the stroke is "supposed" to spare.
- **Paddles/resistance tools: sensible precaution, not clean evidence.**
  Practitioner convention is unambiguous (avoid on an injured shoulder),
  but the published literature on hand-paddle use and shoulder pain is
  genuinely mixed. Avoid them during return because the downside of
  skipping is near-zero, not because of a clean causal finding.

## What this file does not cover

Acute first-24-hours self-care, red-flag/urgent-referral criteria, and a
specific diagnosis-to-treatment decision framework — that content is
genuinely time-bound and situational (tied to one real injury event and
one real appointment), not durable engine-grounding material, and lives
outside this library. This file covers only what generalizes: the
load/injury-risk relationship, rehab-phase structure, adjunct-modality
evidence, and swim-training-adaptation conventions that apply to any future
shoulder-load question this system encounters.
