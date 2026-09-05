# FINPULSE AI — Razorpay Buildathon Track 04

3-way reconciliation controller for **Razorpay × Bank × Ledger**.

FINPULSE closes **one** finance-ops loop on a seeded batch of **150 canonical cases** (448 physical CSV rows). It auto-matches exact triples, investigates leftovers with an LLM, applies a unique-cause **safety gate** (status/routing only), and leaves approve/escalate to a human. It reports a post-recon **cash position** and an inspectable exception list.

**Out of scope:** cash forecasting, live Razorpay APIs, Postgres.

| Matcher precision / recall | AI exception-type accuracy (frozen) | Cash position |
|---|---|---|
| **1.0 / 1.0** (116/116 matches, 34/34 traps refused) | **85.0% (34/40)** on run `27da232e` | Matched ₹22,15,116.50 · in transit ₹1,86,001.00 · exceptional ₹5,24,903.00 |

Official numbers are copied from `artifacts/run_27da232e-53a9-4122-abaf-57ed6e10d6a2/metrics.json`. They are not estimates. Do not rerun the LLM and treat a new score as official.

## Objective

Reconcile three source CSVs, auto-post only deterministic 3-way matches, classify unmatched leftovers, and produce an audit trail plus artifacts a controller can inspect. Ground truth is planted for evaluation and is **never sent to the LLM**.

## Core features

- Deterministic matcher: same `order_ref`, same amount, timestamps within ±24 hours. No LLM on money math or posting.
- Exception investigation via `investigate()` (Gemini through the OpenAI-compatible API).
- Policy routing (`AUTO_SUGGESTED` / `NEEDS_REVIEW` / `UNRESOLVED`) plus a unique-cause evidence gate (status only).
- Human approve / escalate with `AuditEvent` rows.
- FastAPI + SQLite backend; Vite dashboard; CSV/JSON artifact export.
- Frozen scored baseline: matcher 1.0/1.0, exception-type accuracy **85.0% (34/40)**.

## Track 04 mapping

| Requirement | Where it lives |
|---|---|
| One closed finance-ops loop | Ingest → match → investigate leftovers → human approve/escalate → audit + artifacts |
| Deterministic money math | Matcher only: same `order_ref`, same amount, ±24h |
| Inspectable exceptions | Dashboard + `exceptions.csv` / `incorrect.csv` / `recon_report.json` |
| Cash position after recon | Matched / in transit / exceptional on the dashboard and in `metrics.json` |
| Human remains accountable | AI never auto-approves. `AUTO_SUGGESTED` still needs a controller |
| Not in scope | Cash forecasting, live Razorpay APIs, Postgres |

## Architecture

```
CSV fixtures (seed 42)
        ↓
     SQLite
        ├─ matcher (order_ref + amount + ±24h)     ← no LLM
        ├─ leftovers → Exception rows
        ├─ investigate()                           ← only LLM seam
        ├─ policy (0.85 AUTO_SUGGESTED; else NEEDS_REVIEW;
        │          UNRESOLVABLE / insufficient evidence → UNRESOLVED)
        ├─ unique-cause gate (status/routing only)
        ├─ human approve / escalate + AuditEvent
        └─ artifacts/ + Vite dashboard
```

Five tables: `Transaction`, `Match`, `Exception`, `AuditEvent`, `RunMetrics`.

Exception-type accuracy is strictly `predicted exception_type == ground_truth_type`.

### Reconciliation flow

1. Ingest `fixtures/v1/` Razorpay, bank, and ledger CSVs into SQLite.
2. Matcher posts triples that share `order_ref`, exact amount, and a ±24h window.
3. Leftovers become exception rows (`NEEDS_REVIEW` until investigated).
4. `investigate()` classifies `exception_type` and writes an explanation, confidence, and recommended action. AI does not post or auto-approve.
5. Policy then the unique-cause gate set **status** only.
6. A human approves or escalates; events go to `audit_events`.
7. `write_run_artifacts` writes `artifacts/run_<id>/`. A new run always uses a new UUID and does not overwrite `27da232e`.

### Unique-cause safety gate vs the 85.0% score

These are **two different metrics**. Mixing them is incorrect.

