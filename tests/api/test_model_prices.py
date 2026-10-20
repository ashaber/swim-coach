from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.model_prices import split_cache_writes, usage_cost


def cost(model, **kw):
    base = dict(input_tokens=0, cache_read=0, cache_write_5m=0, cache_write_1h=0, output=0)
    base.update(kw)
    return usage_cost(model, **base)


def test_haiku_below_the_step() -> None:
    r = cost("claude-haiku-5-5", input_tokens=10_000, cache_read=60_000, output=1_000)
    assert r["est_cost_usd"] == pytest.approx(0.001 + 0.0006 + 0.0005)
    assert r["prompt_tokens_total"] == 70_000 and r["over_100k"] is False


def test_haiku_above_the_step_is_5x_and_counts_cache_tokens() -> None:
    r = cost("claude-haiku-5-5", input_tokens=1_000, cache_read=60_000, cache_write_1h=50_000)
    assert r["over_100k"] is True
    assert r["est_cost_usd"] == pytest.approx(5 * (1_000 * 0.10 + 60_000 * 0.01 + 50_000 * 0.20) / 1e6)


def test_haiku_exactly_at_the_step_is_not_over() -> None:
    assert cost("claude-haiku-5-5", input_tokens=100_000)["over_100k"] is False


def test_sonnet_5_5_and_5_read_prices_differ() -> None:
    a = cost("claude-sonnet-5-5", cache_read=1_000_000)["est_cost_usd"]
    b = cost("claude-sonnet-5", cache_read=1_000_000)["est_cost_usd"]
    assert a == pytest.approx(0.10) and b == pytest.approx(0.20)
    full = cost("claude-sonnet-5-5", input_tokens=1_000_000, cache_write_5m=1_000_000,
                cache_write_1h=1_000_000, output=1_000_000)["est_cost_usd"]
    assert full == pytest.approx(2 + 2.5 + 4 + 10)


def test_sonnet_has_no_long_prompt_step() -> None:
    assert cost("claude-sonnet-5-5", input_tokens=200_000)["est_cost_usd"] == pytest.approx(0.4)


@pytest.mark.parametrize("model", ["claude-mystery-9", None, ""])
def test_unknown_model_is_null_not_a_crash(model) -> None:
    r = cost(model, input_tokens=5)
    assert r["est_cost_usd"] is None and r["prompt_tokens_total"] == 5


def test_dated_snapshot_resolves_to_family() -> None:
    assert cost("claude-haiku-5-5-20261001", input_tokens=50_000)["est_cost_usd"] == pytest.approx(0.005)


def test_split_cache_writes_prefers_reported_split_else_ttl() -> None:
    reported = SimpleNamespace(
        cache_creation_input_tokens=30,
        cache_creation=SimpleNamespace(ephemeral_5m_input_tokens=10, ephemeral_1h_input_tokens=20),
    )
    assert split_cache_writes(reported, "5m") == (10, 20)
    plain = SimpleNamespace(cache_creation_input_tokens=30)
    assert split_cache_writes(plain, "1h") == (0, 30)
    assert split_cache_writes(plain, "5m") == (30, 0)
