---
id: pp-noc-request-grant
title: "NoC request-grant vs baseline packet-switched — 8×6 mesh/torus study"
open_questions:
  - Under iso-wire (iso-bisection) budgets, when does request-grant beat baseline packet switching on collective traffic?
  - How should synchronized request-grant for allgather/allreduce trade latency of global barrier-style arbitration against injection contention?
  - For asynchronous allgather, how should per-source multicast-tree grants be scheduled without starving other sources?
  - Do bufferless fabrics change the relative value of request-grant versus bufferable designs?
decisions: []
workload: "collective communication patterns on on-chip NoC"
domain: "interconnect / NoC"
---

# NoC request-grant vs baseline packet-switched — 8×6 mesh/torus study

### CTX-001 — Research objective

Compare **request-grant** scheduling mechanisms against a **baseline packet-switched（分组交换）NoC**, and produce a structured research report covering mechanism design, analytic bounds, simulation evidence, and failure modes across topologies, buffering styles, and collective traffic patterns.

### CTX-002 — Topology and wire budget

`refines: CTX-001`

Evaluate two topologies on an **8×6** node grid:

1. **2D mesh**
2. **Folded 2D torus**

**Iso-wire / iso-metal constraint (hard):** total metal-wire resource is constant. Therefore each **folded-2D-torus link has half the per-link bandwidth of the corresponding 2D-mesh link**, so that **bisection bandwidth is equal** between the two topologies. Comparisons must be at this iso-bisection point; do not claim torus wins from “more links” without applying the half-bandwidth rule.

### CTX-003 — Link timing

`refines: CTX-002`

Fixed link delays (in cycles / flits of wire delay):

- **Horizontal (X) links:** 7 cycles
- **Vertical (Y) links:** 9 cycles

Models and simulators shall use these delays for both mesh and folded torus (torus wraparound links inherit the delay of their axis).

### CTX-004 — Buffering styles

`refines: CTX-002`

Two fabric classes must be studied (orthogonal to topology):

- **bufferable** — routers may buffer flits/packets (credit/VC or equivalent)
- **bufferless** — no (or negligible) data buffering in the fabric; deflection / drop-and-retransmit / circuit-like occupancy as appropriate to the candidate mechanism

Report results separately for bufferable vs bufferless; do not average them away.

### CTX-005 — Traffic patterns (collectives)

`refines: CTX-001`

Mandatory traffic patterns:

| Pattern | Notes |
|---------|--------|
| **alltoall** | every node sends to every other node |
| **allgather** | every node contributes; all nodes receive the concatenated result |
| **allreduce** | every node contributes; all nodes receive the reduced result |
| **broadcast** | one (or designated) root → all |
| **reduce** | all → one (or designated) root |

Message sizes, chunking, and multiphase algorithms (e.g. reduce-scatter + allgather for allreduce) are DOF unless fixed by a candidate’s DEC clause.

### CTX-006 — Request-grant mechanism classes

`refines: CTX-001, CTX-005`

Candidates must instantiate request-grant (RG) control relative to the baseline packet-switched datapath. Required semantic classes:

1. **Point-to-point / single-flow RG** (sufficient for **alltoall**, **broadcast**, **reduce**):  
   A request names a single source→destination flow (or a single root-based flow). Grants authorize that flow’s injection / path occupancy. Arbitration may be local or hierarchical but need not wait for a global set of peers.

2. **Synchronized (barrier-style) RG** (**required extra support for allreduce and allgather**):  
   The fabric/controller must **wait until requests from all participating nodes have arrived and form a complete request set**, then **arbitrate once**, then **issue grants uniformly** (coordinated release). Partial grants before the request set is complete are non-conformant for this class.

3. **Asynchronous allgather RG (multicast-tree grant)**:  
   For allgather, an asynchronous RG variant is in scope in which **each grant authorizes a multicast tree rooted at one source node** (that source’s contribution disseminated to all others). Multiple source trees may be scheduled over time; synchronized RG (class 2) remains a required comparison point for allgather/allreduce.

Baseline packet switching has **no** request-grant admission control: packets/flits compete under the fabric’s ordinary routing/arbitration.

### REQ-001 — Fair comparison protocol

`refines: CTX-002, CTX-003, CTX-004, CTX-005`

Every reported comparison shall hold fixed: node count (8×6), link delays (X=7, Y=9), iso-wire half-bandwidth on torus, and the same traffic pattern / offered load / message size point. Vary at most the mechanism class (baseline vs RG variants) and the declared DOF knobs. Topology (mesh vs folded torus) and buffering (bufferable vs bufferless) are experimental factors, not free mix-and-match within a single named comparison unless explicitly ablated.

