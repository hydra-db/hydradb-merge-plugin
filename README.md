<p align="center">
  <img src="assets/icon.png" width="88" alt="HydraDB" />
</p>

<h1 align="center">HydraDB for Merge</h1>

<p align="center">
  Turn 220+ business tools into graph-native memory, through one
  <a href="https://merge.dev">Merge</a> connection.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-FF5719" alt="MIT license" />
  <img src="https://img.shields.io/badge/python-3.9%2B-FF5719" alt="Python 3.9+" />
  <img src="https://img.shields.io/badge/HydraDB-context%20API-111111" alt="HydraDB" />
</p>

---

[Merge](https://merge.dev) gives you one API for 220+ ticketing, CRM, HRIS, ATS,
accounting, and file-storage tools. [HydraDB](https://hydradb.com) turns data
into a graph you can recall from. This connector joins the two: your customers'
business records flow through Merge into a HydraDB knowledge graph, ready for an
agent or app to query.

## Quick start

```bash
pip install -e sync/

export MERGE_API_KEY=...          # Merge production API key
export MERGE_ACCOUNT_TOKEN=...    # the linked account to pull from
export HYDRADB_API_KEY=...        # from the HydraDB dashboard
export HYDRADB_DATABASE=...       # target database (tenant)

python sync/merge_to_hydradb.py ticketing tickets
```

The two positional arguments are the Merge **category** and **model**. They
default to `ticketing` and `tickets`.

## What it does

- **Any Merge model.** Tickets, contacts, employees, candidates, documents, and
  more, selected by category and model.
- **Incremental.** Pass `MERGE_MODIFIED_AFTER` (ISO 8601) to pull only records
  changed since the last run.
- **Resilient.** Backs off on rate limits and transient errors, and caps
  per-item text so a single large record can't blow up an ingest.
- **Recall-ready.** Each record is normalized and ingested as HydraDB knowledge,
  so it comes back through the context API and graph queries.

## Configuration

| Variable | Required | Description |
| - | - | - |
| `MERGE_API_KEY` | yes | Merge production API key. |
| `MERGE_ACCOUNT_TOKEN` | yes | Token for the linked account to sync. |
| `HYDRADB_API_KEY` | yes | HydraDB API key from the dashboard. |
| `HYDRADB_DATABASE` | yes | Target HydraDB database (tenant). |
| `HYDRADB_COLLECTION` | no | Sub-tenant scope within the database. |
| `HYDRADB_LAYOUT` | no | `split` (default) or `unified`; use unified only after production rollout is confirmed. |
| `MERGE_CATEGORY` | no | Default category when no argument is given. |
| `MERGE_MODEL` | no | Default model when no argument is given. |
| `MERGE_MODIFIED_AFTER` | no | ISO 8601 cutoff for an incremental pull. |

## Unified rollout preparation

Unified support is not enabled in production. Keep `HYDRADB_LAYOUT=split`
until your database's production rollout is confirmed. Then explicitly select
`HYDRADB_LAYOUT=unified` (or `HydraDBConfig(..., layout="unified")`).
Only these two layouts are accepted; no failed write is retried in another layout.

Unified sync sends JSON `{database, collection, context: [...]}` without a
split selector. Each generated record keeps its `merge-{model}-{record-id}`
identity as `context_id`, its title and text, and maps `infer` to `enrich`.
Records without an ID or remote ID are rejected in unified sync rather than
overwriting one another. Existing generated records have no separate metadata;
unsupported custom item fields are rejected rather than silently dropped.
Unified acknowledgment counts come from enveloped `data.success_count`, so
per-item failures aren't reported as accepted. Split transport and acknowledgment
handling remain unchanged.

This direct HTTP adapter needs no SDK release. No changes are made to the
Agent Handler MCP connector registration.

## Offline tests

From the repository root:

```bash
pip install -e "sync[test]"
python -m pytest -q
```

Tests mock HTTP; they never contact Merge or HydraDB.

## Also: HydraDB as a tool for Merge agents

The reverse direction lives in [`agent-handler/`](agent-handler/). It registers
HydraDB's hosted MCP server (`mcp.hydradb.com`) as a Merge Agent Handler Custom
MCP Connector, so agents built on Agent Handler can call HydraDB's recall,
ingest, and graph tools alongside Merge's connectors. See
[`agent-handler/README.md`](agent-handler/README.md) for the setup steps.

## License

MIT. See [LICENSE](LICENSE).
