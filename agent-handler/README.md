# HydraDB as a tool in Merge Agent Handler

Register HydraDB's hosted MCP server as a Custom MCP Connector so agents using
Merge Agent Handler can call HydraDB's memory tools (recall, ingest, graph query)
alongside Merge's other connectors.

## Verified compatibility (probed against mcp.hydradb.com)

| Requirement (Merge Custom MCP) | HydraDB MCP |
|---|---|
| Remote, public HTTPS, completes MCP `initialize` | `https://mcp.hydradb.com/mcp` - OK |
| Protocol revision `2025-03-26` or `2024-11-05` | negotiates **both** |
| Static secret auth (one bearer token / API key) | `Authorization: Bearer <HYDRADB_API_KEY>` |
| Server identity | `hydradb-mcp` 1.5.1, `tools` capability |

The one wrinkle: the server needs the target database via an `X-HydraDB-Database`
header. Merge Agent Handler supports **up to 20 non-secret `headers`** on every
request, so this fits there (the API key goes in the secret `auth.header`).

## Registering

`connector.json` holds the Connector config. Per Merge's
[Custom MCP servers](https://docs.merge.dev/merge-agent-handler/build/connecting-agents/custom-mcp-servers)
docs, register it from the Agent Handler dashboard or API with:

- **url:** `https://mcp.hydradb.com/mcp`
- **auth:** `secret` header `Authorization = Bearer <HydraDB API key>` (stored
  encrypted at the org level)
- **headers:** `X-HydraDB-Database = <database/tenant>`

Agent Handler then discovers HydraDB's tools and exposes them through the same MCP
URL the agent already uses. Use a **Tool Pack** to scope which tools are visible;
a minimal memory pack is `hydradb_query` (recall) + `hydradb_ingest` (write).

## Caveats

- The `auth` secret and the `X-HydraDB-Database` value are **org-wide** (one value
  shared across users). For multiple HydraDB databases, register one Connector per
  database.
- The registration API has **no update call** - rotate a secret by deleting and
  re-registering (the dashboard path is shorter for in-use Connectors).
- Requires a Merge Agent Handler account; the Connector is scoped to your org, not
  listed in Merge's shared catalog (that path is "request a Connector", maintained
  by Merge).
