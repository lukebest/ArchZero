# Example: register a real PDF into the corpus scaffold

This walks through attaching a **real PDF** already in the repo
(`docs/2604.03312v1.pdf`) so the ingest / status / offline-eval path is exercised.
It does **not** claim a clean-room reproduction result for that paper.

Tier6 signoff and deployment Feedback remain out of scope.

## 1. Register the PDF

```bash
archzero corpus-add-pdf arch-alphazero docs/2604.03312v1.pdf \
  --title "Computer Architecture's AlphaZero Moment" \
  --family other \
  --label equivalent
```

Checks performed:

- file exists
- `%PDF-` magic header
- copied to `corpus/papers/arch-alphazero/paper.pdf`
- `pdf_real=true` in manifest; corpus `status` stays `scaffold`

## 2. Inspect status

```bash
archzero corpus
```

Expect `pdf_real >= 1` and `success_rate: None`.

## 3. Offline batch smoke (FakeLLM)

```bash
archzero corpus-eval-offline --through tier2 --limit 5
```

Still does **not** invent a paper-level success rate.

## 4. Optional ChampSim (separate)

See [`tools/CHAMPSIM.md`](../tools/CHAMPSIM.md). Not required for corpus offline smoke.

## Current demo entry

After `tools/demo_corpus_pdf.sh`, the manifest includes `arch-alphazero` with:

- real PDF: `papers/arch-alphazero/paper.pdf` (`pdf_real=true`)
- NDF: `papers/arch-alphazero/problem.md`
- offline smoke: `archzero corpus-eval-offline --through tier2`

Still **scaffold** — do not report paper reproduction rates.

