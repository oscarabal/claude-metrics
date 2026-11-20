---
title: Architecture Constraints
arc42-section: "02"
description: Constraints that restrict architecture decisions and their consequences.
---

# Architecture Constraints

| Constraint | Source | Architectural consequence | Negotiable |
| --- | --- | --- | --- |
| Single trusted machine, no auth on the collector, Loki, Prometheus or session-map | `README.md` "Security and privacy" | Every port is published on `127.0.0.1` only; publishing the collector on all interfaces is an explicit, documented opt-out, not the default | Yes, by the operator, with a documented trade-off |
| Windows paths assumed (`${USERPROFILE}`) in `docker-compose.yml` | `docker-compose.yml`, `README.md` Requirements | macOS/Linux users must substitute `${HOME}` themselves; no cross-platform abstraction layer exists | Yes (manual substitution) |
| Docker Desktop / Docker Compose required | `README.md` Requirements | No alternative runtime path (e.g. bare-metal install) is supported | No |
| Loki retains events 30 days; Prometheus 90 days | `loki-config.yaml` (`retention_period: 720h`), `docker-compose.yml` (`--storage.tsdb.retention.time=90d`) | `session-map` must persist its own cost/tool-event history (SQLite in the `coach-data` volume) to outlive Loki's window | No (Loki's window is fixed; the SQLite workaround is the negotiable part) |
| `session-map` may only read `~/.claude/projects`, `~/.claude/commands`, `~/.claude/skills` (read-only) — never all of `~/.claude`, never `settings.json` | `docker-compose.yml` volume comments, `README.md` Security and privacy | Bounds what the improvement report can ever source; any new feature needing more of `~/.claude` requires an explicit, separately justified mount | No, without a documented privacy review |
| `session-map` has no `requirements.txt`; runs as plain Python against the `python:3.13-alpine` base image | `docker-compose.yml` | New functionality must use the standard library, or the constraint itself must be revisited | Yes, if a dependency is deliberately added |
| Grafana dashboard and datasources are provisioned from files, `allowUiUpdates: false` | `grafana-dashboards.yaml` | All dashboard changes are made in `Grafana/claude-code-dashboard.json` plus `docker compose restart grafana`; the Grafana UI cannot be the source of truth | No |
| The Infinity Grafana plugin is installed at first container start (`GF_PLUGINS_PREINSTALL_SYNC`) | `docker-compose.yml` | First start after enabling the "Mejoras" row needs internet access, breaking the "fully local" expectation for that one moment | No |
