# NOTE: preprocessing limitation

The source file (library/sample_pool_workout_openwater_focus.md) is one
single run-on line with no newlines or markdown bullets -- headings,
"Block" labels, and set lines are all mashed together with no separator.
This fixture is a best-effort MANUAL split of that run-on text onto
separate lines, breaking before numbered section markers ("1.", "2.",
"3.", "4."), "Block X:" labels, "Transition Set N" labels, and each
`N x M` set token. It is NOT produced by the parser itself -- the parser
has no run-on-line-splitting logic; this split was done by hand to build
a usable fixture, per Day 3 instructions. A real ingested coach text this
garbled would likely need this same manual pre-split before
`parse_coach_text` could do much with it; that limitation is intentional
and documented rather than solved.

# USMS Sample Workout: Aerobic Engine & Open Water Simulation

## 1. Warm-Up (850 Total)
1 x 400 — Easy Freestyle. Focus on early vertical forearm catch.
6 x 75 — As Kick-Drill-Swim (K-D-S).
25 Kick (2-beat crossover focus) [Source 20].
25 Drill (Fist drill or single-arm to enforce catch stability).
25 Swim (Smooth, long stroke length).

## 2. Preset: Speed Progression & Aerobic Activation (600 Total)
12 x 50 — Freestyle on a descending interval pattern.
First 4 — Cruise pace, establish smooth rhythmic breathing.
Middle 4 — Build to target marathon pace (+5 seconds rest drop).
Final 4 — Fast tempo pace (+5 seconds rest drop). Focus on clean turns.

## 3. Main Set: The Broken Distance Pyramid (2,200 Total)

### Block A: Endurance Capacity
4 x 200 — Pull (Using buoy, paddles optional). Focus on keeping a flat, horizontal line in the water without losing hip rotation.

### Transition Set 1
10 x 50 — Freestyle. Execute these as "Open Wall Sets"—turn 1–2 meters before reaching the wall without touching it. This simulates an in-water open-water start and removes the "wall economy" advantage [Source 15].

### Block B: Negative-Split Durability
4 x 150 — Negative Split. Swim the first 75 controlled and smooth; accelerate the final 75 to exceed baseline pace. This builds the fatigue resiliency required for late-stage race pacing [Source 19].

### Transition Set 2
10 x 50 — Freestyle. Incorporate "Crocodile Sighting" drills—lift your eyes slightly above the surface line every 4th stroke to look at a fixed object at the end of the lane without dropping your hips.

### Block C: Speed Reserve under Fatigue
4 x 100 — Descend 1–4. Each 100 must be faster than the previous one. Repetition #4 should be at maximal sustainable effort while holding exact mechanical form.

## 4. Cool-Down (350 Total)
1 x 150 — Super easy choice stroke, slow heart rate down completely.
1 x 200 — Social kick (Kick with a kickboard at an easy recovery effort) to flush out the lower extremities.
