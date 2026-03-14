"""Compilation feedback loop: retry failed patches with error context."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kernel_patcher.models import BugInstance, EvalResult, EvalStatus, PatchResponse

if TYPE_CHECKING:
    from kernel_patcher.inference import ModelClient
    from kernel_patcher.parser import Parser

logger = logging.getLogger(__name__)

RETRY_PROMPT = (
    "Your previous patch for this kernel bug failed to compile.\n\n"
    "Original crash report:\n{issue}\n\n"
    "Original source files:\n{code}\n\n"
    "Your previous patch (unified diff):\n"
    "```\n{diff}\n```\n\n"
    "Compilation error:\n{error}\n\n"
    "Analyze the compilation error, understand what went wrong in your previous "
    "attempt, and produce a corrected patch. Only provide the updated files in "
    "their entirety. Do not provide any reasoning. Respond in the following format:\n"
    '<file path="{{file_path}}">\n'
    "{{entire updated file contents}}\n"
    "</file>"
)

RETRY_SYSTEM_PROMPT = (
    "You are a kernel patch specialist. A previous attempt to fix a Linux kernel "
    "bug produced a patch that failed to compile. Your job is to analyze the "
    "compilation error and produce a corrected version of the patch."
)


def build_retry_prompt(
    bug: BugInstance,
    previous_diff: str,
    compilation_error: str,
) -> str:
    """Build a feedback prompt that includes the failed attempt and error."""
    return RETRY_PROMPT.format(
        issue=bug.issue,
        code=bug.code,
        diff=previous_diff,
        error=compilation_error,
    )


def retry_failed_patches(
    bugs: list[BugInstance],
    responses: list[PatchResponse],
    results: list[EvalResult],
    client: ModelClient,
    parser: Parser,
    compilation_errors: dict[str, str] | None = None,
    max_retries: int = 2,
) -> list[PatchResponse]:
    """Retry inference for patches that failed compilation.

    Args:
        bugs: Original bug instances.
        responses: Original patch responses (parallel to bugs).
        results: Evaluation results from the first attempt.
        client: Model client for re-inference.
        parser: Parser for extracting patched files from model output.
        compilation_errors: Map of instance_id -> compiler error text.
            If not provided, a generic message is used.
        max_retries: Maximum number of retry attempts per bug.

    Returns:
        Updated list of PatchResponse objects with retried patches
        replacing the originals where successful.
    """
    compilation_errors = compilation_errors or {}

    # Index bugs and responses by instance_id
    bug_map = {b.instance_id: b for b in bugs}
    resp_map = {r.instance_id: r for r in responses}

    # Find which bugs had compilation failures (NOT_APPLIED)
    failed_ids = [
        r.instance_id
        for r in results
        if r.status == EvalStatus.NOT_APPLIED and r.instance_id in resp_map
    ]

    if not failed_ids:
        logger.info("No compilation failures to retry")
        return responses

    logger.info("Retrying %d failed patches (max %d attempts each)", len(failed_ids), max_retries)

    for instance_id in failed_ids:
        bug = bug_map[instance_id]
        current_resp = resp_map[instance_id]

        for attempt in range(1, max_retries + 1):
            previous_diff = current_resp.diff or "(no diff generated)"
            error_text = compilation_errors.get(
                instance_id,
                "Patch could not be applied or failed to compile.",
            )

            retry_prompt = build_retry_prompt(bug, previous_diff, error_text)

            logger.info(
                "Retry %d/%d for %s",
                attempt,
                max_retries,
                instance_id,
            )

            try:
                raw = client.generate(RETRY_SYSTEM_PROMPT, retry_prompt)
            except Exception as e:
                logger.error("Retry inference failed for %s: %s", instance_id, e)
                break

            patched = parser.parse_response(raw)
            if patched:
                current_resp = PatchResponse(
                    instance_id=instance_id,
                    raw_response=raw,
                    patched_files=patched,
                )
                resp_map[instance_id] = current_resp
                logger.info(
                    "Retry %d produced %d patched files for %s", attempt, len(patched), instance_id
                )
                break
            else:
                logger.warning("Retry %d produced no patched files for %s", attempt, instance_id)

    # Rebuild response list in original order
    return [resp_map.get(b.instance_id, r) for b, r in zip(bugs, responses, strict=True)]
