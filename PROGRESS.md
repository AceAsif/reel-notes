# Progress - Build remaining Reel Notes features
Branch: feature/remaining-features
Last updated: 2026-11-12 23:55 (Hobart)

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

## In progress
- (none)

## Next step
- Step 3: /renametag old new (rename or merge a tag across all notes)

## Decisions
- Search-only repo matches need 300+ stars: the 68-star 'claude-code-setup' was wrong; repos shown in the video/caption are still trusted.
- 'Follow' only counts as low priority for 'follow the creator', not 'follow the instructions'.
- Work on a feature branch; the user merges the Pull Request.
- Tests use stand-ins for Whisper/Tesseract/Ollama/GitHub so they run anywhere in under a second.

## Problems / questions for the user
- (none yet)
