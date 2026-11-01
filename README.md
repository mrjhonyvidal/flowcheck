# FlowCheck

A small lab for three everyday problems: bad incoming data, duplicate work after a retry, and AI output that looks right but fails a check. One order-event example connects all three. Use any part on its own.

```bash
git clone https://github.com/mrjhonyvidal/flowcheck.git
cd flowcheck
python3 -m flowcheck demo
python3 -m unittest discover -s tests -v
```

**You need:** Git and Python 3.11 or newer. Allow five minutes. **Account: none. Estimated service cost: £0.** There are no Python packages to install and no network calls after cloning. Laptop and electricity costs are excluded.

The interface is terminal commands and JSON reports. There is no web UI.

You should see **1 accepted and 3 rejected rows**, then **2 inserted events** and **0 new events on retry**. The saved AI examples score **2/4** and **4/4**. These are hand-written teaching fixtures, not measured model performance.

## If setup gets stuck

- Check `git --version` and `python3 --version`. Python must be 3.11 or newer.
- On Windows, replace `python3` with `py -3` after cloning the repository.
- Run commands from the `flowcheck` folder containing this README. No package installation, environment file or virtual environment is required for these examples.

## 1. Check the input

```bash
python3 -m flowcheck validate examples/events.clean.jsonl
python3 -m flowcheck validate examples/events.mixed.jsonl
```

The second command intentionally exits with code 1. Read the line numbers and reasons. It does not fix or discard bad rows silently. The report omits row values, but error messages and IDs still need a retention policy when you adapt this to private data.

Each JSONL line is one JSON object. The version 1 contract has six fields:

| Field | Rule |
| --- | --- |
| `schema_version` | Integer `1` |
| `event_id` | Immutable event identity, 1 to 100 characters |
| `order_id` | Order reference, 1 to 100 characters |
| `amount_minor` | Whole pence or cents, from 0 to 1,000,000,000 |
| `currency` | `GBP`, `EUR` or `USD` |
| `occurred_at` | ISO timestamp with a timezone |

No extra fields, blank IDs, duplicate JSON keys, non-finite numbers or automatic type conversions are accepted. A boolean is not accepted as an integer. All three supported currencies have two decimal places; add an explicit unit rule before accepting a currency with a different minor unit. This checks representation, not whether a real order exists or its price is correct.

## 2. Run the same job twice

```bash
python3 -m flowcheck ingest examples/events.clean.jsonl
python3 -m flowcheck ingest examples/events.clean.jsonl
python3 -m flowcheck ingest examples/events.conflict.jsonl
```

The first run inserts two events. The second reports two duplicates and keeps the same GBP total of **2,249 pence**. The third intentionally exits with code 2: it reuses `evt-1` with a changed amount. The whole conflicting batch rolls back, including its new `evt-3` row.

`runs/orders.db` is a local SQLite file. The event ID is the key, and a hash checks whether a repeated ID has changed content. Insertion and duplicate checking happen inside one transaction. Different IDs are separate events, even when their other fields match. Database transactions do not make an external action happen only once.

For a clean rerun, choose another file with `--database runs/another.db`. `demo` uses a temporary database and is safe to repeat.

## 3. Compare saved AI attempts

```bash
python3 -m flowcheck evaluate examples/traces.candidate.jsonl
python3 -m flowcheck evaluate examples/traces.baseline.jsonl
```

The candidate passes. The baseline intentionally exits with code 1 because two outputs fail. The evaluator checks the event contract and exact agreement with reviewed fields. A missing currency should lead to review, not a guessed default. A customer note cannot replace the stated price.

Every attempt contributes tokens and time, including failed attempts. The default gates require all cases to pass, a total token estimate at or below $0.01, and nearest-rank p95 at or below 5,000 ms. With only four cases, p95 is the slowest observed case, not a useful estimate of production tail latency. Missing traces fail the completeness gate and remain in the quality denominator. Unknown IDs, missing prices and malformed usage records are errors.

The rate file uses **illustrative prices** of $1 per million input tokens and $2 per million output tokens. It makes no claim about a provider. Baseline total: **$0.0028**. Candidate total, including one retry: **$0.0033**. No money is spent. Real bills can include cached tokens, reasoning tokens, tool fees, storage and discounts that this calculator does not model.

You can change the gates:

```bash
python3 -m flowcheck evaluate examples/traces.candidate.jsonl \
  --max-cost-usd 0.005 --max-p95-ms 1000 --min-success-rate 1
```

## Adapt one piece

| Change | Where to start |
| --- | --- |
| Different data fields or a new format version | `flowcheck/contracts.py`, then add invalid and valid examples |
| Another database | Replace `flowcheck/store.py`; keep the retry and rollback tests |
| Real model output | Convert saved responses into the trace format; keep the evaluator independent of provider SDKs |
| A different task | Replace `examples/cases.jsonl` and the result checks in `flowcheck/evaluation.py` |
| Real rates | Copy `examples/prices.json` and pass `--prices your-file.json` |

Trace records need `case_id`, `prompt_version`, `source_version` and `attempts`. Each attempt records a model version, status, token counts and elapsed time, including waiting before that attempt. The final attempt carries `result`. Case records keep input text, `label_version` and reviewed `expected` output. Inspect the fixture files before writing an adapter.

For a live trial, start with ten reviewed, non-sensitive examples. Save the exact model, prompt, source and price versions. Capture retries and waiting time as well as the successful call. Run the saved traces through this evaluator before deciding whether a larger experiment is worthwhile. One successful saved response does not demonstrate future reliability or resistance to prompt injection.

This is a local learning project. There is no scheduler, hosted service, model client or external action. Add those when your use case needs them. Code and synthetic fixtures are [MIT licensed](LICENSE).
