"""Persistent tasks, explicit action dispatch, and artifact-based recovery."""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
import uuid
from pathlib import Path

from workbench.task_naming import create_task_directory

from .codex_runner import CodexRunner, ControllerInterrupted, utc_now
from .effects import check_design
from .prompting import build_prompt
from .results import summarize_results
from .runner import execution_completion_errors
from .state import initialize_run, inspect_run, read_current_stage

logger = logging.getLogger(__name__)

ACTION_FOR_STAGE = {
    "INPUT_READY": "design",
    "WAITING_FOR_R0": "run",
    "R0_PASSED": "design",
    "R0_FAILED_RETURN_TO_DESIGN": "design",
    "EXPERIMENT_DESIGN_READY": "run",
    "IMPLEMENTATION_READY": "run",
    "EXECUTION_IN_PROGRESS": "run",
    "EXECUTION_COMPLETE": "diagnosis",
    "RESULT_DIAGNOSIS_READY": "diagnosis",
    "INTEGRITY_AUDIT_PASS": "audit",
    "COMPLETE": "none",
    "IDEA_ABANDONED": "none",
    "WAITING_FOR_METHOD_REVISION_APPROVAL": "revision",
}
ACTIVE_STATUSES = {"queued", "running", "pausing"}
DECISIONS = {
    "APPROVE_MINIMAL_METHOD_REVISION",
    "APPROVE_EXCEPTION_METHOD_REVISION",
    "REJECT_METHOD_REVISION",
    "ABANDON_IDEA",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def route_fields(run_dir: Path) -> dict[str, str]:
    text = read_text(run_dir / "result_route.md")
    fields = {}
    # These three literal fields are emitted by the diagnosis prompt.
    for key in ("route", "owner_stage", "execution_required"):
        match = re.search(rf"(?mi)^\s*[-*]?\s*`?{key}`?\s*:\s*`?([a-z_]+)", text)
        if match:
            fields[key] = match.group(1)
    return fields


def review_details(run_dir: Path) -> dict | None:
    text = read_text(run_dir / "method_revision_proposal.md")
    match = re.search(r"(?m)^\s*Revision ID\s*:\s*([A-Za-z0-9._-]+)\s*$", text)
    if not match:
        return None
    limit = re.search(r"(?mi)^\s*method_revision_limit_reached\s*:\s*(yes|no)\s*$", text)
    revision_id = match.group(1)
    approved_ids = set()
    current_decision = None
    decision_path = run_dir / "method_revision_decision.md"
    paths = [decision_path, *(run_dir / "decision_history").glob("*.md")]
    for path in paths:
        decision_text = read_text(path)
        recorded_id = re.search(r"(?m)^Revision ID:\s*(\S+)\s*$", decision_text)
        recorded_decision = re.search(r"(?m)^Decision:\s*([A-Z_]+)\s*$", decision_text)
        if recorded_id and recorded_decision:
            if recorded_decision.group(1).startswith("APPROVE_"):
                approved_ids.add(recorded_id.group(1))
            if path == decision_path and recorded_id.group(1) == revision_id:
                current_decision = recorded_decision.group(1)
    configured_limit = re.search(
        r"(?m)^\|\s*Method revision limit\s*\|\s*(\d+)\s*\|",
        read_text(run_dir / "AUTODESIGN_STATE.md"),
    )
    revision_limit = int(configured_limit.group(1)) if configured_limit else 2
    return {
        "revision_id": revision_id,
        "proposal": text,
        "limit_reached": bool(limit and limit.group(1) == "yes")
        or len(approved_ids - {revision_id}) >= revision_limit,
        "approved": bool(current_decision and current_decision.startswith("APPROVE_")),
    }


def require_artifacts(run_dir: Path, *paths: str) -> None:
    missing = [p for p in paths if not (run_dir / p).exists()]
    if missing:
        raise ValueError("缺少步骤产物：" + ", ".join(missing))


def validate_evidence(run_dir: Path) -> None:
    require_artifacts(
        run_dir,
        "raw_results.json",
        "experiment_schedule.json",
        "execution_record.json",
        "command_plan.json",
        "result_summary.json",
    )
    summary = summarize_results(
        read_json(run_dir / "raw_results.json"),
        read_json(run_dir / "experiment_schedule.json"),
        execution_completion_errors(
            read_json(run_dir / "execution_record.json"), read_json(run_dir / "command_plan.json")
        ),
    )
    if summary["status"] != "READY_FOR_GPT_DIAGNOSIS":
        raise ValueError("实验结果尚不完整：" + "; ".join(summary["errors"]))
    if read_json(run_dir / "result_summary.json") != summary:
        raise ValueError("结果汇总与当前原始记录不一致，请重新 ingest 后诊断。")


def validate_handoff(run_dir: Path, action: str, response: dict, before_stage: str) -> str:
    stage = read_current_stage(run_dir)
    next_action = response["next_action"]
    if stage in {"EXPERIMENT_DESIGN_READY", "WAITING_FOR_R0"}:
        report = check_design(run_dir)
        verdict = "PASS" if stage == "EXPERIMENT_DESIGN_READY" else "PROVISIONAL_WAITING_FOR_R0"
        if report["status"] != "PASS" or report.get("declared_design_readiness") != verdict:
            raise ValueError("设计状态与设计契约不一致。")
    if stage == "WAITING_FOR_METHOD_REVISION_APPROVAL":
        require_artifacts(run_dir, "breakpoint_recovery.md", "method_revision_request.md")
        if not review_details(run_dir):
            raise ValueError("人工审核缺少明确的 Revision ID 与具体提案。")
        return "revision"
    if response["outcome"] != "completed":
        return next_action
    if next_action == "revision":
        require_artifacts(run_dir, "breakpoint_recovery.md", "method_revision_request.md")
        return "revision"
    if action in {"design", "revision"}:
        if stage not in {"EXPERIMENT_DESIGN_READY", "WAITING_FOR_R0"}:
            raise ValueError("设计步骤未达到已接受设计或已注册 R0 状态。")
        return "run"
    if action == "run":
        if stage in {"R0_PASSED", "R0_FAILED_RETURN_TO_DESIGN"}:
            record = read_json(run_dir / "r0_record.json")
            if not record:
                raise ValueError("R0 缺少实际探测记录。")
            return "design"
        if stage != "EXECUTION_COMPLETE":
            raise ValueError("执行步骤尚未完成，不能作为成功任务进入诊断。")
        require_artifacts(run_dir, "effect_comparison.md")
        validate_evidence(run_dir)
        return "diagnosis"
    if action == "diagnosis":
        require_artifacts(run_dir, "result_diagnosis.md", "result_route.md")
        route = route_fields(run_dir)
        if route.get("route") not in {"iteration", "tuning", "stop", "report"}:
            raise ValueError("result_route.md 缺少规范 route 字段。")
        if route.get("execution_required") not in {"yes", "no"}:
            raise ValueError("result_route.md 必须声明 execution_required: yes 或 no。")
        if route["route"] == "iteration" or route["execution_required"] == "yes":
            require_artifacts(run_dir, "next_round.md")
            owner = route.get("owner_stage")
            if next_action not in {"design", "run", "revision"} or owner not in {"design", "run"}:
                raise ValueError("未关闭的实验动作必须返回设计、执行或方法修改审核。")
            return next_action
        if stage != "RESULT_DIAGNOSIS_READY":
            raise ValueError("诊断尚未达到科学就绪状态，不能进入最终审计。")
        validate_evidence(run_dir)
        require_artifacts(run_dir, "reports/report_manifest.json", "reports/index.html")
        return "audit"
    if action == "audit":
        require_artifacts(run_dir, "integrity_audit.md")
        if stage == "COMPLETE":
            route = route_fields(run_dir)
            if route.get("execution_required") != "no" or route.get("route") not in {
                "report",
                "stop",
                "tuning",
            }:
                raise ValueError("科学路线仍有未关闭的实验动作，不能完成流程。")
            report = inspect_run(run_dir)
            if report["missing_artifacts"]:
                raise ValueError("最终状态仍缺少必要产物。")
            if not re.search(
                r"(?mi)^Verdict:\s*PASS\s*$", read_text(run_dir / "integrity_audit.md")
            ):
                raise ValueError("最终审计没有通过。")
            validate_evidence(run_dir)
            require_artifacts(run_dir, "reports/report_manifest.json", "reports/index.html")
            return "none"
        if next_action not in {"design", "run", "diagnosis", "revision"}:
            raise ValueError("审计未通过时必须说明具体修复路线。")
        return next_action
    raise ValueError(f"未知工作步骤：{action}（{before_stage}）")


class TaskManager:
    def __init__(self, root: Path, runner: CodexRunner | None = None) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "tasks.json"
        self.lock = threading.RLock()
        self.worker_slot = threading.Semaphore(1)
        self.runner = runner or CodexRunner()
        self.tasks = read_json(self.index_path) if self.index_path.is_file() else {}
        self.threads: dict[str, threading.Thread] = {}
        for task in self.tasks.values():
            if task["status"] in ACTIVE_STATUSES:
                task["status"] = "paused"
                task["summary"] = "服务重新启动。继续前会先核对在途进程和已有结果，避免重复实验。"
        self._save()

    def _save(self) -> None:
        write_json(self.index_path, self.tasks)

    def update(self, task_id: str, **changes: object) -> None:
        with self.lock:
            self.tasks[task_id].update(changes, updated_at=utc_now())
            self._save()

    def get(self, task_id: str) -> dict:
        with self.lock:
            if task_id not in self.tasks:
                raise ValueError("任务不存在。")
            return copy.deepcopy(self.tasks[task_id])

    def list(self) -> list[dict]:
        with self.lock:
            return copy.deepcopy(
                sorted(self.tasks.values(), key=lambda t: t["created_at"], reverse=True)
            )

    def create(self, title: str, idea: str, workspace: str, scope: str = "full",
               pipeline_id: str | None = None) -> dict:
        if not idea.strip():
            raise ValueError("请输入或上传包含 Motivation 和 Contribution 的 Idea。")
        if re.match(r"(?im)^#\s+PASS:", idea):
            raise ValueError("Auto Search 的 PASS 表示放弃方案，不能作为实验 Idea。")
        working_dir = Path(workspace).expanduser()
        if not working_dir.is_absolute() or not working_dir.is_dir():
            raise ValueError("实验工作目录必须是已存在的绝对路径。")
        if scope not in {"full", "design_only"}:
            raise ValueError("未知执行范围。")
        task_id = "design-" + uuid.uuid4().hex[:12]
        run_dir = create_task_directory(
            working_dir.resolve() / "assets/output/auto_design", title, "design"
        )
        input_path = run_dir / "idea.md"
        input_path.write_text(idea, encoding="utf-8")
        initialize_run(input_path, run_dir)
        return self._register(task_id, title, working_dir.resolve(), run_dir, scope, "created", pipeline_id)

    def import_run(self, title: str, run_dir: str, workspace: str) -> dict:
        directory = Path(run_dir).expanduser().resolve()
        working_dir = Path(workspace).expanduser().resolve()
        if not working_dir.is_dir():
            raise ValueError("实验工作目录不存在。")
        stage = read_current_stage(directory)
        with self.lock:
            if any(t["run_dir"] == str(directory) for t in self.tasks.values()):
                raise ValueError("这个运行目录已经登记。")
        status = (
            "completed"
            if stage == "COMPLETE"
            else "abandoned"
            if stage == "IDEA_ABANDONED"
            else "paused"
        )
        # Registration is read-only for the imported run. Recovery uses artifacts, not a thread ID.
        return self._register(
            "design-" + uuid.uuid4().hex[:12], title, working_dir, directory, "full", status
        )

    def _register(
        self, task_id: str, title: str, workspace: Path, run_dir: Path, scope: str, status: str,
        pipeline_id: str | None = None,
    ) -> dict:
        stage = read_current_stage(run_dir)
        task = {
            "id": task_id,
            "title": title.strip() or run_dir.name,
            "workspace": str(workspace),
            "run_dir": str(run_dir),
            "scope": scope,
            "status": status,
            "stage": stage,
            "next_action": ACTION_FOR_STAGE[stage],
            "summary": "任务已登记，等待开始。",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "attempts": [],
            "error": None,
            "pipeline_id": pipeline_id,
        }
        with self.lock:
            self.tasks[task_id] = task
            self._save()
        return copy.deepcopy(task)

    def start(self, task_id: str, scope: str | None = None, recovery_note: str = "") -> dict:
        with self.lock:
            task = self.get(task_id)
            if task["status"] in ACTIVE_STATUSES or task["status"] in {"completed", "abandoned"}:
                raise ValueError("任务正在运行或已结束。")
            stage = read_current_stage(task["run_dir"])
            if stage == "WAITING_FOR_METHOD_REVISION_APPROVAL":
                review = review_details(Path(task["run_dir"]))
                decision = read_text(Path(task["run_dir"]) / "method_revision_decision.md")
                if (
                    not review
                    or f"Revision ID: {review['revision_id']}\n" not in decision
                    or not re.search(
                        r"(?m)^Decision: APPROVE_(MINIMAL|EXCEPTION)_METHOD_REVISION$", decision
                    )
                ):
                    raise ValueError("需要先对当前 Revision ID 作出明确批准。")
            if scope is not None and scope not in {"full", "design_only"}:
                raise ValueError("未知执行范围。")
            (Path(task["run_dir"]) / "pause_requested.json").unlink(missing_ok=True)
            (Path(task["run_dir"]) / "controller_stop_requested.json").unlink(missing_ok=True)
            self.update(task_id, status="queued", error=None, scope=scope or task["scope"],
                        recovery_note=recovery_note.strip(), previous_error=task.get("error"))
            thread = threading.Thread(target=self._run, args=(task_id,), daemon=True)
            self.threads[task_id] = thread
            thread.start()
            return self.get(task_id)

    def interrupt(self, task_id: str) -> dict:
        with self.lock:
            task = self.get(task_id)
            if task["status"] not in ACTIVE_STATUSES:
                raise ValueError("当前没有运行中的控制器。")
            self.pause(task_id)
            write_json(Path(task["run_dir"]) / "controller_stop_requested.json", {"at": utc_now()})
            self.update(task_id, summary="正在停止本任务的 Codex 控制器；保留训练和已有产物，停止后可恢复。")
            return self.get(task_id)

    def pause(self, task_id: str) -> dict:
        with self.lock:
            task = self.get(task_id)
            if task["status"] not in ACTIVE_STATUSES:
                raise ValueError("任务当前没有在执行。")
            write_json(Path(task["run_dir"]) / "pause_requested.json", {"requested_at": utc_now()})
            self.update(
                task_id,
                status="pausing",
                summary="已请求暂停，等待当前实验单元自然完成并收集结果。",
            )
            return self.get(task_id)

    def decide(self, task_id: str, revision_id: str, decision: str) -> dict:
        with self.lock:
            task = self.get(task_id)
            run_dir = Path(task["run_dir"])
            review = review_details(run_dir)
            if (
                task["status"] not in {"waiting_review", "paused", "blocked"}
                or read_current_stage(run_dir) != "WAITING_FOR_METHOD_REVISION_APPROVAL"
                or not review
                or review["revision_id"] != revision_id
            ):
                raise ValueError("当前审核与 Revision ID 不匹配，请刷新后查看完整提案。")
            if decision not in DECISIONS:
                raise ValueError("未知人工决定。")
            if decision == "APPROVE_MINIMAL_METHOD_REVISION" and review["limit_reached"]:
                raise ValueError("已达到修改次数上限，需要明确批准一次例外修改。")
            text = f"# Method Revision Decision\n\nRevision ID: {revision_id}\nDecision: {decision}\nRecorded at: {utc_now()}\n"
            path = run_dir / "method_revision_decision.md"
            if path.exists():
                history = run_dir / "decision_history"
                history.mkdir(exist_ok=True)
                (history / f"decision-{uuid.uuid4().hex[:12]}.md").write_text(
                    path.read_text(), encoding="utf-8"
                )
            path.write_text(text, encoding="utf-8")
            if decision == "ABANDON_IDEA":
                from .state import advance_run

                (run_dir / "idea_abandonment.md").write_text(text, encoding="utf-8")
                advance_run(
                    run_dir,
                    "IDEA_ABANDONED",
                    changed_input="user decision",
                    literal_result=decision,
                )
                self.update(
                    task_id,
                    status="abandoned",
                    stage="IDEA_ABANDONED",
                    summary="用户已废弃此 Idea；全部证据保留。",
                )
            elif decision == "REJECT_METHOD_REVISION":
                self.update(task_id, status="paused", summary="修改提案未获批准，实验保持暂停。")
            else:
                self.update(
                    task_id,
                    status="paused",
                    next_action="revision",
                    summary="已记录批准，正在接续指定修改。",
                )
                return self.start(task_id)
            return self.get(task_id)

    def _run(self, task_id: str) -> None:
        acquired = False
        try:
            while not acquired:
                task = self.get(task_id)
                if (Path(task["run_dir"]) / "pause_requested.json").exists():
                    self.update(task_id, status="paused", summary="排队任务已暂停，尚未启动新调用。")
                    return
                acquired = self.worker_slot.acquire(timeout=0.2)
            while True:
                task = self.get(task_id)
                run_dir = Path(task["run_dir"])
                if (run_dir / "pause_requested.json").exists():
                    self.update(
                        task_id, status="paused", summary="任务已暂停；继续时会从现有证据恢复。"
                    )
                    return
                stage = read_current_stage(run_dir)
                if task["scope"] == "design_only" and stage in {
                    "EXPERIMENT_DESIGN_READY",
                    "WAITING_FOR_R0",
                }:
                    self.update(
                        task_id,
                        status="design_ready",
                        stage=stage,
                        next_action="run",
                        summary="设计阶段已完成；实验尚未启动。",
                    )
                    return
                action = (
                    task["next_action"] if stage == task["stage"] else ACTION_FOR_STAGE[stage]
                )
                if action == "none":
                    if stage == "COMPLETE":
                        validate_handoff(
                            run_dir,
                            "audit",
                            {"outcome": "completed", "next_action": "none"},
                            stage,
                        )
                    self.update(
                        task_id,
                        status="completed" if stage == "COMPLETE" else "abandoned",
                        stage=stage,
                    )
                    return
                if stage == "WAITING_FOR_METHOD_REVISION_APPROVAL" and not read_text(
                    run_dir / "method_revision_decision.md"
                ):
                    self.update(task_id, status="waiting_review", stage=stage)
                    return
                attempts = task["attempts"]
                log_dir = run_dir / "assets" / "logs" / f"{len(attempts) + 1:04d}-{action}"
                attempt = {"action": action, "started_at": utc_now(), "log_dir": str(log_dir)}
                attempts.append(attempt)
                self.update(
                    task_id,
                    status="running",
                    stage=stage,
                    next_action=action,
                    attempts=attempts,
                    summary=f"正在执行 {action}，运行产物将保存到当前任务目录。",
                )
                response = self.runner.invoke(
                    build_prompt(task, action),
                    run_dir,
                    log_dir,
                    lambda event: self._event(task_id, event),
                )
                attempt.update(finished_at=utc_now(), response=response)
                next_action = validate_handoff(run_dir, action, response, stage)
                new_stage = read_current_stage(run_dir)
                self.update(
                    task_id,
                    stage=new_stage,
                    next_action=next_action,
                    attempts=attempts,
                    summary=response["summary"],
                )
                if new_stage == "COMPLETE" and action == "audit" and next_action == "none":
                    self.update(task_id, status="completed")
                    return
                if (
                    new_stage == "WAITING_FOR_METHOD_REVISION_APPROVAL"
                    and not review_details(run_dir)["approved"]
                ):
                    self.update(task_id, status="waiting_review")
                    return
                if response["outcome"] != "completed":
                    status = "paused" if response["outcome"] == "paused" else "blocked"
                    self.update(task_id, status=status)
                    return
                if new_stage == stage and next_action == action:
                    raise ValueError("步骤没有推进，也没有新的修复路线；已停止重复调用。")
        except ControllerInterrupted as error:
            self.update(task_id, status="paused", error=None, summary=str(error))
        except Exception as error:
            logger.exception("AutoDesign task %s stopped", task_id)
            self.update(
                task_id,
                status="failed",
                error=str(error),
                summary="本步骤未完成，请查看错误和日志后继续。",
            )
        finally:
            if acquired:
                self.worker_slot.release()
            with self.lock:
                self.threads.pop(task_id, None)

    def _event(self, task_id: str, event: dict) -> None:
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                self.update(task_id, activity=item["text"])

    def detail(self, task_id: str) -> dict:
        task = self.get(task_id)
        run_dir = Path(task["run_dir"])
        task["stage"] = read_current_stage(run_dir)
        task["review"] = (
            review_details(run_dir)
            if task["stage"] == "WAITING_FOR_METHOD_REVISION_APPROVAL"
            else None
        )
        task["documents"] = {
            name: read_text(run_dir / name)
            for name in (
                "input_brief.md",
                "experiment_design.md",
                "AUTODESIGN_STATE.md",
                "result_diagnosis.md",
                "result_route.md",
                "effect_comparison.md",
                "integrity_audit.md",
                "breakpoint_recovery.md",
            )
        }
        for field, name in (
            ("results", "result_summary.json"),
            ("execution", "execution_record.json"),
        ):
            try:
                task[field] = read_json(run_dir / name) if (run_dir / name).is_file() else None
            except json.JSONDecodeError:
                task[field] = None  # An agent may currently be writing this artifact.
        task["reports_ready"] = (run_dir / "reports" / "index.html").is_file()
        return task
