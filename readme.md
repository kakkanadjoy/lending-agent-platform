# Agentic Commercial Lending Platform

A full-stack agentic platform that automates commercial loan renewal reviews.
Built from scratch, runs locally and on Azure. This README is the complete
project memory — paste it into a new Claude conversation to resume exactly
where we left off.

---

## What it does

A portfolio manager opens the desk, sees loans ranked by deterioration risk
(worst first), clicks one, and the agent runs automatically:

1. Gathers the loan's financials from the database
2. Runs the deterministic rules engine (DSCR check, leverage cap, etc.)
3. Scores it with the XGBoost early warning model
4. Retrieves the relevant policy sections from the vector database (RAG)
5. Drafts a renewal memo with cited policy sections
6. Pauses for a human decision (approve / decline)
7. Records the outcome and resumes

Compliance cases (misrepresentation findings) are routed away automatically —
the LLM never sees them, the gate never appears.

---

## The three intelligences (the core design principle)

| Intelligence | Component | Job |
|---|---|---|
| Rules decide | Rules engine (`rules/engine.py`) | Deterministic policy evaluation — show a regulator |
| ML prioritizes | XGBoost EWS (`ews/`) | Orders the renewal queue worst-first — show a data scientist |
| Agent orchestrates | LangGraph (`agents/`) | Coordinates everything, pauses for humans — show in a demo |

The LLM only drafts. It cannot decide, route, or touch a compliance case.

---

## Full tech stack

| Layer | Technology | Why |
|---|---|---|
| Database | Postgres 16 + pgvector | One DB for LOS tables, event outbox, LangGraph checkpoints, vector corpus |
| Rules engine | Pure Python + policy.yaml | Deterministic, auditable, SR 11-7 posture |
| RAG | pgvector + sentence-transformers | Hybrid search (lexical + semantic) + cross-encoder rerank |
| ML | XGBoost + MLflow | EWS deterioration scoring, tracked experiments |
| Agent | LangGraph | Renewal workflow with human gate + postgres checkpointing |
| Guardrails | Presidio + custom validators | PII redaction, injection screening, fact/citation checking |
| API | FastAPI + uvicorn | REST endpoints + Prometheus metrics |
| Frontend | React 18 + Vite | Renewal desk UI |
| Observability | Prometheus + Grafana | Metrics, dashboards, queue depth |
| Cloud | Azure Container Apps + Neon | Production deployment |

---

## Repository structure

