# Oura Ring Research Dossier — device trust for HRV/sleep/RHR/readiness

> **Provenance note:** this is the raw research input used to author the
> "Oura device trust" section and the amended HRV-guided-load confidence
> rating in `library/10-recovery-hrv.md`. It is **not itself a citable
> library file** — for grounding claims, cite `library/reference_list.md`
> and `library/10-recovery-hrv.md` directly, not this dossier.

Research input for a future edit to `library/10-recovery-hrv.md`. Andrew's
profile lists `hrv_source: Oura ring` (the athlete, referred to as "Renee" in
the existing library file, wears one). This dossier does NOT edit the repo —
it is a citation-verified input for a later, human-scheduled library pass.

**Verification legend** (matches `library/reference_list.md`):
- ✓ — paper verified real by title/author/journal search (and in most cases,
  full text fetched directly from PMC or the publisher).
- ~ — author/venue plausible but this specific paper not individually
  verified; not used below except where explicitly flagged.
- ⚠ — caveat attached (conflict of interest, superseded hardware, small n,
  or a stat I could not independently confirm); read the note before citing.

---

## 1. Executive summary

**Bottom line, per signal:**

- **(a) HRV trend (nightly rMSSD):** Reasonably trustworthy as a **relative,
  night-over-night trend on this athlete's own device**, at **medium-high**
  confidence. Two independent academic validation studies (Cao et al. 2022,
  n=35; Liang et al. 2024, n=114) found strong correlation with chest ECG for
  *night-averaged* HR and rMSSD (r ≈ 0.92–0.99). The catch: accuracy is
  materially worse in noisy/short windows and in older adults, and a data-
  quality filter that keeps accuracy high also silently drops ~30–35% of
  nights. Treat single-night dips cautiously; trust multi-night trends more
  than any one number.
- **(b) Sleep staging:** **Medium** confidence for total sleep time (TST)
  and time-awake, **low-medium** for stage-by-stage detail (light/deep/REM).
  The only study with full independently-confirmed numbers (de Zambotti et
  al. 2017) found deep sleep significantly *underestimated* and REM
  significantly *overestimated* — but that study used the **first-generation
  ring**, not current hardware. A newer, larger Gen3 study (Svensson et al.
  2024) reports "good agreement," but I could not independently pull its
  exact numbers (paywalled) — see caveat below.
- **(c) Resting heart rate (RHR):** **High** confidence. This is the
  best-validated signal — near-1.0 correlation with ECG across every study
  found, and the one small independent multi-device comparison (Dial et al.
  2025) found Oura the *most* accurate RHR tracker among the wearables it
  tested (better than WHOOP, Garmin, Polar).
- **(d) The composite "Readiness" score:** **Low** confidence as a
  driver of plan changes. No independent peer-reviewed validation of Oura's
  Readiness score as a predictive/clinical measure exists in what I found. A
  2025 comparative review across 10 wearable brands found none of the
  manufacturers — Oura included — publish their exact scoring formula/
  weights, and none of the reviewed composite scores had independent
  peer-reviewed validation. Readiness is a proprietary blend, not a
  validated construct; the engine/coach should read the *raw* HRV/RHR/sleep
  trend, not the 0–100 score, if either is to drive a plan decision.

