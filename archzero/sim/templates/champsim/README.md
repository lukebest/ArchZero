# ChampSim mechanism source scaffolds

These `.cc`/`.h` stubs are emitted into candidate workdirs by
`write_champsim_scaffold` for prefetch / replacement families.

They are **not** linked into ArchZero's optional ChampSim binary until you:

1. Copy sources into a ChampSim checkout under `prefetcher/` or `replacement/`.
2. Point `champsim_config.json` L2C module names at them.
3. Rebuild (`JOBS=2 bash tools/setup_champsim.sh` or ChampSim's own build).

Stock runs without a rebuilt binary still fail-closed under `strict_evidence`.