```
lending-agent-platform/
├── agents/           # LangGraph agent (state, nodes, graph, runner, guardrails, prompts, llm)
├── api/              # FastAPI service (main.py, metrics.py)
├── db/               # Schema + repository pattern (all SQL in one place)
├── ews/              # XGBoost EWS (features, train, score, model_artifact/)
├── rag/              # RAG pipeline (corpus, ingest, embedding, search)
├── rules/            # Policy engine (policy.yaml, engine.py)
├── synth/            # Synthetic portfolio generator (ground-truth-first)
├── tests/            # 55 tests across all modules
├── ops/              # Prometheus config + Grafana dashboard JSON
├── web/              # React desk (src/App.jsx, src/api.js, src/styles.css)
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Build phases (how it was built)

### Phase 0 — Foundation
- Docker Compose stack: postgres+pgvector, MLflow, Prometheus, Grafana
- Mini-LOS schema: loans, borrowers, documents, events (transactional outbox)
- Repository pattern: all DB access behind named functions in `db/repository.py`
- Synthetic portfolio generator: 604 loans, ground-truth-first (planted answer key)
- First tests + CI (GitHub Actions with postgres service container)

### Phase 1 — Deterministic core
- Rules engine: policy.yaml → evaluate() → Verdict (exceptions, routing, authority)
- Four rules: DSCR-MIN (1.20), LEVERAGE-MAX (4.0), UTILIZATION-HIGH (0.90), INCOME-MISREP (unwaivable)
- RAG: pgvector hybrid search, RRF fusion, cross-encoder rerank, citations
- Policy corpus generated FROM policy.yaml (single source of truth)

### Phase 2 — ML
- XGBoost EWS trained on planted `deteriorated` labels
- Seven features, delta-based (deterioration = change, not level)
- MLflow tracks runs, registers model, serves via registry
- Score ordering: LN-DEMO-DETERIORATING (0.83), LN-DEMO-COMPLIANCE (0.78) at top

### Phase 3 — LangGraph agent
- Step 1: Renewal graph (gather → rules → score → retrieve → draft → finalize)
- Step 2: Human gate (postgres checkpointing, interrupt_before=["finalize"])
- Step 3: Guardrails (PII redaction, injection screening, number/citation validators)
- Step 4: Real LLM (Azure Foundry gpt-4.1-mini, stub fallback if no credentials)

### Phase 4 — Observability
- FastAPI wraps agent, exposes /metrics
- Prometheus scrapes (pull model, every 10s)
- Grafana dashboard: queue depth, renewal rate, LLM cost, guardrail flag rate, node latency

### Phase 5 — React desk
- Slice 1: EWS-ranked queue + gate screen (start/resume renewal)
- Slice 2a: Role switcher (PM/Underwriter/Approver/Compliance) + activity feed
- Slice 2b: Borrower upload + demo control rail (tickler, reset)

### Phase 6 — Azure delivery
- Dockerfile: Python 3.12 slim, all deps, spaCy model, EWS artifact baked in
- ACR: lendingacrjk.azurecr.io (Basic SKU)
- Container Apps: lending-api in loan-compliance-env (reused, GT limits to 1)
- Database: Neon.tech free tier (GT subscription blocks Postgres Flexible Server)
- Static Web Apps: proud-flower-0e426cc0f.7.azurestaticapps.net
- CORS middleware added for cross-origin frontend→backend calls

---

## Live URLs (Azure)

```
Frontend:   https://proud-flower-0e426cc0f.7.azurestaticapps.net
Backend:    https://lending-api.wittyground-ef1fb78e.centralus.azurecontainerapps.io
API docs:   https://lending-api.wittyground-ef1fb78e.centralus.azurecontainerapps.io/docs
Health:     https://lending-api.wittyground-ef1fb78e.centralus.azurecontainerapps.io/health
```

---

## Demo loans (planted cast)

| Loan ID | Profile | What happens |
|---|---|---|
| LN-DEMO-CLEAN | DSCR 1.45, leverage 2.6 | Clean, fast-track, no exceptions |
| LN-DEMO-DETERIORATING | DSCR 1.12 (was 1.38), util 0.91 | EWS flags, waivable DSCR exception |
| LN-DEMO-LEVERAGE | Leverage 4.8 vs 4.0 cap | Waivable leverage exception |
| LN-DEMO-COMPLIANCE | DSCR 1.05, leverage 4.5, income discrepancy 0.34 | UNWAIVABLE → compliance hold, LLM never runs |

---

## Session startup (local)

```powershell
# 1. Start Docker Desktop (the engine — wait for whale icon)

# 2. Terminal 1 — backend
cd C:\Users\kakka\Github\lending-agent-platform
.venv\Scripts\Activate.ps1
docker compose up -d
uvicorn api.main:app --reload --port 8000

# 3. Terminal 2 — frontend
cd C:\Users\kakka\Github\lending-agent-platform\web
npm run dev
# → http://localhost:5173

