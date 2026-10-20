"""health_vocab: the single source for body regions / restrictions and health-language detection."""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest

from swim_coach import health_vocab as hv
from swim_coach.models import HealthStatus

REPO = Path(__file__).resolve().parents[2]


def test_enums_are_the_stored_vocabulary() -> None:
    assert hv.RESTRICTIONS == ("none", "light_only", "no_training")
    assert hv.RESTRICTION_SEVERITY == {"none": 0, "light_only": 1, "no_training": 2}
    assert "ankle_foot" in hv.BODY_REGIONS and hv.BODY_REGIONS[-1] == "other"
    fields = HealthStatus.model_fields
    assert set(typing.get_args(typing.get_args(fields["body_region"].annotation)[0])) == set(hv.BODY_REGIONS)
    assert set(typing.get_args(fields["restriction"].annotation)) == set(hv.RESTRICTIONS)
    assert set(typing.get_args(fields["source"].annotation)) == set(hv.SOURCES)


def test_every_mapped_word_maps_to_a_real_region() -> None:
    assert set(hv.BODY_REGION_WORDS.values()) <= set(hv.BODY_REGIONS)


@pytest.mark.parametrize(
    "text",
    [
        "my knee hurts on the descent",
        "knee pain on the descent",
        "I have a headache",
        "scratchy throat",
        "coming down with something",
        "I blacked out on the climb",
        "my shoulder felt weird in the second half",
        "sore all over",
        "feeling dizzy",
        "chest pain",
    ],
)
def test_real_reports_are_detected(text: str) -> None:
    assert hv.mentions_health(text)


@pytest.mark.parametrize(
    "text",
    [
        "I'm in the pain cave today",
        "that was a sick descent",
        "we stopped on the shoulder of the road",
        "we did bilateral breathing drills",
        "cold water swimming is great",
        "check my heart rate zones",
        "what is on my plan tomorrow?",
        "thanks, that helps",
    ],
)
def test_known_slang_is_not_health(text: str) -> None:
    assert not hv.mentions_health(text)


@pytest.mark.parametrize(
    "text",
    [
        "pain cave but my knee hurts",
        "sick descent then my shoulder started to ache",
        "hurt locker, and now my chest is tight",
        "pulled over on the shoulder of the road, my hip is sore",
    ],
)
def test_not_health_list_never_suppresses_a_real_report(text: str) -> None:
    assert hv.mentions_health(text)


@pytest.mark.parametrize(
    "sports,text,expected",
    [
        (["bike"], "I have a saddle sore", True),
        (["swim_ow"], "got stung by a jellyfish", True),
        (["bike"], "got stung by a jellyfish", False),
        (["swim_pool", "swim_ow"], "swimmer's ear again", True),
        (["bike"], "swimmer's ear again", False),
        (["cross_train"], "I think it's shin splints", True),
        (["run"], "I think it's plantar fasciitis", True),
        (["bike"], "I had a crash on the corner", True),
        (None, "I had a crash on the corner", False),
    ],
)
def test_sport_specific_terms_follow_the_athletes_sports(sports, text, expected) -> None:
    assert hv.mentions_health(text, sports) is expected


def test_group_hits_name_which_list_fired() -> None:
    assert hv.health_group_matches("I have a headache")["illness"]
    assert hv.health_group_matches("I have a saddle sore", ["bike"])["sport"]
    assert not any(hv.health_group_matches("what pace is css?").values())


# --- guard: no second copy of the vocabulary --------------------------------------------------

_SCAN_DIRS = ("engine/swim_coach", "backend/app", "scripts")
_LITERALS = ('"ankle_foot"', "'ankle_foot'")
_ALLOWED_BODY_REGION_FILES = {"engine/swim_coach/health_vocab.py"}


def _py_files() -> list[Path]:
    return [p for d in _SCAN_DIRS for p in (REPO / d).rglob("*.py")]


def test_body_region_list_is_defined_only_in_health_vocab() -> None:
    offenders = [
        str(p.relative_to(REPO))
        for p in _py_files()
        if str(p.relative_to(REPO)) not in _ALLOWED_BODY_REGION_FILES
        and any(lit in p.read_text(encoding="utf-8") for lit in _LITERALS)
        and re.search(r"[\"']elbow_wrist[\"']", p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"body-region literals must come from swim_coach.health_vocab: {offenders}"


def test_restriction_list_is_defined_only_in_health_vocab() -> None:
    pair = re.compile(r"[\"']light_only[\"']\s*,\s*[\"']no_training[\"']|[\"']none[\"']\s*,\s*[\"']light_only[\"']")
    offenders = [
        str(p.relative_to(REPO))
        for p in _py_files()
        if str(p.relative_to(REPO)) != "engine/swim_coach/health_vocab.py" and pair.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"restriction literals must come from swim_coach.health_vocab: {offenders}"


def _js_label_keys(source: str, const_name: str) -> set[str]:
    block = re.search(rf"const {const_name} = \{{(.*?)\n\}};", source, re.S)
    assert block, const_name
    return set(re.findall(r"^\s*(\w+):", block.group(1), re.M))


def test_pwa_labels_cover_exactly_the_backend_vocab() -> None:
    # The PWA hard-codes display labels keyed by the stored vocabulary; this keeps them in step
    # until they are served from the backend (follow-up).
    views = (REPO / "web/src/views.js").read_text(encoding="utf-8")
    assert _js_label_keys(views, "HEALTH_BODY_REGION_LABELS") == set(hv.BODY_REGIONS)
    assert _js_label_keys(views, "HEALTH_RESTRICTION_LABELS") == set(hv.RESTRICTIONS)
