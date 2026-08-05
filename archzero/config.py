"""Configuration loading and defaults for the Idea Factory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from archzero.models import TaskClass, Tier, UsagePool

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = ROOT / ".archzero"
DEFAULT_CONFIG_PATH = ROOT / "archzero.toml"


class PoolConfig(BaseModel):
    cursor_models: list[str] = Field(
        default_factory=lambda: [
            "cursor-grok-4.5-high-fast",
            "cursor-grok-4.5",
            "composer-2.5",
        ]
    )
    other_prefixes: list[str] = Field(
        default_factory=lambda: ["claude-", "gpt-", "gemini-", "o1-", "o3-", "o4-"]
    )
    preferred_cursor: str = "cursor-grok-4.5-high-fast"
    preferred_other: str = "claude-4.6-sonnet"
    fallback_router: str = "auto-smart"
    fallback_auto: str = "auto"
    optimize_for: str = "balanced"
    model_params: dict[str, str] = Field(default_factory=dict)


class BudgetConfig(BaseModel):
    other_pool_max_tokens: int = 2_000_000
    other_pool_max_calls: int = 200
    # Cursor pool caps (0 = unlimited)
    cursor_pool_max_tokens: int = 0
    cursor_pool_max_calls: int = 0
    max_retries: int = 3
    concurrency: int = 4


class FunnelQuotas(BaseModel):
    tier0_keep: int = 200
    tier1_keep: int = 50
    tier2_keep: int = 20
    tier3_keep: int = 8
    tier4_keep: int = 3
    tier5_keep: int = 2
    tier6_keep: int = 2

    def keep_for(self, tier: Tier) -> int:
        return {
            Tier.T0: self.tier0_keep,
            Tier.T1: self.tier1_keep,
            Tier.T2: self.tier2_keep,
            Tier.T3: self.tier3_keep,
            Tier.T4: self.tier4_keep,
            Tier.T5: self.tier5_keep,
            Tier.T6: self.tier6_keep,
        }[tier]


class FunnelConfig(BaseModel):
    """Funnel policy knobs."""

    # When True, T3+ refuse PASS if configured real backend is unavailable
    strict_evidence: bool = True
    # Tier2: require majority of ensemble runs (when ensemble_n > 1)
    ensemble_n: int = 1
    # Run quant_eval spec + functional verifiers before insight
    use_verifiers: bool = True
    model_exec_timeout_s: int = 30
    model_exec_mem_mb: int = 512


class TaskRouting(BaseModel):
    """Map TaskClass → preferred UsagePool.

    Default: every task uses the Cursor pool (cursor-grok-4.5-high-fast).
    """

    routes: dict[str, str] = Field(
        default_factory=lambda: {
            TaskClass.BULK_SCREEN.value: UsagePool.CURSOR.value,
            TaskClass.EVOLVE.value: UsagePool.CURSOR.value,
            TaskClass.ANALYTIC.value: UsagePool.CURSOR.value,
            TaskClass.COMPREHEND.value: UsagePool.CURSOR.value,
            TaskClass.IDEATE.value: UsagePool.CURSOR.value,
            TaskClass.SYNTHESIZE.value: UsagePool.CURSOR.value,
            TaskClass.SPEC_GEN.value: UsagePool.CURSOR.value,
            TaskClass.FINAL_JUDGE.value: UsagePool.CURSOR.value,
        }
    )

    def pool_for(self, task: TaskClass) -> UsagePool:
        return UsagePool(self.routes.get(task.value, UsagePool.CURSOR.value))


class SimConfig(BaseModel):
    backend: str = "stub"  # stub | champsim | gem5 | directed
    champsim_bin: str | None = None
    gem5_bin: str | None = None
    traces_dir: str | None = None
    suites_file: str | None = None  # path to suites.yaml


class RtlConfig(BaseModel):
    pycircuit_root: str | None = None  # vendor/pycircuit
    pyc_toolchain_root: str | None = None
    baseline_design: str = "coupled_l2"
    require_verilator: bool = True
    optional_yosys_lec: bool = True


class SignConfig(BaseModel):
    """Tier6 physical signoff — reserved; enabled=False until implemented."""

    enabled: bool = False
    yosys_bin: str | None = None
    openroad_bin: str | None = None
    pdk: str | None = None
    liberty: str | None = None


class EvolveConfig(BaseModel):
    backend: str = "mapelites"  # mapelites | openevolve
    islands: int = 3
    generations: int = 10
    population_per_island: int = 20
    reenter_through: Tier = Tier.T2
    feature_dims: list[str] = Field(
        default_factory=lambda: ["family", "model_error", "speedup", "area_proxy"]
    )


class FactoryConfig(BaseModel):
    state_dir: Path = DEFAULT_STATE_DIR
    personas_dir: Path = ROOT / "archzero" / "personas"
    gauntlet_personas: Path | None = None
    cursor_api_key: str | None = None
    pools: PoolConfig = Field(default_factory=PoolConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    quotas: FunnelQuotas = Field(default_factory=FunnelQuotas)
    funnel: FunnelConfig = Field(default_factory=FunnelConfig)
    routing: TaskRouting = Field(default_factory=TaskRouting)
    sim: SimConfig = Field(default_factory=SimConfig)
    rtl: RtlConfig = Field(default_factory=RtlConfig)
    sign: SignConfig = Field(default_factory=SignConfig)
    evolve: EvolveConfig = Field(default_factory=EvolveConfig)
    cleanroom_n: int = 5
    default_through: Tier = Tier.T2

    @property
    def personas_root(self) -> Path:
        if self.gauntlet_personas is not None:
            return self.gauntlet_personas
        return self.personas_dir

    @property
    def db_path(self) -> Path:
        return self.state_dir / "factory.db"

    @property
    def artifacts_dir(self) -> Path:
        return self.state_dir / "artifacts"

    @property
    def transcripts_dir(self) -> Path:
        return self.state_dir / "transcripts"

    @property
    def scratch_dir(self) -> Path:
        return self.state_dir / "scratch"

    def ensure_dirs(self) -> None:
        for d in (
            self.state_dir,
            self.artifacts_dir,
            self.transcripts_dir,
            self.scratch_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def resolved_api_key(self) -> str:
        key = self.cursor_api_key or os.environ.get("CURSOR_API_KEY") or ""
        if not key:
            raise RuntimeError(
                "CURSOR_API_KEY is not set. Export it from "
                "Cursor Dashboard → Integrations, then retry."
            )
        return key.strip()

    def resolved_pycircuit_root(self) -> Path:
        if self.rtl.pycircuit_root:
            return Path(self.rtl.pycircuit_root)
        return ROOT / "vendor" / "pycircuit"

    def resolved_traces_dir(self) -> Path | None:
        if self.sim.traces_dir:
            return Path(self.sim.traces_dir)
        default = ROOT / "benchmarks" / "traces"
        return default if default.is_dir() else None


def load_config(path: Path | None = None) -> FactoryConfig:
    """Load FactoryConfig from TOML (optional) + env."""
    cfg_path = path or DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if cfg_path.is_file():
        import tomllib

        with cfg_path.open("rb") as f:
            data = tomllib.load(f)

    flat: dict[str, Any] = {}
    for key in (
        "state_dir",
        "gauntlet_personas",
        "personas_dir",
        "cursor_api_key",
        "cleanroom_n",
        "default_through",
    ):
        if key in data:
            flat[key] = data[key]
    for section in (
        "pools",
        "budget",
        "quotas",
        "funnel",
        "routing",
        "sim",
        "rtl",
        "sign",
        "evolve",
    ):
        if section in data and isinstance(data[section], dict):
            flat[section] = data[section]

    if "state_dir" in flat:
        flat["state_dir"] = Path(flat["state_dir"])
    if "personas_dir" in flat:
        flat["personas_dir"] = Path(flat["personas_dir"])
    if "gauntlet_personas" in flat:
        flat["gauntlet_personas"] = Path(flat["gauntlet_personas"])

    cfg = FactoryConfig(**flat)
    cfg.ensure_dirs()
    return cfg


def write_default_config(path: Path | None = None) -> Path:
    """Write a starter archzero.toml if missing."""
    target = path or DEFAULT_CONFIG_PATH
    if target.exists():
        return target
    target.write_text(
        """# ArchZero Idea Factory configuration
