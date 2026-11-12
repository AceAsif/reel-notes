# Progress - Build remaining Reel Notes features
Branch: feature/remaining-features
Last updated: 2026-11-13 00:25 (Hobart)

## Plan (in this order)
1. Add tests, tidy duplicate env.example
2. Fix issues from the "5 plugins" test note: low-priority fallback, more actions, promo/"official" claims, stricter repo search
3. /renametag command
4. Record done dates + weekly stats in the Sunday digest
5. Daily nudge (one action each morning) + /nudge
6. Photo slides in carousel posts
7. Notes on phone: /file command + OneDrive/Drive guide in README
8. Final README, help text and BotFather command list

## Done
- Step 1: Added tests/test_processor.py (12 tests) and requirements-dev.txt; removed stray env.example (content moved into .env.example)

- Step 2: Low-priority fallback for bio/DM/comment/channel actions; prompt asks for 3-6 actions; claims must include "official" and "comment X / DM me" offers; MIN_SEARCH_STARS 50 -> 300 (6 new tests)

- Step 3: /renametag old new - renames or merges a tag in every note (1 new test)

- Step 4: Ticked actions now get a date (✅ done / ❌ skipped, Obsidian Tasks style); weekly_stats() + /stats command; Sunday digest starts with the stats (2 new tests)

- Step 5: Daily nudge at NUDGE_TIME (default 08:00) + /nudge; one action from the highest priority level, rotating daily; buttons Done / Skip / Another one (2 new tests)

## In progress
- (none)

## Next step
- Step 6: photo slides in carousel posts (download images, OCR them, include in the note)

## Decisions
- Nudge buttons identify actions by a short file hash + line number, so they still work after /todo numbers change. NUDGE_TIME=off turns the nudge off.
- Done/skip dates use Obsidian Tasks format (✅/❌ YYYY-MM-DD) so the notes also work with the Obsidian Tasks plugin. Actions ticked before this change have no date and aren't counted in stats.
- Search-only repo matches need 300+ stars: the 68-star 'claude-code-setup' was wrong; repos shown in the video/caption are still trusted.
- 'Follow' only counts as low priority for 'follow the creator', not 'follow the instructions'.
- Work on a feature branch; the user merges the Pull Request.
- Tests use stand-ins for Whisper/Tesseract/Ollama/GitHub so they run anywhere in under a second.

## Problems / questions for the user
- (none yet)
