# Sign House WhatsApp MCP

Exposes Sign House **`/api/wa/*`** (on the **main app**) to Cursor/Loom via MCP tools, using the user's JWT.

## Hosted URL (this service)

**`https://YOUR-MCP-HOST/mcp`** — Streamable HTTP (use behind Gunicorn multi-worker).

```json
"sign-house-wa": {
  "url": "https://YOUR-MCP-HOST/mcp",
  "headers": { "Authorization": "Bearer YOUR_JWT" }
}
```

Configure main API: `SIGN_HOUSE_API_URL=https://signhousev3.axilogy.io/api`

## stdio (local)

```bash
export SIGN_HOUSE_JWT='…'
export SIGN_HOUSE_API_URL='https://signhousev3.axilogy.io/api'
./scripts/run_mcp_wa.sh
```

## Web UI

Deploy the frontend from this repo; `/mcp` page stores per-user snippets in Mongo (`mcp_servers`).
