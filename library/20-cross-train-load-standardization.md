# Cross-train load standardization (no-RPE/no-HR case): investigated, no rigorous standard found

Answers a specific question raised while building `engine/swim_coach/load.py`'s
tiered `session_load` fallback (`15-tiered-session-load.md`): tier 4
(`DURATION_ONLY_ASSUMED_INTENSITY`) assumes the same flat intensity for a
cross-train workout (kayak, mountain bike, walk, generic gym session, etc.)
regardless of activity type, whenever that workout has neither an RPE nor
usable HR data. Could that constant be split per activity type instead,
grounded in real evidence? See `00-conventions.md` for the tagging scheme
and `reference_list.md` for full citations.

## The question this investigates

Not "is session-RPE/TRIMP valid for cycling/running/paddling" -- that is
already well-established and is not the gap (see `15-tiered-session-load.md`'s
own tier-2 citations). The narrower, harder question: **when a cross-train
workout has *neither* a subjective RPE *nor* HR telemetry at all, does any
rigorous, peer-reviewed, or widely-adopted industry standard exist for
assuming a different fixed intensity value per activity type** (e.g. "assume
kayaking defaults to CR-10 6, walking defaults to CR-10 3") to replace the
current uniform constant?

## Verdict

**No.** Checked from three independent, convergent angles -- sport-science
literature, the closest real analog found in that literature, and how real
commercial training-load platforms actually handle this exact gap. All three
point the same direction: nobody has solved, or even directly attempted,
the zero-signal per-modality default problem. This is an honest negative
result, not a placeholder for a number nobody wrote down yet -- forcing a
number here would repeat this project's own past mistake of Gemini-fabricated
research precision (`reference_list.md`'s header).

### Angle 1: the validity literature only ever addresses the has-at-least-one-signal case

Session-RPE and TRIMP validity/reliability research -- across running,
cycling, team sports, and swimming -- consistently assumes at least one real
signal (a subjective RPE rating, or HR telemetry) is present to validate
against something else (a criterion measure, or each other). None of it asks
what to assume when *both* are absent. **[ADAPTED: general-endurance/multi-sport]
Confidence: medium.** Sources: **Foster C, Florhaug JA, Franklin J, et al.
(2001)**, "A New Approach to Monitoring Exercise Training," *J Strength Cond
Res*, 15(1):109-115 -- the original sRPE paper itself defines the method as
`duration * RPE`, i.e. it requires an RPE to exist; **Impellizzeri FM,
Rampinini E, Coutts AJ, Sassi A, Marcora SM (2003)**, "Validity of the
session-RPE method for determining training load in team sport athletes,"
*J Sci Med Sport*, 6(4):525 -- validates sRPE against HR-based measures in
soccer players, again assuming both signals are collected; **Haddad M,
Stylianides G, Djaoui L, Dellal A, Chamari K (2017)**, "Session-RPE Method
for Training Load Monitoring: Validity, Ecological Usefulness, and
Influencing Factors," *Frontiers in Neuroscience*, 11:612 (already cited in
`reference_list.md`'s "Injury & training load" section for its reliability
findings) -- a review of the sRPE literature, silent on the zero-signal case
throughout; **Borges TO, Bullock N, Duff C, Coutts AJ (2014)**, "Methods for
Quantifying Training in Sprint Kayak," *J Strength Cond Res*, 28(2):474-482 --
the one paddling-specific paper found, confirms sRPE/TRIMP validity for
kayak training when actually collected, with no assumed-default guidance for
when it isn't. **Test:** if any future sRPE/TRIMP validity study explicitly
tests a zero-signal substitution case for any modality (running, cycling,
paddling, or otherwise), revisit this section and reconsider building a
per-modality constant table.

### Angle 2: the closest real analog is missing-RPE imputation research, and it argues against a fixed constant

The nearest thing in the literature to "what value do you assume when a
subjective load signal is simply missing" is missing-RPE *imputation*
research in rugby -- a genuinely adjacent problem, not a hypothetical one.
**[ADAPTED: general-endurance/multi-sport] Confidence: medium.** **Epp-Stobbe
A, Tsai M-C, Klimstra M (2022)**, "Comparison of Imputation Methods for
Missing Rate of Perceived Exertion Data in Rugby," *Machine Learning and
Knowledge Extraction*, 4(4):41, tested several imputation methods against
real rugby RPE data and found that simple fixed-value substitution -- team-mean
substitution, the closest real-world approach to a flat constant -- was the
**least accurate** method tested; individualized models built on each
athlete's own historical data won instead. **Epp-Stobbe A, Tsai M-C, Klimstra
M (2025)**, "Rugby Sevens sRPE Workload Imputation Using Objective Models of
Measurement," *Applied Sciences*, 15(12):6520, is the follow-up and still
requires objective sensor data as model input -- it doesn't solve, or even
address, the zero-data case this project has. Critically, this doesn't just
fail to support a fixed per-modality constant -- it is mild evidence
*against* one: the paper's own best-performing alternative (a personalized
history-based model) has no fitted history to draw on for a brand-new
modality with zero prior signal, which is exactly this project's situation
for a first-ever kayak or mountain-bike session. **Test:** if an athlete logs
enough dual-signal cross-train sessions (RPE recorded alongside HR/pace) for
one specific `sport_detail` that an individualized historical model becomes
fittable -- Epp-Stobbe's own more-accurate approach -- revisit whether a
per-athlete calibrated multiplier is worth building for that modality
specifically. That is a different, and better-supported, direction than a
flat per-modality constant copied from the rugby literature.

