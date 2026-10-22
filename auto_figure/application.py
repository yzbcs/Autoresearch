"""Persistent six-step figure tasks, with immutable upstream manuscript snapshots."""

from __future__ import annotations

import base64
import copy
import json
import re
import shutil
import subprocess
import threading
import traceback
import zipfile
from pathlib import Path

from auto_table.application import now, render_pdf, simple_name, write_json
from auto_table.codex_runner import Job
from .codex_bridge import invoke
from auto_writing.web.serve import create_latex_zip
from workbench.task_naming import create_task_directory, name_pattern

from . import manuscript, rendering, references, figurecrafter_runner as upstream_runner
from .compiler import compile_latex

ROOT = Path(__file__).resolve().parent
STEPS = ["inspect", "plan", "prepare", "generate", "patch", "compile", "review"]
LABELS = dict(
    zip(STEPS, ["读取论文", "规划插图位置", "准备缺图论文", "FigureCrafter 绘图", "插入论文", "编译 PDF", "图文与排版复核"])
)


class Application:
    def __init__(
        self,
        workspace,
        data_dir=None,
        table=None,
        runner=None,
        generator=None,
        compiler=None,
        renderer=None,
    ):
        self.workspace = Path(workspace).resolve()
        self.root = manuscript.inside(
            self.workspace, data_dir or self.workspace / "assets/output/auto_figure"
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.table = table
        self.runner, self.generator = runner or invoke, generator or upstream_runner.run
        self.compiler, self.renderer = compiler or compile_latex, renderer or rendering.render
        self.lock = threading.RLock()
        self.jobs, self.threads = {}, {}
        for project in self.list():
            if project["status"] == "running":
                project.update(status="paused", message="服务已重启，点击继续会复用已有步骤。")
                self.save(project)

    def directory(self, project_id):
        if not re.fullmatch(name_pattern("figure"), project_id):
            raise ValueError("AutoFigure 任务编号无效。")
        return manuscript.inside(self.root, self.root / project_id)

    def load(self, project_id):
        return json.loads((self.directory(project_id) / "project.json").read_text())

    def save(self, project):
        project["updated_at"] = now()
        write_json(self.directory(project["id"]) / "project.json", project)

    def list(self):
        with self.lock:
            return sorted(
                [json.loads(p.read_text()) for p in self.root.glob("*/project.json")],
                key=lambda p: p["created_at"],
                reverse=True,
            )

    def create(self, payload):
        title = str(payload.get("title", "")).strip()
        if not 1 <= len(title) <= 120:
            raise ValueError("请填写 1–120 字的任务名称。")
        config = upstream_runner.configuration(payload.get("config", {}))
        decoded = {}
        for item in payload.get("files", []):
            name = simple_name(item["name"])
            suffix = Path(name).suffix.lower()
            if suffix not in {".zip", ".pdf"} or suffix in decoded:
                raise ValueError("请提供一个论文 ZIP，以及最多一个参考 PDF。")
            data = base64.b64decode(item["content_base64"], validate=True)
            if not data or len(data) > 20 * 1024 * 1024:
                raise ValueError("输入文件为空或超过 20 MB。")
            if suffix == ".pdf" and not data.startswith(b"%PDF"):
                raise ValueError("参考 PDF 无效。")
            decoded[suffix] = data
        if ".zip" not in decoded:
            raise ValueError("完整插图流程需要论文 LaTeX ZIP。")
        directory = create_task_directory(self.root, title, "figure")
        try:
            inputs = directory / "input"
            inputs.mkdir()
            for suffix, data in decoded.items():
                (inputs / ("manuscript" + suffix)).write_bytes(data)
            project = {
                "id": directory.name,
                "title": title,
                "status": "awaiting_references",
                "step": "inspect",
                "message": "论文已交接，请确认三张参考图后开始 FigureCrafter 绘图。",
                "backend": "figurecrafter",
                "framework_version": "2.5.1",
                "references_confirmed": False,
                "reference_revision": 1,
                "references": references.snapshot(directory, references.default_slots(), 1),
                "created_at": now(),
                "pipeline_id": payload.get("pipeline_id"),
                "source": None,
                "requirements": str(payload.get("requirements", "")),
                "main_file": payload.get("main_file") or None,
                "config": config,
                "input_hash": manuscript.digest(inputs / "manuscript.zip"),
                "pdf_hash": manuscript.digest(inputs / "manuscript.pdf") if (inputs / "manuscript.pdf").exists() else None,
                "attempt": 1,
                "completed_steps": [],
                "events": [],
                "outputs": {},
                "review": None,
                "feedback": "",
            }
            self.save(project)
            return project
        except Exception:
            shutil.rmtree(directory)
            raise

    def table_source(self, project_id):
        if self.table is None:
            raise ValueError("接续 AutoTable 请从统一工作台启动。")
        source = self.table.load(project_id)
        if source["status"] != "ready" or source["mode"] != "manuscript":
            raise ValueError("需要复核通过的 AutoTable 完整论文任务。")
        output = next((o for o in source["outputs"] if o.get("id") == "manuscript"), None)
        if not output or not Path(output.get("pdf", "")).is_file():
            raise ValueError("AutoTable 缺少最终论文 PDF。")
        archive = Path(output["zip"])
        version = {
            "table_id": source["id"],
            "attempt": source["attempt"],
            "zip_sha256": manuscript.digest(archive),
            "pdf_sha256": manuscript.digest(output["pdf"]),
        }
        return source, output, version

    def import_table(self, payload):
        with self.lock:
            source, output, version = self.table_source(str(payload["project_id"]))
            # Handoff is idempotent for a pipeline and an exact source version.
            if payload.get("pipeline_id"):
                for p in self.list():
                    if (
                        p.get("pipeline_id") == payload["pipeline_id"]
                        and p.get("source") == version
                    ):
                        return p
            project = self.create(
                {
                    "title": payload.get("title") or source["title"],
                    "pipeline_id": payload.get("pipeline_id"),
                    "requirements": payload.get("requirements", ""),
                    "config": payload.get("config", {}),
                    "main_file": output["manifest"]["main_tex"],
                    "files": [
                        {
                            "name": "manuscript" + suffix,
                            "content_base64": base64.b64encode(
                                Path(output[key]).read_bytes()
                            ).decode(),
                        }
                        for key, suffix in (("zip", ".zip"), ("pdf", ".pdf"))
                    ],
                }
            )
            project["source"] = version
            self.save(project)
            return project

    def source_current(self, project):
        if not project.get("source"):
            return True
        try:
            return self.table_source(project["source"]["table_id"])[2] == project["source"]
        except (ValueError, OSError, KeyError):
            return False

    def invalidate(self, project_id):
        with self.lock:
            if project_id in self.jobs:
                raise ValueError("请先停止 AutoFigure，再更换上游论文。")
            project = self.load(project_id)
            project.update(
                status="stale", pipeline_id=None, message="上游论文已变化，请接续新版本。"
            )
            self.save(project)

    def select_references(self, project_id, payload):
        with self.lock:
            project = self.load(project_id)
            if project_id in self.jobs or project['status'] == 'stale':
                raise ValueError('请先停止当前绘图；失效任务需从新版本论文接续。')
            if project.get('backend') != 'figurecrafter':
                raise ValueError('历史 AutoFigure-Edit 任务保留只读，请新建 FigureCrafter 任务。')
            slots = payload.get('slots')
            if not isinstance(payload.get('confirm', False), bool):
                raise ValueError('confirm 必须为布尔值。')
            if slots is not None:
                if not isinstance(slots, list) or len(slots) != 3:
                    raise ValueError('请提交恰好三张参考图。')
                slots = [({'name': project['references'][i]['name'],
                           'content_base64': base64.b64encode((self.directory(project_id) / project['references'][i]['path']).read_bytes()).decode()}
                          if isinstance(slot, dict) and slot.get('keep') is True else slot)
                         for i, slot in enumerate(slots)]
                revision = project.get('reference_revision', 1) + 1
                selected = references.snapshot(self.directory(project_id), slots, revision)
            else:
                revision, selected = project['reference_revision'], project['references']
            if project['completed_steps'] or project['status'] in {'ready', 'needs_revision'}:
                project.update(attempt=project['attempt'] + 1, completed_steps=[], outputs={}, review=None)
            project.update(references=selected, reference_revision=revision,
                           references_confirmed=payload.get('confirm', False),
                           status='idle' if payload.get('confirm') else 'awaiting_references', step='inspect',
                           message='三张参考图已确认，可以开始绘图。' if payload.get('confirm') else '请确认三张参考图。')
            self.save(project)
            return copy.deepcopy(project)

    def start(self, project_id, payload=None):
        payload = payload or {}
        with self.lock:
            project = self.load(project_id)
            if project_id in self.jobs:
                if not payload:
                    return copy.deepcopy(project)
                raise ValueError("当前任务仍在运行。")
            if project.get('backend') != 'figurecrafter':
                raise ValueError('旧 AutoFigure-Edit 任务已保留；请从上游新建 FigureCrafter 任务。')
            if not project.get('references_confirmed'):
                raise ValueError('请先确认三张参考图。')
            if project["status"] == "stale" or not self.source_current(project):
                self.invalidate(project_id)
                raise ValueError("上游论文已变化，请接续新版本。")
            if payload.get('retry_review'):
                if project['status'] not in {'needs_revision','failed'} or not set(STEPS[:-1]).issubset(project['completed_steps']):
                    raise ValueError('仅已完成绘图和编译的任务可单独重试复核。')
                project['completed_steps'] = [s for s in project['completed_steps'] if s != 'review']
                project['review'] = None
            elif payload.get("revise"):
                project.update(
                    attempt=project["attempt"] + 1,
                    completed_steps=[],
                    outputs={},
                    feedback=str(payload.get("feedback", ""))
                    + "\n"
                    + json.dumps(project["review"], ensure_ascii=False),
                    review=None,
                )
                project["requirements"] = str(payload.get("requirements", project["requirements"]))
                project["config"] = upstream_runner.configuration(
                    payload.get("config", project["config"])
                )
            elif project["status"] in {"ready", "needs_revision"}:
                raise ValueError("本轮已结束，请创建修改轮次。")
            project.update(status="running", message="正在继续方法主图流程。")
            project["error"] = None
            self.save(project)
            job = Job()
            self.jobs[project_id] = job
            thread = threading.Thread(target=self._run, args=(project_id, job), daemon=True)
            self.threads[project_id] = thread
            thread.start()
            return copy.deepcopy(project)

    def stop(self, project_id):
        with self.lock:
            if job := self.jobs.get(project_id):
                job.cancel()
            return self.load(project_id)

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job.cancel()
        for thread in list(self.threads.values()):
            thread.join(timeout=6)

    def _run(self, project_id, job):
        project = self.load(project_id)
        directory = self.directory(project_id) / f"attempt-{project['attempt']}"
        logs = directory / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        try:
            if (
                manuscript.digest(self.directory(project_id) / "input/manuscript.zip")
                != project["input_hash"]
            ):
                raise ValueError("输入快照已改变，不能继续原轮次。")
            for ref in project['references']:
                if manuscript.digest(self.directory(project_id) / ref['path']) != ref['sha256']:
                    raise ValueError('参考图快照已改变，不能继续原轮次。')
            if project.get('pdf_hash') and manuscript.digest(self.directory(project_id) / 'input/manuscript.pdf') != project['pdf_hash']:
                raise ValueError('输入论文 PDF 快照已改变。')
            for step in STEPS:
                if step in project["completed_steps"]:
                    continue
                job.check()
                project.update(step=step, message=LABELS[step] + "中")
                project["events"].append({"at": now(), "step": step, "status": "started"})
                self.save(project)
                getattr(self, "_" + step)(project, directory, logs, job)
                job.check()
                project["completed_steps"].append(step)
                self.save(project)
            passed = project["review"]["passed"]
            project.update(
                status="ready" if passed else "needs_revision",
                message="主图、含图论文与复核报告已生成。"
                if passed
                else "复核未通过，请查看报告并修改。",
            )
            if not self.source_current(project):
                project.update(
                    status="stale", message="上游论文已变化，本轮结果已失效，请接续新版本。"
                )
            self.save(project)
        except Exception as error:  # noqa: BLE001 - persist background failures
            (logs / "application-error.log").write_text(traceback.format_exc(), encoding="utf-8")
            project.update(
                status="paused" if job.cancelled.is_set() else "failed", message=str(error), error=str(error)
            )
            self.save(project)
        finally:
            with self.lock:
                self.jobs.pop(project_id, None)
                self.threads.pop(project_id, None)

    def _inspect(self, project, directory, logs, job):
        info = manuscript.inspect(
            self.directory(project["id"]) / "input/manuscript.zip",
            directory / "original",
            project["main_file"],
        )
        manuscript.dump(directory / "inspection.json", info)

    def _plan(self, project, directory, logs, job):
        prompt = (ROOT / "prompts/plan.md").read_text()
        prompt += "\n要求：" + project["requirements"] + "\n修改反馈：" + project["feedback"]
        prompt += "\n论文源码与哈希（完整上下文）：\n" + (directory / "inspection.json").read_text()
        plan = self.runner(prompt, ROOT / "prompts/plan.schema.json", directory, logs, "plan", job)
        manuscript.validate_plan(plan, json.loads((directory / "inspection.json").read_text()))
        manuscript.dump(directory / "plan.json", plan)
        (directory / "method.txt").write_text(
            plan["method_text"]
            + "\n\nDraw one method overview with editable labels, modules and connections. "
            "Use only the method described above. No invented results or performance claims.\n"
            + project["requirements"],
            encoding="utf-8",
        )

    def _prepare(self, project, directory, logs, job):
        """Compile the exact paper snapshot, removing only the explicit planned placeholder."""
        inputs = directory / 'figure-input'
        inputs.mkdir(exist_ok=True)
        plan = json.loads((directory / 'plan.json').read_text())
        info = json.loads((directory / 'inspection.json').read_text())
        source = directory / 'drawing-source'
        if source.exists():
            shutil.rmtree(source)
        shutil.copytree(directory / 'original', source)
        if plan['action'] == 'replace_placeholder':
            path = source / plan['source_file']
            text = path.read_text()
            manuscript.validate_plan(plan, info)
            path.write_text(text.replace(plan['anchor'], '% FigureCrafter: method placeholder removed for drawing input\n', 1))
        compiler, pdf = self.compiler(source / info['main_tex'], directory / 'drawing-build', logs / 'drawing-input-compile.log', job.set_process)
        job.check()
        shutil.copy2(pdf, inputs / 'paper-without-main-figure.pdf')
        for ref in project['references']:
            shutil.copy2(self.directory(project['id']) / ref['path'], inputs / f"style-reference-{ref['slot']:02d}.png")
        (inputs / 'request.md').write_text(project['requirements'] + '\nRevision feedback:\n' + project['feedback'], encoding='utf-8')
        manuscript.dump(directory / 'drawing-input-manifest.json', {
            'source': project['source'], 'input_hash': project['input_hash'], 'compiler': compiler,
            'references': project['references'], 'framework_version': '2.5.1',
            'hashes': {p.name: manuscript.digest(p) for p in inputs.iterdir() if p.is_file()}})

    def _generate(self, project, directory, logs, job):
        result = self.generator(directory / 'figure-input', directory / 'generation', project['config'], logs, job)
        if not isinstance(result, dict):
            raise ValueError('FigureCrafter 必须返回原生 PPTX、PDF、PNG 与验证报告。')
        # The isolated worker verifies freeze and native editability before returning.
        for key, name in {'pptx': 'method-overview.pptx', 'pdf': 'method-overview.pdf',
                          'png': 'method-overview.png', 'caption': 'figure-caption.md',
                          'validation': 'native-validation.json', 'freeze': 'figure-freeze.json'}.items():
            file = manuscript.inside(directory / 'generation', result[key])
            if not file.is_file():
                raise ValueError('FigureCrafter 产物缺失：' + key)
            shutil.copy2(file, directory / name)
        report = json.loads((directory / 'native-validation.json').read_text())
        if report['freeze']['errors'] or report['freeze']['unexpected_files']:
            raise ValueError('FigureCrafter 冻结校验未通过。')
        project['outputs'].update(pptx='method-overview.pptx', figure_pdf='method-overview.pdf',
                                  preview='method-overview.png', caption='figure-caption.md')

    def _patch(self, project, directory, logs, job):
        info = json.loads((directory / "inspection.json").read_text())
        plan = json.loads((directory / "plan.json").read_text())
        manifest = manuscript.patch(
            directory / "original",
            directory / "source",
            info,
            plan,
            directory / "method-overview.pptx",
            directory / "method-overview.pdf",
        )
        (directory / "manuscript.patch").write_text(manifest.pop("patch"), encoding="utf-8")
        manifest.update(
            source=project["source"],
            backend="FigureCrafter", framework_version="2.5.1",
            references=project["references"],
            native_validation_sha256=manuscript.digest(directory / "native-validation.json"),
        )
        manuscript.dump(directory / "manifest.json", manifest)
        create_latex_zip(directory / "source", directory / "manuscript-with-figure.zip")
        project["outputs"].update(zip="manuscript-with-figure.zip", patch="manuscript.patch")

    def _compile(self, project, directory, logs, job):
        manifest = json.loads((directory / "manifest.json").read_text())
        compiler, pdf = self.compiler(
            directory / "source" / manifest["main_tex"],
            directory / "build",
            logs / "compile.log",
            job.set_process,
        )
        job.check()
        destination = directory / "manuscript-with-figure.pdf"
        shutil.copy2(pdf, destination)
        pages = render_pdf(destination, directory / "pages")
        if not pages:
            raise ValueError("编译后的 PDF 没有页面。")
        project["outputs"].update(pdf=destination.name, pages=pages)
        manifest.update(compiler=compiler, pdf_sha256=manuscript.digest(destination))
        manuscript.dump(directory / "manifest.json", manifest)

    def _review(self, project, directory, logs, job):
        previous = directory / 'review.json'
        if previous.exists():
            history = directory / 'review-history'
            history.mkdir(exist_ok=True)
            shutil.copy2(previous, history / f'review-{len(list(history.glob("*.json")))+1:03d}.json')
        source_pdf = self.directory(project['id']) / 'input/manuscript.pdf'
        if not source_pdf.exists():
            source_pdf = directory / 'figure-input/paper-without-main-figure.pdf'
        original_pages = render_pdf(source_pdf, directory / 'original-pages')
        command = [upstream_runner.python_path(), str(ROOT / 'native_inspect.py'),
                   str(directory / 'method-overview.pptx'), str(directory / 'method-overview.pdf'),
                   str(directory / 'native-inspection.json')]
        with (logs / 'native-inspection.log').open('w') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       env=upstream_runner.runtime_environment(), start_new_session=True)
            group = upstream_runner.ProcessGroup(process)
            job.set_process(group)
            try:
                process.wait(timeout=60)
            finally:
                group.terminate()
                job.set_process(None)
        job.check()
        if process.returncode:
            raise RuntimeError('交付 PPTX 的直接原生对象检查失败，请查看 native-inspection.log。')
        native = json.loads((directory / 'native-inspection.json').read_text())
        freeze = json.loads((directory / 'generation/workspace/freeze.json').read_text()) if (directory / 'generation/workspace/freeze.json').exists() else None
        if freeze and native['pptx_sha256'] != freeze['files']['delivery/main-figure.pptx']:
            raise ValueError('交付 PPTX 与模型选择的冻结主图不一致。')
        prompt = (ROOT / 'prompts/review.md').read_text()
        final_pages = project['outputs']['pages']
        prompt += '\nFINAL manuscript pages (return exactly these actually inspected paths in inspected_pages):\n' + json.dumps(final_pages)
        prompt += '\nORIGINAL manuscript comparison pages (also attached, do not list these as final inspected_pages):\n' + json.dumps(original_pages)
        images = [directory / 'method-overview.png', *map(Path, final_pages), *map(Path, original_pages)]
        prompt += '\nACTUAL IMAGE ATTACHMENTS IN ORDER:\n' + json.dumps([str(p) for p in images])
        prompt += '\nINLINED EVIDENCE:\n' + '\n'.join(name + '\n' + (directory / name).read_text() for name in ['inspection.json','plan.json','manifest.json','manuscript.patch','native-validation.json','native-inspection.json'])
        name = 'review' if not (directory / 'review-history').exists() else f'review-{len(list((directory / "review-history").glob("*.json"))):03d}'
        if self.runner is invoke:
            review = self.runner(prompt, ROOT / 'prompts/review.schema.json', directory, logs, name, job, images=images)
        else:
            review = self.runner(prompt, ROOT / 'prompts/review.schema.json', directory, logs, 'review', job)
        if type(review.get("passed")) is not bool or not isinstance(review.get("findings"), list):
            raise ValueError("复核结果格式无效。")
        if set(review.get("inspected_pages", [])) != set(project["outputs"]["pages"]):
            review["passed"] = False
            review["findings"].append("复核未覆盖全部论文页面。")
        project["review"] = review
        manuscript.dump(directory / "review.json", review)
        with zipfile.ZipFile(directory / "deliverables.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for name in (
                "method-overview.pptx",
                "method-overview.png",
                "figure-caption.md",
                "figure-freeze.json",
                "drawing-input-manifest.json",
                "method-overview.pdf",
                "manuscript-with-figure.zip",
                "manuscript-with-figure.pdf",
                "manuscript.patch",
                "manifest.json",
                "review.json",
                "plan.json",
                "native-validation.json",
                "native-inspection.json",
            ):
                archive.write(directory / name, name)
        project["outputs"]["bundle"] = "deliverables.zip"

    def artifacts(self, project_id):
        root = self.directory(project_id)
        return [
            {"name": str(p.relative_to(root)), "size": p.stat().st_size}
            for p in sorted(root.rglob("*"))
            if p.is_file() and not p.is_symlink()
        ]

    def artifact(self, project_id, name):
        path = manuscript.inside(self.directory(project_id), self.directory(project_id) / name)
        if not path.is_file():
            raise ValueError("文件不存在。")
        return path
