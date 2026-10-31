# Tire pressure (CX, MTB, gravel, road: starting points, limits, how to tune)

See `00-conventions.md` for the tagging scheme and `reference_list.md` for citations. Companions:
`45-bike-race-setup.md` (sealant, brakes, pre-race checks), `42-ultra-mtb-endurance.md`.

**Sport scope: `bike`.** **UNREVIEWED**, pending human review. Written for a masters amateur
cyclist. **Evidence is thin here:** only a handful of small peer-reviewed cycling studies on
pressure exist, and none gives a prescriptive pressure. Every number below that tells you what to
run comes from a manufacturer, a calculator or a practitioner, all with commercial interest or a
single-source basis, and is labelled that way. **The athlete's own logged pressures on these tires,
rims and courses outrank any calculator or chart.** Use the numbers only as the first guess.

## 1. What research does and does not show (UNREVIEWED)

**[EVIDENCE: cycling]** In coast-down tests on four mountain bikes, terrain surface had the largest
effect on rolling resistance, then rider mass, wheel diameter and inflation pressure (Steyn and
Warnich (2014)). The best combination for keeping momentum after an obstacle included high pressure,
so low pressure is a real trade-off, not free speed. Field MTB testing at 200 and 400 kPa (about 29
and 58 psi) found pressure and surface both affect rolling resistance; the abstract gives no
direction or size (Bertucci et al. (2013)).

**[EVIDENCE: cycling]** A 30 mm versus 25 mm internal rim width cut rolling resistance 1.4% at
matched tire stiffness and raised it 0.9% at the same pressure; effects on speed were most likely
trivial (Maier et al. (2019); three riders, one XC course, one tire model). Confidence: low-medium
for generalising.

**[ADAPTED: general-endurance]** Pressure floor: one rider (about 175 lb) on a paved 6% grade lost
about 1.3% going from 40 to 30 psi, 3.8% power at 20 psi, and more than 20% at 10 psi (Barber
(2016), a practitioner test; one rider, one tire, paved, not off-road). It suggests the penalty is
small above a floor and steep below it. Confidence: low. Test: on a known loose-surface loop,
compare lap time or power at two pressures 3-4 psi apart.

**[ADAPTED: cycling]** Tubeless and latex beat butyl, more at low pressure. On a drum, one 29x2.2
MTB tire saved 7.7 W versus butyl at 15 psi and 2.5 W at 55 psi; latex at 55 psi was almost the same
as tubeless (Bierman (2014), independent tester). It is one 2014 drum test on one tire with
bench-level sealant. Treat the watts as illustrative. Confidence: medium for direction, low for
the figures. Test: none needed; the practical benefit is pinch-flat headroom at low pressure.

**Drum limits.** The same tester scales heavier riders and higher speeds roughly linearly and does
not measure them. Drums do not capture suspension losses on rough ground. The case that high
pressure can be faster on rough pavement and slower on smooth is made by Rene Herse Cycles (sells
tires), not a controlled study.

## 2. Calculators disagree (UNREVIEWED)

`Coach judgment:` treat every output as a hypothesis. For a 170 lb rider on a 28 mm tire, a
secondhand Slowtwitch comparison reported Silca 71 rear and 69 front psi, SRAM/Zipp 61 and 58, and
ENVE 57-73 depending on width (Silca's inputs are known only secondhand via Slowtwitch; the
Silca pages could not be opened). A 9-10 psi spread for one rider is the finding. Zipp states its
output is "a starting point". Inputs commonly asked: tire width, casing, inner rim width, rider and
bike weight, surface.

## 3. Starting ranges (label the source every time)

- **CX, 33 mm tires, average conditions:** 30-35 psi to begin, then adjust after practice laps; very
  muddy, as low as 20 psi with clinchers and 15 psi tubeless. **This rests on one BikeRadar
  article (media), with no rider weight stated; heavier riders need more.** Confidence: low-medium.
- **Gravel (Canyon table, manufacturer, no stated tube/rim assumptions):** 35 mm tires at 140-180 lb:
  40-45 psi hardpack, 35-40 loose gravel, 32-35 mud or sand; 45 mm tires: 32-35, 28-32, 25-30. The
  surface step is about 5-10 psi; rear slightly above front.
- **MTB XC:** no manufacturer figure could be verified; start from the athlete's own logs.
- **Road and hookless:** limited by the rim, see section 4.

## 4. Hookless and rim limits

Schwalbe (manufacturer) publishes maximums for hookless rims: 25-29 mm tires 5 bar (72 psi); 30-34 mm
4.5 bar (65 psi); 35-39 mm 4 bar (58 psi); 40-44 mm 3.5 bar (51 psi); 45-54 mm 3 bar (44 psi). It
says hookless rims may only be combined with its TLE/TLR tires, and tubeless-only hookless rims
cannot take tube-type tires. Zipp states its current road wheels are hookless tubeless. These are
ceilings, not targets. `Coach judgment:` obey the lower of the rim and tire printed maximum; a
heavier rider on 25-28 mm road tires may hit the ceiling first, so widen the tire.

## 5. Practical factors (`Coach judgment:` unless sourced)

- **Weight:** more rider plus bike mass needs more pressure; front lower than rear (Canyon, Zipp).
- **Wet, mud, sand, roots:** lower for grip and compliance. The floor is rim strikes, squirm (vague
  steering in corners) and burping on tubeless; BikeRadar warns of bottoming out the rim. Roots and
  rocks raise pinch-flat risk on tubed setups.
- **Tubular:** cannot burp and can run lower, but a poorly glued tubular can roll off.
- **Gauges:** a practitioner test of six gauges on a tubeless rim at 25, 20 and 15 psi found three
  read identically and one read 2 psi low (Singletrack World (2018)); the author ranked repeatability
  above accuracy. `Coach judgment:` use one gauge and log pressures in that gauge's numbers.
- **Temperature (computed, not a cycling study):** gas law at constant volume gives about 1 psi per
  10 F (5.5 C) at CX pressures; for example 25 psi set at 70 F (21 C) reads about 22.8 psi at 40 F
  (4 C). Set pressure at venue temperature, or add a little when setting indoors. Riding warms the
  air slightly, so recheck after warm-up.

## 6. Pre-ride tuning protocol (`Coach judgment:`, consistent with BikeRadar)

1. Start from the weight-adjusted table or calculator value, or better, the athlete's own log.
2. Ride 2-3 laps of the actual course; change 1-2 psi (0.1 bar) per step.
3. Too low: vague steering, squirm, rim strikes, burping. Add air.
4. Too high: skittish, bouncing off roots, lost traction. Remove air.
5. Settle at the lowest pressure with no strikes or burps. Record pressure, conditions, tire, rim
   width and gauge.
