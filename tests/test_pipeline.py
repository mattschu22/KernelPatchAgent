"""Tests for kernel_patcher.pipeline — all API calls mocked, zero tokens used."""

import json
from unittest.mock import MagicMock, patch

from kernel_patcher.models import EvalJob, EvalResult, EvalStatus, PatchResponse
from kernel_patcher.pipeline import KernelPatchPipeline
from tests.conftest import (
    SAMPLE_CRASH_REPORT,
)


class TestLoadBugs:
    def test_loads_from_json(self, config, data_json):
        pipeline = KernelPatchPipeline(config)
        bugs = pipeline.load_bugs(data_json)
        assert len(bugs) == 2
        assert bugs[0].instance_id == "bug_001"
        assert bugs[1].instance_id == "bug_002"

    def test_bug_fields(self, config, data_json):
        pipeline = KernelPatchPipeline(config)
        bugs = pipeline.load_bugs(data_json)
        assert SAMPLE_CRASH_REPORT.strip() in bugs[0].issue
        assert "[start of" in bugs[0].code


class TestRunInference:
    def test_returns_responses(self, config, sample_bugs, fake_client):
        pipeline = KernelPatchPipeline(config, client=fake_client)
        responses = pipeline.run_inference(sample_bugs)
        assert len(responses) == 2
        assert all(isinstance(r, PatchResponse) for r in responses)

    def test_responses_have_patched_files(self, config, sample_bugs, fake_client):
        pipeline = KernelPatchPipeline(config, client=fake_client)
        responses = pipeline.run_inference(sample_bugs)
        assert "net/smc/smc_sysctl.c" in responses[0].patched_files


class TestGenerateDiffs:
    def test_generates_diff(self, config, sample_bugs, fake_client):
        pipeline = KernelPatchPipeline(config, client=fake_client)
        responses = pipeline.run_inference(sample_bugs)
        pipeline.generate_diffs(sample_bugs, responses)

        # At least one response should have a non-empty diff
        diffs_with_content = [r for r in responses if r.diff]
        assert len(diffs_with_content) > 0

    def test_handles_empty_response(self, config, sample_bugs):
        pipeline = KernelPatchPipeline(config)
        responses = [
            PatchResponse(instance_id="bug_001", raw_response=""),
            PatchResponse(instance_id="bug_002", raw_response=""),
        ]
        pipeline.generate_diffs(sample_bugs, responses)
        # Should not crash; diffs should remain empty
        assert all(r.diff == "" for r in responses)


class TestBuildEvalJobs:
    def test_builds_jobs(self, config, sample_bugs, fake_client):
        pipeline = KernelPatchPipeline(config, client=fake_client)
        responses = pipeline.run_inference(sample_bugs)
        pipeline.generate_diffs(sample_bugs, responses)

        commits = {"bug_001": "abc123", "bug_002": "def456"}
        jobs = pipeline.build_eval_jobs(sample_bugs, responses, commits=commits)

        # Only responses with diffs become jobs
        assert all(isinstance(j, EvalJob) for j in jobs)
        for job in jobs:
            assert job.patch != ""

    def test_skips_no_diff(self, config, sample_bugs):
        pipeline = KernelPatchPipeline(config)
        responses = [
            PatchResponse(instance_id="bug_001", raw_response="", diff=""),
            PatchResponse(instance_id="bug_002", raw_response="", diff=""),
        ]
        jobs = pipeline.build_eval_jobs(sample_bugs, responses)
        assert len(jobs) == 0


class TestFullPipeline:
    def test_run_skip_eval(self, config, sample_bugs, fake_client):
        pipeline = KernelPatchPipeline(config, client=fake_client)
        result = pipeline.run(sample_bugs, skip_eval=True)

        assert len(result.responses) == 2
        assert result.results == []  # evaluation skipped

    def test_run_with_eval(self, config, sample_bugs, fake_client):
        pipeline = KernelPatchPipeline(config, client=fake_client)

        with patch("kernel_patcher.pipeline.KSuiteClient") as MockKSuite:
            mock_ksuite = MagicMock()
            MockKSuite.return_value = mock_ksuite

            # submit_all returns jobs with finished status
            def fake_submit(jobs, cfg):
                for j in jobs:
                    j.job_id = "fake_id"
                    j.status = "submitted"
                return jobs

            mock_ksuite.submit_all.side_effect = fake_submit

            # poll_all marks all as finished
            def fake_poll(jobs, **kwargs):
                for j in jobs:
                    j.status = "finished"
                return jobs

            mock_ksuite.poll_all.side_effect = fake_poll

            commits = {b.instance_id: "abc123" for b in sample_bugs}
            result = pipeline.run(
                sample_bugs,
                skip_eval=False,
                commits=commits,
            )

        assert len(result.responses) == 2
        # All should be correct since we mocked them as finished
        assert all(r.status == EvalStatus.CORRECT for r in result.results)


class TestSaveLoad:
    def test_save_responses(self, config, tmp_dir, fake_client, sample_bugs):
        pipeline = KernelPatchPipeline(config, client=fake_client)
        responses = pipeline.run_inference(sample_bugs)
        path = tmp_dir / "responses.json"
        pipeline.save_responses(responses, path)

        data = json.loads(path.read_text())
        assert len(data) == 2
        assert isinstance(data[0], str)

    def test_save_results(self, config, tmp_dir):
        pipeline = KernelPatchPipeline(config)
        results = [
            EvalResult(instance_id="a", status=EvalStatus.CORRECT),
            EvalResult(instance_id="b", status=EvalStatus.INCORRECT),
        ]
        path = tmp_dir / "results.json"
        pipeline.save_results(results, path)

        data = json.loads(path.read_text())
        assert "c" in data
        assert "i" in data
        assert "na" in data
