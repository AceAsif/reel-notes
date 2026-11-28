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
