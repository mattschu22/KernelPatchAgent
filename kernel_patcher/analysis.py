"""Evaluation analysis: categorize results by subsystem and failure mode."""

from __future__ import annotations

import json
from pathlib import Path


def load_results(path: str | Path) -> dict[str, list[int]]:
    """Load a results JSON file ({c: [...], i: [...], na: [...]})."""
    with open(path) as f:
        data: dict[str, list[int]] = json.load(f)
        return data


def load_patch_types(path: str | Path) -> list[list[str]]:
    """Load patch_types.json: [[files, subsystem], ...]."""
    with open(path) as f:
        data: list[list[str]] = json.load(f)
        return data


def analyze_by_subsystem(
    results: dict[str, list[int]],
    patch_types: list[list[str]],
) -> dict[str, dict[str, int]]:
    """Break down results by kernel subsystem.

    Returns:
        {subsystem: {correct: N, incorrect: N, not_applied: N, total: N}}
    """
    subsystems: dict[str, dict[str, int]] = {}

    # Build index -> subsystem mapping
    idx_to_subsystem: dict[int, str] = {}
    for idx, entry in enumerate(patch_types):
        subsystem = entry[-1] if entry else "Unknown"
        idx_to_subsystem[idx] = subsystem

    # Count by status
    status_map = {"c": "correct", "i": "incorrect", "na": "not_applied"}
    for status_key, label in status_map.items():
        for idx in results.get(status_key, []):
            subsystem = idx_to_subsystem.get(idx, "Unknown")
            if subsystem not in subsystems:
                subsystems[subsystem] = {"correct": 0, "incorrect": 0, "not_applied": 0, "total": 0}
            subsystems[subsystem][label] += 1
            subsystems[subsystem]["total"] += 1

    return dict(sorted(subsystems.items()))


def analyze_file_complexity(
    results: dict[str, list[int]],
    patch_types: list[list[str]],
) -> dict[str, dict[str, int]]:
    """Break down results by number of files involved (single vs. multi-file).

    Returns:
        {"single_file": {correct: N, ...}, "multi_file": {correct: N, ...}}
    """
    buckets: dict[str, dict[str, int]] = {
        "single_file": {"correct": 0, "incorrect": 0, "not_applied": 0, "total": 0},
        "multi_file": {"correct": 0, "incorrect": 0, "not_applied": 0, "total": 0},
    }

    status_map = {"c": "correct", "i": "incorrect", "na": "not_applied"}
    for status_key, label in status_map.items():
        for idx in results.get(status_key, []):
            if idx < len(patch_types):
                files = patch_types[idx][0] if patch_types[idx] else []
                bucket = "single_file" if len(files) <= 1 else "multi_file"
            else:
                bucket = "single_file"
            buckets[bucket][label] += 1
            buckets[bucket]["total"] += 1

    return buckets


def compare_models(
    results_paths: dict[str, str | Path],
    patch_types: list[list[str]],
) -> dict[str, dict[str, dict[str, int]]]:
    """Compare multiple models' results by subsystem.

    Args:
        results_paths: {model_name: path_to_results.json}
        patch_types: The patch_types categorization.

    Returns:
        {model_name: {subsystem: {correct: N, incorrect: N, not_applied: N, total: N}}}
    """
    comparison: dict[str, dict[str, dict[str, int]]] = {}
    for model_name, path in results_paths.items():
        results = load_results(path)
        comparison[model_name] = analyze_by_subsystem(results, patch_types)
    return comparison


def format_summary(
    subsystem_data: dict[str, dict[str, int]],
    model_name: str = "",
) -> str:
    """Format subsystem analysis as a human-readable table."""
    cols = f"{'Fixed':>6} {'Wrong':>6} {'Compile Err':>12} {'Total':>6} {'Fix %':>6}"
    header = f"{'Subsystem':<28} {cols}"
    if model_name:
        lines = [f"\n=== {model_name} ===", header, "-" * len(header)]
    else:
        lines = [header, "-" * len(header)]

    totals = {"correct": 0, "incorrect": 0, "not_applied": 0, "total": 0}
    for subsystem, counts in subsystem_data.items():
        fix_pct = (
            f"{counts['correct'] / counts['total'] * 100:.1f}%" if counts["total"] > 0 else "N/A"
        )
        lines.append(
            f"{subsystem:<28} {counts['correct']:>6} {counts['incorrect']:>6} "
            f"{counts['not_applied']:>12} {counts['total']:>6} {fix_pct:>6}"
        )
        for k in totals:
            totals[k] += counts[k]

    lines.append("-" * len(header))
    total_pct = (
        f"{totals['correct'] / totals['total'] * 100:.1f}%" if totals["total"] > 0 else "N/A"
    )
    lines.append(
        f"{'TOTAL':<28} {totals['correct']:>6} {totals['incorrect']:>6} "
        f"{totals['not_applied']:>12} {totals['total']:>6} {total_pct:>6}"
    )

    return "\n".join(lines)


def run_analysis(data_dir: str | Path) -> str:
    """Run full analysis on all model results in data_dir.

    Expects:
        data_dir/patch_types.json
        data_dir/results/custom_results.json
        data_dir/results/claude_results.json
        data_dir/results/gpt_results.json
    """
    data_dir = Path(data_dir)
    patch_types = load_patch_types(data_dir / "patch_types.json")

    results_dir = data_dir / "results"
    model_files = {
        "Custom (8-agent)": results_dir / "custom_results.json",
        "Claude (sonnet-4)": results_dir / "claude_results.json",
        "GPT-4.1": results_dir / "gpt_results.json",
    }

    output_parts: list[str] = []

    for model_name, path in model_files.items():
        if not path.exists():
            continue
        results = load_results(path)
        subsystem_data = analyze_by_subsystem(results, patch_types)
        output_parts.append(format_summary(subsystem_data, model_name))

        # File complexity analysis
        complexity = analyze_file_complexity(results, patch_types)
        output_parts.append("\n  File complexity:")
        for bucket, counts in complexity.items():
            label = bucket.replace("_", "-")
            fix_rate = (
                f"{counts['correct'] / counts['total'] * 100:.1f}%"
                if counts["total"] > 0
                else "N/A"
            )
            output_parts.append(
                f"    {label}: {counts['correct']}/{counts['total']} fixed ({fix_rate})"
            )

    return "\n".join(output_parts)
