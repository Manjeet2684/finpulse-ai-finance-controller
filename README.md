# FINPULSE AI — Razorpay Buildathon Track 04

3-way reconciliation controller (Razorpay × Bank × Ledger).

**Metrics in this README are written only after a scored run.** Gate A currently
produces matcher counts, matcher precision/recall, and a cash position from
fixture data. Exception-type accuracy and end-to-end throughput including LLM
investigation are filled in later gates from `artifacts/`.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m finpulse generate
python -m finpulse run
python -m pytest
```

Do not put API keys in the repo. Copy `.env.example` to `.env`.
