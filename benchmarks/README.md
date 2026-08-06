# Benchmarks

Trace corpus for Tier3/Tier4 ChampSim (and optionally gem5).

## Layout

- `suites.yaml` — `small` / `full` suite definitions
- `manifest.json` — expected trace names + checksums
- `traces/` — binary traces (gitignored when large; synthetic demos can be regenerated)
- `fetch_traces.py` — download or synthesize traces

## Quick start

```bash
python benchmarks/fetch_traces.py --synthetic
```

Then in `archzero.toml`:

```toml
[sim]
backend = "champsim"
champsim_bin = "tools/champsim/bin/champsim"
traces_dir = "benchmarks/traces"
```

Synthetic traces are for **layout / CI smoke only**. Replace with real ChampSim
traces before claiming architectural results.

## Optional CI smoke

See [tools/CHAMPSIM.md](../tools/CHAMPSIM.md) for turning `pytest -m champsim` from skip → green.
