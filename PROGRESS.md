# Progress - /redo keeps one file, and links inside a repo join the repo line
Branch: fix/redo-and-repo-links
Last updated: 2026-11-28

## Done
- Step 1: the problem. /redo moved the old note into an `old/` folder inside the notes folder and saved
  the new note under a new name, so a notes app showed two copies.
- Step 2: processor.py. New `replace_note(old, old_text, new)`: the new text goes into the old file (same
  name, same place), done and skipped to-dos and learnings are carried over, the just-saved file is
  removed, and on any error the old text is put back. Used by /redo fast (`redo_from_saved`) and by the
  full /redo button (bot.py). `archive_note` and `OLD_DIR_NAME` are gone. The link index sees the
  file list change and rebuilds, so the video points at the same file. Full /redo now also keeps done
  and skipped actions (before, it did not). Existing `old/` folders are not touched.
- Step 3: processor.py. New `fold_repo_links`: a link inside a GitHub repo (blob/, tree/...) joins that
  repo's resource line as "· also: <link>". The repo's own link leads. /tools still reads the line.
- Step 4: tests for replace_note (keeps file and history, rolls back), the bot /redo button, fast /redo
  (same file, no second copy, link index), repo links. Tests: 677 passed.

## Next step
- Owner: merge, pull, restart. Try /redo on a note and check there is still one file.

## Decisions
- The file name stays the same even when the AI gives a new title (the title inside changes).
