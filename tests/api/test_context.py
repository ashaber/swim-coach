"""Unit tests for `app.context`: the cacheable system prefix must be
byte-identical across different user messages (no leaked per-request data),
and keyword routing must pick sensible library files."""

from __future__ import annotations

from swim_coach.store import FileStore

from app.context import (
    build_messages,
    build_per_request_context,
    build_routed_block,
    build_system,
    build_system_blocks,
    route_library_files,
)


def test_system_block_a_is_byte_identical_regardless_of_message(library_dir) -> None:
    # build_system_blocks takes no per-request argument at all -- calling it
    # twice with nothing to vary is the point: there is no code path by
    # which per-request data could leak in.
    block_1 = build_system_blocks(library_dir)
    block_2 = build_system_blocks(library_dir)
    assert block_1 == block_2


def test_system_block_a_has_cache_control(library_dir) -> None:
    blocks = build_system_blocks(library_dir)
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "CRITICAL SAFETY WARNING" in blocks[0]["text"]
    # reference_list.md's own bibliography content belongs in block B (it's
    # routed alongside topic files, not baked into the stable persona
    # block) -- block A only *mentions* the filename via INDEX.md's table.
    assert "Research Reference List" not in blocks[0]["text"]


def test_full_system_is_byte_identical_across_two_different_questions_in_same_bucket(
    library_dir,
) -> None:
    # Both route to 03-periodization.md via different keywords ("cut" vs "repeat").
    system_1 = build_system(library_dir, "why did this week get cut?")
    system_2 = build_system(library_dir, "why was this week repeated instead of advanced?")
    assert system_1 == system_2


def test_system_differs_across_different_buckets(library_dir) -> None:
    pace_system = build_system(library_dir, "what pace should I swim the long set at?")
    ow_system = build_system(library_dir, "what pace should I expect in a wetsuit?")
    # Block A (index 0) is identical; block B (index 1) differs by bucket.
    assert pace_system[0] == ow_system[0]
    assert pace_system[1] != ow_system[1]


def test_route_library_files_pace_question() -> None:
    files = route_library_files("What pace should I swim my Z2 set at?")
    assert "04-css-intensity-anchors.md" in files


def test_route_library_files_open_water_question() -> None:
    files = route_library_files("How should I adjust my pace for a wetsuit swim in chop?")
    assert "05-open-water-pace-inference.md" in files


def test_route_library_files_long_swim_question() -> None:
    files = route_library_files("How big should my next long swim be after the last milestone?")
    assert "06-long-swim-progression.md" in files


def test_route_library_files_default_bucket_when_no_keyword_matches() -> None:
    files = route_library_files("What's the weather like for swimming today?")
    assert files  # falls back to the default bucket, never empty
    assert "03-periodization.md" in files


def test_routed_block_always_includes_reference_list(library_dir) -> None:
    block = build_routed_block(library_dir, "what pace should I swim at?")
    assert "library/reference_list.md" in block[0]["text"]
    assert block[0]["cache_control"] == {"type": "ephemeral"}


def test_build_messages_shape_with_history(app_env) -> None:
    store = FileStore(base_dir=app_env)
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello!"},
    ]
    messages = build_messages(
        store, "renee", message="what's next?", history=history, expert_mode=False
    )
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert "## Athlete context" in messages[0]["content"]
    assert messages[0]["content"].endswith("hi")
    assert messages[1] == {"role": "assistant", "content": "hello!"}
    assert messages[2] == {"role": "user", "content": "what's next?"}


def test_build_messages_shape_without_history(app_env) -> None:
    store = FileStore(base_dir=app_env)
    messages = build_messages(store, "renee", message="hello coach", history=[], expert_mode=False)
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert "## Athlete context" in messages[0]["content"]
    assert messages[0]["content"].endswith("hello coach")


def test_per_request_context_reflects_expert_mode(app_env) -> None:
    store = FileStore(base_dir=app_env)
    expert_text = build_per_request_context(store, "renee", expert_mode=True)
    athlete_text = build_per_request_context(store, "renee", expert_mode=False)
    assert "expert" in expert_text.lower()
    assert "expert" not in athlete_text.lower().split("current week")[0]


def test_per_request_context_includes_summarize_rollup(app_env) -> None:
    store = FileStore(base_dir=app_env)
    text = build_per_request_context(store, "renee", expert_mode=False)
    assert "compliance_pct" in text
    assert "load_ratio_7d_28d" in text
