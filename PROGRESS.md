# Progress - YouTube Shorts/TikTok links and /ask
Branch: feature/shorts-and-ask
Last updated: 2026-11-13 22:35 (Hobart)

## Plan
1. Accept YouTube Shorts / YouTube / TikTok links; fix duplicate check for YouTube IDs; skip videos longer than MAX_MINUTES
2. /ask question: answer from your saved notes with the local AI, showing which notes it used
3. README, /start help, .env.example, BotFather list

## Done
- Step 1: LINK_PATTERN accepts youtube.com/shorts, youtube.com/watch, youtu.be, tiktok.com (incl. vm.tiktok.com); normalise_url keeps the YouTube video ID so watch?v=, shorts/ and youtu.be links match each other; MAX_MINUTES (default 10) skips long videos (15 new tests, new tests/test_bot.py)

- Step 2: /ask question - finds matching notes (any word, weak matches dropped), the AI answers ONLY from them or says it couldn't find it, and the reply lists the source notes for /note (5 new tests)

## In progress
- (none)

## Next step
- Step 3: README, /start help, .env.example (MAX_MINUTES), BotFather list

## Decisions
- /ask never calls the AI when no note matches, so it can't invent an answer from nothing; the reply always shows its sources with a reminder that AI can be wrong.
- Feature #3 ("you saved something similar") dropped at the user's request: a wrong match could make him miss a reel.
- Google Drive: use Google Drive for desktop + NOTES_DIR (already in README), not the Drive API (needs a Google Cloud project and keys).
- Normal YouTube videos are accepted too, but only up to MAX_MINUTES (default 10) so a 1-hour video doesn't block the bot.

## Problems / questions for the user
- Please test one YouTube Short and one TikTok link (the build environment can't reach them).
