"""Application boundaries: real filesystem, HTTP, subprocesses and controlled model responses."""

from __future__ import annotations

import json
import os
import shlex
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from auto_design.codex_runner import CodexRunner
from auto_design.effects import compare_effects
from auto_design.orchestration import TaskManager, read_json, validate_handoff, write_json
from auto_design.prompting import build_prompt
from auto_design.results import ingest_results
from auto_design.runner import run_local_commands
from auto_design.state import advance_run, read_current_stage
from auto_design.tests.test_state import _prepare_design, _prepare_method_revision
from auto_design.web.serve import create_server


def wait_idle(manager: TaskManager, task_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = manager.get(task_id)
        if task["status"] not in {"queued", "running", "pausing"}:
            return task
        time.sleep(0.01)
    raise AssertionError("Task did not reach a stable state")


def create_task(manager: TaskManager, workspace: Path, scope: str = "full") -> dict:
    return manager.create(
        "Engineering verification", "Motivation: test\nContribution: test", str(workspace), scope
    )


class DesignRunner:
    def __init__(
        self, entered: threading.Event | None = None, release: threading.Event | None = None
    ):
        self.actions = []
        self.workspaces = []
        self.entered = entered
        self.release = release

    def invoke(self, prompt, workspace, log_dir, on_event):
        context = json.loads(prompt.split("TASK_CONTEXT_JSON=\n")[-1])
        self.actions.append(context["action"])
        self.workspaces.append(workspace)
        if self.entered:
            self.entered.set()
            assert self.release.wait(5)
        run_dir = Path(context["run_dir"])
        if context["action"] == "design":
            _prepare_design(run_dir, "PASS")
            advance_run(
                run_dir,
                "EXPERIMENT_DESIGN_READY",
                changed_input="test fixture",
                literal_result="PASS",
            )
            return {
                "outcome": "completed",
                "summary": "测试设计完成，未执行实验",
                "next_action": "run",
            }
        return {"outcome": "blocked", "summary": "工程测试不授权实验执行", "next_action": "run"}


def test_design_only_requires_explicit_execution_start(tmp_path):
    runner = DesignRunner()
    manager = TaskManager(tmp_path / "index", runner)
    task = create_task(manager, tmp_path, "design_only")
    manager.start(task["id"])
    assert wait_idle(manager, task["id"])["status"] == "design_ready"
    assert runner.actions == ["design"]
    assert not (Path(task["run_dir"]) / "execution_record.json").exists()
    manager.start(task["id"], scope="full")
    assert wait_idle(manager, task["id"])["status"] == "blocked"
    assert runner.actions == ["design", "run"]
    assert runner.workspaces == [Path(task["run_dir"])] * 2


def test_task_directories_and_imports_preserve_project_instruction_source(tmp_path):
    workspace = tmp_path / "selected project"
    workspace.mkdir()
    instruction = workspace / "AGENTS.md"
    instruction.write_text("Engineering fixture only. Do not launch scientific experiments.")
    runner = DesignRunner()
    manager = TaskManager(tmp_path / "index", runner)
    tasks = [create_task(manager, workspace, "design_only") for _ in range(2)]
    external = TaskManager(tmp_path / "external-index", runner)
    existing = create_task(external, tmp_path, "design_only")
    tasks.append(manager.import_run("Imported fixture", existing["run_dir"], str(workspace)))
    for task in tasks:
        manager.start(task["id"], scope="design_only")
        assert wait_idle(manager, task["id"])["status"] == "design_ready"
        assert runner.workspaces[-1] == Path(task["run_dir"])
        context = json.loads(build_prompt(task, "design").split("TASK_CONTEXT_JSON=\n")[-1])
        assert context["workspace"] == str(workspace)
        assert str(instruction) in context["instruction_files"]
        assert Path(context["references"]).is_dir()
    assert len(set(runner.workspaces)) == 3


@pytest.mark.parametrize("title", ["中文任务标题", "../路径/测试:实验", "长标题" * 120, " /.. "])
def test_named_task_directories_are_safe_unique_and_reloadable(tmp_path, title):
    manager = TaskManager(tmp_path / "index", DesignRunner())
    first, second = [manager.create(title, "Motivation: test", str(tmp_path)) for _ in range(2)]
    root = (tmp_path / "assets/output/auto_design").resolve()
    assert first["run_dir"] != second["run_dir"]
    for task in (first, second):
        directory = Path(task["run_dir"])
        assert directory.parent == root
        assert len(directory.name.encode("utf-8")) < 255
        assert (directory / "idea.md").read_text() == "Motivation: test"
        assert task["title"] == title.strip()
    if title == "中文任务标题":
        assert Path(first["run_dir"]).name.startswith("中文任务标题-design-")
    reloaded = TaskManager(tmp_path / "index", DesignRunner())
    assert reloaded.get(first["id"])["run_dir"] == first["run_dir"]


def test_model_success_without_artifacts_stops_pipeline(tmp_path):
    class EmptyRunner:
        def invoke(self, *args):
            return {"outcome": "completed", "summary": "claimed completion", "next_action": "run"}

    manager = TaskManager(tmp_path / "index", EmptyRunner())
    task = create_task(manager, tmp_path)
    manager.start(task["id"])
    result = wait_idle(manager, task["id"])
    assert result["status"] == "failed"
    assert read_current_stage(task["run_dir"]) == "INPUT_READY"
    assert len(result["attempts"]) == 1


def test_pause_waits_for_current_call_then_stops_dispatch(tmp_path):
    entered, release = threading.Event(), threading.Event()
    runner = DesignRunner(entered, release)
    manager = TaskManager(tmp_path / "index", runner)
    task = create_task(manager, tmp_path)
    manager.start(task["id"])
    assert entered.wait(5)
    assert manager.pause(task["id"])["status"] == "pausing"
    release.set()
    assert wait_idle(manager, task["id"])["status"] == "paused"
    assert runner.actions == ["design"]
    assert (Path(task["run_dir"]) / "experiment_design.md").exists()


def prepare_review(manager, task):
    directory = Path(task["run_dir"])
    _prepare_design(directory, "PASS")
    advance_run(directory, "EXPERIMENT_DESIGN_READY", changed_input="test", literal_result="PASS")
    _prepare_method_revision(directory, revision_id="MR-1")
    advance_run(
        directory,
        "WAITING_FOR_METHOD_REVISION_APPROVAL",
        changed_input="request",
        literal_result="pending",
    )
    manager.update(
        task["id"], status="waiting_review", stage="WAITING_FOR_METHOD_REVISION_APPROVAL"
    )
    return directory


def test_revision_id_and_rejection_block_execution(tmp_path):
    runner = DesignRunner()
    manager = TaskManager(tmp_path / "index", runner)
    task = create_task(manager, tmp_path)
    directory = prepare_review(manager, task)
    with pytest.raises(ValueError, match="Revision ID"):
        manager.decide(task["id"], "MR-2", "APPROVE_MINIMAL_METHOD_REVISION")
    with pytest.raises(ValueError, match="明确批准"):
        manager.start(task["id"])
    original = (directory / "experiment_design.md").read_bytes()
    manager.decide(task["id"], "MR-1", "REJECT_METHOD_REVISION")
    with pytest.raises(ValueError, match="明确批准"):
        manager.start(task["id"])
    assert runner.actions == []
    assert (directory / "experiment_design.md").read_bytes() == original


def test_revision_limit_requires_exception_decision(tmp_path):
    manager = TaskManager(tmp_path / "index", DesignRunner())
    task = create_task(manager, tmp_path)
    directory = prepare_review(manager, task)
    with (directory / "method_revision_proposal.md").open("a") as stream:
        stream.write("\nmethod_revision_limit_reached: yes\n")
    with pytest.raises(ValueError, match="例外"):
        manager.decide(task["id"], "MR-1", "APPROVE_MINIMAL_METHOD_REVISION")


def test_rejected_proposal_can_be_approved_later_and_resumed_without_reapproval(tmp_path):
    runner = DesignRunner()
    manager = TaskManager(tmp_path / "index", runner)
    task = create_task(manager, tmp_path)
    prepare_review(manager, task)
    manager.decide(task["id"], "MR-1", "REJECT_METHOD_REVISION")
    manager.decide(task["id"], "MR-1", "APPROVE_MINIMAL_METHOD_REVISION")
    assert wait_idle(manager, task["id"])["status"] == "blocked"
    assert manager.detail(task["id"])["review"]["approved"] is True
    manager.start(task["id"])
    assert wait_idle(manager, task["id"])["status"] == "blocked"
    assert runner.actions == ["revision", "revision"]


def test_recorded_approvals_enforce_revision_limit(tmp_path):
    manager = TaskManager(tmp_path / "index", DesignRunner())
    task = create_task(manager, tmp_path)
    directory = prepare_review(manager, task)
    history = directory / "decision_history"
    history.mkdir()
    for number in (7, 8):
        (history / f"old-{number}.md").write_text(
            f"Revision ID: MR-{number}\nDecision: APPROVE_MINIMAL_METHOD_REVISION\n"
        )
    with pytest.raises(ValueError, match="例外"):
        manager.decide(task["id"], "MR-1", "APPROVE_MINIMAL_METHOD_REVISION")


def test_restart_pauses_without_relaunching_existing_run(tmp_path):
    root = tmp_path / "index"
    manager = TaskManager(root, DesignRunner())
    task = create_task(manager, tmp_path)
    manager.update(task["id"], status="running")
    record = Path(task["run_dir"]) / "execution_record.json"
    record.write_text('{"status":"EXECUTION_IN_PROGRESS","commands":[]}')
    original = record.read_bytes()
    runner = DesignRunner()
    recovered = TaskManager(root, runner)
    assert recovered.get(task["id"])["status"] == "paused"
    assert record.read_bytes() == original
    assert runner.actions == []


def test_import_is_read_only_and_accepts_original_state_label(tmp_path):
    first = TaskManager(tmp_path / "first", DesignRunner())
    original_task = create_task(first, tmp_path)
    directory = Path(original_task["run_dir"])
    path = directory / "AUTODESIGN_STATE.md"
    path.write_text(path.read_text().replace("Next action", "Next Skill"))
    original = path.read_bytes()
    imported = TaskManager(tmp_path / "second", DesignRunner())
    task = imported.import_run("Imported", str(directory), str(tmp_path))
    assert path.read_bytes() == original
    assert task["status"] == "paused"
    _prepare_design(directory, "PASS")
    advance_run(
        directory,
        "EXPERIMENT_DESIGN_READY",
        changed_input="explicit continuation",
        literal_result="PASS",
    )
    assert "Next action" in path.read_text()


def test_open_iteration_cannot_go_to_final_audit(tmp_path):
    manager = TaskManager(tmp_path / "index", DesignRunner())
    task = create_task(manager, tmp_path)
    run_dir = Path(task["run_dir"])
    (run_dir / "result_diagnosis.md").write_text("INCOMPLETE")
    (run_dir / "result_route.md").write_text(
        "route: iteration\nowner_stage: run\nexecution_required: yes\n"
    )
    (run_dir / "next_round.md").write_text("missing observations")
    with pytest.raises(ValueError, match="未关闭"):
        validate_handoff(
            run_dir, "diagnosis", {"outcome": "completed", "next_action": "audit"}, "INPUT_READY"
        )


def test_local_pause_resumes_mid_stage_without_repeating_completed_commands(tmp_path):
    (tmp_path / "generated_project").mkdir()
    marker = tmp_path / "runs.txt"
    pause = tmp_path / "pause_requested.json"

    def command(script):
        return shlex.join([sys.executable, "-c", script])

    first = command(
        f"from pathlib import Path; Path({str(marker)!r}).write_text('first\\n'); Path({str(pause)!r}).write_text('{{}}')"
    )
    second = command(
        f"from pathlib import Path; p=Path({str(marker)!r}); p.write_text(p.read_text()+'second\\n')"
    )
    plan = {
        stage: [command("print('ok')")] for stage in ("preflight", "smoke", "aggregate", "collect")
    }
    plan["experiment"] = [first, second]
    write_json(tmp_path / "command_plan.json", plan)
    result = run_local_commands(tmp_path)
    assert result["status"] == "EXECUTION_PAUSED_BY_USER"
    assert result["completed_stages"] == ["preflight", "smoke"]
    assert marker.read_text() == "first\n"
    pause.unlink()
    result = run_local_commands(tmp_path)
    assert result["workflow_complete"] is True
    assert marker.read_text() == "first\nsecond\n"
    assert [r["command"] for r in result["commands"]].count(first) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture")
def test_cli_subprocess_records_prompt_stream_stderr_and_response(tmp_path, monkeypatch):
    executable = tmp_path / "codex-fixture"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json,sys\nfrom pathlib import Path\n"
        "prompt=sys.stdin.read()\n"
        "Path('cwd-probe.txt').write_text(str(Path.cwd()))\n"
        "output=Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
        "output.write_text(json.dumps({'outcome':'blocked','summary':prompt,'next_action':'none'}))\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'fixture event'}}))\n"
        "print('fixture stderr',file=sys.stderr)\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("CODEX_CLI", os.path.relpath(executable))
    events = []
    response = CodexRunner().invoke(
        "engineering-only fixture", tmp_path, tmp_path / "logs", events.append
    )
    assert response["summary"] == "engineering-only fixture"
    assert (tmp_path / "cwd-probe.txt").read_text() == str(tmp_path.resolve())
    assert events[0]["item"]["text"] == "fixture event"
    assert "fixture stderr" in (tmp_path / "logs/stderr.log").read_text()
    record = read_json(tmp_path / "logs/execution.json")
    assert record["exit_status"] == 0 and record["finished_at"]
    assert "--ephemeral" in record["command"]
    assert "sdk" not in " ".join(record["command"])


def test_http_task_lifecycle_and_native_assets(tmp_path):
    manager = TaskManager(tmp_path / "index", DesignRunner())
    server = create_server("127.0.0.1", 0, manager, tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path, value=None):
        req = Request(
            base + path,
            data=None if value is None else json.dumps(value).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=5) as response:
            return response.read()

    try:
        assert b"app.js" in request("/")
        assert b"querySelector" in request("/app.js")
        assert json.loads(request("/api/tasks"))["tasks"] == []
        task = json.loads(
            request(
                "/api/tasks",
                {
                    "title": "HTTP verification",
                    "idea": "Motivation: test\nContribution: test",
                    "scope": "design_only",
                },
            )
        )
        assert task["status"] == "created"
        request(f"/api/tasks/{task['id']}/start", {})
        assert wait_idle(manager, task["id"])["status"] == "design_ready"
        detail = json.loads(request(f"/api/tasks/{task['id']}"))
        assert detail["documents"]["experiment_design.md"]
        with pytest.raises(HTTPError):
            request(f"/api/tasks/{task['id']}/files/../../outside.txt")
        assert b"INPUT_READY" in request(f"/api/tasks/{task['id']}/files/AUTODESIGN_STATE.md")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_prompt_paths_work_outside_source_repository(tmp_path):
    manager = TaskManager(tmp_path / "index", DesignRunner())
    task = create_task(manager, tmp_path)
    context = json.loads(build_prompt(task, "design").split("TASK_CONTEXT_JSON=\n")[-1])
    assert Path(context["input"]).read_text().startswith("# Input Brief")
    assert Path(context["references"]).is_dir()
    assert str(tmp_path) in context["run_dir"]


class FullRunner(DesignRunner):
    def invoke(self, prompt, workspace, log_dir, on_event):
        context = json.loads(prompt.split("TASK_CONTEXT_JSON=\n")[-1])
        action = context["action"]
        if action == "design":
            return super().invoke(prompt, workspace, log_dir, on_event)
        self.actions.append(action)
        directory = Path(context["run_dir"])
        if action == "run":
            (directory / "generated_project").mkdir()
            (directory / "implementation_notes.md").write_text("Engineering-only test fixture")
            write_json(directory / "result_contract.json", {"primary_result": "fixture.json"})
            write_json(
                directory / "experiment_schedule.json",
                {
                    "schema_version": "1.0",
                    "cells": [
                        {
                            "experiment_id": "E1",
                            "variant_id": "ours",
                            "benchmark_task_id": "task-1",
                            "seed": 1,
                            "metrics": ["reward"],
                        }
                    ],
                },
            )
            command = shlex.join([sys.executable, "-c", "print('engineering fixture')"])
            write_json(
                directory / "command_plan.json",
                {
                    stage: [command]
                    for stage in ("preflight", "smoke", "experiment", "aggregate", "collect")
                },
            )
            advance_run(
                directory,
                "IMPLEMENTATION_READY",
                changed_input="fixture",
                literal_result="ready",
            )
            assert run_local_commands(directory)["workflow_complete"]
            write_json(
                directory / "fixture.json",
                {
                    "schema_version": "1.0",
                    "runs": [
                        {
                            "experiment_id": "E1",
                            "variant_id": "ours",
                            "benchmark_task_id": "task-1",
                            "seed": 1,
                            "status": "completed",
                            "metrics": {"reward": 0.5},
                        }
                    ],
                },
            )
            ingest_results(directory, directory / "fixture.json")
            compare_effects(directory)
            advance_run(
                directory,
                "EXECUTION_COMPLETE",
                changed_input="fixture results",
                literal_result="PASS",
            )
            return {
                "outcome": "completed",
                "summary": "工程测试命令结束",
                "next_action": "diagnosis",
            }
        if action == "diagnosis":
            (directory / "result_diagnosis.md").write_text(
                "Engineering fixture, no scientific claim"
            )
            (directory / "result_route.md").write_text(
                "route: report\nowner_stage: run\nexecution_required: no\n"
            )
            write_json(directory / "reports/report_manifest.json", {"outputs": []})
            (directory / "reports/index.html").write_text("Engineering-only report fixture")
            advance_run(
                directory,
                "RESULT_DIAGNOSIS_READY",
                changed_input="diagnosis",
                literal_result="ready",
            )
            return {
                "outcome": "completed",
                "summary": "工程测试诊断结束",
                "next_action": "audit",
            }
        (directory / "integrity_audit.md").write_text("Verdict: PASS\nEngineering fixture only")
        advance_run(
            directory, "INTEGRITY_AUDIT_PASS", changed_input="audit", literal_result="PASS"
        )
        advance_run(directory, "COMPLETE", changed_input="audit", literal_result="PASS")
        return {"outcome": "completed", "summary": "完整调用链验收结束", "next_action": "none"}


def test_full_workflow_reaches_completion_only_after_independent_audit(tmp_path):
    runner = FullRunner()
    manager = TaskManager(tmp_path / "index", runner)
    task = create_task(manager, tmp_path)
    manager.start(task["id"])
    result = wait_idle(manager, task["id"])
    assert result["status"] == "completed", result
    assert runner.actions == ["design", "run", "diagnosis", "audit"]
    assert len(result["attempts"]) == 4
