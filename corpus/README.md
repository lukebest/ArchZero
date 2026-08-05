# Corpus scaffold

Wiring scaffold for the paper’s clean-room / quantitative evaluation corpus.

- Target size: **95** papers (`manifest.json`)
- Current: stub entries + optional **real PDF** registration
- `status: scaffold` → `archzero corpus` will **not** invent a success rate
- **Tier6 / deployment Feedback are out of scope** for this corpus path

## Register a real PDF

```bash
archzero corpus-add-pdf my-paper /path/to/paper.pdf \
  --title "Paper title" --family prefetch --label equivalent
```

This copies the PDF under `corpus/papers/<id>/paper.pdf`, sets `pdf_real=true`,
and optionally stores a `cleanroom_label`. It does **not** flip status to
`complete` or compute success rates.

## Labels

`reproduce | equivalent | alternative | defective` (see `label_schema` in manifest).

Do not claim 95%/48% reproduction numbers until real PDFs are attached, evaluated,
and `status` is set to `complete`.

## Offline batch smoke

```bash
archzero corpus-eval-offline --through tier2 --limit 3
```

Runs FakeLLM through Tier0–2 per entry. `success_rate` stays `null` on scaffold.
Does **not** exercise Tier6 or deployment Feedback.

