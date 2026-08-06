---
id: pp-corpus-arch-alphazero
title: "Computer Architecture's AlphaZero Moment — corpus entry"
open_questions:
  - What first-principles gates must an Idea Factory enforce before simulation?
decisions: []
corpus_entry: "arch-alphazero"
family: "other"
---

# Computer Architecture's AlphaZero Moment — corpus entry

### CTX-001 — Paper context

Scaffold entry for arXiv:2604.03312 Idea Factory claims. Used to exercise corpus
ingest/eval wiring; not a claim that ArchZero has reproduced the full paper study.

### REQ-001 — Fail-closed evaluation

The system shall refuse silent PASS when configured real evidence backends are
unavailable (`strict_evidence`).

### REQ-002 — Analytic acceptance path

An analytic model path shall exist that can report miss-reduction style metrics
against stated thresholds for architecture mechanisms under study.

### ACC-001 — Strict evidence

`refines: REQ-001`
`measurable: true`

With `sim.backend` set to a real backend and binary missing, Tier3+ verdicts
shall be `unavailable` (not stub PASS).

### ACC-002 — Analytic thresholds

`refines: REQ-002`
`measurable: true`

Offline analytic smoke shall show predicted MPKI reduction ≥ 15% with Magic Gap ≤ 2×
when a mechanism model is provided (scaffold FakeLLM path allowed).

### NNG-001 — Non-goals

Do not require Tier6 OpenROAD/sky130 or deployment telemetry Feedback for this entry.
