"""Five-stage integration; synthetic model calls, real HTTP, snapshots, SVG and PDF rendering."""

import json
from pathlib import Path

from auto_figure.tests.test_figure import Runner, bundle, generate, wait
from auto_table.tests.test_application import fake_compile, file
from auto_table.tests.test_application import wait as wait_table
from workbench.tests.test_workbench import app as workbench_app
from workbench.tests.test_workbench import json_request, request

app = workbench_app


def ready_table(app):
    def table_runner(prompt, schema, directory, logs, name, job):
        if name == "design":
            return {
                "rationale": "Engineering fixture: preserve tables",
                "tables": [],
                "preamble": "",
                "replacements": [
                    {"filename": p.name, "content": p.read_text()}
                    for p in (directory / "inspection/original-tables").glob("*.tex")
                ],
            }
        return {
            "passed": True,
            "findings": ["Synthetic reviewer"],
            "inspected_pages": [str(p) for p in (directory / "patched/pages").glob("*.png")],
        }

    app.table.runner, app.table.compiler = table_runner, fake_compile
    p = app.table.create(
        {"title": "表格交接工程验收", "mode": "manuscript", "files": [file("paper.zip", bundle())]}
    )
    app.table.start(p["id"])
    p = wait_table(app.table, p["id"])
    assert p["status"] == "ready", p["message"]
    app.figure.runner, app.figure.generator, app.figure.compiler = Runner(), generate, fake_compile
    return p


def test_default_handoff_completion_and_downloads(app):
    table = ready_table(app)
    original = Path(table["outputs"][0]["zip"]).read_bytes()
    # Manual ticks make the handoff/recovery assertions deterministic.
    app.pipeline.close()
    flow = json_request(
        app, "/api/pipelines", {"start_stage": "table", "source_id": table["id"]}, status=201
    )
    assert flow["figure_enabled"]
    app.pipeline.tick()
    first = app.pipeline.get(flow["id"])
    assert first["stage"] == "figure" and first["figure_id"]
    figure_id = first["figure_id"]
    duplicate = app.figure.import_table({"project_id": table["id"], "pipeline_id": flow["id"]})
    assert duplicate["id"] == figure_id
    app.pipeline.tick()
    assert app.figure.load(figure_id)['status'] == 'awaiting_references'
    assert app.pipeline.get(flow['id'])['status'] == 'waiting_review'
    assert not app.figure.jobs
    app.figure.select_references(figure_id, {'confirm': True})
    app.pipeline.tick()
    assert wait(app.figure, figure_id)["status"] == "ready"
    app.pipeline.tick()
    assert app.pipeline.get(flow["id"])["status"] == "completed"
    assert Path(table["outputs"][0]["zip"]).read_bytes() == original
    assert app.figure.load(figure_id)["source"]["attempt"] == table["attempt"]
    detail = json_request(app, f"/auto-figure/api/projects/{figure_id}")
    for name in ("method-overview.pptx", "method-overview.pdf", "manuscript-with-figure.pdf", "manuscript-with-figure.zip"):
        code, _headers, data = request(
            app, f"/auto-figure/api/projects/{figure_id}/files/attempt-1/{name}"
        )
        assert code == 200 and data
    assert detail["review"]["passed"]
    assert json_request(app, "/api/runtime")["active_figures"] == []


def test_upstream_revision_invalidates_old_figure(app):
    table = ready_table(app)
    app.pipeline.close()
    flow = app.pipeline.create({"start_stage": "table", "source_id": table["id"]})
    app.pipeline.tick()
    old = app.pipeline.get(flow["id"])["figure_id"]
    table["attempt"] += 1
    app.table.save(table)
    app.pipeline.tick()
    assert app.figure.load(old)["status"] == "stale"
    assert app.pipeline.get(flow["id"])["stage"] == "table"
    app.pipeline.tick()
    assert app.pipeline.get(flow["id"])["figure_id"] != old
    assert len(app.figure.list()) == 2


def test_independent_upload_namespace_and_errors(app):
    from auto_figure.tests.test_figure import payload

    p = json_request(app, "/auto-figure/api/projects", payload(), status=201)
    assert p["source"] is None
    assert len(json_request(app, "/auto-figure/api/projects")["projects"]) == 1
    assert json_request(app, "/auto-table/api/projects")["projects"] == []
    json_request(app, "/auto-figure/api/import-table", {"project_id": "missing"}, status=400)
    assert request(app, f"/auto-figure/api/projects/{p['id']}/files/%2e%2e/%2e%2e/secret")[0] == 400


def test_legacy_completed_flow_is_not_migrated(app):
    from workbench.pipeline import PipelineManager

    app.pipeline.close()
    flow = {"id": "flow-legacy", "status": "completed", "stage": "table", "events": []}
    (app.pipeline.root / "flow-legacy.json").write_text(json.dumps(flow))
    recovered = PipelineManager(app.pipeline.root, app.workspace, app.design, app.table, app.figure)
    recovered.tick()
    assert recovered.get("flow-legacy")["status"] == "completed"
    assert not app.figure.list()


def test_blocked_figure_flow_observes_manual_review_retry(app):
    table=ready_table(app);app.pipeline.close()
    flow=app.pipeline.create({'start_stage':'table','source_id':table['id']})
    app.pipeline.tick();figure_id=app.pipeline.get(flow['id'])['figure_id']
    app.figure.runner.pass_review=False
    app.figure.select_references(figure_id,{'confirm':True});app.pipeline.tick()
    assert wait(app.figure,figure_id)['status']=='needs_revision'
    app.pipeline.tick();assert app.pipeline.get(flow['id'])['status']=='blocked'
    app.figure.runner.pass_review=True
    app.figure.start(figure_id,{'retry_review':True})
    assert wait(app.figure,figure_id)['status']=='ready'
    app.pipeline.tick();assert app.pipeline.get(flow['id'])['status']=='completed'
