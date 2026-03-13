"""FastAPI server for the multi-agent kernel patching system."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from agents import Runner
from fastapi import FastAPI, HTTPException

from kernel_patcher.agents.registry import AgentRegistry
from kernel_patcher.config import PipelineConfig

# Module-level registry, set during lifespan
_registry: AgentRegistry | None = None


def create_app(config: PipelineConfig | None = None) -> FastAPI:
    """Create the FastAPI application with agent lifespan management."""
    if config is None:
        config = PipelineConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        global _registry
        _registry = AgentRegistry(config)
        _registry.build_all()
        yield
        _registry = None

    app = FastAPI(lifespan=lifespan)

    @app.get("/agents/{agent_slug}")
    async def invoke_agent(agent_slug: str, input: str) -> dict[str, str]:
        if _registry is None:
            raise HTTPException(status_code=503, detail="Server not ready")

        agent = _registry.get_by_slug(agent_slug)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_slug}")

        result = await Runner.run(agent, input)
        output = result.final_output
        if output is None:
            response_output = ""
        elif isinstance(output, str):
            response_output = output
        elif isinstance(output, (dict, list)):
            response_output = json.dumps(output)
        else:
            response_output = str(output)

        return {"agent": agent.name, "output": response_output}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "agents": list(_registry.agents.keys()) if _registry else []}

    return app
