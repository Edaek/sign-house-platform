# Sign House

Production web platform for a Hong Kong signage company. It turns CAD floor-plan PDFs into structured sign takeoffs, and it runs the field WhatsApp workflow that files installation photos onto a NAS.

This copy is published as a **portfolio showcase**. Credentials, customer data, and production secrets are not included.

## Overview

Sign House is a full-stack operations system with two tightly connected products:

1. **Floor-plan takeoff** — upload multi-page PDFs, detect sign markers with computer vision, read codes with OCR, then export Excel or CSV.
2. **WhatsApp field ops** — incoming job-site photos land in an image pool, get classified to a project/site/day, and sync into a nested NAS folder layout (`bucket / site / Photo / YYYY-MM-DD`) with remark files.

The backend is Flask + MongoDB. The frontend is React 18 + TypeScript. Detection uses OpenCV and PaddleOCR. WhatsApp traffic comes through a Socket.IO gateway, and external agents can call the same tools over a hosted MCP endpoint at `/mcp`.

## Product surfaces

### Floor-plan analysis

- JWT auth, project workspace, admin, audit logs, and a correction dictionary
- Multi-page PDF ingest (PyMuPDF / pdf2image)
- Circle, rectangle, template, and filled color-bar detection
- Batch OCR, manual region drawing, pan/zoom canvas editing
- Quantity assignment from neighboring callouts
- Excel template mapping and Excel / CSV export

### WhatsApp + NAS operations

- Inbound media pool with burst coalescing and duplicate-reply guards
- Project / site / day timeline and two-level NAS bucket management
- Bidirectional NAS sync, folder rename/relocate, and site remark `.txt` files
- Optional Loom-owned replies so the local bot does not double-send
- MCP tool server for classify, pool, project, and NAS actions

## Architecture

```text
                    +--------------------------+
                    |  React + TypeScript UI   |
                    |  Vite :3000              |
                    +------------+-------------+
                                 | /api
                    +------------v-------------+
   PDF / Excel      |  Flask API + MCP /mcp    |      WhatsApp
   uploads -------->|  :5002                   |<---- Wakka Gateway
                    +------+---------+---------+
                           |         |
                    MongoDB|         | SFTP
                           |         v
                           |    Company NAS
                           v    bucket / site / Photo / date
                      takeoff data
```

Local development:

| Service | URL |
| --- | --- |
| Web UI | `http://127.0.0.1:3000` |
| API + MCP | `http://127.0.0.1:5002` (`/api/…`, `/mcp/`) |

## Engineering highlights

- **Detection pipeline** — multi-pass HSV masking for red rectangles, a dedicated filled color-bar pass, stacked-bar splitting, and title-block exclusion that does not wipe a color-bar column.
- **OCR that matches the drawing** — PaddleOCR on cropped shapes, letter/digit sign-code rules, and neighbor-window quantity assignment. Color bars skip quantity scanning and default to `qty = 1`.
- **Job control** — cooperative cancel for long OpenCV/OCR runs, plus per-page cache resets so title-block results do not leak across same-size batch pages.
- **WhatsApp reliability** — inbound claim-by-message-id, burst coalescing, and reply-policy gates to stop duplicate worker messages.
- **NAS as source of truth** — nested buckets, duplicate-folder disambiguation, Hong Kong calendar days, and remark-file merge on site rename or relocate.
- **Agent interface** — the same WA/NAS tools are exposed in-process and over MCP so an external assistant can classify photos without a second WhatsApp sender.

## Tech stack

| Layer | Choices |
| --- | --- |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand, Fabric.js, Framer Motion |
| Backend | Flask, Flask-JWT-Extended, Flask-PyMongo, Gunicorn |
| Data | MongoDB |
| Vision / OCR | OpenCV, NumPy, Pillow, PaddleOCR, Tesseract (fallback) |
| Documents | PyMuPDF, pdf2image, openpyxl |
| Messaging | Python-SocketIO gateway, Wakka WhatsApp API |
| Storage | Paramiko SFTP to NAS |
| Agents | Hosted MCP (`/mcp`), optional Loom classify/reply path |
| Deploy | Docker Compose, GitHub Pages frontend, containerized API |

## Getting started

### Prerequisites

- Python 3.10+
- Node.js 18+
- MongoDB 6+
- Tesseract OCR (optional fallback)

```bash
# macOS
brew install tesseract poppler
```

### Setup

```bash
git clone https://github.com/Edaek/sign-house-platform.git
cd sign-house-platform

./scripts/setup.sh
cp backend/.env.example backend/.env
# set MONGO_URI, SECRET_KEY, JWT_SECRET_KEY
```

WhatsApp, NAS, and MCP keys are optional for the floor-plan editor.

### Run

```bash
./scripts/dev.sh
```

Or start the two processes yourself:

```bash
# terminal 1
cd backend
source .venv/bin/activate
python run.py          # API + MCP on :5002

# terminal 2
cd frontend
npm run dev            # UI on :3000
```

Optional WhatsApp gateway:

```bash
cd backend
python run.py --gateway
# or backend + gateway:
python run.py --all
```

Docker:

```bash
docker compose up --build
```

## Typical floor-plan workflow

1. Register / sign in and create a project.
2. Upload an optional Excel template and a multi-page floor-plan PDF.
3. Open a floor, run shape detection, then OCR.
4. Correct codes on the canvas or draw a manual region.
5. Mark the floor complete and export Excel or CSV.

## Project structure

```text
sign-house-platform/
├── backend/
│   ├── app/api/            REST endpoints (auth, processing, WA, NAS, MCP settings)
│   ├── app/services/       CV, OCR, NAS sync, WA classify, reply policy
│   ├── mcp_wa/             Hosted WhatsApp MCP server
│   ├── gateway/            Wakka Socket.IO consumer
│   ├── tests/              Backend regression tests
│   └── run.py
├── frontend/
│   └── src/
│       ├── pages/          Floor-plan editor + WA admin
│       ├── components/     Canvas, tables, NAS timeline
│       ├── store/          Zustand stores
│       └── lib/            API client and WA helpers
├── docs/                   Architecture and operations notes
├── scripts/                setup.sh, dev.sh
└── docker-compose.yml
```

## Environment

Copy `backend/.env.example` to `backend/.env`. The important local keys are:

| Variable | Purpose |
| --- | --- |
| `MONGO_URI` | MongoDB connection string |
| `SECRET_KEY` / `JWT_SECRET_KEY` | App and JWT secrets |
| `PORT` | Backend port (default `5002`) |
| `MCP_HTTP_MOUNT_PREFIX` | MCP mount (default `/mcp`) |
| `WAKKA_*` | WhatsApp provider (optional) |
| `NAS_*` | SFTP NAS sync (optional) |

Never commit a real `.env`. Production tokens and customer media stay out of this repository.

## Tests

```bash
cd backend
source .venv/bin/activate
python -m pytest
```

The suite covers NAS folder matching, remark-file merges, WhatsApp classify/reply policy, MCP HTTP mounting, and duplicate-message guards.

## Portfolio note

I worked on this system in production: floor-plan detection quality, batch OCR behavior, WhatsApp inbound reliability, NAS sync, and the MCP/agent boundary.

Internal deployment runbooks remain in `docs/` for technical depth. Client credentials, live databases, and job-site photos are not part of this repository.

## License

Proprietary. Shared here for portfolio review only. All rights remain with the original product owner.
