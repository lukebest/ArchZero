# ChampSim optional smoke — turning skip → green

Tier3/Tier4 ChampSim tests are **optional**. Without a binary, CI/local pytest
reports `1 skipped` for `tests/test_champsim_optional.py`. This is intentional
fail-closed behavior under `strict_evidence` (missing binary → UNAVAILABLE, not PASS).

## Steps to make the optional smoke pass

1. Build ChampSim (needs time + deps; pin JOBS low on small RAM machines):

```bash
JOBS=2 bash tools/setup_champsim.sh
```

2. Synthesize or fetch traces:

```bash
python benchmarks/fetch_traces.py --synthetic
```

3. Point config at the binary:

```toml
[sim]
backend = "champsim"
champsim_bin = "tools/champsim/bin/champsim"
traces_dir = "benchmarks/traces"
```

4. Run only the optional marker:

```bash
uv run pytest -q -m champsim
```

Expect PASS/FAIL from real evidence — never a silent stub PASS when
`backend = "champsim"` and `strict_evidence = true`.

## Out of scope

- Tier6 OpenROAD/sky130 signoff
- Deployment telemetry Feedback calibration

## Related

Corpus offline batch (no ChampSim required): `archzero corpus-eval-offline`.

