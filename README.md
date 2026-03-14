# KernelPatcher

[![CI](https://github.com/mattschu22/KernelPatchAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/mattschu22/KernelPatchAgent/actions/workflows/ci.yml)

An agentic AI system that automatically generates patches for Linux kernel bugs. Given a crash report and the relevant source files, KernelPatcher produces a corrected version of the code and evaluates it against a kernel build/test infrastructure.

## Architecture

KernelPatcher uses an 8-agent hierarchy where each layer handles a different level of abstraction:

```
                        ┌──────────────┐
Level 0                 │ Orchestrator │
                        └──────┬───────┘
                               │  Directs the Planner → Coder → Reviewer
                               │  cycle (up to 3 iterations)
                 ┌─────────────┼─────────────┐
                 ▼             ▼             ▼
Level 1    ┌─────────┐   ┌─────────┐   ┌──────────┐
           │ Planner │   │  Coder  │   │ Reviewer │
           └────┬────┘   └────┬────┘   └────┬─────┘
                │             │             │
                └─────────────┼─────────────┘
                 ┌────────┬───┴───┬────────┐
                 ▼        ▼       ▼        ▼
Level 2    ┌────────┐ ┌─────┐ ┌──────┐ ┌─────────┐
           │ Elixir │ │ Web │ │ Code │ │ General │
           └────────┘ └─────┘ └──────┘ └─────────┘
           Source code lookup, kernel.org search,
           code analysis, delegated research
```

Agents communicate via HTTP through a FastAPI server. Each agent is backed by an LLM with specialized system prompts and tools scoped to its role.

### Inference Backends

The pipeline supports three model backends for patch generation:

| Backend | Model | Description |
|---------|-------|-------------|
| `custom` | Multi-agent system | 8-agent hierarchy via local server |
| `gpt-4.1` | OpenAI GPT-4.1 | Single-model direct inference |
| `sonnet-4` | Anthropic Claude | Single-model direct inference |

### Compilation Feedback Loop

When patches fail to compile, KernelPatcher can automatically retry with error context. The retry system feeds the original bug, the failed diff, and the compilation error back to the model as a structured prompt, giving it the information needed to produce a corrected patch. This is configurable via `max_retries` in the pipeline.

## Project Structure

```
kernel_patcher/
  __init__.py            Public API
  __main__.py            CLI entry point (infer, serve, analyze)
  config.py              Pipeline configuration and agent hierarchy
  models.py              Data models (BugInstance, PatchResponse, EvalResult)
  parser.py              Parse kBench input format and model XML output
  diff.py                Generate unified diffs via git
  inference.py           Model client backends with parallel execution
  evaluation.py          kSuite job submission and result classification
  pipeline.py            End-to-end orchestration with metrics
  retry.py               Compilation feedback loop for failed patches
  metrics.py             Observability: timing, success rates, p95 latency
  analysis.py            Result analysis by subsystem and file complexity
  agents/
    tools.py             Bootlin source fetcher, kernel.org search
    registry.py          Agent builder with hierarchical tool assignment
    server.py            FastAPI application

prompts/                 System prompts for each agent
descriptions/            Short descriptions used as tool docstrings
data/
  patch_types.json       227 kernel bugs categorized by subsystem
  results/               Evaluation results per model backend
tests/                   116 tests, all API calls mocked (zero tokens)
```

## Setup

```bash
uv sync
```

Or with Docker:

```bash
docker compose up
```

## Usage

Start the multi-agent server:

```bash
python -m kernel_patcher serve --port 8008
```

Run inference on a dataset of kernel bugs:

```bash
python -m kernel_patcher infer --data data.json --model custom --output responses.json
```

Analyze evaluation results by subsystem:

```bash
python -m kernel_patcher analyze --data-dir data/
```

Run as a library:

```python
from kernel_patcher import KernelPatchPipeline, PipelineConfig
from kernel_patcher.config import ModelBackend

config = PipelineConfig(model=ModelBackend.CUSTOM)
pipeline = KernelPatchPipeline(config)

bugs = pipeline.load_bugs("data.json")
result = pipeline.run(bugs, skip_eval=True)

for resp in result.responses:
    print(resp.instance_id, len(resp.patched_files), "files patched")

# Pipeline metrics (timing, success rates)
print(pipeline.metrics.summary())
```

## Testing

```bash
uv run python -m pytest tests/ -v
```

All 116 tests run with mocked API calls and use zero tokens.

## Evaluation Results

Evaluated on 227 kernel bugs from kBench across File System, Networking, Device Drivers, Memory Management, Security, and Virtualization subsystems:

| Model | Fixed Bug | Did Not Fix Bug | Compilation Error |
|-------|-----------|-----------------|-------------------|
| Custom (8-agent) | 26 (11.5%) | 45 (19.8%) | 156 (68.7%) |
| Claude (sonnet-4) | 14 (6.2%) | 40 (17.6%) | 173 (76.2%) |
| GPT-4.1 | 14 (6.2%) | 27 (11.9%) | 186 (81.9%) |

### Breakdown by Subsystem (Custom 8-Agent)

| Subsystem | Fixed | Wrong Fix | Compile Error | Fix Rate |
|-----------|-------|-----------|---------------|----------|
| File System | 13 | 13 | 42 | 19.1% |
| Networking | 7 | 11 | 42 | 11.7% |
| Device Drivers | 5 | 16 | 25 | 10.9% |
| Memory Management | 1 | 2 | 8 | 9.1% |
| Init/System Management | 0 | 2 | 8 | 0.0% |
| Virtualization | 0 | 1 | 5 | 0.0% |
| Security | 0 | 0 | 4 | 0.0% |

Single-file bugs are fixed at 13.2% vs 8.7% for multi-file bugs, confirming that cross-file patches are harder for LLMs to produce correctly.
