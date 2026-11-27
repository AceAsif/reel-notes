# Progress - clean the Resources list when a new note is made
Branch: feature/clean-resources-at-source
Last updated: 2026-11-28

## Done
- Step 1: the note prompt (processor.py) asks for named software, apps, AI models and repos only, by the
  product's own name. No techniques, companies, courses, generic topics or programming languages.
- Step 2: new `clean_resources()` runs on every new note, with the same catalog as /tools: aliases give
  one name (two aliases of one tool become one line), the stoplist and file names are dropped, catalog
  types other than tool, model and repo are dropped, and the catalog link is used when there is one.
  Any other link stays only if the video showed it (`drop_invented_links`) and it is a real web address
  (no shortener, API endpoint or .pdf). A shown bare domain like `strix.ai/docs` gets `https://`.
- Step 3: a resource with no link now says "No link found" (was "No repo found"). /tools reads both.
- Step 4: fix: `mark_unverified_names` was no longer called in `summarise()` (lost in a merge), so new
  notes did not mark invented names. It runs again, before the alias step.
- Step 5: tool_catalog.json: "Claw Code" and "clodcode" -> Claude Code; "react3-fiber" -> React Three
  Fiber (https://github.com/pmndrs/react-three-fiber).
- Step 6: tests for each rule, the full summarise() path (Ollama and GitHub mocked) and the prompt.
  README updated. Old notes are not changed. Tests: 627 passed.

## Next step
- Owner: merge, pull, restart. Send a tech reel and check the Resources list.

## Decisions
- GitHub lookup (`enrich_with_github`) still runs after the clean-up, as before, for tech notes with no link.
