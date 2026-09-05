import { useEffect, useMemo, useState } from "react";

function inr(value) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(n);
}

function pct(value) {
  if (value == null) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function num(value, digits = 2) {
  if (value == null) return "—";
  return Number(value).toFixed(digits);
}

function shortRunId(runId) {
  if (!runId) return "—";
  return runId.length > 12 ? `${runId.slice(0, 8)}…` : runId;
}

function statusBadgeClass(status) {
  switch (status) {
    case "UNRESOLVED":
      return "bg-red-950 text-red-200 ring-1 ring-red-800";
    case "NEEDS_REVIEW":
      return "bg-amber-950 text-amber-200 ring-1 ring-amber-800";
    case "AUTO_SUGGESTED":
      return "bg-sky-950 text-sky-200 ring-1 ring-sky-800";
    case "RESOLVED":
      return "bg-emerald-950 text-emerald-200 ring-1 ring-emerald-800";
    default:
      return "bg-slate-800 text-slate-300 ring-1 ring-slate-700";
  }
}

function typeBadgeClass(type) {
  if (!type) return "bg-slate-800 text-slate-400 ring-1 ring-slate-700";
  switch (type) {
    case "UNRESOLVABLE":
      return "bg-red-950 text-red-200 ring-1 ring-red-800";
    case "AMOUNT_MISMATCH":
    case "BANK_FEE":
      return "bg-violet-950 text-violet-200 ring-1 ring-violet-800";
    case "DATE_DRIFT":
      return "bg-orange-950 text-orange-200 ring-1 ring-orange-800";
    case "MISSING_BANK_RECEIPT":
      return "bg-amber-950 text-amber-100 ring-1 ring-amber-800";
    case "DUPLICATE_RECORD":
      return "bg-indigo-950 text-indigo-200 ring-1 ring-indigo-800";
    default:
      return "bg-slate-800 text-slate-300 ring-1 ring-slate-700";
  }
}

function Badge({ value, kind }) {
  const cls = kind === "status" ? statusBadgeClass(value) : typeBadgeClass(value);
  return (
    <span className={`inline-flex max-w-full truncate rounded-md px-1.5 py-0.5 text-[11px] font-medium ${cls}`}>
      {value || "—"}
    </span>
  );
}

function Card({ label, value, hint, emphasize = false }) {
  return (
    <div
      className={`rounded-xl border p-4 ${
        emphasize ? "border-slate-600 bg-slate-900" : "border-slate-800 bg-slate-900/80"
      }`}
    >
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-2 font-semibold tracking-tight text-white ${emphasize ? "text-2xl" : "text-xl"}`}>
        {value}
      </div>
      {hint ? <div className="mt-1.5 text-xs leading-snug text-slate-500">{hint}</div> : null}
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="h-3 w-24 rounded bg-slate-800" />
      <div className="mt-3 h-7 w-32 rounded bg-slate-800" />
      <div className="mt-2 h-3 w-40 rounded bg-slate-800" />
    </div>
  );
}

const SOURCE_COLUMNS = ["RAZORPAY", "BANK", "LEDGER"];
const DAY_MS = 24 * 60 * 60 * 1000;
const STATUS_FILTERS = ["AUTO_SUGGESTED", "NEEDS_REVIEW", "UNRESOLVED", "RESOLVED"];

function rowMatchesSearch(row, query) {
  if (!query) return true;
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const fields = [String(row.id), row.status, row.exception_type, row.ground_truth_type];
  return fields.some((value) => value != null && String(value).toLowerCase().includes(q));
}

function groupRecordsBySource(records) {
  const grouped = { RAZORPAY: [], BANK: [], LEDGER: [] };
  for (const rec of records || []) {
    if (grouped[rec.source]) grouped[rec.source].push(rec);
  }
  return grouped;
}

function parseTxnTime(value) {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

function formatTxnTime(value) {
  const ms = parseTxnTime(value);
  if (ms == null) return value || "—";
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(ms));
}

function presentAmountsDiffer(grouped) {
  const amounts = new Set();
  for (const source of SOURCE_COLUMNS) {
    for (const rec of grouped[source]) {
      if (rec.amount != null && rec.amount !== "") amounts.add(String(rec.amount));
    }
  }
  return amounts.size > 1;
}

function datesSpanOver24h(grouped) {
  const times = [];
  for (const source of SOURCE_COLUMNS) {
    for (const rec of grouped[source]) {
      const ms = parseTxnTime(rec.txn_time);
      if (ms != null) times.push(ms);
    }
  }
  if (times.length < 2) return false;
  return Math.max(...times) - Math.min(...times) > DAY_MS;
}

function ConfidenceBlock({ confidence }) {
  if (confidence == null) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
        <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Confidence</div>
        <div className="mt-1 text-sm text-slate-300">Not investigated</div>
      </div>
    );
  }
  const pctValue = Math.max(0, Math.min(1, Number(confidence))) * 100;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
      <div className="flex items-center justify-between text-[11px] font-medium uppercase tracking-wide text-slate-500">
        <span>Confidence</span>
        <span className="tabular-nums text-slate-300">{num(confidence, 2)}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div className="h-full rounded-full bg-amber-400" style={{ width: `${pctValue}%` }} />
      </div>
    </div>
  );
}

function RecordCard({ rec, leftover, highlightAmount, highlightDate }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-2 text-[11px]">
      <div className="flex flex-wrap items-center justify-between gap-1">
        <span className="font-mono text-slate-200">{rec.source_txn_id}</span>
        <span
          className={`rounded px-1 py-px text-[10px] font-medium ${
            leftover ? "bg-amber-950 text-amber-200 ring-1 ring-amber-800" : "bg-slate-800 text-slate-400"
          }`}
        >
          {leftover ? "Leftover" : "On-order context"}
        </span>
      </div>
      <div className={`mt-1.5 tabular-nums ${highlightAmount ? "rounded bg-violet-950/80 px-1 font-semibold text-violet-100" : "text-slate-100"}`}>
        {inr(rec.amount)}
      </div>
      <div className={`mt-0.5 ${highlightDate ? "rounded bg-orange-950/80 px-1 text-orange-100" : "text-slate-400"}`}>
        {formatTxnTime(rec.txn_time)}
      </div>
      {rec.description ? <div className="mt-1 line-clamp-3 text-slate-500">{rec.description}</div> : null}
    </div>
  );
}

function ThreeWayCompare({ records, relatedTxnIds }) {
  const grouped = groupRecordsBySource(records);
  const leftoverIds = new Set((relatedTxnIds || []).map((id) => Number(id)));
  const highlightAmount = presentAmountsDiffer(grouped);
  const highlightDate = datesSpanOver24h(grouped);
  const orderRef = (records || []).find((r) => r.order_ref)?.order_ref;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-slate-500">3-way comparison</h3>
        {orderRef ? <span className="font-mono text-[11px] text-slate-400">{orderRef}</span> : null}
      </div>
      {(highlightAmount || highlightDate) ? (
        <p className="mb-2 text-[11px] text-slate-500">
          Highlighted values differ across present records
          {highlightDate ? " (timestamps more than 24h apart)" : ""}
          {highlightAmount ? " (amounts not identical)" : ""}. Visual hint only — not a safety-gate decision.
        </p>
      ) : null}
      <div className="grid min-w-0 grid-cols-3 gap-2 overflow-x-auto">
        {SOURCE_COLUMNS.map((source) => {
          const rows = grouped[source];
          return (
            <div key={source} className="min-w-[7.5rem] space-y-2">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{source}</div>
              {rows.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-700 px-2 py-4 text-center text-[11px] text-slate-500">
                  No {source} record
                </div>
              ) : (
                rows.map((rec) => (
                  <RecordCard
                    key={rec.id}
                    rec={rec}
                    leftover={leftoverIds.has(Number(rec.id))}
                    highlightAmount={highlightAmount}
                    highlightDate={highlightDate}
                  />
                ))
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const RUN_AUDIT_ACTIONS = new Set(["INGEST", "MATCH"]);
const EXCEPTION_AUDIT_ACTIONS = new Set(["INVESTIGATE", "APPROVE", "ESCALATE"]);

function parseAuditState(raw) {
  if (!raw || typeof raw !== "string") return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function statusTransition(event) {
  const before = parseAuditState(event.before_state);
  const after = parseAuditState(event.after_state);
  if (!before || !after || before.status == null || after.status == null) return null;
  if (before.status === after.status) return null;
  return `${before.status} → ${after.status}`;
}

function formatAuditTime(value) {
  const ms = Date.parse(value);
  if (Number.isNaN(ms)) return value || "—";
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(ms));
}

function AuditEventLine({ event }) {
  const transition = statusTransition(event);
  return (
    <li className="text-xs text-slate-300">
      <div>
        <span className="text-slate-500">{formatAuditTime(event.event_time)}</span>
        {" · "}
        <span className="text-slate-400">{event.actor_type}</span>
        {" · "}
        <span className="font-medium text-slate-200">{event.action}</span>
        {event.reason ? <span className="text-slate-500"> — {event.reason}</span> : null}
      </div>
      {transition ? <div className="mt-0.5 text-[11px] text-slate-500">{transition}</div> : null}
    </li>
  );
}

function AuditTimeline({ events }) {
  const rows = events || [];
  const shared = rows.filter((e) => RUN_AUDIT_ACTIONS.has(e.action));
  const own = rows.filter((e) => EXCEPTION_AUDIT_ACTIONS.has(e.action));
  return (
    <div>
      <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">Audit</h3>
      {shared.length > 0 ? (
        <div className="mb-3 rounded-lg border border-slate-800 bg-slate-950/40 px-2.5 py-2">
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-600">
            Shared run events — not specific to this leftover
          </div>
          <ul className="space-y-1.5">
            {shared.map((event, i) => (
              <AuditEventLine key={`run-${i}`} event={event} />
            ))}
          </ul>
        </div>
      ) : null}
      <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">This leftover</div>
      {own.length > 0 ? (
        <ul className="space-y-1.5">
          {own.map((event, i) => (
            <AuditEventLine key={`ex-${i}`} event={event} />
          ))}
        </ul>
      ) : (
        <p className="text-xs text-slate-500">No investigate or review events on this leftover yet.</p>
      )}
    </div>
  );
}

function exportHref(fmt, runId) {
  return `/exceptions/export?fmt=${encodeURIComponent(fmt)}&run_id=${encodeURIComponent(runId)}`;
}

export default function App() {
  const [metrics, setMetrics] = useState(null);
  const [exceptions, setExceptions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [reviewer, setReviewer] = useState("controller");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [apiOk, setApiOk] = useState(null);

  function showToast(kind, text) {
    setToast({ kind, text });
    window.setTimeout(() => setToast(null), 4000);
  }

  async function load({ silent = false } = {}) {
    if (!silent) {
      setLoading(true);
      setError("");
    }
    try {
      const latest = await fetch("/runs/latest");
      if (!latest.ok) {
        setMetrics(null);
        setExceptions([]);
        throw new Error("No reconciliation run yet. Start the API and run: python -m finpulse run --skip-llm");
      }
      const m = await latest.json();
      const listRes = await fetch(`/exceptions?run_id=${m.run_id}`);
      if (!listRes.ok) throw new Error("Failed to load exceptions for this run.");
      const rows = await listRes.json();
      setMetrics(m);
      setExceptions(rows);
    } catch (err) {
      setError(err.message);
      if (!silent) {
        setMetrics(null);
        setExceptions([]);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/health")
      .then((r) => {
        if (!cancelled) setApiOk(r.ok);
      })
      .catch(() => {
        if (!cancelled) setApiOk(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    fetch(`/exceptions/${selectedId}`)
      .then(async (r) => {
        if (!r.ok) throw new Error("Could not load exception detail.");
        return r.json();
      })
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setDetail(null);
          setError(err.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const openCount = useMemo(
    () => exceptions.filter((e) => e.status === "UNRESOLVED" || (e.status === "NEEDS_REVIEW" && !e.reviewed_at)).length,
    [exceptions]
  );

  const typeOptions = useMemo(() => {
    const types = new Set();
    for (const row of exceptions) {
      if (row.exception_type) types.add(row.exception_type);
      if (row.ground_truth_type) types.add(row.ground_truth_type);
    }
    return [...types].sort();
  }, [exceptions]);

  const filteredExceptions = useMemo(() => {
    return exceptions.filter((row) => {
      if (!rowMatchesSearch(row, search)) return false;
      if (statusFilter && row.status !== statusFilter) return false;
      if (typeFilter && row.exception_type !== typeFilter && row.ground_truth_type !== typeFilter) return false;
      return true;
    });
  }, [exceptions, search, statusFilter, typeFilter]);

  const filtersActive = Boolean(search.trim() || statusFilter || typeFilter);

  useEffect(() => {
    if (selectedId == null) return;
    if (!filteredExceptions.some((row) => row.id === selectedId)) {
      setSelectedId(null);
    }
  }, [filteredExceptions, selectedId]);

  async function act(id, action) {
    const current = exceptions.find((e) => e.id === id);
    if (action === "approve" && current?.status === "RESOLVED") {
      showToast("error", "This exception is already resolved.");
      return;
    }
    if (action === "escalate") {
      const ok = window.confirm("Escalate this exception to UNRESOLVED? This is recorded on the audit trail.");
      if (!ok) return;
    }

    setBusy(true);
    setError("");
    try {
      const res = await fetch(`/exceptions/${id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reviewer,
          reason: action === "escalate" ? "Escalated from dashboard" : "",
        }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `Request failed (${res.status})`);
      }
      await load({ silent: true });
      const fresh = await fetch(`/exceptions/${id}`);
      if (!fresh.ok) throw new Error("Updated, but failed to refresh exception detail.");
      setDetail(await fresh.json());
      showToast("success", action === "approve" ? "Exception approved and marked resolved." : "Exception escalated.");
    } catch (err) {
      const message = err.message || "Action failed.";
      setError(message);
      showToast("error", message);
    } finally {
      setBusy(false);
    }
  }

  const selectedStatus = detail?.exception?.status;
  const alreadyResolved = selectedStatus === "RESOLVED";
  const accuracyPending = metrics != null && metrics.exception_accuracy_pct == null;
  const selectedIndex = filteredExceptions.findIndex((row) => row.id === selectedId);
  const canPrev = selectedIndex > 0;
  const canNext = selectedIndex >= 0 && selectedIndex < filteredExceptions.length - 1;

  function clearFilters() {
    setSearch("");
    setStatusFilter("");
    setTypeFilter("");
  }

  return (
    <div className="min-h-screen">
      {toast ? (
        <div
          className={`fixed right-4 top-4 z-50 max-w-sm rounded-lg border px-4 py-3 text-sm shadow-lg ${
            toast.kind === "success"
              ? "border-emerald-800 bg-emerald-950 text-emerald-100"
              : "border-red-800 bg-red-950 text-red-100"
          }`}
        >
          {toast.text}
        </div>
      ) : null}

      <div className="mx-auto max-w-7xl px-6 py-7">
        <header className="mb-6 flex flex-wrap items-start justify-between gap-4 border-b border-slate-800 pb-6">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-400">FINPULSE</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-white">AI Reconciliation Control Center</h1>
            <p className="mt-1 max-w-xl text-sm text-slate-400">
              Monitor reconciliation, investigate exceptions, and keep human approval in control. Razorpay × Bank ×
              Ledger.
            </p>
            {apiOk === true ? (
              <p className="mt-2 text-xs text-emerald-400">● API Connected</p>
            ) : apiOk === false ? (
              <p className="mt-2 text-xs text-red-400">● API Unavailable</p>
            ) : (
              <p className="mt-2 text-xs text-slate-500">● Checking API…</p>
            )}
          </div>
          <div className="flex flex-col items-stretch gap-2 sm:items-end">
            <div className="flex flex-wrap gap-2">
              {metrics?.run_id ? (
                <>
                  <a className="rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-100 hover:bg-slate-700" href={exportHref("json", metrics.run_id)}>
                    Export JSON
                  </a>
                  <a className="rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-100 hover:bg-slate-700" href={exportHref("csv", metrics.run_id)}>
                    Export CSV
                  </a>
                  <a
                    className="rounded-lg bg-amber-500 px-3 py-2 text-sm font-medium text-slate-950 hover:bg-amber-400"
                    href={exportHref("unresolved", metrics.run_id)}
                  >
                    Unresolved list
                  </a>
                </>
              ) : (
                <>
                  <span className="cursor-not-allowed rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-500">Export JSON</span>
                  <span className="cursor-not-allowed rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-500">Export CSV</span>
                  <span className="cursor-not-allowed rounded-lg bg-slate-800/80 px-3 py-2 text-sm text-slate-500">Unresolved list</span>
                </>
              )}
            </div>
            {metrics?.run_id ? (
              <p className="text-xs text-slate-500" title={metrics.run_id}>
                Current run <span className="font-mono text-slate-300">{shortRunId(metrics.run_id)}</span>
                {metrics.records_processed != null ? ` · ${metrics.records_processed} rows` : ""}
                {metrics.exceptions_created != null ? ` · ${metrics.exceptions_created} leftovers` : ""}
              </p>
            ) : null}
          </div>
        </header>

        {error ? (
          <div className="mb-5 rounded-lg border border-red-800 bg-red-950/80 px-4 py-3 text-sm text-red-100">{error}</div>
        ) : null}

        {loading ? (
          <>
            <section className="mb-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </section>
            <section className="mb-6 grid gap-3 md:grid-cols-3">
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </section>
          </>
        ) : !metrics ? (
          <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/50 px-6 py-12 text-center">
            <p className="text-sm font-medium text-slate-200">No reconciliation run loaded</p>
            <p className="mt-2 text-sm text-slate-500">
              Start the API, then run <code className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-300">python -m finpulse run --skip-llm</code>{" "}
              and refresh.
            </p>
          </div>
        ) : (
          <>
            <section className="mb-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
              <Card
                emphasize
                label="Matcher precision / recall"
                value={`${pct(metrics.matcher_precision)} / ${pct(metrics.matcher_recall)}`}
                hint="Vs planted match key — not LLM confidence"
              />
              <Card
                emphasize
                label="Open exceptions"
                value={String(openCount)}
                hint={`${metrics.exceptions_created ?? exceptions.length} leftovers on this run`}
              />
              <Card
                label="Match time"
                value={metrics.match_ms == null ? "—" : `${num(metrics.match_ms, 2)} ms`}
                hint="Deterministic matcher wall time for this run"
              />
              <Card
                label="Exception-type accuracy"
                value={accuracyPending ? "Pending LLM" : `${num(metrics.exception_accuracy_pct, 1)}%`}
                hint={
                  accuracyPending
                    ? "This SQLite run has not been investigated yet. Official scored accuracy is only in the frozen artifact folder — not shown here."
                    : "predicted exception_type == ground_truth_type for this run"
                }
              />
            </section>

            <section className="mb-6 grid gap-3 md:grid-cols-3">
              <Card
                emphasize
                label="Cash matched / settled"
                value={inr(metrics.cash_matched_amount)}
                hint="Sum of auto-matched Razorpay amounts"
              />
              <Card label="Cash in transit" value={inr(metrics.cash_in_transit_amount)} hint="Missing bank receipt leftovers" />
              <Card label="Cash exceptional" value={inr(metrics.cash_exception_amount)} hint="Other unmatched amounts" />
            </section>

            {metrics.manual_baseline_minutes_assumed != null ? (
              <p className="mb-6 text-xs text-slate-500">
                Assumed manual baseline: {num(metrics.manual_baseline_minutes_assumed, 0)} min (3 minutes × exceptions — not
                measured). Skip-LLM records/min is wall-clock of this run and is not shown as a headline figure.
              </p>
            ) : null}

            <section className="grid gap-6 lg:grid-cols-5">
              <div className="overflow-hidden rounded-xl border border-slate-800 lg:col-span-3">
                <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
                  <h2 className="text-sm font-semibold text-white">Exceptions ({exceptions.length})</h2>
                  <span className="text-xs text-slate-400">{openCount} need attention</span>
                </div>
                {exceptions.length === 0 ? (
                  <div className="px-4 py-10 text-center text-sm text-slate-500">No exceptions on this run.</div>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-3 py-2">
                      <input
                        type="search"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="Search id, status, type…"
                        aria-label="Search exceptions"
                        className="min-w-[10rem] flex-1 rounded-md bg-slate-800 px-2 py-1.5 text-xs text-slate-100 placeholder:text-slate-500"
                      />
                      <select
                        value={statusFilter}
                        onChange={(e) => setStatusFilter(e.target.value)}
                        aria-label="Filter by status"
                        className="rounded-md bg-slate-800 px-2 py-1.5 text-xs text-slate-100"
                      >
                        <option value="">All statuses</option>
                        {STATUS_FILTERS.map((status) => (
                          <option key={status} value={status}>
                            {status}
                          </option>
                        ))}
                      </select>
                      <select
                        value={typeFilter}
                        onChange={(e) => setTypeFilter(e.target.value)}
                        aria-label="Type (predicted or planted)"
                        className="rounded-md bg-slate-800 px-2 py-1.5 text-xs text-slate-100"
                      >
                        <option value="">Type (predicted or planted)</option>
                        {typeOptions.map((type) => (
                          <option key={type} value={type}>
                            {type}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={clearFilters}
                        disabled={!filtersActive}
                        className="rounded-md bg-slate-800 px-2 py-1.5 text-xs text-slate-200 disabled:opacity-30"
                      >
                        Clear
                      </button>
                      <span className="text-[11px] text-slate-500">
                        Showing {filteredExceptions.length} of {exceptions.length}
                      </span>
                    </div>
                    {filteredExceptions.length === 0 ? (
                      <div className="px-4 py-10 text-center text-sm text-slate-400">
                        No exceptions match your filters. Try clearing the search or filters.
                      </div>
                    ) : (
                      <div className="max-h-[540px] overflow-auto">
                        <table className="w-full text-left text-[13px]">
                          <thead className="sticky top-0 bg-slate-900 text-[11px] uppercase tracking-wide text-slate-500">
                            <tr>
                              <th className="px-3 py-2 font-medium">ID</th>
                              <th className="px-3 py-2 font-medium">Predicted</th>
                              <th className="px-3 py-2 font-medium">Planted / eval</th>
                              <th className="px-3 py-2 font-medium">Status</th>
                              <th className="px-3 py-2 font-medium">Conf</th>
                            </tr>
                          </thead>
                          <tbody>
                            {filteredExceptions.map((row) => (
                              <tr
                                key={row.id}
                                onClick={() => setSelectedId(row.id)}
                                className={`cursor-pointer border-t border-slate-800/80 hover:bg-slate-800/50 ${
                                  selectedId === row.id ? "bg-slate-800 ring-1 ring-inset ring-amber-500/40" : ""
                                }`}
                              >
                                <td className="px-3 py-1.5 font-mono text-slate-300">{row.id}</td>
                                <td className="px-3 py-1.5">
                                  <Badge kind="type" value={row.exception_type} />
                                </td>
                                <td className="px-3 py-1.5">
                                  <Badge kind="type" value={row.ground_truth_type} />
                                </td>
                                <td className="px-3 py-1.5">
                                  <Badge kind="status" value={row.status} />
                                </td>
                                <td className="px-3 py-1.5 tabular-nums text-slate-300">
                                  {row.confidence == null ? "—" : num(row.confidence, 2)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )}
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 lg:col-span-2">
                {!selectedId ? (
                  <p className="text-sm text-slate-400">
                    Select an exception to inspect records, AI explanation, and the audit trail.
                  </p>
                ) : !detail ? (
                  <div>
                    <div className="mb-3 flex justify-end gap-1">
                      <button
                        type="button"
                        disabled={!canPrev}
                        onClick={() => canPrev && setSelectedId(filteredExceptions[selectedIndex - 1].id)}
                        className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
                      >
                        Previous
                      </button>
                      <button
                        type="button"
                        disabled={!canNext}
                        onClick={() => canNext && setSelectedId(filteredExceptions[selectedIndex + 1].id)}
                        className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
                      >
                        Next
                      </button>
                    </div>
                    <div className="animate-pulse space-y-3">
                      <div className="h-4 w-32 rounded bg-slate-800" />
                      <div className="h-4 w-full rounded bg-slate-800" />
                      <div className="h-20 rounded bg-slate-800" />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="text-xs text-slate-500">Exception #{detail.exception.id}</div>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <span className="text-lg font-semibold text-white">
                            {detail.exception.exception_type || "Not investigated"}
                          </span>
                          <Badge kind="status" value={detail.exception.status} />
                        </div>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        <button
                          type="button"
                          disabled={!canPrev}
                          onClick={() => canPrev && setSelectedId(filteredExceptions[selectedIndex - 1].id)}
                          className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
                        >
                          Previous
                        </button>
                        <button
                          type="button"
                          disabled={!canNext}
                          onClick={() => canNext && setSelectedId(filteredExceptions[selectedIndex + 1].id)}
                          className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
                        >
                          Next
                        </button>
                      </div>
                    </div>
                    <ConfidenceBlock confidence={detail.exception.confidence} />
                    <div>
                      <h3 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">
                        Investigation
                      </h3>
                      <p className="text-sm leading-relaxed text-slate-200">
                        {detail.exception.ai_explanation || "No LLM explanation yet."}
                      </p>
                      {detail.exception.recommended_action ? (
                        <p className="mt-2 text-sm text-amber-200">{detail.exception.recommended_action}</p>
                      ) : null}
                    </div>
                    <ThreeWayCompare
                      records={detail.records}
                      relatedTxnIds={detail.exception.related_txn_ids}
                    />
                    <AuditTimeline events={detail.audit} />
                    <div className="flex flex-wrap items-center gap-2 border-t border-slate-800 pt-3">
                      <input
                        className="rounded-md bg-slate-800 px-2 py-1.5 text-sm"
                        value={reviewer}
                        onChange={(e) => setReviewer(e.target.value)}
                        aria-label="Reviewer name"
                      />
                      <button
                        disabled={busy || alreadyResolved}
                        onClick={() => act(detail.exception.id, "approve")}
                        className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {busy ? "Working…" : alreadyResolved ? "Already resolved" : "Approve"}
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => act(detail.exception.id, "escalate")}
                        className="rounded-md bg-red-700 px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        Escalate
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
