"""Score saved extraction attempts against reviewed synthetic cases."""

from decimal import Decimal, InvalidOperation
import math
from .contracts import order_errors
from .io import canonical


def nonnegative_number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return value


def price(value):
    if isinstance(value, bool):
        raise ValueError("Prices must be finite non-negative numbers")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Invalid price") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError("Prices must be finite non-negative numbers")
    return amount


def result_errors(result):
    if not isinstance(result, dict) or set(result) != {"decision", "event"}:
        return ["Result requires exactly decision and event"]
    if result["decision"] == "review":
        return [] if result["event"] is None else ["A review result must have event: null"]
    if result["decision"] == "accept":
        return order_errors(result["event"])
    return ["decision must be accept or review"]


def keyed(records, name):
    indexed = {}
    for record in records:
        identifier = record.get("case_id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in indexed:
            raise ValueError(f"{name} has a missing or repeated case_id")
        indexed[identifier] = record
    if not indexed:
        raise ValueError(f"{name} is empty")
    return indexed


def evaluate(cases, traces, prices, min_success_rate=1.0, max_cost_usd=0.01, max_p95_ms=5000):
    nonnegative_number(min_success_rate, "min_success_rate")
    if min_success_rate > 1:
        raise ValueError("min_success_rate must be at most 1")
    budget = price(max_cost_usd)
    nonnegative_number(max_p95_ms, "max_p95_ms")
    labels = keyed(cases, "Cases")
    runs = keyed(traces, "Traces")
    if runs.keys() - labels.keys():
        raise ValueError("Traces contain unknown case IDs")
    if not isinstance(prices, dict) or not prices:
        raise ValueError("Provide at least one model price")
    for rates in prices.values():
        if not isinstance(rates, dict) or set(rates) != {"input_per_million", "output_per_million"}:
            raise ValueError("Each model price needs input_per_million and output_per_million")
        for rate in rates.values():
            price(rate)
    total_cost, successes, total_attempts = Decimal(0), 0, 0
    latencies, details = [], []
    for identifier, case in labels.items():
        if not isinstance(case.get("input"), str) or not case["input"].strip():
            raise ValueError(f"Case {identifier} needs input text")
        if not isinstance(case.get("label_version"), str) or not case["label_version"].strip():
            raise ValueError(f"Case {identifier} needs a label_version")
        if result_errors(case.get("expected")):
            raise ValueError(f"Invalid reviewed expectation for {identifier}")
        trace = runs.get(identifier)
        if trace is None:
            details.append({"case_id": identifier, "success": False, "reason": "Missing trace"})
            continue
        for field in ("prompt_version", "source_version"):
            if not isinstance(trace.get(field), str) or not trace[field].strip():
                raise ValueError(f"Trace {identifier} needs {field}")
        attempts = trace.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ValueError(f"Trace {identifier} needs at least one attempt")
        elapsed, case_cost = 0, Decimal(0)
        for attempt in attempts:
            if not isinstance(attempt, dict) or attempt.get("status") not in ("ok", "error"):
                raise ValueError("Each attempt needs status ok or error")
            model = attempt.get("model")
            if not isinstance(model, str) or model not in prices:
                raise ValueError(f"Missing price for model {model}")
            for field in ("input_tokens", "output_tokens"):
                if type(attempt.get(field)) is not int or attempt[field] < 0:
                    raise ValueError(f"{field} must be a non-negative integer")
            elapsed += nonnegative_number(attempt.get("elapsed_ms"), "elapsed_ms")
            rates = prices[model]
            case_cost += (Decimal(attempt["input_tokens"]) * price(rates["input_per_million"])
                          + Decimal(attempt["output_tokens"]) * price(rates["output_per_million"])) / 1_000_000
        errors = result_errors(attempts[-1].get("result"))
        success = (attempts[-1]["status"] == "ok" and not errors
                   and canonical(attempts[-1]["result"]) == canonical(case["expected"]))
        successes += int(success)
        total_attempts += len(attempts)
        total_cost += case_cost
        latencies.append(elapsed)
        details.append({"case_id": identifier, "success": success, "attempts": len(attempts),
                        "reason": "Matched reviewed output" if success else "; ".join(errors) or "Output did not match",
                        "cost_usd": float(case_cost), "elapsed_ms": elapsed})
    rate = successes / len(labels)
    p95 = sorted(latencies)[math.ceil(0.95 * len(latencies)) - 1] if latencies else None
    gates = {"quality": rate >= min_success_rate, "cost": total_cost <= budget,
             "latency": p95 is not None and p95 <= max_p95_ms, "complete": len(runs) == len(labels)}
    return {"cases": len(labels), "successes": successes, "success_rate": rate,
            "attempts": total_attempts, "total_cost_usd": float(total_cost),
            "cost_per_success_usd": float(total_cost / successes) if successes else None,
            "p95_ms": p95, "gates": gates, "passed": all(gates.values()), "details": details}
