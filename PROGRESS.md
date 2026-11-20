# Progress - Done, with one line of what I learned
Branch: feature/done-with-learning
Last updated: 2026-11-20

## Done
- Step 1: note format. A done action can have one indented line under it: `  - 💡 Learned: text`.
  `add_learning(note_name, action_text, learning)` finds the done line (icons, due date and the ✅ date
  do not matter; the newest tick wins if the same text was ticked twice), puts the line right under it,
  and replaces an older answer. `clean_learning` makes ONE plain line (no new lines, no leading bullet,
  max 300 characters, "skip"/"no"/"nothing" = nothing to save). The line starts with two spaces, so it is
  never a to-do, an action or a heading. It also works for a note still waiting on the PC.
- Step 2: the question. After ONE Done (the nudge or reminder button, or `/done 3`), the bot asks "What did
  you learn? Reply to this message with one line." with a `ForceReply`. `/done 1 3 4` and `/skip` do not ask.
  `ASK_LEARNING=off` turns it off.
- Step 3: the answer. Only a REPLY to that question is saved (`chat` checks `reply_to_message`), so a normal
  chat message is never taken by mistake. "skip" saves nothing. If the notes folder cannot be reached, the
  question stays and you can reply again later. The bot remembers the last 20 questions (memory only).
- Step 4: `/month` shows what you learned (last 5). `stats_between` has a `learned` list.
  Chat, `/ask` and `/search` find it because it is in the note.
- Step 5: 44 new tests; the shared fake message in tests/test_bot.py now has `reply_to_message` and a
  `reply_text` that returns a message (like Telegram). README, HANDOVER (format line), `.env.example`.
  Checked with the real Telegram classes: the ForceReply is valid and a reply goes to the chat handler.
  Tests: 432 passed.

## Next step
- Owner: pull, restart. Tick one action (`/done 1` or the Done button). Reply to the question. Open the
  note with `/note` and look for the 💡 line. Then send `/month`.

## Decisions
- Reply-only (not "the next message"): a chat message right after a Done must stay a chat message.
- No question for many Dones at once or for Skip: no nagging. It can be switched off.
- The questions are remembered in memory only: after a restart an old question gets no answer. That is fine.
- Not done: a learning for an action ticked by hand in the note file.
- graphify (added by the owner) has no graph and no `graphify` command in this environment, so its rules
  could not be followed here.
