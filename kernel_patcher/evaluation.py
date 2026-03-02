"""Evaluation pipeline: submit patches to kSuite and collect results."""

from __future__ import annotations

import logging
import time
from typing import Dict, List

from kernel_patcher.config import PipelineConfig
from kernel_patcher.models import EvalJob, EvalResult, EvalStatus

logger = logging.getLogger(__name__)


class KSuiteClient:
    """Client for the kSuite kernel testing infrastructure.

    Wraps the KBDr kGymClient API for job submission and polling.
    """

    def __init__(self, url: str):
        self._url = url
        self._client = None

    def _get_client(self):
        if self._client is None:
            from KBDr.kclient import kGymClient
            self._client = kGymClient(self._url)
        return self._client

    def submit_job(self, job: EvalJob, config: PipelineConfig) -> str:
        """Submit a single evaluation job to kSuite.

        Returns the job ID assigned by kSuite.
        """
        from KBDr.kclient import (
            kJobRequest,
            kBuilderArgument,
            kVMManagerArgument,
            KernelGitCommit,
            Reproducer,
        )

        ksrc = KernelGitCommit(
            gitUrl=config.git_url,
            commitId=job.commit,
            kConfig=job.cfg,
            arch="amd64",
            compiler="gcc",
            linker="ld",
        )
        builder = kBuilderArgument(
            kernelSource=ksrc,
            userspaceImage="buildroot.raw",
            patch=job.patch,
        )
        vm = kVMManagerArgument(
            reproducer=Reproducer(
                reproducerType="c",
                reproducerText=job.reproducer,
                syzkallerCheckout=job.syz_check,
            ),
            image=0,
            machineType="qemu:2-4096",
        )
        request = kJobRequest(
            jobWorkers=[builder, vm],
            tags={"name": job.name},
        )

        client = self._get_client()
        job_id = client.create_job(request)
        logger.info("Submitted %s -> %s", job.name, job_id)
        return str(job_id)

    def poll_job(self, job_id: str) -> str:
        """Check the status of a submitted job. Returns status string."""
        from KBDr.kclient import JobId

        client = self._get_client()
        status = client.get_job(JobId(job_id))
        return getattr(status, "status", "unknown")

    def submit_all(
        self, jobs: List[EvalJob], config: PipelineConfig
    ) -> List[EvalJob]:
        """Submit all evaluation jobs and update their job_id and status."""
        for job in jobs:
            try:
                job.job_id = self.submit_job(job, config)
                job.status = "submitted"
            except Exception as e:
                logger.error("Failed to submit %s: %s", job.name, e)
                job.status = "submit_failed"
        return jobs

    def poll_all(
        self, jobs: List[EvalJob], poll_interval: float = 30.0, max_polls: int = 100
    ) -> List[EvalJob]:
        """Poll all jobs until completion or timeout."""
        for attempt in range(max_polls):
            pending = [
                j
                for j in jobs
                if j.status not in ("finished", "aborted", "submit_failed")
            ]
            if not pending:
                break

            logger.info(
                "Poll %d: %d jobs still pending", attempt + 1, len(pending)
            )
            for job in pending:
                try:
                    job.status = self.poll_job(job.job_id)
                except Exception as e:
                    logger.warning("Poll failed for %s: %s", job.name, e)

            time.sleep(poll_interval)

        return jobs


def classify_results(jobs: List[EvalJob]) -> List[EvalResult]:
    """Convert completed jobs into evaluation results.

    Jobs that finished successfully are CORRECT; aborted jobs are INCORRECT;
    jobs that failed to submit are NOT_APPLIED.
    """
    results = []
    for job in jobs:
        if job.status == "finished":
            status = EvalStatus.CORRECT
        elif job.status == "aborted":
            status = EvalStatus.INCORRECT
        else:
            status = EvalStatus.NOT_APPLIED

        results.append(
            EvalResult(
                instance_id=job.instance_id,
                status=status,
                job_id=job.job_id,
            )
        )
    return results


def results_to_dict(results: List[EvalResult]) -> Dict[str, List[int]]:
    """Convert results list to the {c: [...], i: [...], na: [...]} format."""
    out: Dict[str, List[int]] = {"c": [], "i": [], "na": []}
    for i, r in enumerate(results):
        out[r.status.value].append(i)
    return out
