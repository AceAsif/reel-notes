# Progress - do tasks by chatting in plain English
Branch: feature/chat-actions
Last updated: 2026-11-28

## Done
- Step 1: processor.py. `detect_intent(message)` asks the local model (JSON schema) for one intent:
  done, skip, todo, stats, find_note, show_note, dupes, tools or chat, plus the task or search words.
  An unknown answer means chat.
- Step 2: processor.py. `match_actions(words)` finds open actions by action text and note title, with
  light fuzzy matching for typos ("halmark"). Filler words like "task" and "one" are ignored. Up to 3.
- Step 3: bot.py. `chat()` asks for the intent first. If the AI is down, it falls back to normal chat.
  - done / skip: shows the best match with "Yes, tick it", "Not this one" (next match), "Cancel".
    Only "Yes" changes the note, through `complete_actions` (the same code as /done and /skip).
    Reply: "✅ Ticked: <action> (from <note title>)". Done still asks "What did you learn?".
    No match: says so and points to /todo.
  - todo, stats, dupes, tools: the command handlers themselves. find_note: `send_search` (split out of
    /search). show_note: `send_note` (split out of /note) on the best search result.
- Step 4: chat system prompt says the bot cannot change tasks or notes and must suggest a command.
  A reply that still claims "I've marked / ticked / skipped..." is replaced with that advice.
- Step 5: tests/test_chat_actions.py (Ollama mocked): Hallmark done, BLA skip, todo list, stats, dupes,
  find and show note, no match, two matches, Cancel, typo, odd intent, no claimed action, AI down.
  conftest.py now blocks every real Ollama call in tests. README updated. Tests: 642 passed.

## Next step
- Owner: merge, pull, restart. Say "I finished the <task> task" and press Yes.

## Decisions
- Every chat message now makes one extra short AI call (the intent), so chat replies are a little slower.
- A button press acts on the action's id, so it still works if /todo numbers changed in between.
