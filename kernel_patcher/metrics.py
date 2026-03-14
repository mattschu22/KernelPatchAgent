"""Pipeline observability: timing, token tracking, and success/failure rates."""

from __future__ import annotations

import logging
import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


@dataclass
class InferenceEvent:
    """A single inference call with timing and outcome."""

    instance_id: str
    duration_s: float
    success: bool
    error: str = ""
    patched_file_count: int = 0


@dataclass
class PipelineMetrics:
    """Collects and summarizes pipeline execution metrics.

    Usage:
        metrics = PipelineMetrics()
        with metrics.track_inference("bug_001") as tracker:
            result = client.generate(...)
            tracker.patched_file_count = len(parsed_files)
        metrics.summary()
    """

    events: list[InferenceEvent] = field(default_factory=list)
    _stage_timings: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def track_inference(self, instance_id: str) -> Iterator[InferenceEvent]:
        """Context manager to time and record a single inference call."""
        event = InferenceEvent(instance_id=instance_id, duration_s=0.0, success=False)
        start = time.monotonic()
        try:
            yield event
            event.success = True
        except Exception as e:
            event.error = str(e)
            raise
        finally:
            event.duration_s = time.monotonic() - start
            self.events.append(event)

    @contextmanager
    def track_stage(self, name: str) -> Iterator[None]:
        """Time a named pipeline stage (e.g. 'inference', 'diff_generation')."""
        start = time.monotonic()
        try:
            yield
        finally:
            self._stage_timings[name] = time.monotonic() - start

    @property
    def total_events(self) -> int:
        return len(self.events)

    @property
    def successful(self) -> list[InferenceEvent]:
        return [e for e in self.events if e.success]

    @property
    def failed(self) -> list[InferenceEvent]:
        return [e for e in self.events if not e.success]

    @property
    def success_rate(self) -> float:
        if not self.events:
            return 0.0
        return len(self.successful) / len(self.events)

    @property
    def durations(self) -> list[float]:
        return [e.duration_s for e in self.events]

    def percentile(self, p: float) -> float:
        """Compute the p-th percentile of inference durations."""
        if not self.durations:
            return 0.0
        sorted_d = sorted(self.durations)
        idx = int(len(sorted_d) * p / 100)
        idx = min(idx, len(sorted_d) - 1)
        return sorted_d[idx]

    def summary(self) -> dict[str, object]:
        """Produce a summary dict suitable for logging or JSON serialization."""
        durations = self.durations
        result: dict[str, object] = {
            "total_inferences": self.total_events,
            "successful": len(self.successful),
            "failed": len(self.failed),
            "success_rate": round(self.success_rate, 4),
        }
        if durations:
            result["latency"] = {
                "mean_s": round(statistics.mean(durations), 3),
                "median_s": round(statistics.median(durations), 3),
                "p95_s": round(self.percentile(95), 3),
                "p99_s": round(self.percentile(99), 3),
                "min_s": round(min(durations), 3),
                "max_s": round(max(durations), 3),
            }
        if self._stage_timings:
            result["stage_timings_s"] = {k: round(v, 3) for k, v in self._stage_timings.items()}
        patches_produced = sum(e.patched_file_count for e in self.successful)
        result["total_patched_files"] = patches_produced
        return result

    def log_summary(self) -> None:
        """Log the metrics summary at INFO level."""
        s = self.summary()
        logger.info("Pipeline metrics: %s", s)
