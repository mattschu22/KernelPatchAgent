"""Tests for kernel_patcher.config — zero API tokens."""

import pytest
from pathlib import Path

from kernel_patcher.config import (
    AGENT_LEVELS,
    ALL_AGENTS,
    ModelBackend,
    PipelineConfig,
    slugify,
)


class TestSlugify:
    def test_simple(self):
        assert slugify("Orchestrator") == "orchestrator"

    def test_multi_word(self):
        assert slugify("Web Summary") == "web_summary"

    def test_code_summary(self):
        assert slugify("Code Summary") == "code_summary"


class TestModelBackend:
    def test_values(self):
        assert ModelBackend.GPT.value == "gpt-4o"
        assert ModelBackend.CLAUDE.value == "sonnet-4"
        assert ModelBackend.CUSTOM.value == "custom"


class TestAgentLevels:
    def test_orchestrator_at_top(self):
        assert "Orchestrator" in AGENT_LEVELS[0]

    def test_planner_coder_reviewer_level_1(self):
        assert "Planner" in AGENT_LEVELS[1]
        assert "Coder" in AGENT_LEVELS[1]
        assert "Reviewer" in AGENT_LEVELS[1]

    def test_support_agents_level_2(self):
        assert "Elixir" in AGENT_LEVELS[2]
        assert "Web Summary" in AGENT_LEVELS[2]
        assert "Code Summary" in AGENT_LEVELS[2]
        assert "General" in AGENT_LEVELS[2]

    def test_all_agents_covered(self):
        flat = [a for level in AGENT_LEVELS for a in level]
        for agent in ALL_AGENTS:
            assert agent in flat


class TestPipelineConfig:
    def test_defaults(self):
        config = PipelineConfig()
        assert config.model == ModelBackend.CUSTOM
        assert config.max_workers == 8
        assert config.server_port == 8008

    def test_server_base_url(self):
        config = PipelineConfig(server_host="myhost", server_port=9999)
        assert config.server_base_url == "http://myhost:9999"

    def test_paths_are_set(self):
        config = PipelineConfig()
        assert config.prompts_dir is not None
        assert config.descriptions_dir is not None
        assert config.data_dir is not None

    def test_load_prompt(self):
        config = PipelineConfig()
        # Should load from the actual prompts directory
        prompt = config.load_prompt("Orchestrator")
        assert "orchestrator" in prompt.lower() or "Orchestrator" in prompt

    def test_load_description(self):
        config = PipelineConfig()
        desc = config.load_description("Orchestrator")
        assert len(desc) > 0

    def test_load_all_prompts(self):
        config = PipelineConfig()
        prompts = config.load_all_prompts()
        assert len(prompts) == len(ALL_AGENTS)
        for agent in ALL_AGENTS:
            assert agent in prompts

    def test_load_all_descriptions(self):
        config = PipelineConfig()
        descs = config.load_all_descriptions()
        assert len(descs) == len(ALL_AGENTS)
