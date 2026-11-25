# Progress - Batch 5, item 2: check tool names against the transcript
Branch: feature/batch5-verify-tool-names
Last updated: 2026-11-25

## Done
- Step 1: processor.py. New `mark_unverified_names(resources, source_text)`. It runs in `summarise()` after
  `drop_invented_links`. A resource whose name is not in the transcript, on-screen text or caption gets
  `unverified: True`. Names are compared with `squash()`, so "claude-mem" matches "Claude mem".
- Step 2: `resource_line()` shows such a name as "Name (unverified)". `enrich_with_github()` skips it, so no
  GitHub search runs for an invented name.
- Step 3: test with one real name and one invented name. Tests: 531 passed.

## Next step
- Owner: merge, pull, restart. Send a tech reel. Names the video never says should show "(unverified)".

## Decisions
- Mark, not remove: Whisper and OCR can misspell a real name, so removing it would lose real tools.
