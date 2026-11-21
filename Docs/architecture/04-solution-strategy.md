---
title: Solution Strategy
arc42-section: "04"
description: Fundamental approaches that shape the architecture and realize its drivers.
---

# Solution Strategy

| Driver | Strategy | Detailed view or ADR |
| --- | --- | --- |
| Data minimization / privacy by construction | `session-map` reads conversation files but indexes metadata only (timestamps, models, token counts, tool/skill/command names, titles) and discards message text after transient use; volume mounts are scoped to exactly `projects`, `commands`, `skills`, all read-only | [05](05-building-block-view.md) `index.py`, `coach/inventory.py`, `coach/errors.py`; [08](08-crosscutting-concepts.md) |
| Attribution correctness despite incomplete telemetry (desktop ignores `OTEL_RESOURCE_ATTRIBUTES`) | `session-map` independently derives `project` from each session's recorded `cwd` and publishes it as a Prometheus gauge (`claude_session_project`) that every dashboard query joins against | [06](06-runtime-view.md) "Project attribution for a session with no OTEL_RESOURCE_ATTRIBUTES" |
| History must survive Loki's 30-day retention | A small SQLite store (`coach/store.py`) in the `coach-data` volume persists per-request cost and per-tool-event rows plus daily Loki aggregates, restored into the in-memory index on every restart | [05](05-building-block-view.md) `coach/store.py`; [06](06-runtime-view.md) "Report history surviving a restart" |
| Near-zero operational overhead | A single Docker Compose file; `session-map` has no dependencies beyond the Python standard library; Grafana's datasources and dashboard are provisioned from version-controlled files, not configured through its UI | [07](07-deployment-view.md) |
| Cost numbers must be explainable | Cost is computed once, by the official OTLP exporter in Claude Code, and `session-map` only looks it up (matched by request id) rather than recomputing it; the index keeps two separate sources (conversation files for tokens/structure, Loki/SQLite for cost) explicitly reconciled by request id instead of merged into one blob | [06](06-runtime-view.md) |
| The dashboard needs richer, slower-changing analysis (the "improvement report") without slowing scrapes | `coach/metrics.py` runs a background thread that recomputes series and findings on a timer and caches them; Prometheus scrapes and Grafana's Infinity datasource only ever read the cache | [05](05-building-block-view.md) `coach/metrics.py`; [08](08-crosscutting-concepts.md) "Background polling with cached results" |

No ADRs exist yet for these decisions (see [09](09-architecture-decisions.md)); they are documented
here as the as-built strategy, evidenced by the code and configuration cited above.
