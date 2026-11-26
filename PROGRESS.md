# Progress - clean the /tools list
Branch: feature/tools-cleanup
Last updated: 2026-11-26

## Done
- Step 1: new `tool_catalog.json` in the repo root: aliases (Higgs Field, Higgsfield.ai, Higgsfield MCP ->
  Higgsfield), official links for popular tools, a stoplist (generic phrases and lighting terms), and a type
  for each entry (tool, model, repo, language, course, company, channel, other).
- Step 2: processor.py. `all_tools()` = `raw_tools()` (reads notes) + `clean_tools()` (pure, tested). Rules:
  - Names are grouped without case, spaces or punctuation ("Claude-Mem" = "Claude Mem"). Count = notes.
  - "X GitHub", "X GitHub Repo", "X Website", "X Docs", "X Documentation", "X Integrations", "X Example"
    fold into "X". Their link is preferred as X's link.
  - "GitHub Repository" / "GitHub repo" take the repo name from the link; without a GitHub link they drop.
  - A link is dropped if 3+ different tools use it, if it is an API endpoint (api./mcp. hosts,
    googleapis.com, /api/, /v1...), or if it is not a web address (.pdf, spaces, %20, |, t.co, tinyurl...).
  - Catalog link wins. Type: catalog, else channel / course by name, else repo for a GitHub link, else tool.
- Step 3: bot.py. `/tools` shows tool, model and repo only. `/tools all` shows everything with [type].
  /start, README and botfather-commands.txt updated.
- Step 4: tests for each rule, plus a check that the real catalog loads. Tests: 572 passed.
- Real notes: before 353 entries, after 221 in /tools (271 in /tools all). No saved note was changed.

## Next step
- Owner: merge, pull, restart. Send /tools and /tools all. Add missed names to tool_catalog.json.

## Decisions
- No people's names from the notes are in the catalog (the repo is public). Channels are found by
  "YouTube Channel" / "on Instagram" in the name instead.
- Unknown names default to "tool", so new non-tools still show until added to the stoplist.
