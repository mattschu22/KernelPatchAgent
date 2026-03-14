"""Tests for pipeline metrics and observability."""

from __future__ import annotations

import time

import pytest

from kernel_patcher.metrics import PipelineMetrics


class TestTrackInference:
    def test_records_successful_event(self) -> None:
        m = PipelineMetrics()
        with m.track_inference("bug_001") as event:
            event.patched_file_count = 2
        assert len(m.events) == 1
        assert m.events[0].success is True
        assert m.events[0].instance_id == "bug_001"
        assert m.events[0].patched_file_count == 2
        assert m.events[0].duration_s > 0

    def test_records_failed_event(self) -> None:
        m = PipelineMetrics()
        with pytest.raises(ValueError, match="oops"), m.track_inference("bug_002"):
            raise ValueError("oops")
        assert len(m.events) == 1
        assert m.events[0].success is False
        assert m.events[0].error == "oops"

    def test_duration_is_measured(self) -> None:
        m = PipelineMetrics()
        with m.track_inference("bug_003"):
            time.sleep(0.01)
        assert m.events[0].duration_s >= 0.01


class TestTrackStage:
    def test_records_stage_timing(self) -> None:
        m = PipelineMetrics()
        with m.track_stage("inference"):
            time.sleep(0.01)
        assert "inference" in m._stage_timings
        assert m._stage_timings["inference"] >= 0.01

    def test_multiple_stages(self) -> None:
        m = PipelineMetrics()
        with m.track_stage("a"):
            pass
        with m.track_stage("b"):
            pass
        assert "a" in m._stage_timings
        assert "b" in m._stage_timings


class TestSuccessRate:
    def test_all_successful(self) -> None:
        m = PipelineMetrics()
        for i in range(5):
            with m.track_inference(f"bug_{i}"):
                pass
        assert m.success_rate == 1.0

    def test_mixed(self) -> None:
        m = PipelineMetrics()
        with m.track_inference("ok"):
            pass
        with pytest.raises(RuntimeError), m.track_inference("fail"):
            raise RuntimeError("bad")
        assert m.success_rate == 0.5

    def test_empty(self) -> None:
        m = PipelineMetrics()
        assert m.success_rate == 0.0


class TestPercentile:
    def test_p95(self) -> None:
        m = PipelineMetrics()
        for i in range(100):
            with m.track_inference(f"bug_{i}"):
                pass
        p95 = m.percentile(95)
        assert p95 >= 0.0

    def test_empty(self) -> None:
        m = PipelineMetrics()
        assert m.percentile(95) == 0.0


class TestSummary:
    def test_contains_expected_keys(self) -> None:
        m = PipelineMetrics()
        with m.track_inference("bug_001") as event:
            event.patched_file_count = 3
        with m.track_stage("inference"):
            pass
        s = m.summary()
        assert s["total_inferences"] == 1
        assert s["successful"] == 1
        assert s["failed"] == 0
        assert s["success_rate"] == 1.0
        assert "latency" in s
        assert "stage_timings_s" in s
        assert s["total_patched_files"] == 3

    def test_empty_summary(self) -> None:
        m = PipelineMetrics()
        s = m.summary()
        assert s["total_inferences"] == 0
        assert s["success_rate"] == 0.0
