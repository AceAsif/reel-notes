# Progress - no more empty Action items
Branch: fix/empty-action-items
Last updated: 2026-11-28

## Done
- Step 1: the cause. Only two steps can empty the list: the note prompt allowed `[]` ("Use [] if nothing
  is worth doing"), and `split_actions` moves "Comment X to get the link" actions to "From the creator".
  When that was the AI's only action, nothing was left. The claim filter, the unverified-name check and
  `clean_resources` never touch actions. (The real note was not opened, so which of the two hit is not
  known for sure.)
- Step 2: the prompt asks for 1-2 actions and says bait like "comment X" is not an action.
- Step 3: new `ensure_action` at the end of `summarise`: no action left (and no habit) -> ask the AI once
  more with the title, summary and main resource. Still none -> "Try <main resource>: <link>", or
  "Review this note" with no resource. It logs a warning and the Telegram reply says
  "⚠️ No action found, added a default".
- Step 4: new `drop_link_borrowers`: when two resources share one link, a name the video never said
  ("Relay Example" on screen, pointing at the Hallmark repo) is dropped.
- Step 5: new `collapse_repeats` in `transcribe`: a transcript said twice word for word, or one sentence
  repeated many times in a row, is kept once. Short real repeats ("no no no") stay.
- Step 6: tests for each case (bait-only action, retry, fallback with and without a resource, AI down,
  habit note, shared link, repeated transcript, Telegram notice). Old notes are not changed.
  Chat simulator (local qwen3:8b): 7 of 7 pass.
  Tests: 673 passed.

## Next step
- Owner: merge, pull, restart. Send the Hallmark reel again with /redo.

## Decisions
- The retry costs one more AI call, only for notes that would have had no action.
