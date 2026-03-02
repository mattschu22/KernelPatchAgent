"""Tests for kernel_patcher.inference — all API calls mocked, zero tokens used."""

import sys

import pytest
from unittest.mock import patch, MagicMock

from kernel_patcher.config import ModelBackend, PipelineConfig
from kernel_patcher.inference import (
    OpenAIClient,
    AnthropicClient,
    CustomAgentClient,
    build_user_prompt,
    create_client,
    run_inference,
    run_inference_single,
)
from kernel_patcher.models import BugInstance, PatchResponse
from kernel_patcher.parser import Parser
from tests.conftest import FakeModelClient, SAMPLE_RESPONSE_TEXT


class TestBuildUserPrompt:
    def test_contains_issue_and_code(self):
        bug = BugInstance(instance_id="x", issue="crash report", code="int x;")
        prompt = build_user_prompt(bug)
        assert "crash report" in prompt
        assert "int x;" in prompt

    def test_format(self):
        bug = BugInstance(instance_id="x", issue="BUG", code="code")
        prompt = build_user_prompt(bug)
        assert prompt.startswith("Crash report:")
        assert "Files:" in prompt


class TestCreateClient:
    def test_custom_backend(self):
        config = PipelineConfig(model=ModelBackend.CUSTOM)
        client = create_client(config)
        assert isinstance(client, CustomAgentClient)

    @patch("openai.OpenAI")
    def test_gpt_backend(self, mock_openai):
        config = PipelineConfig(model=ModelBackend.GPT)
        client = create_client(config)
        assert isinstance(client, OpenAIClient)

    def test_claude_backend(self):
        anthropic_mock = MagicMock()
        with patch.dict("sys.modules", {"anthropic": anthropic_mock}):
            config = PipelineConfig(model=ModelBackend.CLAUDE)
            client = create_client(config)
            assert isinstance(client, AnthropicClient)


class TestRunInferenceSingle:
    def test_successful_inference(self, sample_bugs):
        client = FakeModelClient(
            responses={"smc_sysctl": SAMPLE_RESPONSE_TEXT},
        )
        parser = Parser()
        result = run_inference_single(client, sample_bugs[0], parser)

        assert result.instance_id == "bug_001"
        assert result.raw_response == SAMPLE_RESPONSE_TEXT
        assert "net/smc/smc_sysctl.c" in result.patched_files
        assert len(client.calls) == 1

    def test_failed_inference_returns_empty(self, sample_bugs):
        class FailClient:
            def generate(self, sys, user):
                raise RuntimeError("API error")

        parser = Parser()
        result = run_inference_single(FailClient(), sample_bugs[0], parser)
        assert result.instance_id == "bug_001"
        assert result.raw_response == ""
        assert result.patched_files == {}


class TestRunInference:
    def test_processes_all_bugs(self, sample_bugs, fake_client, config):
        results = run_inference(sample_bugs, config, client=fake_client)
        assert len(results) == 2
        assert results[0].instance_id == "bug_001"
        assert results[1].instance_id == "bug_002"
        assert len(fake_client.calls) == 2

    def test_parallel_execution(self, sample_bugs, fake_client, config):
        config.max_workers = 4
        results = run_inference(sample_bugs, config, client=fake_client)
        assert len(results) == 2

    def test_handles_partial_failure(self, sample_bugs, config):
        call_count = 0

        class FlakeyClient:
            def generate(self, sys, user):
                nonlocal call_count
                call_count += 1
                if "smc_sysctl" in user:
                    raise RuntimeError("timeout")
                return SAMPLE_RESPONSE_TEXT

        results = run_inference(sample_bugs, config, client=FlakeyClient())
        assert len(results) == 2
        # One should have failed gracefully
        empty = [r for r in results if r.raw_response == ""]
        assert len(empty) >= 1


class TestOpenAIClient:
    @patch("openai.OpenAI")
    def test_generate(self, MockOpenAI):
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_choice = MagicMock()
        mock_choice.message.content = "patched code"
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[mock_choice]
        )

        client = OpenAIClient()
        result = client.generate("system", "user")
        assert result == "patched code"
        mock_client.chat.completions.create.assert_called_once()


class TestAnthropicClient:
    def test_generate(self):
        mock_inner = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "patched code"
        mock_inner.messages.create.return_value = MagicMock(content=[mock_block])

        anthropic_mod = MagicMock()
        anthropic_mod.Anthropic.return_value = mock_inner

        with patch.dict("sys.modules", {"anthropic": anthropic_mod}):
            client = AnthropicClient()
            result = client.generate("system", "user")
            assert result == "patched code"
            mock_inner.messages.create.assert_called_once()
