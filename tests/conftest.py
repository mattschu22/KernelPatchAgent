"""Shared fixtures and mock helpers for KernelPatcher tests."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock

import pytest

from kernel_patcher.config import ModelBackend, PipelineConfig
from kernel_patcher.models import BugInstance, EvalJob, PatchResponse


# ---------------------------------------------------------------------------
# Sample data constants
# ---------------------------------------------------------------------------

SAMPLE_INPUT_TEXT = """[start of net/smc/smc_sysctl.c]
net/smc/smc_sysctl.c
1 #include <linux/kernel.h>
2 #include <linux/sysctl.h>
3
4 static int smc_sysctl_init(void)
5 {
6     return 0;
7 }
[end of net/smc/smc_sysctl.c]"""

SAMPLE_RESPONSE_TEXT = """<file path="net/smc/smc_sysctl.c">
#include <linux/kernel.h>
#include <linux/sysctl.h>

static int smc_sysctl_init(void)
{
    int ret = 0;
    return ret;
}
</file>"""

SAMPLE_CRASH_REPORT = """
BUG: KASAN: slab-use-after-free in smc_sysctl_init+0x42/0x80
Read of size 8 at addr ffff88800a1234 by task syz-executor/1234
"""

SAMPLE_CODE = """[start of net/smc/smc_sysctl.c]
net/smc/smc_sysctl.c
1 #include <linux/kernel.h>
2 static int smc_sysctl_init(void) { return 0; }
[end of net/smc/smc_sysctl.c]"""

SAMPLE_MULTI_FILE_INPUT = """[start of fs/ext4/file.c]
fs/ext4/file.c
1 #include <linux/fs.h>
2 void ext4_func(void) {}
[end of fs/ext4/file.c]
[start of fs/ext4/namei.c]
fs/ext4/namei.c
1 #include <linux/fs.h>
2 void ext4_namei_func(void) {}
[end of fs/ext4/namei.c]"""

SAMPLE_MULTI_FILE_RESPONSE = """<file path="fs/ext4/file.c">
#include <linux/fs.h>
void ext4_func(void) { /* patched */ }
</file>
<file path="fs/ext4/namei.c">
#include <linux/fs.h>
void ext4_namei_func(void) { /* patched */ }
</file>"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that's cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_bugs() -> List[BugInstance]:
    """A small set of sample bug instances for testing."""
    return [
        BugInstance(
            instance_id="bug_001",
            issue=SAMPLE_CRASH_REPORT,
            code=SAMPLE_CODE,
            files=["net/smc/smc_sysctl.c"],
            category="Networking",
        ),
        BugInstance(
            instance_id="bug_002",
            issue="BUG: null pointer in ext4_func",
            code=SAMPLE_MULTI_FILE_INPUT,
            files=["fs/ext4/file.c", "fs/ext4/namei.c"],
            category="File System",
        ),
    ]


@pytest.fixture
def sample_responses() -> List[PatchResponse]:
    """Sample patch responses matching sample_bugs."""
    return [
        PatchResponse(
            instance_id="bug_001",
            raw_response=SAMPLE_RESPONSE_TEXT,
            patched_files={"net/smc/smc_sysctl.c": "#include <linux/kernel.h>\nstatic int smc_sysctl_init(void) { int ret = 0; return ret; }\n"},
        ),
        PatchResponse(
            instance_id="bug_002",
            raw_response=SAMPLE_MULTI_FILE_RESPONSE,
            patched_files={
                "fs/ext4/file.c": '#include <linux/fs.h>\nvoid ext4_func(void) { /* patched */ }\n',
                "fs/ext4/namei.c": '#include <linux/fs.h>\nvoid ext4_namei_func(void) { /* patched */ }\n',
            },
        ),
    ]


@pytest.fixture
def config(tmp_dir) -> PipelineConfig:
    """A PipelineConfig pointing at temp directories."""
    return PipelineConfig(
        model=ModelBackend.CUSTOM,
        max_workers=2,
        data_dir=tmp_dir,
    )


@pytest.fixture
def data_json(tmp_dir, sample_bugs) -> Path:
    """Write sample bug data to a JSON file and return the path."""
    path = tmp_dir / "data.json"
    data = [
        {"instance_id": b.instance_id, "issue": b.issue, "code": b.code}
        for b in sample_bugs
    ]
    path.write_text(json.dumps(data))
    return path


class FakeModelClient:
    """A mock model client that returns canned responses without using API tokens."""

    def __init__(self, responses: Dict[str, str] | None = None, default: str = ""):
        self._responses = responses or {}
        self._default = default
        self.calls: List[tuple] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        # Try to match on a substring of the user prompt
        for key, val in self._responses.items():
            if key in user_prompt:
                return val
        return self._default


@pytest.fixture
def fake_client() -> FakeModelClient:
    """A FakeModelClient with canned responses for the sample bugs."""
    return FakeModelClient(
        responses={
            "smc_sysctl": SAMPLE_RESPONSE_TEXT,
            "ext4": SAMPLE_MULTI_FILE_RESPONSE,
        },
        default='<file path="unknown.c">\n// no fix\n</file>',
    )
