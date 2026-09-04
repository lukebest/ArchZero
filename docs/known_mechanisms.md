# Known mechanisms (literature-intelligence index)

Index for novelty checks against scanned papers. Each entry is a mechanism *as built or specified in that paper*, not a proposed ArchZero candidate. Do not treat this file as an architecture idea list.

Domain tags used below: `LLM decode`, `NoC`, `cache`.

---

## From 2609.01084 (block-diffusion edge / WIFiV-LPDDR)

Insights: [`docs/insights/2609.01084.md`](insights/2609.01084.md)

### wifiv-lpddr-precision-tagged-read

- **Paper:** 2609.01084
- **What the hardware does:** Stores a canonical INT8 residual/weight word in a wide-I/O LPDDR organization; a precision tag selects a memory-side clamp/shift/compare/mux view (q8/q4/q2) or omits the payload (q0) before the DQ stream.
- **Structures:** 4F² VCT array; CBA (array vs. FinFET peri); 2.5D interposer DQ widening; local buffer; precision decoder; clamp/shift/comparators/muxes; per-payload scales applied on chip.
- **Domain tags:** LLM decode, cache
- **Insights:** [2609.01084](insights/2609.01084.md)

### brq-kv-canonical-lowrank-residual

- **Paper:** 2609.01084
- **What the hardware does:** Keeps every prefix KV entry as rank-2 coefficients plus a signed-INT8 residual master; residual bit-width is a query-ranked, span-cached tier map, never an eviction.
- **Structures:** Persistent `{C_K, C_V, INT8 residual, BF16 U}` in DRAM; one-time rank-2 bases after `N_min` tokens; per-span argsort map `τ`; offline clip/shift maps `Z4/Z2` and diagonal scales `D_p`; input-stationary Q tile; factorized Value aggregation path.
- **Domain tags:** LLM decode, cache
- **Insights:** [2609.01084](insights/2609.01084.md)

### dat-ffn-drift-tiered-replacement-delta-carry

- **Paper:** 2609.01084
- **What the hardware does:** Freezes an FFN channel order at block entry on a GPTQ-8 master, then maps per-step activation drift to q8 replacement, adjacent-corrected q4/q2 deltas, or q0 carry of cached gated-FFN state.
- **Structures:** GPTQ-8 codes + group scales; derived q4/q2 views; rank-8 adjacent corrections `Δ^{84}`, `Δ^{42}`; cached anchor `(X,G,U,S,Y)`; drift scalar `q_t` + EMA budget; gather buffer over 128-wide GPTQ groups on the IS array.
- **Domain tags:** LLM decode, cache
- **Insights:** [2609.01084](insights/2609.01084.md)

### input-stationary-mixed-precision-systolic-for-tagged-views

- **Paper:** 2609.01084
- **What the hardware does:** Holds a BF16 activation/query tile stationary while streaming precision-tagged KV residuals or FFN weight views (and separate low-rank / correction branches) into a mixed-precision array.
- **Structures:** Input-stationary systolic (adapted from prior mixed-precision DNN array); BF16 live activations; per-tier residual buckets; fused scale on low-bit partials.
- **Domain tags:** LLM decode
- **Insights:** [2609.01084](insights/2609.01084.md)

---

## From 2608.30509 (CHIPSMORE; NUS Fong group)

Insights: [`docs/insights/2608.30509.md`](insights/2608.30509.md)

Related (same lab, not independent): LEAP [`2609.00857`](insights/2609.00857.md). CHIPSMORE adopts LEAP spatial mapping.

### chipsmore-heterogeneous-rram-sram-pe

- **Paper:** 2608.30509
- **What the hardware does:** Pairs a nonvolatile analog RRAM-ACIM macro (frozen pretrained weights, SMAC) with a volatile SRAM-DCIM macro (LoRA and/or KV, digital SMAC) in one PE.
- **Structures:** RRAM-ACIM 256×256; SRAM-DCIM 256×64; AXI-Stream hosts into each macro; input/output buffers; adder tree on the SRAM path.
- **Domain tags:** LLM decode
- **Insights:** [2608.30509](insights/2608.30509.md)

### chipsmore-ipcn-dmac-router

- **Paper:** 2608.30509
- **What the hardware does:** Mesh routers execute DMAC / partial-sum / activation on in-flight runtime tensors (e.g. Q·Kᵀ) under a centrally sequenced 30-bit ISA, not just route packets.
- **Structures:** 2D-mesh unit router; N/S/E/W FIFOs (256 B); 7 computational macros; 4×7 output crossbar; AXI-Stream PE adapters; NPM (double-buffered CMD/CFR banks + CSR); configuration co-processor; network main controller; 30-bit instruction word.
- **Domain tags:** LLM decode, NoC
- **Insights:** [2608.30509](insights/2608.30509.md)

