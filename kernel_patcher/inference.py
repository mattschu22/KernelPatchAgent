"""Inference pipeline: query models to generate kernel patches."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol
from urllib import parse, request

from kernel_patcher.config import SYSTEM_PROMPT, ModelBackend, PipelineConfig
from kernel_patcher.models import BugInstance, PatchResponse
from kernel_patcher.parser import Parser

logger = logging.getLogger(__name__)


class ModelClient(Protocol):
    """Protocol for model inference backends."""

    def generate(self, system_prompt: str, user_prompt: str) -> str: ...


class OpenAIClient:
    """Inference via OpenAI API (gpt-4.1)."""

    def __init__(self, model: str = "gpt-4.1"):
        from openai import OpenAI

        self._client = OpenAI()
        self._model = model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        completion = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = completion.choices[0].message.content
        return content or ""


class AnthropicClient:
    """Inference via Anthropic API (Claude)."""

    def __init__(self, model: str = "claude-sonnet-4-20250514", max_tokens: int = 10000):
        from anthropic import Anthropic

        self._client = Anthropic()
        self._model = model
        self._max_tokens = max_tokens

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        completion = self._client.messages.create(
            max_tokens=self._max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            model=self._model,
        )
        text: str = completion.content[0].text
        return text


class CustomAgentClient:
    """Inference via the local multi-agent server."""

    def __init__(self, base_url: str = "http://localhost:8008"):
        self._base_url = base_url

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        combined = (
            f"<SYS PROMPT>{system_prompt}</SYS PROMPT>\n<USER PROMPT>{user_prompt}</USER PROMPT>"
        )
        params = parse.urlencode({"input": combined})
        url = f"{self._base_url}/agents/orchestrator?{params}"
        with request.urlopen(url) as resp:
            result: str = json.loads(resp.read().decode("utf-8"))["output"]
            return result


def build_user_prompt(bug: BugInstance) -> str:
    """Build the user prompt for a bug instance."""
    return f"Crash report:\n{bug.issue}\n\nFiles:\n{bug.code}"


def create_client(config: PipelineConfig) -> ModelClient:
    """Create the appropriate model client based on config."""
    if config.model == ModelBackend.GPT:
        return OpenAIClient()
    elif config.model == ModelBackend.CLAUDE:
        return AnthropicClient()
    elif config.model == ModelBackend.CUSTOM:
        return CustomAgentClient(config.server_base_url)
    else:
        raise ValueError(f"Unknown model backend: {config.model}")


def run_inference_single(
    client: ModelClient,
    bug: BugInstance,
    parser: Parser,
) -> PatchResponse:
    """Run inference on a single bug instance."""
    user_prompt = build_user_prompt(bug)
    try:
        raw = client.generate(SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        logger.error("Inference failed for %s: %s", bug.instance_id, e)
        return PatchResponse(instance_id=bug.instance_id, raw_response="")

    patched = parser.parse_response(raw)
    return PatchResponse(
        instance_id=bug.instance_id,
        raw_response=raw,
        patched_files=patched,
    )


def run_inference(
    bugs: list[BugInstance],
    config: PipelineConfig,
    client: ModelClient | None = None,
) -> list[PatchResponse]:
    """Run parallel inference across all bug instances.

    Args:
        bugs: List of bug instances to patch.
        config: Pipeline configuration.
        client: Optional pre-built model client (created from config if None).

    Returns:
        List of PatchResponse objects, one per bug.
    """
    if client is None:
        client = create_client(config)
    parser = Parser()

    responses: dict[str, PatchResponse] = {}

    def _infer(bug: BugInstance) -> PatchResponse:
        return run_inference_single(client, bug, parser)

    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        futures = {executor.submit(_infer, bug): bug for bug in bugs}
        for future in as_completed(futures):
            bug = futures[future]
            try:
                resp = future.result()
                responses[bug.instance_id] = resp
                logger.info("Completed inference for %s", bug.instance_id)
            except Exception as e:
                logger.error("Inference failed for %s: %s", bug.instance_id, e)
                responses[bug.instance_id] = PatchResponse(
                    instance_id=bug.instance_id, raw_response=""
                )

    # Return in original order
    return [responses[bug.instance_id] for bug in bugs]
