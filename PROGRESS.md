# Progress - Chat mode (talk to the bot about your notes)
Branch: feature/chat-mode
Last updated: 2026-11-14 00:15 (Hobart)

## Plan
1. chat_reply(): find matching notes (this + previous message), friendly system prompt, recent history, local Ollama /api/chat
2. Bot: normal text messages go to chat mode (links still make notes), "typing..." indicator, sources list, /newchat to forget the conversation
3. README, help text, BotFather list

## Done
- Step 1: chat_reply() with relevant_notes() (shared with /ask), friendly "Reel Notes" system prompt that only uses facts from the notes, last 6 back-and-forth turns, Markdown cleanup (4 new tests)

- Step 2: Normal text messages go to chat mode (links still make notes, /commands unchanged); typing indicator; sources listed under the reply and usable with /note; friendly message if Ollama is off; /newchat; main() split into build_app() + main() so routing can be tested (8 new tests)

## In progress
- (none)

## Next step
- Step 3: README, BotFather list

## Decisions
- Message routing order matters: the link handler is registered before the chat handler, so a link is never treated as chat. A test checks this.
- Uses only the local qwen2.5:7b model through Ollama (free, private), as the user asked.
- Notes are found from the current AND previous user message, so follow-up questions work.
- temperature 0.4: a bit more natural than notes (0.2) but still careful.

## Problems / questions for the user
- (none yet)
