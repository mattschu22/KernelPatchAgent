FROM python:3.12-slim AS base

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY kernel_patcher/ kernel_patcher/
COPY prompts/ prompts/
COPY descriptions/ descriptions/

EXPOSE 8008

CMD ["uv", "run", "python", "-m", "kernel_patcher", "serve", "--port", "8008"]
