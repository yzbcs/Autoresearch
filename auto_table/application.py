"""Persistent, resumable table tasks; the browser only operates this application state."""

from __future__ import annotations

import base64
import copy
import json
import re
import shutil
import threading
import traceback
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from auto_writing.web.serve import compile_latex
from workbench.task_naming import create_task_directory, name_pattern

from . import codex_runner
from .engine.ingest import InputError, load_inputs
from .engine.manuscript import inspect_manuscript, replace_manuscript
from .engine.pipeline import generate
from .engine.templates import available_templates, deep_merge
from .prompting import ROOT, design_prompt, review_prompt

STEPS = ["inspect", "design", "render", "compile", "review"]
LABELS = {
    "inspect": "读取输入",
    "design": "设计表格",
    "render": "生成与替换",
    "compile": "编译 PDF",
    "review": "视觉与数据复核",
}
MAX_FILE_BYTES = 20 * 1024 * 1024


def now():
    return datetime.now(UTC).isoformat()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def simple_name(name):
    if (
        not isinstance(name, str)
        or not name
        or Path(name).name != name
        or name in {".", ".."}
        or "\\" in name
    ):
        raise ValueError("文件名必须是不含路径的名称。")
    return name


class Application:
    def __init__(self, workspace: Path, data_dir: Path | None = None, runner=None, compiler=None):
        self.workspace = workspace.resolve()
        self.root = (data_dir or self.workspace / "assets/output/auto_table").resolve()
        self.input_root = self.workspace / "assets/input/auto_table"
        self.log_root = self.workspace / "assets/logs/auto_table"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        self.threads = {}
        self.runner = runner or codex_runner.invoke
        self.compiler = compiler or compile_latex
        for path in self.root.glob("*/project.json"):
            project = read_json(path)
            if project["status"] == "running":
                project.update(status="paused", message="服务已重启，当前进度已保留，请点击继续。")
                write_json(path, project)

    def directory(self, project_id):
        if not re.fullmatch(r"(?:table-[a-f0-9]{12}|" + name_pattern("table") + ")", project_id):
            raise ValueError("任务编号无效。")
        return self.root / project_id

    def load(self, project_id):
        path = self.directory(project_id) / "project.json"
        if not path.is_file():
            raise ValueError("任务不存在。")
        return read_json(path)

    def save(self, project):
        project["updated_at"] = now()
        write_json(self.directory(project["id"]) / "project.json", project)

    def list(self):
        with self.lock:
            return sorted(
                [read_json(p) for p in self.root.glob("*/project.json")],
                key=lambda p: p["created_at"],
                reverse=True,
            )

    def create(self, payload):
        title = str(payload.get("title", "")).strip()
        if not title or len(title) > 120:
            raise ValueError("请填写 1–120 字的项目名称。")
        mode = payload.get("mode", "manuscript")
        if mode not in {"manuscript", "results"}:
            raise ValueError("请选择论文 ZIP 或实验数据模式。")
        files = payload.get("files", [])
        if not isinstance(files, list) or not 1 <= len(files) <= 20:
            raise ValueError("请上传 1–20 个输入文件。")
        decoded = []
        names = set()
        for item in files:
            name = simple_name(item["name"])
            if name in names:
                raise ValueError(f"输入文件重名：{name}")
            names.add(name)
            data = base64.b64decode(item["content_base64"], validate=True)
            if not data or len(data) > MAX_FILE_BYTES:
                raise ValueError(f"文件为空或超过 20 MB：{name}")
            extension = Path(name).suffix.lower()
            allowed = (
                {".zip", ".pdf"} if mode == "manuscript" else {".csv", ".tsv", ".json", ".jsonl"}
            )
            if extension not in allowed:
                raise ValueError(f"当前模式不支持 {extension} 文件。")
            if extension == ".pdf" and not data.startswith(b"%PDF"):
                raise ValueError("参考 PDF 文件无效。")
            decoded.append((name, data))
        if mode == "manuscript" and (
            sum(Path(n).suffix.lower() == ".zip" for n, _ in decoded) != 1
            or sum(Path(n).suffix.lower() == ".pdf" for n, _ in decoded) > 1
        ):
            raise ValueError("论文模式需要一个 ZIP 和最多一个参考 PDF。")
        config = payload.get("config", {})
        if not isinstance(config, dict):
            raise TypeError("配置必须为 JSON 对象。")
        project_id = create_task_directory(self.root, title, "table").name
        input_dir = self.input_root / project_id
        input_dir.mkdir(parents=True)
        inputs = []
        for name, data in decoded:
            path = input_dir / name
            path.write_bytes(data)
            inputs.append({"name": name, "path": str(path), "size": len(data)})
        project = {
            "id": project_id,
            "title": title,
            "mode": mode,
            "pipeline_id": payload.get("pipeline_id"),
            "writing_project_id": payload.get("writing_project_id"),
            "inputs": inputs,
            "requirements": str(payload.get("requirements", "")),
            "config": config,
            "main_file": str(payload.get("main_file", "")).strip() or None,
            "manual_config": bool(payload.get("manual_config", False)),
            "status": "idle",
            "message": "输入已保存，点击开始整理。",
            "step": "inspect",
            "completed_steps": [],
            "attempt": 1,
            "outputs": [],
            "review": None,
            "created_at": now(),
            "events": [],
            "feedback": "",
        }
        if project["manual_config"] and (mode != "results" or not config):
            shutil.rmtree(input_dir)
            raise ValueError("直接配置模式需要实验数据和非空 JSON 配置。")
        with self.lock:
            self.save(project)
        return project

    def import_writing(self, payload):
        from auto_writing.web import serve as writing

        source = writing.load_project(str(payload.get("project_id", "")))
        publication = writing.publication_dir(writing.safe_project_dir(source["id"]))
        archive = publication / "manuscript-latex.zip"
        if not archive.is_file():
            raise ValueError("该写作任务尚未生成 LaTeX ZIP。")
        paths = [("manuscript.zip", archive)]
        pdf = publication / "manuscript.pdf"
        if pdf.is_file() and source.get("publication", {}).get("status") == "ready":
            paths.append(("manuscript.pdf", pdf))
        return self.create(
            {
                "title": payload.get("title") or source["title"],
                "mode": "manuscript",
                "files": [
                    {"name": name, "content_base64": base64.b64encode(path.read_bytes()).decode()}
                    for name, path in paths
                ],
                "requirements": payload.get("requirements", ""),
                "pipeline_id": payload.get("pipeline_id"),
                "writing_project_id": source["id"],
            }
        )

    def start(self, project_id, payload=None):
        payload = payload or {}
        with self.lock:
            project = self.load(project_id)
            if project_id in self.jobs:
                raise ValueError("当前任务仍在运行。")
            if payload.get("revise"):
                project["attempt"] += 1
                project["completed_steps"] = []
                project["outputs"] = []
                project["feedback"] = (
                    str(payload.get("feedback", ""))
                    + "\n"
                    + json.dumps(project.get("review"), ensure_ascii=False)
                )
                project["review"] = None
                for key in ("requirements", "main_file", "config"):
                    if key in payload:
                        project[key] = payload[key]
                if not isinstance(project["config"], dict):
                    raise TypeError("配置必须为 JSON 对象。")
            elif project["status"] in {"ready", "needs_revision"}:
                raise ValueError("本轮已结束，请修改要求后重新设计。")
            project.update(status="running", message="正在继续表格流程。")
            self.save(project)
            job = codex_runner.Job()
            self.jobs[project_id] = job
            thread = threading.Thread(target=self._run, args=(project_id, job), daemon=True)
            self.threads[project_id] = thread
            thread.start()
            return copy.deepcopy(project)

    def stop(self, project_id):
        with self.lock:
            project = self.load(project_id)
            if job := self.jobs.get(project_id):
                job.cancel()
                project["message"] = "正在停止当前步骤，保留已完成产物。"
                self.save(project)
            return project

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job.cancel()
        for thread in list(self.threads.values()):
            thread.join(timeout=5)

    def _run(self, project_id, job):
        try:
            project = self.load(project_id)
            directory = self.directory(project_id) / f"attempt-{project['attempt']}"
            logs = self.log_root / project_id / f"attempt-{project['attempt']}"
            directory.mkdir(parents=True, exist_ok=True)
            logs.mkdir(parents=True, exist_ok=True)
            for step in STEPS:
                if step in project["completed_steps"]:
                    continue
                job.check()
                with self.lock:
                    project.update(step=step, message=LABELS[step] + "中")
                    project["events"].append({"at": now(), "step": step, "status": "started"})
                    self.save(project)
                getattr(self, "_" + step)(project, directory, logs, job)
                job.check()
                with self.lock:
                    project["completed_steps"].append(step)
                    project["events"].append({"at": now(), "step": step, "status": "completed"})
                    self.save(project)
            with self.lock:
                passed = project["review"]["passed"]
                project.update(
                    status="ready" if passed else "needs_revision",
                    message="表格、PDF 与复核报告已生成。"
                    if passed
                    else "复核发现需要修改的问题，请查看报告并重新设计。",
                )
                self.save(project)
        except Exception as error:  # noqa: BLE001 - persist all background worker failures
            (logs / "application-error.log").write_text(traceback.format_exc(), encoding="utf-8")
            with self.lock:
                project = self.load(project_id)
                project.update(
                    status="paused" if job.cancelled.is_set() else "failed", message=str(error)
                )
                project["events"].append(
                    {
                        "at": now(),
                        "step": project["step"],
                        "status": project["status"],
                        "message": str(error),
                    }
                )
                self.save(project)
        finally:
            with self.lock:
                self.jobs.pop(project_id, None)
                self.threads.pop(project_id, None)

    def _inspect(self, project, directory, logs, job):
        if project["mode"] == "manuscript":
            target = directory / "inspection"
            if target.exists():
                shutil.rmtree(target)
            archive, pdf = self.manuscript_inputs(project)
            manifest = inspect_manuscript(archive, target, pdf, project["main_file"])
        else:
            try:
                observations = load_inputs(
                    [i["path"] for i in project["inputs"]], project["config"]
                )
                manifest = {
                    "record_count": len(observations),
                    "methods": list(dict.fromkeys(i.method for i in observations)),
                    "datasets": list(dict.fromkeys(i.dataset for i in observations)),
                    "metrics": list(dict.fromkeys(i.metric for i in observations)),
                }
                write_json(directory / "observations.json", [i.to_dict() for i in observations])
            except InputError as error:
                if project["manual_config"]:
                    raise
                # A custom method column is resolvable by the design agent from the raw input.
                manifest = {"ingestion_message": str(error)}
            manifest["templates"] = available_templates()
        write_json(directory / "inspection.json", manifest)
        project["inspection"] = manifest

    @staticmethod
    def manuscript_inputs(project):
        archive = next(
            i["path"] for i in project["inputs"] if Path(i["name"]).suffix.lower() == ".zip"
        )
        pdf = next(
            (i["path"] for i in project["inputs"] if Path(i["name"]).suffix.lower() == ".pdf"), None
        )
        return archive, pdf

    def _design(self, project, directory, logs, job):
        if project["mode"] == "manuscript" and not project["inspection"]["tables"]:
            response = {
                "rationale": "论文未包含 table/table* 环境，保持源码不变并编译复核完整 PDF。",
                "tables": [],
                "replacements": [],
                "preamble": "",
            }
        elif project["manual_config"]:
            response = {
                "rationale": "按用户提供的明确配置生成，保留确定性聚合与校验。",
                "tables": [
                    {
                        "id": "main-table",
                        "title": project["title"],
                        "config_json": json.dumps(project["config"]),
                    }
                ],
                "replacements": [],
                "preamble": "",
            }
        else:
            response = self.runner(
                design_prompt(project, directory, read_json(directory / "inspection.json")),
                ROOT / "prompts/design.schema.json",
                directory,
                logs,
                "design",
                job,
            )
        self.validate_plan(project, response)
        write_json(directory / "plan.json", response)
        project["rationale"] = response["rationale"]

    @staticmethod
    def validate_plan(project, plan):
        if not isinstance(plan.get("rationale"), str):
            raise TypeError("设计结果缺少说明。")
        names = set()
        key = "tables" if project["mode"] == "results" else "replacements"
        no_tables = project["mode"] == "manuscript" and not project["inspection"]["tables"]
        if not isinstance(plan.get(key), list) or (not plan[key] and not no_tables):
            raise ValueError("没有生成可用的表格方案。请检查输入或补充要求。")
        for item in plan[key]:
            name = item["id"] if key == "tables" else item["filename"]
            simple_name(name)
            if name in names:
                raise ValueError(f"表格输出名称重复：{name}")
            names.add(name)
            if key == "tables":
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
                    raise ValueError("表格 ID 只能包含字母、数字、下划线和连字符。")
                if not isinstance(json.loads(item["config_json"]), dict):
                    raise ValueError("生成的表格配置不是 JSON 对象。")
            elif not name.endswith(".tex") or name == "preamble.tex":
                raise ValueError("替换文件必须为清单中的表格 .tex 文件。")

    def _render(self, project, directory, logs, job):
        plan = read_json(directory / "plan.json")
        project["outputs"] = []
        if project["mode"] == "results":
            for table in plan["tables"]:
                job.check()
                config = deep_merge(json.loads(table["config_json"]), project["config"])
                destination = directory / "tables" / table["id"]
                manifest = generate([i["path"] for i in project["inputs"]], destination, config)
                project["outputs"].append(
                    {
                        "id": table["id"],
                        "title": table["title"],
                        "directory": str(destination),
                        "manifest": manifest,
                        "tex": str(destination / "table.tex"),
                        "html": str(destination / "table.html"),
                        "caption": (destination / "caption.txt").read_text(),
                        "description": (destination / "description.txt").read_text(),
                    }
                )
                with self.lock:
                    self.save(project)
        else:
            replacements = directory / "replacements"
            if replacements.exists():
                shutil.rmtree(replacements)
            replacements.mkdir()
            for table in plan["replacements"]:
                (replacements / table["filename"]).write_text(table["content"], encoding="utf-8")
            if plan.get("preamble"):
                (replacements / "preamble.tex").write_text(plan["preamble"], encoding="utf-8")
            destination = directory / "patched"
            if destination.exists():
                shutil.rmtree(destination)
            archive, pdf = self.manuscript_inputs(project)
            manifest = replace_manuscript(
                archive, replacements, destination, pdf, main_file=project["main_file"]
            )
            project["outputs"] = [
                {
                    "id": "manuscript",
                    "title": "替换后的论文",
                    "directory": str(destination),
                    "manifest": manifest,
                    "zip": str(destination / "manuscript-patched.zip"),
                    "tex": str(destination / "source" / manifest["main_tex"]),
                }
            ]

    def _compile(self, project, directory, logs, job):
        for output in project["outputs"]:
            job.check()
            if output.get("pdf") and Path(output["pdf"]).is_file() and output.get("pages"):
                continue
            target = Path(output["directory"])
            main = target / "preview.tex" if project["mode"] == "results" else Path(output["tex"])
            compiler, built = self.compiler(
                main, target / "build", logs / (output["id"] + "-compile.log"), job.set_process
            )
            job.check()
            pdf = target / (
                "preview.pdf" if project["mode"] == "results" else "manuscript-patched.pdf"
            )
            shutil.copy2(built, pdf)
            output.update(pdf=str(pdf), compiler=compiler)
            output["pages"] = render_pdf(pdf, target / "pages")
            output["manifest"]["compiled_pdf"] = str(pdf)
            output["manifest"]["compiler"] = compiler
            write_json(target / "manifest.json", output["manifest"])
            with self.lock:
                self.save(project)
        # Source deliveries remain downloadable even when compilation fails. A complete bundle is
        # created only after every PDF has actually been built.
        with zipfile.ZipFile(directory / "deliverables.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for output in project["outputs"]:
                target = Path(output["directory"])
                if project["mode"] == "results":
                    for name in (
                        "caption.txt",
                        "description.txt",
                        "table.tex",
                        "table.html",
                        "preview.tex",
                        "preview.pdf",
                    ):
                        archive.write(target / name, f"{output['id']}/{name}")
                else:
                    for path in (target / "replacement-tables").glob("*.tex"):
                        archive.write(path, "replacement-tables/" + path.name)
                    archive.write(output["zip"], "manuscript-patched.zip")
                    archive.write(output["pdf"], "manuscript-patched.pdf")

    def _review(self, project, directory, logs, job):
        review = self.runner(
            review_prompt(project, directory, project["outputs"]),
            ROOT / "prompts/review.schema.json",
            directory,
            logs,
            "review",
            job,
        )
        pages = {p for output in project["outputs"] for p in output["pages"]}
        if type(review.get("passed")) is not bool or not isinstance(review.get("findings"), list):
            raise ValueError("复核结果格式无效。")
        if set(review.get("inspected_pages", [])) != pages:
            review["passed"] = False
            review["findings"].append("复核未覆盖全部渲染页面。")
        project["review"] = review
        write_json(directory / "review.json", review)

    def artifacts(self, project_id):
        self.load(project_id)
        roots = {
            "output": self.directory(project_id),
            "input": self.input_root / project_id,
            "logs": self.log_root / project_id,
        }
        files = []
        for kind, root in roots.items():
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file() and "build" not in path.relative_to(root).parts:
                    relative = path.relative_to(root).as_posix()
                    files.append({"kind": kind, "path": relative, "size": path.stat().st_size})
        return files

    def artifact(self, project_id, kind, name):
        self.load(project_id)
        roots = {
            "output": self.directory(project_id),
            "input": self.input_root / project_id,
            "logs": self.log_root / project_id,
        }
        if kind not in roots:
            raise ValueError("文件类别不存在。")
        root = roots[kind].resolve()
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError("文件不存在。")
        return path


def render_pdf(pdf, directory):
    import fitz

    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    with fitz.open(pdf) as document:
        for index, page in enumerate(document):
            path = directory / f"page-{index + 1}.png"
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(path)
            paths.append(str(path))
    return paths
