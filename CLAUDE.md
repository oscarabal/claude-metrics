# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local observability stack for Claude Code itself: Docker Compose services that receive Claude Code's
OpenTelemetry metrics/events, store them, and render a Grafana dashboard (cost, tokens, sessions, skills,
tools) plus a custom "improvement report" that coaches usage. There is no build step and no test suite —
the only Python code is `session-map/`, run directly inside its container.

## Commands

```bash
cp .env.example .env && docker compose up -d               # start the stack (set GRAFANA_ADMIN_PASSWORD first)
docker compose up -d --force-recreate otel-collector        # apply otel-collector-config.yaml changes
docker compose restart grafana                               # apply Grafana/claude-code-dashboard.json changes (provisioned, can't edit via UI)
docker compose restart session-map                            # apply session-map/ code changes
docker compose logs --tail 50 otel-collector                 # see what telemetry arrives
curl -s http://localhost:8889/metrics | grep claude_code      # check metrics exposed to Prometheus
docker compose exec session-map python /app/coach/cli.py report --window 30 > report.md   # generate the report from the CLI
```

There's no package manager, linter or test runner — `session-map` is plain-stdlib Python (no
`requirements.txt`) run via the `python:3.13-alpine` image with `session-map/` bind-mounted read-only.
Iterate by editing the `.py` files and restarting the `session-map` container.

## Architecture

```
Claude Code --OTLP/gRPC--> otel-collector --metrics--> Prometheus --\
                                |--events--> Loki -----------------> Grafana
~/.claude/projects (read-only) --> session-map --session->project/context/skills--> Prometheus
                                              \--cost lookup by request id--> Loki
```

- **otel-collector** (`otel-collector-config.yaml`): receives OTLP, exposes `:8889/metrics` for
  Prometheus, forwards events to Loki.
- **prometheus** (`prometheus.yml`): scrapes `otel-collector:8889` and `session-map:9100`, 90-day retention.
- **loki** (`loki-config.yaml`): stores events, 30-day retention.
- **session-map** (`session-map/`): the only custom code. Runs `map.py` as an HTTP server on `:9100`.
  See below.
- **grafana**: provisioned (not click-configured) from `Grafana/claude-code-dashboard.json`,
  `grafana-datasource.yaml` (Prometheus, Loki, and an Infinity datasource reading `session-map`'s
  report endpoints), `grafana-dashboards.yaml`.

### Why session-map exists

Claude Code's desktop app ignores `OTEL_RESOURCE_ATTRIBUTES`, so telemetry alone can't attribute a
session to a project. `session-map` reads `~/.claude/projects` transcript files (read-only, mounted
into the container) to recover `cwd` → project name, and reads the conversation JSON itself (metadata
only — timestamps, models, token counts, tool/skill names, titles; **never message text**) to build an
index covering every session ever, not just ones since telemetry was enabled. Costs come only from
Loki (matched to conversation messages by request id), because transcripts carry tokens but not cost.

### session-map module layout

- `map.py` — entry point; HTTP server, publishes session→project and per-session context gauges to
  Prometheus (`:9100/metrics`), serves `/sessions` and `/session/<id>`.
- `index.py` — background incremental reader of `~/.claude/projects`; the metadata index and
  project-from-cwd logic (`PROJECT_ROOTS` handling, worktree resolution).
- `pages.py` — HTML rendering for the session list/detail pages (no JS framework, inline CSS).
- `report_page.py` — renders the improvement report's Markdown (from `coach/render.py`) as HTML with
  download/copy buttons; reuses `pages.py`'s CSS.
- `coach/` — the improvement-report subsystem, structured as a pipeline:
  - `inventory.py` — reads `~/.claude/commands` and `~/.claude/skills` (read-only; never all of
    `~/.claude` or `settings.json`).
  - `loki.py` — queries Loki for effort, call origin, tool bytes, permission decisions.
  - `store.py` — SQLite in the `coach-data` volume, persisting per-request cost/model/effort/session and
    per-tool-event data past Loki's 30-day window.
  - `metrics.py` — turns the above into the rule inputs.
  - `report.py` — the rule engine (D1–D10 shared with the sibling OpenCode project, C1–C6 Claude-Code-only).
  - `render.py` — rule findings → the Spanish Markdown report.
  - `cli.py` — `python /app/coach/cli.py report --window N` entry point.
  - `errors.py` — error-text classification (text is read transiently to classify, then discarded).

Endpoints `session-map` serves beyond the HTML pages: `/report`, `/report.md`, `/report.json`,
`/coach/summary`, `/coach/findings`, `/coach/rules`, `/coach/tool_bytes` (consumed by Grafana's Infinity
datasource for the "Mejoras" dashboard row).

## Conventions to preserve

- **Privacy boundary is load-bearing, not incidental.** `session-map` must never persist conversation
  text, prompt/error text beyond transient classification, or full `~/.claude` (only
  `projects`, `commands`, `skills` are mounted, all read-only). Any change touching `index.py`,
  `coach/errors.py`, or the volume mounts in `docker-compose.yml` must keep this invariant.
- All ports are published on `127.0.0.1` only (no auth on collector/Loki/Prometheus/session-map) —
  don't change this without also adding auth.
- The dashboard JSON is the source of truth for Grafana; it's provisioned, so edits must go in
  `Grafana/claude-code-dashboard.json` and need `docker compose restart grafana`, not the Grafana UI.
- README.md and README.es.md are parallel (English/Spanish) and should be updated together; the
  improvement report's own prose is always Spanish regardless.
- Windows paths (`${USERPROFILE}`) are assumed in `docker-compose.yml`; note this if porting to
  macOS/Linux (`${HOME}`).
