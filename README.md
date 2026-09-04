# FINPULSE AI — Razorpay Buildathon Track 04

3-way reconciliation controller: Razorpay × Bank × Ledger.

The agent closes **one** finance-ops loop on a seeded batch of **150 canonical cases** (448 physical CSV rows). It auto-matches exact triples, investigates leftovers, and writes an inspectable exception list. It does not forecast cash. It does report a post-recon **cash position**.

## The loop

1. Ingest three source CSVs.
2. Deterministic matcher posts triples with the same `order_ref`, the same amount, and timestamps within **±24 hours**. No LLM is involved.
3. Leftovers become exceptions. `investigate()` (OpenAI) classifies `exception_type` and explains. AI never posts, never does money math, never auto-approves.
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
copy .env.example .env   # add OPENAI_API_KEY
python -m finpulse generate
python -m finpulse run          # matcher + LLM + score + artifacts
python -m finpulse run --skip-llm   # matcher only, if you have no key yet
python -m pytest
python -m finpulse serve        # API on :8000
```

Dashboard:

```bash
cd frontend
npm install
npm run dev                     # :5173, proxies to the API
```

## Measured numbers (matcher-only run `595dff23-303a-450b-9990-2f14feecb852`)

Copied from `artifacts/run_595dff23-303a-450b-9990-2f14feecb852/metrics.json`. Not estimated.

| Metric | Value |
|---|---|
| Canonical cases | 150 |
| Physical rows | 448 (Razorpay 150, Bank 148, Ledger 150) |
| Matcher precision | 1.0 |
| Matcher recall | 1.0 |
| Matches created | 116 / 116 planted |
| Traps correctly refused | 34 / 34 |
| Exceptions created | 40 (8 BANK_FEE, 6 DUPLICATE, 8 MISSING_BANK, 6 DATE_DRIFT, 6 AMOUNT_MISMATCH, 6 UNRESOLVABLE) |
| Match wall time | 4.37 ms |
| Ingest+match throughput | 2329.88 records/sec (matcher-only; LLM not in this run) |
| Cash matched | ₹22,15,116.50 |
| Cash in transit | ₹1,86,001.00 |
| Cash exceptional | ₹5,24,903.00 |
| Manual baseline | **ASSUMED** 120 minutes (3 min × 40 exceptions) — not measured |
| Exception-type accuracy | **null — LLM not run; no key in this environment** |

Inspect: `artifacts/run_595dff23-303a-450b-9990-2f14feecb852/unresolved.csv` and `recon_report.json`.

After you add `OPENAI_API_KEY` and re-run without `--skip-llm`, `exception_accuracy_pct`, `investigate_ms`, and end-to-end records/sec will be overwritten from that run. Do not hand-edit this table.

## How AI is used

- Only through `finpulse/investigate.py` → `investigate()`.
- Input: leftover records plus other rows on the same `order_ref`. No ground-truth fields.
- Output: `exception_type` enum, explanation, confidence, recommended action, `insufficient_evidence`.
- One extra call if confidence &lt; 0.6. Cached after `investigated_at` is set.
- Concurrency capped at 5.
- Failed calls become `UNRESOLVED`, not scored as correct.

## Known limitations

- Synthetic data, fixed seed 42. Match rate is only meaningful next to the planted mix above.
- 3-way match requires exact amount equality; fees never auto-match.
- AI cannot close the books. AUTO_SUGGESTED still needs a human.
- End-to-end throughput including LLM is missing until a keyed run.
- SQLite, local only. No live Razorpay APIs.

## What broke (Failure Recovery)

- Pinned `pydantic==2.11.3` has no Python 3.14 Windows wheel; moved to 2.13.5 which ships `pydantic-core` cp314.
- `session_scope()` was a bare generator; wrapping it with `@contextmanager` unblocked the first real run.
- No `OPENAI_API_KEY` in this environment, so Gate B/C LLM scoring is implemented but not executed. Matcher artifacts were still written rather than faking an accuracy number.

## Pitch outline (5 minutes)

1. Problem: 3-way recon is still done by hand; one cherry-picked match proves nothing.
2. Demo the command and open `unresolved.csv`.
3. Split: matcher has no LLM; LLM cannot touch amounts or post.
4. Three numbers: matcher precision/recall, exception-type accuracy (after keyed run), records/min.
5. One failure: unresolvable case + missing API key handled without inventing metrics.
