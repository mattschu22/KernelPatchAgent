"""Tests for kernel_patcher.models — zero API tokens."""

import pytest

from kernel_patcher.models import (
    BugInstance,
    EvalResult,
    EvalStatus,
    PatchResponse,
    PipelineResult,
)


class TestBugInstance:
    def test_basic_creation(self):
        bug = BugInstance(instance_id="x", issue="crash", code="int x;")
        assert bug.instance_id == "x"
        assert bug.files == []
        assert bug.category == ""

    def test_with_all_fields(self):
        bug = BugInstance(
            instance_id="test_123",
            issue="KASAN bug",
            code="void f() {}",
            files=["file.c"],
            category="Networking",
        )
        assert bug.files == ["file.c"]
        assert bug.category == "Networking"


class TestPatchResponse:
    def test_defaults(self):
        resp = PatchResponse(instance_id="x", raw_response="raw")
        assert resp.patched_files == {}
        assert resp.diff == ""

    def test_with_patched_files(self):
        resp = PatchResponse(
            instance_id="x",
            raw_response="raw",
            patched_files={"a.c": "code"},
            diff="---\n+++\n",
        )
        assert "a.c" in resp.patched_files


class TestEvalResult:
    def test_status_values(self):
        assert EvalStatus.CORRECT.value == "c"
        assert EvalStatus.INCORRECT.value == "i"
        assert EvalStatus.NOT_APPLIED.value == "na"


class TestPipelineResult:
    def test_categorization(self):
        results = [
            EvalResult(instance_id="a", status=EvalStatus.CORRECT),
            EvalResult(instance_id="b", status=EvalStatus.INCORRECT),
            EvalResult(instance_id="c", status=EvalStatus.NOT_APPLIED),
            EvalResult(instance_id="d", status=EvalStatus.CORRECT),
        ]
        pr = PipelineResult(results=results)
        assert len(pr.correct) == 2
        assert len(pr.incorrect) == 1
        assert len(pr.not_applied) == 1

    def test_empty_results(self):
        pr = PipelineResult()
        assert pr.correct == []
        assert pr.incorrect == []
        assert pr.not_applied == []
