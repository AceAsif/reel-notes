# Progress - Small improvements + /plan
Branch: feature/small-improvements
Last updated: 2026-11-14 13:40 (Hobart)

## Plan
1. Chat fixes: follow-ups reuse the previous notes; no invented steps; mention unverified claims
2. /todo in pages (10 per page, Prev/Next buttons) + /todo high|normal|low filter
3. /plan N: turn a note into a ready-to-paste Claude prompt (ART format)
4. Resurface an old note once a week
5. Monthly learning summary (1st of each month) + /month
6. README, help text, BotFather list

## Done
- Step 1: is_follow_up() so "which one first?" reuses the previous question's notes; chat prompt forbids invented steps/settings and flags "Claims to check" (8 new tests)

## In progress
- (none)

## Next step
- Step 2: /todo pages with buttons

## Decisions
- /plan added to this batch: the user asked about it and it's small.
- Follow-up = short message (<= 4 meaningful words) with a pointing word (it, that, which, first, more...).

## Problems / questions for the user
- (none yet)
