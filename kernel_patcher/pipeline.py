"""End-to-end kernel patching pipeline.

Ties together: load data -> inference -> parse responses -> generate diffs -> evaluate.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from kernel_patcher.config import PipelineConfig
from kernel_patcher.diff import DiffGenerator
from kernel_patcher.evaluation import KSuiteClient, classify_results, results_to_dict
from kernel_patcher.inference import ModelClient, create_client, run_inference
from kernel_patcher.metrics import PipelineMetrics
from kernel_patcher.models import (
    BugInstance,
    EvalJob,
    EvalResult,
    PatchResponse,
    PipelineResult,
)
from kernel_patcher.parser import Parser
from kernel_patcher.retry import retry_failed_patches

logger = logging.getLogger(__name__)


class KernelPatchPipeline:
    """Orchestrates the full kernel patching and evaluation pipeline."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        client: ModelClient | None = None,
    ):
        self.config = config or PipelineConfig()
        self.client = client
        self.parser = Parser()
        self.diff_gen = DiffGenerator()
        self.metrics = PipelineMetrics()

    def load_bugs(self, data_path: str | Path | None = None) -> list[BugInstance]:
        """Load bug instances from a JSON data file.

        Expected format: list of dicts with keys: instance_id, issue, code.
        """
        if data_path is None:
            assert self.config.data_dir is not None
            data_path = self.config.data_dir / "data.json"
        data_path = Path(data_path)

        with open(data_path) as f:
            raw = json.load(f)

        bugs = []
        for item in raw:
            bugs.append(
                BugInstance(
                    instance_id=item.get("instance_id", ""),
                    issue=item.get("issue", ""),
                    code=item.get("code", ""),
                    files=item.get("files", []),
                    category=item.get("category", ""),
                )
            )
        return bugs

    def load_patch_types(self) -> list[list[str]]:
        """Load the patch_types.json benchmark categorization."""
        assert self.config.data_dir is not None
        path = self.config.data_dir / "patch_types.json"
        with open(path) as f:
            result: list[list[str]] = json.load(f)
            return result

    def run_inference(self, bugs: list[BugInstance]) -> list[PatchResponse]:
        """Run model inference on a list of bugs."""
        return run_inference(bugs, self.config, self.client)

    def generate_diffs(
        self, bugs: list[BugInstance], responses: list[PatchResponse]
    ) -> list[PatchResponse]:
        """Generate git diffs for each response by comparing original and patched files."""
        for bug, resp in zip(bugs, responses, strict=True):
            if not resp.patched_files:
                continue
            try:
                original_files = self.parser.parse_input(bug.code)
                resp.diff = self.diff_gen.generate(original_files, resp.patched_files)
            except Exception as e:
                logger.error("Diff generation failed for %s: %s", bug.instance_id, e)
                resp.diff = ""
        return responses

    def build_eval_jobs(
        self,
        bugs: list[BugInstance],
        responses: list[PatchResponse],
        commits: dict[str, str] | None = None,
        reproducers: dict[str, str] | None = None,
        configs: dict[str, str] | None = None,
        syz_checks: dict[str, str] | None = None,
    ) -> list[EvalJob]:
        """Build evaluation jobs from inference responses.

        The commits, reproducers, configs, and syz_checks dicts map instance_id
        to their respective values. In a full deployment these come from kBench
        and syzkaller data.
        """
        commits = commits or {}
        reproducers = reproducers or {}
        configs = configs or {}
        syz_checks = syz_checks or {}

        jobs = []
        for i, (bug, resp) in enumerate(zip(bugs, responses, strict=True)):
            iid = bug.instance_id
            if not resp.diff:
                continue
            jobs.append(
                EvalJob(
                    name=f"{self.config.model.value}_{i}",
                    instance_id=iid,
                    job_id="",
                    patch=resp.diff,
                    commit=commits.get(iid, ""),
                    reproducer=reproducers.get(iid, ""),
                    cfg=configs.get(iid, ""),
                    syz_check=syz_checks.get(iid, ""),
                )
            )
        return jobs

    def evaluate(self, jobs: list[EvalJob]) -> list[EvalResult]:
        """Submit jobs to kSuite and poll until completion."""
        ksuite = KSuiteClient(self.config.ksuite_url)
        jobs = ksuite.submit_all(jobs, self.config)
        jobs = ksuite.poll_all(jobs)
        return classify_results(jobs)

    def run(
        self,
        bugs: list[BugInstance],
        skip_eval: bool = False,
        commits: dict[str, str] | None = None,
        reproducers: dict[str, str] | None = None,
        configs: dict[str, str] | None = None,
        syz_checks: dict[str, str] | None = None,
        max_retries: int = 0,
        compilation_errors: dict[str, str] | None = None,
    ) -> PipelineResult:
        """Run the full pipeline: inference -> diff -> evaluate -> retry.

        Args:
            bugs: List of bug instances to process.
            skip_eval: If True, skip the kSuite evaluation step.
            commits: Map of instance_id -> parent commit hash.
            reproducers: Map of instance_id -> C reproducer code.
            configs: Map of instance_id -> kernel config.
            syz_checks: Map of instance_id -> syzkaller checkout.
            max_retries: Number of retry attempts for compilation failures.
            compilation_errors: Map of instance_id -> compiler error text
                for the feedback loop.

        Returns:
            PipelineResult with responses and (optionally) evaluation results.
        """
        result = PipelineResult()

        with self.metrics.track_stage("inference"):
            logger.info("Starting inference for %d bugs", len(bugs))
            responses = self.run_inference(bugs)
            result.responses = responses

        with self.metrics.track_stage("diff_generation"):
            logger.info("Generating diffs")
            self.generate_diffs(bugs, responses)

        if not skip_eval:
            with self.metrics.track_stage("evaluation"):
                logger.info("Building evaluation jobs")
                jobs = self.build_eval_jobs(
                    bugs,
                    responses,
                    commits,
                    reproducers,
                    configs,
                    syz_checks,
                )
                logger.info("Submitting %d jobs for evaluation", len(jobs))
                result.results = self.evaluate(jobs)

            # Retry compilation failures with feedback
            if max_retries > 0 and result.results:
                with self.metrics.track_stage("retry"):
                    client = self.client or create_client(self.config)
                    result.responses = retry_failed_patches(
                        bugs=bugs,
                        responses=result.responses,
                        results=result.results,
                        client=client,
                        parser=self.parser,
                        compilation_errors=compilation_errors,
                        max_retries=max_retries,
                    )
                    # Re-generate diffs and re-evaluate retried patches
                    self.generate_diffs(bugs, result.responses)
                    jobs = self.build_eval_jobs(
                        bugs,
                        result.responses,
                        commits,
                        reproducers,
                        configs,
                        syz_checks,
                    )
                    if jobs:
                        result.results = self.evaluate(jobs)

        self.metrics.log_summary()
        return result

    def save_responses(self, responses: list[PatchResponse], path: str | Path) -> None:
        """Save raw responses to a JSON file."""
        data = [r.raw_response for r in responses]
        with open(path, "w") as f:
            json.dump(data, f)

    def save_results(self, results: list[EvalResult], path: str | Path) -> None:
        """Save evaluation results to a JSON file."""
        data = results_to_dict(results)
        with open(path, "w") as f:
            json.dump(data, f)
