---
title: Architecture Documentation
description: Navigation index for the claude-metrics arc42 architecture documentation.
---

# Architecture Documentation

This folder documents **how** `claude-metrics` — a local observability stack for Claude Code — is
structurally shaped, following the twelve canonical [arc42](https://arc42.org) sections. This page is
the navigation index only; it owns no architectural content of its own.

The project has no dedicated product-intent source (no ProductShape or equivalent). `README.md` and
`README.es.md` at the repository root are the closest thing to product intent and are cited as such
where relevant; see [01 Introduction and Goals](01-introduction-and-goals.md) for how that gap is
handled.

| # | Section | Covers |
| --- | --- | --- |
| 01 | [Introduction and Goals](01-introduction-and-goals.md) | Why the stack exists, its quality goals, its stakeholders |
| 02 | [Constraints](02-constraints.md) | Fixed conditions (OS, tooling, retention, privacy) that shape decisions |
| 03 | [Context and Scope](03-context-and-scope.md) | System boundary, external systems, ports and channels |
| 04 | [Solution Strategy](04-solution-strategy.md) | The few big calls that shape the rest of the architecture |
| 05 | [Building Block View](05-building-block-view.md) | The services and, inside `session-map`, its modules |
| 06 | [Runtime View](06-runtime-view.md) | How telemetry, project attribution and the report actually flow |
| 07 | [Deployment View](07-deployment-view.md) | Docker Compose topology, ports, volumes |
| 08 | [Crosscutting Concepts](08-crosscutting-concepts.md) | Privacy minimization, localhost-only exposure, provisioning-as-code, cost reconciliation |
| 09 | [Architecture Decisions](09-architecture-decisions.md) | Index of ADRs (none recorded yet) |
| 10 | [Quality Requirements](10-quality-requirements.md) | How stated quality goals are actually realized, and known gaps |
| 11 | [Risks and Technical Debt](11-risks-and-technical-debt.md) | Known limitations, from the README's own "Limitations" section |
| 12 | [Glossary](12-glossary.md) | Domain terms (query_source, effort, prompt_id, project attribution, etc.) |

There is no legacy `docs/ARCHITECTURE.md` to migrate; this documentation was generated fresh from the
repository's code, configuration and `README.md`/`README.es.md`.
