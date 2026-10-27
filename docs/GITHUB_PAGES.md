# GitHub Pages frontend

Pages only serves **static files**. Login, register, and WA all need a real backend.

## Actions Variables or Secrets

CI reads **`vars.VITE_API_URL` first**, then falls back to **`secrets.VITE_API_URL`**.

| Name | Example | Required |
|------|---------|----------|
| `VITE_API_URL` | `https://signhouse-v3-mcp.it9up.com` | **Yes** (no `/api` suffix) |
| `VITE_MCP_PUBLIC_URL` | `https://signhouse-v3-mcp.it9up.com/mcp/` | Optional (MCP page hint) |

Settings → Secrets and variables → Actions → **Variables** or **Secrets**.

If login/register still hit `https://xerosumio.github.io/api/...` (405), the last Pages deploy was built **without** `VITE_API_URL` — re-run **Deploy Frontend to GitHub Pages** after setting the variable.

### Backend CORS (`ALLOWED_ORIGINS` on it9up / Coolify)

Browsers send `Origin: https://xerosumio.github.io` — **no** `/sign-house-v3-mcp` path.

```env
ALLOWED_ORIGINS=http://127.0.0.1:3010,http://localhost:3010,https://xerosumio.github.io
```

Wrong (CORS will fail): `https://xerosumio.github.io/sign-house-v3-mcp`

After changing env, restart the backend container. Newer backend builds also normalize path suffixes in `ALLOWED_ORIGINS`.

## Redeploy

Push to `main` (frontend paths) or run **Deploy Frontend to GitHub Pages** workflow manually.

## Local vs Pages

| | Local `npm run dev` | GitHub Pages |
|--|---------------------|--------------|
| API | Vite proxy → `127.0.0.1:5010` | `VITE_API_URL` at build time |
| Base path | `/` | `/sign-house-v3-mcp/` |
