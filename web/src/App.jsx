import { useEffect, useState } from "react";
import { fetchQueue, startRenewal, resumeRenewal } from "./api.js";

// ── helpers ─────────────────────────────────────────────────────────────
// Risk band from the EWS score: this is the priority signal the whole desk
// is organized around. Worst credits read hot, healthy ones read calm.
function riskBand(score) {
  if (score >= 0.7) return { label: "High", cls: "risk-high" };
  if (score >= 0.4) return { label: "Watch", cls: "risk-watch" };
  return { label: "Healthy", cls: "risk-healthy" };
}

// ── queue (the priority rail) ───────────────────────────────────────────
function Queue({ onSelect, selectedId }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchQueue(20).then(setRows).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="panel-msg">Couldn't load the queue. Is the API running on :8000? ({error})</div>;
  if (!rows) return <div className="panel-msg">Loading the queue…</div>;
  if (rows.length === 0) return <div className="panel-msg">No loans in the portfolio yet.</div>;

  return (
    <div className="queue">
      <div className="queue-head">
        <span>Renewal queue</span>
        <span className="queue-sub">{rows.length} loans · worst first</span>
      </div>
      {rows.map((r, i) => {
        const band = riskBand(r.ews_score);
        return (
          <button
            key={r.loan_id}
            className={`queue-row ${selectedId === r.loan_id ? "is-selected" : ""}`}
            onClick={() => onSelect(r.loan_id)}
          >
            <span className="rank">{i + 1}</span>
            <span className="loan-id">{r.loan_id}</span>
            <span className="risk-bar-wrap">
              <span className={`risk-bar ${band.cls}`} style={{ width: `${Math.round(r.ews_score * 100)}%` }} />
            </span>
            <span className={`risk-tag ${band.cls}`}>{band.label}</span>
            <span className="score">{r.ews_score.toFixed(2)}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── gate screen (the human-in-the-loop moment) ──────────────────────────
function Gate({ loanId }) {
  const [state, setState] = useState(null);   // start result
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [outcome, setOutcome] = useState(null);   // resume result

  // a stable thread id per loan view so resume targets the same run
  const threadId = `desk-${loanId}`;

  useEffect(() => {
    setState(null); setOutcome(null); setError(null); setBusy(true);
    startRenewal(loanId, threadId)
      .then(setState)
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [loanId]);

  async function decide(decision) {
    setBusy(true);
    try {
      const r = await resumeRenewal(threadId, decision);
      setOutcome(r);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (busy && !state) return <div className="panel-msg">Running the agent…</div>;
  if (error) return <div className="panel-msg">{error}</div>;
  if (!state) return null;

  const isCompliance = state.routing === "compliance_review";
  const flags = state.draft_flags || [];

  return (
    <div className="gate">
      <div className="gate-head">
        <h2>{loanId}</h2>
        <span className={`routing-tag ${isCompliance ? "routing-compliance" : "routing-normal"}`}>
          {isCompliance ? "Compliance hold" : state.routing}
        </span>
      </div>

      {isCompliance && (
        <div className="bright-line">
          Bright line: routed to compliance for suspected misrepresentation.
          No renewal review is drafted. A compliance officer must review.
        </div>
      )}

      <section className="review">
        <h3>Drafted review</h3>
        <pre className="review-text">{state.review_text}</pre>
        {flags.length > 0 && (
          <div className="flags">
            Guardrails flagged this draft:
            <ul>{flags.map((f, i) => <li key={i}>{f}</li>)}</ul>
          </div>
        )}
      </section>

      <section className="trail">
        <h3>Agent trail</h3>
        <ol>{(state.trail || []).map((t, i) => <li key={i}>{t}</li>)}</ol>
      </section>

      {!isCompliance && !outcome && (
        <div className="actions">
          <button className="btn decline" disabled={busy} onClick={() => decide("decline")}>Decline</button>
          <button className="btn approve" disabled={busy} onClick={() => decide("approve")}>Approve</button>
        </div>
      )}

      {outcome && (
        <div className={`outcome ${outcome.human_decision}`}>
          Decision recorded: <strong>{outcome.human_decision}</strong>.
          <ol className="trail-after">{(outcome.trail || []).slice(-1).map((t, i) => <li key={i}>{t}</li>)}</ol>
        </div>
      )}
    </div>
  );
}

// ── app shell ────────────────────────────────────────────────────────────
export default function App() {
  const [selected, setSelected] = useState(null);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Renewal Desk</div>
        <div className="role">Portfolio Manager</div>
      </header>
      <div className="layout">
        <aside className="sidebar">
          <Queue onSelect={setSelected} selectedId={selected} />
        </aside>
        <main className="main">
          {selected
            ? <Gate key={selected} loanId={selected} />
            : <div className="empty">Select a loan from the queue to review its renewal.</div>}
        </main>
      </div>
    </div>
  );
}
