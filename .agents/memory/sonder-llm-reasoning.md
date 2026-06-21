---
name: Sonder LLM reasoning effort / latency
description: Why every LLM call sends reasoning effort low, and how the param fallback works.
---

# Sonder LLM reasoning effort & latency

`Storyteller` defaults `reasoning_effort="low"` and sends
`extra_body={"reasoning": {"effort": ...}}` on every chat.completions call.

**Why:** without it, `openai/gpt-oss-120b` (OpenRouter) emits huge chain-of-thought
(reasoning_len ~20k-30k) and a single call runs 100-515s. A `/api/chat` makes
several sequential calls, so total blows past the Replit dev-proxy timeout and the
preview shows "We couldn't reach this app" (the proxy fallback, not an app crash).
The SDK `timeout=60s` does NOT abort these — it's a per-read timeout, so as long as
tokens keep dribbling the connection stays alive. Low effort dropped a converse
call from ~100-515s to ~10-50s.

**How to apply:** `_complete()` retries on failure dropping ONLY the offending
param — `temperature` (reasoning models reject it) and/or `reasoning`/`extra_body`
(OpenAI-compatible endpoints that don't support reasoning controls). Keep that
graceful degradation so swapping LLM_MODEL/LLM_BASE_URL to a non-reasoning target still
works. To make it tunable, thread reasoning_effort from settings.
