"""Real module orchestration with explicit engineering-only model responses."""

import sys
import threading
import time
from pathlib import Path

import pytest

from auto_design.codex_runner import CodexRunner
from auto_design.tests.test_application import DesignRunner, FullRunner, prepare_review, wait_idle
from auto_writing.web.automation import STEPS, template_payload
from workbench.pipeline import PipelineManager
from workbench.tests.test_workbench import (
    app as workbench_app,
)
from workbench.tests.test_workbench import (
    await_condition,
    evaluation_examples,
    idea_examples,
    json_request,
    new_design,
    new_writing,
    request,
    search,
    search_examples,
    writing,
    writing_examples,
)

app = workbench_app


@pytest.fixture(autouse=True)
def table_engineering_fixture(app):
    # Preserve explicit coverage of the legacy four-stage pipeline.
    # Five-stage default and AutoTable handoff are exercised in test_figure_pipeline.py.
    app.pipeline.figure = None
    from auto_table.tests.test_application import fake_compile

    def runner(prompt, schema, directory, logs, name, job):
        if name == "design":
            originals = directory / "inspection" / "original-tables"
            return {
                "rationale": "Engineering fixture preserves original table values.",
                "tables": [],
                "replacements": [
                    {"filename": p.name, "content": p.read_text()} for p in originals.glob("*.tex")
                ],
                "preamble": "",
            }
        return {
            "passed": True,
            "findings": ["Engineering fixture only."],
            "inspected_pages": [str(p) for p in (directory / "patched/pages").glob("*.png")],
        }

    app.table.runner = runner
    app.table.compiler = fake_compile


def seed_search(monkeypatch, fail_second=False):
    papers = [search_examples.paper_record(f"Pipeline engineering fixture {i}") for i in range(2)]
    manifest = search.direction_research.build_manifest(
        "Engineering fixture", {"scope_summary": "Fixture", "papers": papers}, 2
    )
    calls = {"search": 0, "ideas": 0}

    def research(*args, **kwargs):
        calls["search"] += 1
        return manifest

    def idea(*args, **kwargs):
        calls["ideas"] += 1
        if fail_second and calls["ideas"] == 2:
            raise RuntimeError("Engineering fixture: interrupted second Idea")
        return idea_examples.VALID_MARKDOWN

    monkeypatch.setattr(search.direction_research, "execute_research_agent", research)
    monkeypatch.setattr(search.research_pipeline.generate_idea, "run_codex", idea)
    monkeypatch.setattr(
        search.research_pipeline,
        "execute_json_agent",
        lambda *a, **k: evaluation_examples.evaluation([p["id"] for p in manifest["papers"]]),
    )
    return manifest, calls


