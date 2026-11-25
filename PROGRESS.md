# Progress - Batch 5, item 3: "No repo found" instead of search links
Branch: feature/batch5-no-repo-found
Last updated: 2026-11-25

## Done
- Step 1: processor.py. `resource_line()` no longer builds a Google or GitHub search link. A resource with no
  real URL is shown as "Name — No repo found". Real links (and bare domains like `strix.ai/docs`) are kept.
  `enrich_with_github()` no longer sets the unused `search` flag. Unused `quote_plus` import removed.
- Step 2: tests. 3 old tests changed from "google.com/search" to "No repo found". New tests: no search link for
  bad or empty links, and a real repo link is kept. README updated. Tests: 532 passed.

## Next step
- Owner: merge, pull, restart. Send a reel that names a tool with no repo. The note should say "No repo found".

## Decisions
- Old notes keep their search links. Only new notes change.
- Non-code resources (books, websites) with no URL also say "No repo found". See to-do in the PR.
