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
# Progress - chat task matching finds words anywhere in the note
Branch: fix/chat-task-matching
Last updated: 2026-11-28

## Done
- Step 1: the problem. "I have completed the Hallmark task" found nothing: `match_actions` only looked at the
  action text and the note title, and "Hallmark" was only in a resource link (github.com/Nutlope/hallmark).
- Step 2: processor.py. `match_actions` now looks at the action text and title (3 points a word), the file
  name without its date (2), and the summary, tags and resource names and links (1). Small typos still
  match. Filler words are ignored (the, task, one, I, have, completed, finished, done, skip...).
  Any match counts; the best come first, up to 5.
- Step 3: new `closest_actions`: when nothing matches, the 5 open actions most like the words.
- Step 4: bot.py. One match: "Tick this off?" with Yes / Not this one / Cancel (as before). Several
  matches (one note or many): one button per action (up to 5) and Cancel. No match: "Is it one of these?"
  with the 5 closest actions and Cancel. Pressing an action button only shows the Yes / Cancel question
  for it; a task changes only after "Yes".
- Step 5: tools/chat_sim.py sample notes: Hallmark only in Resources, "orbit" only in the file name,
  "Remotion" in two notes. Scenarios can press several buttons ("A >> B"). New scenarios for each.
- Step 6: tests (resources, file name, summary, tags, ranking, filler words, pick list, one note with two
  actions, 5 closest + Cancel). Tests: 666 passed. Simulator (local qwen3:8b): 9 of 9 pass.

- Step 7: merged main (PR #39, no more empty Action items). Only PROGRESS.md had a conflict; both
  logs are kept (main's is in git history).

## Next step
- Owner: merge, pull, restart. Say "I have completed the Hallmark task".

## Decisions
- An action button asks Yes / Cancel before it ticks, so one wrong tap changes nothing.