def seed_writing(monkeypatch, calls, fail_at=None, fail_compile=False, with_table=False):
    examples = writing_examples.AutoWritingWebTests()
    plan = {
        "subsections": [
            {"title": title} for title in ("Sensing Models", "Feature Fusion", "Robust Recognition")
        ]
    }
    intro = examples.intro_research_result()
    research = {
        "subsections": [
            {
                **s,
                "thesis": "A precise technical thesis supported by verified engineering sources.",
                "papers": intro["paragraph_2_papers"][:3],
                "synthesis": "These works establish a coherent technical context for the experiment.",
                "unresolved_gap": "The precise technical gap requires direct experimental verification.",
            }
            for s in plan["subsections"]
        ]
    }

    def invoke(project, task, *args, **kwargs):
        calls.append(task)
        if task == fail_at and calls.count(task) == 1:
            raise RuntimeError("Engineering fixture: transient writing failure")
        if task == "intro_research":
            return intro
        if task == "related_work_plan":
            return plan
        if task == "related_work_research":
            return research
        if task == "reference_insertion":
            return examples.reference_result()
        if task == "latex_publication":
            return {
                "content": "\\documentclass{article}\n\\begin{document}\n\\begin{abstract}\nEngineering fixture only.\n\\end{abstract}\n"
                + "\n".join(
                    f"\\section{{{writing.SECTION_LABELS[s]}}}\nEngineering fixture without scientific claims."
                    for s in writing.BASE_SECTION_ORDER
                )
                + (
                    "\n"
                    + r"\begin{table}\caption{Engineering fixture}\label{tab:main}\begin{tabular}{lr}Baseline & 81.0\\Candidate & 85.0\end{tabular}\end{table}"
                    if with_table
                    else ""
                )
                + "\n\\nocite{*}\n\\bibliographystyle{plain}\n\\bibliography{references}\n\\end{document}"
            }
        if task == "abstract":
            sentence = "The completed paper supports this concise evidence based abstract statement through verified technical reasoning and measured experimental results within the stated evaluation scope only."
            return {
                "content": "\\begin{abstract}\n"
                + " ".join(f"{sentence[:-1]} {i}." for i in range(1, 9))
                + "\n\\end{abstract}"
            }
        return {
            "content": f"\\section{{{task}}}\n"
            + "Engineering fixture verifies workflow transport without making scientific claims. "
            * 4
        }

    def compile_pdf(main, build, log, **kwargs):
        calls.append("compile")
        if fail_compile and calls.count("compile") == 1:
            raise RuntimeError("Engineering fixture: compiler temporarily unavailable")
        build.mkdir(exist_ok=True)
        pdf = build / "fixture.pdf"
        pdf.write_bytes(b"%PDF-1.4\n% Engineering transport fixture only\n%%EOF")
        log.write_text("Engineering compiler fixture")
        return "engineering-fixture", pdf

    monkeypatch.setattr(writing, "invoke_codex_json", invoke)
    monkeypatch.setattr(writing, "compile_latex", compile_pdf)


