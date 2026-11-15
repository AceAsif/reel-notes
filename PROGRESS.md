# Progress - Photo timeout fix, due dates, /plan for several notes
Branch: feature/due-dates-and-multi-plan
Last updated: 2026-11-15 22:40 (Hobart)

## Done
- Step 1: fix "Timed out" on photos (longer Telegram timeouts + 3 download retries)

- Step 2: due dates (/due), DUE SOON section in /todo, nudge + weekly review

- Step 3: /plan for several notes (/plan 1 3 5, /plan #tag), shorter resource lines in plans

## Next step
- Nothing; waiting for the user to merge the PR

## Decisions
- Due dates stored as '📅 YYYY-MM-DD' (Obsidian Tasks), due-soon = overdue..+2 days
- OCR of the accent image works; the error was Telegram's 5 s download limit
