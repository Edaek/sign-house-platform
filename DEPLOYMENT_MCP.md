# MCP split — URL migration

After deploying **sign-house-v3-mcp** on its own domain:

| Client | Old URL | New URL |
|--------|---------|---------|
| Cursor `mcp.json` | `https://MAIN/api/mcp/wa/mcp` | `https://MCP-HOST/mcp` |
| Loom **wa** connection | same | same |

- Bearer token: Sign House login JWT (MCP site or main site if `JWT_SECRET_KEY` matches).
- Main app should return **404** for `/api/mcp/*` after MCP removal from sign-house-v3.

Verify:

```bash
curl -s "https://MCP-HOST/api/mcp/hosted-wa/status"
curl -s -X POST "https://MCP-HOST/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}},"id":1}'
```
