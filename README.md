# FINPULSE AI — Razorpay Buildathon Track 04

3-way reconciliation controller: Razorpay × Bank × Ledger.

The agent closes **one** finance-ops loop on a seeded batch of **150 canonical cases** (448 physical CSV rows). It auto-matches exact triples, investigates leftovers, and writes an inspectable exception list. It does not forecast cash. It does report a post-recon **cash position**.

## The loop

1. Ingest three source CSVs.
2. Deterministic matcher posts triples with the same `order_ref`, the same amount, and timestamps within **±24 hours**. No LLM is involved.
3. Leftovers become exceptions. `investigate()` (Gemini via the OpenAI-compatible endpoint) classifies `exception_type` and explains. AI never posts, never does money math, never auto-approves.
4. A human approves or escalates.
5. One scored run writes `artifacts/run_<id>/`.

## Architecture

```
CSV fixtures → SQLite
                ├─ matcher (order_ref + amount + ±24h)
                ├─ investigate()  ← only LLM seam
                ├─ policy gate (0.6 retry, 0.85 AUTO_SUGGESTED, UNRESOLVABLE → UNRESOLVED)
                └─ artifacts/ + dashboard
```

Five tables: `Transaction`, `Match`, `Exception`, `AuditEvent`, `RunMetrics`.

Ground truth is planted by the generator, stored on `Match` / `Exception`, **never sent to the LLM**. Exception accuracy is strictly `predicted exception_type == ground_truth_type`.

## How to run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # add GEMINI_API_KEY
python -m finpulse generate
python -m finpulse run          # matcher + Gemini + score + artifacts
python -m finpulse investigate  # resume failed LLM calls without re-ingesting
python -m finpulse run --skip-llm   # matcher only
python -m pytest
python -m finpulse serve        # API on :8000
```

Dashboard:

```bash
cd frontend
npm install
npm run dev                     # :5173, proxies to the API
```

## Measured numbers (scored run `27da232e-53a9-4122-abaf-57ed6e10d6a2`)

Copied from `artifacts/run_27da232e-53a9-4122-abaf-57ed6e10d6a2/metrics.json`. Not estimated.

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

**Accuracy breakdown:** 8/8 BANK_FEE, 6/6 DUPLICATE_RECORD, 8/8 MISSING_BANK_RECEIPT, 6/6 DATE_DRIFT, 6/6 AMOUNT_MISMATCH, **0/6 UNRESOLVABLE**. All six misses are `UNRESOLVABLE → AMOUNT_MISMATCH` (high-confidence). Inspect `incorrect.csv`. Policy `unresolved.csv` is empty because the model never set `insufficient_evidence` on those six.

**Throughput note:** matcher time is 4 ms. The 2058 s wall clock is calendar time of this scored run, including Gemini free-tier 429s (20 requests/day per model) and two `finpulse investigate` resumes onto other Flash models. It is not a clean uninterrupted batch clock.

Inspect: `artifacts/run_27da232e-53a9-4122-abaf-57ed6e10d6a2/incorrect.csv`, `exceptions.csv`, `recon_report.json`.

## How AI is used

- Only through `finpulse/investigate.py` → `investigate()`.
- Provider: Gemini free tier, OpenAI SDK pointed at `https://generativelanguage.googleapis.com/v1beta/openai/`. Default model `gemini-3.5-flash`.
- Input: leftover records plus other rows on the same `order_ref`. No ground-truth fields.
- Output: `exception_type` enum, explanation, confidence, recommended action, `insufficient_evidence`.
- One extra classification call if confidence &lt; 0.6. Successful calls are cached (`investigated_at`). Failed quota calls are not cached.
- Concurrency default 2 (Gemini free RPM is 5).
- Failed calls stay `UNRESOLVED` and are scored as incorrect until retried.

## Known limitations

- Synthetic data, fixed seed 42. Match rate is only meaningful next to the planted mix.
- 3-way match requires exact amount equality; fees never auto-match.
- AI cannot close the books. AUTO_SUGGESTED still needs a human.
- Gemini free-tier per-model daily cap is 20 requests. This scored run used `gemini-3.6-flash`, then `gemini-flash-latest` (3.8), then `gemini-3.5-flash` to finish 40 leftovers.
- The model never classified `UNRESOLVABLE`; it called those six `AMOUNT_MISMATCH` instead.
- SQLite, local only. No live Razorpay APIs.

## What broke (Failure Recovery)

- Pinned `pydantic==2.11.3` has no Python 3.14 Windows wheel; moved to 2.13.5 which ships `pydantic-core` cp314.
- `session_scope()` was a bare generator; wrapping it with `@contextmanager` unblocked the first real run.
- `gemini-2.5-flash` returns 404 for new API users; Google now requires `gemini-3.x-flash`.
- `gemini-3.6-flash` free tier is 20 requests/day; the first investigation wave stopped at 19 successes + 21 quota failures. Failures are not cached. `python -m finpulse investigate` resumed on other Flash models.
- `gemini-flash-latest` aliases `gemini-3.8-flash` (5 RPM / 20 RPD). Concurrency was dropped to 2 and RPM 429s wait for the advertised retry delay; daily-quota 429s do not wait.

## Pitch outline (5 minutes)

1. Problem: 3-way recon is still done by hand; one cherry-picked match proves nothing.
2. Demo the command and open `incorrect.csv` (the six UNRESOLVABLE misses).
3. Split: matcher has no LLM; LLM cannot touch amounts or post.
4. Three numbers: matcher 1.0/1.0, exception-type accuracy 85.0%, matcher 4 ms vs assumed 120 min manual.
5. One failure: free-tier quota exhausted mid-batch; we resumed instead of inventing accuracy.
