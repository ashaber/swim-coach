"""Thin wrapper over the `anthropic` SDK: builds the request, runs the
manual tool loop, streams text back to the caller as SSE-framed chunks.

Verified-current API usage (see this build's task brief for the exact,
checked patterns):
  - `client.messages.stream(model=..., max_tokens=MAX_TOKENS, system=[...],
    messages=[...], tools=[...])` as a context manager; `stream.text_stream`
    yields text deltas, `stream.get_final_message()` returns the full
    message (content blocks, stop_reason, usage) once the stream ends.
  - Never pass `temperature`, `top_p`, or `top_k` -- 400 on Sonnet 5.
  - `thinking` is passed EXPLICITLY: `{"type": "adaptive"}` for
    CLAUDE_THINKING=adaptive, `{"type": "disabled"}` for disabled. Never
    omitted (omission means adaptive on Sonnet 5 but OFF on Opus 4.7/4.8) and
    never `budget_tokens` (400 on the current models).
  - `stop_reason == "refusal"` is checked before any content is read.
  - `usage.cache_read_input_tokens` / `cache_creation_input_tokens` are
    logged every turn so cache hits are verifiable from the logs.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import anthropic

from app.config import Settings
from app.logging_config import get_logger
from app.tools import ToolHandler

log = get_logger(__name__)

MAX_TOOL_ITERATIONS = 5
# max_tokens caps thinking + text COMBINED. On Sonnet 5 with adaptive
# thinking, a hard question can spend >2048 tokens thinking alone, leaving
# zero text (seen in prod 2026-07-15: coach_smoke prompts b/c returned empty
# replies with stop_reason=max_tokens at exactly 2048 output tokens; Opus 4.8
# never hit this because omitted/disabled thinking left the full budget to
# text). 16384 leaves generous thinking headroom while still bounding the
# worst-case per-message output spend.
MAX_TOKENS = 16384


def build_request_kwargs(
    settings: Settings,
    system: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The exact kwargs sent to `client.messages.stream` -- factored out so
    tests can assert on its shape without touching the network."""
    kwargs: dict[str, Any] = {
        "model": settings.claude_model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
    if settings.claude_thinking == "disabled":
        kwargs["thinking"] = {"type": "disabled"}
    else:
        # "adaptive": pass it EXPLICITLY, never omit. Omitting is
        # model-dependent -- Sonnet 5 runs adaptive when `thinking` is
        # absent, but the Opus line (4.7/4.8) runs with NO thinking when it's
        # absent. An explicit {"type": "adaptive"} means adaptive on every
        # current model, so the config knob behaves the same regardless of
        # CLAUDE_MODEL.
        kwargs["thinking"] = {"type": "adaptive"}
    return kwargs


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


class ClaudeChat:
    """Holds the anthropic client + settings; `run_streaming` is the tool
    loop entry point used by `routes/chat.py`.

    `client` is injectable so tests never construct a real
    `anthropic.Anthropic()` -- pass a fake with a `.messages.stream(...)`
    context manager instead.
    """

    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None) -> None:
        self.settings = settings
        self.client = client if client is not None else anthropic.Anthropic(
            api_key=settings.anthropic_api_key
        )

    def run_streaming(
        self,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, ToolHandler],
    ) -> Iterator[str]:
        """Yields SSE-framed JSON lines (`"data: {...}\\n\\n"`).

        Each iteration streams one model turn. If the turn's `stop_reason`
        is `tool_use`, every `tool_use` block in the final message is
        executed via `tool_handlers`, and an assistant turn + a
        `tool_result` user turn are appended to `messages` before looping.
        The loop ends (and a final `done`/`refusal`/`error` event is
        emitted) once a turn's `stop_reason` isn't `tool_use`, or after
        `MAX_TOOL_ITERATIONS` turns (a runaway-tool-call guard).

        Thin wrapper over `_run_turns` (the shared tool-loop generator also
        used by `run_once`) -- SSE-frames each raw event dict it yields.
        """
        for event in self._run_turns(system, messages, tools, tool_handlers):
            yield _sse(event)

    def run_once(
        self,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, ToolHandler],
    ) -> str:
        """Non-streaming counterpart to `run_streaming`, for a caller that
        needs ONE complete answer string to persist (the direct-to-coach
        question endpoint, `POST /api/feedback/questions`) rather than an
        SSE stream to relay to a browser.

        Drives the exact same tool loop as `run_streaming` (via the shared
        `_run_turns` generator -- no duplicated loop logic), draining every
        `"text"` event and concatenating their `"text"` payloads into the
        final return value. `"tool_use"`/tool-execution side effects happen
        exactly as they already do in `run_streaming`.

        Error/refusal contract: if the turn sequence ends in a `"refusal"`
        or `"error"` event (or hits the max-tool-iterations guard, which
        itself yields an `"error"` event), this raises `RuntimeError` with
        that event's content as the message, rather than returning a
        string. Callers must catch `RuntimeError` explicitly and turn it
        into a clean error response (e.g. a 502) -- never let it become an
        unhandled 500. A plain-string-return contract was considered (e.g. a
        sentinel prefix) but rejected: an exception can't be silently
        mistaken for real model output the way a sentinel string could be if
        a caller forgets to check for it.
        """
        text_parts: list[str] = []
        for event in self._run_turns(system, messages, tools, tool_handlers):
            event_type = event.get("type")
            if event_type == "text":
                text_parts.append(event["text"])
            elif event_type == "refusal":
                raise RuntimeError("refusal")
            elif event_type == "error":
                raise RuntimeError(event.get("error", "unknown error"))
            elif event_type == "done":
                break
            # "tool_use" events are informational only here -- the actual
            # tool execution/side effects already happened inside
            # _run_turns before the event was yielded.
        return "".join(text_parts)

    def _run_turns(
        self,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, ToolHandler],
    ) -> Iterator[dict[str, Any]]:
        """Shared tool-loop generator behind both `run_streaming` (which
        SSE-frames each event) and `run_once` (which drains text events into
        one string). Yields raw event dicts -- `{"type": "text", "text":
        ...}`, `{"type": "tool_use", ...}`, `{"type": "done", ...}`,
        `{"type": "refusal"}`, or `{"type": "error", "error": ...}` -- with
        exactly the same shapes `run_streaming` has always emitted (SSE-
        framed) before this refactor, so its behavior/tests are unchanged.
        """
        messages = list(messages)

        for iteration in range(MAX_TOOL_ITERATIONS):
            request_kwargs = build_request_kwargs(self.settings, system, messages, tools)

            try:
                with self.client.messages.stream(**request_kwargs) as stream:
                    for text in stream.text_stream:
                        yield {"type": "text", "text": text}
                    final = stream.get_final_message()
            except anthropic.APIError as exc:
                log.error("anthropic api error", error=str(exc), iteration=iteration)
                yield {"type": "error", "error": str(exc)}
                return

            usage = final.usage
            log.info(
                "claude turn complete",
                iteration=iteration,
                stop_reason=final.stop_reason,
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0),
                cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0),
            )

            # Checked before any content is read, per the task's exact API
            # guidance -- a refusal's content shape isn't meant to be
            # processed as a normal answer or tool-use turn.
            if final.stop_reason == "refusal":
                yield {"type": "refusal"}
                return

            if final.stop_reason != "tool_use":
                yield {"type": "done", "stop_reason": final.stop_reason}
                return

            # exclude_none drops SDK-only null fields (a response TextBlock
            # carries parsed_output/citations that are None in ordinary chat);
            # replaying them verbatim makes the API reject the follow-up request
            # ("text.parsed_output: Extra inputs are not permitted"). Non-null
            # blocks -- text, tool_use, and thinking (which must be replayed on
            # thinking models mid-tool-use) -- are preserved intact.
            assistant_content = [block.model_dump(exclude_none=True) for block in final.content]
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                handler = tool_handlers.get(block.name)
                yield {"type": "tool_use", "name": block.name, "input": block.input}
                try:
                    result = (
                        handler(block.input) if handler else {"error": f"unknown tool {block.name}"}
                    )
                except Exception as exc:  # noqa: BLE001 - a tool bug must not crash the chat turn
                    log.error("tool execution failed", tool=block.name, error=str(exc))
                    result = {"error": str(exc)}
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        log.warn("max tool iterations exceeded", max_iterations=MAX_TOOL_ITERATIONS)
        yield {"type": "error", "error": "max tool iterations exceeded"}
