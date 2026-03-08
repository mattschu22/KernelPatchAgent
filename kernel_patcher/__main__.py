"""CLI entry point for the KernelPatcher pipeline.

Usage:
    python -m kernel_patcher infer --data data.json --model custom --output responses.json
    python -m kernel_patcher serve --port 8008
"""

from __future__ import annotations

import argparse
import logging
import sys

from kernel_patcher.config import ModelBackend, PipelineConfig


def cmd_infer(args):
    from kernel_patcher.pipeline import KernelPatchPipeline

    config = PipelineConfig(
        model=ModelBackend(args.model),
        max_workers=args.workers,
    )
    pipeline = KernelPatchPipeline(config)
    bugs = pipeline.load_bugs(args.data)

    if args.limit:
        bugs = bugs[: args.limit]

    responses = pipeline.run_inference(bugs)
    pipeline.generate_diffs(bugs, responses)
    pipeline.save_responses(responses, args.output)
    print(f"Saved {len(responses)} responses to {args.output}")


def cmd_serve(args):
    import uvicorn

    from kernel_patcher.agents.server import create_app

    config = PipelineConfig(server_port=args.port)
    app = create_app(config)
    uvicorn.run(app, host="0.0.0.0", port=args.port)


def main():
    parser = argparse.ArgumentParser(description="KernelPatcher pipeline")
    sub = parser.add_subparsers(dest="command")

    # infer
    infer_p = sub.add_parser("infer", help="Run inference on kernel bugs")
    infer_p.add_argument("--data", required=True, help="Path to bug data JSON")
    infer_p.add_argument("--model", default="custom", choices=["gpt-4.1", "sonnet-4", "custom"])
    infer_p.add_argument("--output", default="responses.json")
    infer_p.add_argument("--workers", type=int, default=8)
    infer_p.add_argument("--limit", type=int, default=None, help="Limit number of bugs to process")

    # serve
    serve_p = sub.add_parser("serve", help="Start the agent server")
    serve_p.add_argument("--port", type=int, default=8008)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.command == "infer":
        cmd_infer(args)
    elif args.command == "serve":
        cmd_serve(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
