---
name: Long-running verification jobs
description: How to run a job that exceeds the bash tool timeout when verifying things in this repl.
---

Bash tool calls cap at ~120s, and processes started with `&` / `nohup` / `setsid`
get reaped when the spawning bash tool call returns — so you cannot poll a
detached shell process across separate tool calls.

**Why:** the environment cleans up the bash session's children on tool return.

**How to apply:** for a job that legitimately runs minutes (e.g. an LLM pipeline
on a slow free model), write a small one-shot Python/JS script that writes its
result to a file (e.g. `/tmp/out.json`), register it as a temporary console
**workflow** via `configureWorkflow` (workflows are Replit-managed and persist),
then poll the output file in later bash calls. Remove the workflow when done.
