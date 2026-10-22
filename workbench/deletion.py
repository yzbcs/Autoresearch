"""Delete stopped tasks and owned files, with shared-flow and path protection."""

import shutil
import uuid
from contextlib import ExitStack
from pathlib import Path

from auto_design.orchestration import ACTIVE_STATUSES
from auto_search.web import serve as search
from auto_writing.web import serve as writing

FIELDS = {
    "search": "search_run",
    "design": "design_id",
    "writing": "writing_id",
    "table": "table_id",
    "figure": "figure_id",
}


def owned(path, parent):
    path, parent = Path(path), Path(parent).resolve()
    # Never follow task directory symlinks or remove a user-selected workspace.
    if path.is_symlink() or path.resolve().parent != parent:
        raise ValueError("目录超出任务存储范围；外部接续目录不自动删除。")
    return path.resolve()


def stopped_paths(app, module, identity):
    if module == "search":
        search.safe_run_directory(identity)
        root = search.RUNS_ROOT / identity
        if any(
            j["run_name"] == identity and j["status"] not in {"ready", "failed", "cancelled"}
            for j in search.JOB_MANAGER.snapshots()
        ):
            raise ValueError("请先停止调研任务，再删除。")
        return [owned(root, search.RUNS_ROOT)]
    if module == "writing":
        if writing.GENERATION_MANAGER.has_project_job(identity) or (
            identity in writing.GENERATION_MANAGER.automation_threads
            and writing.GENERATION_MANAGER.automation_threads[identity].is_alive()
        ):
            raise ValueError("请先停止写作任务，再删除。")
        writing.safe_project_dir(identity)
        return [owned(writing.WRITING_RUNS_ROOT / identity, writing.WRITING_RUNS_ROOT)]
    manager = getattr(app, module)
    if module != "design":
        owned(manager.root / identity, manager.root)
    task = manager.get(identity) if module == "design" else manager.load(identity)
    thread = manager.threads.get(identity)
    if (
        task["status"] in ACTIVE_STATUSES
        or (thread and thread.is_alive())
        or identity in getattr(manager, "jobs", {})
    ):
        raise ValueError("请先暂停任务并等待后台工作结束，再删除。")
    if module == "design":
        parent = Path(task["workspace"]) / "assets/output/auto_design"
        return [owned(Path(task["run_dir"]), parent)]
    paths = [owned(manager.directory(identity), manager.root)]
    if module == "table":
        paths += [
            owned(manager.input_root / identity, manager.input_root),
            owned(manager.log_root / identity, manager.log_root),
        ]
    return paths


def delete(app, module, identity):
    if module not in {*FIELDS, "pipeline"}:
        raise ValueError("未知任务类型。")
    # Match the pipeline -> module lock order used by normal workflow advancement.
    with ExitStack() as locks:
        for lock in (
            app.pipeline.lock,
            app.design.lock,
            app.table.lock,
            app.figure.lock,
            search.JOB_MANAGER.lock,
            writing.GENERATION_MANAGER.lock,
        ):
            locks.enter_context(lock)
        flows = app.pipeline.flows
        shared = []
        if module == "pipeline":
            flow = app.pipeline.get(identity)
            if flow["status"] in {"running", "waiting_review", "waiting_selection"}:
                raise ValueError("请先暂停全流程，再删除。")
            items = []
            for kind, field in FIELDS.items():
                task_id = flow.get(field)
                if not task_id:
                    continue
                if any(f["id"] != identity and f.get(field) == task_id for f in flows.values()):
                    shared.append({"module": kind, "id": task_id})
                else:
                    items.append((kind, task_id))
        else:
            if any(f.get(FIELDS[module]) == identity for f in flows.values()):
                raise ValueError("该任务正被全流程引用，请先删除对应全流程（共享任务会保留）。")
            items = [(module, identity)]

        paths = []
        for kind, task_id in items:
            # All active-task and path checks finish before any file is moved.
            paths.extend(stopped_paths(app, kind, task_id))
        if module == "pipeline":
            paths.append(owned(app.pipeline.root / f"{identity}.json", app.pipeline.root))
        moved = []
        old_tasks = app.design.tasks.copy()
        old_flows = flows.copy()
        try:
            for path in dict.fromkeys(paths):
                if path.exists():
                    temporary = path.parent / ".deleted" / uuid.uuid4().hex
                    if temporary.parent.is_symlink():
                        raise ValueError("任务清理目录不能是符号链接。")
                    temporary.parent.mkdir(exist_ok=True)
                    path.rename(temporary)
                    moved.append((path, temporary))
            for kind, task_id in items:
                if kind == "design":
                    app.design.tasks.pop(task_id, None)
            app.design._save()
            if module == "pipeline":
                flows.pop(identity)
        except Exception:
            app.design.tasks = old_tasks
            flows.clear()
            flows.update(old_flows)
            for path, temporary in reversed(moved):
                temporary.rename(path)
            app.design._save()
            raise
        if module == "pipeline":
            app.pipeline.forget_view(identity)
        for kind, task_id in items:
            if kind == "search":
                for job_id, job in list(search.JOB_MANAGER.jobs.items()):
                    if job.run_dir.name == task_id:
                        search.JOB_MANAGER.jobs.pop(job_id)
        cleanup_pending = []
        for original, temporary in moved:
            try:
                if temporary.is_dir():
                    shutil.rmtree(temporary)
                else:
                    temporary.unlink()
            except OSError:
                cleanup_pending.append(str(temporary))
        return {
            "deleted": True,
            "removed": [{"module": k, "id": i} for k, i in items],
            "shared_preserved": shared,
            "cleanup_pending": cleanup_pending,
        }
