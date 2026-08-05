"""In-process asyncio worker pool skeleton for funnel scale experiments."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class WorkerJob(Generic[T]):
    id: str
    payload: T
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerResult(Generic[R]):
    job_id: str
    ok: bool
    value: R | None = None
    error: str | None = None


class LocalWorkerPool:
    """Bounded concurrency worker pool (single machine)."""

    def __init__(self, concurrency: int = 4) -> None:
        self.concurrency = max(1, concurrency)

    async def map(
        self,
        jobs: list[WorkerJob[T]],
        handler: Callable[[WorkerJob[T]], Awaitable[R]],
    ) -> list[WorkerResult[R]]:
        sem = asyncio.Semaphore(self.concurrency)

        async def _one(job: WorkerJob[T]) -> WorkerResult[R]:
            async with sem:
                try:
                    value = await handler(job)
                    return WorkerResult(job_id=job.id, ok=True, value=value)
                except Exception as exc:  # noqa: BLE001
                    return WorkerResult(job_id=job.id, ok=False, error=str(exc))

        return list(await asyncio.gather(*[_one(j) for j in jobs]))
