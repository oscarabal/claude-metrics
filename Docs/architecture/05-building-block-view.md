---
title: Building Block View
arc42-section: "05"
description: Static decomposition, responsibilities, interfaces, and dependencies.
---

# Building Block View

## Whitebox Overall System

### Overview

`claude-metrics` is five Docker Compose services. Four are off-the-shelf images wired by
configuration files; one (`session-map`) is this repository's only custom code.

### Decomposition Rationale

The boundary follows the off-the-shelf-vs-custom line: anything OpenTelemetry/Prometheus/Loki/Grafana
already do well is left to their stock images and config files. `session-map` exists only for the two
gaps those tools cannot fill on their own (project attribution for desktop sessions, and history that
outlives Loki's retention) plus the derived "improvement report" feature.

### Contained Building Blocks

| Building block | Responsibility | Interfaces | Source location |
| --- | --- | --- | --- |
| `otel-collector` | Receives OTLP metrics/events from Claude Code, exposes a Prometheus scrape endpoint, forwards events to Loki | OTLP gRPC/HTTP in; Prometheus exposition out; OTLP/HTTP to Loki out | `otel-collector-config.yaml` |
| `prometheus` | Stores metrics, answers PromQL, feeds Grafana | Scrapes `otel-collector:8889` and `session-map:9100`; serves PromQL on `:9090` | `prometheus.yml` |
| `loki` | Stores log events (30-day retention), answers LogQL | OTLP/HTTP in; LogQL on `:3100` | `loki-config.yaml` |
| `session-map` | Derives project attribution, serves session pages, builds and serves the improvement report, persists history Loki would otherwise lose | HTTP `:9100` (metrics, `/sessions`, `/session/<id>`, `/report*`, `/coach/*`); reads `~/.claude/{projects, commands, skills}` read-only; LogQL client to Loki | `session-map/` (see Level 2) |
| `grafana` | Renders the dashboard and Infinity-backed "Mejoras" panels | HTTP `:3000`; datasource clients to Prometheus, Loki, and `session-map` (via Infinity) | `Grafana/claude-code-dashboard.json`, `grafana-datasource.yaml`, `grafana-dashboards.yaml` |

### Important Interfaces

- `claude_code_*` metrics (six, see [03](03-context-and-scope.md)) — the contract between Claude Code's
  exporter and everything downstream.
- `claude_session_project`, `claude_context_*`, `claude_day_*` — the contract `session-map` adds on top,
  joined into dashboard queries by `session_id` or `project`.
- `/coach/summary`, `/coach/findings`, `/coach/rules`, `/coach/tool_bytes` — the JSON contract Grafana's
  Infinity datasource consumes for the "Mejoras" row.
- `/report`, `/report.md`, `/report.json` — the contract shared with the sibling OpenCode module (same
  `format_version`, same top-level keys, same rule ids where a rule means the same thing).

## Level 2

### Whitebox: `session-map`

| Module | Responsibility |
| --- | --- |
| `map.py` | Process entry point; `ThreadingHTTPServer` routing (`/`, `/sessions`, `/session/<id>`, `/report*`, `/coach/*`); publishes the `claude_session_project`/`claude_context_*`/`claude_day_*` Prometheus gauges |
| `index.py` | Background, incremental reader of `~/.claude/projects`; builds the in-memory metadata index (sessions, messages, tool calls, commands, skills); derives `project` from each session's `cwd` (honoring `PROJECT_ROOTS`, worktree resolution); matches request costs from Loki by request id |
| `pages.py` | Renders the `/sessions` list and `/session/<id>` detail pages as plain HTML/CSS (no framework, no JS build) |
| `report_page.py` | Renders the improvement report (Markdown from `coach/render.py`) as an HTML page with download/copy buttons, reusing `pages.py`'s CSS |
| `coach/inventory.py` | Reads `~/.claude/commands` and `~/.claude/skills` (names, pinned model, last-changed date only) |
| `coach/loki.py` | Runs LogQL aggregate queries (sums/counts per day) against Loki; never a raw event list, so no text ever returns |
| `coach/store.py` | SQLite persistence (`coach-data` volume) for per-request cost rows, per-tool-event rows, and daily aggregates, so history survives Loki's 30-day window and container restarts |
| `coach/metrics.py` | Background thread: saves costs to the store, refreshes Loki daily aggregates every 10 min, recomputes cached Prometheus series every 2 min and findings every 10 min |
| `coach/report.py` | The rule engine (`build()`): turns the index snapshot plus the inventory into the improvement-report dict (rules D1–D10 shared with the OpenCode module, C1–C6 Claude-Code-specific) |
| `coach/render.py` | Turns the report dict into the Spanish Markdown (and JSON) report |
| `coach/errors.py` | Classifies tool-error text into a fixed set of classes; the text itself is read only transiently and discarded |
| `coach/cli.py` | `python coach/cli.py report --window N` — the command-line path to the same report, reading the transcripts itself rather than sharing the server's memory |

## Level 3

No level-3 refinement is warranted: no module above is large, risky or volatile enough to need a
further whitebox breakdown beyond its docstring-level responsibility already shown.
