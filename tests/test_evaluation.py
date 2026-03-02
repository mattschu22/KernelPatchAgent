"""Tests for kernel_patcher.evaluation — zero API tokens, no kSuite needed."""

import pytest

from kernel_patcher.evaluation import classify_results, results_to_dict
from kernel_patcher.models import EvalJob, EvalResult, EvalStatus


def _make_job(name: str, status: str) -> EvalJob:
    return EvalJob(
        name=name,
        instance_id=name,
        job_id=f"job_{name}",
        patch="diff",
        commit="abc123",
        reproducer="int main(){}",
        cfg="CONFIG_X=y",
        syz_check="check",
        status=status,
    )


class TestClassifyResults:
    def test_finished_is_correct(self):
        jobs = [_make_job("a", "finished")]
        results = classify_results(jobs)
        assert len(results) == 1
        assert results[0].status == EvalStatus.CORRECT

    def test_aborted_is_incorrect(self):
        jobs = [_make_job("a", "aborted")]
        results = classify_results(jobs)
        assert results[0].status == EvalStatus.INCORRECT

    def test_other_status_is_not_applied(self):
        jobs = [_make_job("a", "submit_failed")]
        results = classify_results(jobs)
        assert results[0].status == EvalStatus.NOT_APPLIED

    def test_mixed_results(self):
        jobs = [
            _make_job("a", "finished"),
            _make_job("b", "aborted"),
            _make_job("c", "submit_failed"),
            _make_job("d", "finished"),
        ]
        results = classify_results(jobs)
        assert len([r for r in results if r.status == EvalStatus.CORRECT]) == 2
        assert len([r for r in results if r.status == EvalStatus.INCORRECT]) == 1
        assert len([r for r in results if r.status == EvalStatus.NOT_APPLIED]) == 1


class TestResultsToDict:
    def test_format(self):
        results = [
            EvalResult(instance_id="a", status=EvalStatus.CORRECT),
            EvalResult(instance_id="b", status=EvalStatus.INCORRECT),
            EvalResult(instance_id="c", status=EvalStatus.NOT_APPLIED),
        ]
        d = results_to_dict(results)
        assert d == {"c": [0], "i": [1], "na": [2]}

    def test_empty(self):
        d = results_to_dict([])
        assert d == {"c": [], "i": [], "na": []}

    def test_all_correct(self):
        results = [
            EvalResult(instance_id=str(i), status=EvalStatus.CORRECT) for i in range(3)
        ]
        d = results_to_dict(results)
        assert d["c"] == [0, 1, 2]
        assert d["i"] == []
        assert d["na"] == []
