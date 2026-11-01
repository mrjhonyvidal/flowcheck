from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from flowcheck.contracts import order_errors, validate_file
from flowcheck.evaluation import evaluate
from flowcheck.io import decode, read_records
from flowcheck.store import ingest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


class FlowCheckTest(unittest.TestCase):
    def setUp(self):
        self.events = read_records(EXAMPLES / "events.clean.jsonl")
        self.cases = read_records(EXAMPLES / "cases.jsonl")
        self.traces = read_records(EXAMPLES / "traces.candidate.jsonl")
        self.prices = decode((EXAMPLES / "prices.json").read_text())

    def score(self, **limits):
        return evaluate(self.cases, self.traces, self.prices, **limits)

    def test_contract_rejects_types_units_and_unknown_fields(self):
        for patch in ({"amount_minor": True}, {"amount_minor": "1250"}, {"amount_minor": -1},
                      {"amount_minor": 1.5}, {"currency": "JPY"}, {"currency": []},
                      {"schema_version": True}, {"schema_version": 2}, {"extra": "value"},
                      {"order_id": " "}, {"occurred_at": "2026-10-20T09:00:00"}):
            with self.subTest(patch=patch):
                self.assertTrue(order_errors({**self.events[0], **patch}))
        self.assertEqual(order_errors(self.events[0]), [])

    def test_invalid_json_and_row_positions_are_reported(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "rows.jsonl"
            path.write_text(json.dumps(self.events[0]) + '\n\n{"amount_minor":NaN}\n[]\n')
            accepted, report = validate_file(path)
        self.assertEqual(len(accepted), 1)
        self.assertEqual([row["line"] for row in report["errors"]], [3, 4])
        self.assertNotIn("order-1", json.dumps(report))

    def test_duplicate_keys_are_not_silently_overwritten(self):
        with self.assertRaisesRegex(ValueError, "Repeated JSON key"):
            decode('{"amount_minor":100,"amount_minor":900}')

    def test_empty_input_is_an_error(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "empty.jsonl"
            path.write_text("\n")
            with self.assertRaises(ValueError):
                validate_file(path)

    def test_retry_does_not_change_totals_and_key_order_is_irrelevant(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "orders.db"
            first = ingest(self.events, path)
            retry = ingest([dict(reversed(list(row.items()))) for row in self.events], path)
        self.assertEqual(first["inserted"], 2)
        self.assertEqual(retry["inserted"], 0)
        self.assertEqual(retry["duplicates"], 2)
        self.assertEqual(retry["totals_minor"], {"GBP": 2249})

    def test_conflict_rolls_back_new_records_in_same_batch(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "orders.db"
            ingest(self.events, path)
            with self.assertRaisesRegex(ValueError, "batch rolled back"):
                ingest(read_records(EXAMPLES / "events.conflict.jsonl"), path)
            result = ingest(self.events, path)
        self.assertEqual(result["stored_events"], 2)
        self.assertEqual(result["totals_minor"], {"GBP": 2249})

    def test_two_workers_do_not_double_count(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "orders.db"
            with ThreadPoolExecutor(max_workers=2) as workers:
                reports = list(workers.map(lambda _: ingest(self.events, path), range(2)))
        self.assertEqual(sum(report["inserted"] for report in reports), 2)
        self.assertTrue(all(report["stored_events"] == 2 for report in reports))

    def test_invalid_batch_cannot_partially_write(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "orders.db"
            with self.assertRaises(ValueError):
                ingest([self.events[0], {**self.events[1], "amount_minor": "999"}], path)
            self.assertFalse(path.exists())

    def test_distinct_ids_and_currencies_stay_separate(self):
        with TemporaryDirectory() as folder:
            result = ingest([self.events[0], {**self.events[0], "event_id": "evt-new"},
                             {**self.events[1], "currency": "EUR"}], Path(folder) / "orders.db")
        self.assertEqual(result["totals_minor"], {"EUR": 999, "GBP": 2500})

    def test_cost_includes_failed_retry_and_quality_checks_labels(self):
        candidate = self.score()
        baseline = evaluate(self.cases, read_records(EXAMPLES / "traces.baseline.jsonl"), self.prices)
        self.assertEqual(candidate["successes"], 4)
        self.assertEqual(candidate["attempts"], 5)
        self.assertAlmostEqual(candidate["total_cost_usd"], 0.0033)
        self.assertAlmostEqual(candidate["cost_per_success_usd"], 0.000825)
        self.assertEqual(candidate["p95_ms"], 800)
        self.assertTrue(candidate["passed"])
        self.assertEqual(baseline["successes"], 2)
        self.assertAlmostEqual(baseline["total_cost_usd"], 0.0028)
        self.assertFalse(baseline["passed"])

    def test_missing_trace_remains_in_quality_denominator(self):
        self.traces.pop()
        result = self.score()
        self.assertEqual(result["cases"], 4)
        self.assertEqual(result["success_rate"], 0.75)
        self.assertFalse(result["gates"]["complete"])

    def test_no_success_has_no_invented_cost_per_success(self):
        for trace in self.traces:
            trace["attempts"][-1]["status"] = "error"
        result = self.score()
        self.assertIsNone(result["cost_per_success_usd"])
        self.assertEqual(result["p95_ms"], 800)
        self.assertFalse(result["passed"])

    def test_unknown_and_duplicate_case_ids_are_errors(self):
        for records in ([*self.traces, self.traces[0]], [{**self.traces[0], "case_id": "unknown"}]):
            with self.subTest(records=records):
                with self.assertRaises(ValueError):
                    evaluate(self.cases, records, self.prices)

    def test_invalid_usage_or_missing_prices_cannot_look_cheap(self):
        for patch in ({"model": "unpriced"}, {"input_tokens": -1}, {"input_tokens": True},
                      {"elapsed_ms": float("nan")}, {"elapsed_ms": -1}, {"status": "skipped"}):
            with self.subTest(patch=patch):
                traces = deepcopy(self.traces)
                traces[0]["attempts"][0].update(patch)
                with self.assertRaises(ValueError):
                    evaluate(self.cases, traces, self.prices)

    def test_changed_semantics_fail_even_with_valid_structure(self):
        self.traces[0]["attempts"][0]["result"]["event"]["amount_minor"] = 99999
        self.assertEqual(self.score()["successes"], 3)

    def test_review_cannot_also_accept_an_event(self):
        self.traces[2]["attempts"][0]["result"]["event"] = self.events[0]
        self.assertEqual(self.score()["successes"], 3)

    def test_limits_and_rates_must_be_finite_and_sensible(self):
        for limits in ({"max_cost_usd": -1}, {"max_cost_usd": float("nan")},
                       {"min_success_rate": 1.1}, {"max_p95_ms": float("inf")}):
            with self.subTest(limits=limits):
                with self.assertRaises(ValueError):
                    self.score(**limits)
        self.prices["teaching-model"]["input_per_million"] = "NaN"
        with self.assertRaises(ValueError):
            self.score()

    def test_quality_cost_and_latency_are_separate_gates(self):
        result = self.score(max_cost_usd=0.001, max_p95_ms=700)
        self.assertTrue(result["gates"]["quality"])
        self.assertFalse(result["gates"]["cost"])
        self.assertFalse(result["gates"]["latency"])

    def test_provenance_is_required(self):
        del self.traces[0]["prompt_version"]
        with self.assertRaisesRegex(ValueError, "prompt_version"):
            self.score()

    def test_cli_exit_codes_and_demo_are_repeatable(self):
        def run(*args):
            return subprocess.run([sys.executable, "-m", "flowcheck", *args], cwd=ROOT,
                                  capture_output=True, text=True)
        for _ in range(2):
            result = run("demo")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["retry"]["inserted"], 0)
        self.assertEqual(run("validate", "examples/events.mixed.jsonl").returncode, 1)
        self.assertEqual(run("evaluate", "examples/traces.baseline.jsonl").returncode, 1)
        self.assertEqual(run("evaluate", "examples/traces.candidate.jsonl").returncode, 0)
        self.assertEqual(run("validate", "examples/missing.jsonl").returncode, 2)
        with TemporaryDirectory() as folder:
            database = str(Path(folder) / "orders.db")
            self.assertEqual(run("ingest", "examples/events.mixed.jsonl", "--database", database).returncode, 1)
            self.assertFalse(Path(database).exists())


if __name__ == "__main__":
    unittest.main()
