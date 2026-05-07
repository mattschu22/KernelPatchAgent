"""Tests for kernel_patcher.inference — all API calls mocked, zero tokens used."""

import pytest
from unittest.mock import MagicMock, patch

from kernel_patcher.config import ModelBackend, PipelineConfig
from kernel_patcher.inference import (
    AnthropicClient,
    CustomAgentClient,
    OpenAIClient,
    build_user_prompt,
    create_client,
    generate_with_retry,
    run_inference,
    run_inference_single,
)
from kernel_patcher.models import BugInstance
from kernel_patcher.parser import Parser
from tests.conftest import SAMPLE_RESPONSE_TEXT, FakeModelClient


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


class TestGenerateWithRetry:
    def test_returns_first_success(self):
        client = FakeModelClient(default="ok")
        sleeps: list[float] = []
        result = generate_with_retry(
            client, "sys", "user",
            max_retries=3, initial_backoff=1.0, max_backoff=10.0,
            sleep=sleeps.append,
        )
        assert result == "ok"
        assert sleeps == []
        assert len(client.calls) == 1

    def test_retries_then_succeeds(self):
        attempts = {"n": 0}

        class FlakeyClient:
            def generate(self, sys, user):
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise RuntimeError("transient")
                return "ok"

        sleeps: list[float] = []
        result = generate_with_retry(
            FlakeyClient(), "sys", "user",
            max_retries=5, initial_backoff=1.0, max_backoff=10.0,
            sleep=sleeps.append,
        )
        assert result == "ok"
        assert attempts["n"] == 3
        assert len(sleeps) == 2

    def test_exhausts_retries_and_raises(self):
        class AlwaysFails:
            def generate(self, sys, user):
                raise RuntimeError("boom")

        sleeps: list[float] = []
        with pytest.raises(RuntimeError, match="boom"):
            generate_with_retry(
                AlwaysFails(), "sys", "user",
                max_retries=2, initial_backoff=0.1, max_backoff=1.0,
                sleep=sleeps.append,
            )
        # max_retries=2 means 3 total attempts, so 2 sleeps between them
        assert len(sleeps) == 2

    def test_zero_retries_means_one_attempt(self):
        class AlwaysFails:
            def generate(self, sys, user):
                raise RuntimeError("boom")

        sleeps: list[float] = []
        with pytest.raises(RuntimeError):
            generate_with_retry(
                AlwaysFails(), "sys", "user",
                max_retries=0, initial_backoff=0.1, max_backoff=1.0,
                sleep=sleeps.append,
            )
        assert sleeps == []

    def test_rate_limit_honors_retry_after(self):
        class RateLimitError(Exception):
            def __init__(self):
                super().__init__("429 Too Many Requests")
                self.status_code = 429
                self.headers = {"Retry-After": "7"}

        attempts = {"n": 0}

        class RateLimitedClient:
            def generate(self, sys, user):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RateLimitError()
                return "ok"

        sleeps: list[float] = []
        result = generate_with_retry(
            RateLimitedClient(), "sys", "user",
            max_retries=3, initial_backoff=1.0, max_backoff=60.0,
            sleep=sleeps.append,
        )
        assert result == "ok"
        assert sleeps == [7.0]

    def test_rate_limit_capped_by_max_backoff(self):
        class RateLimitError(Exception):
            def __init__(self):
                super().__init__("429")
                self.status_code = 429
                self.retry_after = 999

        attempts = {"n": 0}

        class Client:
            def generate(self, sys, user):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RateLimitError()
                return "ok"

        sleeps: list[float] = []
        generate_with_retry(
            Client(), "sys", "user",
            max_retries=2, initial_backoff=1.0, max_backoff=5.0,
            sleep=sleeps.append,
        )
        assert sleeps == [5.0]


class TestRunInferenceSingleRetries:
    def test_recovers_from_transient_error(self, sample_bugs):
        attempts = {"n": 0}

        class FlakeyClient:
            def generate(self, sys, user):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RuntimeError("transient")
                return SAMPLE_RESPONSE_TEXT

        with patch("kernel_patcher.inference.time.sleep"):
            result = run_inference_single(
                FlakeyClient(), sample_bugs[0], Parser(),
                max_retries=2, initial_backoff=0.01, max_backoff=0.1,
            )
        assert result.raw_response == SAMPLE_RESPONSE_TEXT
        assert attempts["n"] == 2

    def test_returns_empty_after_exhausting_retries(self, sample_bugs):
        class AlwaysFails:
            def generate(self, sys, user):
                raise RuntimeError("boom")

        with patch("kernel_patcher.inference.time.sleep"):
            result = run_inference_single(
                AlwaysFails(), sample_bugs[0], Parser(),
                max_retries=2, initial_backoff=0.01, max_backoff=0.1,
            )
        assert result.raw_response == ""
        assert result.patched_files == {}


class TestRunInferenceConfigRetries:
    def test_uses_config_retry_settings(self, sample_bugs, config):
        attempts: dict[str, int] = {}

        class FlakeyClient:
            def generate(self, sys, user):
                key = "smc" if "smc_sysctl" in user else "ext4"
                attempts[key] = attempts.get(key, 0) + 1
                if attempts[key] == 1:
                    raise RuntimeError("transient")
                return SAMPLE_RESPONSE_TEXT

        config.max_inference_retries = 2
        config.inference_initial_backoff = 0.01
        config.inference_max_backoff = 0.05
        with patch("kernel_patcher.inference.time.sleep"):
            results = run_inference(sample_bugs, config, client=FlakeyClient())
        assert all(r.raw_response == SAMPLE_RESPONSE_TEXT for r in results)
        assert attempts == {"smc": 2, "ext4": 2}


class TestOpenAIClient:
    @patch("openai.OpenAI")
    def test_generate(self, MockOpenAI):
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_choice = MagicMock()
        mock_choice.message.content = "patched code"
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

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
