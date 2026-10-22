"""Persistent links between the four existing module task managers."""

from __future__ import annotations

import base64
import copy
import json
import threading
import uuid
from pathlib import Path

from auto_design.codex_runner import utc_now
from auto_design.orchestration import (
    ACTIVE_STATUSES,
    TaskManager,
    read_current_stage,
    validate_handoff,
    write_json,
)
from auto_search.web import serve as search
from auto_writing.web import serve as writing


def encoded_file(path: Path) -> dict:
    return {"name": path.name, "content_base64": base64.b64encode(path.read_bytes()).decode()}


class PipelineManager:
    def __init__(self, root: Path, workspace: Path, design: TaskManager, table, figure=None):
        self.root, self.workspace, self.design = root, workspace, design
        self.table = table
        self.figure = figure
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.flows = {p.stem: json.loads(p.read_text()) for p in root.glob("flow-*.json")}
        for flow in self.flows.values():
            if flow["status"] in {"running", "waiting_review"}:
                self.update(flow, "paused", "服务重启后已暂停，点击继续会核对原任务并恢复。")

    def save(self, flow: dict) -> None:
        write_json(self.root / f"{flow['id']}.json", flow)

    def update(self, flow: dict, status: str, message: str) -> None:
        if flow.get("status") != status or flow.get("message") != message:
            flow.update(status=status, message=message, updated_at=utc_now())
            flow["events"].append(
                {"at": flow["updated_at"], "stage": flow["stage"], "message": message}
            )
            self.save(flow)

    def list(self) -> list[dict]:
        with self.lock:
            return copy.deepcopy(
                sorted(self.flows.values(), key=lambda f: f["created_at"], reverse=True)
            )

    def get(self, flow_id: str) -> dict:
        if flow_id not in self.flows:
            raise ValueError("全流程任务不存在。")
        return self.flows[flow_id]

    def create(self, payload: dict) -> dict:
        with self.lock:
            stage = str(payload.get("start_stage", "search"))
            selection = str(payload.get("selection", "auto"))
            if stage not in {"search", "design", "writing", "table"} or selection not in {"auto", "manual"}:
                raise ValueError("未知起点或选题方式。")
            direction = str(payload.get("direction", "")).strip()
            source = str(payload.get("source_id", "")).strip() or None
            count = int(payload.get("paper_count", 3))
            if not 2 <= count <= 6:
                raise ValueError("论文数量需要在 2 到 6 之间。")
            if stage == "search" and not source and not 3 <= len(direction) <= 1000:
                raise ValueError("请填写 3 到 1000 个字符的研究方向。")
            if stage != "search" and not source:
                raise ValueError("请选择已有的模块任务。")
            field = {"search": "search_run", "design": "design_id", "writing": "writing_id", "table": "table_id"}[stage]
            if source and any(
                f.get(field) == source and f["status"] != "completed" for f in self.flows.values()
            ):
                raise ValueError("这个任务已经关联全流程，请继续原流程。")
            if source:
                if stage == "search":
                    if not (search.safe_run_directory(source) / "job.json").is_file():
                        raise ValueError("所选调研没有任务记录。")
                elif stage == "design":
                    self.design.get(source)
                elif stage == "table":
                    if self.table.load(source)["mode"] != "manuscript":
                        raise ValueError("接续表格需要完整论文任务。")
                else:
                    writing.load_project(source)
            flow_id = "flow-" + uuid.uuid4().hex[:12]
            title = str(
                payload.get("title")
                or (direction if len(direction) <= 120 else "研究流程 " + utc_now())
                or source
            )
            if len(title) > 120:
                raise ValueError("任务名称不能超过 120 个字符。")
            template = payload.get("template_file")
            if template:
                _, data = writing.decode_zip_file(template)
                if not writing.zipfile.is_zipfile(writing.io.BytesIO(data)):
                    raise ValueError("LaTeX 模板不是有效 ZIP。")
                (self.root / flow_id).mkdir()
                (self.root / flow_id / "latex-template.zip").write_bytes(data)
            now = utc_now()
            flow = {
                "id": flow_id,
                "title": title,
                "direction": direction,
                "paper_count": count,
                "selection": selection,
                "stage": stage,
                "search_run": None,
                "design_id": None,
                "writing_id": None,
                "table_id": None,
                "figure_id": None,
                "figure_enabled": self.figure is not None,
                "idea_id": None,
                "status": "running",
                "message": "已授权启动全流程。",
                "created_at": now,
                "updated_at": now,
                "events": [],
                "retry": True,
            }
            flow[field] = source
            self.flows[flow_id] = flow
            self.save(flow)
            return copy.deepcopy(flow)

    def candidates(self, flow: dict) -> list[dict]:
        if not flow.get("search_run"):
            return []
        directory = search.safe_run_directory(flow["search_run"])
        if not (directory / "web-data.json").is_file():
            return []
        dataset = search.apply_human_reviews(
            search.read_json_if_exists(directory / "web-data.json"), directory
        )
        ranking = search.read_json_if_exists(directory / "evaluation.json").get("ranking", [])
        ideas = dataset["ideas"]
        for idea in ideas:
            path = directory / "papers" / idea["id"] / "idea.md"
            idea["eligible"] = (
                idea.get("human_review") != "discarded"
                and path.is_file()
                and not search.research_pipeline.generate_idea.is_pass_markdown(path.read_text())
            )
        return sorted(
            ideas, key=lambda i: ranking.index(i["id"]) if i["id"] in ranking else len(ranking)
        )

    def action(self, flow_id: str, action: str, payload: dict) -> dict:
        with self.lock:
            flow = self.get(flow_id)
            if action == "pause":
                self.update(flow, "paused", "已暂停自动推进，当前模块保留已有产物。")
                self.pause_module(flow, interrupt=False)
            elif action == "interrupt":
                self.update(flow, "paused", "已请求停止当前控制器；训练进程保留，停止后可继续。")
                self.pause_module(flow, interrupt=True)
            elif action == "resume":
                if flow["status"] == "completed":
                    raise ValueError("流程已完成。")
                if flow["status"] == "running":
                    raise ValueError("流程正在推进，无需重复启动。")
                flow.update(retry=True, recovery_note=str(payload.get("recovery_note", "")))
                if flow["stage"] == "writing" and flow.get("writing_id"):
                    (writing.safe_project_dir(flow["writing_id"]) / "recovery_note.md").write_text(
                        flow["recovery_note"], encoding="utf-8"
                    )
                self.update(flow, "running", "正在核对原任务与已有产物，恢复当前步骤。")
            elif action == "select":
                if flow["stage"] != "search" or flow.get("design_id"):
                    raise ValueError("已交接的 Idea 不能在此替换。")
                candidates = {i["id"]: i for i in self.candidates(flow)}
                idea_id = str(payload.get("idea_id", ""))
                if idea_id not in candidates or not candidates[idea_id]["eligible"]:
                    raise ValueError("请选择一个未放弃且有有效 Idea 文档的方案。")
                flow["idea_id"] = idea_id
                self.update(flow, "running", "已选定 Idea，将自动交接实验。")
                self.save(flow)
            elif action == "template":
                _, data = writing.decode_zip_file(payload.get("template_file", {}))
                if not writing.zipfile.is_zipfile(writing.io.BytesIO(data)):
                    raise ValueError("模板不是有效的 ZIP。")
                if flow.get("table_id") and flow["table_id"] in self.table.jobs:
                    raise ValueError("请先暂停并等待表格步骤停止。")
                if flow.get("figure_id") and self.figure and flow["figure_id"] in self.figure.jobs:
                    raise ValueError("请先停止并等待主图步骤结束。")
                if flow["stage"] in {"table", "figure"} and not flow.get("writing_id"):
                    raise ValueError("从 AutoTable 接续的任务请上传新论文创建任务，不能回退到不存在的写作阶段。")
                if flow.get("writing_id"):
                    project = writing.load_project(flow["writing_id"])
                    if writing.GENERATION_MANAGER.has_project_job(project["id"]):
                        raise ValueError("请先暂停并等待写作步骤停止。")
                    if (
                        writing.GENERATION_MANAGER.automation_state(project["id"])["status"]
                        == "running"
                    ):
                        raise ValueError("请先暂停自动写作。")
                    (
                        writing.safe_project_dir(project["id"]) / "input/latex-template.zip"
                    ).write_bytes(data)
                    project["publication"].update(status="stale", error="模板已更新，请继续排版。")
                    writing.save_project(project)
                directory = self.root / flow_id
                directory.mkdir(exist_ok=True)
                (directory / "latex-template.zip").write_bytes(data)
                if flow.get("table_id"):
                    previous = self.table.load(flow["table_id"])
                    previous["pipeline_id"] = None
                    self.table.save(previous)
                    flow.update(table_id=None, stage="writing")
                if flow.get("figure_id") and self.figure:
                    self.figure.invalidate(flow["figure_id"])
                    flow["figure_id"] = None
                self.update(flow, "paused", "模板已保存，点击继续使用新模板排版。")
            else:
                raise ValueError("未知流程操作。")
            return copy.deepcopy(flow)

    def pause_module(self, flow: dict, interrupt: bool) -> None:
        if flow["stage"] == "search" and flow.get("search_run"):
            for job in search.JOB_MANAGER.snapshots():
                if job["run_name"] == flow["search_run"] and job["status"] not in {
                    "ready",
                    "failed",
                    "cancelled",
                }:
                    search.JOB_MANAGER.stop(job["id"])
        elif flow["stage"] == "design" and flow.get("design_id"):
            task = self.design.get(flow["design_id"])
            if task["status"] in ACTIVE_STATUSES:
                (self.design.interrupt if interrupt else self.design.pause)(task["id"])
        elif flow["stage"] == "table" and flow.get("table_id"):
            self.table.stop(flow["table_id"])
        elif flow["stage"] == "figure" and flow.get("figure_id") and self.figure:
            self.figure.stop(flow["figure_id"])
        elif flow["stage"] == "writing" and flow.get("writing_id"):
            manager = writing.GENERATION_MANAGER
            manager.pause_auto(flow["writing_id"])
            if interrupt:
                with manager.lock:
                    for job in list(manager.jobs.values()):
                        if job.project_id == flow["writing_id"]:
                            manager.cancel(job.id)

    def start(self) -> None:
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="workbench-pipelines")
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(5)

    def _run(self) -> None:
        while not self.stop_event.wait(0.5):
            self.tick()

    def tick(self) -> None:
        with self.lock:
            for flow in self.flows.values():
                if flow["status"] not in {"running", "waiting_review"}:
                    # Figure tasks may be resumed/reviewed on their own page. Observe
                    # that child after a failure without retrying any upstream stage.
                    if not (flow['status'] == 'blocked' and flow['stage'] == 'figure'):
                        continue
                try:
                    getattr(self, f"advance_{flow['stage']}")(flow)
                except Exception as error:  # noqa: BLE001 - persist worker failures for browser recovery
                    self.update(flow, "blocked", str(error))

    def advance_search(self, flow: dict) -> None:
        if not flow["search_run"]:
            existing = next(
                (r for r in search.list_run_summaries() if r.get("pipeline_id") == flow["id"]), None
            )
            if existing:
                flow["search_run"] = existing["run_name"]
            else:
                job = search.JOB_MANAGER.create(
                    flow["direction"], flow["paper_count"], True, 900, pipeline_id=flow["id"], title=flow["title"]
                )
                flow["search_run"] = job.run_dir.name
            flow["retry"] = False
            self.save(flow)
        run = next(
            (r for r in search.list_run_summaries() if r["run_name"] == flow["search_run"]), None
        )
        if run is None:
            raise ValueError("调研任务已被删除，无法继续交接。")
        if run["status"] in {"failed", "cancelled"}:
            if flow.pop("retry", False):
                search.JOB_MANAGER.resume(run["run_name"], flow.get("recovery_note", ""))
                self.save(flow)
                return
            self.update(flow, "blocked", run.get("error") or "调研已停止，点击继续从已有产物恢复。")
            return
        if run["status"] != "ready":
            flow["retry"] = False
            self.update(flow, "running", run["stage"])
            return
        candidates = self.candidates(flow)
        if not flow["idea_id"]:
            eligible = [
                i for i in candidates if i["eligible"] and i["review"]["verdict"] == "promising"
            ]
            if flow["selection"] == "auto" and eligible:
                flow["idea_id"] = eligible[0]["id"]
            else:
                self.update(
                    flow,
                    "waiting_selection",
                    "请选择 Idea；自动选题只采用评审为 promising 且未被人工放弃的方案。",
                )
                return
        selected = next(
            (i for i in candidates if i["id"] == flow["idea_id"] and i["eligible"]), None
        )
        if not selected:
            raise ValueError("选定 Idea 已不可用，请重新选择。")
        existing = next((t for t in self.design.list() if t.get("pipeline_id") == flow["id"]), None)
        if not existing:
            source = (
                search.safe_run_directory(flow["search_run"])
                / "papers"
                / flow["idea_id"]
                / "idea.md"
            )
            existing = self.design.create(
                flow["title"], source.read_text(), str(self.workspace), pipeline_id=flow["id"]
            )
            write_json(
                Path(existing["run_dir"]) / "search_handoff.json",
                {
                    "pipeline_id": flow["id"],
                    "run": flow["search_run"],
                    "idea_id": flow["idea_id"],
                    "source": str(source),
                    "review": selected["review"],
                    "at": utc_now(),
                },
            )
        flow.update(design_id=existing["id"], stage="design", retry=True)
        self.update(flow, "running", "Idea 已交接 Auto Design，进入实验设计与执行。")
        self.save(flow)

    def advance_design(self, flow: dict) -> None:
        task = self.design.get(flow["design_id"])
        if task["status"] in ACTIVE_STATUSES:
            flow["retry"] = False
            self.update(flow, "running", task["summary"])
            return
        if task["status"] == "waiting_review":
            self.update(flow, "waiting_review", "方法修改等待网页审批；批准后流程自动继续。")
            return
        if task["status"] == "abandoned":
            self.update(flow, "blocked", "Idea 已废弃，不交接为论文结果。")
            return
        if task["status"] != "completed":
            if task["status"] in {"created", "design_ready"} or flow.pop("retry", False):
                self.design.start(
                    task["id"], scope="full", recovery_note=flow.get("recovery_note", "")
                )
                flow["retry"] = False
                self.save(flow)
                return
            self.update(flow, "blocked", task.get("error") or task["summary"])
            return
        existing = next(
            (p for p in writing.list_projects() if p.get("pipeline_id") == flow["id"]), None
        )
        if not existing:
            directory = Path(task["run_dir"])
            # The handoff gate changes whether scientific evidence is allowed into writing.
            if read_current_stage(directory) != "COMPLETE":
                raise ValueError("实验磁盘状态尚未 COMPLETE，不允许交接写作。")
            if (
                validate_handoff(
                    directory, "audit", {"outcome": "completed", "next_action": "none"}, "COMPLETE"
                )
                != "none"
            ):
                raise ValueError("实验仍有后续动作，不允许交接写作。")
            names = (
                "idea.md",
                "experiment_design.md",
                "result_diagnosis.md",
                "integrity_audit.md",
                "result_summary.json",
                "raw_results.json",
                "experiment_schedule.json",
                "result_contract.json",
                "effect_comparison.md",
                "execution_record.json",
            )
            sources = [directory / name for name in names if (directory / name).is_file()]
            brief = directory / "writing_handoff.md"
            brief.write_text(
                "# 实验到写作交接\n\n只能根据这些真实产物写作；保留负结果、N/A、INCOMPLETE、逐 seed 证据及审计的结论边界。\n"
                f"\n实验任务：{task['id']}\n流程任务：{flow['id']}\n"
                + "\n".join(f"- {p.name}: {p}" for p in sources)
                + "\n",
                encoding="utf-8",
            )
            # Large raw records remain available at their complete source paths in the brief.
            supports = [
                encoded_file(p) for p in sources if p.stat().st_size <= writing.MAX_FILE_BYTES
            ]
            for item in supports:
                writing.decode_file(item, "evidence")
            existing = writing.create_project(
                flow["title"], encoded_file(brief), supports, pipeline_id=flow["id"]
            )
        flow.update(writing_id=existing["id"], stage="writing", retry=True)
        self.update(flow, "running", "已核对完成状态与审计，将实验资料自动交接论文写作。")
        self.save(flow)

    def advance_writing(self, flow: dict) -> None:
        manager = writing.GENERATION_MANAGER
        state = manager.automation_state(flow["writing_id"])
        if state["status"] == "completed":
            from auto_writing.web.automation import next_step

            if next_step(writing.load_project(flow["writing_id"])) is None:
                existing = next(
                    (p for p in self.table.list() if p.get("pipeline_id") == flow["id"]), None
                )
                if not existing:
                    existing = self.table.import_writing(
                        {
                            "project_id": flow["writing_id"],
                            "pipeline_id": flow["id"],
                            "requirements": "整理论文表格并复核完整 PDF；保持原始数值、均值和样本标准差、N/A、INCOMPLETE、引用与科学结论边界。",
                        }
                    )
                flow.update(table_id=existing["id"], stage="table", retry=True)
                self.update(
                    flow, "running", "论文源码与 PDF 已复制交接 AutoTable，开始表格整理与复核。"
                )
                self.save(flow)
                return
        if flow.get("retry") and state["status"] != "running":
            if (
                manager.has_project_job(flow["writing_id"])
                or flow["writing_id"] in manager.automation_threads
            ):
                return
            writing.list_projects()
            template = self.root / flow["id"] / "latex-template.zip"
            manager.start_auto(
                flow["writing_id"], encoded_file(template) if template.is_file() else None
            )
            flow["retry"] = False
            self.save(flow)
            return
        if state["status"] == "running":
            self.update(flow, "running", state["message"])
        else:
            self.update(flow, "blocked", state.get("message", "写作已暂停，请继续当前步骤。"))

    def advance_table(self, flow: dict) -> None:
        project = self.table.load(flow["table_id"])
        if project["status"] == "ready":
            if flow.get("figure_enabled") and self.figure is None:
                raise ValueError("本流程需要 AutoFigure，但主图服务尚未注册。")
            if flow.get("figure_enabled") and self.figure:
                figure = self.figure.import_table({"project_id": project["id"], "pipeline_id": flow["id"]})
                flow.update(figure_id=figure["id"], stage="figure", retry=True)
                self.update(flow, "running", "表格复核已通过，论文副本已交接 Auto Figure；请打开绘图页面确认三张参考图。")
                self.save(flow)
                return
            self.update(
                flow,
                "completed",
                "论文表格已整理、编译并通过复核；最终 LaTeX 与 PDF 可在 AutoTable 下载。",
            )
        elif project["status"] == "running" or project["id"] in self.table.jobs:
            flow["retry"] = False
            self.update(flow, "running", project["message"])
        elif flow.pop("retry", False):
            self.table.start(
                project["id"],
                {
                    "revise": project["status"] == "needs_revision",
                    "feedback": flow.get("recovery_note", ""),
                },
            )
            self.save(flow)
        else:
            self.update(flow, "blocked", project.get("error") or project["message"])

    def advance_figure(self, flow: dict) -> None:
        project = self.figure.load(flow["figure_id"])
        if not self.figure.source_current(project):
            if project["id"] in self.figure.jobs:
                self.figure.stop(project["id"])
                self.update(flow, "running", "上游论文变化，正在停止旧版本主图任务。")
                return
            self.figure.invalidate(project["id"])
            flow.update(figure_id=None, stage="table", retry=True)
            self.update(flow, "running", "旧主图已失效，重新核对 AutoTable 论文版本。")
            self.save(flow)
        elif project['status'] == 'awaiting_references':
            self.update(flow, 'waiting_review', '请打开 Auto Figure 确认三张参考图，确认后继续 FigureCrafter 绘图。')
        elif project['status'] == 'idle' and project.get('references_confirmed'):
            self.figure.start(project['id'])
            flow['retry'] = False
            self.update(flow, 'running', '参考图已确认，FigureCrafter 正在生成主图。')
        elif project["status"] == "ready":
            self.update(flow, "completed", "方法主图已插入论文，最终 PDF 通过复核；可在 Auto Figure 下载 PPTX、独立主图 PDF、论文源码与完整论文 PDF。")
        elif project["status"] == "running" or project["id"] in self.figure.jobs:
            flow["retry"] = False
            self.update(flow, "running", project["message"])
        elif flow.pop("retry", False):
            self.figure.start(project["id"], {"revise": project["status"] == "needs_revision",
                                              "feedback": flow.get("recovery_note", "")})
            self.save(flow)
        else:
            self.update(flow, "blocked", project["message"])