**Single biggest caveat, overall:** the existing library file's HRV-guided-
training citations (Kiviniemi 2007, Vesterinen 2016, Javaloyes 2020) were
**all** measured via a **morning, post-waking, supine/standing orthostatic
protocol** — not the **overnight** measurement Oura reports. A newer study
(Nuuttila et al. 2024) directly compared morning-vs-nocturnal HRV response
to a training-load increase in the same runners and found the two
**diverge in their response to training**, despite correlating at baseline.
This doesn't mean Oura's overnight number is worse — in that one study,
nocturnal HRV actually tracked training-load changes and subsequent
performance *better* than the morning protocol — but it does mean the
specific thresholds/mechanics from those three RCTs (e.g., "1 SD below a
rolling baseline") were never validated on overnight data, and shouldn't be
imported into an engine rule as if they were.

**Verified-vs-dropped counts by topic:**

| Topic | Verified (✓) | Verified-with-caveat (✓⚠) | Dropped/unverifiable |
|---|---|---|---|
| 1. HRV validity vs ECG | 2 | 1 (Kinnunen 2020 — employee-authored, stats not independently confirmed) | 0 |
| 2. Sleep staging & RHR | 2 | 0 | 0 |
| 3. Temperature / respiratory rate | 1 | 0 | 1 (manufacturer blog claims, not treated as research) |
| 4. HRV-guided-training protocol mismatch | 1 new + 3 already in library confirmed as morning-protocol | 0 | 0 |
| 5. Menstrual cycle | 2 | 1 (Thigpen/Patel/Zhang 2025 — all 3 authors are Oura employees) | 0 |
| 6. Limitations / readiness score | 1 (composite-score review) | 0 | 1 (Marco Altini substack commentary — real person, not a citable primary source) |

---

## 2. Verified sources, by topic

### Topic 1 — Oura HRV validity vs. ECG

- **✓ Cao R., Azimi I., Sarhaddi F., Niela-Vilén H., Axelin A., Liljeberg
  P., Rahmani A.M. (2022)** — "Accuracy Assessment of Oura Ring Nocturnal
  Heart Rate and Heart Rate Variability in Comparison With
  Electrocardiography in Time and Frequency Domains: Comprehensive
  Analysis" — *Journal of Medical Internet Research*, 24(1):e27487.
  **Verification:** full text fetched directly (PMC). Authors are at
  University of Turku (Finland) and UC Irvine — no Oura employee among the
  author list found; appears independently funded/conducted. **Summary:**
  35 healthy adults (19F/16M, mean age 32.3), one home overnight recording
  each (~8.25h), against a Shimmer3 chest ECG reference. In 5-minute
  windows: HR correlation r=0.993 (bias −0.44 bpm), rMSSD correlation
  r=0.915 (bias −14.97 ms, wide 95% CI −44 to +14 ms). At the
  **whole-night-average** level (the more relevant unit for daily
  readiness-style use), HR and rMSSD correlations both "approached 1.0" and
  other HRV metrics (SDNN, AVNN, pNN50, LF, HF) stayed above 0.82;
  frequency-domain measures (LF, HF, LF:HF) were noted by the authors as
  most noise-sensitive. **Limitation the authors state themselves:**
  single-night, healthy-adults-only sample — "lacks generalizability... to
  nonhealthy individuals." **Proposed tag:** device validity, general
  healthy-adult population, independent academic. **Informs:** the engine/
  coach should read Oura's **nightly-average** rMSSD, not any intraday or
  5-minute figure, as the trustworthy unit; this is the strongest single
  citation for "an HRV dip flagged by Oura is probably a real
  physiological signal, not device noise" — provided it persists as a
  multi-night trend rather than one night.

- **✓⚠ Kinnunen H., Rantanen A., Kenttä T., Koskimäki H. (2020)** —
  "Feasible assessment of recovery and cardiovascular health: accuracy of
  nocturnal HR and HRV assessed via ring PPG in comparison to medical grade
  ECG" — *Physiological Measurement*, 41:04NT01. **Verification:** title/
  authors/journal corroborated across IOPscience, ResearchGate, and
  independent secondary listings — the paper is real. Full text was
  **paywalled (403)**, so I could not independently confirm the specific
  effect sizes; some web summaries attribute r²=0.996 (HR) / r²=0.980
  (HRV) to this paper, but since I never read the primary text myself,
  **I am not recording those numbers as confirmed** — flagging this
  explicitly per this repo's fabrication history. **Conflict of interest:**
  Hannu Kinnunen was Oura's Chief Scientific Officer (2014–2021) at the
  time of publication — this is **manufacturer-affiliated** validation
  research, a materially different trust tier than Cao et al. above.
  **Proposed tag:** device validity, manufacturer-affiliated — cite as
  corroborating-but-lower-weight, and do not cite specific numbers from it
  without a follow-up full-text read.

- **✓ Liang T., Yilmaz G., Soon C.-S. (2024)** — "Deriving Accurate
  Nocturnal Heart Rate, rMSSD and Frequency HRV from the Oura Ring" —
  *Sensors*, 24(23):7475. **Verification:** full text fetched directly
  (PMC). **Summary:** 114 participants (Oura Ring **Generation 3**),
  SOMNOtouch ECG reference, in-lab sleep studies, split into younger
  (20–44y, n=92) and older (45–68y, n=22) groups. At an 80% data-quality
  threshold: HR r=0.992–0.994 (both age groups); rMSSD r=0.979 (younger)
  vs. 0.937 (older); rMSSD bias +2.5 to +3.8 ms. **Key caveat:** more than
  half of *older* participants had HRV Median Absolute Percentage Error
  >10% at the 5-minute level (younger participants mostly stayed under
  that threshold); accuracy substantially improves once you aggregate to
  30-minute or full-night windows regardless of age. Applying the
  strictest (80%) data-quality filter rejected **~30–35% of nights**
  outright. **Proposed tag:** device validity, age-stratified, current
  hardware generation. **Informs:** if Renee's Oura app ever flags a night
  as low signal quality, that night's number should be discounted rather
  than treated as a real physiological reading; age-related accuracy
  degradation is a real, quantified effect in this literature (relevant if
  her age is on the older side of "recreational endurance athlete").

- **✓ Dial M.B., Hollander M.E., Vatne E.A., Emerson A.M., Edwards N.A.,
  Hagen J.A. (2025)** — "Validation of nocturnal resting heart rate and
  heart rate variability in consumer wearables" — *Physiological Reports*,
  13(16):e70527. **Verification:** full text fetched directly (PMC).
  **Summary:** small but multi-night (13 healthy adults, 536 nights total)
  head-to-head comparison of Oura Gen3, Oura Gen4, Polar Grit X Pro, Garmin
  Fenix 6, and WHOOP 4.0 against a Polar H10 chest-strap ECG reference.
  Oura Gen3/Gen4 were the **best-performing devices of the five tested**
  for both RHR (CCC 0.97–0.98, MAPE 1.67–1.94%) and HRV (CCC 0.97–0.99,
  MAPE 5.96–7.15%) — ahead of WHOOP, and well ahead of Garmin/Polar watches
  in this comparison. **Proposed tag:** device validity, independent,
  comparative (n=13 is small, but this is the only source found that
  benchmarks Oura against its direct competitors on the same nights).
  **Informs:** modest additional confidence that, *among wearables*, Oura
  specifically is not an outlier-bad choice for this athlete's HRV/RHR
  signal.

### Topic 2 — Oura sleep staging and RHR accuracy vs. PSG/ECG

- **✓⚠ de Zambotti M., Rosas L., Colrain I.M., Baker F.C. (2017)** —
  "The Sleep of the Ring: Comparison of the ŌURA Sleep Tracker Against
  Polysomnography" — *Behavioral Sleep Medicine*, 17(2):124–136.
  **Verification:** full text fetched directly (PMC). Independent
  (SRI International / SRI Biosciences / Stanford-affiliated group), not
  Oura-employee-authored. **Summary:** 41 healthy adolescents/young adults
  (13–22y), single in-lab PSG night, **first-generation Oura ring**. Total
  sleep time bias −1.3±21.7 min (87.8% of nights within a ±30 min
  "clinically satisfactory" band); wake-after-sleep-onset not significantly
  different on average but noisier when WASO was high. **Deep sleep (N3)
  was significantly underestimated** by ~20 min (p=.004); **REM was
  significantly overestimated** by ~17 min (p=.034). Epoch-by-epoch:
  sensitivity to detect sleep 96%, but specificity to detect wake only 48%
  (i.e., the ring is much better at confirming "asleep" than "awake").
  **Major caveat: this is the original 2016–17-era ring**, not current
  Gen3/Gen4 hardware or algorithms — findings on stage-by-stage accuracy
  should not be assumed to transfer unchanged to whatever generation Renee
  actually wears. **Proposed tag:** device validity, sleep-staging,
  superseded hardware generation.

- **✓⚠ Svensson T., Madhawa K., NT H., Chung U., Kishi Svensson A.
  (2024)** — "Validity and reliability of the Oura Ring Generation 3
  (Gen3) with Oura sleep staging algorithm 2.0 (OSSA 2.0) when compared to
  multi-night ambulatory polysomnography: A validation study of 96
  participants and 421,045 epochs" — *Sleep Medicine* (2024). **Verification:**
  title/authors/journal corroborated across the Lund University research
  portal, ScienceDirect, and ResearchGate — additionally, a published
  "Comment on..." and the authors' "Response to comment on..." both exist
  for this paper, which is strong secondary confirmation the study is real
  and drew scientific scrutiny. Full text was paywalled (403), so I
  could **not** independently confirm the exact accuracy/kappa figures —
  secondary sources describe "good agreement with PSG for global sleep
  measures and time spent in light and deep sleep," which I'm recording
  as a qualitative characterization only, not a verified number.
  **Design strengths over de Zambotti 2017:** current-generation ring
  + current algorithm (OSSA 2.0), multi-night ambulatory (not single-
  lab-night) PSG, larger and more age-diverse sample (96 adults, ages
  20–70). **Proposed tag:** device validity, sleep-staging, current
  generation — the more relevant citation for Renee's actual device, but
  flag that I could not verify its numbers first-hand; a future pass
  should try to obtain the full text before citing specific figures.

*(RHR accuracy is covered under Topic 1 — Cao et al. 2022 and Dial et al.
2025 both include RHR alongside HRV; no RHR-only study was found or
needed.)*

### Topic 3 — Oura temperature and respiratory rate

- **✓⚠ Maijala A., Kinnunen H., Koskimäki H., Jämsä T., Kangas M.
  (2019)** — "Nocturnal finger skin temperature in menstrual cycle
  tracking: ambulatory pilot study using a wearable Oura ring" — *BMC
  Women's Health*, 19:150. **Verification:** full text fetched directly
  (PMC). **Conflict of interest:** Kinnunen (Oura's CSO at the time) is a
  co-author — manufacturer-affiliated, though published in an independent
  peer-reviewed journal. **Summary:** small pilot (n=22 women), nocturnal
  skin temperature differed between follicular/luteal phases by a mean
  0.30°C, vs. 0.23°C for oral thermometer readings (skin-vs-oral
  correlation r=0.563); the best-performing ovulation-detection algorithm
  variant had ~83% sensitivity within a −3/+2-day fertile window against a
  urine LH-test reference. Authors themselves call this a pilot needing
  larger validation. **Proposed tag:** device validity, temperature-as-
  cycle-signal, small pilot, employee co-authored — see full listing under
  Topic 5 too, since it's really both a temperature-validity and a
  menstrual-cycle paper.

- **Manufacturer-sourced, NOT independent research (flag distinctly, do
  not weight as peer-reviewed evidence):** Oura's own blog posts "How
  Accurate Is Oura's Temperature Data?" and "How Accurate Is Oura's
  Respiratory Rate?" describe in-house validation (skin-temperature vs.
  iButton reference sensors in lab water-bath and free-living conditions;
  respiratory rate vs. an ECG-derived respiratory-sinus-arrhythmia method,
  done in partnership with National University of Singapore / Duke-NUS as
  part of an internal "Need for Sleep Study," n=43). These are Oura's own
  published white-paper-style claims — real, but manufacturer-authored and
  not independently peer-reviewed as far as I could confirm. **No
  independent, peer-reviewed validation of Oura's respiratory-rate metric
  specifically was found** — this is a genuine gap, not just a low-
  confidence finding.

### Topic 4 — HRV-guided-training literature: morning vs. overnight measurement (the protocol-mismatch question)

This is the topic most directly relevant to whether the existing library
file's HRV-guided-training citations transfer cleanly to an Oura user.

- **Confirmed via protocol description (not a new citation, but a
  necessary re-check of what's already in `reference_list.md`):**
  `Kiviniemi et al. (2007)`, `Vesterinen et al. (2016)`, and `Javaloyes et
  al. (2020)` **all used a morning, post-waking, orthostatic (supine and/or
  standing) HRV measurement protocol** — not overnight recording.
  Kiviniemi: measured at home each morning after waking and voiding, hard/
  easy decision keyed to a rolling 10-day baseline (≥1 SD drop, or a
  2-day downward trend, triggered easy/rest). Vesterinen: morning
  measurement, decisions keyed to a 7-day rolling LnRMSSD average.
  Javaloyes: morning-after-waking, supine, 90-second recording (last 60s
  used). **None of the three measured HRV overnight/nocturnally the way
  Oura does.** This confirms, rather than merely assumes, the concern the
  existing `10-recovery-hrv.md` file already flags qualitatively.

- **✓ Nuuttila O.-P., Kyröläinen H., Kokkonen V.-P., Uusitalo A. (2024)**
  — "Morning versus nocturnal heart rate and heart rate variability
  responses to intensified training in recreational runners" — *Sports
  Medicine - Open*, 10:120. **Verification:** full text fetched directly
  (PMC). **Summary:** 24 recreational runners (10F), 3-week baseline + a
  2-week block with training load raised ~80%; compared a **morning
  orthostatic test** (supine/standing, chest strap) against **nocturnal
  PPG-wearable** recording in the *same athletes*. Morning and nocturnal
  HR/LnRMSSD correlated moderately-to-highly at **baseline**, but their
  **responses to the training-load increase diverged**: nocturnal segments
  showed larger, more consistent changes to both the acute (post-time-
  trial) and chronic (2-week overload) stimulus than the morning protocol
  did; and only the **nocturnal** (not morning) HR/HRV correlated with the
  subsequent change in 3000 m performance (r=0.63 for HR, r=−0.50 for
  LnRMSSD). **Proposed tag:** device-protocol-comparison — this is the
  single most load-bearing new citation in this dossier. **Informs:**
  directly answers the dossier's Topic-4 question. It shows the
  morning-vs-overnight distinction is **not a null concern** — the two
  signals genuinely diverge under training stress — but it is *reassuring*
  in one respect: in this study, the overnight-style signal was **at least
  as sensitive**, and possibly more predictive of subsequent performance,
  than the morning-protocol signal the existing citations used. The
  takeaway for the engine/coach isn't "distrust Oura's nightly HRV," it's
  "don't assume Kiviniemi/Vesterinen/Javaloyes's specific numeric
  thresholds (e.g., '1 SD below a 10-day baseline') apply unchanged to an
  overnight number — the *mechanism* (hard day only on stable/rising HRV)
  is plausible, but the *threshold calibration* has not been shown to
  transfer."

### Topic 5 — Menstrual-cycle / female-specific Oura signals

- **✓⚠ Maijala et al. (2019)** — see full entry under Topic 3. Employee
  co-authored (Kinnunen), small pilot (n=22), but a real independent-
  journal publication.

- **✓⚠ Thigpen N., Patel S., Zhang X. (2025)** — "Oura Ring as a Tool for
  Ovulation Detection: Validation Analysis" — *Journal of Medical Internet
  Research*, 27:e60667. **Verification:** full text fetched directly
  (PMC). **Conflict of interest — significant:** all three authors are
  Oura Health employees, and the paper explicitly discloses this. Also
  note the "ground truth" is **self-reported** home LH-test results from
  Oura's own commercial user base, not a lab-confirmed reference standard.
  **Summary:** 1,155 ovulatory cycles from 964 commercial Oura users
  (ages 18–52); the temperature-based physiology algorithm detected 96.4%
  of ovulations with an average error of 1.26 days, vs. 3.44 days for a
  calendar-based method; accuracy was somewhat worse (1.7-day error) in
  unusually long cycles (≥36 days). **Proposed tag:** device validity,
  large commercial-scale sample but industry-authored — treat the
  *direction* (temperature-based detection beats calendar guessing) as
  plausible, and heavily discount the *precision* of the specific accuracy
  percentages given the conflict of interest and self-report reference
  standard.

- **✓ Alzueta E., de Zambotti M., Javitz H., et al. (2022)** — "Tracking
  Sleep, Temperature, Heart Rate, and Daily Symptoms Across the Menstrual
  Cycle with the Oura Ring in Healthy Women" — *International Journal of
  Women's Health*, 14:491–503. **Verification:** full text fetched
  directly (PMC). Independent (de Zambotti group, not Oura employees).
  **Summary:** 26 healthy women, one full cycle each. No significant
  cycle-phase differences in sleep architecture; nocturnal HR rose in
  mid-/late-luteal phase (p=.001); distal skin temperature showed the
  expected biphasic pattern (elevated luteal, a dip around ovulation,
  p=.05); physical symptoms were worse at menses (p<.001). **Authors'
  own limitation:** no blood hormone assay was collected, so this is an
  *observational/descriptive* study, not a diagnostic-accuracy validation
  — they explicitly call the device "promising" and ask for future work
  against gold-standard hormone/PSG references across cycle phases.
  **Proposed tag:** device validity/observational, independent, small n,
  descriptive rather than diagnostic-accuracy.

### Topic 6 — Known limitations, motion/quality artifacts, and the Readiness score

- **✓ Doherty C., Baldwin M., Lambe R., Burke D., Altini M. (2025)** —
  "Readiness, recovery, and strain: an evaluation of composite health
  scores in consumer wearables" — *Translational Exercise Biomedicine*,
  2(2):128–144. **Verification:** title/authors/journal/volume-issue-pages
  corroborated across DOAJ, the publisher (De Gruyter Brill), Semantic
  Scholar, and ResearchGate. **Summary:** systematically reviewed 14
  composite health scores (readiness/recovery/strain-type scores) across
  10 wearable manufacturers, including Oura's Readiness and Resilience
  scores, Garmin's Body Battery/Training Readiness, WHOOP's Recovery/
  Strain, Polar's Nightly Recharge, and others. Found that **none of the
  manufacturers publish their exact scoring formula or metric weights**,
  and — per the search-derived description I could access (I could not
  fetch the publisher's full text directly; this characterization is
  drawn from consistent secondary summaries across three independent
  listings, so I'm marking it ✓ for existence but noting the summary
  itself is once-removed) — that this class of proprietary composite score
  generally **lacks independent peer-reviewed validation**. **Proposed
  tag:** device validity, composite-score-specific, cross-brand review.
  **Informs directly:** the Readiness score should not be treated as a
  validated clinical/training-prescription measure. If the engine or a
  coaching session ever weighs "readiness" numerically, it should be
  built from the raw, individually-validated components (nightly rMSSD,
  RHR, sleep duration) rather than Oura's own blended 0–100 number.

- **Self-noted limitations already present in the Topic-1 papers**
  (not separate citations, but worth stating plainly since they matter for
  engine design): Cao et al. (2022) and Liang et al. (2024) both note,
  in their own discussion sections, that (a) frequency-domain HRV
  parameters are the most noise-sensitive, (b) accuracy degrades in
  shorter windows and in older adults, and (c) a meaningful fraction of
  nights get rejected by strict data-quality filters. None of the
  verified papers in this dossier specifically studied Oura accuracy
  during **alcohol use**, **atrial fibrillation/arrhythmia**, or other
  acute physiological confounds — I looked and did not find a peer-
  reviewed Oura-specific study on either. General PPG-wearable literature
  (not Oura-specific, and not individually verified as a citable paper
  here) consistently reports that PPG-derived HR/HRV degrades during
  motion, poor skin contact, ambient light interference, and irregular
  cardiac rhythms — this is stated as background/discussion-section
  content in the papers above, not as a standalone finding to cite by
  itself.

---

## 3. Rejected / unverifiable sources encountered

- **Oura's own "Independent Study Finds Oura Ring Most Accurate..." blog
  post** — this is Oura's own marketing summary *of* the Dial et al. 2025
  paper (already cited independently above). Don't cite the blog post;
  cite Dial et al. 2025 directly.
- **"An independent analysis found a statistically significant correlation
  between Oura ring temperature deviation and morning oral temperature
  measured by Kinsa QuickCare"** — appeared only in a low-authority
  aggregator summary (wearablexp.com-style site); could not trace to a
  primary academic source. Dropped — do not cite.
- **Marco Altini Substack commentary on data quality / high-HRV-during-
  motion artifacts** — Altini is a legitimate HRV researcher/practitioner
  (co-author on the Doherty et al. 2025 review above), but a Substack post
  is not itself a citable primary research source. The underlying point
  (elevated apparent HRV during motion often reflects artifact, not
  parasympathetic activity) is consistent with what Cao et al. (2022) and
  Liang et al. (2024) say in their own discussion sections — cite those
  instead if this claim is needed.
- **"Oura ring 600,000+ members ... 15.6% mean HRV drop on drinking
  nights"** figure, and the "WHOOP 74% of collegiate athletes had
  suppressed HRV after drinking" figure — both appeared only in secondary/
  aggregator summaries with no traceable primary study. Dropped — treat
  "alcohol lowers Oura-measured HRV" as directionally plausible common
  knowledge, not a citable, verified finding, until a primary source is
  found.
- **Reputable.health, Livity, WearableXP, SimpleWearableReport** and
  similar consumer-review/SEO sites that came up repeatedly describing the
  Readiness score algorithm — none are primary research; used only to
  confirm the *existence* of the Doherty et al. 2025 review, not cited as
  sources themselves.
- **A JMIR mHealth 2020 paper on smart-ring-vs-smartwatch sleep tracking
  against actigraphy** (e20465) surfaced in search but was not pursued —
  actigraphy is a weaker reference standard than PSG and it's redundant
  with the de Zambotti/Svensson PSG-referenced studies already verified
  above.

---

## 4. Proposed integration into `library/10-recovery-hrv.md`

Read (read-only) before this pass: the file currently has one HRV-guided-
load section ("HRV- and wellness-guided load adjustment," lines ~125–160)
that already candidly states the Oura device exists in Renee's profile but
no HRV data is logged yet, and already flags — as a general concern, not
yet citation-backed — that Kiviniemi/Vesterinen/Javaloyes are multi-week
studies in a different population, not validated for the athlete's actual
short-window scenario. It does **not** currently address device-measurement
protocol (morning vs. overnight) or device accuracy at all.

**Recommended changes for the future edit (not made here):**

1. **Add a new "Oura device trust" subsection**, probably right after the
   existing "HRV- and wellness-guided load adjustment" section, covering:
   - Nightly-average rMSSD and RHR are reasonably trustworthy as *trend*
     signals (Cao et al. 2022; Liang et al. 2024; Dial et al. 2025) —
     medium-high confidence — but single-night or short-window numbers are
     noisier and should be discounted, especially on any night the app
     flags low signal quality.
   - Sleep-stage detail (light/deep/REM split) is lower confidence than
     total sleep time; the best available current-generation evidence
     (Svensson et al. 2024) reports good agreement but its exact numbers
     could not be independently verified in this pass — flag as a
     follow-up to re-verify with full-text access before citing precise
     figures.
   - The Readiness score itself (the 0–100 composite) has **no**
     independent peer-reviewed validation found (Doherty et al. 2025) —
     any future engine rule should key off raw HRV/RHR/sleep, never the
     blended score.
   - No Oura-specific validation exists for behavior during alcohol
     use, arrhythmia, or illness — flag this as an open gap, not a
     resolved low-risk.

2. **Amend the existing HRV-guided-load section's Confidence line.** It's
   currently "Confidence: medium" for the Kiviniemi/Vesterinen/Javaloyes
   trio, justified only by "these are multi-week studies in a different
   population, not this athlete's exact short-window scenario." That
   should now **also** cite the **measurement-protocol mismatch** — all
   three used morning orthostatic HRV, not overnight — as a second,
   independent reason for the medium (not high) confidence rating, backed
   by Nuuttila et al. (2024)'s direct finding that morning and nocturnal
   HRV diverge in their response to training load. Suggested added text:
   "these three RCTs measured HRV each morning after waking, not
   overnight; Nuuttila et al. (2024) found morning and nocturnal HRV
   respond differently to a training-load increase in the same athletes,
   so the *mechanism* (hard day only on stable/rising HRV) plausibly
   transfers to an overnight-measuring device like Oura, but the specific
   thresholds calibrated in these studies (e.g., Kiviniemi's '1 SD below a
   10-day rolling baseline') have not been shown to hold for nightly Oura
   data — any engine threshold should be derived from Renee's own overnight
   baseline once data exists, not imported from these numbers directly."

3. **Leave the "what's still a gap" closing section's HRV bullet
   largely as-is** but note it can now cite specific device-accuracy
   evidence rather than reading as a pure unknown — the gap is genuinely
   "no HRV data logged yet," not "we don't know if the device can be
   trusted at all."
