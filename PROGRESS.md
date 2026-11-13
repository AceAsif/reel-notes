# Progress - /remind command
Branch: feature/reminders
Last updated: 2026-11-13 23:40 (Hobart)

## Plan
1. Understand "when" in everyday words + save reminders to reminders.json
2. Bot: /remind N when, /reminders, /unremind N; send reminders on time with Done / Skip / Tomorrow buttons; reminders survive restarts; 🔔 shown in /todo
3. README, help text, BotFather list

## Done
- Step 1: parse_when() understands weekdays, today/tonight/tomorrow, next week, in N minutes/hours/days/weeks, 20/11, 20/11/2027, 2026-12-25, 25 dec, plus times (5pm, 17:30, morning); add/remove/load reminders in reminders.json (22 new tests)

- Step 2: /remind N when, /reminders, /unremind N; reminder message with Done / Skip / Tomorrow buttons; reminders reload on start-up (missed ones are sent ~15 s after start); 🔔 shown in /todo; ticking an action removes its reminder

- Step 3: README (remind commands, reading notes on a phone)

## In progress
- (none)

## Next step
- All steps done. User: merge the PR, git pull, restart the bot, try /remind, update BotFather

## Decisions
- A reminder missed while the PC was off is sent shortly after the bot starts again, not lost.
- Dates are day-first (20/11 = 20 November), as used in Australia.
- No time given = 9:00 am. "friday" said on a Friday after that time = next Friday.
- reminders.json lives in the project folder and is git-ignored (personal data).

## Problems / questions for the user
- (none yet)
