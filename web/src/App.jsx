import { useEffect, useState, useCallback } from "react";
import { fetchQueue, fetchEvents, startRenewal, resumeRenewal,
         uploadDocument, runTickler, resetPortfolio, fetchExplanation } from "./api.js";

const ROLES = [
  { id: "pm",          label: "Portfolio Manager" },
  { id: "underwriter", label: "Underwriter" },
  { id: "approver",    label: "Approver" },
  { id: "compliance",  label: "Compliance Officer" },
];

function riskBand(score) {
  if (score >= 0.7) return { label: "High",    cls: "risk-high" };
  if (score >= 0.4) return { label: "Watch",   cls: "risk-watch" };
  return               { label: "Healthy", cls: "risk-healthy" };
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function eventLabel(e) {
  const type = e.event_type || "";
  const loan = e.loan_id ? " · " + e.loan_id : "";
  return type + loan;
}

function Queue({ onSelect, selectedId }) {
  const [rows,    setRows]    = useState(null);
  const [allRows, setAllRows] = useState([]);
  const [error,   setError]   = useState(null);
  const [search,  setSearch]  = useState("");

  useEffect(() => {
    fetchQueue(50).then(setRows).catch((e) => setError(e.message));
    fetchQueue(604).then(setAllRows).catch(() => {});
  }, []);

  if (error)             return <div className="panel-msg">Could not load queue. ({error})</div>;
  if (!rows)             return <div className="panel-msg">Loading...</div>;
  if (rows.length === 0) return <div className="panel-msg">No loans yet.</div>;

  const displayRows = search
    ? allRows.filter(r => r.loan_id.toLowerCase().includes(search.toLowerCase()))
    : rows;
  return (
    <div className="queue">
      <div className="queue-head">
        <span>Renewal queue</span>
        <span className="queue-sub">
  {search ? `${displayRows.length} results` : `${rows.length} loans · worst first`}
</span>
      </div>
      <input
        className="queue-search"
        placeholder="Search loan ID..."
        value={search}
        onChange={e => setSearch(e.target.value)}
      />
      {displayRows.map((r, i) => {
        const band = riskBand(r.ews_score);
        const selCls = selectedId === r.loan_id ? "is-selected" : "";
        return (
          <button key={r.loan_id} className={"queue-row " + selCls} onClick={() => onSelect(r.loan_id)}>
            <span className="rank">{i + 1}</span>
            <span className="loan-id">{r.loan_id}</span>
            <span className="risk-bar-wrap"><span className={"risk-bar " + band.cls} style={{ width: Math.round(r.ews_score * 100) + "%" }} /></span>
            <span className={"risk-tag " + band.cls}>{band.label}</span>
            <span className="score">{r.ews_score.toFixed(2)}</span>
          </button>
        );
      })}
    </div>
  );
}

function ActivityFeed() {
  const [events, setEvents] = useState([]);
  const [error,  setError]  = useState(null);
  const load = useCallback(() => {
    fetchEvents(30).then(setEvents).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { load(); const id = setInterval(load, 5000); return () => clearInterval(id); }, [load]);
  return (
    <div className="feed">
      <div className="feed-head"><span>Activity feed</span><span className="feed-sub">live · 5 s</span></div>
      {error && <div className="panel-msg">{error}</div>}
      {events.length === 0 && !error && <div className="panel-msg">No events yet.</div>}
      {events.map((e) => (
        <div key={e.event_id} className="feed-row">
          <span className="feed-time">{fmtTime(e.created_at)}</span>
          <span className="feed-label">{eventLabel(e)}</span>
        </div>
      ))}
    </div>
  );
}

function UploadView() {
  const [file,   setFile]   = useState(null);
  const [status, setStatus] = useState(null);
  const [busy,   setBusy]   = useState(false);
  async function submit() {
    if (!file) return;
    setBusy(true); setStatus(null);
    try {
      const r = await uploadDocument(file);
      setStatus({ ok: true, msg: "Uploaded " + r.filename + " (" + (r.size/1024).toFixed(1) + " KB). Watch the activity feed." });
    } catch (e) { setStatus({ ok: false, msg: "Upload failed: " + e.message }); }
    finally { setBusy(false); }
  }
  return (
    <div className="upload-view">
      <h2>Borrower Document Upload</h2>
      <p className="upload-desc">Upload a borrower PDF. The platform fires a document_received event visible in the activity feed.</p>
      <div className="upload-box">
        <input type="file" accept=".pdf" onChange={(e) => setFile(e.target.files[0])} className="file-input" />
        <button className="btn approve" disabled={!file || busy} onClick={submit}>{busy ? "Uploading..." : "Upload"}</button>
      </div>
      {file && <div className="upload-fname">Selected: {file.name}</div>}
      {status && <div className={"upload-status " + (status.ok ? "ok" : "err")}>{status.msg}</div>}
    </div>
  );
}

function DemoRail() {
  const [open,   setOpen]   = useState(false);
  const [status, setStatus] = useState(null);
  async function act(fn, label) {
    setStatus("Running: " + label + "...");
    try { const r = await fn(); setStatus("Done - " + label + ": " + JSON.stringify(r)); }
    catch (e) { setStatus("Failed - " + label + ": " + e.message); }
  }
  return (
    <div className="demo-rail">
      <button className="demo-toggle" onClick={() => setOpen(!open)}>Demo controls {open ? "▲" : "▼"}</button>
      {open && (
        <div className="demo-buttons">
          <button className="btn-demo" onClick={() => act(runTickler, "Run tickler")}>Run nightly tickler</button>
          <button className="btn-demo" onClick={() => act(resetPortfolio, "Reset portfolio")}>Reset portfolio</button>
          {status && <div className="demo-status">{status}</div>}
        </div>
      )}
    </div>
  );
}

function Gate({ loanId, role }) {
  const [state,   setState]   = useState(null);
  const [busy,    setBusy]    = useState(false);
  const [error,   setError]   = useState(null);
  const [outcome, setOutcome] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const threadId = "desk-" + loanId;
  useEffect(() => {
    setState(null); setOutcome(null); setError(null); setBusy(true); setExplanation(null);
    startRenewal(loanId, threadId).then(setState).catch((e) => setError(e.message)).finally(() => setBusy(false));
    fetchExplanation(loanId).then(setExplanation).catch(() => {});
  }, [loanId]);

  async function decide(decision) {
    setBusy(true);
    try { setOutcome(await resumeRenewal(threadId, decision)); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  if (busy && !state) return <div className="panel-msg">Running the agent...</div>;
  if (error)          return <div className="panel-msg">{error}</div>;
  if (!state)         return null;
  const isCompliance = state.routing === "compliance_review";
  const flags        = state.draft_flags || [];
  const canDecide    = (role === "approver" || role === "underwriter") && !isCompliance && !outcome;
  const routingCls   = isCompliance ? "routing-compliance" : "routing-normal";
  const roleLabel    = (ROLES.find(r => r.id === role) || {}).label;
  return (
    <div className="gate">
      <div className="gate-head">
        <h2>{loanId}</h2>
        <span className={"routing-tag " + routingCls}>{isCompliance ? "Compliance hold" : state.routing}</span>
      </div>
      {isCompliance && <div className="bright-line">Bright line: routed to compliance for suspected misrepresentation. No renewal review is drafted.</div>}
      {!isCompliance && (
        <section className="review">
          {(state.exceptions || []).length > 0 && (
            <div className="exceptions">
              <h3>Policy Exceptions</h3>
              <table className="exc-table">
                <thead><tr><th>Code</th><th>Severity</th><th>Observed</th><th>Threshold</th><th>Waiver Authority</th></tr></thead>
                <tbody>
                  {state.exceptions.map((e, i) => (
                    <tr key={i}>
                      <td>{e.code}</td>
                      <td><span className={"sev sev-" + e.severity}>{e.severity}</span></td>
                      <td>{e.observed}</td>
                      <td>{e.threshold}</td>
                      <td>{e.waiver_authority || "unwaivable"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h3>Drafted Review</h3>
          <pre className="review-text">{state.review_text}</pre>
          {flags.length > 0 && <div className="flags">Guardrails flagged this draft:<ul>{flags.map((f, i) => <li key={i}>{f}</li>)}</ul></div>}
        </section>
      )}
      {explanation && explanation.contributions && (
        <section className="shap">
          <h3>Why this EWS score? ({explanation.score})</h3>
          <div className="shap-bars">
            {Object.entries(explanation.contributions).filter(([,v]) => v !== 0).map(([feat, val]) => (
              <div key={feat} className="shap-row">
                <span className="shap-feat">{feat.replace(/_/g, " ")}</span>
                <div className="shap-bar-wrap">
                  <div className={"shap-bar " + (val > 0 ? "shap-pos" : "shap-neg")}
                    style={{ width: Math.min(100, Math.abs(val) * 60) + "%" }} />
                </div>
                <span className={"shap-val " + (val > 0 ? "shap-pos-text" : "shap-neg-text")}>
                  {val > 0 ? "+" : ""}{val.toFixed(3)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
      <section className="trail">
        <h3>Agent trail</h3>
        <ol>{(state.trail || []).map((t, i) => <li key={i}>{t}</li>)}</ol>
      </section>
      {canDecide && (
        <div className="actions">
          <button className="btn decline" disabled={busy} onClick={() => decide("decline")}>Decline</button>
          <button className="btn approve" disabled={busy} onClick={() => decide("approve")}>Approve</button>
        </div>
      )}
      {!canDecide && !isCompliance && !outcome && (
        <div className="role-notice">Viewing as <strong>{roleLabel}</strong>. Switch to Underwriter or Approver to decide.</div>
      )}
      {outcome && (
        <div className={"outcome " + outcome.human_decision}>
          Decision recorded: <strong>{outcome.human_decision}</strong>.
          <ol className="trail-after">{(outcome.trail || []).slice(-1).map((t, i) => <li key={i}>{t}</li>)}</ol>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [selected, setSelected] = useState(null);
  const [role,     setRole]     = useState("pm");
  const [tab,      setTab]      = useState("queue");
  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-left">
          <div className="brand">Renewal Desk</div>
          <nav className="tabs">
            <button className={"tab " + (tab === "queue" ? "tab-active" : "")} onClick={() => setTab("queue")}>Queue</button>
            <button className={"tab " + (tab === "upload" ? "tab-active" : "")} onClick={() => setTab("upload")}>Upload</button>
          </nav>
        </div>
        <div className="topbar-right">
          <select className="role-select" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
        </div>
      </header>
      {tab === "upload" ? (
        <div className="upload-page"><UploadView /></div>
      ) : (
        <div className="layout">
          <aside className="sidebar">
            <Queue onSelect={setSelected} selectedId={selected} />
            <ActivityFeed />
            <DemoRail />
          </aside>
          <main className="main">
            {selected ? <Gate key={selected} loanId={selected} role={role} /> : <div className="empty">Select a loan from the queue to review its renewal.</div>}
          </main>
        </div>
      )}
    </div>
  );
}
