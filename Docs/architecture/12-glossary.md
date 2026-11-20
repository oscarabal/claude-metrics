---
title: Glossary
arc42-section: "12"
description: Architecture-specific technical terms and abbreviations.
---

# Glossary

| Term | Definition |
| --- | --- |
| `query_source` | OTLP attribute identifying what made a given call: `sdk`/`repl_main_thread` for the main agent thread, `agent:...` for a subagent, a `*_tool` suffix for calls made inside a tool, and background-work hints (`prompt_suggestion`, `compact`, hook/title/summary generation) otherwise. `coach/report.py`'s `origin_kind()` buckets these into `principal`, `subagentes`, `herramientas`, `fondo`. |
| `effort` | The reasoning-effort level of a model call (`low`/`medium`/`high`/`xhigh`/`max`); `coach/report.py`'s `HIGH_EFFORT` treats `high`/`xhigh`/`max` as a single "high effort" bucket for rule C1. |
| `prompt_id` | The identifier shared by every event (`api_request`, `tool_result`, `tool_decision`, …) produced within one user prompt's turn; used to group spend and tool activity per prompt, and to open a prompt's full timeline in Grafana Explore. |
| `request_id` | The identifier of one model API call; the join key `session-map` uses to attach a Loki-sourced cost to a specific message in a conversation file. |
| Project attribution | `session-map`'s derivation of a session's `project` label from its recorded working directory (`cwd`), lower-cased, honoring `PROJECT_ROOTS` and worktree resolution — compensating for the desktop app ignoring `OTEL_RESOURCE_ATTRIBUTES`. |
| Session index | `index.py`'s in-memory, incrementally-updated structure built from `~/.claude/projects`, holding only conversation metadata (never message text). |
| Improvement report / "Mejoras" | `session-map`'s generated Markdown/JSON analysis of usage, built from the session index, the Loki/SQLite-derived request and tool-event history, and the command/skill inventory, organized around rule ids D1–D10 (shared with the sibling OpenCode module) and C1–C6 (Claude-Code-specific). |
| Finding | One rule violation instance produced by `coach/report.py`, carrying a severity, evidence, impact and recommendation, rendered into the report and exposed via `/coach/findings`. |
| Coach | The informal name (module path `session-map/coach/`) for the improvement-report subsystem: inventory, Loki queries, SQLite store, background metrics, the rule engine, and Markdown rendering. |
| Context window bar | The session-detail page's visualization of a session's token usage against an assumed context limit (`CONTEXT_LIMIT_DEFAULT`, overridable per model via `CONTEXT_LIMITS`), following the main thread only — excluding subagent messages. |
| Query source bucket (`fondo`) | Spanish for "background"; one of the four `origin_kind()` buckets, meaning a call made outside any user-visible conversation turn (hooks, title/summary generation, compaction, quota checks). |
