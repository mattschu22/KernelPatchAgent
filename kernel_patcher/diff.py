"""Generate unified diffs between old and new file contents using git."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile


class DiffGenerator:
    """Generate unified diffs by writing files to temp directories and running git diff."""

    def __init__(self, work_dir: str | None = None):
        self._work_dir = work_dir

    def generate(self, old_files: dict[str, str], new_files: dict[str, str]) -> str:
        """Generate a unified diff between old and new file versions.

        Args:
            old_files: Mapping of filepath -> original content.
            new_files: Mapping of filepath -> patched content.

        Returns:
            Unified diff string suitable for `git apply`.
        """
        work_dir = self._work_dir or tempfile.mkdtemp(prefix="kpatch_diff_")
        old_dir = os.path.join(work_dir, "old")
        new_dir = os.path.join(work_dir, "new")

        try:
            result_parts: list[str] = []
            all_files = set(list(old_files.keys()) + list(new_files.keys()))

            for filename in sorted(all_files):
                if not filename:
                    continue

                old_path = os.path.join(old_dir, filename)
                new_path = os.path.join(new_dir, filename)

                os.makedirs(os.path.dirname(old_path), exist_ok=True)
                os.makedirs(os.path.dirname(new_path), exist_ok=True)

                with open(old_path, "w") as f:
                    f.write(old_files.get(filename, ""))
                with open(new_path, "w") as f:
                    f.write(new_files.get(filename, ""))

                proc = subprocess.run(
                    ["git", "diff", "--no-index", old_path, new_path],
                    capture_output=True,
                    text=True,
                )

                # Normalize absolute temp paths to relative kernel paths
                diff_text = proc.stdout
                diff_text = diff_text.replace(old_path, f"/{filename}")
                diff_text = diff_text.replace(new_path, f"/{filename}")
                result_parts.append(diff_text)

            return "".join(result_parts)
        finally:
            if self._work_dir is None:
                shutil.rmtree(work_dir, ignore_errors=True)
