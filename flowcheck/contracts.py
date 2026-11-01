"""Explicit rules for the first order-event format. No automatic coercion."""

from datetime import datetime
from .io import rows

FIELDS = {"schema_version", "event_id", "order_id", "amount_minor", "currency", "occurred_at"}
CURRENCIES = {"GBP", "EUR", "USD"}
MAX_AMOUNT_MINOR = 1_000_000_000


def order_errors(record):
    if not isinstance(record, dict):
        return ["Expected a JSON object"]
    errors = []
    missing = FIELDS - record.keys()
    unknown = record.keys() - FIELDS
    if missing:
        errors.append(f"Missing fields: {', '.join(sorted(missing))}")
    if unknown:
        errors.append(f"Unknown fields: {', '.join(sorted(unknown))}")
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        errors.append("schema_version must be the integer 1")
    for field in ("event_id", "order_id"):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 100:
            errors.append(f"{field} must contain 1 to 100 characters with no outer spaces")
    amount = record.get("amount_minor")
    if type(amount) is not int or not 0 <= amount <= MAX_AMOUNT_MINOR:
        errors.append(f"amount_minor must be an integer from 0 to {MAX_AMOUNT_MINOR}")
    currency = record.get("currency")
    if not isinstance(currency, str) or currency not in CURRENCIES:
        errors.append("currency must be GBP, EUR or USD")
    try:
        timestamp = record.get("occurred_at")
        if not isinstance(timestamp, str) or "T" not in timestamp:
            raise ValueError()
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
    except ValueError:
        errors.append("occurred_at must be an ISO timestamp with a timezone")
    return errors


def validate_file(path):
    accepted, rejected = [], []
    for line_number, record, parse_error in rows(path):
        errors = [parse_error] if parse_error else order_errors(record)
        if errors:
            # Keep only positions and reasons in shared reports, not the input row.
            rejected.append({"line": line_number, "errors": errors})
        else:
            accepted.append(record)
    if not accepted and not rejected:
        raise ValueError("The input contains no records")
    return accepted, {"accepted": len(accepted), "rejected": len(rejected), "errors": rejected}
