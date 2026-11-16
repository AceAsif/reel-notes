# Progress - Batch 1: safety and small bugs (from Fable's review)
Branch: fix/batch1-safety-and-small-bugs
Last updated: 2026-11-16 (Hobart)

## Done
- Step 1: AI output is validated (clean_note_fields, JSON schema for Ollama, one retry, clear error) [B1, B2]
- Step 2: small bugs: links without https kept (B5), repo name with trailing dot (B6), /retag duplicate Tags line (B7),
  video caption no longer saved as Source (B8), edited messages ignored (B4), tray uses NOTES_DIR (B10),
  clear message when the notes folder is missing (B9)
- Saved Fable's review as docs/REVIEW_BY_FABLE.md

## Next step
- Batch 2: stable /todo numbers + safer action IDs (B3, B19)
- Then: catch-up of missed nudge/review when the PC starts (F6, now high priority: the PC is not on at a fixed time)
- Then: fewer actions + 'pick one' buttons (F2, F1)

## Decisions
- Owner ticks actions in Telegram only, so stable numbers (B3) matter more than hand-edit safety (B23)
- Owner has 205 open actions from 48 reels (about 4 per reel): fewer actions per reel is the main product fix
