# Bike fit measurement (the geometry method, saddle, and what the fit literature supports)

See `00-conventions.md` for tags and `reference_list.md` for citations. Companion: `45-bike-race-setup.md`.

**Sport scope: `bike`.** **UNREVIEWED**, pending human review. Written for a masters amateur
cyclist (CX bike, full-suspension MTB). **This is a measuring method plus a thin
literature map, not a fit method:** the tool records and compares geometry, gives no target angles,
and the human fitter decides. The existing `save_setup_note` and `get_bike_fit` guidance stays.

## 1. Measuring bike geometry (`Coach judgment:`)

No source covered this method. Tape distances between marked points (BB bolt, front and rear axle
ends, bar clamp BC, saddle tip ST, sit-bone point S, hand point H) are solved by trilateration with
sides fixed from the bike's layout, so nothing depends on the bike being level. H is the midpoint of
a string between the left and right contact points (hood tops or grip centers), so it sits on the
centerline. Ground direction comes from the axle line, corrected by the floor-to-axle height
difference. Lateral offsets are half of measured widths; a blank width uses a labelled fallback and
is flagged. A 5 mm width error moves no output by more than about 0.25 mm.

S replaces an earlier saddle midpoint: saddles are concave, so a point computed along a tilt line is
not on the surface. S is a tape mark on the saddle's top centerline at an entered distance from the
tip, the same distance on both bikes when the saddle is the same. **No standard exists for this
location**; use the fitter's, or keep it consistent. BB-S and BC-S place S. Reported are BB-origin
X/Y of ST, S, BC and H; bar stack and reach (at the clamp); hand reach and drop (at H); and
optional maker frame stack and reach (head tube top, not measured, recorded only).

Six checks are compared with the solved geometry, never used to build it: RA-FA, FA-H, RA-BC, BC-H,
RA-S, and the solved ST-S line against the entered mark distance. A check warns at max(3 mm, 2.5 x
its expected sd) and is flagged likely-bad beyond max(6 mm, 4 x sd). At 1 mm tape error a seeded
simulation of 3,000 bikes each gave warnings on 6.9% of CX and 7.5% of MTB bikes, and flags on
0.03% and 0.1%. A 12 mm typo in any of the fifteen tapes, or in the mark distance, trips a check.
BB-S is almost the saddle height itself, so ST-S barely sees it (about 1 mm); RA-S catches it (about
12 mm against a flag at 9). BC-S shows in ST-S (about 12 mm against 7) and RA-S (about 7 mm). Failed checks
name likely tapes as a hint. The checks cannot see floor heights, saddle tilt or
length, crank length, string length or widths. The +/- covers 1 mm tape error only. Seated results
treat the front triangle as rigid. The drops are out of scope.

## 2. Saddle: sit point, tilt, fore/aft (`Coach judgment:`)

Saddle height is shown as BB center to S in a straight line; the seat tube is not measured, so it
is not a height along the seat tube. Fitters quote setback from the nose, so tip-based
setback stays alongside sit-point setback. Compare sit-point setback, not saddle rail position
(recorded as free text only), because seat tube angle differs between bikes. The comparison shows
whether the saddle models match; a matching saddle makes it cleaner. Saddle length is recorded
only.

Tilt is read with a straightedge from tip to tail and a digital level on the straightedge, since the
concave top makes a level sitting on it unreliable; an optional floor reading with the same device
is subtracted. Tilt beyond about +/-4 degrees is treated as suspect and checked: the tool shows a
neutral "check the measurement" note, which is not a target, blocks nothing and changes no result.

Unsourced practitioner lore, not studied here: nose-up tilt is often said to add to low back pain
through reduced hip support, and nose-down puts more pressure on the hands. A 1999 uncontrolled
study with inconsistent secondary reporting exists and is not used. Also unsourced: practitioners
argue a saddle too far forward can raise, not lower, low back stress; no study testing this was
verified here.

