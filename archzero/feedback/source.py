"""Feedback / telemetry layer — interface only (implementation deferred)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class FeedbackSource(ABC):
    """Deployment telemetry that calibrates evaluation and drives new questions."""

    @abstractmethod
    def collect(self) -> dict[str, Any]:
        """Collect raw telemetry counters / traces from deployment."""

    @abstractmethod
    def calibrate(self, models: list[str]) -> dict[str, Any]:
        """Calibrate analytic / sim models against telemetry."""

    @abstractmethod
    def drift_questions(self) -> list[str]:
        """Emit new open questions when workload drift is detected."""


class NullFeedbackSource(FeedbackSource):
    """Placeholder used until telemetry is implemented."""

    def collect(self) -> dict[str, Any]:
        raise NotImplementedError(
            "Feedback/telemetry layer is deferred. "
            "Wire a real FeedbackSource when deployment counters are available."
        )

    def calibrate(self, models: list[str]) -> dict[str, Any]:
        raise NotImplementedError("Feedback/telemetry layer is deferred.")

    def drift_questions(self) -> list[str]:
        # Soft no-op so pipeline can call without crashing
        return []
