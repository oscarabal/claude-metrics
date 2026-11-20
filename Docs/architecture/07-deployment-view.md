---
title: Deployment View
arc42-section: "07"
description: Runtime infrastructure and the mapping of software building blocks onto it.
---

# Deployment View

## Infrastructure Level 1

### Overview

A single Docker host — the maintainer's own Windows machine (or macOS/Linux with `${HOME}` substituted,
see [02](02-constraints.md)) running Docker Desktop. `docker compose up -d` (or `Iniciar-metricas.bat`,
which also starts Docker Desktop if needed and opens Grafana) brings up all five services on one
Compose network; there is no multi-host or cloud deployment target.

### Topology Rationale

Everything is local and port-bound to `127.0.0.1` because the collector, Loki and Prometheus carry
telemetry attributes (including user email and account id) and have no authentication of their own;
see [02](02-constraints.md) and [08](08-crosscutting-concepts.md). There is no orchestration beyond
Compose, no HA and no backup of the named volumes — a deliberate trade-off for a single-user local tool,
stated explicitly in `README.md`'s "Limitations".

### Quality and Performance Characteristics

- Prometheus: 90-day retention, `--storage.tsdb.retention.time=90d`, deletes by block (can keep up to
  ~9 extra days).
- Loki: 30-day retention (`retention_period: 720h`), compactor marks expired data every 10 minutes and
  deletes it ~2 hours later.
- `session-map`'s own background index scan of `~/.claude/projects` takes about half a minute for 300 MB
  on first start, then only reads appended data.

### Building Block Mapping

| Building block or artifact | Infrastructure element | Environment |
| --- | --- | --- |
| `otel-collector` | `otel/opentelemetry-collector-contrib:latest` container, ports `127.0.0.1:4317`, `127.0.0.1:4318`, `8889` | Docker Compose, single host |
| `prometheus` | `prom/prometheus:latest` container, port `127.0.0.1:9090`, volume `prometheus-data` | Docker Compose, single host |
| `loki` | `grafana/loki:3.4.2` container, port `127.0.0.1:3100`, volume `loki-data` | Docker Compose, single host |
| `session-map` | `python:3.13-alpine` container running `map.py`, port `127.0.0.1:9100`, volume `coach-data`; bind mounts `${USERPROFILE}/.claude/{projects,commands,skills}` read-only | Docker Compose, single host |
| `grafana` | `grafana/grafana:latest` container, port `127.0.0.1:3000`, volume `grafana-data`; `GF_PLUGINS_PREINSTALL_SYNC` installs the Infinity plugin on first start | Docker Compose, single host |

## Infrastructure Level 2

No further infrastructure refinement is warranted: there is exactly one environment (the operator's
machine) and no element above has internal infrastructure complex enough to need its own diagram.
