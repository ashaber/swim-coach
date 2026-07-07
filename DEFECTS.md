# Defects — swim-coach

Tracked defects to address opportunistically. Format: `D<n> — title (where found)`.

## Open

_(none)_

## Fixed

**D1** — Chat backend 400 when the research-logging path fires mid-conversation: `messages.N.content.1.text.parsed_output: Extra inputs are not permitted`.
  - Instance 1 (2026-07-06): `messages.5…` — after a fueling-during-swim follow-up ("fueled during swim but not sure how much…").
  - Instance 2 (2026-07-07): `messages.8…` — after "Did you note the headwind on return? Is there data for effects of headwind in open water swimming?" during a fueling/nutrition discussion. Different index, same shape.
  - **Root cause:** the tool-use loop (`backend/app/claude.py`) replayed the assistant turn via `block.model_dump()`, which serialized the SDK's null `parsed_output`/`citations` fields on text blocks; the API rejects those as *input* on the follow-up request. Only fires when the turn contains a tool call (e.g. `log_open_question`), so the turn has to be replayed — hence "whenever research-logging triggers," at whatever message index the tool call lands.
  - **Fix:** `model_dump(exclude_none=True)` drops the null SDK-only fields while preserving text/tool_use/thinking blocks. Regression test `test_replayed_assistant_content_drops_sdk_only_null_fields`; the API fakes now carry `parsed_output` like the real SDK so the fix is actually exercised. Branch `phase2.5/d1-parsed-output-toolloop`.
