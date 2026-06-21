---
name: Sonder run_chat 2-call pipeline
description: The chat playlist path costs exactly 2 LLM calls; how the reply text is sourced and why a slow studio_brief can appear to hang.
---

# run_chat playlist path = exactly 2 LLM calls

After the Musixmatch search, the playlist path makes only two LLM calls:
- `plan_musixmatch_search(...)` — the search router/query writer.
- `studio_brief(...)` inside `build_studio(...)` — one call that produces ALL
  narrations + the playlist `summary` + moods.

The chat bubble text **reuses `studio.summary`** (falling back to
`compose_track_list_reply(tracks)` if empty). There is NO separate
"response writer" call anymore — `compose_musixmatch_response` still exists in
`core/storyteller.py` but is unused by `run_chat`. Do not reintroduce it as a
third call without a deliberate reason.

**Why:** cut latency and rate-limit pressure. The two phases used to run
concurrently; now there is only one expensive enrichment+narration phase.

**Invariant:** every early-return / no-results branch in `run_chat` must set
non-empty `assistant.content` (the no-tracks branch returns a deterministic
"no matching tracks" message). An empty reply renders as a blank chat bubble.

# A slow studio_brief can look like a multi-minute hang

The OpenAI SDK auto-retries timeouts (~2 retries × the per-call `timeout`, default
60s ⇒ up to ~3 min) before raising. On the throttled free OpenRouter provider, a
large `studio_brief` prompt (many tracks with long lyrics) can therefore appear to
"hang" for minutes with no `[LLM] ←` line, then fail — this is SDK retry
amplification, not a code bug. To fail faster, lower `max_retries` on the client.

**How to apply:** when chat seems stuck mid-request, check whether it's a single
large studio_brief call retrying, not a deadlock. Concurrency for the data
lookups in `build_studio` is capped at `min(3, len(enriched))` to avoid
TheAudioDB/Musixmatch burst rate limits.
