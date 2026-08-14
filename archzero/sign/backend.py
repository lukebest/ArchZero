"""SignBackend ABC — Tier6 reserved; NullSignBackend always unavailable."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archzero.config import FactoryConfig
from archzero.sign.ppa import PPAMetrics


@dataclass
class SignRequest:
    candidate_id: str
    workdir: Path
    verilog_files: list[str] = field(default_factory=list)
    top: str = "top"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignResult:
    ok: bool
    unavailable: bool = True
    backend: str = "null"
    ppa: PPAMetrics | None = None
    log: str = ""
    artifacts: list[str] = field(default_factory=list)


class SignBackend(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def run(self, req: SignRequest) -> SignResult: ...


class NullSignBackend(SignBackend):
    """Placeholder until OpenROAD/sky130 flow is wired."""

    name = "null"

    def available(self) -> bool:
        return False

    def run(self, req: SignRequest) -> SignResult:
        return SignResult(
            ok=False,
            unavailable=True,
            backend="null",
            log="Tier6 signoff reserved; not implemented",
        )


def get_sign_backend(cfg: FactoryConfig) -> SignBackend:
    from archzero.sign.registry import resolve_sign_backend

    return resolve_sign_backend(cfg)