### chipsmore-hierarchical-kv-waterfill

- **Paper:** 2608.30509
- **What the hardware does:** Places KV in router scratchpad, then SRAM-DCIM (base mode only), then 2T0C eDRAM; LoRA mode withholds SRAM-DCIM from the KV pool; overflow stripes across chiplets.
- **Structures:** 16 MiB scratchpad / 16 MiB SRAM-DCIM / 64 MiB 2T0C eDRAM per compute tile (10 ms refresh); mode table (Base vs. LoRA); UCIe endpoints for striping.
- **Domain tags:** LLM decode, cache, NoC
- **Insights:** [2608.30509](insights/2608.30509.md)

### chipsmore-nonreplicated-layer-pipeline

- **Paper:** 2608.30509
- **What the hardware does:** Binds each transformer layer to a unique weight-bearing chiplet cluster and staggers requests so multiple requests occupy different layers while sharing one RRAM weight image; a stage holds exclusive occupancy.
- **Structures:** Spatially unrolled CT clusters; per-request KV/activation state in the hierarchy above; software offset injection (Fig. 4 in the paper).
- **Domain tags:** LLM decode, NoC
- **Insights:** [2608.30509](insights/2608.30509.md)

### chipsmore-state-aware-cluster-power-gate

- **Paper:** 2608.30509
- **What the hardware does:** After a layer step, keeps only the memory that holds volatile LoRA or KV powered; RRAM may go dark (nonvolatile); IPCN and idle compute are gated.
- **Structures:** Per-CT power domains around IPCN vs. SRAM/eDRAM vs. RRAM; retention policy by state class (pretrained / LoRA / KV).
- **Domain tags:** LLM decode, NoC
- **Insights:** [2608.30509](insights/2608.30509.md)

### chipsmore-ucie-chiplet-ct

- **Paper:** 2608.30509
- **What the hardware does:** Scales beyond one compute tile with UCIe die-to-die links (2 endpoints × 16 lanes per tile) while keeping the intra-tile fabric as the IPCN.
- **Structures:** Compute tile; UCIe endpoints; “Sys. Main Memory” off the configuration path; cluster size 4 chiplets in the evaluated table.
- **Domain tags:** NoC
- **Insights:** [2608.30509](insights/2608.30509.md)

---

## From 2609.00857 (LEAP; same NUS group as CHIPSMORE)

Insights: [`docs/insights/2609.00857.md`](insights/2609.00857.md)

CHIPSMORE’s intra-tile mapping/dataflow is this paper. Score novelty against *both*.

### leap-typed-imc-nmc-inc-macro

- **Paper:** 2609.00857
- **What the hardware does:** Assigns DSMMs (dynamic×static) to a 128×128 8-bit RRAM IMC PE, DDMMs (dynamic×dynamic) to router scratchpad+IRCU, and partial-result reduction to in-router INC.
- **Structures:** Macro = IMC PE + router; 32 KB (A) / 64 KB (D-decode) scratchpad; 256 B route buffers; 64-bit packets; 16 IRCU MACs; 16-bit datapath.
- **Domain tags:** LLM decode, NoC
- **Insights:** [2609.00857](insights/2609.00857.md)

### leap-d-imc-less-decode-partition

- **Paper:** 2609.00857
- **What the hardware does:** Physically splits the mesh: prefill macros keep IMC+router; decode macros drop the IMC PE and enlarge scratch so decode is a concurrent-scratch bandwidth farm; KV is shipped from prefill to decode overlapped with AllGather.
- **Structures:** LEAP-A homogeneous macros vs. LEAP-D two macro types; decode-region KV map (Fig. 8 in the paper); broadcast of the current token across the decode region.
- **Domain tags:** LLM decode, NoC, cache
- **Insights:** [2609.00857](insights/2609.00857.md)

### leap-deterministic-collective-dataflow

- **Paper:** 2609.00857
- **What the hardware does:** Compiles all post-partition traffic into a closed set of collectives (Broadcast, Reduce, ReduceScatter / E-ReduceScatter, AllReduce, AllGather, MAC) on spanning trees or rings, with declared compute-communication overlap.
- **Structures:** Table II primitives; IRCU as reduce engine; RPU / RPU-group geometry; rectangular row/column-major weight maps; `2⌈D/C⌉×2⌈D/C⌉` attention region.
- **Domain tags:** NoC, LLM decode
- **Insights:** [2609.00857](insights/2609.00857.md)

### leap-cyclic-kv-scratchpad

- **Paper:** 2609.00857
- **What the hardware does:** Appends decode tokens cyclically across scratchpads in the mapped KV rectangle so growing context load-balances local SRAM.
- **Structures:** Per-macro scratchpad; mapped K/V channels; cyclic write index (Fig. 4 in the paper).
- **Domain tags:** cache, LLM decode
- **Insights:** [2609.00857](insights/2609.00857.md)

