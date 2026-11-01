"""Run with python3 -m flowcheck from the project directory."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from .contracts import validate_file
from .evaluation import evaluate
from .io import decode, read_records
from .store import ingest

ROOT = Path(__file__).resolve().parents[1]


def score(cases, traces, prices, **limits):
    return evaluate(read_records(cases), read_records(traces), decode(Path(prices).read_text()), **limits)


def demo():
    examples = ROOT / "examples"
    _, validation = validate_file(examples / "events.mixed.jsonl")
    clean, _ = validate_file(examples / "events.clean.jsonl")
    # A temporary database makes repeated demo runs independent.
    with TemporaryDirectory(prefix="flowcheck-") as folder:
        first = ingest(clean, Path(folder) / "orders.db")
        retry = ingest(clean, Path(folder) / "orders.db")
    reports = {name: score(examples / "cases.jsonl", examples / f"traces.{name}.jsonl",
                           examples / "prices.json") for name in ("baseline", "candidate")}
    return {"validation": validation, "first_run": first, "retry": retry, "evaluations": reports}


def parser():
    command = argparse.ArgumentParser(description="Check data, retry a job, and compare saved AI outputs offline.")
    actions = command.add_subparsers(dest="action", required=True)
    actions.add_parser("demo", help="Run all three experiments with synthetic fixtures")
    for name in ("validate", "ingest"):
        action = actions.add_parser(name)
        action.add_argument("path", type=Path)
        if name == "ingest":
            action.add_argument("--database", type=Path, default=Path("runs/orders.db"))
    scoring = actions.add_parser("evaluate")
    scoring.add_argument("traces", type=Path)
    scoring.add_argument("--cases", type=Path, default=ROOT / "examples/cases.jsonl")
    scoring.add_argument("--prices", type=Path, default=ROOT / "examples/prices.json")
    scoring.add_argument("--min-success-rate", type=float, default=1.0)
    scoring.add_argument("--max-cost-usd", type=float, default=0.01)
    scoring.add_argument("--max-p95-ms", type=float, default=5000)
    return command


def main(argv=None):
    arguments = parser().parse_args(argv)
    try:
        if arguments.action == "demo":
            result, failed = demo(), False
        elif arguments.action in ("validate", "ingest"):
            records, result = validate_file(arguments.path)
            failed = result["rejected"] > 0
            if arguments.action == "ingest" and not failed:
                result = ingest(records, arguments.database)
        else:
            result = score(arguments.cases, arguments.traces, arguments.prices,
                           min_success_rate=arguments.min_success_rate,
                           max_cost_usd=arguments.max_cost_usd, max_p95_ms=arguments.max_p95_ms)
            failed = not result["passed"]
        print(json.dumps(result, indent=2, allow_nan=False))
        return 1 if failed else 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
