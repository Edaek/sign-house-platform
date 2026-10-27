# WhatsApp MCP on `mcp-v3` branch

This branch merges the former **sign-house-v3-mcp** repo into Sign House v3:

- **One process**: Flask `/api` + hosted MCP at `/mcp` (see `backend/mcp_wa/`, `DEPLOYMENT_MCP.md`)
- **Env**: use **`backend/.env`** with v3 defaults (`PORT=5002`, `APP_URL=http://localhost:5002`, frontend on **3000**)
- **Do not** use a separate 5010 MCP-only deploy unless you intentionally split again

`main` may still document the old split layout; active WA + Loomy + MCP work happens on **`mcp-v3`**.
