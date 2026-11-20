---
title: Crosscutting Concepts
arc42-section: "08"
description: Shared architectural mechanisms applied across multiple building blocks.
---

# Crosscutting Concepts

## Data minimization by construction

### Scope

Everywhere `session-map` touches data that could originate from conversation content: `index.py`'s
transcript scan, `coach/inventory.py`'s command/skill reads, `coach/errors.py`'s classification, and
every volume mount in `docker-compose.yml`.

### Mechanism

Three layers enforce the same intent rather than relying on one filter: (1) only three specific
subfolders of `~/.claude` are ever mounted, and only read-only; (2) `index.py` extracts and keeps
timestamps, models, token counts, tool/skill/command names, titles and compaction markers, never
message text; (3) `coach/errors.py` reads an error's text just long enough to classify it into a fixed
set of classes, then discards it. The improvement report inherits this by construction — it cannot leak
what was never indexed.

### Evidence

`docker-compose.yml` volume comments ("solo lectura; nunca ~/.claude entero ni settings.json"),
`index.py`'s module docstring, `coach/errors.py`'s module docstring, `README.md`'s "Security and
privacy" section.

## Localhost-only network exposure

### Scope

Every service's port mapping in `docker-compose.yml`.

### Mechanism

All ports (`4317`, `4318`, `3100`, `9090`, `9100`, `3000`) are bound as `127.0.0.1:<port>:<port>`
rather than exposed on all interfaces, compensating for the absence of authentication on the collector,
Loki, Prometheus and `session-map`. `8889` (the collector's Prometheus exposition endpoint) is the one
exception, bound without an explicit host — scraped only by Prometheus on the same Compose network.

### Evidence

`docker-compose.yml` port mappings; `README.md` "Security and privacy": "Ports are published on
`127.0.0.1` only, because the collector, Loki and Prometheus have no authentication".

## Provisioning-as-code for Grafana

### Scope

`grafana-datasource.yaml`, `grafana-dashboards.yaml`, `Grafana/claude-code-dashboard.json`.

### Mechanism

Datasources (Prometheus, Loki, the Infinity-backed `Coach` datasource) and the single dashboard are
declared as files mounted into Grafana's provisioning directories, with `allowUiUpdates: false`. This
makes the dashboard JSON, not Grafana's running state, the single source of truth, at the cost of
requiring `docker compose restart grafana` after every edit and preventing changes from the UI.

### Evidence

`grafana-dashboards.yaml` (`allowUiUpdates: false`), `grafana-datasource.yaml`'s fixed `uid`s (so panel
JSON can reference them stably), `README.md`: "Because it is provisioned it cannot be saved from the
interface: changes are made in the JSON."

## Cost reconciliation across independent sources

### Scope

`index.py`'s cost-matching logic, `coach/store.py`, `coach/loki.py`.

### Mechanism

Token counts and structural facts come from the conversation files; cost comes only from Loki's
`api_request` events, matched to a specific message by request id. The two are never merged into one
blob — the index keeps `costs`/`requests`/`request_meta` as separate maps keyed by request id, joined
on read. This is why a message can have tokens but no cost (made before telemetry was enabled) and why
`README.md` documents that about nine tenths of Loki's recorded cost can be matched to a conversation
message.

### Evidence

`index.py` module docstring; `coach/store.py` module docstring; `README.md` "The conversation files
carry tokens but no cost...".

## Background polling with cached results

### Scope

`coach/metrics.py`, consumed by `map.py`'s `/metrics` and `/coach/*` handlers.

### Mechanism

A single background thread recomputes Prometheus series every 2 minutes and findings every 10 minutes,
storing results in a module-level `_state` dict guarded by a lock; HTTP handlers only ever read that
cache, never recompute inline. The module docstring explains why: computing these series during a
Prometheus scrape made the sibling OpenCode module time out.

### Evidence

`coach/metrics.py` module docstring and `ROUND`/`SERIES_EVERY`/`FINDINGS_EVERY` constants.