# See archzero.config.FactoryConfig for all fields.

# state_dir = ".archzero"
# personas_dir = "archzero/personas"
# cleanroom_n = 5
# default_through = "tier2"

[pools]
preferred_cursor = "cursor-grok-4.5-high-fast"
preferred_other = "claude-4.6-sonnet"

[budget]
other_pool_max_tokens = 2000000
other_pool_max_calls = 200
cursor_pool_max_tokens = 0
cursor_pool_max_calls = 0
concurrency = 4

[quotas]
tier0_keep = 200
tier1_keep = 50
tier2_keep = 20
tier3_keep = 8
tier4_keep = 3
tier5_keep = 2
tier6_keep = 2

[funnel]
strict_evidence = true
ensemble_n = 1
use_verifiers = true

[sim]
backend = "stub"
# backend = "directed"  # family event-model (Magic Gap friendly; not ChampSim)
# champsim_bin = "tools/champsim/bin/champsim"
# traces_dir = "benchmarks/traces"

[rtl]
# pycircuit_root = "vendor/pycircuit"
# pyc_toolchain_root = ".pycircuit_out/toolchain/install"

[sign]
enabled = false
# Tier6 physical signoff reserved — not implemented yet

[evolve]
backend = "mapelites"
islands = 3
generations = 10
""",
        encoding="utf-8",
    )
    return target
