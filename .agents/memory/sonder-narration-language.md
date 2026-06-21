---
name: Sonder narration language resolution
description: How the narration language must be resolved once and threaded everywhere so narration text and translated lyrics never diverge.
---

# Narration language must be resolved once, then threaded everywhere

In "Auto" mode the UI passes `lang_name="Auto"` down the chat pipeline. Passing
that literal string into LLM prompt templates produces "Scrivi in Auto" — a
meaningless instruction — so the model guesses and **leaks the source language**
(English lyrics/bios bleed into the narration). Meanwhile the Musixmatch
*translated lyrics* were fetched from the router's `plan.narration_lang`, so the
two could end up in different languages.

**Rule:** resolve a single canonical narration language **once** in `run_chat`
(after the router plan + langdetect fallback) via
`resolve_narration_lang(plan, lang_name, lang_code)` in `backend/constants.py`,
which returns `(language_name, audiodb_code, musixmatch_code)`. Thread that one
result into **every** text producer AND the lyric translation:
`converse()`, `compose_musixmatch_response()`, `studio_brief()` (via
`build_studio`), and `search_musixmatch_from_plan(..., translation_lang=...)`.

**Why:** any path that recomputes its own language (e.g. the old
`search_musixmatch_from_plan` calling `_plan_translation_lang` internally)
reintroduces divergence — especially in explicit-language mode, where the UI
language should win but the router's `narration_lang` may differ.

**How to apply:** when adding any new LLM call or Musixmatch fetch in the chat
pipeline, take the language from the already-resolved tuple in `run_chat` — never
pass `lang_name`/"Auto" or re-derive from the plan. Prompt templates also carry
an explicit "write ONLY in {language} even if sources are in another language"
rule; keep that when editing them.

**"Auto" mode is fully removed.** The output ALWAYS follows the selected UI
language, even if the user types in another language. `resolve_narration_lang`
now unconditionally returns the UI language (legacy "Auto"/empty → English) and
IGNORES the plan's `narration_lang`; the langdetect fallback in `run_chat` is
gone. All `language == "Auto"` branches were stripped from storyteller
(`converse`, `plan_musixmatch_search`, `suggest_*_themes`) and the "Auto" keys
removed from constants' LANGUAGES/TTS_LANG/MXM/GREETINGS/REFUSALS/EXAMPLE_PROMPTS;
every `.get(..., X["Auto"])` fallback now points at the English entry. Don't
reintroduce an Auto sentinel or language detection — if you need a default, use
English. The router prompt still emits a `narration_lang` field but it is
intentionally ignored downstream.

**Frontend display rule (studio.html `showLyrics`):** the prominent `.lyr-translated`
slot must show ONLY the real UI-language translation (`translatedLines[idx]`). Do NOT
fall back to the song's original line (the old `translatedLines[idx] || original` /
`|| l`) — that leaked the song language into the translation slot whenever a line was
missing (no translation, or richsync-vs-plain line misalignment). The song text lives
only in the secondary `.lyr-original` line (needed for richsync word highlight); when
it's the only line, `.lyr-original:only-child` CSS makes it readable.
