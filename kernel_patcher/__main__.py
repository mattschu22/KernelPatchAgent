"""CLI entry point for the KernelPatcher pipeline.

Usage:
    python -m kernel_patcher infer --data data.json --model custom --output responses.json
    python -m kernel_patcher serve --port 8008
    python -m kernel_patcher analyze --data-dir data/
"""

from __future__ import annotations

import argparse
import logging
import sys

from kernel_patcher.config import ModelBackend, PipelineConfig


def cmd_infer(args: argparse.Namespace) -> None:
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

    summary = pipeline.metrics.summary()
    print(f"Saved {len(responses)} responses to {args.output}")
    if summary.get("latency"):
        latency = summary["latency"]
        print(f"Latency: mean={latency['mean_s']}s, p95={latency['p95_s']}s")  # type: ignore[index]


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from kernel_patcher.agents.server import create_app

    config = PipelineConfig(server_port=args.port)
    app = create_app(config)
    uvicorn.run(app, host="0.0.0.0", port=args.port)


def cmd_analyze(args: argparse.Namespace) -> None:
    from kernel_patcher.analysis import run_analysis

    output = run_analysis(args.data_dir)
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="KernelPatcher pipeline")
    sub = parser.add_subparsers(dest="command")

    # infer
    infer_p = sub.add_parser("infer", help="Run inference on kernel bugs")
    infer_p.add_argument("--data", required=True, help="Path to bug data JSON")
    infer_p.add_argument(
        "--model",
        default="custom",
        choices=["gpt-4.1", "sonnet-4", "custom"],
    )
    infer_p.add_argument("--output", default="responses.json")
    infer_p.add_argument("--workers", type=int, default=8)
    infer_p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of bugs to process",
    )

    # serve
    serve_p = sub.add_parser("serve", help="Start the agent server")
    serve_p.add_argument("--port", type=int, default=8008)

    # analyze
    analyze_p = sub.add_parser("analyze", help="Analyze evaluation results by subsystem")
    analyze_p.add_argument(
        "--data-dir",
        default="data",
        help="Directory containing results and patch_types",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.command == "infer":
        cmd_infer(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
