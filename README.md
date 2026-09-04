# FINPULSE AI — Razorpay Buildathon Track 04

A **3-way reconciliation controller** (Razorpay × Bank × Ledger) that closes **one** finance-ops loop on a seeded batch of **150 canonical cases** (448 physical CSV rows).

It auto-matches exact triples, sends leftovers to an LLM investigator, applies a unique-cause **safety gate** (status/routing only), and leaves a human in the loop. It reports a post-recon **cash position** and an inspectable exception list. **It does not forecast cash.**

| Matcher precision / recall | AI exception-type accuracy (frozen) | Cash position |
|---|---|---|
| **1.0 / 1.0** (116/116 matches, 34/34 traps refused) | **85.0% (34/40)** on run `27da232e` | Matched ₹22,15,116.50 · in transit ₹1,86,001.00 · exceptional ₹5,24,903.00 |

Official numbers are copied from `artifacts/run_27da232e-53a9-4122-abaf-57ed6e10d6a2/metrics.json`. They are not estimates. **Do not rerun the LLM and treat a new score as official.**

## Track 04 mapping

| Requirement | Where it lives |
|---|---|
| One closed finance-ops loop | Ingest → match → investigate leftovers → human approve/escalate → audit + artifacts |
| Deterministic money math | Matcher only: same `order_ref`, same amount, ±24h. No LLM on amounts or posting |
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

Ground truth is planted by the generator and stored on `Match` / `Exception`. **It is never sent to the LLM.** Exception-type accuracy is strictly `predicted exception_type == ground_truth_type`.

### Unique-cause safety gate vs the 85.0% score

These are **two different metrics**. Mixing them is incorrect.

1. **Official AI type accuracy stays 85.0% (34/40)** on frozen run `27da232e-53a9-4122-abaf-57ed6e10d6a2`.
2. All six misses are planted `UNRESOLVABLE` cases that Gemini labeled `AMOUNT_MISMATCH` at confidence 0.95, status `AUTO_SUGGESTED`. Inspect `incorrect.csv`. This is a taxonomy collision (`AMOUNT_MISMATCH` is a parent class; those leftovers also have date conflict), not a random outage.
3. The unique-cause gate runs **after** policy and changes **status/routing only**. Independent evidence families: `AMOUNT`, `DATE`, `MISSING_SOURCE`, `DUPLICATE`. **BANK_FEE is a subtype of `AMOUNT`**, not its own family. **≥2 families → `UNRESOLVED`.**
4. The gate does **not** rewrite `exception_type`, `ai_verdict_correct`, or `exception_accuracy_pct`.
5. Read-only simulation (routing, not a new score): `artifacts/gate_simulation_27da232e.json` (`multi_family_blocked_from_auto_suggest`: 6). Future `python -m finpulse run` applies the gate; that run is **not** a replacement official score.

On the frozen baseline, policy `unresolved.csv` is empty because the model never set `insufficient_evidence` on those six. The gate simulation is what would block them from `AUTO_SUGGESTED`.

## Prerequisites

- Python **3.14** (developed and tested on Windows with 3.14; 3.11+ may work)
- Node.js (dashboard only)
- Optional: `GEMINI_API_KEY` for live investigation. **Not required** for matcher + dashboard demo
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

Put a Gemini key in `.env` only if you will call the LLM. Never commit `.env`.

Fixture CSVs are already in `fixtures/v1/` (seed 42). To regenerate:

```bash
python -m finpulse generate
```

## Path A — matcher + dashboard (no API key)

Enough for judges to see 116 matches, 40 leftovers, cash, inspection, approve/escalate, and exports.

```bash
python -m finpulse run --skip-llm
python -m pytest
python -m finpulse serve
```

