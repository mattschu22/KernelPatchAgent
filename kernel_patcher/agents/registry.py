"""Agent registry: build and manage the multi-agent hierarchy."""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional

import httpx
from agents import Agent, Runner
from agents.tool import function_tool

from kernel_patcher.agents.tools import build_bootlin_fetch_tool, build_kernel_org_search_tool
from kernel_patcher.config import AGENT_LEVELS, ALL_AGENTS, PipelineConfig, slugify

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Builds, stores, and looks up agents by name or slug."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.agents: Dict[str, Agent] = {}
        self.slug_to_name: Dict[str, str] = {}
        self._descriptions: Dict[str, str] = {}

    async def call_subagent_http(self, agent_name: str, agent_input: str) -> str:
        """Call a subagent via HTTP GET request."""
        endpoint = f"{self.config.server_base_url}/agents/{slugify(agent_name)}"
        params = {"input": agent_input}

        async with httpx.AsyncClient(timeout=self.config.agent_timeout) as client:
            try:
                response = await client.get(endpoint, params=params)
                response.raise_for_status()
            except httpx.HTTPError as http_err:
                raise RuntimeError(
                    f"{agent_name} HTTP request failed: {http_err}"
                ) from http_err

        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                return response.json().get("output", response.text)
            except json.JSONDecodeError:
                return response.text
        return response.text

    def _build_subagent_tool(self, agent_name: str):
        """Create a function_tool that calls a subagent via HTTP."""
        description = self._descriptions[agent_name]

        @function_tool(
            name_override=slugify(agent_name),
            description_override=description,
        )
        async def call_subagent(input: str, target_agent: str = agent_name) -> str:
            logger.info("Calling subagent %s", target_agent)
            return await self.call_subagent_http(target_agent, input)

        return call_subagent

    def _get_additional_tools(self, agent_name: str) -> list:
        """Get extra tools for specific agents."""
        tools = []
        if agent_name == "Elixir":
            tools.append(build_bootlin_fetch_tool())
        elif agent_name == "Web Summary":
            tools.append(build_kernel_org_search_tool())
        return tools

    def _get_subagent_tools(self, agent_name: str) -> list:
        """Get subagent call tools based on the hierarchy."""
        tools = []
        for i, level in enumerate(AGENT_LEVELS[:-1]):
            if agent_name in level:
                for sub_name in AGENT_LEVELS[i + 1]:
                    tools.append(self._build_subagent_tool(sub_name))
                break
        return tools

    def build_all(self) -> None:
        """Build all agents from prompts and descriptions on disk."""
        self._descriptions = self.config.load_all_descriptions()

        for name in ALL_AGENTS:
            instructions = self.config.load_prompt(name)
            tools = self._get_subagent_tools(name) + self._get_additional_tools(name)
            self.agents[name] = Agent(name=name, instructions=instructions, tools=tools)
            self.slug_to_name[slugify(name)] = name

    def get_by_slug(self, slug: str) -> Optional[Agent]:
        """Look up an agent by its URL slug."""
        name = self.slug_to_name.get(slug)
        if name is None:
            return None
        return self.agents.get(name)

    def get_by_name(self, name: str) -> Optional[Agent]:
        """Look up an agent by its display name."""
        return self.agents.get(name)

    async def run_agent(self, agent_name: str, input_text: str) -> str:
        """Run an agent and return its final output as a string."""
        agent = self.agents.get(agent_name)
        if agent is None:
            raise ValueError(f"Unknown agent: {agent_name}")

        result = await Runner.run(agent, input_text)
        output = result.final_output
        if output is None:
            return ""
        if isinstance(output, str):
            return output
        if isinstance(output, (dict, list)):
            return json.dumps(output)
        return str(output)
