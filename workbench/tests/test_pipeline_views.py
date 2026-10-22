"""Homepage read models remain available while orchestration is busy."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from workbench.pipeline import PipelineManager
from workbench.tests.test_journey import seed_flow
from workbench.tests.test_workbench import app as workbench_app
from workbench.tests.test_workbench import json_request, request

app = workbench_app


def test_summary_and_detail_do_not_wait_for_orchestration_lock(app, monkeypatch):
    app.pipeline.close()
    flow = seed_flow(app, status="running", stage="design")
    entered, release = threading.Event(), threading.Event()

    def blocked_step(_):
        entered.set()
        release.wait(5)

    monkeypatch.setattr(app.pipeline, "advance_design", blocked_step)
    worker = threading.Thread(target=app.pipeline.tick)
    worker.start()
    try:
        assert entered.wait(1)
        with ThreadPoolExecutor() as executor:
            future = executor.submit(json_request, app, "/api/pipelines?summary=1")
            try:
                result = future.result(timeout=1)
                assert result["pipelines"][0]["id"] == flow["id"]
                assert (
                    json_request(app, f"/api/pipelines/{flow['id']}?summary=1")["status"]
                    == "running"
                )
            finally:
                release.set()
    finally:
        release.set()
        worker.join(2)


def test_compact_list_has_no_history_payload_but_default_api_remains_compatible(app):
    events = [
        {"at": str(i), "stage": "search", "message": "engineering fixture " * 20}
        for i in range(10000)
    ]
    flow = seed_flow(app, events=events)
    status, _, payload = request(app, "/api/pipelines?summary=1")
    assert status == 200 and len(payload) < 2000
    compact = json.loads(payload)["pipelines"][0]
    assert compact["event_count"] == 10000 and "events" not in compact
    full = json_request(app, "/api/pipelines")["pipelines"][0]
    assert full["events"] == events and full["id"] == flow["id"]


def test_history_is_paginated_without_losing_events_and_can_be_exported(app):
    events = [{"at": str(i), "message": f"fixture-{i}"} for i in range(501)]
    flow = seed_flow(app, events=events)
    base = f"/api/pipelines/{flow['id']}/events"
    last = json_request(app, base)
    middle = json_request(app, base + f"?before={last['before']}")
    first = json_request(app, base + f"?before={middle['before']}")
    assert first["events"] + middle["events"] + last["events"] == events
    assert first["before"] is None and last["total"] == 501
    assert json_request(app, base + "?all=1")["events"] == events
    assert request(app, base + "?before=bad")[0] == 400


def test_saved_view_is_isolated_and_tracks_updates_and_restart(app):
    flow = seed_flow(app, events=[{"message": "original"}])
    view = app.pipeline.get_view(flow["id"])
    view["events"][0]["message"] = "changed by reader"
    assert app.pipeline.get_view(flow["id"])["events"][0]["message"] == "original"
    with app.pipeline.lock:
        app.pipeline.update(flow, "blocked", "Fixture needs attention")
    assert app.pipeline.list(summary=True)[0]["message"] == "Fixture needs attention"
    restarted = PipelineManager(app.pipeline.root, app.workspace, app.design, app.table, app.figure)
    assert restarted.get_view(flow["id"])["status"] == "blocked"


def test_detail_skips_candidate_disk_reads_when_not_selecting(app, monkeypatch):
    flow = seed_flow(app)

    def unexpected(_):
        raise AssertionError("No candidate scan needed")

    monkeypatch.setattr(app.pipeline, "candidates", unexpected)
    assert json_request(app, f"/api/pipelines/{flow['id']}?summary=1")["candidates"] == []
