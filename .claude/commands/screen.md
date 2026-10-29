---
description: Screen every company on BME Growth with the agents (C1-C7)
argument-hint: "[as-of date, default 2026-10-28]"
---

Run the BME Growth screen for the date $ARGUMENTS (default `2026-10-28`) as
the **orchestrator** agent (`.claude/agents/orchestrator.md`). Read `AGENTS.md`
first: its rules apply to every agent you launch.

1. `python -m screener run --as-of <date>` (downloads what the cache lacks).
2. `python -m screener todo --as-of <date>`.
3. Hand each line to the agent it names (`reader`, `shareholders`, `filter`),
   several companies in parallel when they are independent.
4. When they report back, run step 1 again with `--offline`, then step 2.
5. Repeat until `todo` is empty. Then show the funnel, the PASS list with its
   sources and the closest FAILs, and open `runs/<date>/report.html`.
