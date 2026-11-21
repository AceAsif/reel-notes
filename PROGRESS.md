# Progress - a new note never overwrites an older note
Branch: claude/gallant-johnson-lxv95t
Last updated: 2026-11-21

## Done
- Step 1: the bug. `save_note` names a file `YYYY-MM-DD_HHMM_<title>.md`. Two notes with the same title in
  the same minute (two reels sent together, or the same topic twice) had the same name, and the second one
  replaced the first. The first note and its actions were lost with no message.
- Step 2: the fix. New `_free_name(folder, name)` in processor.py gives `name.md`, or `name_2.md`,
  `name_3.md`... if the file is already there. `write_note_file` now always uses it, for the notes folder
  and for the pending folder. `sync_pending` uses the same helper (it did the same thing in its own loop).
  `save_note` is the only caller of `write_note_file`. `/redo` is not changed: it renames the old note to
  `.redo` first, so the new note still gets the normal name.
- Step 3: tests. No old test depended on the overwrite (all 432 passed after the fix). 2 new tests in
  tests/test_notes_fallback.py stop the clock and save 3 (and 2) notes with the same title: all are kept,
  named `..._2.md`, `..._3.md`, with their own source and actions. Both fail on the old code.
  Tests: 434 passed.

## Next step
- Owner: pull, restart. Send two reels about the same thing at the same time. Both notes should be there.

## Decisions
- No `keep_existing` flag: nothing needs to overwrite a note, so the safe way is the only way.
- A name is checked, then written. Two saves in the same split second could still clash. That is very
  unlikely for one person, and the fallback test fakes a broken folder through `Path.write_text`, so the
  write stays a plain `write_text`.
- graphify has no graph and no `graphify` command in this environment, so its rules could not be followed here.