def wait_flow(app, flow_id, status, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        flow = json_request(app, f"/api/pipelines/{flow_id}")
        if flow["status"] == status:
            return flow
        if flow["status"] == "blocked" and status != "blocked":
            raise AssertionError(flow)
        time.sleep(0.05)
    raise AssertionError(flow)


def test_search_resume_reuses_completed_ideas_and_survives_manager_restart(app, monkeypatch):
    manifest, calls = seed_search(monkeypatch, fail_second=True)
    job = search.JOB_MANAGER.create("Resume engineering fixture", 2, True, 900)
    assert job.finished_event.wait(5) and job.status == "failed"
    first = job.run_dir / "papers" / manifest["papers"][0]["id"] / "idea.md"
    original = first.read_bytes()
    monkeypatch.setattr(search, "JOB_MANAGER", search.JobManager())
    resumed = json_request(app, f"/auto-search/api/runs/{job.run_dir.name}/resume", {}, status=202)
    assert resumed["id"] == job.id
    assert search.JOB_MANAGER.get(job.id).finished_event.wait(5)
    assert search.JOB_MANAGER.get(job.id).status == "ready"
    assert calls == {"search": 1, "ideas": 3}
    assert first.read_bytes() == original


def test_stop_search_keeps_outputs_and_resume_route(app, monkeypatch):
    entered = threading.Event()

    def blocked(*args, cancel_event, **kwargs):
        entered.set()
        assert cancel_event.wait(5)
        raise RuntimeError("Engineering cancellation")

    monkeypatch.setattr(search.direction_research, "execute_research_agent", blocked)
    job = search.JOB_MANAGER.create("Stop engineering fixture", 2, True, 900)
    assert entered.wait(5)
    marker = job.run_dir / "preserved.txt"
    marker.write_text("completed work")
    json_request(app, f"/auto-search/api/jobs/{job.id}/stop", {}, status=202)
    assert job.finished_event.wait(5)
    assert marker.read_text() == "completed work"


def test_full_pipeline_uses_real_handoffs_and_does_not_duplicate(app, monkeypatch):
    _, search_calls = seed_search(monkeypatch)
    writing_calls = []
    seed_writing(monkeypatch, writing_calls, with_table=True)
    app.design.runner = FullRunner()
    flow = json_request(
        app,
        "/api/pipelines",
        {"direction": "Engineering workflow only", "paper_count": 2},
        status=201,
    )
    completed = wait_flow(app, flow["id"], "completed")
    assert app.design.runner.actions == ["design", "run", "diagnosis", "audit"]
    assert writing_calls == [key for _, key in STEPS[:-1]] + ["latex_publication", "compile"]
    assert search_calls == {"search": 1, "ideas": 2}
    assert len(app.design.list()) == len(writing.list_projects()) == 1
    project = writing.load_project(completed["writing_id"])
    assert project["pipeline_id"] == flow["id"]
    table = app.table.load(completed["table_id"])
    assert table["pipeline_id"] == flow["id"] and table["writing_project_id"] == project["id"]
    assert table["status"] == "ready" and table["review"]["passed"]
    assert table["completed_steps"] == ["inspect", "design", "render", "compile", "review"]
    assert len(app.table.list()) == 1
    output = table["outputs"][0]
    relative = Path(output["pdf"]).relative_to(app.table.directory(table["id"]))
    status, _, pdf = request(app, f"/auto-table/api/projects/{table['id']}/files/output/{relative}")
    assert status == 200 and pdf.startswith(b"%PDF")
    assert "raw_results.json" in [f["name"] for f in project["support_files"]]
    for _ in range(3):
        app.pipeline.tick()
    assert len(writing.list_projects()) == 1
    json_request(app, f"/api/pipelines/{flow['id']}/resume", {}, status=400)


def test_manual_selection_pause_and_restart_do_not_dispatch_experiments(app, monkeypatch):
    seed_search(monkeypatch)
    flow = json_request(
        app,
        "/api/pipelines",
        {"direction": "Manual engineering fixture", "selection": "manual"},
        status=201,
    )
    waiting = wait_flow(app, flow["id"], "waiting_selection")
    assert not app.design.list()
    json_request(app, f"/api/pipelines/{flow['id']}/pause", {})
    app.pipeline.tick()
    assert not app.design.list()
    app.pipeline.close()
    recovered = PipelineManager(app.pipeline.root, app.workspace, app.design, app.table)
    recovered.tick()
    assert recovered.get(flow["id"])["status"] == "paused"
    assert not app.design.list()
    assert len(waiting["candidates"]) == 2


def test_revision_gate_and_invalid_completion_do_not_reach_writing(app):
    task = new_design(app)
    prepare_review(app.design, task)
    flow = json_request(
        app, "/api/pipelines", {"start_stage": "design", "source_id": task["id"]}, status=201
    )
    wait_flow(app, flow["id"], "waiting_review")
    assert not writing.list_projects()
    assert not app.design.runner.actions
    app.pipeline.close()
    # A status label alone must not pass the evidence gate.
    app.design.update(task["id"], status="completed")
    app.pipeline.get(flow["id"])["status"] = "running"
    app.pipeline.tick()
    assert app.pipeline.get(flow["id"])["status"] == "blocked"
    assert not writing.list_projects()


def test_writing_failure_retries_only_current_step_and_recompiles_without_regeneration(
    app, monkeypatch
):
    calls = []
    seed_writing(monkeypatch, calls, fail_at="method", fail_compile=True)
    project = new_writing(app)
    flow = json_request(
        app, "/api/pipelines", {"start_stage": "writing", "source_id": project["id"]}, status=201
    )
    wait_flow(app, flow["id"], "blocked")
    assert calls.count("intro") == calls.count("method") == 1
    json_request(app, f"/api/pipelines/{flow['id']}/resume", {"recovery_note": "Engineering retry"})
    # Wait until it has moved beyond the old blocked state into compilation failure.
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and calls.count("compile") < 1:
        time.sleep(0.05)
    wait_flow(app, flow["id"], "blocked")
    assert calls.count("intro") == 1 and calls.count("method") == 2
    assert writing.load_project(project["id"])["publication"]["status"] == "partial"
    publication = writing.publication_dir(writing.safe_project_dir(project["id"]))
    source = publication / "source/main.tex"
    source.write_text(
        source.read_text().replace(
            "Engineering fixture only.", "Repaired engineering fixture only."
        )
    )
    json_request(app, f"/api/pipelines/{flow['id']}/resume", {})
    wait_flow(app, flow["id"], "completed")
    assert calls.count("latex_publication") == 1 and calls.count("compile") == 2
    with writing.zipfile.ZipFile(publication / "manuscript-latex.zip") as archive:
        assert "Repaired engineering fixture only." in archive.read("main.tex").decode()


def test_design_silent_controller_can_be_stopped_from_http_and_retried(app, tmp_path, monkeypatch):
    executable = tmp_path / "codex-silent-fixture"
    executable.write_text(
        f"#!{sys.executable}\nimport sys,time\nfrom pathlib import Path\nsys.stdin.read()\nPath('entered.txt').write_text('running')\ntime.sleep(30)\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("CODEX_CLI", str(executable))
    app.design.runner = CodexRunner()
    task = new_design(app)
    base = f"/auto-design/api/tasks/{task['id']}"
    json_request(app, base + "/start", {}, status=202)
    await_condition(lambda: (Path(task["run_dir"]) / "entered.txt").is_file())
    json_request(app, base + "/interrupt", {}, status=202)
    assert wait_idle(app.design, task["id"])["status"] == "paused"
    assert (Path(task["run_dir"]) / "entered.txt").read_text() == "running"
    app.design.runner = FullRunner()
    json_request(app, base + "/resume", {"recovery_note": "Use preserved work"}, status=202)
    assert wait_idle(app.design, task["id"])["status"] == "design_ready"


def test_default_template_is_accepted_by_existing_zip_decoder(tmp_path):
    name, data = writing.decode_zip_file(template_payload(tmp_path))
    assert name.endswith(".zip")
    assert writing.zipfile.is_zipfile(writing.io.BytesIO(data))


def test_design_tasks_run_concurrently_and_pause_independently(app):
    first, second = new_design(app), new_design(app)
    entered = {Path(t["run_dir"]): threading.Event() for t in (first, second)}
    release = {path: threading.Event() for path in entered}

    class ParallelRunner(DesignRunner):
        def invoke(self, prompt, workspace, log_dir, on_event):
            entered[workspace].set()
            assert release[workspace].wait(5)
            return super().invoke(prompt, workspace, log_dir, on_event)

    app.design.runner = ParallelRunner()
    try:
        app.design.start(first["id"])
        assert entered[Path(first["run_dir"])].wait(5)
        app.design.start(second["id"])
        assert entered[Path(second["run_dir"])].wait(5)
        with pytest.raises(ValueError):
            app.design.start(first["id"])
        app.design.pause(second["id"])
        release[Path(second["run_dir"])].set()
        assert wait_idle(app.design, second["id"])["status"] == "paused"
        assert app.design.get(first["id"])["status"] == "running"
        assert len(app.design.get(second["id"])["attempts"]) == 1
    finally:
        for event in release.values():
            event.set()
        for task in (first, second):
            wait_idle(app.design, task["id"])


def test_handoff_recovers_existing_link_after_interruption(app, monkeypatch):
    seed_search(monkeypatch)
    flow = json_request(
        app,
        "/api/pipelines",
        {"direction": "Recovery engineering fixture", "selection": "manual"},
        status=201,
    )
    waiting = wait_flow(app, flow["id"], "waiting_selection")
    app.pipeline.close()
    candidate = waiting["candidates"][0]["id"]
    source = search.safe_run_directory(waiting["search_run"]) / "papers" / candidate / "idea.md"
    existing = app.design.create(
        "Interrupted handoff fixture",
        source.read_text(),
        str(app.workspace),
        pipeline_id=flow["id"],
    )
    app.pipeline.action(flow["id"], "select", {"idea_id": candidate})
    app.pipeline.tick()
    assert app.pipeline.get(flow["id"])["design_id"] == existing["id"]
    assert len(app.design.list()) == 1


def test_auto_selection_does_not_promote_rejected_ideas(app, monkeypatch):
    seed_search(monkeypatch)
    flow = json_request(
        app,
        "/api/pipelines",
        {"direction": "Rejected engineering fixture", "selection": "manual"},
        status=201,
    )
    waiting = wait_flow(app, flow["id"], "waiting_selection")
    app.pipeline.close()
    directory = search.safe_run_directory(waiting["search_run"])
    for idea in waiting["candidates"]:
        search.write_human_review(directory, idea["id"], "discarded")
    current = app.pipeline.get(flow["id"])
    current.update(selection="auto", status="running")
    app.pipeline.tick()
    assert current["status"] == "waiting_selection"
    assert not app.design.list()


def completed_writing(app, monkeypatch):
    from auto_table.tests.test_application import manuscript_zip
    from auto_writing.web import automation

    project = writing.load_project(new_writing(app)["id"])
    publication = writing.publication_dir(writing.safe_project_dir(project["id"]))
    publication.mkdir(parents=True, exist_ok=True)
    (publication / "manuscript-latex.zip").write_bytes(manuscript_zip())
    project["publication"]["status"] = "ready"
    writing.save_project(project)
    monkeypatch.setattr(
        writing.GENERATION_MANAGER, "automation_state", lambda _: {"status": "completed"}
    )
    monkeypatch.setattr(automation, "next_step", lambda _: None)
    return project


def test_table_failure_review_retry_and_template_invalidation(app, monkeypatch):
    from auto_table.tests.test_application import fake_compile

    project = completed_writing(app, monkeypatch)
    calls, reviews = [], []
    original_runner = app.table.runner

    def compile_pdf(*args, **kwargs):
        calls.append("compile")
        if calls.count("compile") == 1:
            raise RuntimeError("Engineering fixture: unavailable compiler")
        return fake_compile(*args, **kwargs)

    def runner(*args):
        calls.append(args[-2])
        response = original_runner(*args)
        if args[-2] == "review":
            reviews.append(True)
            response["passed"] = len(reviews) > 1
        return response

    app.table.runner, app.table.compiler = runner, compile_pdf
    flow = json_request(
        app, "/api/pipelines", {"start_stage": "writing", "source_id": project["id"]}, status=201
    )
    blocked = wait_flow(app, flow["id"], "blocked")
    table_id = blocked["table_id"]
    assert app.table.load(table_id)["status"] == "failed"
    json_request(app, f"/api/pipelines/{flow['id']}/resume", {})
    blocked = wait_flow(app, flow["id"], "blocked")
    assert app.table.load(table_id)["status"] == "needs_revision"
    assert calls.count("design") == 1
    json_request(app, f"/api/pipelines/{flow['id']}/resume", {"recovery_note": "Recheck layout"})
    final = wait_flow(app, flow["id"], "completed")
    assert final["table_id"] == table_id and len(app.table.list()) == 1
    assert calls.count("design") == 2 and calls.count("compile") == 3
    assert app.table.load(table_id)["attempt"] == 2
    assert (app.table.directory(table_id) / "attempt-1/deliverables.zip").is_file()
    # Replacing the writing template must invalidate the downstream snapshot.
    updated = json_request(
        app,
        f"/api/pipelines/{flow['id']}/template",
        {"template_file": template_payload(app.workspace)},
    )
    assert updated["stage"] == "writing" and updated["table_id"] is None
    assert updated["status"] == "paused"
    assert app.table.load(table_id)["pipeline_id"] is None
    assert app.table.load(table_id)["status"] == "ready"


def test_table_handoff_recovers_saved_project_and_restart(app, monkeypatch):
    project = completed_writing(app, monkeypatch)
    app.pipeline.close()
    flow = app.pipeline.create({"start_stage": "writing", "source_id": project["id"]})
    existing = app.table.import_writing({"project_id": project["id"], "pipeline_id": flow["id"]})
    app.pipeline.tick()
    assert app.pipeline.get(flow["id"])["table_id"] == existing["id"]
    app.pipeline.action(flow["id"], "pause", {})
    recovered = PipelineManager(app.pipeline.root, app.workspace, app.design, app.table)
    recovered.tick()
    assert recovered.get(flow["id"])["status"] == "paused"
    assert len(app.table.list()) == 1
    recovered.action(flow["id"], "resume", {})
    recovered.tick()
    from auto_table.tests.test_application import wait

    assert wait(app.table, existing["id"])["status"] == "ready"
    recovered.tick()
    assert recovered.get(flow["id"])["status"] == "completed"
