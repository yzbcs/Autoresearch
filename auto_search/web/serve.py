from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import threading
import traceback
import uuid
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

WEB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))
import direction_research
import research_pipeline

from workbench.task_naming import create_task_directory, name_pattern

try:
    from .build_data import DEFAULT_MANIFEST, DEFAULT_RUN_DIR, build_dataset, write_dataset
except ImportError:
    from build_data import DEFAULT_MANIFEST, DEFAULT_RUN_DIR, build_dataset, write_dataset


RUNS_ROOT = PROJECT_ROOT / "research_runs"
MAX_REQUEST_BYTES = 64 * 1024
DIRECTION_RUN_RE = re.compile(r"(?:direction-\d{8}-\d{6}-[a-f0-9]{6}|" + name_pattern("search") + ")")
READABLE_RUNS = {"medical-vlm-10"}
HUMAN_REVIEW_VALUES = {"approved", "discarded"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchJob:
    def __init__(self, direction: str, paper_count: int, evaluate: bool, timeout: int,
                 run_dir: Path | None = None, pipeline_id: str | None = None, title: str | None = None):
        self.id = uuid.uuid4().hex[:12]
        self.run_dir = run_dir or create_task_directory(RUNS_ROOT, title or direction, "search")
        self.direction = direction
        self.paper_count = paper_count
        self.evaluate = evaluate
        self.timeout = timeout
        self.status = "queued"
        self.stage = "等待开始"
        self.progress = 0
        self.created_at = utc_now()
        self.updated_at = self.created_at
        self.error: str | None = None
        self.papers: list[dict[str, Any]] = []
        self.events: list[dict[str, str]] = []
        self.pipeline_id = pipeline_id
        if run_dir is not None:
            saved = read_json_if_exists(run_dir / "job.json")
            self.run_dir = run_dir
            for field in ("id", "created_at", "papers", "events", "pipeline_id"):
                if field in saved:
                    setattr(self, field, saved[field])
        self._lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.finished_event = threading.Event()
        self.active_process: Any | None = None
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.add_event("从已有产物继续" if run_dir else "任务已进入队列")

    def add_event(self, message: str) -> None:
        with self._lock:
            self.updated_at = utc_now()
            self.events.append({"at": self.updated_at, "message": message})
            self.events = self.events[-30:]
            self.persist()

    def update(self, status: str, stage: str, progress: int, event: str | None = None) -> None:
        with self._lock:
            if self.cancel_event.is_set() and self.status == "cancelling" and status != "cancelled":
                return
            self.status = status
            self.stage = stage
            self.progress = max(0, min(100, progress))
            self.updated_at = utc_now()
            if event:
                self.events.append({"at": self.updated_at, "message": event})
                self.events = self.events[-30:]
            self.persist()

    def set_papers(self, papers: list[dict[str, Any]]) -> None:
        with self._lock:
            self.papers = [
                {
                    "id": paper["id"],
                    "title": paper["title"],
                    "year": paper["year"],
                    "venue": paper["venue"],
                    "source_url": paper["source_url"],
                    "reported_weakness": paper["reported_weakness"],
                    "feasibility_status": paper.get("feasibility_status", "unknown"),
                }
                for paper in papers
            ]
            self.persist()

    def fail(self, error: Exception) -> None:
        message = str(error).strip() or error.__class__.__name__
        if len(message) > 4000:
            message = message[-4000:]
        with self._lock:
            self.error = message
            self.status = "failed"
            self.stage = "任务失败"
            self.updated_at = utc_now()
            self.events.append({"at": self.updated_at, "message": "任务失败，请查看错误详情"})
            self.persist()

    def register_process(self, process: Any | None) -> None:
        with self._lock:
            self.active_process = process
            if process is not None and self.cancel_event.is_set() and process.poll() is None:
                process.terminate()

    def request_cancel(self) -> None:
        self.cancel_event.set()
        with self._lock:
            process = self.active_process
            if process is not None and process.poll() is None:
                process.terminate()
            if self.status not in {"ready", "failed", "cancelled"}:
                self.status = "cancelling"
                self.stage = "正在取消"
                self.updated_at = utc_now()
                self.events.append({"at": self.updated_at, "message": "正在停止 Codex 任务"})
                self.persist()

    def snapshot(self, include_private: bool = False) -> dict[str, Any]:
        with self._lock:
            value = {
                "id": self.id,
                "run_name": self.run_dir.name,
                "direction": self.direction,
                "paper_count": self.paper_count,
                "evaluate": self.evaluate,
                "timeout": self.timeout,
                "pipeline_id": self.pipeline_id,
                "status": self.status,
                "stage": self.stage,
                "progress": self.progress,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "error": self.error,
                "papers": self.papers,
                "events": list(self.events),
                "result_url": f"/api/runs/{self.run_dir.name}/ideas" if self.status == "ready" else None,
            }
            if include_private:
                value["run_dir"] = str(self.run_dir)
            return value

    def persist(self) -> None:
        if not self.run_dir.exists() and self.status == "queued":
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / "job.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.snapshot(include_private=True), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


class JobManager:
    def __init__(self):
        self.jobs: dict[str, ResearchJob] = {}
        self.lock = threading.RLock()
        self.worker_slot = threading.Semaphore(1)

    def create(self, direction: str, paper_count: int, evaluate: bool, timeout: int,
               pipeline_id: str | None = None, title: str | None = None) -> ResearchJob:
        job = ResearchJob(direction, paper_count, evaluate, timeout, pipeline_id=pipeline_id, title=title)
        with self.lock:
            self.jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job,), daemon=True, name=f"w2c-{job.id}")
        thread.start()
        return job

    def resume(self, run_name: str, recovery_note: str = "") -> ResearchJob:
        with self.lock:
            directory = safe_run_directory(run_name)
            saved = read_json_if_exists(directory / "job.json")
            if not saved:
                raise ValueError("没有可恢复的调研记录。")
            live = self.jobs.get(saved["id"])
            if live and not live.finished_event.is_set():
                raise ValueError("当前任务尚未停止，请等待当前调用结束。")
            if saved["status"] == "ready":
                raise ValueError("调研已完成，无需重试。")
            (directory / "recovery_note.md").write_text(
                f"Previous error: {saved.get('error') or ''}\nUser troubleshooting context: {recovery_note}\n",
                encoding="utf-8")
            job = ResearchJob(saved["direction"], saved["paper_count"], saved["evaluate"],
                              saved.get("timeout", 900), run_dir=directory)
            self.jobs[job.id] = job
            threading.Thread(target=self._run, args=(job,), daemon=True).start()
            return job

    def stop(self, job_id: str) -> ResearchJob:
        job = self.get(job_id)
        if job is None:
            raise ValueError("任务已中断，请刷新后继续。")
        job.request_cancel()
        return job

    def get(self, job_id: str) -> ResearchJob | None:
        with self.lock:
            return self.jobs.get(job_id)

    def snapshots(self) -> list[dict[str, Any]]:
        with self.lock:
            return [job.snapshot() for job in self.jobs.values()]

    def cancel_and_delete(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None:
            return False
        if job.status == "ready":
            raise ValueError("Completed research must be deleted from its folder menu.")
        job.request_cancel()
        if not job.finished_event.wait(timeout=12):
            raise TimeoutError("The research process did not stop within 12 seconds.")
        delete_run_directory(job.run_dir)
        with self.lock:
            self.jobs.pop(job_id, None)
        return True

    def delete_completed_run(self, run_name: str) -> None:
        with self.lock:
            active = next((job for job in self.jobs.values() if job.run_dir.name == run_name), None)
            if active and active.status not in {"ready", "failed", "cancelled"}:
                raise ValueError("Running research must be cancelled before deletion.")
            if active:
                self.jobs.pop(active.id, None)
        delete_run_directory(RUNS_ROOT / run_name)

    def _run(self, job: ResearchJob) -> None:
        acquired = False
        try:
            while not acquired:
                if job.cancel_event.is_set():
                    job.update("cancelled", "已取消", 0, "任务在开始前已取消")
                    return
                acquired = self.worker_slot.acquire(timeout=0.2)
            try:
                if job.cancel_event.is_set():
                    job.update("cancelled", "已取消", 0, "任务在开始前已取消")
                    return
                job.run_dir.mkdir(parents=True, exist_ok=True)
                job.update("researching", "检索并核验论文", 5, "Codex 正在搜索论文与公开 Benchmark")
                manifest_path = job.run_dir / "manifest.snapshot.json"
                if manifest_path.is_file():
                    manifest = read_json_if_exists(manifest_path)
                else:
                    manifest = direction_research.execute_research_agent(
                        job.direction,
                        job.paper_count,
                        timeout=job.timeout,
                        cancel_event=job.cancel_event,
                        process_callback=job.register_process,
                        workspace=job.run_dir,
                    )
                    research_pipeline.write_json_atomic(manifest_path, manifest)
                job.set_papers(manifest["papers"])
                job.update(
                    "generating",
                    "生成 Contribution 与 Idea",
                    25,
                    f"已核验 {len(manifest['papers'])} 篇论文，开始逐篇生成方案",
                )

                def generation_progress(done: int, total: int, paper: dict[str, Any]) -> None:
                    progress = 25 + round(55 * done / total)
                    job.update(
                        "generating",
                        f"生成方案 {done}/{total}",
                        progress,
                        f"已完成：{paper['title']}",
                    )

                portfolio = research_pipeline.generate_portfolio(
                    manifest,
                    job.run_dir,
                    model=None,
                    timeout=job.timeout,
                    force=False,
                    progress_callback=generation_progress,
                    cancel_event=job.cancel_event,
                    process_callback=job.register_process,
                )
                if job.evaluate:
                    job.update("evaluating", "独立评审方案", 84, "Codex 正在评分并整理主要风险")
                    research_pipeline.evaluate_portfolio(
                        portfolio,
                        job.run_dir,
                        model=None,
                        timeout=job.timeout,
                        force=False,
                        cancel_event=job.cancel_event,
                        process_callback=job.register_process,
                    )
                research_pipeline.build_index(manifest, job.run_dir)
                dataset = build_dataset(job.run_dir, manifest_path)
                write_dataset(dataset, job.run_dir / "web-data.json")
                job.update("ready", "完成", 100, f"已生成 {len(dataset['ideas'])} 个研究方案")
            finally:
                self.worker_slot.release()
        except Exception as error:
            if job.cancel_event.is_set():
                job.update("cancelled", "已取消", 0, "调研已取消")
            else:
                traceback.print_exc()
                job.fail(error)
        finally:
            job.register_process(None)
            job.finished_event.set()


def safe_run_directory(run_name: str) -> Path:
    allowed = bool(DIRECTION_RUN_RE.fullmatch(run_name)) or run_name in READABLE_RUNS
    if not allowed:
        raise ValueError("Invalid research folder name.")
    target = (RUNS_ROOT / run_name).resolve()
    if target.parent != RUNS_ROOT.resolve():
        raise ValueError("Research folder is outside the runs directory.")
    return target


def delete_run_directory(run_dir: Path) -> None:
    target = safe_run_directory(run_dir.name)
    if target.exists():
        shutil.rmtree(target)
    if run_dir.name == "medical-vlm-10":
        fallback_data = WEB_ROOT / "data" / "ideas.json"
        if fallback_data.is_file():
            fallback_data.unlink()


def read_json_if_exists(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_human_reviews(run_dir: Path) -> dict[str, str]:
    raw = read_json_if_exists(run_dir / "human_review.json")
    return {
        str(idea_id): decision
        for idea_id, decision in raw.items()
        if decision in HUMAN_REVIEW_VALUES
    }


def dataset_path_for_run(run_dir: Path) -> Path:
    data_path = run_dir / "web-data.json"
    if run_dir.name == "medical-vlm-10" and not data_path.is_file():
        data_path = WEB_ROOT / "data" / "ideas.json"
    return data_path


def apply_human_reviews(data: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    reviews = read_human_reviews(run_dir)
    for idea in data.get("ideas", []):
        if isinstance(idea, dict):
            idea["human_review"] = reviews.get(str(idea.get("id")))
    return data


def write_human_review(run_dir: Path, idea_id: str, decision: str | None) -> None:
    if decision is not None and decision not in HUMAN_REVIEW_VALUES:
        raise ValueError("Human review must be approved, discarded, or null.")
    data_path = dataset_path_for_run(run_dir)
    data = read_json_if_exists(data_path)
    valid_ids = {str(idea.get("id")) for idea in data.get("ideas", []) if isinstance(idea, dict)}
    if idea_id not in valid_ids:
        raise ValueError("Idea not found in this research folder.")
    reviews = read_human_reviews(run_dir)
    if decision is None:
        reviews.pop(idea_id, None)
    else:
        reviews[idea_id] = decision
    output = run_dir / "human_review.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(reviews, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)


def run_idea_metadata(run_dir: Path) -> list[dict[str, Any]]:
    data_path = dataset_path_for_run(run_dir)
    data = read_json_if_exists(data_path)
    reviews = read_human_reviews(run_dir)
    return [
        {
            "id": idea.get("id"),
            "index": idea.get("index"),
            "title": idea.get("idea_title", idea.get("paper_title", "Untitled Idea")),
            "verdict": idea.get("review", {}).get("verdict", "unreviewed"),
            "human_review": reviews.get(str(idea.get("id"))),
        }
        for idea in data.get("ideas", [])
        if isinstance(idea, dict) and idea.get("id")
    ]


def list_run_summaries() -> list[dict[str, Any]]:
    live = {item["run_name"]: item for item in JOB_MANAGER.snapshots()}
    run_names = set(live)
    run_names.update(
        run_name
        for run_name in READABLE_RUNS
        if (RUNS_ROOT / run_name).is_dir()
        and dataset_path_for_run(RUNS_ROOT / run_name).is_file()
    )
    run_names.update(path.name for path in RUNS_ROOT.glob("*") if path.is_dir())
    summaries: list[dict[str, Any]] = []
    transient_statuses = {"queued", "researching", "generating", "evaluating", "cancelling"}
    for run_name in run_names:
        try:
            run_dir = safe_run_directory(run_name)
        except ValueError:
            continue
        job = live.get(run_name) or read_json_if_exists(run_dir / "job.json")
        manifest = read_json_if_exists(run_dir / "manifest.snapshot.json")
        search = manifest.get("search", {}) if isinstance(manifest.get("search"), dict) else {}
        direction = str(job.get("direction") or search.get("query") or run_name)
        status = str(job.get("status") or ("ready" if run_idea_metadata(run_dir) else "failed"))
        stage = str(job.get("stage") or ("完成" if status == "ready" else "不可用"))
        if run_name not in live and status in transient_statuses:
            status = "failed"
            stage = "服务重启后任务已中断"
        ideas = run_idea_metadata(run_dir) if status == "ready" else []
        created_at = str(job.get("created_at") or datetime.fromtimestamp(run_dir.stat().st_mtime, timezone.utc).isoformat())
        summaries.append(
            {
                "run_name": run_name,
                "job_id": job.get("id") if run_name in live else None,
                "direction": direction,
                "paper_count": int(job.get("paper_count") or len(manifest.get("papers", [])) or len(ideas)),
                "evaluate": bool(job.get("evaluate", (run_dir / "evaluation.json").is_file())),
                "status": status,
                "stage": stage,
                "progress": int(job.get("progress", 100 if status == "ready" else 0)),
                "created_at": created_at,
                "updated_at": str(job.get("updated_at") or created_at),
                "error": job.get("error"),
                "events": job.get("events", []),
                "pipeline_id": job.get("pipeline_id"),
                "ideas": ideas,
                "deletable": True,
            }
        )
    return sorted(summaries, key=lambda item: item["created_at"], reverse=True)


JOB_MANAGER = JobManager()


class AppHandler(SimpleHTTPRequestHandler):
    server_version = "W2CIdeaBrowser/1.0"

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_api_error(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self.send_json({"error": message}, status)

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        if path == "/api/health":
            try:
                cli = str(direction_research.generate_idea.resolve_codex_cli())
            except RuntimeError:
                cli = None
            self.send_json({"status": "ok", "codex_cli": cli})
            return
        if path == "/api/runs":
            self.send_json({"runs": list_run_summaries()})
            return
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{12})", path)
        if match:
            job = JOB_MANAGER.get(match.group(1))
            if job is None:
                self.send_api_error("Task not found.", HTTPStatus.NOT_FOUND)
            else:
                self.send_json(job.snapshot())
            return
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{12})/ideas", path)
        if match:
            job = JOB_MANAGER.get(match.group(1))
            if job is None:
                self.send_api_error("Task not found.", HTTPStatus.NOT_FOUND)
                return
            if job.status != "ready":
                self.send_api_error("Task is not ready.", HTTPStatus.CONFLICT)
                return
            data_path = job.run_dir / "web-data.json"
            data = json.loads(data_path.read_text(encoding="utf-8"))
            self.send_json(apply_human_reviews(data, job.run_dir))
            return
        match = re.fullmatch(r"/api/runs/([^/]+)/ideas", path)
        if match:
            try:
                run_dir = safe_run_directory(match.group(1))
            except ValueError as error:
                self.send_api_error(str(error), HTTPStatus.NOT_FOUND)
                return
            data_path = dataset_path_for_run(run_dir)
            if not data_path.is_file():
                self.send_api_error("Research run not found.", HTTPStatus.NOT_FOUND)
            else:
                data = json.loads(data_path.read_text(encoding="utf-8"))
                self.send_json(apply_human_reviews(data, run_dir))
            return
        super().do_GET()

    def do_PUT(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        match = re.fullmatch(r"/api/runs/([^/]+)/ideas/([a-z0-9_]+)/human-review", path)
        if not match:
            self.send_api_error("Endpoint not found.", HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("Invalid request size.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            run_dir = safe_run_directory(match.group(1))
            decision = payload.get("decision")
            if decision is not None and not isinstance(decision, str):
                raise ValueError("Human review decision must be a string or null.")
            write_human_review(run_dir, match.group(2), decision)
            self.send_json({"idea_id": match.group(2), "decision": decision})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_api_error(str(error))

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        resume_match = re.fullmatch(r"/api/runs/([^/]+)/resume", path)
        stop_match = re.fullmatch(r"/api/jobs/([a-f0-9]{12})/stop", path)
        if resume_match or stop_match:
            try:
                job = (JOB_MANAGER.resume(resume_match.group(1)) if resume_match
                       else JOB_MANAGER.stop(stop_match.group(1)))
                self.send_json(job.snapshot(), HTTPStatus.ACCEPTED)
            except (ValueError, OSError) as error:
                self.send_api_error(str(error), HTTPStatus.CONFLICT)
            return
        cancel_match = re.fullmatch(r"/api/jobs/([a-f0-9]{12})/cancel", path)
        if cancel_match:
            try:
                deleted = JOB_MANAGER.cancel_and_delete(cancel_match.group(1))
                if not deleted:
                    self.send_api_error("Task not found.", HTTPStatus.NOT_FOUND)
                else:
                    self.send_json({"deleted": True})
            except TimeoutError as error:
                self.send_api_error(str(error), HTTPStatus.CONFLICT)
            except ValueError as error:
                self.send_api_error(str(error), HTTPStatus.CONFLICT)
            return
        if path != "/api/jobs":
            self.send_api_error("Endpoint not found.", HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("Invalid request size.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            direction = str(payload.get("direction", "")).strip()
            paper_count = int(payload.get("paper_count", 3))
            evaluate = bool(payload.get("evaluate", True))
            if not 3 <= len(direction) <= 1000:
                raise ValueError("研究方向需要 3 到 1000 个字符。")
            if not 2 <= paper_count <= 6:
                raise ValueError("论文数量需要在 2 到 6 之间。")
            job = JOB_MANAGER.create(direction, paper_count, evaluate, timeout=900)
            self.send_json(job.snapshot(), HTTPStatus.ACCEPTED)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_api_error(str(error))

    def do_DELETE(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        match = re.fullmatch(r"/api/runs/([^/]+)", path)
        if not match:
            self.send_api_error("Endpoint not found.", HTTPStatus.NOT_FOUND)
            return
        try:
            JOB_MANAGER.delete_completed_run(match.group(1))
            self.send_json({"deleted": True})
        except ValueError as error:
            self.send_api_error(str(error), HTTPStatus.CONFLICT)

    def log_message(self, format: str, *args: Any) -> None:
        if not self.path.startswith("/api/jobs/"):
            super().log_message(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local W2C research workspace.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    if args.run_dir.is_dir():
        dataset = build_dataset(args.run_dir, args.manifest)
        output = write_dataset(dataset)
        print(f"Loaded {dataset['summary']['total']} ideas from {args.run_dir}")
        print(f"Data: {output}")
    else:
        if args.run_dir.name == "medical-vlm-10":
            (WEB_ROOT / "data" / "ideas.json").unlink(missing_ok=True)
        print(f"Skipped deleted default research folder: {args.run_dir}")
    handler = partial(AppHandler, directory=str(WEB_ROOT))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Open http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
