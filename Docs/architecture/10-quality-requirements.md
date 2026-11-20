---
title: Quality Requirements
arc42-section: "10"
description: Architectural realization and evidence for product quality requirements.
---

# Quality Requirements

This project has no ProductShape or other formal product-intent source (see
[01](01-introduction-and-goals.md)), so the "requirement" column below is drawn from the quality goals
stated or implied in `README.md`/`README.es.md` rather than from a cited, versioned requirements
catalogue. Treat it as the best available evidence, not as a formally traceable source.

## Quality Requirements Overview

| Stated requirement (README) | Architectural realization | Evidence or gap |
| --- | --- | --- |
| Never store conversation text, prompt text (by default) or full `~/.claude` | `index.py` keeps metadata only; mounts limited to `projects`/`commands`/`skills`, read-only (see [08](08-crosscutting-concepts.md)) | Realized. Gap: `OTEL_LOG_USER_PROMPTS=1` does store prompt text in Loki for 30 days — an explicit, documented opt-in, not a default violation |
| Attribute every session (CLI and desktop, past and present) to a project | `session-map` derives `project` from `cwd` and publishes `claude_session_project`, joined by every dashboard query | Realized for sessions with a recorded, resolvable `cwd`. Gap: a session with no `cwd`, or opened at a home folder/drive root, reports as `otros`; a session loses its project if Claude Code deletes its transcript file |
| Cost/token figures should reconcile and be explainable, not presented as exact invoices | Cost is read, never recomputed, from Loki's `api_request` events, matched by request id; `README.md` states the estimate's nature explicitly | Realized, with a documented gap: about nine tenths of Loki's recorded cost can be matched to a conversation message; the rest (background calls outside any conversation) cannot |
| History should survive Loki's 30-day retention | `coach/store.py` SQLite persistence, restored on every start | Realized from the day the store was enabled onward; history from before that point is not retroactively recovered |
| Run with near-zero operational overhead on one machine | Docker Compose, provisioned Grafana, dependency-free `session-map` | Realized. Gap: Grafana's Infinity plugin still needs internet access on its very first start |
| Tolerate transient failures of Loki/Prometheus without losing data permanently | `coach/loki.py` retries failed query kinds next round; `coach/metrics.py`'s loop catches exceptions per round | Realized for transient failures. Gap: no high availability and no backup of the named volumes — a lost volume is a lost history, by explicit design choice (see [11](11-risks-and-technical-debt.md)) |

## Quality Scenarios

### Desktop session gets attributed to the right project within seconds of starting

Stimulus: a new Claude Code desktop session starts in a working directory under a configured
`PROJECT_ROOTS` entry. Expected response: within roughly 15 seconds (the time for Claude Code to write
the transcript file and for Prometheus to scrape `session-map`'s next publication), dashboard panels
filtered to that project include the new session. Evidence: `README.md` "A new session has no project
until Claude Code creates its transcript file and Prometheus scrapes it (about 15 seconds)".

### Loki is temporarily unreachable while the improvement report is being built

Stimulus: `coach/loki.py`'s query to Loki raises an exception for one aggregate kind during a
background round. Expected response: that kind's rows are skipped for this round and retried next
round; the report still renders using whatever rows the SQLite store already has, with no unhandled
exception reaching the HTTP handler. Evidence: `coach/loki.py`'s `except Exception` per query kind;
`coach/metrics.py`'s `_loop`'s `except Exception` per round.
