"""Tests for evaluation analysis and categorization."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from kernel_patcher.analysis import (
    analyze_by_subsystem,
    analyze_file_complexity,
    format_summary,
    run_analysis,
)

SAMPLE_PATCH_TYPES = [
    [["net/smc/smc_sysctl.c"], "Networking"],
    [["fs/ext4/file.c"], "File System"],
    [["drivers/hid/hid-core.c"], "Device Drivers"],
    [["mm/gup.c"], "Memory Management"],
    [["fs/ext4/file.c", "fs/ext4/namei.c"], "File System"],
]

SAMPLE_RESULTS = {
    "c": [0, 1],
    "i": [2],
    "na": [3, 4],
}


class TestAnalyzeBySubsystem:
    def test_counts_per_subsystem(self) -> None:
        breakdown = analyze_by_subsystem(SAMPLE_RESULTS, SAMPLE_PATCH_TYPES)
        assert breakdown["Networking"]["correct"] == 1
        assert breakdown["File System"]["correct"] == 1
        assert breakdown["File System"]["not_applied"] == 1
        assert breakdown["Device Drivers"]["incorrect"] == 1
        assert breakdown["Memory Management"]["not_applied"] == 1

    def test_totals(self) -> None:
        breakdown = analyze_by_subsystem(SAMPLE_RESULTS, SAMPLE_PATCH_TYPES)
        for _subsystem, counts in breakdown.items():
            expected = counts["correct"] + counts["incorrect"] + counts["not_applied"]
            assert counts["total"] == expected

    def test_empty_results(self) -> None:
        breakdown = analyze_by_subsystem({"c": [], "i": [], "na": []}, SAMPLE_PATCH_TYPES)
        assert breakdown == {}

    def test_sorted_by_name(self) -> None:
        breakdown = analyze_by_subsystem(SAMPLE_RESULTS, SAMPLE_PATCH_TYPES)
        keys = list(breakdown.keys())
        assert keys == sorted(keys)


class TestAnalyzeFileComplexity:
    def test_single_vs_multi(self) -> None:
        complexity = analyze_file_complexity(SAMPLE_RESULTS, SAMPLE_PATCH_TYPES)
        # Indices 0,1,2,3 are single-file; index 4 is multi-file
        assert complexity["single_file"]["total"] == 4
        assert complexity["multi_file"]["total"] == 1
        assert complexity["multi_file"]["not_applied"] == 1

    def test_empty(self) -> None:
        complexity = analyze_file_complexity({"c": [], "i": [], "na": []}, SAMPLE_PATCH_TYPES)
        assert complexity["single_file"]["total"] == 0
        assert complexity["multi_file"]["total"] == 0


class TestFormatSummary:
    def test_contains_subsystem_names(self) -> None:
        breakdown = analyze_by_subsystem(SAMPLE_RESULTS, SAMPLE_PATCH_TYPES)
        output = format_summary(breakdown, "Test Model")
        assert "Networking" in output
        assert "File System" in output
        assert "Test Model" in output
        assert "TOTAL" in output

    def test_contains_percentages(self) -> None:
        breakdown = analyze_by_subsystem(SAMPLE_RESULTS, SAMPLE_PATCH_TYPES)
        output = format_summary(breakdown)
        assert "%" in output


class TestRunAnalysis:
    def test_full_analysis(self, tmp_path: Path) -> None:
        # Write test data
        (tmp_path / "patch_types.json").write_text(json.dumps(SAMPLE_PATCH_TYPES))
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        (results_dir / "custom_results.json").write_text(json.dumps(SAMPLE_RESULTS))

        output = run_analysis(tmp_path)
        assert "Custom (8-agent)" in output
        assert "Networking" in output

    def test_missing_model_files(self, tmp_path: Path) -> None:
        (tmp_path / "patch_types.json").write_text(json.dumps(SAMPLE_PATCH_TYPES))
        (tmp_path / "results").mkdir()
        # No results files exist - should not crash
        output = run_analysis(tmp_path)
        assert output == ""  # No models found
