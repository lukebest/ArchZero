"""Simulation backend interface for Tier3/4."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archzero.config import FactoryConfig


@dataclass
class SimRequest:
    candidate_id: str
    workdir: Path
    patch_hint: str
    suite: str = "default"  # small | default | full
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimResult:
    ok: bool
    metrics: dict[str, Any]
    log: str = ""
    backend: str = ""
    unavailable: bool = False


class SimBackend(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def run(self, req: SimRequest) -> SimResult: ...


def get_backend(cfg: FactoryConfig) -> SimBackend:
    name = (cfg.sim.backend or "stub").lower()
    if name == "champsim":
        from archzero.sim.champsim import ChampSimBackend

        return ChampSimBackend(cfg)
    if name == "gem5":
        from archzero.sim.gem5 import Gem5Backend

        return Gem5Backend(cfg)
    if name == "directed":
        from archzero.sim.directed import DirectedSimBackend

        return DirectedSimBackend(cfg)
    from archzero.sim.stub import StubSimBackend

    return StubSimBackend(cfg)
