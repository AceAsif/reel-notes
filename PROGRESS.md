# Progress - totals in /tools and a few bad entries
Branch: feature/tools-counts
Last updated: 2026-11-26

## Done
- Step 1: bot.py. /tools header: "Tools in your notes: N". /tools all header: "Everything in your notes: N"
  and one line with a count per type (tool, model, repo, language, course, company, channel, other).
- Step 2: tool_catalog.json. 8 non-tool names added to the stoplist. Aliases: ChachiBT -> ChatGPT,
  C-Dance 2.5 -> Seedance 2.5.
- Step 3: processor.py. Names that look like file names (.xlsx, .csv, .pdf, .docx, .pptx, .txt, .json,
  .zip) are dropped. This covers the spreadsheet name without putting it in the public repo.
- Step 4: tests for the headers, each new stoplist name, file names and the two aliases. Tests: 584 passed.
- Real notes: /tools 210 (was 221), /tools all 260 (was 271).

## Next step
- Owner: merge, pull, restart. Send /tools and /tools all.

## Decisions
- The spreadsheet name was not added to the stoplist: it has a location in it and the repo is public.
