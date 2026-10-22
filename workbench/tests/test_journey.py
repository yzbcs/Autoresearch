"""Journey projections must stay read-only and distinguish evidence from progress."""

import json
from pathlib import Path

from workbench.tests.test_workbench import app as workbench_app
from workbench.tests.test_workbench import json_request, request

app = workbench_app


def seed_flow(app, **overrides):
    flow = {
        "id": "flow-journey-test",
        "title": "Journey engineering fixture",
        "direction": "Engineering fixture, not research results",
        "stage": "search",
        "status": "paused",
        "message": "Engineering fixture paused",
        "created_at": "2026-10-22T01:00:00+00:00",
        "updated_at": "2026-10-22T01:00:00+00:00",
        "events": [],
        "figure_enabled": True,
        **overrides,
    }
    with app.pipeline.lock:
        app.pipeline.flows[flow["id"]] = flow
        app.pipeline.save(flow)
    return flow


def journey(app, flow):
    return json_request(app, f"/api/pipelines/{flow['id']}/journey")


def test_empty_journey_does_not_invent_metrics_or_write_records(app):
    flow = seed_flow(app)
    path = app.pipeline.root / f"{flow['id']}.json"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    result = journey(app, flow)
    assert all(value is None for value in result["metrics"].values())
    assert next(n for n in result["nodes"] if n["id"] == "execution")["status"] == "pending"
    assert result["events"] == []
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_resumed_writing_does_not_claim_skipped_upstream_is_complete(app):
    flow = seed_flow(app, stage="writing", writing_id="missing-writing")
    result = journey(app, flow)
    for name in ("papers", "design", "execution"):
        assert next(n for n in result["nodes"] if n["id"] == name)["status"] == "skipped"
    assert result["warnings"]


def test_design_progress_is_observed_cells_and_pending_diagnosis(app):
    task = app.design.create(
        "Engineering-only journey", "Motivation: fixture\nContribution: fixture", str(app.workspace)
    )
    root = Path(task["run_dir"])
    (root / "AUTODESIGN_STATE.md").write_text("| Current stage | EXECUTION_IN_PROGRESS |\n")
    (root / "result_summary.json").write_text(
        json.dumps({"status": "INCOMPLETE", "observed_cell_count": 2, "expected_cell_count": 6})
    )
    (root / "execution_record.json").write_text('{"commands": []}')
    flow = seed_flow(app, stage="design", design_id=task["id"])
    result = journey(app, flow)
    nodes = {n["id"]: n for n in result["nodes"]}
    assert nodes["design"]["status"] == "done"
    assert nodes["execution"]["status"] == "paused"
    assert nodes["diagnosis"]["status"] == "pending"
    assert result["metrics"]["experiments"]["done"] == 2
    assert result["metrics"]["experiments"]["total"] == 6
    assert nodes["execution"]["artifacts"][0]["name"] == "execution_record.json"
    (root / "result_summary.json").write_text('{"status":')
    assert journey(app, flow)["metrics"]["experiments"] is None


def test_real_r0_failure_adds_detour_and_legacy_flow_omits_figure(app):
    task = app.design.create(
        "Engineering-only R0", "Motivation: fixture\nContribution: fixture", str(app.workspace)
    )
    root = Path(task["run_dir"])
    (root / "AUTODESIGN_STATE.md").write_text("| Current stage | R0_FAILED_RETURN_TO_DESIGN |\n")
    flow = seed_flow(app, stage="design", design_id=task["id"], figure_enabled=False)
    result = journey(app, flow)
    assert next(n for n in result["nodes"] if n["id"] == "r0")["status"] == "blocked"
    assert {"source": "r0", "target": "design", "kind": "detour"} in result["edges"]
    assert "figure" not in [n["id"] for n in result["nodes"]]


def test_unknown_flow_and_mutations_rejected(app):
    status, _, _ = request(app, "/api/pipelines/unknown/journey")
    assert status == 400
    flow = seed_flow(app)
    status, _, _ = request(app, f"/api/pipelines/{flow['id']}/journey", {}, method="POST")
    assert status == 400
    assert app.pipeline.get(flow["id"])["status"] == "paused"


def test_journey_page_and_assets_are_served(app):
    for path in (
        "/journey.html",
        "/journey.css",
        "/journey.js",
        "/journey-i18n.js",
        "/shell.css",
        "/layout.css",
        "/vendor/svg-pan-zoom/svg-pan-zoom.min.js",
    ):
        status, _, data = request(app, path)
        assert status == 200
        assert data


def test_search_counts_and_candidates_use_saved_records(app):
    root = app.data_dir / "auto_search" / "direction-20261022-090000-abcdef"
    root.mkdir()
    (root / "manifest.snapshot.json").write_text(
        json.dumps({"papers": [{"title": "A"}, {"title": "B"}]})
    )
    (root / "web-data.json").write_text(
        json.dumps(
            {
                "ideas": [
                    {"id": "idea-a", "idea_title": "A"},
                    {"id": "idea-b", "idea_title": "B"},
                    None,
                ]
            }
        )
    )
    (root / "human_review.json").write_text('{"idea-a": "discarded"}')
    flow = seed_flow(app, search_run=root.name, idea_id="idea-b")
    result = journey(app, flow)
    assert result["metrics"]["papers"] == 2
    assert result["metrics"]["ideas"] == 2
    assert next(n for n in result["nodes"] if n["id"] == "idea-0")["status"] == "done"
    assert next(n for n in result["nodes"] if n["id"] == "idea-1")["status"] == "skipped"


def test_event_order_handles_different_timezones(app):
    flow = seed_flow(
        app,
        events=[
            {"at": "2026-10-22T09:00:00+08:00", "stage": "search", "message": "earlier"},
            {"at": "2026-10-22T05:00:00+00:00", "stage": "search", "message": "later"},
        ],
    )
    assert [e["message"] for e in journey(app, flow)["events"]] == ["earlier", "later"]
