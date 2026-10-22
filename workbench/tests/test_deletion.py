"""Deletion tests use disposable engineering tasks and never run models."""

import base64
import json
from pathlib import Path
from types import SimpleNamespace

from auto_figure.tests.test_figure import payload
from workbench.tests.test_journey import seed_flow
from workbench.tests.test_workbench import app as workbench_app
from workbench.tests.test_workbench import json_request, new_writing, request

app = workbench_app


def design(app):
    return app.design.create(
        "Disposable engineering fixture",
        "Motivation: fixture\nContribution: fixture",
        str(app.workspace),
    )


def erase(app, module, identity, status=200):
    return json_request(app, f"/api/items/{module}/{identity}", method="DELETE", status=status)


def test_design_deletion_removes_owned_files_and_index_but_keeps_workspace(app):
    task = design(app)
    outside = app.workspace / "keep.txt"
    outside.write_text("keep")
    result = erase(app, "design", task["id"])
    assert result["deleted"] and not result["cleanup_pending"]
    assert not Path(task["run_dir"]).exists()
    assert task["id"] not in app.design.tasks
    assert outside.read_text() == "keep"
    assert task["id"] not in json.loads(app.design.index_path.read_text())


def test_all_module_files_removed_through_native_and_shared_routes(app):
    search = app.data_dir / "auto_search" / "direction-20261023-010000-abcdef"
    search.mkdir()
    (search / "job.json").write_text('{"status":"ready"}')
    writing = new_writing(app)
    table = app.table.create(
        {
            "title": "Disposable table",
            "mode": "results",
            "files": [
                {
                    "name": "results.csv",
                    "content_base64": base64.b64encode(b"method,score\nfixture,1\n").decode(),
                }
            ],
        }
    )
    figure = app.figure.create(payload())
    logs = app.table.log_root / table["id"]
    logs.mkdir(parents=True)
    (logs / "fixture.log").write_text("fixture")
    for module, identity, url in [
        ("search", search.name, f"/auto-search/api/runs/{search.name}"),
        ("writing", writing["id"], f"/auto-writing/api/writings/{writing['id']}"),
        ("table", table["id"], f"/auto-table/api/projects/{table['id']}"),
        ("figure", figure["id"], f"/auto-figure/api/projects/{figure['id']}"),
    ]:
        assert json_request(app, url, method="DELETE")["deleted"]
    assert not search.exists()
    assert not (app.data_dir / "auto_writing" / writing["id"]).exists()
    assert not app.table.directory(table["id"]).exists()
    assert not (app.table.input_root / table["id"]).exists()
    assert not logs.exists()
    assert not app.figure.directory(figure["id"]).exists()


def test_active_or_referenced_task_cannot_be_deleted(app):
    task = design(app)
    app.design.update(task["id"], status="running")
    assert "暂停" in erase(app, "design", task["id"], 400)["error"]
    app.design.update(task["id"], status="paused")
    flow = seed_flow(app, stage="design", design_id=task["id"])
    assert "全流程" in erase(app, "design", task["id"], 400)["error"]
    assert Path(task["run_dir"]).exists() and app.pipeline.get(flow["id"])


def test_pipeline_deletion_preserves_shared_tasks_and_deletes_exclusive_files(app):
    exclusive, shared = design(app), design(app)
    # Shared search folder is referenced by both records.
    root = app.data_dir / "auto_search" / "direction-20261023-010001-abcdef"
    root.mkdir()
    flow = seed_flow(app, design_id=exclusive["id"], search_run=root.name)
    other = seed_flow(app, id="flow-another", design_id=shared["id"], search_run=root.name)
    result = erase(app, "pipeline", flow["id"])
    assert result["shared_preserved"] == [{"module": "search", "id": root.name}]
    assert root.exists() and Path(shared["run_dir"]).exists()
    assert not Path(exclusive["run_dir"]).exists()
    assert not (app.pipeline.root / (flow["id"] + ".json")).exists()
    assert app.pipeline.get(other["id"])


def test_preflight_failure_keeps_every_task_and_flow(app):
    task = design(app)
    root = app.data_dir / "auto_search" / "direction-20261023-010002-abcdef"
    root.mkdir()
    flow = seed_flow(app, search_run=root.name, design_id=task["id"])
    app.design.update(task["id"], status="running")
    erase(app, "pipeline", flow["id"], 400)
    assert root.exists() and Path(task["run_dir"]).exists()
    assert app.pipeline.get(flow["id"])


def test_symlink_external_directory_and_live_workers_are_protected(app):
    task = design(app)
    original = Path(task["run_dir"])
    outside = app.workspace / "external"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    app.design.update(task["id"], run_dir=str(outside))
    erase(app, "design", task["id"], 400)
    app.design.update(task["id"], run_dir=str(original))
    app.design.threads[task["id"]] = SimpleNamespace(is_alive=lambda: True)
    erase(app, "design", task["id"], 400)
    app.design.threads.pop(task["id"])
    moved = original.with_name("original")
    original.rename(moved)
    original.symlink_to(outside, target_is_directory=True)
    erase(app, "design", task["id"], 400)
    assert original.is_symlink() and (outside / "keep.txt").exists()


def test_file_move_failure_rolls_back(app, monkeypatch):
    task = design(app)
    flow = seed_flow(app, design_id=task["id"])
    rename = Path.rename

    def fail_flow(path, target):
        if path.name == flow["id"] + ".json":
            raise OSError("engineering failure")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_flow)
    erase(app, "pipeline", flow["id"], 400)
    assert Path(task["run_dir"]).exists()
    assert app.design.get(task["id"])
    assert app.pipeline.get(flow["id"])


def test_delete_assets_and_injection(app):
    for path in ("/list-actions.js", "/list-actions.css"):
        assert request(app, path)[0] == 200
    for name in ("search", "design", "writing", "table", "figure"):
        assert b"/list-actions.js" in request(app, f"/auto-{name}/")[2]


def test_search_symlink_to_another_task_never_deletes_target(app):
    root = app.data_dir / "auto_search"
    target = root / "direction-20261023-010010-abcdef"
    alias = root / "direction-20261023-010011-abcdef"
    target.mkdir()
    (target / "keep.json").write_text("{}")
    alias.symlink_to(target, target_is_directory=True)
    erase(app, "search", alias.name, 400)
    assert alias.is_symlink() and (target / "keep.json").is_file()


def test_running_pipeline_cannot_be_deleted(app):
    flow = seed_flow(app, status="running")
    erase(app, "pipeline", flow["id"], 400)
    assert (app.pipeline.root / (flow["id"] + ".json")).exists()


def test_staging_directory_cannot_redirect_files_outside_storage(app):
    task = design(app)
    original = Path(task["run_dir"])
    outside = app.workspace / "outside-cleanup"
    outside.mkdir()
    (original.parent / ".deleted").symlink_to(outside, target_is_directory=True)
    erase(app, "design", task["id"], 400)
    assert original.exists() and not list(outside.iterdir())
    assert app.design.get(task["id"])
