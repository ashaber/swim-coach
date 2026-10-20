"""Health vocabulary: the ONE place the health/body/restriction enums and health-language term
lists are defined. The engine owns domain definitions; models, routes, tool schemas, context
rendering and the chat router all import from here (a guard test fails if a second copy of the
body-region or restriction lists appears anywhere else).

Two kinds of content:
  * Enums (BODY_REGIONS, RESTRICTIONS, SOURCES, ONSETS, SEVERITIES) -- the stored vocabulary of
    `HealthStatus`.
  * Detection terms (PAIN/ILLNESS/ACUTE/MEDICAL, anatomy, sport-specific additions, and a small
    NOT-HEALTH phrase list) used to decide "does this message mention a possible health problem?".
    Detection is a safety net, not a diagnosis: the repo rail is "any pain report -> stop-and-assess
    -> Sonnet", so every list here is tuned to OVER-match. A false positive only costs a bigger
    model call; a miss is the failure that matters.

False positives only cost a Sonnet call, so when in doubt, leave a phrase OFF the NOT-HEALTH list.

Coach judgment: all term lists below (no research citation; they encode what athletes and coaches
actually type, including the IDEA 022 PR #215 misses: "blacked out", "coming down with something",
"headache", "scratchy throat").
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from typing import Literal

# --- enums ------------------------------------------------------------------------------------

BODY_REGIONS: tuple[str, ...] = (
    "shoulder", "knee", "back", "hip", "ankle_foot", "elbow_wrist",
    "illness_systemic", "head_neck", "other",
)
# Ordered mildest to most restrictive; the index is the severity rank.
RESTRICTIONS: tuple[str, ...] = ("none", "light_only", "no_training")
SOURCES: tuple[str, ...] = ("self_reported", "practitioner")
ONSETS: tuple[str, ...] = ("acute", "gradual")
SEVERITIES: tuple[str, ...] = ("slight", "minimal", "mild", "moderate", "serious", "long_term")

BodyRegion = Literal[BODY_REGIONS]  # type: ignore[valid-type]
Restriction = Literal[RESTRICTIONS]  # type: ignore[valid-type]
HealthSource = Literal[SOURCES]  # type: ignore[valid-type]
Onset = Literal[ONSETS]  # type: ignore[valid-type]
Severity = Literal[SEVERITIES]  # type: ignore[valid-type]

RESTRICTION_SEVERITY: dict[str, int] = {name: rank for rank, name in enumerate(RESTRICTIONS)}

# --- word -> coarse region (used to tag a free-text body part, e.g. by record_health_status) --

BODY_REGION_WORDS: dict[str, str] = {
    **dict.fromkeys(("shoulder", "shoulders", "rotator cuff", "scapula", "clavicle", "collarbone", "deltoid",
                     "bicep", "tricep"), "shoulder"),
    **dict.fromkeys(("knee", "knees", "patella", "kneecap", "meniscus"), "knee"),
    **dict.fromkeys(("lower back", "upper back", "spine", "spinal", "lumbar", "thoracic", "ribs", "rib"), "back"),
    **dict.fromkeys(("hip", "hips", "hamstring", "quad", "quads", "quadriceps", "glute", "glutes", "groin",
                     "adductor", "hip flexor", "thigh", "pelvis", "it band", "itb"), "hip"),
    **dict.fromkeys(("calf", "calves", "achilles", "shin", "shins", "foot", "feet", "ankle", "plantar", "heel",
                     "toe", "arch"), "ankle_foot"),
    **dict.fromkeys(("wrist", "elbow", "forearm", "hand", "thumb", "finger"), "elbow_wrist"),
    **dict.fromkeys(("neck", "head", "headache", "concussion", "jaw", "cervical"), "head_neck"),
    **dict.fromkeys(("flu", "cold", "covid", "fever", "sick", "illness", "virus", "infection", "stomach", "gi"),
                    "illness_systemic"),
}

# --- detection terms --------------------------------------------------------------------------
# Plain words/phrases; `\b`-bounded and case-insensitive when compiled. A trailing `*` means
# "any word ending" (injur* -> injury, injured).

PAIN_TERMS: tuple[str, ...] = (
    "pain", "painful", "hurt", "hurts", "hurting", "ache", "aches", "aching", "sore", "soreness", "tender",
    "twinge", "twinges", "niggle", "niggles", "tweak", "tweaked", "pulled", "strain", "strained", "sprain",
    "sprained", "swollen", "swelling", "bruis*", "inflam*", "tendin*", "tendon", "fractur*", "cramp*", "stiff",
    "numb*", "tingl*", "burning", "injur*",
)
ILLNESS_TERMS: tuple[str, ...] = (
    "sick", "ill", "illness", "flu", "covid", "fever", "feverish", "cough*", "sniffl*", "congest*",
    "sore throat", "scratchy throat", "headache", "migraine", "nausea", "nauseous", "vomit*", "diarrh*",
    "infection", "infected", "rash", "virus", "viral", "stomach bug", "food poisoning", "dehydrat*",
    "hypotherm*", "heatstroke", "heat stroke", "cold and", "a cold", "head cold", "chest cold",
    "coming down with", "under the weather", "caught the bug", "caught a bug", "bug going around",
    "shiver*", "cold shock", "cold water shock", "feel off", "feeling off", "feel unwell", "feeling unwell",
    "feel rough", "feeling rough", "feel awful", "feeling awful", "feel terrible", "feeling terrible",
    "feel weird", "feeling weird", "feel faint", "feeling faint",
)
ACUTE_TERMS: tuple[str, ...] = (
    "irregular", "afib", "a-fib", "arrhythmia", "skipped beat", "spiked at rest", "breath away", "gasp*",
    "hyperventilat*", "dizzy", "dizziness", "light-headed", "lightheaded", "faint*", "blacked out", "blacking out", "black out",
    "passed out", "palpitation*", "shortness of breath", "short of breath", "can't breathe", "breathless",
    "breathe", "breathing", "chest", "heart racing", "racing heart", "irregular heartbeat", "confus*",
    "disorient*", "concussion", "seiz*", "bleed*", "blood",
)
MEDICAL_TERMS: tuple[str, ...] = (
    "doctor", "physio", "physiotherapist", "gp", "surgeon", "surgery", "medical", "medication", "meds",
    "antibiotic*", "prescri*", "diagnos*", "mri", "x-ray", "xray", "scan", "symptom*", "asthma", "inhaler",
)
# Anatomy words that, with no pain word, still deserve a closer look ("my shoulder felt weird").
# Deliberately excludes words that are common non-anatomy English ("back", "head", "hand", "arch",
# "lat", "cold", "gi"); pain-with-"back" is caught by "back pain"/"lower back" etc.
ANATOMY_TERMS: tuple[str, ...] = tuple(
    sorted(
        {
            *(w for w, r in BODY_REGION_WORDS.items() if r != "illness_systemic"
              and w not in {"head", "hand", "arch", "toe", "rib", "ribs"}),
            "ribs", "back pain", "elbows", "wrists", "ankles", "lats", "rotator", "tendonitis",
        }
    )
)

# Sport-specific additions, selected by the athlete's effective sports (data keyed by sport; the
# union over the athlete's sports is added to the generic lists). Sport names are models.Sport.
SPORT_HEALTH_TERMS: dict[str, tuple[str, ...]] = {
    "swim_pool": (
        "swimmer's ear", "swimmers ear", "shoulder impingement", "impingement", "ear infection",
        "water in my ear", "swimmer's shoulder", "breaststroker's knee",
    ),
    "swim_ow": (
        "swimmer's ear", "swimmers ear", "shoulder impingement", "impingement", "jellyfish", "stung",
        "sting", "chafing", "chafed", "salt rash", "ear infection", "hypothermic",
    ),
    "bike": (
        "saddle sore", "saddle sores", "numb hands", "numb feet", "numb crotch", "road rash", "crash",
        "crashed", "fell off", "came off", "hit by a car", "hot foot", "carpal", "taint",
    ),
    "strength": ("tweak", "tweaked", "strain", "strained", "pulled", "popped", "pinch*"),
    "cross_train": ("shin splints", "plantar fasciitis", "stress fracture", "runner's knee", "blister*",
                    "black toenail", "it band", "turned my ankle", "rolled my ankle"),
    "recovery": ("stiff", "knot", "knots"),
}
# "run" is not a models.Sport (running is logged under cross_train); the run-specific terms live
# under cross_train above and are also reachable by this alias for callers that name it.
SPORT_ALIASES: dict[str, str] = {"run": "cross_train", "running": "cross_train", "cycling": "bike"}

# Known slang / false positives. Each phrase is removed from the text BEFORE term matching, so it
# can only ever suppress its own words; "my knee hurts on the descent" is untouched. Coach judgment:
# conservative on purpose -- never add a phrase that could swallow a real report.
NOT_HEALTH_PHRASES: tuple[str, ...] = (
    "pain cave", "pain locker", "hurt locker", "sick descent", "sick climb", "sick ride", "sick swim",
    "sick set", "sick session", "sick trail", "sick line", "sick time", "sick pace", "shoulder of the road",
    "hard shoulder", "road shoulder", "shoulder season", "bilateral breathing", "breathing drill",
    "breathing pattern", "breathe every", "breathe to the", "breathing every", "breathing side",
    "cold plunge", "killer climb", "killer set", "chest press", "chest fly",
)


def _term_regex(term: str) -> str:
    if term.endswith("*"):
        return r"\b" + re.escape(term[:-1]) + r"\w*"
    return r"\b" + re.escape(term) + r"\b"


@lru_cache(maxsize=256)
def _compile(terms: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted(set(terms), key=len, reverse=True)
    return re.compile("|".join(_term_regex(t) for t in ordered), re.IGNORECASE)


def compile_terms(terms: Iterable[str]) -> re.Pattern[str]:
    """One case-insensitive alternation over `terms` (longest first); compiled once per term set."""
    return _compile(tuple(terms))


_NOT_HEALTH_RE = compile_terms(NOT_HEALTH_PHRASES)

# generic term groups, each compiled once; the router names its rules after these keys
TERM_GROUPS: dict[str, tuple[str, ...]] = {
    "pain": PAIN_TERMS,
    "anatomy": ANATOMY_TERMS,
    "illness": ILLNESS_TERMS,
    "acute": ACUTE_TERMS,
    "medical": MEDICAL_TERMS,
}


def sport_terms(sports: Iterable[str] | None) -> tuple[str, ...]:
    """The extra detection terms for an athlete's sports (empty/None = generic terms only)."""
    out: list[str] = []
    for sport in sports or ():
        out.extend(SPORT_HEALTH_TERMS.get(SPORT_ALIASES.get(sport, sport), ()))
    return tuple(dict.fromkeys(out))


def strip_not_health(text: str) -> str:
    """`text` with known non-health slang removed (see NOT_HEALTH_PHRASES)."""
    return _NOT_HEALTH_RE.sub(" ", text)


def health_group_matches(text: str, sports: Iterable[str] | None = None) -> dict[str, bool]:
    """Which term groups hit in `text` after non-health slang is removed; the sport-specific
    additions report under "sport"."""
    cleaned = strip_not_health(text)
    hits = {name: bool(compile_terms(terms).search(cleaned)) for name, terms in TERM_GROUPS.items()}
    extra = sport_terms(sports)
    hits["sport"] = bool(extra and compile_terms(extra).search(cleaned))
    return hits


def mentions_health(text: str, sports: Iterable[str] | None = None) -> bool:
    """True when `text` may report a pain/injury/illness/symptom (over-matching by design)."""
    return any(health_group_matches(text, sports).values())