## 3. Fit, back pain and posture (UNREVIEWED)

**[EVIDENCE: cycling]** A systematic review of 8 studies and 255 subjects, median Downs and Black
12 of 27 ("low to moderate quality"), found "cyclists with lower handlebar heights displayed
increased lumbosacral flexion angles" (Streisfeld et al. (2017)). Confidence: low-medium.

**[EVIDENCE: cycling]** In 30 road cyclists, 30 mountain bikers and 30 non-cyclists, "the road
bicycling posture was characterised by greater lumbar flexion and more significant anterior pelvic
tilt and trunk inclination compared with the mountain biking posture", and "the thoracic spine was
more flexed in mountain biking" (Muyor and Zabala (2016); catalogue abstract only, riders' bikes and
hand position not stated).

**[ADAPTED: cycling]** For a drop-bar CX bike that road finding is an inference, not a CX result.
Confidence: low. Test: photograph trunk and pelvic angle on both bikes at matched effort and compare.

**[EVIDENCE: cycling]** A 2026 systematic review of three studies (one RCT, two quasi-experimental;
qualitative, no meta-analysis) says fitting "appears effective in reducing LBP", that "evidence
remains limited by methodological heterogeneity and short follow-ups", and that static versus
dynamic fitting "is not well established" (Barrajon et al. (2026)). The RCT is listed there as 72
trained cyclists, 3D dynamic fit versus usual setup, 30 days; another record gave a different
sample, and that is unresolved. A 2024 review (Husband et al. (2024); abstract only) rated none of
47 studies good quality and linked saddle height, trunk angle and saddle fore/aft to performance,
and saddle fore/aft changes hip and trunk angles at that abstract level. Nothing here supports a
specific tilt, drop or reach number as a pain fix.

## 4. Crank, pedal stack, static versus dynamic, tools

Comparison shows the crank length difference (for example 172.5 mm CX and 170 mm MTB) and its
effect on pedal axle to sit point: crank down is height plus crank, crank up is height minus crank,
so a 2.5 mm difference moves them by 2.5 mm in opposite directions. No recommendation follows.

Pedal stack (pedal axle center to shoe sole, clipped in) is optional, hard to measure, and
limited in accuracy; maker spec or measured is recorded. The same shoes on both bikes cancel, so
only the pedal difference matters. Pedal-axle-to-sit-point figures stay geometric, without stack;
when both snapshots have a stack, the comparison also shows its difference and the adjusted
difference with a stated +/-3 mm per snapshot, independent of tape error. No shoe or cleat fields.

**[EVIDENCE: cycling]** Saddle-height methods are "varied and not well established" and suggest 25-30
degrees of knee flexion (Bini, Hume and Croft (2011); narrative review). In 15 riders dynamic knee
flexion was 5.4 degrees greater than static (95% CI 3.5, 7.4), typical error 1.7 degrees dynamic
versus 4.2 static, and the 25-35 degree guidance became 30-40 for dynamic measurement (Corbett and
Bevins (2014); catalogue abstract). These ranges differ by test condition, not as targets, and a
static tape tool does not capture dynamic angles.

**[EVIDENCE: cycling]** A 3D camera system (Retul, 18 Hz) against Vicon (240 Hz) in 11 male
triathletes showed very high correlation on 6 of 18 measures and 0.7-0.9 on the rest (Scoz et al.
(2021)). Between fitters, nine studios advised positions differing by up to 3 cm (Braeckevelt et
al. (2019); conference abstract, not re-checked).

## 5. Gaps and when to see a clinician (`Coach judgment:`)

No peer-reviewed work on suspension sag or CX dismounts was found, no standard exists for the
sit-bone reference, and no 2D-versus-3D study was found. Hub width and Q-factor effects are treated
as negligible here.

Night pain, constant or radiating pain, numbness or weakness, or pain that does not settle with rest
goes to a clinician. Any pain report is stop-and-assess; no prescriptions here, the fitter decides.
