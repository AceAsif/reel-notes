# Progress - Batch 2: timing, stable numbers, catch-up, pick one action
Branch: claude/kind-wright-iffgne
Last updated: 2026-11-16 (Hobart)

## Done
- Step 1: timing per step (download, Whisper, OCR, AI) in bot.log and in the note reply [review 3.2, Top 5 #5 step A]
- Step 2: action ids no longer use line numbers; /todo numbers stay the same until the next /todo [B3, B19]
- Step 3: catch-up of missed nudge, weekly review, resurface, monthly summary and yt-dlp update [F6, B16]
- Step 4: AI asked for 0-3 actions, every step kept for roadmap reels, simple English;
  pick-one buttons under each new note [F2, F1]

## Next step
- Owner: merge the pull request, restart the bot, send 5 reels and note the ⏱ numbers
- Then decide from the timings: OCR clean-up (Top 5 #5 step B) or Whisper on GPU (step D)
- Still open from the review: real yt-dlp / Whisper errors (B11, B12), short words in search (B14),
  weekly clean-up of old actions (F4), /redo fast (F3)

## Decisions
- English only in notes, bot messages and prompts (owner's choice). Simple English.
- First start after this update sends no catch-up messages (it only records today's state)
- A missed daily nudge is not sent the next day (today's nudge comes anyway)
- Pick buttons use letters (A, B, C) so they are not mixed up with /todo numbers
- Max 3 real actions per note; creator offers ("comment X") stay as extra low-priority lines
