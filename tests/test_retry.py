"""Tests for the compilation feedback retry loop."""

from __future__ import annotations

from kernel_patcher.models import BugInstance, EvalResult, EvalStatus, PatchResponse
from kernel_patcher.parser import Parser
from kernel_patcher.retry import build_retry_prompt, retry_failed_patches
from tests.conftest import SAMPLE_RESPONSE_TEXT, FakeModelClient


class TestBuildRetryPrompt:
    def test_contains_original_issue(self) -> None:
        bug = BugInstance(instance_id="b1", issue="KASAN: use-after-free", code="int x;")
        prompt = build_retry_prompt(bug, "diff --git ...", "error: undeclared")
        assert "KASAN: use-after-free" in prompt

    def test_contains_previous_diff(self) -> None:
        bug = BugInstance(instance_id="b1", issue="crash", code="void f() {}")
        prompt = build_retry_prompt(bug, "--- a/f.c\n+++ b/f.c", "error: syntax")
        assert "--- a/f.c" in prompt

    def test_contains_compilation_error(self) -> None:
        bug = BugInstance(instance_id="b1", issue="crash", code="void f() {}")
        prompt = build_retry_prompt(bug, "diff", "error: implicit declaration of 'kfree'")
        assert "implicit declaration of 'kfree'" in prompt


class TestRetryFailedPatches:
    def test_retries_not_applied_patches(self) -> None:
        bugs = [
            BugInstance(
                instance_id="b1",
                issue="crash",
                code="[start of f.c]\nf.c\n1 int x;\n[end of f.c]",
            ),
        ]
        responses = [
            PatchResponse(instance_id="b1", raw_response="bad", diff="--- a/f.c\n+++ b/f.c"),
        ]
        results = [
            EvalResult(instance_id="b1", status=EvalStatus.NOT_APPLIED),
        ]

        client = FakeModelClient(default=SAMPLE_RESPONSE_TEXT)
        parser = Parser()

        updated = retry_failed_patches(
            bugs,
            responses,
            results,
            client,
            parser,
            compilation_errors={"b1": "error: undeclared variable"},
            max_retries=1,
        )

        assert len(updated) == 1
        # Should have retried and gotten new patched files
        assert updated[0].patched_files
        assert "net/smc/smc_sysctl.c" in updated[0].patched_files

    def test_skips_correct_patches(self) -> None:
        bugs = [
            BugInstance(instance_id="b1", issue="crash", code="int x;"),
        ]
        original_response = PatchResponse(
            instance_id="b1",
            raw_response="good",
            patched_files={"f.c": "fixed"},
        )
        responses = [original_response]
        results = [
            EvalResult(instance_id="b1", status=EvalStatus.CORRECT),
        ]

        client = FakeModelClient(default="should not be called")
        parser = Parser()

        updated = retry_failed_patches(bugs, responses, results, client, parser, max_retries=2)

        assert len(updated) == 1
        assert updated[0] is original_response
        assert len(client.calls) == 0

    def test_skips_incorrect_patches(self) -> None:
        bugs = [
            BugInstance(instance_id="b1", issue="crash", code="int x;"),
        ]
        responses = [
            PatchResponse(instance_id="b1", raw_response="wrong"),
        ]
        results = [
            EvalResult(instance_id="b1", status=EvalStatus.INCORRECT),
        ]

        client = FakeModelClient(default="nope")
        parser = Parser()

        updated = retry_failed_patches(bugs, responses, results, client, parser, max_retries=2)
        assert len(client.calls) == 0
        assert updated == responses

    def test_respects_max_retries(self) -> None:
        bugs = [
            BugInstance(instance_id="b1", issue="crash", code="int x;"),
        ]
        responses = [
            PatchResponse(instance_id="b1", raw_response="bad", diff="diff"),
        ]
        results = [
            EvalResult(instance_id="b1", status=EvalStatus.NOT_APPLIED),
        ]

        # Client returns unparseable response, so retries exhaust
        client = FakeModelClient(default="no valid xml here")
        parser = Parser()

        retry_failed_patches(
            bugs,
            responses,
            results,
            client,
            parser,
            max_retries=3,
        )
        assert len(client.calls) == 3

    def test_handles_empty_results(self) -> None:
        updated = retry_failed_patches(
            bugs=[],
            responses=[],
            results=[],
            client=FakeModelClient(),
            parser=Parser(),
        )
        assert updated == []
