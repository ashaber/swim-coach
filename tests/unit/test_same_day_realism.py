import uuid
from datetime import date, timedelta

from swim_coach.plan import BIKE_MAX_BIKE_DAYS_PER_WEEK, BIKE_MAX_HARD_DAYS_PER_WEEK, evaluate_week_realism
from swim_coach.models import Session

ATHLETE = uuid.uuid4()
MONDAY = date(2026, 10, 12)


def ride(offset: int, zone: str = "Z2", kind=None, minutes: float = 60.0) -> Session:
    return Session(
        id=uuid.uuid4(), athlete_id=ATHLETE, date=MONDAY + timedelta(days=offset), sport="bike",
        source="ai_coach", duration_min=minutes, intensity={"zone": zone}, purpose="ride", kind=kind,
    )


def test_a_double_counts_as_one_bike_day() -> None:
    days = BIKE_MAX_BIKE_DAYS_PER_WEEK
    sessions = [ride(i) for i in range(days)] + [ride(0)]  # a second ride on day 0
    assert not any("bike training days" in w for w in evaluate_week_realism(sessions))


def test_warmup_does_not_add_a_bike_day() -> None:
    days = BIKE_MAX_BIKE_DAYS_PER_WEEK
    sessions = [ride(i) for i in range(days)] + [ride(days, kind="warmup", minutes=30.0)]
    assert not any("bike training days" in w for w in evaluate_week_realism(sessions))


def test_two_hard_rides_one_day_is_one_hard_day() -> None:
    sessions = [ride(0, "Z4"), ride(0, "Z4")] + [ride(2, "Z4")] * (BIKE_MAX_HARD_DAYS_PER_WEEK - 2)
    assert not any("hard bike days planned" in w for w in evaluate_week_realism(sessions))
