---
id: pp-corpus-stub-bypass
title: "Bypass-aware writeback scaffold"
open_questions: []
decisions: []
corpus_entry: "stub-bypass"
family: "bypass"
---

# Bypass-aware writeback scaffold

### CTX-001 — Workload context

Synthetic decode-like L2 traffic for corpus scaffold entry `stub-bypass`.

### REQ-001 — Miss-rate reduction

The mechanism shall reduce L2 MPKI by ≥ 15% versus baseline.

### REQ-002 — Bandwidth respect

The mechanism must not increase DRAM bandwidth demand by more than 5% at iso-IPC.

### ACC-001 — Analytic acceptance

`refines: REQ-001`
`measurable: true`

Analytic model shall show predicted MPKI reduction ≥ 15%; Magic Gap ≤ 2×.

### ACC-002 — Simulation acceptance

`refines: REQ-001, REQ-002`
`measurable: true`

Directed or ChampSim/gem5 run shall confirm MPKI and bandwidth constraints.

### DOF-001 — Family

Open degrees of freedom within the `bypass` family.
