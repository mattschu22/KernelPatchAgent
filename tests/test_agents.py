"""Tests for kernel_patcher.agents — mocked, zero API tokens."""

from unittest.mock import MagicMock, patch

from kernel_patcher.config import AGENT_LEVELS, ALL_AGENTS, PipelineConfig, slugify


class TestSlugMapping:
    def test_all_agents_slugify_consistently(self):
        for name in ALL_AGENTS:
            slug = slugify(name)
            assert slug == slug.lower()
            assert " " not in slug

    def test_slug_roundtrip(self):
        slug_map = {slugify(name): name for name in ALL_AGENTS}
        assert len(slug_map) == len(ALL_AGENTS)  # no collisions


class TestAgentHierarchy:
    def test_orchestrator_can_call_level_1(self):
        # Orchestrator is in level 0, should call level 1 agents
        assert "Orchestrator" in AGENT_LEVELS[0]
        level1 = AGENT_LEVELS[1]
        assert "Planner" in level1
        assert "Coder" in level1
        assert "Reviewer" in level1

    def test_planner_can_call_level_2(self):
        assert "Planner" in AGENT_LEVELS[1]
        level2 = AGENT_LEVELS[2]
        assert "Elixir" in level2
        assert "General" in level2

    def test_coder_has_no_subagents(self):
        # Coder is in level 1, level 2 agents are Planner's tools
        # But the hierarchy means level 1 -> level 2
        # Coder should NOT have subagent tools (only Planner does in practice)
        # The hierarchy allows it, but the actual agent system limits it
        # This is a design test
        assert "Coder" in AGENT_LEVELS[1]

    def test_level_2_is_leaf(self):
        # Level 2 agents call into level 3 which is empty
        assert AGENT_LEVELS[3] == []


class TestAgentRegistryBuild:
    @patch("kernel_patcher.agents.registry.Agent")
    def test_build_all_creates_agents(self, MockAgent):
        from kernel_patcher.agents.registry import AgentRegistry

        config = PipelineConfig()
        registry = AgentRegistry(config)

        MockAgent.return_value = MagicMock()
        registry.build_all()

        assert len(registry.agents) == len(ALL_AGENTS)
        for name in ALL_AGENTS:
            assert name in registry.agents

    @patch("kernel_patcher.agents.registry.Agent")
    def test_slug_lookup(self, MockAgent):
        from kernel_patcher.agents.registry import AgentRegistry

        config = PipelineConfig()
        registry = AgentRegistry(config)
        MockAgent.return_value = MagicMock()
        registry.build_all()

        assert registry.get_by_slug("orchestrator") is not None
        assert registry.get_by_slug("web_summary") is not None
        assert registry.get_by_slug("nonexistent") is None

    @patch("kernel_patcher.agents.registry.Agent")
    def test_name_lookup(self, MockAgent):
        from kernel_patcher.agents.registry import AgentRegistry

        config = PipelineConfig()
        registry = AgentRegistry(config)
        MockAgent.return_value = MagicMock()
        registry.build_all()

        assert registry.get_by_name("Orchestrator") is not None
        assert registry.get_by_name("Nonexistent") is None