### Angle 3: real commercial platforms don't define a per-activity default for this case either

If a per-modality assumed-intensity convention existed anywhere close to
industry-standard, the two most relevant commercial training-load platforms
would be the place to find it. Neither does. **[ADAPTED:
general-endurance/multi-sport] Confidence: medium-high** (a direct
confirmation of what a specific vendor's documentation does and doesn't say
is lower-inference than a cross-discipline research adaptation, but it is
still vendor documentation, not peer-reviewed evidence). TrainingPeaks' own
Training Stress Score documentation -- the same practitioner source already
cited in `15-tiered-session-load.md` and `reference_list.md`'s "Practical /
non-journal resources" section for the swim-specific cubed-IF adaptation --
was checked directly for this question too, and confirms their methodology
requires at least one of power, pace, HR, or RPE to compute a TSS value at
all; no fallback is defined for the all-missing case. Garmin/Firstbeat's
EPOC-based Training Load documentation and technical write-ups were also
checked directly (industry-practice tier, weaker rigor than the peer-reviewed
sources above; no specific URL retained here per this project's zero-
fabricated-citation discipline -- see `reference_list.md`'s header) and
confirm their system **degrades or omits** the load estimate rather than
substituting a per-activity assumed value when HR is absent. Both platforms
made the same choice this project already made independently: when the real
signal isn't there, don't guess a modality-specific number -- either
compute a real number (this project's uniform-fallback approach: give
*something* rather than silently excluding the workout, per
`15-tiered-session-load.md`'s design principle) or openly decline to
estimate (their approach). Neither chose "assume kayaking is harder than
walking by some specific fixed factor." **Test:** if TrainingPeaks or
Garmin/Firstbeat ever publish a defined all-missing-data fallback
methodology instead of degrading/omitting the estimate, revisit this
section -- their current choice to omit rather than guess is itself
informative evidence about the state of industry consensus on this exact
gap, and a reversal would be worth noticing.

### A candidate ruled out: MET-based activity tables

The most obvious-looking off-the-shelf answer -- "just use a standard MET
(metabolic equivalent) value per activity type, there's a huge published
table of those" -- was considered and rejected. **[ADAPTED:
general-endurance/multi-sport] Confidence: high** (this is a definitional
mismatch, not a contested empirical question). **Ainsworth BE, Haskell WL,
Herrmann SD, et al. (2011)**, "2011 Compendium of Physical Activities," *Med
Sci Sports Exerc*, 43(8):1575-1581, is real and authoritative for what it
measures, but what it measures is not what this project needs: METs are the
*absolute energy cost* of an activity performed at a *specified* pace/
intensity, not a *relative perceived-intensity* rating for an
unspecified-pace generic session. No validated MET-to-RPE conversion exists
for "someone did an unspecified amount of kayaking for 45 minutes, how hard
did that feel" -- MET tables answer a different question (energy
expenditure at a given, known pace) than the one tier 4 needs (assumed
perceived intensity for a session logged with no pace, HR, or RPE at all).
**Test:** if a validated MET-to-RPE conversion for an unspecified/generic
session is published, revisit whether the Compendium could ground a
per-modality constant after all.

## Decision

**Coach judgment:** the uniform `DURATION_ONLY_ASSUMED_INTENSITY` fallback
constant in `engine/swim_coach/load.py` stays as-is, undifferentiated by
`Workout.sport_detail`. This is a deliberate, documented simplification, not
an oversight discovered and left unfixed -- the alternative (a per-modality
constant table) was actively investigated and found unsupported by rigorous
evidence from every angle checked above, and the closest real analog
(missing-RPE imputation research) suggests a fixed-constant approach would
likely be *less* accurate than what it would replace, not more. No code
change follows from this research pass; see `15-tiered-session-load.md`'s
"Known limitation" section for where this conclusion is recorded against
the constant it grounds.