### leap-serpentine-inter-layer-walk

- **Paper:** 2609.00857
- **What the hardware does:** Places successive decoder blocks (attention + FFN) in a serpentine so the last layer’s output token has a short path back to the first layer for the next decode step.
- **Structures:** Tile/channel/RPU/macro hierarchy; Llama-shaped “FFN capacity ≈ attention capacity” floorplan regularity (Fig. 5 in the paper).
- **Domain tags:** NoC, LLM decode
- **Insights:** [2609.00857](insights/2609.00857.md)

### leap-b2-imc-mutex-batch

- **Paper:** 2609.00857
- **What the hardware does:** Runs at most two requests by overlapping decode-A in the decode region with prefill-B in the prefill region, stalling one side at layer granularity when both need the single IMC weight image.
- **Structures:** Shared IMC in the prefill partition; software stall rules (attention vs. projection-loop priority); no extra weight replica.
- **Domain tags:** LLM decode
- **Insights:** [2609.00857](insights/2609.00857.md)

---

## From 2609.00450 (HBQ; MICRO 2026)

Insights: [`docs/insights/2609.00450.md`](insights/2609.00450.md)

### hbq-two-level-significand-scale

- **Paper:** 2609.00450
- **What the hardware does:** Quantizes a large L1 block with an FP8 (ue5m3) scale, then applies a 2-bit significand L2 scale `α = 1 + c/2^x` per micro-block so B=128 stays accurate; weights pick SIG2 vs. SIG3 per L1 block via a 1-bit `k`.
- **Structures:** L1 scale `s_b`; L2 encodings `c_a`, `c_w`; selector `k`; μB-to-1 FX adder tree; L2 dequant; FX2FP; L1 FP dequant; HBQ-E μB=32 / HBQ-A μB=8.
- **Domain tags:** LLM decode, cache
- **Insights:** [2609.00450](insights/2609.00450.md)

### hbq-large-block-fx-pe

- **Paper:** 2609.00450
- **What the hardware does:** Baseline (and HBQ) PE does B multiplies, a lossless fixed-point intra-block (or intra-μB) adder tree, then dequant and FP cross-block accumulate — large B amortizes the FP/dequant tail.
- **Structures:** Fig. 2 four-stage PE; FP2FX; B-to-1 or μB-to-1 FX tree; FP8 or PoT dequant; FP accumulator; 28 nm synthesized MAC.
- **Domain tags:** LLM decode
- **Insights:** [2609.00450](insights/2609.00450.md)

### hbq-unified-w-a-kv-systolic

- **Paper:** 2609.00450
- **What the hardware does:** Weight-stationary 4096-MAC array that treats 4-bit KV as weights so projection GEMMs and attention GEMMs (QKᵀ, SV) share one low-precision PE; Q and S are re-quantized after RoPE/softmax.
- **Structures:** 32 WS PEs × 128 MAC; 41.5 kB input buffer; weight preload registers; broadcast activation; online HBQ quantizer (3-stage, 128 act/cycle); assumed FP16 SIMD for nonlinear ops.
- **Domain tags:** LLM decode, cache
- **Insights:** [2609.00450](insights/2609.00450.md)

### hbq-mxint8-psum-block-quant

- **Paper:** 2609.00450
- **What the hardware does:** Compresses 32 FP16 partial sums to MXINT8 (block = N_PE) on the psum buffer write path and dequantizes on read so the same SRAM holds a larger WS tile and cuts EMA.
- **Structures:** 132 kB psum+scale buffer; MXINT8 quantizer/dequantizer; 32 FP16 adders; lossless FX reduction inside the PE still happens every B products.
- **Domain tags:** LLM decode, cache
- **Insights:** [2609.00450](insights/2609.00450.md)

### hbq-e2-a5-fp8-scale-format-stack

- **Paper:** 2609.00450
- **What the hardware does:** Fixes the one-level BQ format stack used under HBQ: 2-bit-exponent element format, 5-bit activations, FP8 ue5m3 block scales, weight FP4, L1 B=128 (DSE outcome, not a separate circuit).
- **Structures:** Same PE as `hbq-large-block-fx-pe`; scale format ue5m3 (no NVFP-style per-tensor scale in their default); packed 5-bit blocks to byte multiples.
- **Domain tags:** LLM decode
- **Insights:** [2609.00450](insights/2609.00450.md)

---

## Future scans

Stub. Append new papers below using the same fields (`id` slug, paper, one-line what the hardware does, structures, domain tags, link to `docs/insights/<arxiv-id>.md`). Do not invent mechanisms that were not in the PDF.

<!-- next: YYYY.NNNNN -->
