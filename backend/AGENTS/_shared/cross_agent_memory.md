# Cross-Agent Memory

Shared facts, constraints, and active blockers between Personal Agent and Coding Agent.
Both agents read this file at the start of a collaboration run.
Only Personal writes `## decisions`; only Coding writes `## constraints`;
either may update `## known_blockers`. Blockers are cleared automatically
when the run that produced them completes.

---

## decisions

<!-- Immutable facts set by Personal Agent. Each is a single-line fact with
     a timestamp. Do not edit these — append only. -->

None yet.

---

## constraints

<!-- Project-scoped constraints set by Coding Agent when it discovers
     invariants that must hold across runs. Format: one constraint per line
     with a brief rationale. -->

None yet.

---

## known_blockers

<!-- Active blockers that are opened during a collaboration run. When the
     run completes, the agent that opened the blocker should clear it.
     Format: - [run_id] description -->

None yet.
