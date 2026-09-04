from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class TxnView:
    id: int
    source: str
    source_txn_id: str
    order_ref: str
    amount: Decimal
    currency: str
    txn_time: datetime
    status: str
    description: str


@dataclass(frozen=True)
class Triple:
    razorpay: TxnView
    bank: TxnView
    ledger: TxnView
    match_rule: str


@dataclass(frozen=True)
class ExceptionGroup:
    order_ref: str
    related: tuple[TxnView, ...]
    detected_reason: str


def quantize(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"))


def within_window(a: datetime, b: datetime, hours: int) -> bool:
    return abs((a - b).total_seconds()) <= hours * 3600


def triple_in_window(r: TxnView, b: TxnView, l: TxnView, hours: int) -> bool:
    return (
        within_window(r.txn_time, b.txn_time, hours)
        and within_window(r.txn_time, l.txn_time, hours)
        and within_window(b.txn_time, l.txn_time, hours)
    )


def amounts_equal(r: TxnView, b: TxnView, l: TxnView) -> bool:
    return quantize(r.amount) == quantize(b.amount) == quantize(l.amount)


def _window_span_seconds(r: TxnView, b: TxnView, l: TxnView) -> float:
    times = (r.txn_time, b.txn_time, l.txn_time)
    return (max(times) - min(times)).total_seconds()


def find_triples(txns: list[TxnView], window_hours: int, match_rule: str) -> list[Triple]:
    by_order: dict[str, list[TxnView]] = {}
    for txn in txns:
        by_order.setdefault(txn.order_ref, []).append(txn)

    matches: list[Triple] = []
    for _order_ref, group in sorted(by_order.items()):
        rp = [t for t in group if t.source == "RAZORPAY"]
        bk = [t for t in group if t.source == "BANK"]
        ld = [t for t in group if t.source == "LEDGER"]
        candidates: list[tuple[float, str, str, str, TxnView, TxnView, TxnView]] = []
        for r in rp:
            for b in bk:
                for l in ld:
                    if not amounts_equal(r, b, l):
                        continue
                    if not triple_in_window(r, b, l, window_hours):
                        continue
                    span = _window_span_seconds(r, b, l)
                    candidates.append(
                        (span, r.source_txn_id, b.source_txn_id, l.source_txn_id, r, b, l)
                    )
        candidates.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
        used: set[int] = set()
        for _span, _rid, _bid, _lid, r, b, l in candidates:
            if r.id in used or b.id in used or l.id in used:
                continue
            used.update((r.id, b.id, l.id))
            matches.append(Triple(razorpay=r, bank=b, ledger=l, match_rule=match_rule))
    return matches


def leftover_groups(txns: list[TxnView], triples: list[Triple]) -> list[ExceptionGroup]:
    matched_ids = set()
    for triple in triples:
        matched_ids.update((triple.razorpay.id, triple.bank.id, triple.ledger.id))
    leftovers = [t for t in txns if t.id not in matched_ids]
    by_order: dict[str, list[TxnView]] = {}
    for txn in leftovers:
        by_order.setdefault(txn.order_ref, []).append(txn)

    groups: list[ExceptionGroup] = []
    for order_ref, group in sorted(by_order.items()):
        related = tuple(sorted(group, key=lambda t: (t.source, t.source_txn_id)))
        groups.append(
            ExceptionGroup(
                order_ref=order_ref,
                related=related,
                detected_reason="NO_TRIPLE_MATCH",
            )
        )
    return groups
