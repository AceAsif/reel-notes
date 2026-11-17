# Progress - Batch 4 (do-features)
Branch: feature/batch4-do-features
Last updated: 2026-11-17

## Done
- Step 1: Fixed the creator-offer pattern: "LinkedIn bio", "DM your manager", "link in your notes app"
  are real actions again. Added /undocleanup (puts back the last /cleanup; file cleanup_undo.json,
  in .gitignore).

- Step 2: Save one, do one: after a new note, if nothing was ticked for 7 days, ask about ONE older
  action (Done / Drop it / Open note). At most once a day (state in bot_state.json).
- Step 3: The nudge now shows the link (a real one first, else the reel) and 2 key points, with an
  Open note button.
- Step 4: Get prompt: a button for 🤖 actions in the nudge, and /prompt 3.

- Step 5: Search keeps short topic words (ai, uv) and drops filler; /usage counts command names.
- Step 6: README, HANDOVER, BotFather command list (duplicate `plan` line removed).

## Next step
- Merge the PR, git pull, restart the bot. Add `undocleanup`, `prompt`, `usage` in BotFather.
- Use the bot for a week; check /usage; then decide which commands to hide.

## Decisions
- /undocleanup only remembers the LAST clean-up. Actions you ticked since then stay as they are.
