# Progress - a new note never overwrites an older note
Branch: claude/gallant-johnson-lxv95t
Last updated: 2026-11-22

## Done
- Step 1: the bug. `save_note` names a file `YYYY-MM-DD_HHMM_<title>.md`. Two notes with the same title in
  the same minute (two reels sent together, or the same topic twice) had the same name, and the second one
  replaced the first. The first note and its actions were lost with no message.
- Step 2: the fix. `save_note` and `write_note_file` now default to `keep_existing=True`: they use
  `_free_name(folder, name)`, which gives `name.md`, or `name_2.md`, `name_3.md`... if the file is already
  there. This works for the notes folder and for the pending folder. `sync_pending` uses the same helper.
  `/redo` is not changed: it renames the old note to `.redo` first, so the new note gets the normal name.
  `/redo fast` already passed `keep_existing=True`.
- Step 3: tests. No old test depended on the overwrite. 2 new tests in tests/test_notes_fallback.py stop
  the clock and save 3 (and 2) notes with the same title: all are kept, named `..._2.md`, `..._3.md`,
  with their own source and actions. Both fail on the old code.
- Step 4: merged main (with /redo fast) into this branch and fixed the conflicts in processor.py.

## Next step
- Owner: merge the pull request. Pull, restart. Send two reels about the same thing at the same time.
  Both notes should be there.

## Decisions
- `keep_existing` stays (main uses it), but `True` is now the default. Nothing in the code passes `False`.
- A name is checked, then written. Two saves in the same split second could still clash. That is very
  unlikely for one person, and the fallback test fakes a broken folder through `Path.write_text`, so the
  write stays a plain `write_text`.
- graphify has no graph and no `graphify` command in this environment, so its rules could not be followed here.
