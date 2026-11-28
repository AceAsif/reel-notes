# Progress - local chat simulator
Branch: feature/chat-sim (built on feature/chat-actions, which is not merged yet)
Last updated: 2026-11-28

## Done
- Step 1: tools/chat_sim.py. A message is routed by the real `bot.build_app()` handlers (the same
  handler Telegram would pick) and run with fake message objects. It prints the detected intent, the
  reply and the button labels. `--press "<label>"` presses a button. `--file` runs scenarios and prints
  a pass/fail table (exit code 1 if any fail).
- Step 2: safety. Each scenario gets a new temp folder with SAMPLE notes (no private note text is
  printed). All notes folders and state files point into it, are checked before anything runs, and are
  put back after. Only the local Ollama URL may be called; GitHub, Telegram and anything else is
  blocked. Links are not downloaded. `--copy-real-notes` (owner only) uses a temp COPY of the real notes.
- Step 3: tests/chat_scenarios.txt (Hallmark done, BLA skip, todo list, tools, no match, a question).
  A scenario fails on a wrong intent, missing reply text, a button that can't be pressed, or a chat
  reply that claims it changed something.
- Step 4: tests/test_chat_sim.py (AI mocked): all scenarios, sandbox paths restored, failures found,
  links skipped, network blocked, missing button. Tests: 648 passed.
- Step 5: CLAUDE.md: run the simulator after changing chat or intent code.
- Step 6: real run with local qwen3:8b on sample notes: 6 of 6 scenarios pass.
- Step 7: audit fixes.
  - `detect_intent` asks the AI only when the message has a task or command word (finish, done, did,
    skip, todo, list, stats, find, show, open, tools, dupe, twice...). "hello" makes one AI call, not two.
  - The claim guard also catches passive and short claims ("has been completed", "is marked",
    "is now done", "Done!", "all set"; "Well done!" is fine). The reply becomes: "I can't change tasks
    in chat. Try: I finished <task>, or /done."
  - New `catalog_maps()`: /tools and new notes build the catalog lookups in one place.
  - Deleted the unused `process_video`. `normalise_url` runs the Threads check once.
  - New scenario "I have completed the Hallmark task". Tests: 661 passed. Real run: 7 of 7 pass.

## Next step
- Owner: merge feature/chat-actions first, then this branch.

## Decisions
- Sample notes by default, because CLAUDE.md says Claude Code must never read the real notes.
