# Sign House WhatsApp MCP

Exposes all `/api/wa/*` operations to Cursor via MCP tools, authenticated with your Sign House login JWT.

## Recommended: URL (HTTP)

Backend serves MCP at **`/api/mcp/wa/mcp`** (Streamable HTTP, stateless — use this in Cursor behind Gunicorn) and optionally **`/api/mcp/wa/sse`** (SSE only works with a single worker / sticky sessions).

```json
"sign-house-wa": {
  "url": "https://YOUR-BACKEND/api/mcp/wa/sse",
  "transport": "sse",
  "headers": {
    "Authorization": "Bearer YOUR_JWT"
  }
}
```

Local dev (Vite proxy): `http://localhost:3001/api/mcp/wa/sse`

1. `pip install -r requirements.txt` on the backend (includes `mcp`, `a2wsgi`).
2. Log in on the web app → MCP page → **Use Sign House WA preset** (fills URL + Bearer token).
3. Paste into Cursor `mcp.json` → Reload MCP.

## Optional: stdio (offline laptop)

| Field | Value |
|-------|--------|
| Command | `backend/scripts/run_mcp_wa.sh` (absolute path) |
| env | `SIGN_HOUSE_JWT`, `SIGN_HOUSE_API_URL` |

## Environment

| Variable | Required | Default |
|----------|----------|---------|
| `SIGN_HOUSE_JWT` | yes | — |
| `SIGN_HOUSE_API_URL` | no | `http://127.0.0.1:5000/api` (only if MCP talks to Flask directly; prefer your web app origin + `/api`) |
| `SIGN_HOUSE_HTTP_TIMEOUT` | no | `60` (NAS sync tools use 300s) |

## Token expiry

If tools return 401/403, log in again and update `SIGN_HOUSE_JWT` in Cursor env.

## Run manually

```bash
cd backend
export SIGN_HOUSE_JWT='…'
export SIGN_HOUSE_API_URL='http://127.0.0.1:5000/api'
./scripts/run_mcp_wa.sh
# or: cd backend && python -m mcp_wa.server
```

Start with `wa_whoami` in Cursor to verify auth.
