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
  row, `NOTES_PENDING_DIR`.
- Step 6: merged `main` into this branch (it had the habit fix, #21). The only conflict was this file.
  Tests after the merge: 388 passed.

## Next step
- Owner: bring Google Drive back (see the README steps), pull, restart the bot.
- The reels that failed (4 links) were not saved. Send them again.

## Decisions
- Capture never depends on Google Drive any more. Reading (/todo, /search...) still needs the notes
  folder: notes waiting on the PC are not in /todo until they are moved.
- Fallback folder is inside the project's `notes/` folder, so no new private path is needed.
- Not done: a /sync command (the 5-minute check does it); showing pending notes in /todo.

---

# Earlier task (merged in #21): One idea, one to-do (habit and action duplicates)
Branch: fix/habit-action-duplicate

## The problem (seen in a real note)
A motivation reel gave a "Habit to try" AND an action with the same meaning ("Every morning, write
down one limiting belief..." and "Write down one belief that limits you..."). Both are open to-dos
(`open_actions` counts both sections), so /todo showed the same idea twice. /plan did too.

## Done
- Step 1: `similar_idea(a, b)`: two lines are the same idea when they share at least 3 words and at
  least 60% of the words of the shorter one. No AI. Words about WHEN ("every", "morning", weekdays,
  "one") and common filler words are ignored. Light stemming ("limiting", "limits" -> "limit").
- Step 2: new notes: `merge_habit_and_actions` (called in `summarise`). If the habit repeats an action,
  the action is dropped and the habit keeps ONE to-do with the action's priority and the 🧠 type,
  e.g. `- [ ] 🔥 🧠 Every morning, ...`. A repeated "other idea" is dropped too. A different action
  stays. The Telegram reply shows the habit once.
- Step 3: old notes: `/cleanup` counts and skips the pair ("dups"). It keeps the action and skips the
  habit, unless only the habit has a due date. A habit that repeats an action that /cleanup skips as an
  extra is not skipped (the idea stays once). Uses the normal confirm button and `/undocleanup`.
- Step 4: `/plan` lists a repeated line once.
- Step 5: 25 new tests, README. Tests: 371 passed.

## Decisions
- Deterministic rule (no AI call): fast, free and testable. Thresholds are in `similar_idea`.
- New notes keep the HABIT (it has the detail "every morning"); old notes keep the ACTION (it has the
  priority, type and maybe a due date, and the note is not rewritten).
- The prompt is not changed: the model's output is checked after the fact, which is more reliable.
- Not done: merging two different actions that look alike in different notes.
