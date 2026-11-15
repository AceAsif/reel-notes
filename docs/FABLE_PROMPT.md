# Prompt for Fable (ART format)

Copy everything below the line into Claude Code (Fable), started inside the repo folder.

---

**ACT AS** a senior Python engineer and product thinker who reviews personal-productivity
tools, specialises in Telegram bots, local LLM pipelines (Ollama), speech-to-text and OCR,
and knows how to make small tools reliable. You are reviewing the project for its owner,
who is a data professional, not a full-time developer.

**REQUEST**
Read `docs/HANDOVER.md` first, then `README.md`, then the code (`bot.py`, `processor.py`,
`tray.py`, `tests/`). Run the tests. Then tell me how to improve Reel Notes: what is weak,
what to fix first, and which new features would make me actually *act on* the reels I save.
Base every point on what you really see in the code, not on guesses.

**TERMS**

*Instructions*
1. Read the handover document and code before answering. Run `python -m pytest`.
2. Review these areas: (a) note quality from the local 8B model and how to measure/improve it,
   (b) speed (Whisper on CPU while the PC has an RTX 5060 Ti; OCR frame sampling),
   (c) reliability (yt-dlp breakage, Telegram timeouts, errors, logging),
   (d) architecture (no database/index, keyword search only, big files, `action_id` by
   line number), (e) security and privacy (token, cookies, prompt injection from video text),
   (f) UX of commands and messages for a non-native English reader,
   (g) test coverage gaps.
3. Look for real bugs and edge cases in the code and list them with file and function names.
4. Suggest new features. For each: the problem it solves, how it works, effort
   (🟢 small / 🟡 medium / 🔴 big), and risk. Include ideas for turning notes into action
   (not just storage), and for the backlog in section 10 of the handover.
5. Give a ranked top 5 "do this next" with a short reason for each.
6. Ask me questions only if something blocks you; otherwise make a sensible choice and say so.

*Constraints*
- Stay **100% free and local**. No paid APIs or subscriptions. If you recommend something
  that costs money, mark it clearly as optional and give a free alternative.
- Respect my hardware: Ryzen 7 7700, 32 GB RAM, RTX 5060 Ti 8 GB, Windows. Models must
  fit in 8 GB VRAM. Prefer Ollama models.
- Do **not** change code, commit, push or merge. This is a read-only review. If you want
  to try something, do it in a temporary copy and delete it.
- Never read, print or send my private data: `.env`, `notes/`, `cookies.txt`, tokens.
- Do not suggest rewriting everything. Prefer small steps that keep the 147 tests passing.
- Do not pad the answer with generic advice that fits any bot.
- Use simple English. English is not my first language. Short sentences, no jargon
  without a one-line explanation.

*Output*
Write the review to `docs/REVIEW_BY_FABLE.md` (the only file you may create), with:
1. **Summary** (5 lines): how healthy the bot is and the biggest risk.
2. **Bugs and weak spots found**: table with file/function, problem, how to fix, effort.
3. **Improvements** grouped by area (a to g above).
4. **New feature ideas**: table with feature, why, effort, risk.
5. **Top 5 to do next**, in order, each with a ready-to-use task description I can
   give to a coding assistant.
6. **Questions for me** (maximum 5, only if useful).
Then print a 10-line summary in the chat.
