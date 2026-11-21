---
title: Introduction and Goals
arc42-section: "01"
description: Architectural orientation, drivers, quality goals, and documentation stakeholders.
---

# Introduction and Goals

## Requirements Overview

This project has no dedicated product-intent source (no ProductShape or equivalent model under
`docs/product/`). Product intent lives directly in `README.md` / `README.es.md`, which describe the
system's purpose, usage and limitations in prose aimed at the end user. This section treats those
files as the intent source and links to them rather than restating their content; claims below that
depend on them are marked as such instead of using a formal citation mechanism, which this project does
not have.

In short: `claude-metrics` is a local Docker Compose stack that receives the OpenTelemetry metrics and
events Claude Code already exports, stores them, and renders a Grafana dashboard plus a generated
"improvement report" — all so a single developer can see how many tokens and dollars their Claude Code
usage costs, by project, model, skill and command, without sending any of it off-machine.

## Quality Goals

Ranked by what drives the architecture's shape, derived from the emphasis and repeated caveats in
`README.md`:

1. **Data minimization / privacy by construction.** No conversation text, prompt text (unless
   explicitly opted in) or `~/.claude` settings ever reach storage; only metadata is kept, and only
   specific subfolders are mounted read-only. This is not a bolt-on policy — it determines what
   `session-map`'s index is allowed to hold (see [08](08-crosscutting-concepts.md)).
2. **Operate on one trusted machine with near-zero ops.** Everything is `docker compose up -d`;
   Grafana, its datasources and the dashboard are provisioned as code, not clicked together; there is
   no auth service, no build step and no package manager for `session-map` (plain-stdlib Python).
3. **Attribution correctness despite incomplete telemetry.** Claude Code's desktop app ignores
   `OTEL_RESOURCE_ATTRIBUTES`, and Loki only retains 30 days. The architecture exists largely to patch
   these two gaps (project attribution from `cwd`, and a local SQLite history) so dashboard numbers
   stay correct over time.
4. **Numbers must be explainable, not just displayed.** Cost is an estimate reconciled across two
   independent sources (Prometheus metrics and Loki events matched by request id); the README commits
   to stating this estimate's limits explicitly rather than presenting it as exact.

## Stakeholders

| Role | Expectation |
| --- | --- |
| The maintainer, as operator | Stand the stack up on their own machine with one command; trust that it never exfiltrates conversation content. |
| The maintainer, as dashboard viewer | See cost/token/session figures that reconcile with what they'd expect from their own Claude Code usage. |
| An AI assistant consuming the improvement report | Receive a self-contained Markdown report (figures, findings, recommendations) with no conversation text, prompts or e-mails, written for pasting into a chat. |
