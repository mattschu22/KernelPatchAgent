"""Configuration for the KernelPatcher pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List


class ModelBackend(str, Enum):
    GPT = "gpt-4.1"
    CLAUDE = "sonnet-4"
    CUSTOM = "custom"


# Agent hierarchy: each level can call agents in the next level
AGENT_LEVELS: List[List[str]] = [
    ["Orchestrator"],
    ["Planner", "Coder", "Reviewer"],
    ["Elixir", "Web Summary", "Code Summary", "General"],
    [],
]

ALL_AGENTS = [
    "Orchestrator",
    "Planner",
    "Coder",
    "Reviewer",
    "Elixir",
    "Web Summary",
    "Code Summary",
    "General",
]


def slugify(name: str) -> str:
    """Convert agent name to URL slug: 'Web Summary' -> 'web_summary'."""
    return "_".join(name.lower().split())


SYSTEM_PROMPT = """
You are a helpful assistant that follows directions exactly. You will be tasked with fixing various bugs in the Linux kernel. You will receive various C files.
Your task is to analyze the relevant logs, understand the issue, and create an appropriate patch. You will receive tasks in the following format:

Crash report:
<issue>
{CRASH_TEXT}
</issue>

Files:
[file path="{file_path}"]
{file_contents}
[/file]

When you respond, only provide the updated files in their entirety. Do not provide any reasoning. Respond in the following format:
<file path="{file_path}">
{entire updated file contents}
</file>
""".strip()


@dataclass
class PipelineConfig:
    """Configuration for the kernel patching pipeline."""

    model: ModelBackend = ModelBackend.CUSTOM
    max_workers: int = 8
    server_host: str = "localhost"
    server_port: int = 8008
    agent_timeout: int = 60
    max_review_cycles: int = 3

    # Paths
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    prompts_dir: Path = field(default=None)
    descriptions_dir: Path = field(default=None)
    data_dir: Path = field(default=None)

    # kSuite
    ksuite_url: str = "http://localhost:8000"
    git_url: str = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"

    def __post_init__(self):
        if self.prompts_dir is None:
            self.prompts_dir = self.project_root / "prompts"
        if self.descriptions_dir is None:
            self.descriptions_dir = self.project_root / "descriptions"
        if self.data_dir is None:
            self.data_dir = self.project_root / "data"

    @property
    def server_base_url(self) -> str:
        return f"http://{self.server_host}:{self.server_port}"

    def load_prompt(self, agent_name: str) -> str:
        path = self.prompts_dir / f"{slugify(agent_name)}.txt"
        return path.read_text()

    def load_description(self, agent_name: str) -> str:
        path = self.descriptions_dir / f"{slugify(agent_name)}.txt"
        return path.read_text()

    def load_all_prompts(self) -> Dict[str, str]:
        return {name: self.load_prompt(name) for name in ALL_AGENTS}

    def load_all_descriptions(self) -> Dict[str, str]:
        return {name: self.load_description(name) for name in ALL_AGENTS}
