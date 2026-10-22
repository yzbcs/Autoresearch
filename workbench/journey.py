"""Read-only projections of existing workflow records for the journey canvas."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from auto_design.orchestration import read_current_stage, review_details
from auto_search.web import serve as search
from auto_writing.web import serve as writing

STAGES = ("search", "design", "writing", "table", "figure")
TITLES = {
    "search": "调研与选题",
    "design": "实验与审计",
    "writing": "写作与引用",
    "table": "表格与复核",
    "figure": "主图与交付",
}


def read_record(path: Path) -> dict:
    # Agents may be writing a file when this view is refreshed. Never repair it here.
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            return {}
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def snapshot(app, flow_id: str) -> dict:
    flow = app.pipeline.get_view(flow_id)
    stage = flow["stage"]
    active_index = STAGES.index(stage)
    nodes, edges, warnings, module_events = [], [], [], []
    counts = {"papers": None, "ideas": None, "experiments": None, "iterations": None}
    enabled = flow.get("figure_enabled", False) or bool(flow.get("figure_id"))

    def state(module, linked):
        index = STAGES.index(module)
        if not linked:
            return "skipped" if index < active_index else "pending"
        if index < active_index or flow["status"] == "completed" and index == active_index:
            return "done"
        if index > active_index:
            return "pending"
        return {
            "running": "running",
            "completed": "done",
            "blocked": "blocked",
            "paused": "paused",
            "waiting_selection": "waiting",
            "waiting_review": "waiting",
        }.get(flow["status"], "pending")

    def node(key, title, module, x, y, status, summary="", url=None):
        value = {
            "id": key,
            "title": title,
            "stage": module,
            "x": x,
            "y": y,
            "status": status,
            "summary": summary,
            "url": url,
            "artifacts": [],
            "checks": [],
        }
        nodes.append(value)
        return value

    def connect(source, target, kind="main"):
        edges.append({"source": source, "target": target, "kind": kind})

    def artifact(value, root, name, url):
        if (root / name).is_file():
            value["artifacts"].append(
                {"name": name, "url": url, "size": (root / name).stat().st_size}
            )

    def events(items, module):
        for item in items:
            if isinstance(item, dict) and (item.get("message") or item.get("status")):
                module_events.append(
                    {
                        "at": item.get("at", ""),
                        "stage": module,
                        "message": str(item.get("message") or item["status"]),
                        "source": "module",
                    }
                )

    run = flow.get("search_run")
    search_url = "/auto-search/?run=" + quote(run, safe="") if run else None
    direction = node(
        "direction",
        "研究方向",
        "search",
        30,
        240,
        "done" if flow.get("direction") or run else "skipped",
        flow.get("direction") or "从已有模块接续，本流程未记录研究方向。",
        search_url,
    )
    papers = node(
        "papers",
        "论文证据",
        "search",
        190,
        240,
        state("search", run),
        "尚未创建调研任务。",
        search_url,
    )
    connect(direction["id"], papers["id"])
    candidates = []
    if run:
        try:
            root = search.safe_run_directory(run)
            data = read_record(root / "web-data.json")
            job = read_record(root / "job.json")
            manifest = read_record(root / "manifest.snapshot.json")
            candidates = data.get("ideas", [])
            candidates = (
                [i for i in candidates if isinstance(i, dict)]
                if isinstance(candidates, list)
                else []
            )
            counts["papers"] = (
                len(manifest["papers"])
                if isinstance(manifest.get("papers"), list)
                else len(job["papers"])
                if isinstance(job.get("papers"), list)
                else None
            )
            counts["ideas"] = len(candidates) if data else None
            reviews = read_record(root / "human_review.json")
            papers["summary"] = (
                job.get("error") or job.get("stage") or "论文证据已归档，请在调研模块核对来源。"
            )
            if job.get("status") == "ready":
                papers["status"] = "done"
            events(job.get("events", []), "search")
        except (ValueError, OSError, KeyError) as error:
            warnings.append(f"调研记录暂不可读：{error}")
            reviews = {}
    else:
        reviews = {}
    # Keep the chosen idea visible even for a large portfolio.
    shown = sorted(candidates, key=lambda i: i.get("id") != flow.get("idea_id"))[:3]
    if not shown:
        shown = [{"id": None, "idea_title": "候选 Idea"}]
    for index, idea in enumerate(shown):
        chosen = bool(idea.get("id") and idea["id"] == flow.get("idea_id"))
        discarded = reviews.get(
            idea.get("id"), idea.get("human_review")
        ) == "discarded" or idea.get("is_pass", False)
        status = (
            "done"
            if chosen
            else "skipped"
            if discarded
            else "waiting"
            if idea.get("id")
            else state("search", run)
        )
        value = node(
            f"idea-{index}",
            "已选 Idea" if chosen else f"候选 Idea {index + 1}",
            "search",
            360,
            240 + (index - (len(shown) - 1) / 2) * 104,
            status,
            idea.get("idea_title") or idea.get("paper_title") or "等待调研与候选生成。",
            search_url + "#" + quote(str(idea["id"]), safe="")
            if idea.get("id") and search_url
            else search_url,
        )
        value["subtitle"] = (
            "已选定"
            if chosen
            else "已放弃"
            if discarded
            else "待核验"
            if idea.get("id")
            else "尚未生成"
        )
        value["review"] = idea.get("review", {})
        connect("papers", value["id"], "main" if chosen else "branch")
        connect(value["id"], "design", "main" if chosen else "branch")

    task_id = flow.get("design_id")
    design_url = "/auto-design/?task=" + quote(task_id, safe="") if task_id else None
    ds = state("design", task_id)
    design = node(
        "design", "实验设计", "design", 540, 240, ds, "等待选题交接或接续已有实验。", design_url
    )
    execution = node(
        "execution", "实验执行", "design", 710, 240, ds, "尚无实验执行记录。", design_url
    )
    diagnosis = node(
        "diagnosis",
        "诊断与审计",
        "design",
        880,
        240,
        ds,
        "实验完成后进行科学诊断与完整性审计。",
        design_url,
    )
    connect("design", "execution")
    connect("execution", "diagnosis")
    if task_id:
        try:
            task = app.design.get(task_id)
            root = Path(task["run_dir"])
            current = read_current_stage(root)
            attempts = task.get("attempts", [])
            design_attempts = [a for a in attempts if a.get("action") in {"design", "revision"}]
            counts["iterations"] = len(design_attempts)
            design["summary"] = task.get("summary") or current
            execution["summary"] = (
                task.get("error") or task.get("activity") or task.get("summary") or current
            )
            if flow["stage"] == "design" and flow["status"] != "completed":
                run_stages = {
                    "IMPLEMENTATION_READY",
                    "EXECUTION_IN_PROGRESS",
                    "EXPERIMENT_DESIGN_READY",
                }
                late_stages = {
                    "EXECUTION_COMPLETE",
                    "RESULT_DIAGNOSIS_READY",
                    "INTEGRITY_AUDIT_PASS",
                    "COMPLETE",
                }
                design["status"] = "done" if current in run_stages | late_stages else ds
                execution["status"] = (
                    "done" if current in late_stages else ds if current in run_stages else "pending"
                )
                diagnosis["status"] = ds if current in late_stages else "pending"
                if current == "WAITING_FOR_METHOD_REVISION_APPROVAL":
                    design["status"] = "waiting"
                    execution["status"] = "paused"
            result = read_record(root / "result_summary.json")
            done, total = result.get("observed_cell_count"), result.get("expected_cell_count")
            if (
                isinstance(done, int)
                and isinstance(total, int)
                and 0 <= done <= total
                and total > 0
            ):
                counts["experiments"] = {
                    "done": done,
                    "total": total,
                    "basis": "已记录观测单元 / 计划单元，不代表审计通过",
                }
                execution["progress"] = {"done": done, "total": total}
            for value, files in [
                (design, ["experiment_design.md", "command_plan.json"]),
                (execution, ["execution_record.json", "raw_results.json", "result_summary.json"]),
                (diagnosis, ["result_diagnosis.md", "integrity_audit.md"]),
            ]:
                for name in files:
                    artifact(
                        value,
                        root,
                        name,
                        f"/auto-design/api/tasks/{quote(task_id, safe='')}/files/{name}",
                    )
            r0 = read_record(root / "r0_record.json")
            if r0 or current.startswith("R0_") or current == "WAITING_FOR_R0":
                failed = current == "R0_FAILED_RETURN_TO_DESIGN" or r0.get("status") in {
                    "FAIL",
                    "failed",
                }
                passed = current == "R0_PASSED" or r0.get("status") == "PASS"
                probe = node(
                    "r0",
                    "R0 探测",
                    "design",
                    620,
                    420,
                    "blocked" if failed else "done" if passed else "waiting",
                    "前置探测返回设计，请查看原探测记录。"
                    if failed
                    else "按登记的 R0 探测记录展示。",
                    design_url,
                )
                artifact(
                    probe,
                    root,
                    "r0_record.json",
                    f"/auto-design/api/tasks/{quote(task_id, safe='')}/files/r0_record.json",
                )
                connect("design", "r0", "detour")
                connect("r0", "execution" if passed else "design", "detour")
            if (root / "method_revision_proposal.md").is_file():
                review = review_details(root) or {}
                revision = node(
                    "revision",
                    "方法修改审批",
                    "design",
                    825,
                    75,
                    "done" if review.get("approved") else "waiting",
                    "请在实验模块查看指定 Revision ID 的提案和决定。",
                    design_url,
                )
                artifact(
                    revision,
                    root,
                    "method_revision_proposal.md",
                    f"/auto-design/api/tasks/{quote(task_id, safe='')}/files/method_revision_proposal.md",
                )
                connect("revision", "design", "detour")
            for attempt in attempts:
                if attempt.get("started_at"):
                    module_events.append(
                        {
                            "at": attempt["started_at"],
                            "stage": "design",
                            "message": f"启动{ {'design': '实验设计', 'run': '实验执行', 'diagnosis': '结果诊断', 'audit': '独立审计', 'revision': '方法修改'}.get(attempt.get('action'), '工作流调用') }",
                            "source": "module",
                        }
                    )
        except (ValueError, OSError, KeyError) as error:
            warnings.append(f"实验记录暂不可读：{error}")

    previous = "diagnosis"
    for module, field, x, title in [
        ("writing", "writing_id", 1050, "论文写作"),
        ("table", "table_id", 1220, "表格复核"),
        ("figure", "figure_id", 1390, "主图与交付"),
    ]:
        if module == "figure" and not enabled:
            continue
        project_id = flow.get(field)
        url = f"/auto-{module}/?project={quote(project_id, safe='')}" if project_id else None
        value = node(
            module, title, module, x, 240, state(module, project_id), "等待上游交接。", url
        )
        connect(previous, module)
        previous = module
        if not project_id:
            continue
        try:
            if module == "writing":
                root = writing.safe_project_dir(project_id)
                project = read_record(root / "project.json")
                sections = project.get("sections", {})
                value["checks"] = [
                    {
                        "label": writing.SECTION_LABELS.get(key, key),
                        "done": record.get("status") == "ready",
                    }
                    for key, record in sections.items()
                ]
                value["summary"] = "基于实验材料完成六章节、引用与排版。"
                for filename, kind in [
                    ("manuscript-latex.zip", "latex"),
                    ("manuscript.pdf", "pdf"),
                ]:
                    artifact(
                        value,
                        root / "publication",
                        filename,
                        f"/auto-writing/api/writings/{quote(project_id, safe='')}/publication/download/{kind}",
                    )
            else:
                manager = app.table if module == "table" else app.figure
                project = manager.load(project_id)
                value["summary"] = project.get("error") or project.get("message", "")
                if module == stage:
                    value["status"] = {
                        "ready": "done",
                        "needs_revision": "blocked",
                        "failed": "blocked",
                        "awaiting_references": "waiting",
                        "stale": "blocked",
                        "paused": "paused",
                        "idle": "pending",
                        "running": "running",
                    }.get(project.get("status"), value["status"])
                if flow["status"] == "paused" and module == stage and value["status"] == "running":
                    value["status"] = "paused"
                value["checks"] = [
                    {"label": label, "done": step in project.get("completed_steps", [])}
                    for step, label in (
                        {
                            "inspect": "读取输入",
                            "design": "设计表格",
                            "render": "生成表格",
                            "compile": "编译 PDF",
                            "review": "独立复核",
                        }
                        if module == "table"
                        else {
                            "inspect": "读取论文",
                            "plan": "规划插图",
                            "prepare": "准备论文",
                            "generate": "FigureCrafter 绘图",
                            "patch": "插入论文",
                            "compile": "编译 PDF",
                            "review": "图文复核",
                        }
                    ).items()
                ]
                if module == "table":
                    for item in manager.artifacts(project_id):
                        if item["kind"] == "output" and item["path"].endswith(
                            (".pdf", ".zip", "review.json")
                        ):
                            value["artifacts"].append(
                                {
                                    "name": item["path"],
                                    "url": f"/auto-table/api/projects/{quote(project_id, safe='')}/files/output/{quote(item['path'], safe='/')}",
                                    "size": item["size"],
                                }
                            )
                    value["artifacts"] = value["artifacts"][-12:]
                if module == "figure":
                    for key, name in project.get("outputs", {}).items():
                        if key in {"pptx", "figure_pdf", "pdf", "zip", "bundle"} and isinstance(
                            name, str
                        ):
                            # File URLs use the same guarded route as the module itself.
                            value["artifacts"].append(
                                {
                                    "name": name,
                                    "url": f"/auto-figure/api/projects/{quote(project_id, safe='')}/files/attempt-{project['attempt']}/{quote(name, safe='/')}",
                                    "size": None,
                                }
                            )
                events(project.get("events", []), module)
        except (ValueError, OSError, KeyError) as error:
            warnings.append(f"{TITLES[module]}记录暂不可读：{error}")

    for value in nodes:
        if value["stage"] == stage and value["status"] in {
            "running",
            "waiting",
            "blocked",
            "paused",
        }:
            value["message"] = flow.get("message", "")
    flow_events = [
        {**e, "source": "pipeline"} for e in flow.get("events", []) if isinstance(e, dict)
    ]

    def event_time(event):
        try:
            stamp = datetime.fromisoformat(str(event.get("at", "")))
            return (
                stamp.replace(tzinfo=UTC).timestamp()
                if stamp.tzinfo is None
                else stamp.timestamp()
            )
        except ValueError:
            return 0

    timeline = sorted([*flow_events, *module_events], key=event_time)
    timeline = list({(e.get("at"), e.get("stage"), e.get("message")): e for e in timeline}.values())
    return {
        "flow": flow,
        "nodes": nodes,
        "edges": edges,
        "metrics": counts,
        "events": timeline,
        "warnings": warnings,
        "stages": [{"id": s, "title": TITLES[s]} for s in STAGES if s != "figure" or enabled],
    }
