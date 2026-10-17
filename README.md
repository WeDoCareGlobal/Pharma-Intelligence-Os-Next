# Pharma Intelligence OS — Pharmacovigilance & Regulatory Intelligence (Next Generation)

> **Development status:** This repository is a work in progress. The architecture and examples below are not a certification that every integration is implemented or production-validated. Review the current source, tests and release notes before deployment. Publication DOIs identify their recorded artifacts, not automatically the latest Next commit. See the [portfolio evidence index](https://wedocare-global.com/evidence.html).


[![CI](https://github.com/WeDoCareGlobal/Pharma-Intelligence-Os-Next/actions/workflows/ci.yml/badge.svg)](https://github.com/WeDoCareGlobal/Pharma-Intelligence-Os-Next/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22983388.svg)](https://doi.org/10.5281/zenodo.22983388)
[![ORCID](https://img.shields.io/badge/ORCID-0009--0009--8515--2727-green.svg)](https://orcid.org/0009-0009-8515-2727)
[![We Do Care Global](https://img.shields.io/badge/We%20Do%20Care%20Global-Enterprise%20AI%20Governance-purple.svg)](https://wedocare-global.com/)

**Part of the [We Do Care Global](https://wedocare-global.com/) ecosystem — 6 published systems, Apache-2.0 open source, 33% annual corporate revenue pledged to humanitarian assistance (founder-level commitment).**

---

## Overview

**Pharma-Intelligence-Os-Next** is a **polyglot** pharmacovigilance and regulatory intelligence platform combining:

- **Python (`pharma_next/`)** — FastAPI case review API, tenant-scoped SQLite/PostgreSQL storage, authenticated editor/reviewer roles, ICH E2B(R3) package generation, disproportionality signal management (PRR/ROR), PSUR/PBRER working drafts, openFDA integration
- **TypeScript (`frontend/` + `backend/`)** — React + Vite + TailwindCSS dashboard, AppDeploy SDK backend with realtime WebSocket updates

> **Software tool only.** E2B transmission to EMA EudraVigilance and official regulatory submissions are registration-gated by design; the workspace never fabricates a regulatory status.

---

## Polyglot Architecture

```
Pharma-Intelligence-Os-Next/
├── pharma_next/                      # Python: FastAPI Case Review API
│   ├── main.py                       # Factory entry point (uvicorn)
│   ├── api.py                        # /v1/cases endpoints (create/read/revise/history/review/draft)
│   ├── store.py                      # Tenant-scoped SQLite/PostgreSQL + optimistic locking
│   ├── models.py                     # Pydantic models (Case, Revision, Review, AuditEvent)
│   ├── signals.py                    # PRR/ROR disproportionality analysis
│   ├── e2b.py                        # ICH E2B(R3) XML generation
│   ├── openfda.py                    # FDA openFDA feed ingestion
│   └── __init__.py
├── frontend/                         # React + Vite + TypeScript (Dashboard UI)
│   ├── src/
│   │   ├── App.tsx                   # Main dashboard: case review, signals, PSUR, FDA tracking
│   │   ├── main.tsx                  # Entry point
│   │   ├── index.css                 # TailwindCSS + custom styles
│   │   └── lib/                      # API client, utilities
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   └── index.html
├── backend/                          # TypeScript: AppDeploy SDK Backend
│   ├── index.ts                      # Control plane API: cases, approvals, OAuth, sync
│   ├── realtime.ts                   # WebSocket server setup
│   ├── realtime-subscribers.ts       # Realtime subscription management
│   ├── package.json
│   └── tsconfig.json
├── .zenodo.json                      # Zenodo metadata for DOI minting
├── CITATION.cff                      # Citation file format
├── CHANGELOG.md
├── CODE_OF_CLAUDE.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── cron.json                         # Scheduled sync (Sarajevo TZ)
├── Dockerfile                        # Multi-stage: frontend + backend + Python
├── pyproject.toml                    # Python package config
├── package.json                      # Frontend dependencies
├── requirements.txt                  # Python dependencies
└── .github/workflows/                # CI, release, docker, Pages, Zenodo
```

---

## Quick Start

### Python API (Core Case Review)
```bash
# Clone
git clone https://github.com/WeDoCareGlobal/Pharma-Intelligence-Os-Next.git
cd Pharma-Intelligence-Os-Next

# Install Python dependencies
pip install -e ".[test]"

# Configure environment
export PHARMA_DATABASE=sqlite+aiosqlite:///./pharma.db
export PHARMA_SERVICE_IDENTITIES='{"token1": {"tenant": "demo", "subject": "reviewer1", "role": "reviewer"}}'

# Run API server (port 8000)
uvicorn pharma_next.main:application --factory --host 0.0.0.0 --port 8000

# Test endpoints
curl http://localhost:8000/health
curl -H "Authorization: Bearer token1" http://localhost:8000/v1/cases
```

### Frontend Development (React Dashboard)
```bash
cd frontend
npm install
npm run dev  # Vite dev server on :5173
```

### Backend Development (TypeScript AppDeploy SDK)
```bash
cd backend
npm install
npm run dev  # ts-node on :3001
```

### Full Stack (Docker)
```bash
# Build multi-stage image
docker build -t pharma-intelligence-os .

# Run on port 8080
docker run -p 8080:8080 \
  -e PHARMA_DATABASE=sqlite+aiosqlite:///./pharma.db \
  -e PHARMA_SERVICE_IDENTITIES='{"token1": {"tenant": "demo", "subject": "reviewer1", "role": "reviewer"}}' \
  pharma-intelligence-os

# Frontend: http://localhost:8080
# Python API: http://localhost:8080/api/v1/*
# Backend API: http://localhost:8080/api/control-plane
```

---

## Core Capabilities

| Domain | Features |
|--------|----------|
| **ICSR Case Review** | Tenant-scoped cases, revisions, optimistic locking, editor/reviewer separation, SHA-256 draft export |
| **Signal Management** | PRR (Proportional Reporting Ratio), ROR (Reporting Odds Ratio) with confidence intervals |
| **Regulatory Docs** | ICH E2B(R3) XML generation, PSUR/PBRER working drafts |
| **FDA Intelligence** | openFDA feed ingestion: approvals, safety alerts, enforcement reports |
| **Audit Trail** | Transactional audit events (create/revise/review/approve/export) |
| **Realtime UI** | WebSocket updates for case status, review assignments, signal alerts |

---

## API Endpoints (Python `pharma_next`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | — | Process status |
| `POST` | `/v1/cases` | ✓ | Create case |
| `GET` | `/v1/cases` | ✓ | List cases (tenant-scoped) |
| `GET` | `/v1/cases/{id}` | ✓ | Read case |
| `POST` | `/v1/cases/{id}/revisions` | ✓ | Create revision (editor) |
| `POST` | `/v1/cases/{id}/review` | ✓ | Submit review (reviewer) |
| `GET` | `/v1/cases/{id}/draft` | ✓ | Export reviewed-case JSON + SHA-256 |
| `GET` | `/v1/cases/{id}/history` | ✓ | Audit trail |
| `GET` | `/v1/signals/prr` | ✓ | PRR analysis |
| `GET` | `/v1/signals/ror` | ✓ | ROR analysis |
| `POST` | `/v1/e2b/generate` | ✓ | Generate ICH E2B(R3) XML |

---

## Backend API (TypeScript AppDeploy SDK)

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /api/control-plane` | ✓ | Full state: cases, reviews, signals, audit |
| `GET /api/integrations` | ✓ | GitHub/ORCID/Zenodo connection status |
| `POST /api/integrations/:provider/start` | ✓ | OAuth flow start |
| `GET /api/oauth/:provider/callback` | — | OAuth callback |
| `POST /api/actions` | ✓ | Case actions (assign, escalate, export) |
| `POST /api/approvals/decision` | ✓ | Approve/reject case reviews |
| `WS /api/realtime/subscribe` | — | Realtime case/signal updates |

---

## Deployment

| Target | Command |
|--------|---------|
| **Docker (local)** | `docker build -t pharma-intelligence-os . && docker run -p 8080:8080 pharma-intelligence-os` |
| **GHCR** | `ghcr.io/WeDoCareGlobal/Pharma-Intelligence-Os-Next` (auto on push to `main`) |
| **Cloud** | Requires Cloudflare API token + secrets |

### CI/CD (`.github/workflows/`)
- `ci.yml` — Lint, typecheck, test, security scan on PR/push
- `release.yml` — Version bump, tag, Docker build/push on release
- `docker.yml` — Multi-arch build/push to GHCR on `main` push
- `pages.yml` — Deploy `docs/` to GitHub Pages
- `zenodo.yml` — Archive releases to Zenodo, mint DOI, push to ORCID

---

## License

Apache-2.0 © 2026 [We Do Care Global](https://wedocare-global.com/) — Emir Perla (ORCID: 0009-0009-8515-2727)

33% of profits → humanitarian aid.

---

## Citation

```bibtex
@software{perla2026pharma,
  author = {Perla, Emir},
  title = {Pharma Intelligence OS — Pharmacovigilance & Regulatory Intelligence Workspace},
  version = {0.1.1},
  year = {2026},
  doi = {10.5281/zenodo.22983388},
  url = {https://github.com/WeDoCareGlobal/Pharma-Intelligence-Os-Next}
}
```

---

## WDCG Ecosystem

| System | Repo | Purpose |
|--------|------|---------|
| **AgentGuard** | `WeDoCareGlobal/agentguard-next` | Security & governance control plane |
| **FoundationCentar** | `WeDoCareGlobal/FoundationCentar-Next` | One-Click Agent Factory |
| **Enterprise Hybrid-RAG** | `WeDoCareGlobal/enterprise-hybrid-rag-next` | Hybrid retrieval |
| **Agent Eval** | `WeDoCareGlobal/agent-eval-next` | Evaluation harness |
| **AgentVault** | `WeDoCareGlobal/AgentVault-Next` | Tool registry & assurance |
| **Pharma Intelligence OS** | `WeDoCareGlobal/Pharma-Intelligence-Os-Next` | **This repo** — Regulatory intelligence |