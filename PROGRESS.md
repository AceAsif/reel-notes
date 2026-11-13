# Progress - /remind command
Branch: feature/reminders
Last updated: 2026-11-13 23:15 (Hobart)

## Plan
1. Understand "when" in everyday words + save reminders to reminders.json
2. Bot: /remind N when, /reminders, /unremind N; send reminders on time with Done / Skip / Tomorrow buttons; reminders survive restarts; 🔔 shown in /todo
3. README, help text, BotFather list

## Done
- Step 1: parse_when() understands weekdays, today/tonight/tomorrow, next week, in N minutes/hours/days/weeks, 20/11, 20/11/2027, 2026-12-25, 25 dec, plus times (5pm, 17:30, morning); add/remove/load reminders in reminders.json (22 new tests)

## In progress
- (none)

## Next step
- Step 2: bot commands and the scheduled reminder messages

## Decisions
- Dates are day-first (20/11 = 20 November), as used in Australia.
- No time given = 9:00 am. "friday" said on a Friday after that time = next Friday.
- reminders.json lives in the project folder and is git-ignored (personal data).

## Problems / questions for the user
- (none yet)
