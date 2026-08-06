"""Dedup + local worker pool skeleton."""

from __future__ import annotations

import pytest

from archzero.funnel.dedup import dedup_candidates, jaccard, tokenize
from archzero.models import Candidate
from archzero.worker.queue import LocalWorkerPool, WorkerJob


def test_jaccard_and_dedup():
    assert jaccard(tokenize("dead block filter"), tokenize("dead-block filter prefetch")) > 0.4
    cands = [
        Candidate(
            problem_id="p",
            title="Dead-block filter",
            mechanism="LLC dead block filter prefetch",
        ),
        Candidate(
            problem_id="p",
            title="Dead block filter",
            mechanism="LLC dead-block filter prefetch",
        ),
        Candidate(
            problem_id="p",
            title="Bypass throttle",
            mechanism="writeback bypass threshold",
        ),
    ]
    out = dedup_candidates(cands, threshold=0.7)
    assert len(out.kept) == 2
    assert len(out.dropped) == 1


@pytest.mark.asyncio
async def test_local_worker_pool():
    pool = LocalWorkerPool(concurrency=2)

    async def handler(job: WorkerJob[int]) -> int:
        return job.payload * 2

    jobs = [WorkerJob(id=str(i), payload=i) for i in range(5)]
    results = await pool.map(jobs, handler)
    assert len(results) == 5
    assert all(r.ok for r in results)
    assert sorted(r.value for r in results) == [0, 2, 4, 6, 8]
