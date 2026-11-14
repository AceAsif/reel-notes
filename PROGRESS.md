# Progress - Creator info + GitHub repo check
Branch: feature/creator-and-repo-check
Last updated: 2026-11-14 14:50 (Hobart)

## Plan
1. Save the creator (name, @handle, profile link) and a "From the creator" section with their offers (comment X, DM, link in bio); better promo filter; /plan puts offers in a "Backup if a link is wrong" part
2. Repo check: for GitHub links, show last update, licence, archived, and "not found" warnings
3. README

## Done
- Step 1: creator_from_info() from yt-dlp (uploader, uploader_id, uploader_url); "- Creator:" line in the note header; "## From the creator" section with offers (nothing deleted: offers stay as 🔽 low actions too); promo filter now catches 'MEMORY' in single quotes, CAPS keywords, "follow for more", "link in bio" but not "add a comment to your code" or "follow the instructions"; /plan moves offers + creator into a backup part (13 new tests)

## In progress
- (none)

## Next step
- Step 2: GitHub repo health (last update, archived, licence, not found)

## Decisions
- Nothing about the creator is ever removed from a note: offers are kept as low actions AND listed under "From the creator". Only the Claude prompt (/plan) moves them to a backup part, because Claude can't comment on Instagram.
- Instagram sometimes gives a number instead of a username: numbers are not shown as @handle.
- Old notes have no Creator line (it wasn't saved before); new notes will.

## Problems / questions for the user
- (none yet)