1. Official AI type accuracy stays **85.0% (34/40)** on frozen run `27da232e-53a9-4122-abaf-57ed6e10d6a2`.
2. All six misses are planted `UNRESOLVABLE` cases that Gemini labeled `AMOUNT_MISMATCH` at confidence 0.95, status `AUTO_SUGGESTED`. See `incorrect.csv`. This is a taxonomy collision (`AMOUNT_MISMATCH` is a parent class; those leftovers also have date conflict).
3. The unique-cause gate runs **after** policy and changes **status/routing only**. Independent evidence families: `AMOUNT`, `DATE`, `MISSING_SOURCE`, `DUPLICATE`. **BANK_FEE is a subtype of `AMOUNT`**, not its own family. **≥2 families → `UNRESOLVED`.**
4. The gate does **not** rewrite `exception_type`, `ai_verdict_correct`, or `exception_accuracy_pct`.
5. Read-only routing simulation: `artifacts/gate_simulation_27da232e.json` (`multi_family_blocked_from_auto_suggest`: 6). Later `python -m finpulse run` applies the gate; that run is not a replacement official score.

On the frozen baseline, policy `unresolved.csv` is empty because the model never set `insufficient_evidence` on those six. The gate simulation is what would block them from `AUTO_SUGGESTED`.

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.14 (3.11+ may work) |
| API | FastAPI, Uvicorn |
| Database | SQLite via SQLAlchemy 2 |
| LLM | Gemini free tier (`gemini-3.5-flash` default) through the OpenAI SDK |
| Dashboard | React 19, Vite 7, Tailwind CDN |
| Tests | pytest |

## Project structure

```
finpulse/           # API, ingest, matcher, investigate, policy, gate, review, export
frontend/           # Vite dashboard (proxies /health, /runs, /exceptions, /generate)
fixtures/v1/        # Seeded CSVs + answer_key.json (seed 42)
tests/              # Matcher, policy, gate, review, scoring
artifacts/run_27da232e-53a9-4122-abaf-57ed6e10d6a2/   # Frozen official scored run
artifacts/gate_simulation_27da232e.json               # Routing simulation only
```

## Prerequisites

- Python **3.14** (developed on Windows 3.14)
- Node.js (dashboard only)
- Optional: `GEMINI_API_KEY` for live investigation. Not required for matcher + dashboard.
- Network: Tailwind CDN for dashboard styling; Gemini only if you run the LLM path

## Setup

```bash
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Environment

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Required only for `python -m finpulse run` without `--skip-llm`, and for `investigate` |
| `GEMINI_MODEL` | Default `gemini-3.5-flash` |
| `FINPULSE_DATABASE_URL` | Default `sqlite:///./finpulse.db` |
| `FINPULSE_LLM_CONCURRENCY` | Default `2` |

Fixture CSVs are already in `fixtures/v1/` (seed 42). To regenerate:

```bash
python -m finpulse generate
```

## How to run

### Matcher and dashboard (no API key)

```bash
python -m finpulse run --skip-llm
python -m pytest
python -m finpulse serve
```

API: `http://127.0.0.1:8000` (`GET /health` → `{"ok": true}`).

