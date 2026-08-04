---
id: pp-demo-cache
title: "Demo — reduce L2 miss penalty under LLM decode traffic"
open_questions:
  - Can a small predictor cut MPKI without blowing area?
  - What is the bandwidth ceiling given HBM stack limits?
decisions: []
workload: "LLM decode / token generation"
---

# Demo — reduce L2 miss penalty under LLM decode traffic

### CTX-001 — Workload context

LLM decode streams show irregular but bursty L2 miss trains. Baseline MPKI is elevated versus steady-state server workloads.

### CTX-002 — Hardware envelope

`refines: CTX-001`

Target: mid-range accelerator SoC, 4 MB shared L2, HBM2e. Area budget for new structures ≤ 0.5 mm² at 5 nm-class density proxy.

### REQ-001 — Miss-rate reduction

`refines: CTX-001`

The mechanism shall reduce L2 MPKI by ≥ 15% on the decode trace suite versus the unmodified baseline.

### REQ-002 — Bandwidth respect

`refines: CTX-002`

The mechanism must not increase DRAM bandwidth demand by more than 5% at iso-IPC.

### NNG-001 — Non-goals

Do not redesign the NoC. Do not change ISA. Do not require OS changes.

### ACC-001 — Analytic acceptance

`refines: REQ-001`
`measurable: true`

An analytic model (Tier2) shall show predicted MPKI reduction ≥ 15% with stated assumptions; Magic Gap between model and any available sim ≤ 2×.

### ACC-002 — Simulation acceptance

`refines: REQ-001, REQ-002`
`measurable: true`

Stub or ChampSim/gem5 run on synthetic decode-like traces shall confirm MPKI and bandwidth constraints.

### DOF-001 — Predictor family

Open degrees of freedom: table size, history length, prefetch distance, filter vs. prefetch vs. dead-block. Exploration within DOF is encouraged.
