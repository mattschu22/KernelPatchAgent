"""Data models for the KernelPatcher pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass
class BugInstance:
    """A single kernel bug from the benchmark dataset."""

    instance_id: str
    issue: str
    code: str
    files: list[str] = field(default_factory=list)
    category: str = ""


@dataclass
class PatchResponse:
    """Response from a model containing patched file contents."""

    instance_id: str
    raw_response: str
    patched_files: dict[str, str] = field(default_factory=dict)
    diff: str = ""


class EvalStatus(StrEnum):
    CORRECT = "c"
    INCORRECT = "i"
    NOT_APPLIED = "na"


@dataclass
class EvalResult:
    """Result of evaluating a patch via kSuite."""

    instance_id: str
    status: EvalStatus
    job_id: str = ""


@dataclass
class EvalJob:
    """A submitted kSuite evaluation job."""

    name: str
    instance_id: str
    job_id: str
    patch: str
    commit: str
    reproducer: str
    cfg: str
    syz_check: str
    status: str = "pending"


@dataclass
class PipelineResult:
    """Full result of running the pipeline on a set of bugs."""

    responses: list[PatchResponse] = field(default_factory=list)
    results: list[EvalResult] = field(default_factory=list)

    @property
    def correct(self) -> list[EvalResult]:
        return [r for r in self.results if r.status == EvalStatus.CORRECT]

    @property
    def incorrect(self) -> list[EvalResult]:
        return [r for r in self.results if r.status == EvalStatus.INCORRECT]

    @property
    def not_applied(self) -> list[EvalResult]:
        return [r for r in self.results if r.status == EvalStatus.NOT_APPLIED]