Second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173/**. On Windows use `localhost`, not `127.0.0.1:5173`. Start the API before the dashboard. Vite proxies `/runs`, `/exceptions`, `/health`, and `/generate` to port 8000.

`--skip-llm` leaves dashboard exception-type accuracy as **Pending LLM**. That is expected. Official **85.0%** is in the frozen artifact folder below, not in this live SQLite run.

A new `python -m finpulse run` writes `artifacts/run_<uuid>/`. It does not overwrite `27da232e`.

### Live LLM investigation (optional)

Requires `GEMINI_API_KEY`. Gemini free tier may return 429 (per-model daily cap has been 20 requests). Failed calls are not cached (`investigated_at` stays empty):

```bash
python -m finpulse run
python -m finpulse investigate
```

This applies investigation and unique-cause routing on a **new** run. It does not replace the official 85.0%.

Read-only gate simulation on the frozen leftovers:

```bash
python -m finpulse gate-sim
```

## Dashboard

The dashboard loads `GET /runs/latest` and `GET /exceptions?run_id=…`. Values are API data, not hardcoded.

- Metric cards: matcher precision/recall, exception-type accuracy (or Pending LLM), throughput, assumed manual baseline, cash split.
- Exceptions table: predicted type, planted type, status, confidence. Click a row for detail.
- Detail panel: AI explanation, recommended action, records on the same `order_ref`, audit events.
- Approve / escalate: `POST /exceptions/{id}/approve` or `/escalate` with a reviewer name.
- Export links: JSON, CSV, and unresolved list via `GET /exceptions/export`.

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Liveness |
| `POST` | `/generate` | Rewrite fixture CSVs (seed 42) |
| `POST` | `/runs` | Ingest + match; query `skip_llm`, `reset`, `force_investigate`. `reset=true` wipes SQLite |
| `GET` | `/runs/latest` | Metrics for the newest run |
| `GET` | `/exceptions` | Optional `run_id` |
| `GET` | `/exceptions/{id}` | Records + audit |
| `POST` | `/exceptions/{id}/approve` | Body: `{ "reviewer", "reason" }` |
| `POST` | `/exceptions/{id}/escalate` | Same body |
| `GET` | `/exceptions/export` | `fmt=json\|csv\|unresolved`; optional `run_id` |

## Official scored run `27da232e-53a9-4122-abaf-57ed6e10d6a2`

Copied from that folder’s `metrics.json`. Not estimated. Do not modify this directory.

| Metric | Value |
|---|---|
| Canonical cases | 150 |
| Physical rows | 448 (Razorpay 150, Bank 148, Ledger 150) |
| Matcher precision | 1.0 |
| Matcher recall | 1.0 |
| Matches created | 116 / 116 planted |
| Traps correctly refused | 34 / 34 |
| Exceptions created | 40 |
| Exception-type accuracy | **85.0% (34 / 40)** |
| Match wall time | 3.97 ms |
| End-to-end wall clock | 2058.37 s (includes free-tier quota pauses and two resumes — see note) |
| Throughput (that wall clock) | 13.06 records/min · 0.218 records/sec |
| Cash matched | ₹22,15,116.50 |
| Cash in transit | ₹1,86,001.00 |
| Cash exceptional | ₹5,24,903.00 |
| Manual baseline | **ASSUMED** 120 minutes (3 min × 40 exceptions) — not measured |

**Accuracy breakdown:** 8/8 BANK_FEE, 6/6 DUPLICATE_RECORD, 8/8 MISSING_BANK_RECEIPT, 6/6 DATE_DRIFT, 6/6 AMOUNT_MISMATCH, **0/6 UNRESOLVABLE**.

**Throughput note:** matcher time is ~4 ms. The 2058 s wall clock is calendar time of the scored run, including Gemini free-tier 429s and two `finpulse investigate` resumes onto other Flash models. It is not a clean uninterrupted batch clock. Skip-LLM throughput (thousands of records/sec) is not the official figure.

Inspect: `incorrect.csv`, `exceptions.csv`, `recon_report.json` in the frozen run folder.

If other `artifacts/run_*` folders appear locally (matcher-only or verification runs), ignore them for scoring. Only `27da232e` is official.

## How AI is used

- Only through `finpulse/investigate.py` → `investigate()`.
- Provider: Gemini free tier, OpenAI SDK at `https://generativelanguage.googleapis.com/v1beta/openai/`. Default model `gemini-3.5-flash`.
- Input: leftover records plus other rows on the same `order_ref`. No ground-truth fields.
- Output: `exception_type` enum, explanation, confidence, recommended action, `insufficient_evidence`.
- One extra classification call if confidence &lt; 0.6. Successful calls are cached (`investigated_at`). Failed quota calls are not cached.
- Concurrency default 2 (Gemini free RPM is 5).
- Failed calls stay `UNRESOLVED` until retried.

## Tests

```bash
python -m pytest -q
```

Expect **31 passed**. Deprecation warnings from `datetime.utcnow()` in `review.py` / `ingest.py` are known and not failures.

## Limitations

- Synthetic data, fixed seed 42. Match rate is only meaningful next to the planted mix.
- 3-way match requires exact amount equality; fees never auto-match.
- AI cannot close the books. `AUTO_SUGGESTED` still needs a human.
- Gemini free-tier per-model daily cap is 20 requests. The scored run used `gemini-3.6-flash`, then `gemini-flash-latest` (3.8), then `gemini-3.5-flash` to finish 40 leftovers.
- The model never classified `UNRESOLVABLE`; it called those six `AMOUNT_MISMATCH` instead.
- SQLite, local only. No live Razorpay APIs.
- Dashboard styling uses the Tailwind CDN (needs network).

## Implementation notes

- Pinned `pydantic==2.11.3` has no Python 3.14 Windows wheel; the project uses 2.13.5 (`pydantic-core` cp314).
- `session_scope()` is a `@contextmanager` (a bare generator left sessions unusable).
- `gemini-2.5-flash` returns 404 for new API users; Google now requires `gemini-3.x-flash`.
- `gemini-3.6-flash` free tier is 20 requests/day; the first investigation wave stopped at 19 successes + 21 quota failures. Failures are not cached. `python -m finpulse investigate` resumed on other Flash models.
- `gemini-flash-latest` aliases `gemini-3.8-flash` (5 RPM / 20 RPD). Concurrency is 2. RPM 429s wait for the advertised retry delay; daily-quota 429s do not wait.
