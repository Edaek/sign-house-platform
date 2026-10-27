# Local development (`mcp-v3`)

Single repo, single backend:

- Backend: **5002** — `/api/*` + `/mcp/`
- Frontend: **3000** — Vite proxies `/api` → **5002**

```bash
cp backend/.env.example backend/.env   # if needed; keep your v3 secrets
./scripts/dev.sh
```

MCP HTTP (Cursor / Loom): `http://127.0.0.1:5002/mcp/` with `Authorization: Bearer <Sign House JWT>`.

Install **`a2wsgi`** if logs say MCP is not mounted: `pip install a2wsgi`.