### REQ-002 — Mechanism coverage

`refines: CTX-006`

The study shall evaluate at least:

- baseline packet-switched NoC;
- point-to-point RG on **alltoall**, **broadcast**, and **reduce**;
- synchronized RG on **allgather** and **allreduce**;
- asynchronous allgather RG with **per-source multicast-tree grants**.

Omitting synchronized RG for allgather/allreduce is a FAIL for completeness.

### REQ-003 — Primary metrics

`refines: CTX-001, CTX-005`

For each (topology × buffering × pattern × mechanism) cell, report at least:

- **completion latency** (cycles to collective done);
- **throughput / offered-load sustainability** (or time-normalized goodput);
- **link utilization** and evidence of **hotspot / bisection saturation**;
- for RG: **request wait time**, **grant wait time**, and (for synchronized RG) **barrier assemble time** until the full request set is ready.

### REQ-004 — Research report deliverable

`refines: CTX-001, REQ-002, REQ-003`

Produce a research report that includes: problem setup and iso-wire rationale; mechanism definitions (baseline, P2P RG, synchronized RG, async allgather multicast-tree RG); analytic or first-principles bounds where applicable; experimental matrix and results; discussion of when RG helps or hurts; threats to validity (bufferless modeling assumptions, grant tree embedding, etc.).

### NNG-001 — Non-goals

`refines: CTX-001`

Out of scope unless promoted via a new DOF/DEC:

- Full-chip RTL / physical signoff of routers
- Off-chip network or multi-socket fabrics
- Cache-coherence protocol redesign (use collectives as traffic, not as directory protocols)
- Changing the 8×6 size or the X=7 / Y=9 link delays without an explicit DEC
- Claiming torus benefits without applying the half-per-link-bandwidth iso-wire rule

### ACC-001 — Completeness of experimental matrix

`refines: REQ-001, REQ-002`
`measurable: true`

The report (or accompanying result tables) shall cover all five traffic patterns and both topologies under the iso-wire rule, with bufferable and bufferless called out. Synchronized RG evidence for allgather and allreduce shall be present. Checklist score: fraction of required matrix cells filled ≥ 0.90.

### ACC-002 — Iso-wire honesty

`refines: CTX-002, REQ-001`
`measurable: true`

Any mesh vs torus comparison shall state per-link bandwidth ratio (torus = ½ mesh) and equal bisection bandwidth. A comparison that gives torus full mesh per-link bandwidth fails this acceptance check.

### ACC-003 — Synchronized RG semantics

`refines: CTX-006, REQ-002`
`measurable: true`

For synchronized RG runs on allgather/allreduce, traces or model logs shall show: no data-plane grant issue before the full request set is complete; a single arbitration epoch; then uniform/coordinated grants. Violation ⇒ FAIL for that mechanism cell.

### ACC-004 — Async allgather multicast-tree grant

`refines: CTX-006, REQ-002`
`measurable: true`

For asynchronous allgather RG, each grant shall be attributable to **one source’s multicast tree** (paths/schedule documented). Report shall contrast this against synchronized RG on the same allgather workload.

### ACC-005 — Baseline relative improvement reporting

`refines: REQ-003, REQ-004`
`measurable: true`

For each pattern, report RG completion latency relative to baseline packet switching (speedup or slowdown). Magic Gap between any analytic prediction and simulation ≤ 2× on latency for the headline configurations, with assumptions stated.

### DOF-001 — Open design dimensions

`refines: CTX-006`

Open degrees of freedom (explore; record choices in DEC-*):

- Request/grant message formats, VC or sideband control network vs in-band
- Arbitration policy (age, round-robin, tree-depth aware, quota)
- Multicast tree construction for async allgather grants (dimension-order spanning tree, recursive doubling embedding, etc.)
- Phasing of allreduce (rabenseifner vs tree reduce+broadcast) under RG
- Injection rate, message size, flit width, number of VCs (bufferable)
- Bufferless conflict resolution (deflection vs NACK/retry) interacting with grants
- Whether broadcast/reduce use a fixed root or rotate roots

### DOF-002 — Modeling fidelity

`refines: CTX-003, CTX-004`

Cycle-accurate vs flit-level vs coarse analytic models are acceptable if Magic Gap is reported. Prefer a directed or dedicated collective model before full gem5/RTL.
