"""Integration checks use real HTTP and files, with explicit engineering-only model fixtures."""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from auto_design.tests import test_application as design_examples
from auto_search.tests import test_direction_research as search_examples
from auto_search.tests import test_generate_idea as idea_examples
from auto_search.tests import test_research_pipeline as evaluation_examples
from auto_writing.tests import test_web as writing_examples
from workbench.server import MODULES, Workbench, search, writing


def request(app, path, value=None, method=None):
    data = json.dumps(value).encode("utf-8") if value is not None else None
    req = Request(
        f"http://127.0.0.1:{app.server.server_port}" + quote(path, safe="/%?=&"),
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        response = urlopen(req, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def json_request(app, path, value=None, method=None, status=200):
    actual_status, headers, body = request(app, path, value, method)
    assert actual_status == status, body.decode("utf-8", errors="replace")
    assert "application/json" in headers["Content-Type"]
    return json.loads(body)


def await_condition(callback):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = callback()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError("Engineering fixture did not finish")


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Each test is a separate workspace and index. No normal task is created or executed.
    monkeypatch.setattr(search, "RUNS_ROOT", tmp_path / "search")
    monkeypatch.setattr(writing, "WRITING_RUNS_ROOT", tmp_path / "writing")
    monkeypatch.setattr(search, "JOB_MANAGER", search.JobManager())
    monkeypatch.setattr(writing, "GENERATION_MANAGER", writing.GenerationManager())
    instance = Workbench(tmp_path, tmp_path / "assets/output/workbench", port=0)
    instance.design.runner = design_examples.DesignRunner()
    instance.start_modules()
    thread = threading.Thread(target=instance.server.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.server.shutdown()
        instance.close()
        thread.join(5)


def new_design(app, **overrides):
    payload = {
        "title": "工程验收：不产生科学结果",
        "idea": "Motivation: integration test\nContribution: engineering verification",
        "scope": "design_only",
        **overrides,
    }
    return json_request(app, "/auto-design/api/tasks", payload, status=201)


def new_writing(app):
    return json_request(
        app,
        "/auto-writing/api/writings",
        {
            "title": "工程写作验收",
            "experiment_file": writing_examples.encoded_file(
                "实验说明.md", "Engineering test only. 无科研结论。\n".encode()
            ),
            "support_files": [writing_examples.encoded_file("notes.txt", b"support fixture")],
        },
        status=201,
    )


@pytest.mark.parametrize("module", MODULES)
def test_module_pages_assets_navigation_and_health(app, module):
    status, headers, body = request(app, f"/{module}/?view=initial")
    assert status == 200
    assert int(headers["Content-Length"]) == len(body)
    assert f'data-module="{module}"'.encode() in body
    assert b"/module-nav.js" in body and b"/module-nav.css" in body
    assert b"iframe" not in body
    for asset in ("app.js", "styles.css", "assets/the-thainker-logo.png"):
        assert request(app, f"/{module}/{asset}")[0] == 200
    head_status, head_headers, head_body = request(app, f"/{module}/", method="HEAD")
    assert head_status == 200 and head_body == b""
    assert int(head_headers["Content-Length"]) == len(body)
    assert json_request(app, f"/{module}/api/health")["status"] == "ok"
    assert request(app, f"/{module}")[0] == 200  # canonical slash redirect


def test_home_and_namespaces_stay_separate(app):
    assert b"AutoResearch" in request(app, "/")[2]
    assert b"aria-label" in request(app, "/module-nav.js")[2]
    assert json_request(app, "/auto-search/api/runs") == {"runs": []}
    assert json_request(app, "/auto-design/api/tasks") == {"tasks": []}
    assert json_request(app, "/auto-writing/api/writings") == {"writings": []}
    design, paper = new_design(app), new_writing(app)
    assert len(json_request(app, "/auto-design/api/tasks")["tasks"]) == 1
    assert len(json_request(app, "/auto-writing/api/writings")["writings"]) == 1
    assert json_request(app, "/auto-search/api/runs")["runs"] == []
    assert request(app, f"/auto-writing/api/tasks/{design['id']}")[0] == 404
    assert request(app, f"/auto-search/api/writings/{paper['id']}")[0] == 404


def test_design_start_and_files_work_under_module_path(app):
    task = new_design(app)
    base = f"/auto-design/api/tasks/{task['id']}"
    json_request(app, base + "/start", {}, status=202)
    assert design_examples.wait_idle(app.design, task["id"])["status"] == "design_ready"
    detail = json_request(app, base)
    assert detail["documents"]["experiment_design.md"]
    assert detail["scope"] == "design_only"
    assert app.design.runner.actions == ["design"]
    assert request(app, base + "/files/AUTODESIGN_STATE.md")[0] == 200
    directory = Path(task["run_dir"])
    (directory / "reports").mkdir()
    (directory / "reports/index.html").write_text('<img src="图 表.png">')
    image = b"engineering fixture binary\x00\x01\xff"
    (directory / "reports/图 表.png").write_bytes(image)
    assert (
        request(app, base + "/files/reports/index.html")[2]
        == b'<img src="\xe5\x9b\xbe \xe8\xa1\xa8.png">'
    )
    assert request(app, base + "/files/reports/" + quote("图 表.png"))[2] == image
    assert request(app, base + "/files/reports/index.html")[2].count(b"module-nav") == 0


def test_design_pause_resume_import_and_decision_routes(app, tmp_path):
    entered, release = threading.Event(), threading.Event()
    app.design.runner = design_examples.DesignRunner(entered, release)
    task = new_design(app)
    base = f"/auto-design/api/tasks/{task['id']}"
    try:
        json_request(app, base + "/start", {}, status=202)
        assert entered.wait(5)
        assert json_request(app, base + "/pause", {}, status=202)["status"] == "pausing"
    finally:
        release.set()
    assert design_examples.wait_idle(app.design, task["id"])["status"] == "paused"
    app.design.runner = design_examples.DesignRunner()
    json_request(app, base + "/resume", {}, status=202)
    assert design_examples.wait_idle(app.design, task["id"])["status"] == "design_ready"

    review_task = new_design(app)
    design_examples.prepare_review(app.design, review_task)
    review_base = f"/auto-design/api/tasks/{review_task['id']}/decision"
    json_request(
        app, review_base, {"revision_id": "wrong", "decision": "REJECT_METHOD_REVISION"}, status=400
    )
    json_request(
        app, review_base, {"revision_id": "MR-1", "decision": "REJECT_METHOD_REVISION"}, status=202
    )
    assert app.design.get(review_task["id"])["status"] == "paused"
    assert app.design.get(review_task["id"])["attempts"] == []

    external = design_examples.TaskManager(tmp_path / "external-index")
    existing = design_examples.create_task(external, tmp_path)
    imported = json_request(
        app,
        "/auto-design/api/tasks/import",
        {"title": "Imported fixture", "run_dir": existing["run_dir"], "workspace": str(tmp_path)},
        status=201,
    )
    assert imported["status"] == "paused"
    assert imported["run_dir"] == existing["run_dir"]
    assert imported["attempts"] == []


def test_writing_upload_edit_dependencies_and_delete(app):
    project = new_writing(app)
    base = f"/auto-writing/api/writings/{project['id']}"
    assert Path(project["experiment"]["path"]).read_text().endswith("无科研结论。\n")
    assert len(project["sections"]) == 6
    assert {item["key"] for item in project["actions"]} == set(writing.RESEARCH_ACTIONS)
    updated = json_request(
        app,
        base,
        {
            "title": "Edited fixture",
            "retained_support_paths": [],
            "experiment_file": writing_examples.encoded_file("replacement.txt", b"new fixture"),
            "new_support_files": [writing_examples.encoded_file("table.csv", b"a,b\n1,2\n")],
        },
        method="PUT",
    )
    assert updated["title"] == "Edited fixture"
    assert Path(updated["experiment"]["path"]).read_bytes() == b"new fixture"
    assert [item["name"] for item in updated["support_files"]] == ["table.csv"]
    blocked = json_request(app, base + "/sections/intro/generate", {}, status=409)
    assert "intro_research" in json.dumps(blocked)
    json_request(app, base + "/actions/related_work_plan/run", {}, status=409)
    json_request(app, base + "/publication/build", {}, status=409)
    json_request(app, base, method="DELETE")
    assert json_request(app, "/auto-writing/api/writings")["writings"] == []


def test_writing_research_and_generation_through_http(app, monkeypatch):
    project = new_writing(app)
    base = f"/auto-writing/api/writings/{project['id']}"
    examples = writing_examples.AutoWritingWebTests()
    research = examples.intro_research_result()
    monkeypatch.setattr(writing, "invoke_codex_json", lambda *args, **kwargs: research)
    json_request(app, base + "/actions/intro_research/run", {}, status=202)
    await_condition(
        lambda: (
            writing.load_project(project["id"])["research"]["intro_research"]["status"] != "running"
        )
    )
    assert writing.load_project(project["id"])["research"]["intro_research"]["status"] == "ready"
    content = "\\section{Introduction}\nThis engineering fixture contains enough English text to exercise the complete HTTP generation route and deterministic output validation without making any scientific claim."
    monkeypatch.setattr(writing, "invoke_codex", lambda *args, **kwargs: content)
    json_request(app, base + "/sections/intro/generate", {}, status=202)
    await_condition(
        lambda: writing.load_project(project["id"])["sections"]["intro"]["status"] != "running"
    )
    detail = json_request(app, base)
    assert detail["sections"][0]["content"] == content
    assert detail["reference"]["reference_count"] == 7


def test_writing_binary_downloads_and_cancel_routing(app, monkeypatch):
    project = new_writing(app)
    base = f"/auto-writing/api/writings/{project['id']}"
    directory = writing.WRITING_RUNS_ROOT / project["id"] / "publication"
    directory.mkdir()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("main.tex", "Engineering-only transport fixture")
    (directory / "manuscript-latex.zip").write_bytes(archive.getvalue())
    pdf = b"%PDF-1.4\n% Engineering download fixture\n\x00\xff\n%%EOF\n"
    (directory / "manuscript.pdf").write_bytes(pdf)
    detail = json_request(app, base)
    for kind, expected in (("latex", archive.getvalue()), ("pdf", pdf)):
        status, headers, body = request(app, base + "/publication/download/" + kind)
        assert status == 200 and body == expected
        assert int(headers["Content-Length"]) == len(expected)
        assert "attachment" in headers["Content-Disposition"]
    assert detail["publication"]["pdf_url"].endswith("/publication/download/pdf")
    calls = []
    monkeypatch.setattr(
        writing.GENERATION_MANAGER, "cancel", lambda job_id: calls.append(job_id) or True
    )
    json_request(app, "/auto-writing/api/generation/123456abcdef/cancel", {})
    assert calls == ["123456abcdef"]


def test_search_pipeline_review_and_delete_through_http(app, monkeypatch):
    papers = [search_examples.paper_record(f"Integration fixture {i}") for i in range(2)]
    manifest = search.direction_research.build_manifest(
        "Engineering verification", {"scope_summary": "Fixture only", "papers": papers}, 2
    )
    monkeypatch.setattr(
        search.direction_research, "execute_research_agent", lambda *a, **k: manifest
    )
    monkeypatch.setattr(
        search.research_pipeline.generate_idea,
        "run_codex",
        lambda *a, **k: idea_examples.VALID_MARKDOWN,
    )
    ids = [paper["id"] for paper in manifest["papers"]]
    monkeypatch.setattr(
        search.research_pipeline,
        "execute_json_agent",
        lambda *a, **k: evaluation_examples.evaluation(ids),
    )
    job = json_request(
        app,
        "/auto-search/api/jobs",
        {"direction": "工程验收，不作为科研证据", "paper_count": 2, "evaluate": True},
        status=202,
    )
    assert search.JOB_MANAGER.get(job["id"]).finished_event.wait(8)
    finished = json_request(app, f"/auto-search/api/jobs/{job['id']}")
    assert finished["status"] == "ready", finished
    dataset = json_request(app, f"/auto-search/api/jobs/{job['id']}/ideas")
    assert len(dataset["ideas"]) == 2
    assert [item["title"] for item in dataset["ideas"][0]["causes"]] == [
        "Detail dilution",
        "Scale mismatch",
        "Training imbalance",
    ]
    assert all(idea["review"]["verdict"] == "promising" for idea in dataset["ideas"])
    run_url = f"/auto-search/api/runs/{finished['run_name']}"
    assert json_request(app, run_url + "/ideas")["run_name"] == finished["run_name"]
    review_url = run_url + f"/ideas/{ids[0]}/human-review"
    json_request(app, review_url, {"decision": "approved"}, method="PUT")
    assert json_request(app, run_url + "/ideas")["ideas"][0]["human_review"] == "approved"
    json_request(app, review_url, {"decision": None}, method="PUT")
    assert json_request(app, run_url + "/ideas")["ideas"][0]["human_review"] is None
    json_request(app, run_url, method="DELETE")
    assert json_request(app, "/auto-search/api/runs")["runs"] == []


def test_search_cancel_and_cli_missing_are_reported(app, monkeypatch):
    def blocked_research(*args, cancel_event, **kwargs):
        assert cancel_event.wait(8)
        raise RuntimeError("Cancelled engineering fixture")

    monkeypatch.setattr(search.direction_research, "execute_research_agent", blocked_research)
    job = json_request(
        app,
        "/auto-search/api/jobs",
        {"direction": "取消路径工程验收", "paper_count": 2},
        status=202,
    )
    assert json_request(app, f"/auto-search/api/jobs/{job['id']}/cancel", {})["deleted"]
    assert json_request(app, "/auto-search/api/runs")["runs"] == []

    def missing_cli():
        raise RuntimeError("CLI missing")

    monkeypatch.setattr(search.direction_research.generate_idea, "resolve_codex_cli", missing_cli)
    assert json_request(app, "/auto-search/api/health")["codex_cli"] is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture")
def test_search_processes_use_each_task_directory(app, tmp_path, monkeypatch):
    papers = [search_examples.paper_record(f"Directory fixture {i}") for i in range(2)]
    research = {"scope_summary": "Engineering fixture only", "papers": papers}
    manifest = search.direction_research.build_manifest("Directory check", research, 2)
    responses = tmp_path / "fixture-responses.json"
    responses.write_text(
        json.dumps(
            {
                "direction_research.schema.json": research,
                "idea": idea_examples.VALID_MARKDOWN,
                "evaluation.schema.json": evaluation_examples.evaluation(
                    [paper["id"] for paper in manifest["papers"]]
                ),
            }
        )
    )
    executable = tmp_path / "codex-directory-fixture"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json,sys\nfrom pathlib import Path\n"
        "if '--version' in sys.argv:\n"
        "    print('codex engineering fixture'); sys.exit(0)\n"
        "sys.stdin.read()\n"
        "stage = Path(sys.argv[sys.argv.index('--output-schema')+1]).name "
        "if '--output-schema' in sys.argv else 'idea'\n"
        f"responses = json.loads(Path({str(responses)!r}).read_text())\n"
        "record = {'stage':stage, 'cwd':str(Path.cwd()), "
        "'cd':sys.argv[sys.argv.index('--cd')+1]}\n"
        "with Path('directory-observations.jsonl').open('a') as log:\n"
        "    log.write(json.dumps(record)+'\\n')\n"
        "output = Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
        "value = responses[stage]\n"
        "output.write_text(value if isinstance(value,str) else json.dumps(value))\n"
    )
    executable.chmod(0o755)
    monkeypatch.setattr(
        search.direction_research.generate_idea,
        "codex_candidates",
        lambda: [Path(os.path.relpath(executable))],
    )
    directories = []
    for _ in range(2):
        job = json_request(
            app,
            "/auto-search/api/jobs",
            {"direction": "执行目录工程验收", "paper_count": 2, "evaluate": True},
            status=202,
        )
        live_job = search.JOB_MANAGER.get(job["id"])
        assert live_job.finished_event.wait(8)
        assert live_job.status == "ready", live_job.error
        directory = live_job.run_dir.resolve()
        directories.append(directory)
        observed = [
            json.loads(line)
            for line in (directory / "directory-observations.jsonl").read_text().splitlines()
        ]
        assert [item["stage"] for item in observed] == [
            "direction_research.schema.json",
            "idea",
            "idea",
            "evaluation.schema.json",
        ]
        assert all(item["cwd"] == item["cd"] == str(directory) for item in observed)
        assert (directory / "web-data.json").is_file()
    assert directories[0] != directories[1]


def test_writing_cli_uses_isolated_config_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(writing, "WRITING_RUNS_ROOT", tmp_path)
    project = {"id": "writing-fixture"}
    (tmp_path / project["id"] / "prompts").mkdir(parents=True)
    monkeypatch.delenv("CODEX_IGNORE_USER_CONFIG", raising=False)
    monkeypatch.setattr(writing, "resolve_codex_cli", lambda: Path("codex"))
    commands = []

    class Process:
        returncode = 0

        def __init__(self, command, **kwargs):
            commands.append(command)

        def communicate(self, **kwargs):
            command = commands[-1]
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text('{"ok":true}')
            return "", ""

    monkeypatch.setattr(writing.subprocess, "Popen", Process)
    response = writing.invoke_codex_json(
        project, "smoke", "Engineering fixture", tmp_path / "schema.json"
    )
    assert response == {"ok": True}
    assert "--ignore-user-config" in commands[-1]
    assert "--ephemeral" in commands[-1]
    monkeypatch.setenv("CODEX_IGNORE_USER_CONFIG", "0")
    writing.invoke_codex_json(project, "smoke", "Engineering fixture", tmp_path / "schema.json")
    assert "--ignore-user-config" not in commands[-1]


def test_table_upload_generate_preview_and_download_under_prefix(app):
    from auto_table.tests.test_application import Runner, fake_compile, payload

    app.table.runner = Runner()
    app.table.compiler = fake_compile
    project = json_request(app, "/auto-table/api/projects", payload(), status=201)
    assert project["status"] == "idle"
    assert json_request(app, "/auto-table/api/catalog")["templates"]
    json_request(app, f"/auto-table/api/projects/{project['id']}/start", {}, status=202)
    await_condition(lambda: app.table.load(project["id"])["status"] == "ready")
    detail = json_request(app, f"/auto-table/api/projects/{project['id']}")
    paths = [f["path"] for f in detail["artifacts"] if f["kind"] == "output"]
    for name in ("attempt-1/tables/main/table.html", "attempt-1/deliverables.zip", "attempt-1/tables/main/preview.pdf"):
        assert name in paths
        status, headers, body = request(app, f"/auto-table/api/projects/{project['id']}/files/output/{name}")
        assert status == 200 and body
        if name.endswith("pdf"):
            assert body.startswith(b"%PDF")
    assert json_request(app, "/auto-writing/api/writings")["writings"] == []
    assert json_request(app, "/auto-table/api/projects")["projects"][0]["id"] == project["id"]


def test_table_imports_writing_zip_as_separate_immutable_input(app):
    from auto_table.tests.test_application import manuscript_zip

    paper = new_writing(app)
    publication = writing.publication_dir(writing.safe_project_dir(paper["id"]))
    publication.mkdir(parents=True, exist_ok=True)
    source = manuscript_zip()
    (publication / "manuscript-latex.zip").write_bytes(source)
    listing = json_request(app, "/auto-table/api/writing-projects")
    assert listing["projects"][0]["id"] == paper["id"]
    table = json_request(app, "/auto-table/api/import-writing", {"project_id": paper["id"]}, status=201)
    assert table["writing_project_id"] == paper["id"]
    assert Path(table["inputs"][0]["path"]).read_bytes() == source
    assert (publication / "manuscript-latex.zip").read_bytes() == source
    assert table["status"] == "idle"


def test_runtime_accounts_for_and_stops_table_job(app):
    from auto_table.tests.test_application import payload

    entered = threading.Event()
    def blocking(prompt, schema, directory, logs, name, job):
        entered.set()
        job.cancelled.wait(3)
        job.check()
    app.table.runner = blocking
    project = app.table.create(payload())
    app.table.start(project["id"])
    assert entered.wait(2)
    assert app.runtime_state()["active_tables"] == [project["id"]]
    assert not app.runtime_state()["idle"]
    app.prepare_restart()
    assert app.table.load(project["id"])["status"] == "paused"
