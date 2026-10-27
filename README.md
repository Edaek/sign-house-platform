# Sign House v3 (`mcp-v3` branch)

Sign House v3 (floor plans, WA, admin) with **hosted WhatsApp MCP** at `/mcp` and Loomy WA tooling in **one** backend process.

> **`main`** may still describe the old split from sign-house-v3-mcp. Active MCP + Loomy work uses branch **`mcp-v3`** (this layout).

## Local dev

```bash
./scripts/setup.sh   # once
./scripts/dev.sh     # backend :5002 + frontend :3000
```

WhatsApp Gateway (optional):

```bash
cd backend && PYTHONPATH=. .venv/bin/python run.py --gateway
# or backend + gateway:
cd backend && PYTHONPATH=. .venv/bin/python run.py --all
```

| What | URL |
|------|-----|
| Web UI | http://127.0.0.1:3000 |
| API + MCP HTTP | http://127.0.0.1:5002 (`/api/…`, `/mcp/`) |

## Env

Use your existing **`backend/.env`** (v3 `MONGO_URI`, `WAKKA_*`, NAS, etc.). Merge in any new keys from **`backend/.env.example`** (MCP mount, Loomy, Loom Platform):

- `PORT=5002`, `APP_URL=http://localhost:5002`
- `SIGN_HOUSE_API_URL=http://127.0.0.1:5002/api`
- `MCP_HTTP_MOUNT_PREFIX=/mcp`

See [LOCAL_DEV.md](./LOCAL_DEV.md), [DEPLOYMENT_MCP.md](./DEPLOYMENT_MCP.md), [docs/LOOM_WA_PLATFORM_BRIDGE.md](./docs/LOOM_WA_PLATFORM_BRIDGE.md).
