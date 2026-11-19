import json

import pytest
import requests
import responses

from sync.merge_to_hydradb import HydraDBConfig, MergeConfig, ingest_items, main, record_to_item, sync

BASE = "https://api.hydradb.com"


def config(**kwargs):
    return HydraDBConfig("offline-key", "db", collection="col", **kwargs)


@pytest.mark.parametrize("layout", ["auto", "UNIFIED", "", None])
def test_invalid_layout_is_rejected(layout):
    with pytest.raises(ValueError, match="layout"):
        config(layout=layout)


@responses.activate
def test_unified_write_uses_json_context_and_stable_record_ids():
    responses.add(responses.POST, BASE + "/context/ingest",
                  json={"success": True, "data": {"success_count": 1, "failed_count": 0,
                        "results": [{"id": "merge-tickets-123", "status": "queued"}]}}, status=202)
    item = record_to_item({"id": "123", "name": "Ticket", "description": "body"}, "tickets")
    assert ingest_items(config(layout="unified"), [item]) == 1
    request = responses.calls[0].request
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.body) == {
        "database": "db", "collection": "col", "context": [
            {"context_id": "merge-tickets-123", "title": "Ticket", "text": "Ticket\n\nbody", "enrich": True}
        ],
    }


@responses.activate
def test_unified_partial_ack_counts_only_accepted_items(capsys):
    responses.add(responses.POST, BASE + "/context/ingest", json={"success": True, "data": {
        "success_count": 1, "failed_count": 1, "results": [
            {"id": "merge-tickets-1", "status": "queued", "error": None},
            {"id": "merge-tickets-2", "status": "failed", "error": "invalid"},
        ],
    }}, status=202)
    items = [record_to_item({"id": str(n), "name": "Ticket"}, "tickets") for n in [1, 2]]
    assert ingest_items(config(layout="unified"), items) == 1
    assert "merge-tickets-2" in capsys.readouterr().err


@responses.activate
def test_unified_batches_and_enveloped_count_acknowledgments():
    for count in [2, 1]:
        responses.add(responses.POST, BASE + "/context/ingest",
                      json={"success": True, "data": {"success_count": count, "failed_count": 0, "results": []}}, status=202)
    items = [record_to_item({"id": str(n), "name": "Ticket"}, "tickets") for n in range(3)]
    assert ingest_items(config(layout="unified"), items, batch_size=2) == 3
    assert [len(json.loads(call.request.body)["context"]) for call in responses.calls] == [2, 1]


@responses.activate
def test_split_transport_and_acceptance_accounting_stay_unchanged():
    responses.add(responses.POST, BASE + "/context/ingest",
                  json={"success": True, "results": [{"id": "merge-tickets-1", "status": "queued"}]})
    assert ingest_items(config(), [record_to_item({"id": "1", "name": "Ticket"}, "tickets")]) == 1
    request = responses.calls[0].request
    assert "multipart/form-data" in request.headers["Content-Type"]
    assert b'app_knowledge' in request.body
    assert b'name="type"' in request.body
    assert b'knowledge' in request.body


@pytest.mark.parametrize("layout", ["split", "unified"])
@responses.activate
def test_failed_write_is_not_retried_in_another_layout(layout):
    responses.add(responses.POST, BASE + "/context/ingest", json={"success": False, "error": "no"}, status=400)
    with pytest.raises(requests.HTTPError):
        ingest_items(config(layout=layout), [record_to_item({"id": "1"}, "tickets")])
    assert len(responses.calls) == 1


def test_sync_rejects_missing_record_identity_only_for_unified(monkeypatch):
    monkeypatch.setattr("sync.merge_to_hydradb.fetch_records", lambda *args, **kwargs: iter([{"name": "no id"}]))
    with pytest.raises(ValueError, match="id"):
        sync(MergeConfig("k", "account"), config(layout="unified"), "ticketing", "tickets")
    assert record_to_item({"name": "no id"}, "tickets")["id"] == "merge-tickets-"


@pytest.mark.parametrize("item", [
    {"id": "stable", "content": {"text": "body"}, "metadata": {"unsupported": "must not disappear"}},
    {"id": "stable", "content": {"text": "body", "html_base64": "unsupported"}},
    {"id": "", "content": {"text": "body"}},
])
@responses.activate
def test_unified_custom_items_fail_before_http_instead_of_losing_fields(item):
    with pytest.raises(ValueError):
        ingest_items(config(layout="unified"), [item])
    assert not responses.calls


def test_unified_remote_id_fallback_is_stable_and_text_limits_are_preserved():
    record = {"remote_id": "remote-123", "name": "Title", "description": "x" * 9000}
    first = record_to_item(record, "tickets", layout="unified")
    assert first == record_to_item(record, "tickets", layout="unified")
    assert first["id"] == "merge-tickets-remote-123"
    assert len(first["content"]["text"]) == 8000


@responses.activate
def test_unified_missing_acceptance_count_is_not_reported_as_success():
    responses.add(responses.POST, BASE + "/context/ingest",
                  json={"success": True, "data": {}}, status=202)
    with pytest.raises(RuntimeError, match="success_count"):
        ingest_items(config(layout="unified"), [record_to_item({"id": "1"}, "tickets")])
    assert len(responses.calls) == 1


def test_main_reads_explicit_layout_from_existing_environment_config(monkeypatch, capsys):
    for key, value in {"MERGE_API_KEY": "k", "MERGE_ACCOUNT_TOKEN": "a", "HYDRADB_API_KEY": "k",
                       "HYDRADB_DATABASE": "db", "HYDRADB_LAYOUT": "unified"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.argv", ["merge_to_hydradb.py", "ticketing", "tickets"])
    def fake_sync(merge, hydradb, *args):
        assert hydradb.layout == "unified"
        return 1
    monkeypatch.setattr("sync.merge_to_hydradb.sync", fake_sync)
    main()
    assert capsys.readouterr().out == "Synced 1 ticketing/tickets records into HydraDB.\n"
