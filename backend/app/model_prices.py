"""Per-model prices as data, and the one cost function every model-call log line uses.

Source: https://platform.claude.com/docs/en/about-claude/pricing (fetched 2026-10-20). USD per
million tokens. A request's prompt length is fresh input + cache reads + cache writes; Haiku 5.5
prices the WHOLE request at 5x each rate when that length exceeds 100,000 tokens (each request is
priced on its own). Unknown models are never an error: cost is None.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float
    # Above this prompt length every rate is multiplied by `long_prompt_multiplier` (None = no step).
    long_prompt_tokens: int | None = None
    long_prompt_multiplier: float = 1.0


_SONNET_5_5 = ModelPrice(input=2.0, cache_write_5m=2.5, cache_write_1h=4.0, cache_read=0.10, output=10.0)

# Keyed by model-ID prefix; the longest matching prefix wins (dated snapshots resolve to their family).
MODEL_PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5-5": _SONNET_5_5,
    "claude-sonnet-5": ModelPrice(
        input=2.0, cache_write_5m=2.5, cache_write_1h=4.0, cache_read=0.20, output=10.0
    ),
    "claude-haiku-5-5": ModelPrice(
        input=0.10, cache_write_5m=0.125, cache_write_1h=0.20, cache_read=0.01, output=0.50,
        long_prompt_tokens=100_000, long_prompt_multiplier=5.0,
    ),
}


def price_for(model: str | None) -> ModelPrice | None:
    if not model:
        return None
    matches = [k for k in MODEL_PRICES if model.startswith(k)]
    return MODEL_PRICES[max(matches, key=len)] if matches else None


def usage_cost(
    model: str | None,
    *,
    input_tokens: int,
    cache_read: int,
    cache_write_5m: int,
    cache_write_1h: int,
    output: int,
) -> dict[str, object]:
    """`{prompt_tokens_total, over_100k, est_cost_usd}` for one request. est_cost_usd is None for
    an unknown model. `over_100k` is the Haiku price step, reported for every model."""
    total = input_tokens + cache_read + cache_write_5m + cache_write_1h
    price = price_for(model)
    cost: float | None = None
    if price is not None:
        mult = 1.0
        if price.long_prompt_tokens is not None and total > price.long_prompt_tokens:
            mult = price.long_prompt_multiplier
        cost = mult * (
            input_tokens * price.input
            + cache_read * price.cache_read
            + cache_write_5m * price.cache_write_5m
            + cache_write_1h * price.cache_write_1h
            + output * price.output
        ) / 1_000_000
    return {"prompt_tokens_total": total, "over_100k": total > 100_000, "est_cost_usd": cost}


def split_cache_writes(usage: object, default_ttl: str) -> tuple[int, int]:
    """(5m, 1h) cache-write tokens: the usage object's own split when it reports one, else all
    writes priced at `default_ttl` (the configured TTL)."""
    total = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    breakdown = getattr(usage, "cache_creation", None)
    one_h = getattr(breakdown, "ephemeral_1h_input_tokens", None)
    five_m = getattr(breakdown, "ephemeral_5m_input_tokens", None)
    if isinstance(one_h, int) and isinstance(five_m, int):
        return five_m, one_h
    return (0, total) if default_ttl == "1h" else (total, 0)
