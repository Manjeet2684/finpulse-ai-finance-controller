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

function Card({ label, value, hint }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
      {hint ? <div className="mt-1 text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}

export default function App() {
  const [metrics, setMetrics] = useState(null);
  const [exceptions, setExceptions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reviewer, setReviewer] = useState("controller");

  async function load() {
    setError("");
    try {
      const m = await fetch("/runs/latest").then((r) => {
        if (!r.ok) throw new Error("No run yet. Start the API and python -m finpulse run");
        return r.json();
      });
      setMetrics(m);
      const rows = await fetch(`/exceptions?run_id=${m.run_id}`).then((r) => r.json());
      setExceptions(rows);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    fetch(`/exceptions/${selectedId}`)
      .then((r) => r.json())
      .then(setDetail)
      .catch((err) => setError(err.message));
  }, [selectedId]);

  const unresolved = useMemo(
    () => exceptions.filter((e) => e.status === "UNRESOLVED" || (e.status === "NEEDS_REVIEW" && !e.reviewed_at)),
    [exceptions]
  );

  async function act(id, action) {
    setBusy(true);
    try {
      await fetch(`/exceptions/${id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer, reason: action === "escalate" ? "Escalated from dashboard" : "" }),
      });
      await load();
      const fresh = await fetch(`/exceptions/${id}`).then((r) => r.json());
      setDetail(fresh);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">FINPULSE AI</h1>
          <p className="text-slate-400">Track 04 — 3-way reconciliation controller (Razorpay × Bank × Ledger)</p>
        </div>
        <div className="flex gap-2">
          <a className="rounded-lg bg-slate-800 px-3 py-2 text-sm" href="/exceptions/export?fmt=json">
            Export JSON
          </a>
          <a className="rounded-lg bg-slate-800 px-3 py-2 text-sm" href="/exceptions/export?fmt=csv">
            Export CSV
          </a>
          <a className="rounded-lg bg-amber-500 px-3 py-2 text-sm font-medium text-slate-950" href="/exceptions/export?fmt=unresolved">
            Unresolved list
          </a>
        </div>
      </header>

      {error ? <div className="mb-4 rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-red-200">{error}</div> : null}

      <section className="mb-8 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card
          label="Matcher precision / recall"
          value={`${pct(metrics?.matcher_precision)} / ${pct(metrics?.matcher_recall)}`}
          hint="Vs planted match key — not LLM confidence"
        />
        <Card
          label="Exception-type accuracy"
          value={metrics?.exception_accuracy_pct == null ? "Pending LLM" : `${num(metrics.exception_accuracy_pct, 1)}%`}
          hint="predicted exception_type == ground_truth_type"
        />
        <Card
          label="Throughput"
          value={`${num(metrics?.records_per_minute, 1)} rec/min`}
          hint={`${num(metrics?.records_per_second, 2)} records/sec · ${metrics?.records_processed ?? "—"} rows`}
        />
        <Card
          label="Manual baseline (ASSUMED)"
          value={`${num(metrics?.manual_baseline_minutes_assumed, 0)} min`}
          hint="3 minutes × exceptions — not measured"
        />
      </section>

      <section className="mb-8 grid gap-4 md:grid-cols-3">
        <Card label="Cash matched / settled" value={inr(metrics?.cash_matched_amount)} hint="Sum of auto-matched Razorpay amounts" />
        <Card label="Cash in transit" value={inr(metrics?.cash_in_transit_amount)} hint="Missing bank receipt leftovers" />
        <Card label="Cash exceptional" value={inr(metrics?.cash_exception_amount)} hint="Other unmatched amounts" />
      </section>

      <section className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3 rounded-xl border border-slate-800 overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <h2 className="font-semibold">Exceptions ({exceptions.length})</h2>
            <span className="text-xs text-slate-400">{unresolved.length} open / unresolved</span>
          </div>
          <div className="max-h-[540px] overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-slate-900 text-slate-400">
                <tr>
                  <th className="px-3 py-2">ID</th>
                  <th className="px-3 py-2">Predicted</th>
                  <th className="px-3 py-2">Truth</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Conf</th>
                </tr>
              </thead>
              <tbody>
                {exceptions.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => setSelectedId(row.id)}
                    className={`cursor-pointer border-t border-slate-800 hover:bg-slate-800/60 ${selectedId === row.id ? "bg-slate-800" : ""}`}
                  >
                    <td className="px-3 py-2">{row.id}</td>
                    <td className="px-3 py-2">{row.exception_type || "—"}</td>
                    <td className="px-3 py-2">{row.ground_truth_type || "—"}</td>
                    <td className="px-3 py-2">{row.status}</td>
                    <td className="px-3 py-2">{row.confidence == null ? "—" : num(row.confidence, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="lg:col-span-2 rounded-xl border border-slate-800 bg-slate-900 p-4">
          {!detail ? (
            <p className="text-slate-400">Select an exception to inspect records, AI explanation, and audit trail.</p>
          ) : (
            <div className="space-y-4">
              <div>
                <div className="text-xs text-slate-400">Exception #{detail.exception.id}</div>
                <div className="text-lg font-semibold">{detail.exception.exception_type || "Not investigated"}</div>
                <div className="text-sm text-slate-400">{detail.exception.status}</div>
              </div>
              <p className="text-sm text-slate-200">{detail.exception.ai_explanation || "No LLM explanation yet."}</p>
              <p className="text-sm text-amber-200">{detail.exception.recommended_action}</p>
              <div>
                <h3 className="mb-2 text-xs uppercase tracking-wide text-slate-400">Side-by-side records</h3>
                <div className="space-y-2">
                  {detail.records.map((t) => (
                    <div key={t.id} className="rounded-lg border border-slate-800 p-2 text-xs">
                      <div className="font-medium">
                        {t.source} · {t.source_txn_id}
                      </div>
                      <div>
                        {inr(t.amount)} · {t.txn_time}
                      </div>
                      <div className="text-slate-400">{t.description}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h3 className="mb-2 text-xs uppercase tracking-wide text-slate-400">Audit</h3>
                <ul className="space-y-1 text-xs text-slate-300">
                  {detail.audit.map((a, i) => (
                    <li key={i}>
                      {a.event_time} · {a.actor_type} · {a.action} — {a.reason}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  className="rounded bg-slate-800 px-2 py-1 text-sm"
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                />
                <button
                  disabled={busy}
                  onClick={() => act(detail.exception.id, "approve")}
                  className="rounded bg-emerald-600 px-3 py-1 text-sm font-medium"
                >
                  Approve
                </button>
                <button
                  disabled={busy}
                  onClick={() => act(detail.exception.id, "escalate")}
                  className="rounded bg-red-700 px-3 py-1 text-sm font-medium"
                >
                  Escalate
                </button>
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
