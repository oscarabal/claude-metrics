---
title: Architecture Decisions
arc42-section: "09"
description: Index of architecturally significant decisions and affected views.
---

# Architecture Decisions

No ADR directory (`docs/adr/` or equivalent) exists in this repository, and no ADR process is in use.

| Decision | ADR | Affected architecture |
| --- | --- | --- |

The following choices, evidenced in [04 Solution Strategy](04-solution-strategy.md), are significant
enough that they would warrant an ADR if this project adopts an ADR process:

- Deriving project attribution from a session's `cwd` instead of requiring `OTEL_RESOURCE_ATTRIBUTES`
  everywhere (works around the desktop app's limitation, but ties attribution to a filesystem
  convention — see [02](02-constraints.md) and [11](11-risks-and-technical-debt.md)).
- Persisting a local SQLite history (`coach/store.py`) instead of accepting Loki's 30-day retention as
  a hard limit for the improvement report.
- Keeping `session-map` dependency-free (standard library only) rather than adopting a web framework or
  metrics client library.

This section should be updated to reference real ADRs if and when any of the above (or a future
decision of similar weight) gets one.
