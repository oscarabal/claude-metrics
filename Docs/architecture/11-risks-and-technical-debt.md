---
title: Risks and Technical Debt
arc42-section: "11"
description: Prioritized architectural risks, technical debt, evidence, and mitigation.
---

# Risks and Technical Debt

All rows below are drawn from `README.md`'s own "Limitations" section plus directly observed fallback
behavior in the code; none are speculative.

| Risk or debt | Architectural impact | Evidence | Priority | Mitigation or decision |
| --- | --- | --- | --- | --- |
| Cost is a client-side estimate, not an invoice | Every cost figure across the dashboard and the improvement report inherits this uncertainty | `README.md` "Limitations": "Cost is an estimate computed by the client from token counts, not an invoice" | Medium | Documented as-is; no reconciliation against a billing source exists or is planned |
| Cost per skill cannot be isolated (LogQL does not join events) | The skill-cost table over-attributes cost: it adds the whole turn's cost to each skill that activated during it | `README.md`: "The skill table adds up the cost of the prompts that activate each skill, including the rest of the turn" | Medium | Documented as-is |
| A session loses its project if its transcript file is deleted | Historical dashboard figures for that session silently fall back to unattributed (`otros`) | `README.md`: "If Claude Code deletes old transcripts, those sessions lose their project" | Low | Accepted; no retention of `session-map`'s own derived attribution independent of the source transcript |
| Subagent cost/tokens count toward the session but not toward the context-window bar | The context bar can understate actual context pressure when subagents ran | `README.md`: "A subagent's messages count in the tokens and cost of its session, and are not part of the context bar, which follows the main thread" | Low | Documented as-is |
| No high availability, no backup of Prometheus/Loki/Grafana/coach-data volumes | A lost or corrupted Docker volume is a permanently lost history, including the SQLite cost store that exists specifically to survive Loki's retention | `README.md` "Limitations": "No high availability and no backups of the volumes" | Medium | Explicit, stated trade-off for a single-user local tool; not planned to change |
| `coach/store.py` falls back to an in-memory SQLite connection if the `coach-data` volume path is unwritable | History silently stops persisting across restarts, with no visible error to the operator beyond the absence of growing history | `coach/store.py` `__init__`: `except (OSError, sqlite3.Error): self.persistent = False` | Low | Graceful degradation is intentional (serves rather than crashes), but the `persistent` flag is not currently surfaced anywhere an operator would see it |
| Grafana's Infinity plugin install (`GF_PLUGINS_PREINSTALL_SYNC`) requires internet access on first container start | Breaks the "fully local" expectation at exactly the moment a new environment is first stood up | `docker-compose.yml` comment; `README.md`: "the first start after this change needs internet access" | Low | Accepted one-time dependency |
| `session-map`'s improvement-report rule ids (D1–D10, C1–C6) are a shared contract with a separate OpenCode module, maintained only by convention | A rule id or report-shape change here can silently break compatibility with that other project, with no automated check in this repository | `coach/report.py` module docstring: "The dict follows the same contract as the OpenCode module... so both can be read alike" | Medium | No cross-repository contract test exists; changes to `RULES`, `FORMAT_VERSION` or top-level report keys should be treated as a breaking-change risk |
