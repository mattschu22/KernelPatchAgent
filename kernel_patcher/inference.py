"""Inference pipeline: query models to generate kernel patches."""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol
from urllib import parse, request
from urllib.error import HTTPError

from kernel_patcher.config import SYSTEM_PROMPT, ModelBackend, PipelineConfig
from kernel_patcher.models import BugInstance, PatchResponse
from kernel_patcher.parser import Parser

logger = logging.getLogger(__name__)


def _is_rate_limit(exc: BaseException) -> bool:
    """Detect rate-limit errors across SDKs without hard-importing them."""
    if isinstance(exc, HTTPError) and exc.code == 429:
        return True
    if getattr(exc, "status_code", None) == 429:
        return True
    if type(exc).__name__ == "RateLimitError":
        return True
    return False


def _retry_after_seconds(exc: BaseException) -> float | None:
    """Pull a Retry-After hint off an exception if the SDK exposes one."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is None:
        headers = getattr(exc, "headers", None)
    if headers is not None:
        try:
            value = headers.get("Retry-After") or headers.get("retry-after")
        except AttributeError:
            value = None
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    direct = getattr(exc, "retry_after", None)
    if direct is not None:
        try:
            return float(direct)
        except (TypeError, ValueError):
            return None
    return None


def _compute_backoff(
    attempt: int,
    initial: float,
    cap: float,
    retry_after: float | None,
) -> float:
    """Exponential backoff with jitter, overridden by Retry-After when present."""
    if retry_after is not None and retry_after > 0:
        return min(retry_after, cap)
    base = min(initial * (2 ** (attempt - 1)), cap)
    return base * (0.5 + random.random() / 2)


def generate_with_retry(
    client: ModelClient,
    system_prompt: str,
    user_prompt: str,
    max_retries: int,
    initial_backoff: float,
    max_backoff: float,
    instance_id: str = "",
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Call ``client.generate`` with retry + backoff on transient errors.

    Re-raises the last exception if all attempts fail.
    """
    last_exc: BaseException | None = None
    total_attempts = max_retries + 1
    for attempt in range(1, total_attempts + 1):
        try:
            return client.generate(system_prompt, user_prompt)
        except Exception as exc:
            last_exc = exc
            if attempt >= total_attempts:
                break
            rate_limited = _is_rate_limit(exc)
            retry_after = _retry_after_seconds(exc) if rate_limited else None
            delay = _compute_backoff(attempt, initial_backoff, max_backoff, retry_after)
            logger.warning(
                "Inference attempt %d/%d for %s failed (%s%s); sleeping %.2fs",
                attempt,
                total_attempts,
                instance_id or "<unknown>",
                "rate limited: " if rate_limited else "",
                exc,
                delay,
            )
            sleep(delay)
    assert last_exc is not None
    raise last_exc


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
    max_retries: int = 0,
    initial_backoff: float = 1.0,
    max_backoff: float = 60.0,
) -> PatchResponse:
    """Run inference on a single bug instance.

    Transient errors (including rate limits) are retried up to ``max_retries``
    times with exponential backoff. After exhausting retries, an empty
    PatchResponse is returned so the rest of the pipeline can proceed.
    """
    user_prompt = build_user_prompt(bug)
    try:
        raw = generate_with_retry(
            client,
            SYSTEM_PROMPT,
            user_prompt,
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            max_backoff=max_backoff,
            instance_id=bug.instance_id,
        )
    except Exception as e:
        logger.error(
            "Inference failed for %s after %d retries: %s",
            bug.instance_id,
            max_retries,
            e,
        )
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
        return run_inference_single(
            client,
            bug,
            parser,
            max_retries=config.max_inference_retries,
            initial_backoff=config.inference_initial_backoff,
            max_backoff=config.inference_max_backoff,
        )

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
