---
name: Sonder deployment target
description: Why Sonder's chat must deploy on Reserved VM, not Autoscale
---

The `/api/chat` pipeline makes 3-4 sequential LLM calls (router → critic ∥ studio brief)
plus Musixmatch/TheAudioDB lookups. A single healthy request takes ~75s end-to-end
even with a fast paid model.

**Rule:** Deploy Sonder as Reserved VM (`deploymentTarget = "vm"`), not Autoscale.

**Why:** Autoscale truncates requests past its per-request limit. In production the
chat request would start (`[LLM] → POST`) and get killed before any `← OK`, so the
frontend hung on the POST forever. Reserved VM has no per-request duration cap.

**How to apply:** If chat "hangs with no response" in production, check the deploy
target first. Also avoid OpenRouter `:free` models — they often never return at all
(the paid `openai/gpt-oss-120b` returns reliably ~15s/call). LLM_MODEL lives in
.replit [userenv.shared] and DEFAULT_LLM_MODEL in core/config.py — keep them in sync.
