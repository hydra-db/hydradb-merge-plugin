"""Sync records from Merge's unified API into HydraDB knowledge."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable

import requests

MERGE_BASE = "https://api.merge.dev/api"
HYDRADB_BASE = "https://api.hydradb.com"
MAX_ITEM_CHARS = 8000


@dataclass
class MergeConfig:
    api_key: str
    account_token: str
    base_url: str = MERGE_BASE


@dataclass
class HydraDBConfig:
    api_key: str
    database: str
    collection: str = ""
    base_url: str = HYDRADB_BASE


def _merge_headers(cfg: MergeConfig) -> dict[str, str]:
    """
    Build the Merge request headers.

    arg : cfg (MergeConfig) - Merge credentials.
    return : headers (dict) - Authorization and X-Account-Token headers.
    """
    return {
        "Authorization": f"Bearer {cfg.api_key}",
        "X-Account-Token": cfg.account_token,
    }


def _get_with_retry(
    http: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    retries: int = 4,
) -> requests.Response:
    """
    GET a Merge URL, backing off on rate limits and transient server errors.

    arg : http (requests.Session) - Session used for the request.
    arg : url (string) - Absolute URL to fetch.
    arg : headers (dict) - Request headers.
    arg : params (dict or None) - Query parameters, or None for a cursor URL.
    arg : retries (int) - Maximum number of backoff retries.
    return : response (requests.Response) - The successful response.
    """
    for attempt in range(retries + 1):
        resp = http.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == retries:
                resp.raise_for_status()
            wait = float(resp.headers.get("Retry-After") or (2**attempt))
            time.sleep(min(wait, 30))
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError("unreachable")


def fetch_records(
    cfg: MergeConfig,
    category: str,
    model: str,
    page_size: int = 100,
    modified_after: str | None = None,
    session: requests.Session | None = None,
) -> Iterable[dict[str, Any]]:
    """
    Yield every record of one Merge model, following cursor pagination.

    arg : cfg (MergeConfig) - Merge credentials.
    arg : category (string) - Merge vertical (ticketing, crm, hris, ats, ...).
    arg : model (string) - Plural object path (tickets, contacts, ...).
    arg : page_size (int) - Records per page.
    arg : modified_after (string or None) - ISO 8601 cutoff for an incremental pull.
    arg : session (requests.Session or None) - Optional reused session.
    return : records (iterable of dict) - One normalized record at a time.
    """
    http = session or requests.Session()
    url: str | None = f"{cfg.base_url}/{category}/v1/{model}"
    params: dict[str, Any] | None = {"page_size": page_size}
    if modified_after:
        params["modified_after"] = modified_after
    while url:
        resp = _get_with_retry(http, url, _merge_headers(cfg), params)
        body = resp.json()
        for record in body.get("results", []):
            yield record
        url = body.get("next")
        params = None


def record_to_item(record: dict[str, Any], model: str) -> dict[str, Any]:
    """
    Map a Merge record to a HydraDB knowledge item.

    arg : record (dict) - A normalized Merge record.
    arg : model (string) - The model the record belongs to.
    return : item (dict) - A HydraDB knowledge item with a stable id.
    """
    rid = str(record.get("id") or record.get("remote_id") or "")
    title = (
        record.get("name")
        or record.get("subject")
        or record.get("title")
        or f"{model[:-1] if model.endswith('s') else model} {rid}"[:120]
    )
    body = record.get("description") or record.get("body") or ""
    text = f"{title}\n\n{body}".strip() if body else json.dumps(record, default=str)
    if len(text) > MAX_ITEM_CHARS:
        text = text[: MAX_ITEM_CHARS - 1] + "…"
    return {
        "id": f"merge-{model}-{rid}",
        "title": str(title)[:120],
        "content": {"text": text},
        "infer": True,
    }


def ingest_items(
    cfg: HydraDBConfig,
    items: list[dict[str, Any]],
    batch_size: int = 50,
    session: requests.Session | None = None,
) -> int:
    """
    Ingest knowledge items into HydraDB in batches.

    arg : cfg (HydraDBConfig) - HydraDB credentials and scope.
    arg : items (list of dict) - Knowledge items to store.
    arg : batch_size (int) - Items per ingest request.
    arg : session (requests.Session or None) - Optional reused session.
    return : sent (int) - Number of items accepted for ingestion.
    """
    http = session or requests.Session()
    sent = 0
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        resp = http.post(
            f"{cfg.base_url}/context/ingest",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            files={
                "tenant_id": (None, cfg.database),
                "sub_tenant_id": (None, cfg.collection),
                "kind": (None, "knowledge"),
                "app_knowledge": (None, json.dumps(batch)),
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        if not body.get("success", False):
            raise RuntimeError(f"HydraDB ingest failed: {body.get('error')}")
        sent += len(batch)
    return sent


def sync(
    merge: MergeConfig,
    hydradb: HydraDBConfig,
    category: str,
    model: str,
    modified_after: str | None = None,
) -> int:
    """
    Pull one Merge model and ingest it into HydraDB.

    arg : merge (MergeConfig) - Merge credentials.
    arg : hydradb (HydraDBConfig) - HydraDB credentials and scope.
    arg : category (string) - Merge vertical.
    arg : model (string) - Plural object path.
    arg : modified_after (string or None) - ISO 8601 cutoff for an incremental sync.
    return : synced (int) - Number of records ingested.
    """
    items = [
        record_to_item(r, model)
        for r in fetch_records(merge, category, model, modified_after=modified_after)
    ]
    return ingest_items(hydradb, items)


def main() -> None:
    """
    Run a sync from environment variables and command-line arguments.

    return : none (None) - Prints the number of records synced.
    """
    import sys

    category = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MERGE_CATEGORY", "ticketing")
    model = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("MERGE_MODEL", "tickets")
    merge = MergeConfig(
        api_key=os.environ["MERGE_API_KEY"],
        account_token=os.environ["MERGE_ACCOUNT_TOKEN"],
    )
    hydradb = HydraDBConfig(
        api_key=os.environ["HYDRADB_API_KEY"],
        database=os.environ["HYDRADB_DATABASE"],
        collection=os.environ.get("HYDRADB_COLLECTION", ""),
    )
    count = sync(merge, hydradb, category, model, os.environ.get("MERGE_MODIFIED_AFTER"))
    print(f"Synced {count} {category}/{model} records into HydraDB.")


if __name__ == "__main__":
    main()
