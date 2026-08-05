"""Local worker-pool skeleton for campaign scale-out (not distributed yet)."""

from archzero.worker.queue import LocalWorkerPool, WorkerJob

__all__ = ["LocalWorkerPool", "WorkerJob"]
