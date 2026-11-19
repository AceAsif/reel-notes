# Progress - Fallback when the notes folder (Google Drive) is missing
Branch: fix/notes-folder-fallback
Last updated: 2026-11-19

## The problem (seen in a real chat)
Google Drive for desktop was not running, so drive G: did not exist. Every link failed with
"[WinError 3] The system cannot find the path specified: 'G:\\'". The cause: `save_note` made the
notes folder as its LAST step, after the download, Whisper and the AI. So the bot did 1-2 minutes of
work and then lost the result. Commands like /todo already said "folder missing", but capture did not.

## Done
- Step 1: `write_note_file`: write the note to the notes folder. If that fails (OSError: missing drive,
  offline Drive, no permission), write it to `notes/pending` on this PC and log the real error
  (`notes:` line in bot.log). `NOTES_PENDING_DIR` can change the folder. `notes/` is already private
  (.gitignore, deny rules, commit check).
- Step 2: `sync_pending`: when the notes folder is back, copy each pending note, check the size, then
  delete it from the PC. Never overwrites (a name that exists gets _2, _3). If a copy fails the note
  stays and it is tried again. The bot's 5-minute check (`run_due_jobs`) calls it and sends
  "Your notes folder is back. Moved N notes from this PC to it."
- Step 3: the Telegram reply warns when a note was kept on the PC. "I can't see your notes folder" now
  says new reels are still saved on this PC, and how many are waiting. /health shows them.
- Step 4: the duplicate check also looks in the pending folder.
- Step 5: 17 new tests (a folder on a drive that does not exist, the whole pipeline, moving back, name
  clashes, failed and bad copies, the messages). README: steps to bring Google Drive back, Troubleshooting
  row, `NOTES_PENDING_DIR`. Tests: 363 passed.

## Next step
- Owner: bring Google Drive back (see the README steps), pull, restart the bot.
- The reels that failed (4 links) were not saved. Send them again.

## Decisions
- Capture never depends on Google Drive any more. Reading (/todo, /search...) still needs the notes
  folder: notes waiting on the PC are not in /todo until they are moved.
- Fallback folder is inside the project's `notes/` folder, so no new private path is needed.
- Not done: a /sync command (the 5-minute check does it); showing pending notes in /todo.
