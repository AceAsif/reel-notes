# Progress - /tools command
Branch: feature/tools-command
Last updated: 2026-11-26

## Done
- Step 1: processor.py. New `all_tools()` reads the "## Resources" lines of every note in the notes folder
  and the pending folder (through `note_sections`). It returns (name, link or "No repo found", count).
  A tool counts once per note (case does not matter). Names ending "(unverified)" are skipped. An old
  Google or GitHub search link counts as "No repo found". Sorted by count, then name.
- Step 2: processor.py. New `split_messages(lines)` joins lines into messages of 4000 characters or less.
- Step 3: bot.py. New `/tools` command. Says "No tools found in your notes yet." when there are none.
  Added to the /start text, README and botfather-commands.txt.
- Step 4: tests: once per note, unverified skipped, old search link, pending folder, empty folder, long list
  split, empty reply. Tests: 541 passed.

## Next step
- Owner: merge, pull, restart. Paste the new BotFather list. Send /tools.

## Decisions
- Notes saved before item 2 have no "(unverified)" mark, so invented names in old notes still show.
- The first real link seen for a tool is shown.
