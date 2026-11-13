# Progress - YouTube Shorts/TikTok links and /ask
Branch: feature/shorts-and-ask
Last updated: 2026-11-13 22:15 (Hobart)

## Plan
1. Accept YouTube Shorts / YouTube / TikTok links; fix duplicate check for YouTube IDs; skip videos longer than MAX_MINUTES
2. /ask question: answer from your saved notes with the local AI, showing which notes it used
3. README, /start help, .env.example, BotFather list

## Done
- Step 1: LINK_PATTERN accepts youtube.com/shorts, youtube.com/watch, youtu.be, tiktok.com (incl. vm.tiktok.com); normalise_url keeps the YouTube video ID so watch?v=, shorts/ and youtu.be links match each other; MAX_MINUTES (default 10) skips long videos (15 new tests, new tests/test_bot.py)

## In progress
- (none)

## Next step
- Step 2: /ask command (find relevant notes by keywords, ask Ollama to answer ONLY from them, list sources with /note numbers)

## Decisions
- Feature #3 ("you saved something similar") dropped at the user's request: a wrong match could make him miss a reel.
- Google Drive: use Google Drive for desktop + NOTES_DIR (already in README), not the Drive API (needs a Google Cloud project and keys).
- Normal YouTube videos are accepted too, but only up to MAX_MINUTES (default 10) so a 1-hour video doesn't block the bot.

## Problems / questions for the user
- Please test one YouTube Short and one TikTok link (the build environment can't reach them).
