# Observability: telling what failed from the logs

Every service line is one JSON object on stdout (info/warn) or stderr (error) — Cloud Run turns each into a
Cloud Logging entry with the fields under `jsonPayload`.

## Two audiences, two views of one failure

| | Coach (model) | Operator (you, in Cloud Logging) |
|---|---|---|
| Storage read fails | `{"code": "storage_error", "what": "macro plan", "retryable": true, "what_to_do": ...}` — **no exception text** | `storage read failed` + `what`, `error_type`, `error`, `stack`, **`tool`, `athlete`, `input_summary`** |
| Tool crashes (a bug) | `{"code": "internal_error", "do_not_retry_same_call": true, "what_to_do": ...}` | `tool execution failed` + `tool`, `athlete`, `input_summary`, `error_type`, `stack` |
| One bad workout in a week write | note `NOT APPLIED (override #N, DATE): ...` or `detailed part ... could not be applied`; `not_applied` list in the result | `override entry failed` + `index`, `date`, `stack`, plus the tool context above |

The coach never sees driver/SQL text (it can leak hosts or credentials and only invites excuses); the operator
always gets the real cause and stack.

## Fields on every line emitted inside a tool call

`tool`, `athlete` (slug), `input_summary` (first 300 chars of the tool input). Set by
`tools._with_log_context`; applies to *every* log line a tool emits, including future ones.

Failure lines add: `error_type`, `error` (≤500 chars), `stack` (last 6000 chars).
The per-call summary line `tool call` carries `tool`, `had_error`, `error`, **`error_code`**, `persisted`.
The per-turn line `claude turn complete` carries `tools_invoked` and `tool_errors_so_far` (the failure tax).

## Queries (Logging Query Language)

Every failure, newest first:

    resource.type="cloud_run_revision" severity>=ERROR

What failed for one athlete:

    jsonPayload.athlete="renee" severity>=ERROR

All storage problems, and which resource:

    jsonPayload.msg="storage read failed"
    jsonPayload.what="macro plan"

Tool bugs (need a code fix):

    jsonPayload.msg="tool execution failed"

Week writes that degraded (one workout dropped to prose, the rest written):

    jsonPayload.msg="override entry failed"

Errors the coach saw, by kind:

    jsonPayload.msg="tool call" jsonPayload.error_code="storage_error"

Swallowed exceptions (a default was used; nothing failed visibly):

    jsonPayload.msg="swallowed exception, using a default"

## Caveat

Log context is a `ContextVar` set only around a plain synchronous call. Never hold `log_context` across a
generator `yield` — streaming responses run in per-call context copies, so the value would leak or vanish.
