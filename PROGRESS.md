# Progress - "Already saved" shows which note and when
Branch: feature/already-saved-details
Last updated: 2026-11-27

## Done
- Step 1: bot.py. The warning now shows the note title, file name, when it was saved and the folder
  (notes folder or pending folder). Saved time: the note's Date line or file name (written with the PC
  clock); if neither has a date, the file time in TIMEZONE from .env.
- Step 2: buttons Save again, Show old note, Cancel.
  - Show old note sends the note text in chat, split into parts under Telegram's limit. The warning and
    the link stay, so Save again still works after it.
  - Cancel: "Kept the old note: <file>, saved <date and time>. Nothing downloaded."
  - File moved or missing (on Show old note): says so and offers Save again and Cancel.
  - Video and screenshot messages show the same details, without buttons.
- Step 3: processor.py. `split_messages` now cuts a very long line (a transcript) into parts instead of
  cutting it off, so no text is lost.
- Step 4: tests: details text, pending folder, Save again, Show old note, Cancel, missing file, long
  note. README updated. Tests: 588 passed.

## Next step
- Owner: merge, pull, restart. Send a saved link again and try each button.

## Decisions
- The saved time comes from the PC clock, so it is right when the PC uses the same zone as TIMEZONE.
- A long note is sent as plain text, split in parts. /file still sends the note as a file.
