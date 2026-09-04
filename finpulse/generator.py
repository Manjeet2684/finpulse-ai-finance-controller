from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from random import Random

from finpulse.config import FIXTURE_DIR
from finpulse.enums import CURRENCY, ExceptionType, Source

SEED = 42
N_EXACT = 110
N_BANK_FEE = 8
N_DUPLICATE = 6
N_MISSING_BANK = 8
N_DATE_DRIFT = 6
N_AMOUNT_MISMATCH = 6
N_UNRESOLVABLE = 6

CSV_FIELDS = [
    "source",
    "source_txn_id",
    "order_ref",
    "amount",
    "currency",
    "txn_time",
    "status",
    "description",
]


def _amount(rng: Random) -> Decimal:
    rupees = rng.randint(5, 400) * 100
    paise = rng.choice([0, 0, 0, 50])
    return Decimal(f"{rupees}.{paise:02d}")


def _pay_id(rng: Random) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "pay_" + "".join(rng.choice(alphabet) for _ in range(14))


def _utr(rng: Random) -> str:
    return "UTR" + "".join(rng.choice("0123456789") for _ in range(12))


def _iso(ts: datetime) -> str:
    return ts.replace(microsecond=0).isoformat() + "Z"


def generate_fixture(out_dir: Path | None = None, seed: int = SEED) -> dict:
    rng = Random(seed)
    out_dir = out_dir or FIXTURE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    base = datetime(2026, 8, 1, 9, 0, 0)
    rows: list[dict] = []
    cases: list[dict] = []
    should_match: list[dict] = []
    exceptions: list[dict] = []
    seq = 1

    def order_ref() -> str:
        nonlocal seq
        ref = f"ORD-2026-{seq:04d}"
        seq += 1
        return ref

    def add_row(source: str, source_txn_id: str, ref: str, amount: Decimal, ts: datetime, status: str, desc: str) -> dict:
        row = {
            "source": source,
            "source_txn_id": source_txn_id,
            "order_ref": ref,
            "amount": f"{amount:.2f}",
            "currency": CURRENCY,
            "txn_time": _iso(ts),
            "status": status,
            "description": desc,
        }
        rows.append(row)
        return row

    def add_exact() -> None:
        ref = order_ref()
        amount = _amount(rng)
        t0 = base + timedelta(hours=seq * 2, minutes=rng.randint(0, 40))
        rp = add_row(
            Source.RAZORPAY,
            _pay_id(rng),
            ref,
            amount,
            t0,
            "captured",
            f"Razorpay payment captured for {ref}",
        )
        bk = add_row(
            Source.BANK,
            _utr(rng),
            ref,
            amount,
            t0 + timedelta(hours=rng.randint(1, 8)),
            "credited",
            f"NEFT credit settlement {ref}",
        )
        ld = add_row(
            Source.LEDGER,
            f"JE-2026-{seq:04d}-R",
            ref,
            amount,
            t0 + timedelta(minutes=rng.randint(15, 180)),
            "posted",
            f"Sales receipt posted {ref}",
        )
        cases.append({"case_id": ref, "kind": "EXACT_TRIPLE", "order_ref": ref, "should_match": True})
        should_match.append(
            {
                "order_ref": ref,
                "amount": f"{amount:.2f}",
                "razorpay_source_txn_id": rp["source_txn_id"],
                "bank_source_txn_id": bk["source_txn_id"],
                "ledger_source_txn_id": ld["source_txn_id"],
            }
        )

    def add_bank_fee() -> None:
        ref = order_ref()
        amount = _amount(rng)
        fee = (amount * Decimal("0.02")).quantize(Decimal("0.01"))
        if fee < Decimal("2.00"):
            fee = Decimal("2.00")
        bank_amount = amount - fee
        t0 = base + timedelta(days=2, hours=seq)
        add_row(Source.RAZORPAY, _pay_id(rng), ref, amount, t0, "captured", f"Payment captured {ref}")
        add_row(
            Source.BANK,
            _utr(rng),
            ref,
            bank_amount,
            t0 + timedelta(hours=4),
            "credited",
            f"Settlement net of MDR {fee:.2f} for {ref}",
        )
        add_row(
            Source.LEDGER,
            f"JE-2026-{seq:04d}-R",
            ref,
            amount,
            t0 + timedelta(hours=1),
            "posted",
            f"Gross sales receipt {ref}",
        )
        cases.append({"case_id": ref, "kind": ExceptionType.BANK_FEE, "order_ref": ref, "should_match": False})
        exceptions.append(
            {
                "order_ref": ref,
                "ground_truth_type": ExceptionType.BANK_FEE,
                "ground_truth_label": f"Bank credit is net of MDR {fee:.2f}; gross {amount:.2f} vs net {bank_amount:.2f}",
            }
        )

    def add_duplicate() -> None:
        ref = order_ref()
        amount = _amount(rng)
        t0 = base + timedelta(days=3, hours=seq)
        rp = add_row(Source.RAZORPAY, _pay_id(rng), ref, amount, t0, "captured", f"Payment captured {ref}")
        bk = add_row(
            Source.BANK,
            _utr(rng),
            ref,
            amount,
            t0 + timedelta(hours=2),
            "credited",
            f"Primary NEFT credit {ref}",
        )
        ld = add_row(
            Source.LEDGER,
            f"JE-2026-{seq:04d}-R",
            ref,
            amount,
            t0 + timedelta(hours=1),
            "posted",
            f"Sales receipt {ref}",
        )
        add_row(
            Source.BANK,
            _utr(rng),
            ref,
            amount,
            t0 + timedelta(hours=2, minutes=12),
            "credited",
            f"Duplicate bank posting {ref} — same order, second UTR",
        )
        cases.append({"case_id": ref, "kind": ExceptionType.DUPLICATE_RECORD, "order_ref": ref, "should_match": True})
        should_match.append(
            {
                "order_ref": ref,
                "amount": f"{amount:.2f}",
                "razorpay_source_txn_id": rp["source_txn_id"],
                "bank_source_txn_id": bk["source_txn_id"],
                "ledger_source_txn_id": ld["source_txn_id"],
            }
        )
        exceptions.append(
            {
                "order_ref": ref,
                "ground_truth_type": ExceptionType.DUPLICATE_RECORD,
                "ground_truth_label": f"Second bank UTR posted for {ref} after a valid triple already exists",
            }
        )

    def add_missing_bank() -> None:
        ref = order_ref()
        amount = _amount(rng)
        t0 = base + timedelta(days=4, hours=seq)
        add_row(Source.RAZORPAY, _pay_id(rng), ref, amount, t0, "captured", f"Payment captured {ref}")
        add_row(
            Source.LEDGER,
            f"JE-2026-{seq:04d}-R",
            ref,
            amount,
            t0 + timedelta(minutes=40),
            "posted",
            f"Sales receipt posted, bank not yet received {ref}",
        )
        cases.append(
            {"case_id": ref, "kind": ExceptionType.MISSING_BANK_RECEIPT, "order_ref": ref, "should_match": False}
        )
        exceptions.append(
            {
                "order_ref": ref,
                "ground_truth_type": ExceptionType.MISSING_BANK_RECEIPT,
                "ground_truth_label": f"Razorpay and ledger present for {ref}; no bank credit",
            }
        )

    def add_date_drift() -> None:
        ref = order_ref()
        amount = _amount(rng)
        t0 = base + timedelta(days=5, hours=seq)
        add_row(Source.RAZORPAY, _pay_id(rng), ref, amount, t0, "captured", f"Payment captured {ref}")
        add_row(
            Source.BANK,
            _utr(rng),
            ref,
            amount,
            t0 + timedelta(days=rng.randint(3, 6)),
            "credited",
            f"Delayed bank credit {ref} — outside 24h window",
        )
        add_row(
            Source.LEDGER,
            f"JE-2026-{seq:04d}-R",
            ref,
            amount,
            t0 + timedelta(hours=2),
            "posted",
            f"Sales receipt {ref}",
        )
        cases.append({"case_id": ref, "kind": ExceptionType.DATE_DRIFT, "order_ref": ref, "should_match": False})
        exceptions.append(
            {
                "order_ref": ref,
                "ground_truth_type": ExceptionType.DATE_DRIFT,
                "ground_truth_label": f"Same amount and order_ref for {ref} but bank timestamp is >24h from the other two",
            }
        )

    def add_amount_mismatch() -> None:
        ref = order_ref()
        amount = _amount(rng)
        delta = Decimal(rng.choice([500, 750, 1000, 1500]))
        ledger_amount = amount - delta if amount > delta + Decimal("100") else amount + delta
        t0 = base + timedelta(days=6, hours=seq)
        add_row(Source.RAZORPAY, _pay_id(rng), ref, amount, t0, "captured", f"Payment captured {ref}")
        add_row(
            Source.BANK,
            _utr(rng),
            ref,
            amount,
            t0 + timedelta(hours=3),
            "credited",
            f"Bank credit matches Razorpay for {ref}",
        )
        add_row(
            Source.LEDGER,
            f"JE-2026-{seq:04d}-R",
            ref,
            ledger_amount,
            t0 + timedelta(hours=1),
            "posted",
            f"Ledger booking {ledger_amount:.2f} does not match cash {amount:.2f} for {ref}",
        )
        cases.append({"case_id": ref, "kind": ExceptionType.AMOUNT_MISMATCH, "order_ref": ref, "should_match": False})
        exceptions.append(
            {
                "order_ref": ref,
                "ground_truth_type": ExceptionType.AMOUNT_MISMATCH,
                "ground_truth_label": f"Razorpay/bank {amount:.2f} vs ledger {ledger_amount:.2f} for {ref} — not an MDR pattern",
            }
        )

    def add_unresolvable() -> None:
        ref = order_ref()
        a = _amount(rng)
        b = a + Decimal(rng.choice([37, 83, 121]))
        c = a - Decimal(rng.choice([19, 41, 67]))
        if c <= 0:
            c = Decimal("11.00")
        t0 = base + timedelta(days=8, hours=seq)
        add_row(
            Source.RAZORPAY,
            _pay_id(rng),
            ref,
            a,
            t0,
            "captured",
            f"Captured {a:.2f} for {ref}; customer later disputed in-app",
        )
        add_row(
            Source.BANK,
            _utr(rng),
            ref,
            b,
            t0 + timedelta(days=2, hours=5),
            "credited",
            f"Unrelated-looking credit {b:.2f} tagged {ref} after a partial refund attempt",
        )
        add_row(
            Source.LEDGER,
            f"JE-2026-{seq:04d}-R",
            ref,
            c,
            t0 + timedelta(days=1, hours=11),
            "posted",
            f"Ledger {c:.2f} for {ref} with contra note: split across another invoice",
        )
        cases.append({"case_id": ref, "kind": ExceptionType.UNRESOLVABLE, "order_ref": ref, "should_match": False})
        exceptions.append(
            {
                "order_ref": ref,
                "ground_truth_type": ExceptionType.UNRESOLVABLE,
                "ground_truth_label": f"Three conflicting amounts and dates for {ref} ({a:.2f}/{b:.2f}/{c:.2f}); not a single fee, duplicate, or booking miss",
            }
        )

    for _ in range(N_EXACT):
        add_exact()
    for _ in range(N_BANK_FEE):
        add_bank_fee()
    for _ in range(N_DUPLICATE):
        add_duplicate()
    for _ in range(N_MISSING_BANK):
        add_missing_bank()
    for _ in range(N_DATE_DRIFT):
        add_date_drift()
    for _ in range(N_AMOUNT_MISMATCH):
        add_amount_mismatch()
    for _ in range(N_UNRESOLVABLE):
        add_unresolvable()

    by_source = {Source.RAZORPAY: [], Source.BANK: [], Source.LEDGER: []}
    for row in rows:
        by_source[row["source"]].append(row)

    def write_csv(path: Path, data: list[dict]) -> None:
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(data)

    write_csv(out_dir / "razorpay.csv", by_source[Source.RAZORPAY])
    write_csv(out_dir / "bank.csv", by_source[Source.BANK])
    write_csv(out_dir / "ledger.csv", by_source[Source.LEDGER])

    with (out_dir / "ground_truth.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["case_id", "kind", "order_ref", "should_match"])
        writer.writeheader()
        writer.writerows(cases)

    answer_key = {
        "seed": seed,
        "canonical_cases": len(cases),
        "physical_rows": len(rows),
        "row_counts": {k: len(v) for k, v in by_source.items()},
        "planted_should_match": len(should_match),
        "planted_exceptions": len(exceptions),
        "exception_type_counts": {
            t.value: sum(1 for e in exceptions if e["ground_truth_type"] == t) for t in ExceptionType
        },
        "should_match": should_match,
        "exceptions": exceptions,
        "cases": cases,
    }
    (out_dir / "answer_key.json").write_text(json.dumps(answer_key, indent=2), encoding="utf-8")
    return answer_key
