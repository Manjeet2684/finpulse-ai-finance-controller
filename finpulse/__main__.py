from __future__ import annotations

import argparse
import json

import uvicorn

from finpulse.pipeline import generate, run_batch


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="finpulse")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("generate", help="Write seeded fixture CSVs + answer key")
    run_p = sub.add_parser("run", help="Ingest fixture, match, investigate leftovers, write artifacts")
    run_p.add_argument("--no-reset", action="store_true")
    run_p.add_argument("--skip-llm", action="store_true")
    run_p.add_argument("--force-investigate", action="store_true")
    serve_p = sub.add_parser("serve", help="Start the API")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.cmd == "generate":
        key = generate()
        print(json.dumps({
            "canonical_cases": key["canonical_cases"],
            "physical_rows": key["physical_rows"],
            "row_counts": key["row_counts"],
            "planted_should_match": key["planted_should_match"],
            "planted_exceptions": key["planted_exceptions"],
            "exception_type_counts": key["exception_type_counts"],
        }, indent=2))
        return
    if args.cmd == "run":
        summary = run_batch(
            reset=not args.no_reset,
            skip_llm=args.skip_llm,
            force_investigate=args.force_investigate,
        )
        print(json.dumps(summary, indent=2, default=str))
        return
    if args.cmd == "serve":
        uvicorn.run("finpulse.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
