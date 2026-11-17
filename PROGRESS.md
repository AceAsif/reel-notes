# Progress - Batch 4 (do-features)
Branch: feature/batch4-do-features
Last updated: 2026-11-17

## Done
- Step 1: Fixed the creator-offer pattern: "LinkedIn bio", "DM your manager", "link in your notes app"
  are real actions again. Added /undocleanup (puts back the last /cleanup; file cleanup_undo.json,
  in .gitignore).

## Next step
- Step 2: Save one, do one. Step 3: nudge with link + key points + Open note. Step 4: Get prompt.
  Step 5: search fix + usage counter. Step 6: docs, PR.

## Decisions
- /undocleanup only remembers the LAST clean-up. Actions you ticked since then stay as they are.