API: `http://127.0.0.1:8000` (`/health` → `{"ok": true}`).

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173/** (use `localhost`, not `127.0.0.1:5173`, on Windows). Start the API **before** the dashboard. The Vite app proxies `/runs`, `/exceptions`, `/health`, and `/generate` to port 8000.

`--skip-llm` leaves exception-type accuracy as **Pending LLM** on the dashboard. That is expected. Cite **85.0%** from the frozen artifact folder below, not from this live run.

A new `python -m finpulse run` writes a **new** `artifacts/run_<uuid>/` folder. It does not overwrite `27da232e`.

## Path B — live LLM investigation (optional)

Needs `GEMINI_API_KEY`. Gemini free tier may 429 (per-model daily cap historically 20 requests). Failed calls are not cached (`investigated_at` stays empty) so you can resume:

```bash
python -m finpulse run
python -m finpulse investigate
```

Default model: `gemini-3.5-flash` (see `.env.example`). Concurrency default 2.

**This path is a live demo of investigation + gate routing. It does not replace the official 85.0%.**

Read-only gate simulation on the frozen leftovers:

```bash
python -m finpulse gate-sim
```

## Demo script (about 5 minutes)

1. Run Path A (`--skip-llm`, API, dashboard).
2. Show matcher cards: precision/recall 100%, 40 exceptions, cash split.
3. Click a leftover. Show the three source records side by side.
4. Approve or escalate. Show the new `APPROVE` / `ESCALATE` audit line.
5. Download Export JSON / CSV / Unresolved list.
6. Open frozen artifacts (**do not overwrite**):
   - `artifacts/run_27da232e-53a9-4122-abaf-57ed6e10d6a2/metrics.json` → `exception_accuracy_pct: 85.0`
   - `incorrect.csv` → six `UNRESOLVABLE` → `AMOUNT_MISMATCH`
7. Open `artifacts/gate_simulation_27da232e.json`. One sentence: those six would be routed `UNRESOLVED`; **type and 85% unchanged**.

### Screenshots / video checklist

Record 3–5 minutes. Do not show `.env` or API keys.

- Dashboard metric cards (matcher + cash)
- Exceptions table
- Detail drawer: 3-way records + audit
- After Approve: `RESOLVED` + `APPROVE` audit
- Frozen `incorrect.csv` (six misses)
- Frozen `metrics.json` (`85.0`)
- Optional: gate simulation header (`official_ai_exception_accuracy_pct: 85.0`, `multi_family_blocked_from_auto_suggest: 6`)

## Official scored run `27da232e-53a9-4122-abaf-57ed6e10d6a2`

Copied from that folder’s `metrics.json`. Not estimated.

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

**Throughput note:** matcher time is ~4 ms. The 2058 s wall clock is calendar time of the scored run, including Gemini free-tier 429s and two `finpulse investigate` resumes onto other Flash models. It is **not** a clean uninterrupted batch clock. Do not headline skip-LLM throughput (~thousands of records/sec) as the official figure.

Inspect: `incorrect.csv`, `exceptions.csv`, `recon_report.json` in the frozen run folder.

If other `artifacts/run_*` folders appear locally (matcher-only or verification runs), **ignore them for scoring**. Only `27da232e` is official.

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

## Known limitations

- Synthetic data, fixed seed 42. Match rate is only meaningful next to the planted mix.
- 3-way match requires exact amount equality; fees never auto-match.
- AI cannot close the books. `AUTO_SUGGESTED` still needs a human.
- Gemini free-tier per-model daily cap is 20 requests. The scored run used `gemini-3.6-flash`, then `gemini-flash-latest` (3.8), then `gemini-3.5-flash` to finish 40 leftovers.
- The model never classified `UNRESOLVABLE`; it called those six `AMOUNT_MISMATCH` instead.
- SQLite, local only. No live Razorpay APIs.
- Dashboard styling uses the Tailwind CDN (needs network).

## What broke (failure recovery)

- Pinned `pydantic==2.11.3` has no Python 3.14 Windows wheel; moved to 2.13.5 which ships `pydantic-core` cp314.
- `session_scope()` was a bare generator; wrapping it with `@contextmanager` unblocked the first real run.
- `gemini-2.5-flash` returns 404 for new API users; Google now requires `gemini-3.x-flash`.
- `gemini-3.6-flash` free tier is 20 requests/day; the first investigation wave stopped at 19 successes + 21 quota failures. Failures are not cached. `python -m finpulse investigate` resumed on other Flash models.
- `gemini-flash-latest` aliases `gemini-3.8-flash` (5 RPM / 20 RPD). Concurrency was dropped to 2 and RPM 429s wait for the advertised retry delay; daily-quota 429s do not wait.

## Pitch outline (5 minutes)

1. Problem: 3-way recon is still done by hand; one cherry-picked match proves nothing.
2. Demo matcher + dashboard, then open frozen `incorrect.csv` (the six UNRESOLVABLE misses).
3. Split: matcher has no LLM; LLM cannot touch amounts or post.
4. Three numbers: matcher 1.0/1.0, exception-type accuracy 85.0%, matcher ~4 ms vs **assumed** 120 min manual.
5. Unique-cause gate: routing safety for multi-family leftovers; **does not change 85.0%**.
6. One failure: free-tier quota exhausted mid-batch; we resumed instead of inventing accuracy.
