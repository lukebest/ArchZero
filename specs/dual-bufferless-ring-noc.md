---
id: pp-dual-bufferless-ring-noc
title: "Dual full bufferless rings — AI-core ↔ memory HA all-to-all makespan"
open_questions:
  - What routing / injection policy minimizes makespan under uniform core→HA read traffic?
  - How does response length R trade off against ring contention and makespan?
  - Can plane selection or direction choice reduce hotspots without adding buffers?
decisions: []
workload: "All-to-all AI-core → memory HA random-uniform reads (request + response)"
domain: interconnection_network
---

# Dual full bufferless rings — AI-core ↔ memory HA all-to-all makespan

### CTX-001 — Topology (node roles)

Closed ring of **N = 20** nodes indexed `0..19`. Node `19` is adjacent to node `0`.

- **Even indices** `{0,2,4,…,18}`: **AI cores** (10 nodes).
- **Odd indices** `{1,3,5,…,19}`: **memory Home Agent (HA)** nodes (10 nodes).

Cores and HAs alternate around the ring.

### CTX-002 — Dual full bufferless ring planes

`refines: CTX-001`

Two **independent parallel ring planes** (plane A, plane B). Each plane is a **full ring**: every node attaches to both planes.

Per plane:

- The ring is **bidirectional** (clockwise + counterclockwise).
- Each node has **one inject/eject port** onto that plane.
- On a given plane, the two directions **share the same buffer** at the node attach point.
- Links are **bufferless** (no per-hop buffering beyond the shared plane port / link occupancy model assumed by the evaluator).

Aggregate structure:

- **4 ring directions per node** (2 planes × 2 directions).
- **Directed segments**: `20 nodes × 2 planes × 2 directions = 80` directed hops/segments on the fabric.

### CTX-003 — Traffic pattern (read round-trip)

`refines: CTX-001, CTX-002`

Workload is **memory reads** modeled as request/response pairs:

1. **Request**: AI core → memory HA, **1 flit**.
2. **Response**: memory HA → originating AI core, **R flits** (default **R = 4**; R is a sweep parameter).

**Spatial pattern**: every AI core issues reads to **all** memory HA nodes with **uniform random** destination choice among the 10 HAs (all-to-all core→HA random-uniform access). Responses return to the issuing core.

Unless otherwise stated in a campaign, treat destinations as i.i.d. uniform over odd indices, independent across requests.

### CTX-004 — Performance metric

`refines: CTX-003`

Primary figure of merit is **makespan**: wall-clock (or cycle) time until the **last response flit** of the evaluated traffic batch has been **ejected at its destination AI core**.

Lower makespan is better. Report makespan in cycles (or equivalent discrete time units of the chosen model).

### REQ-001 — Completeness

`refines: CTX-003, CTX-004`

The mechanism (routing, plane selection, injection scheduling, or equivalent control policy) shall deliver **every** request and its full R-flit response; no silent drops. Makespan is defined only for a fully completed batch.

### REQ-002 — Topology fidelity

`refines: CTX-001, CTX-002`

Evaluations shall respect the dual full bufferless ring geometry: 20 nodes, even=core / odd=HA, two planes, bidirectional per plane, shared buffer per plane port, and 80 directed segments. Do not invent extra hops, shortcuts, or per-hop store-and-forward buffers unless explicitly declared as a DOF change and reflected in ACC.

### REQ-003 — Makespan objective

`refines: CTX-004`

Under the default traffic (uniform core→HA reads, R=4 unless swept), the proposed policy shall **minimize makespan** relative to a stated baseline (e.g., random plane + shortest-path direction, or dimension-order equivalent on each ring). Report absolute makespan and speedup vs baseline.

### NNG-001 — Non-goals

`refines: CTX-001`

- Do not change the 20-node bipartition (core/HA roles) or add/remove nodes.
- Do not replace the dual-ring topology with mesh/torus/Clos unless the campaign explicitly forks a new problem package.
- Do not require coherent caching protocols beyond HA serving read responses of length R.
- Tier6 physical P&R / OpenROAD signoff is out of scope for this package.
- Deployment telemetry Feedback is out of scope.

### ACC-001 — Analytic / discrete-event acceptance

`refines: REQ-001, REQ-003`
`measurable: true`

An analytic or discrete-event model (Tier2 / directed Tier3) shall:

1. Encode the dual-plane bufferless ring and 80 directed segments.
2. Drive all-to-all uniform core→HA reads with request = 1 flit, response = R flits (default R=4).
3. Report **makespan** = time of last response-flit eject at a core.
4. Compare against a documented baseline policy; state assumptions (injection rate, serialization at shared plane ports, conflict model).

Magic Gap between analytic prediction and any higher-fidelity sim ≤ **2×** on makespan for the same traffic seed set, when both are available.

### ACC-002 — Parameter sweep (optional but preferred)

`refines: REQ-003, CTX-003`
`measurable: true`

When claiming robustness, report makespan vs **R ∈ {1,2,4,8,16}** (or a stated subset) under identical topology and routing family. Default single-point claim uses **R = 4**.

### ACC-003 — Evidence hygiene

`refines: REQ-002`
`measurable: true`

Stub-only evidence is insufficient for a PASS claim under paper-profile `strict_evidence` when a real/directed NoC backend is configured. Unavailable backends → `UNAVAILABLE`, not PASS.

### DOF-001 — Control policy knobs

`refines: CTX-002, CTX-003`

Open degrees of freedom (explore within DOF):

- Plane selection (A vs B) per packet or per flow.
- Direction choice (CW vs CCW) on the chosen plane (typically shortest path, but alternatives allowed if declared).
- Injection / ejection scheduling at the shared per-plane port.
- Batch size / outstanding requests per core.
- Response length R (as a study parameter; default 4).
- Conflict resolution / deflection / retry rules consistent with **bufferless** constraints.

### DOF-002 — Evaluation batch definition

`refines: CTX-003, CTX-004`

Campaigns should fix (or sweep) the number of read transactions **T** (e.g., each of 10 cores issues K reads ⇒ T = 10K) and random seed(s). Makespan comparisons must use the same T and seeds across policies.
