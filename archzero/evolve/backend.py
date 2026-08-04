"""Evolution backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from archzero.config import FactoryConfig
from archzero.models import Candidate


class EvolutionBackend(ABC):
    name: str = "base"

    @abstractmethod
    async def run(
        self,
        cfg: FactoryConfig,
        seeds: list[Candidate],
        *,
        generations: int,
        campaign_id: str | None = None,
    ) -> dict[str, Any]: ...
