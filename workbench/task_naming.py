"""Shared names for new task directories; legacy identifiers remain readable."""
import re
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def name_pattern(kind: str) -> str:
    return rf"[\w-]{{1,60}}-{kind}-\d{{8}}-\d{{6}}-\d{{6}}(?:-[a-f0-9]{{8}})?"


def create_task_directory(root: Path, title: str, kind: str) -> Path:
    if kind not in {"design", "writing", "search", "table"}:
        raise ValueError("Unknown task kind")
    title = re.sub(r"[^\w-]+", "-", title.strip()).strip("-_")[:60].rstrip("-_")
    title = title.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip("-_")
    title = title or "未命名任务"
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S-%f")
    name = f"{title}-{kind}-{timestamp}"
    root.mkdir(parents=True, exist_ok=True)
    while True:
        directory = root / name
        try:
            directory.mkdir()
            return directory
        except FileExistsError:
            name = f"{title}-{kind}-{timestamp}-{uuid.uuid4().hex[:8]}"