# 4. If portfolio/model wiped (after full docker volume reset):
python -m synth.generate_portfolio --bulk 600
python -m rag.ingest
python -m ews.train
```

Verify:
- http://localhost:8000/docs — FastAPI docs
- http://localhost:5173 — React desk
- http://localhost:9090/targets — Prometheus (lending-api UP)
- http://localhost:3000 — Grafana
- http://localhost:5000 — MLflow

Note: first loan click after reboot may 500 (torch cold start) — click again, works.

---

## Neon database

```
Host:     ep-jolly-sea-athslzwl.c-9.us-east-1.aws.neon.tech
Database: neondb
User:     neondb_owner
SSL:      require
```

Full connection string:
```
postgresql://neondb_owner:npg_n0x4DCVztJYh@ep-jolly-sea-athslzwl.c-9.us-east-1.aws.neon.tech/neondb?sslmode=require
```

To seed Neon from scratch:
```powershell
$env:DATABASE_URL="postgresql://neondb_owner:npg_n0x4DCVztJYh@ep-jolly-sea-athslzwl.c-9.us-east-1.aws.neon.tech/neondb?sslmode=require"
python db/apply_schema.py
python -m synth.generate_portfolio --bulk 600
python -m rag.ingest
python -m ews.train
```

---

## Redeploy backend to Azure

```powershell
# After any code change to the Python backend:
docker build -t lendingacrjk.azurecr.io/lending-api:latest .
docker push lendingacrjk.azurecr.io/lending-api:latest
az containerapp update --name lending-api --resource-group rg-loan-compliance --image lendingacrjk.azurecr.io/lending-api:latest
```

Frontend redeploys automatically on `git push` via GitHub Actions.

---

## Shutdown Azure (stop billing)

```powershell
# Scale to zero (stops compute, keeps config)
az containerapp update --name lending-api --resource-group rg-loan-compliance --min-replicas 0 --max-replicas 0

# Nuclear — delete everything
az group delete --name lending-rg --yes --no-wait
az group delete --name rg-loan-compliance --yes --no-wait
```

---

## Key design decisions (the "why")

**Policy as data** — `rules/policy.yaml` is read three ways: engine evaluates against it,
RAG corpus is generated from it, synthetic generator uses its thresholds for ground truth.
Change a threshold once, all three move.

**Ground-truth-first synthetic data** — loans are generated by deciding their reality
first (deteriorated/clean), then generating numbers to match. The generator IS the
answer key for testing the rules engine and training the EWS.

**Transactional outbox** — events table in postgres is the nervous system. An
announcement is just a row. Worker polls for unprocessed rows. Crash-safe,
audit-friendly, activity-feed-ready.

**Repository pattern** — all SQL in `db/repository.py`. No other file writes SQL.
When the database moves (local → Azure), one file changes.

**Three seats** — rules decide (deterministic, SR 11-7), EWS prioritizes (ML,
queue ordering only), agent orchestrates (LangGraph, pauses/resumes). LLM is one
node of seven and only writes, never decides.

**Postgres wears the vector hat** — pgvector in the same postgres that holds LOS
data. No separate vector database. One connection string, one backup, one place.

**Human gates are architecture** — LangGraph interrupts + postgres checkpoints,
not UI politeness. A paused workflow survives process death. Resume can happen
days later in a completely fresh process.

---

## Known issues / gotchas

- **Torch cold start**: first `/renewals/start` call after a reboot may 500 as
  torch initializes the sentence-transformer. Second call always works.
- **Pinned deps**: `torch==2.4.1`, `transformers==4.57.6`, `sentence-transformers==3.0.1`
  must stay pinned — version drift causes the meta tensor crash.
- **GT Azure restrictions**: Postgres Flexible Server blocked (use Neon),
  ACR Tasks blocked (build locally), max 1 Container Apps environment.
- **PowerShell heredocs**: backticks (`) in JSX template literals get interpreted
  by PowerShell. Always edit JSX files in VS Code, not via PowerShell echo/heredoc.
- **vite.config.js proxy**: must point to `http://localhost:8000` for local dev.
  The `VITE_API_URL` env var overrides for Azure mode.

---

## GitHub

Repository: https://github.com/kakkanadjoy/lending-agent-platform
Owner: kakkanadjoy (jkakkanad3@gatech.edu)
Branch: main
CI: GitHub Actions (tests on every push, Static Web Apps deploy on every push)

---

## Azure resources

| Resource | Name | Resource Group | Notes |
|---|---|---|---|
| Container Registry | lendingacrjk | lending-rg | Basic SKU |
| Container App | lending-api | rg-loan-compliance | 1 CPU, 2GB RAM, scale-to-zero |
| Static Web App | lending-desk | lending-rg | Free tier, auto-deploys from GitHub |
| Container Apps Env | loan-compliance-env | rg-loan-compliance | Reused from prior project |
| Subscription | Azure subscription 1 | — | Georgia Tech (a0a71415-...) |