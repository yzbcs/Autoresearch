from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

WEB_ROOT = Path(__file__).resolve().parent
AUTO_WRITING_ROOT = WEB_ROOT.parent
if str(AUTO_WRITING_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(AUTO_WRITING_ROOT.parent))
from workbench.task_naming import create_task_directory, name_pattern

WRITING_RUNS_ROOT = AUTO_WRITING_ROOT / "writing_runs"
PROMPT_TEMPLATES_PATH = WEB_ROOT / "prompt_templates.json"
RESEARCH_PROMPT_TEMPLATES_PATH = WEB_ROOT / "research_prompt_templates.json"
LATEX_PROMPT_TEMPLATE_PATH = WEB_ROOT / "latex_prompt_template.json"
OUTPUT_SCHEMA_PATH = WEB_ROOT / "schemas" / "section_output.schema.json"
LATEX_OUTPUT_SCHEMA_PATH = WEB_ROOT / "schemas" / "latex_output.schema.json"
REFERENCE_OUTPUT_SCHEMA_PATH = WEB_ROOT / "schemas" / "reference_output.schema.json"
RESEARCH_SCHEMA_PATHS = {
    "intro_research": WEB_ROOT / "schemas" / "intro_research.schema.json",
    "related_work_plan": WEB_ROOT / "schemas" / "related_work_plan.schema.json",
    "related_work_research": WEB_ROOT / "schemas" / "related_work_research.schema.json",
    "reference_insertion": REFERENCE_OUTPUT_SCHEMA_PATH,
}
MAX_REQUEST_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_SUPPORT_FILES = 12
MAX_TEMPLATE_FILES = 1000
MAX_TEMPLATE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
DEFAULT_WRITING_TIMEOUT_SECONDS = 15 * 60
DEFAULT_RESEARCH_TIMEOUT_SECONDS = 20 * 60
PROJECT_ID_PATTERN = r"(?:writing-\d{8}-\d{6}-[a-f0-9]{6}|" + name_pattern("writing") + ")"
PROJECT_ID_RE = re.compile(PROJECT_ID_PATTERN)
BASE_SECTION_ORDER = ("intro", "related_work", "method", "experiments", "conclusion")
SECTION_ORDER = BASE_SECTION_ORDER + ("abstract",)
SECTION_LABELS = {
    "intro": "Introduction",
    "related_work": "Related Work",
    "method": "Method",
    "experiments": "Experiments",
    "conclusion": "Conclusion",
    "abstract": "Abstract",
}
SECTION_DESCRIPTIONS = {
    "intro": "研究意义、相关进展、问题缺口与贡献概述",
    "related_work": "按技术脉络组织并定位尚未解决的问题",
    "method": "从输入到输出说明整体流程与核心模块",
    "experiments": "实验设置、量化结果、消融与案例分析",
    "conclusion": "凝练方法、证据与论文层面的核心结论",
    "abstract": "在全文完成后概括问题、方法机制与核心实验结论",
}
RESEARCH_ACTIONS = (
    "intro_research",
    "related_work_plan",
    "related_work_research",
    "reference_insertion",
)
ACTION_LABELS = {
    "intro_research": "Introduction 论文调研",
    "related_work_plan": "Related Work 章节规划",
    "related_work_research": "Related Work 论文调研",
    "reference_insertion": "参考文献调研与插入",
}
ACTION_DESCRIPTIONS = {
    "intro_research": "为 Introduction 第一、二段检索并核验论文证据",
    "related_work_plan": "根据论文问题与 Introduction 规划三个技术主题",
    "related_work_research": "围绕三个既定主题分别检索并核验代表性论文",
    "reference_insertion": "补齐全文引用、插入 LaTeX citation 并生成 BibTeX",
}
RESEARCH_PATH_ENTRY_KEYS = {
    "intro_research": "intro_literature_research",
    "related_work_plan": "related_work_subsection_plan",
    "related_work_research": "related_work_literature_research",
    "reference_insertion": "reference_bibliography",
}
PATH_ENTRY_KEYS = {
    "intro": "generated_introduction",
    "related_work": "generated_related_work",
    "method": "generated_method",
    "experiments": "generated_experiments",
    "conclusion": "generated_conclusion",
    "abstract": "generated_abstract",
}
DEPENDENCIES = {
    "intro": (),
    "related_work": ("intro",),
    "method": ("intro",),
    "experiments": ("method",),
    "conclusion": ("intro", "method", "experiments"),
    "abstract": BASE_SECTION_ORDER,
}
ACTION_DEPENDENCIES = {
    "intro_research": (),
    "related_work_plan": ("intro", "intro_research"),
    "related_work_research": ("intro", "related_work_plan"),
    "reference_insertion": ("intro", "related_work", "experiments", "abstract"),
}
SECTION_ACTION_REQUIREMENTS = {
    "intro": ("intro_research",),
    "related_work": ("related_work_plan", "related_work_research"),
    "method": (),
    "experiments": (),
    "conclusion": (),
    "abstract": (),
}
DEPENDENTS = {
    "intro": ("related_work", "method", "experiments", "conclusion", "abstract"),
    "related_work": ("abstract",),
    "method": ("experiments", "conclusion", "abstract"),
    "experiments": ("conclusion", "abstract"),
    "conclusion": ("abstract",),
    "abstract": (),
}
ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
    ".pdf",
    ".doc",
    ".docx",
    ".csv",
    ".tsv",
    ".xls",
    ".xlsx",
}
LATEX_COMPILER_NAMES = ("latexmk", "tectonic", "xelatex", "pdflatex")


class GenerationPreconditionError(ValueError):
    def __init__(self, missing: list[str]):
        self.missing = missing
        labels = "、".join(requirement_label(item) for item in missing)
        super().__init__(f"请先完成或重新完成 {labels}，再继续当前步骤。")


def requirement_label(key: str) -> str:
    return SECTION_LABELS.get(key) or ACTION_LABELS.get(key) or key


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(value)
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def safe_filename(filename: str, fallback: str) -> str:
    name = Path(filename.replace("\\", "/")).name.strip()
    if not name:
        name = fallback
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._") or fallback
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不支持的文件类型：{suffix or '无扩展名'}")
    return f"{stem[:80]}{suffix}"


def decode_file(payload: dict[str, Any], fallback: str) -> tuple[str, bytes]:
    filename = safe_filename(str(payload.get("name", "")), fallback)
    encoded = payload.get("content_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError(f"文件 {filename} 没有可读取的内容。")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError(f"文件 {filename} 的编码无效。") from error
    if not data:
        raise ValueError(f"文件 {filename} 为空。")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"文件 {filename} 超过 20 MB。")
    return filename, data


def safe_project_dir(project_id: str) -> Path:
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError("写作项目不存在。")
    path = (WRITING_RUNS_ROOT / project_id).resolve()
    root = WRITING_RUNS_ROOT.resolve()
    if path.parent != root or not path.is_dir():
        raise ValueError("写作项目不存在。")
    return path


def project_path(project_id: str) -> Path:
    return safe_project_dir(project_id) / "project.json"


def load_project(project_id: str) -> dict[str, Any]:
    path = project_path(project_id)
    if not path.is_file():
        raise ValueError("写作项目不存在。")
    project = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(project, dict) or project.get("id") != project_id:
        raise ValueError("写作项目配置无效。")
    ensure_project_shape(project)
    return project


def save_project(project: dict[str, Any]) -> None:
    ensure_project_shape(project)
    project["updated_at"] = utc_now()
    write_json_atomic(WRITING_RUNS_ROOT / project["id"] / "project.json", project)


def empty_task_record() -> dict[str, Any]:
    return {
        "status": "empty",
        "generated_at": None,
        "error": None,
        "job_id": None,
    }


def ensure_project_shape(project: dict[str, Any]) -> None:
    sections = project.setdefault("sections", {})
    missing_abstract = "abstract" not in sections
    for section in SECTION_ORDER:
        sections.setdefault(section, empty_task_record())
    research = project.setdefault("research", {})
    missing_reference = "reference_insertion" not in research
    for action in RESEARCH_ACTIONS:
        research.setdefault(action, empty_task_record())
    publication = project.setdefault("publication", empty_task_record())
    for key, value in {
        **empty_task_record(),
        "template": None,
        "compiler": None,
        "latex_zip": None,
        "pdf": None,
        "compile_log": None,
    }.items():
        publication.setdefault(key, value)
    if (missing_abstract or missing_reference) and publication.get("status") in {
        "ready",
        "partial",
    }:
        publication.update(
            {
                "status": "stale",
                "error": "写作流程已新增 Abstract 与参考文献步骤，请完成后重新排版发布。",
                "job_id": None,
            }
        )


def section_output_path(run_dir: Path, section: str) -> Path:
    return run_dir / "manuscript" / f"{section}.json"


def research_output_path(run_dir: Path, action: str) -> Path:
    if action == "reference_insertion":
        return reference_output_path(run_dir)
    return run_dir / "context" / f"{action}.json"


def reference_output_path(run_dir: Path) -> Path:
    return run_dir / "manuscript" / "referenc.json"


def reference_bib_path(run_dir: Path) -> Path:
    return run_dir / "manuscript" / "references.bib"


def publication_dir(run_dir: Path) -> Path:
    return run_dir / "publication"


def all_sections_ready(project: dict[str, Any]) -> bool:
    return not missing_requirements(project, SECTION_ORDER)


def publication_missing_requirements(project: dict[str, Any]) -> list[str]:
    requirements = SECTION_ORDER + ("reference_insertion",)
    return missing_requirements(project, requirements)


def section_content(run_dir: Path, section: str) -> str:
    path = section_output_path(run_dir, section)
    if not path.is_file():
        return ""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    content = value.get(section) if isinstance(value, dict) else None
    return content.strip() if isinstance(content, str) else ""


def research_content(run_dir: Path, action: str) -> dict[str, Any] | None:
    path = research_output_path(run_dir, action)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def requirement_ready(project: dict[str, Any], requirement: str) -> bool:
    run_dir = WRITING_RUNS_ROOT / project["id"]
    if requirement in SECTION_ORDER:
        record = project["sections"][requirement]
        return record.get("status") == "ready" and bool(
            section_content(run_dir, requirement)
        )
    if requirement in RESEARCH_ACTIONS:
        record = project["research"][requirement]
        return record.get("status") == "ready" and bool(
            research_content(run_dir, requirement)
        )
    return False


def missing_requirements(
    project: dict[str, Any], requirements: tuple[str, ...]
) -> list[str]:
    return [item for item in requirements if not requirement_ready(project, item)]


def unmet_dependencies(project: dict[str, Any], section: str) -> list[str]:
    return missing_requirements(project, DEPENDENCIES[section])


def unmet_section_requirements(project: dict[str, Any], section: str) -> list[str]:
    requirements = DEPENDENCIES[section] + SECTION_ACTION_REQUIREMENTS[section]
    return missing_requirements(project, requirements)


def unmet_action_requirements(project: dict[str, Any], action: str) -> list[str]:
    return missing_requirements(project, ACTION_DEPENDENCIES[action])


def project_has_running_task(project: dict[str, Any]) -> bool:
    records = (
        list(project["sections"].values())
        + list(project["research"].values())
        + [project["publication"]]
    )
    return any(record.get("status") == "running" for record in records)


def build_path_contract(project: dict[str, Any]) -> dict[str, Any]:
    run_dir = (WRITING_RUNS_ROOT / project["id"]).resolve()
    experiment_path = (run_dir / project["experiment"]["relative_path"]).resolve()
    support_dir = (run_dir / "input" / "supporting_materials").resolve()
    entries: dict[str, dict[str, Any]] = {
        "experiment_description": {
            "path": str(experiment_path),
            "contains": "The uploaded experiment description: research objective, method design, implementation details, evaluation protocol, and recorded results. It is the primary factual source.",
            "description_zh": "上传的实验说明；应包含研究目标、方法设计、实现细节、评估协议和已有结果，是事实主来源。",
            "required": True,
        },
        "supporting_materials": {
            "path": str(support_dir),
            "contains": "Optional reference papers, tables, figures, notes, or supplementary evidence uploaded with this writing project. The directory may be empty.",
            "description_zh": "可选补充资料目录；用于放置参考论文、表格、图片、笔记或其他证据，可以为空。",
            "required": False,
        },
        "intro_literature_research": {
            "path": str(research_output_path(run_dir, "intro_research").resolve()),
            "contains": "Verified literature evidence for Introduction paragraphs 1 and 2, including source URLs and explicit evidence boundaries.",
            "description_zh": "Introduction 调研结果；分别保存第一段的领域证据与第二段的代表性论文，并记录来源链接和证据边界。",
            "required": False,
        },
        "related_work_subsection_plan": {
            "path": str(research_output_path(run_dir, "related_work_plan").resolve()),
            "contains": "The approved plan of exactly three Related Work subsection titles, scopes, connections, and search queries.",
            "description_zh": "Related Work 章节规划；固定三个 subsection 的名称、范围、与本文关系及检索词。",
            "required": False,
        },
        "related_work_literature_research": {
            "path": str(research_output_path(run_dir, "related_work_research").resolve()),
            "contains": "Verified literature evidence organized under the exact three planned Related Work subsection titles.",
            "description_zh": "Related Work 调研结果；严格按已规划的三个 subsection 整理并核验代表性论文。",
            "required": False,
        },
        "generated_introduction": {
            "path": str(section_output_path(run_dir, "intro").resolve()),
            "contains": "The generated Introduction JSON object. Read its intro field when a later section declares Introduction as a dependency.",
            "description_zh": "Introduction 输出；JSON 对象的 intro 字段保存完整引言，后续依赖引言的部分会读取它。",
            "required": False,
        },
        "generated_related_work": {
            "path": str(section_output_path(run_dir, "related_work").resolve()),
            "contains": "The generated Related Work JSON object. Read its related_work field only when needed for terminology consistency.",
            "description_zh": "Related Work 输出；JSON 对象的 related_work 字段保存完整相关工作。",
            "required": False,
        },
        "generated_method": {
            "path": str(section_output_path(run_dir, "method").resolve()),
            "contains": "The generated Method JSON object. Read its method field when Experiments or Conclusion declares Method as a dependency.",
            "description_zh": "Method 输出；JSON 对象的 method 字段保存完整方法，Experiments 和 Conclusion 会读取它。",
            "required": False,
        },
        "generated_experiments": {
            "path": str(section_output_path(run_dir, "experiments").resolve()),
            "contains": "The generated Experiments JSON object. Read its experiments field when Conclusion declares Experiments as a dependency.",
            "description_zh": "Experiments 输出；JSON 对象的 experiments 字段保存完整实验，Conclusion 会读取它。",
            "required": False,
        },
        "generated_conclusion": {
            "path": str(section_output_path(run_dir, "conclusion").resolve()),
            "contains": "The generated Conclusion JSON object with a conclusion field.",
            "description_zh": "Conclusion 输出；JSON 对象的 conclusion 字段保存完整结论。",
            "required": False,
        },
        "generated_abstract": {
            "path": str(section_output_path(run_dir, "abstract").resolve()),
            "contains": "The generated Abstract JSON object with an abstract field.",
            "description_zh": "Abstract 输出；JSON 对象的 abstract 字段保存完整摘要。",
            "required": False,
        },
        "reference_bibliography": {
            "path": str(reference_output_path(run_dir).resolve()),
            "contains": "The reference artifact containing verified metadata, BibTeX, citation coverage, and citation-inserted manuscript sections.",
            "description_zh": "参考文献产物；保存核验后的元数据、BibTeX、引用覆盖范围及插入引用后的章节。",
            "required": False,
        },
        "reference_bib_file": {
            "path": str(reference_bib_path(run_dir).resolve()),
            "contains": "The directly compilable BibTeX bibliography generated from referenc.json.",
            "description_zh": "可直接编译的 BibTeX 文件；由 referenc.json 中的最终参考文献生成。",
            "required": False,
        },
        "latex_template_source": {
            "path": str((publication_dir(run_dir) / "source").resolve()),
            "contains": "The safely extracted LaTeX template and the adapted primary TeX document.",
            "description_zh": "LaTeX 模板工作目录；保存安全解压后的模板及适配完成的主 TeX 文件。",
            "required": False,
        },
        "latex_package": {
            "path": str((publication_dir(run_dir) / "manuscript-latex.zip").resolve()),
            "contains": "The downloadable LaTeX source package after manuscript adaptation.",
            "description_zh": "适配后的 LaTeX 源码包；发布任务完成后可直接下载。",
            "required": False,
        },
        "compiled_pdf": {
            "path": str((publication_dir(run_dir) / "manuscript.pdf").resolve()),
            "contains": "The compiled paper PDF when a supported LaTeX compiler is available and compilation succeeds.",
            "description_zh": "编译后的论文 PDF；本机编译器可用且模板编译成功时生成。",
            "required": False,
        },
        "resolved_prompts": {
            "path": str((run_dir / "prompts").resolve()),
            "contains": "One resolved prompt per manually started research or writing task. Each file records the exact runtime paths supplied to that agent.",
            "description_zh": "运行时 prompt 目录；每次手工启动的调研或生成任务都会保存一份已解析 prompt，记录实际传入 agent 的全部路径。",
            "required": False,
        },
    }
    return {
        "project_id": project["id"],
        "generated_at": utc_now(),
        "rule": "Agents may read only these runtime paths. Prompt templates must not contain machine-specific or project-specific paths.",
        "entries": entries,
    }


def refresh_path_contract(project: dict[str, Any]) -> dict[str, Any]:
    contract = build_path_contract(project)
    run_dir = WRITING_RUNS_ROOT / project["id"]
    write_json_atomic(run_dir / "path_contract.json", contract)
    return contract


def create_project(
    title: str,
    experiment_file: dict[str, Any],
    support_files: list[dict[str, Any]] | None = None,
    pipeline_id: str | None = None,
) -> dict[str, Any]:
    title = title.strip()
    if not 1 <= len(title) <= 120:
        raise ValueError("写作名称需要 1 到 120 个字符。")
    experiment_name, experiment_data = decode_file(experiment_file, "experiment")
    support_files = support_files or []
    if len(support_files) > MAX_SUPPORT_FILES:
        raise ValueError(f"补充资料最多上传 {MAX_SUPPORT_FILES} 个文件。")

    run_dir = create_task_directory(WRITING_RUNS_ROOT, title, "writing")
    project_id = run_dir.name
    input_dir = run_dir / "input"
    support_dir = input_dir / "supporting_materials"
    (run_dir / "manuscript").mkdir(parents=True, exist_ok=False)
    (run_dir / "prompts").mkdir()
    (run_dir / "context").mkdir()
    support_dir.mkdir(parents=True)
    experiment_path = input_dir / experiment_name
    experiment_path.write_bytes(experiment_data)

    stored_support: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for index, item in enumerate(support_files, start=1):
        name, data = decode_file(item, f"support_{index}")
        candidate = name
        stem, suffix = Path(name).stem, Path(name).suffix
        serial = 2
        while candidate.lower() in used_names:
            candidate = f"{stem}_{serial}{suffix}"
            serial += 1
        used_names.add(candidate.lower())
        (support_dir / candidate).write_bytes(data)
        stored_support.append(
            {
                "name": candidate,
                "relative_path": str(Path("input") / "supporting_materials" / candidate),
                "size": len(data),
            }
        )
    now = utc_now()
    project: dict[str, Any] = {
        "id": project_id,
        "title": title,
        "pipeline_id": pipeline_id,
        "created_at": now,
        "updated_at": now,
        "experiment": {
            "name": experiment_name,
            "relative_path": str(Path("input") / experiment_name),
            "size": len(experiment_data),
        },
        "support_files": stored_support,
        "sections": {section: empty_task_record() for section in SECTION_ORDER},
        "research": {action: empty_task_record() for action in RESEARCH_ACTIONS},
    }
    save_project(project)
    refresh_path_contract(project)
    return project


def invalidate_project_inputs(project: dict[str, Any]) -> None:
    run_dir = WRITING_RUNS_ROOT / project["id"]
    reason = "项目输入文件已更新，请基于最新文件重新完成此步骤。"
    for action in RESEARCH_ACTIONS:
        record = project["research"][action]
        if research_content(run_dir, action):
            record.update({"status": "stale", "error": reason, "job_id": None})
        else:
            record.update({**empty_task_record()})
    for section in SECTION_ORDER:
        record = project["sections"][section]
        if section_content(run_dir, section):
            record.update({"status": "stale", "error": reason, "job_id": None})
        else:
            record.update({**empty_task_record()})
    mark_publication_stale(project, "项目输入文件已更新，请重新生成全部章节后再次排版发布。")


def update_project(
    project_id: str,
    title: str,
    experiment_file: dict[str, Any] | None,
    retained_support_paths: list[str] | None,
    new_support_files: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    project = load_project(project_id)
    if project_has_running_task(project):
        raise ValueError("请先停止正在运行的任务，再修改项目文件。")
    title = title.strip()
    if not 1 <= len(title) <= 120:
        raise ValueError("写作名称需要 1 到 120 个字符。")

    title_changed = title != project["title"]
    current_support = project.get("support_files", [])
    known_support = {str(item["relative_path"]): item for item in current_support}
    if retained_support_paths is None:
        retained_support_paths = list(known_support)
    if not isinstance(retained_support_paths, list) or not all(
        isinstance(item, str) for item in retained_support_paths
    ):
        raise ValueError("保留的补充资料清单格式无效。")
    if len(retained_support_paths) != len(set(retained_support_paths)):
        raise ValueError("保留的补充资料清单包含重复项。")
    unknown = [item for item in retained_support_paths if item not in known_support]
    if unknown:
        raise ValueError("补充资料清单包含不属于当前项目的文件。")

    new_support_files = new_support_files or []
    if not isinstance(new_support_files, list) or not all(
        isinstance(item, dict) for item in new_support_files
    ):
        raise ValueError("新增补充资料格式无效。")
    if len(retained_support_paths) + len(new_support_files) > MAX_SUPPORT_FILES:
        raise ValueError(f"补充资料最多保留和上传 {MAX_SUPPORT_FILES} 个文件。")

    decoded_experiment = (
        decode_file(experiment_file, "experiment") if experiment_file is not None else None
    )
    decoded_support = [
        decode_file(item, f"support_{index}")
        for index, item in enumerate(new_support_files, start=1)
    ]

    run_dir = WRITING_RUNS_ROOT / project_id
    input_dir = run_dir / "input"
    support_dir = input_dir / "supporting_materials"
    retained = [known_support[item] for item in retained_support_paths]
    used_names = {str(item["name"]).lower() for item in retained}
    added: list[dict[str, Any]] = []
    for name, data in decoded_support:
        candidate = name
        stem, suffix = Path(name).stem, Path(name).suffix
        serial = 2
        while candidate.lower() in used_names:
            candidate = f"{stem}_{serial}{suffix}"
            serial += 1
        used_names.add(candidate.lower())
        write_bytes_atomic(support_dir / candidate, data)
        added.append(
            {
                "name": candidate,
                "relative_path": str(Path("input") / "supporting_materials" / candidate),
                "size": len(data),
            }
        )

    retained_set = set(retained_support_paths)
    for item in current_support:
        if str(item["relative_path"]) not in retained_set:
            (run_dir / str(item["relative_path"])).unlink(missing_ok=True)

    input_changed = bool(decoded_experiment or decoded_support) or len(retained) != len(
        current_support
    )
    if decoded_experiment is not None:
        name, data = decoded_experiment
        old_path = run_dir / str(project["experiment"]["relative_path"])
        new_path = input_dir / name
        write_bytes_atomic(new_path, data)
        if old_path.resolve() != new_path.resolve():
            old_path.unlink(missing_ok=True)
        project["experiment"] = {
            "name": name,
            "relative_path": str(Path("input") / name),
            "size": len(data),
        }
    project["support_files"] = retained + added
    project["title"] = title
    if input_changed:
        invalidate_project_inputs(project)
    elif title_changed:
        mark_publication_stale(project, "写作名称已更新，请重新排版发布以同步论文标题。")
    save_project(project)
    refresh_path_contract(project)
    return project


def decode_zip_file(payload: dict[str, Any]) -> tuple[str, bytes]:
    raw_name = Path(str(payload.get("name", "")).replace("\\", "/")).name.strip()
    if not raw_name or Path(raw_name).suffix.lower() != ".zip":
        raise ValueError("请上传 ZIP 格式的 LaTeX 模板。")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(raw_name).stem).strip("._")
    name = f"{(name or 'latex-template')[:80]}.zip"
    encoded = payload.get("content_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("LaTeX 模板没有可读取的内容。")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("LaTeX 模板编码无效。") from error
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("LaTeX 模板为空或超过 20 MB。")
    return name, data


def extract_latex_template(data: bytes, destination: Path) -> list[Path]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError("LaTeX 模板 ZIP 已损坏或不是有效压缩包。") from error
    with archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if not files or len(files) > MAX_TEMPLATE_FILES:
            raise ValueError(f"LaTeX 模板必须包含 1 到 {MAX_TEMPLATE_FILES} 个文件。")
        if sum(item.file_size for item in files) > MAX_TEMPLATE_UNCOMPRESSED_BYTES:
            raise ValueError("LaTeX 模板解压后超过 100 MB。")
        extracted: list[Path] = []
        normalized_paths: set[str] = set()
        for item in files:
            relative = PurePosixPath(item.filename.replace("\\", "/"))
            mode = item.external_attr >> 16
            if (
                relative.is_absolute()
                or not relative.parts
                or ".." in relative.parts
                or any(part in {"", "."} or ":" in part for part in relative.parts)
                or stat.S_ISLNK(mode)
            ):
                raise ValueError("LaTeX 模板包含不安全的文件路径或符号链接。")
            normalized = relative.as_posix().lower()
            if normalized in normalized_paths:
                raise ValueError("LaTeX 模板包含重复的文件路径。")
            normalized_paths.add(normalized)
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            write_bytes_atomic(target, archive.read(item))
            extracted.append(target)
    return extracted


def detect_latex_main(paths: list[Path], source_root: Path) -> Path:
    candidates: list[tuple[int, Path]] = []
    preferred_names = {"main.tex": 30, "paper.tex": 20, "manuscript.tex": 10}
    for path in paths:
        if path.suffix.lower() != ".tex":
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        if "\\documentclass" not in content or "\\begin{document}" not in content:
            continue
        depth = len(path.relative_to(source_root).parts)
        score = preferred_names.get(path.name.lower(), 0) - depth
        if "\\end{document}" in content:
            score += 5
        candidates.append((score, path))
    if not candidates:
        raise ValueError("模板中没有找到同时包含 documentclass 和 document 环境的主 TeX 文件。")
    candidates.sort(key=lambda item: (item[0], str(item[1]).lower()), reverse=True)
    return candidates[0][1]


def bibtex_key_pattern(citation_key: str) -> re.Pattern[str]:
    return re.compile(
        rf"@[A-Za-z]+\s*\{{\s*{re.escape(citation_key)}\s*,",
        re.IGNORECASE,
    )


def validate_bibtex_entry(citation_key: Any, bibtex: Any, field: str) -> tuple[str, str]:
    key = citation_key.strip() if isinstance(citation_key, str) else ""
    value = bibtex.strip() if isinstance(bibtex, str) else ""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9:_-]{2,79}", key):
        raise ValueError(f"{field}.citation_key 不是有效的 ASCII 引用键。")
    if len(value) < 40 or not bibtex_key_pattern(key).search(value):
        raise ValueError(f"{field}.bibtex 不是与 citation_key 匹配的完整 BibTeX 条目。")
    return key, value


def legacy_citation_key(item: dict[str, Any], title: str) -> str:
    author = str(item.get("lead_author") or item.get("authors") or "").strip()
    author_parts = re.findall(
        r"[A-Za-z][A-Za-z0-9]+",
        author.encode("ascii", "ignore").decode("ascii"),
    )
    title_parts = [
        part
        for part in re.findall(
            r"[A-Za-z][A-Za-z0-9]+",
            title.encode("ascii", "ignore").decode("ascii"),
        )
        if part.lower() not in {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}
    ]
    author_token = author_parts[-1] if author_parts else ""
    title_token = title_parts[0] if title_parts else "Reference"
    year = str(item.get("year") or "")
    key = f"{author_token}{year}{title_token}" or "LegacyReference"
    key = re.sub(r"[^A-Za-z0-9:_-]", "", key)
    if not key or not key[0].isalpha():
        key = "Legacy" + key
    return key[:80]


def clean_bibtex_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("{", "").replace("}", "")
    for character in ("&", "%", "#", "_"):
        text = text.replace(character, "\\" + character)
    return text


def build_legacy_bibtex(record: dict[str, Any], citation_key: str) -> str:
    fields = [("title", clean_bibtex_text(record.get("title")))]
    if record.get("authors"):
        fields.append(("author", clean_bibtex_text(record["authors"])))
    if record.get("year"):
        fields.append(("year", clean_bibtex_text(record["year"])))
    if record.get("venue"):
        fields.append(("howpublished", clean_bibtex_text(record["venue"])))
    if record.get("doi"):
        fields.append(("doi", str(record["doi"]).strip()))
    if record.get("source_url"):
        fields.append(("url", str(record["source_url"]).strip()))
    lines = [f"@misc{{{citation_key},"]
    lines.extend(f"  {name} = {{{value}}}," for name, value in fields if value)
    lines.append("}")
    return "\n".join(lines)


def research_reference_records(action: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[tuple[dict[str, Any], str]] = []
    if action == "intro_research":
        sources.extend((item, "intro_p1") for item in result.get("paragraph_1_evidence", []))
        sources.extend((item, "intro_p2") for item in result.get("paragraph_2_papers", []))
    elif action == "related_work_research":
        for subsection in result.get("subsections", []):
            sources.extend((item, "related_work") for item in subsection.get("papers", []))

    records: list[dict[str, Any]] = []
    for item, scope in sources:
        title = str(item.get("title") or item.get("source_title") or "").strip()
        citation_key = str(item.get("citation_key", "")).strip()
        bibtex = str(item.get("bibtex", "")).strip()
        legacy = not citation_key or not bibtex
        if legacy:
            citation_key = legacy_citation_key(item, title)
        authors = str(item.get("authors") or item.get("lead_author") or "").strip()
        record = {
            "citation_key": citation_key,
            "title": title,
            "authors": authors,
            "year": item.get("year"),
            "venue": str(item.get("venue", "")).strip(),
            "doi": str(item.get("doi", "")).strip(),
            "source_url": str(item.get("source_url", "")).strip(),
            "bibtex": bibtex,
            "used_in": [scope],
            "source_actions": [action],
            "metadata_status": "legacy_candidate" if legacy else "verified",
        }
        if legacy:
            record["bibtex"] = build_legacy_bibtex(record, citation_key)
        records.append(
            record
        )
    return records


def reference_identity(record: dict[str, Any]) -> str:
    title = re.sub(r"[^a-z0-9]+", "", str(record.get("title", "")).lower())
    if title:
        return f"title:{title}"
    doi = str(record.get("doi", "")).strip().lower()
    if doi:
        return f"doi:{doi.removeprefix('https://doi.org/').removeprefix('doi:')}"
    return "title:"


def merge_research_references(
    project: dict[str, Any], action: str, result: dict[str, Any]
) -> None:
    if action not in {"intro_research", "related_work_research"}:
        return
    run_dir = WRITING_RUNS_ROOT / project["id"]
    existing = research_content(run_dir, "reference_insertion") or {}
    merged: dict[str, dict[str, Any]] = {}
    key_identities: dict[str, str] = {}
    for record in list(existing.get("references", [])) + research_reference_records(action, result):
        if not isinstance(record, dict):
            continue
        identity = reference_identity(record)
        if identity in {"title:", "doi:"}:
            continue
        current = merged.get(identity)
        if current is None:
            current = dict(record)
            current["used_in"] = list(dict.fromkeys(record.get("used_in", [])))
            current["source_actions"] = list(
                dict.fromkeys(record.get("source_actions", []))
            )
            key = str(current.get("citation_key", "")).strip()
            if key in key_identities and key_identities[key] != identity:
                base = key or "Reference"
                serial = 2
                while f"{base}{serial}" in key_identities:
                    serial += 1
                replacement = f"{base}{serial}"
                bibtex = str(current.get("bibtex", ""))
                current["bibtex"] = bibtex_key_pattern(key).sub(
                    lambda match: match.group(0).replace(key, replacement, 1),
                    bibtex,
                    count=1,
                )
                current["citation_key"] = replacement
                key = replacement
            key_identities[key] = identity
            merged[identity] = current
        else:
            for field in ("authors", "year", "venue", "doi", "source_url"):
                if not current.get(field) and record.get(field):
                    current[field] = record[field]
            current["used_in"] = list(
                dict.fromkeys(current.get("used_in", []) + record.get("used_in", []))
            )
            current["source_actions"] = list(
                dict.fromkeys(
                    current.get("source_actions", []) + record.get("source_actions", [])
                )
            )

    references = list(merged.values())
    for record in references:
        if record.get("metadata_status") == "legacy_candidate":
            record["bibtex"] = build_legacy_bibtex(record, record["citation_key"])
    references.sort(key=lambda item: (int(item.get("year") or 0), item.get("title", "")))
    existing.update(
        {
            "migration_version": 2,
            "phase": "research",
            "references": references,
            "bibtex": "\n\n".join(str(item.get("bibtex", "")).strip() for item in references),
            "updated_sections": existing.get("updated_sections"),
            "coverage": existing.get("coverage"),
            "evidence_boundaries": existing.get("evidence_boundaries", []),
        }
    )
    write_json_atomic(reference_output_path(run_dir), existing)
    reference_bib_path(run_dir).write_text(existing["bibtex"].rstrip() + "\n", encoding="utf-8")
    record = project["research"]["reference_insertion"]
    if record.get("status") not in {"ready", "stale"}:
        record.update(
            {
                "status": "draft",
                "generated_at": utc_now(),
                "error": None,
                "job_id": None,
            }
        )


def sync_existing_research_references(project: dict[str, Any]) -> bool:
    run_dir = WRITING_RUNS_ROOT / project["id"]
    existing = research_content(run_dir, "reference_insertion") or {}
    if existing.get("phase") == "inserted":
        return False
    represented = {
        action
        for record in existing.get("references", [])
        if isinstance(record, dict)
        for action in record.get("source_actions", [])
    }
    needs_upgrade = existing.get("migration_version") != 2
    changed = False
    for action in ("intro_research", "related_work_research"):
        result = research_content(run_dir, action)
        if result and (needs_upgrade or action not in represented):
            merge_research_references(project, action, result)
            changed = True
    return changed


def migrate_existing_research_references() -> None:
    for path in WRITING_RUNS_ROOT.glob("*/project.json"):
        try:
            project = load_project(path.parent.name)
            if sync_existing_research_references(project):
                save_project(project)
                refresh_path_contract(project)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue


def load_templates() -> dict[str, Any]:
    templates = json.loads(PROMPT_TEMPLATES_PATH.read_text(encoding="utf-8"))
    if not isinstance(templates, dict) or set(templates) != set(SECTION_ORDER):
        raise ValueError("Prompt template configuration is invalid.")
    return templates


def load_research_templates() -> dict[str, Any]:
    templates = json.loads(RESEARCH_PROMPT_TEMPLATES_PATH.read_text(encoding="utf-8"))
    if not isinstance(templates, dict) or set(templates) != set(RESEARCH_ACTIONS):
        raise ValueError("Research prompt template configuration is invalid.")
    return templates


def load_latex_prompt_template() -> dict[str, Any]:
    template = json.loads(LATEX_PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(template, dict) or not isinstance(template.get("template"), list):
        raise ValueError("LaTeX prompt template configuration is invalid.")
    return template


def agent_path_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": entry["path"],
        "contains": entry["contains"],
        "required": entry["required"],
    }


def resolve_template(
    project: dict[str, Any], task: str, template_lines: Any, path_context: dict[str, Any]
) -> str:
    if not isinstance(template_lines, list) or not all(
        isinstance(line, str) and line.strip() for line in template_lines
    ):
        raise ValueError(f"Prompt template for {task} is invalid.")
    template = "\n\n".join(line.strip() for line in template_lines)
    if re.search(r"(?:[A-Za-z]:[\\/]|/Users/|/home/)", template):
        raise ValueError(f"Prompt template for {task} contains a fixed machine path.")
    resolved = template.replace(
        "<<PATH_CONTEXT_JSON>>",
        json.dumps(path_context, ensure_ascii=False, indent=2),
    )
    if "<<" in resolved or ">>" in resolved:
        raise ValueError(f"Prompt template for {task} has unresolved placeholders.")
    prompt_path = WRITING_RUNS_ROOT / project["id"] / "prompts" / f"{task}.resolved.txt"
    prompt_path.write_text(resolved.rstrip() + "\n", encoding="utf-8")
    return resolved


def build_resolved_prompt(project: dict[str, Any], section: str) -> str:
    if section not in SECTION_ORDER:
        raise ValueError("写作部分不存在。")
    missing = unmet_section_requirements(project, section)
    if missing:
        raise GenerationPreconditionError(missing)
    templates = load_templates()

    contract = refresh_path_contract(project)
    entries = contract["entries"]
    path_context = {
        "current_section": section,
        "current_output": {
            "path": entries[PATH_ENTRY_KEYS[section]]["path"],
            "contains": f"The destination JSON file for the generated {SECTION_LABELS[section]} section.",
            "required": False,
        },
        "experiment_description": agent_path_entry(entries["experiment_description"]),
        "supporting_materials": agent_path_entry(entries["supporting_materials"]),
        "dependencies": {
            dependency: agent_path_entry(entries[PATH_ENTRY_KEYS[dependency]])
            for dependency in DEPENDENCIES[section]
        },
        "research_evidence": {
            action: agent_path_entry(entries[RESEARCH_PATH_ENTRY_KEYS[action]])
            for action in SECTION_ACTION_REQUIREMENTS[section]
        },
        "path_contract": {
            "path": str((WRITING_RUNS_ROOT / project["id"] / "path_contract.json").resolve()),
            "contains": "The complete runtime path contract and content expectations for this writing project.",
        },
    }
    return resolve_template(project, section, templates[section].get("template"), path_context)


def build_research_prompt(project: dict[str, Any], action: str) -> str:
    if action not in RESEARCH_ACTIONS:
        raise ValueError("调研步骤不存在。")
    missing = unmet_action_requirements(project, action)
    if missing:
        raise GenerationPreconditionError(missing)
    templates = load_research_templates()
    contract = refresh_path_contract(project)
    entries = contract["entries"]
    dependencies: dict[str, Any] = {}
    for requirement in ACTION_DEPENDENCIES[action]:
        if requirement in SECTION_ORDER:
            dependencies[requirement] = agent_path_entry(entries[PATH_ENTRY_KEYS[requirement]])
        else:
            dependencies[requirement] = agent_path_entry(
                entries[RESEARCH_PATH_ENTRY_KEYS[requirement]]
            )
    path_context = {
        "current_action": action,
        "current_output": {
            "path": entries[RESEARCH_PATH_ENTRY_KEYS[action]]["path"],
            "contains": "The destination JSON file for the current literature-research or planning task.",
            "required": False,
        },
        "experiment_description": agent_path_entry(entries["experiment_description"]),
        "supporting_materials": agent_path_entry(entries["supporting_materials"]),
        "dependencies": dependencies,
        "path_contract": {
            "path": str((WRITING_RUNS_ROOT / project["id"] / "path_contract.json").resolve()),
            "contains": "The complete runtime path contract and content expectations for this writing project.",
        },
    }
    if action == "reference_insertion":
        path_context["existing_references"] = agent_path_entry(
            entries["reference_bibliography"]
        )
        path_context["prior_research"] = {
            research_action: agent_path_entry(
                entries[RESEARCH_PATH_ENTRY_KEYS[research_action]]
            )
            for research_action in ("intro_research", "related_work_research")
        }
    return resolve_template(project, action, templates[action].get("template"), path_context)


def build_latex_prompt(project: dict[str, Any], main_tex: Path) -> str:
    missing = publication_missing_requirements(project)
    if missing:
        raise GenerationPreconditionError(missing)
    run_dir = WRITING_RUNS_ROOT / project["id"]
    source_root = publication_dir(run_dir) / "source"
    try:
        main_relative = main_tex.resolve().relative_to(source_root.resolve())
    except ValueError as error:
        raise ValueError("LaTeX 主文件不在模板工作目录中。") from error
    template = load_latex_prompt_template()
    path_context = {
        "task": "latex_publication",
        "project_title": project["title"],
        "template_root": {
            "path": str(source_root.resolve()),
            "contains": "The complete extracted LaTeX template, including class files, bibliography files, figures, and the primary TeX document.",
            "required": True,
        },
        "primary_tex": {
            "path": str(main_tex.resolve()),
            "relative_path": main_relative.as_posix(),
            "contains": "The primary TeX document whose template structure and preamble must be preserved while replacing demonstration manuscript content.",
            "required": True,
        },
        "generated_sections": {
            section: {
                "path": str(section_output_path(run_dir, section).resolve()),
                "contains": f"The generated {SECTION_LABELS[section]} JSON object. Read its {section} field.",
                "required": True,
            }
            for section in SECTION_ORDER
        },
        "reference_bibliography": {
            "path": str(reference_output_path(run_dir).resolve()),
            "contains": "The final verified reference artifact, including BibTeX and citation-inserted Introduction, Related Work, and Experiments sections.",
            "required": True,
        },
        "reference_bib_file": {
            "path": str(reference_bib_path(run_dir).resolve()),
            "contains": "The ready-to-compile BibTeX database for every citation in the manuscript.",
            "required": True,
        },
    }
    return resolve_template(
        project,
        "latex_publication",
        template.get("template"),
        path_context,
    )


def codex_candidates() -> list[Path]:
    candidates: list[Path] = []
    if configured := os.environ.get("CODEX_CLI"):
        candidates.append(Path(configured))
    if discovered := shutil.which("codex"):
        candidates.append(Path(discovered))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    bundled = local_app_data / "OpenAI" / "Codex" / "bin"
    if bundled.is_dir():
        candidates.extend(
            sorted(
                bundled.glob("*/codex.exe"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        )
    return list(dict.fromkeys(path.resolve() for path in candidates))


def resolve_codex_cli() -> Path:
    failures: list[str] = []
    for candidate in codex_candidates():
        try:
            result = subprocess.run(
                [str(candidate), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            failures.append(f"{candidate}: {error}")
            continue
        if result.returncode == 0:
            return candidate
        failures.append(f"{candidate}: {result.stderr.strip()}")
    detail = "\n".join(failures) or "No Codex CLI candidate was found."
    raise RuntimeError("无法找到可用的 Codex CLI。请设置 CODEX_CLI。\n" + detail)


def codex_timeout_seconds(enable_search: bool) -> int:
    variable = "CODEX_RESEARCH_TIMEOUT_SECONDS" if enable_search else "CODEX_TIMEOUT_SECONDS"
    default = DEFAULT_RESEARCH_TIMEOUT_SECONDS if enable_search else DEFAULT_WRITING_TIMEOUT_SECONDS
    try:
        return max(60, int(os.environ.get(variable, default)))
    except ValueError:
        return default


def write_codex_log(
    run_dir: Path,
    task: str,
    outcome: str,
    stdout: str,
    stderr: str,
) -> Path:
    log_path = run_dir / "prompts" / f"{task}.codex.log"
    log_path.write_text(
        "\n".join(
            (
                f"timestamp={utc_now()}",
                f"outcome={outcome}",
                "",
                "[stdout]",
                stdout.strip(),
                "",
                "[stderr]",
                stderr.strip(),
                "",
            )
        ),
        encoding="utf-8",
    )
    return log_path


def invoke_codex_json(
    project: dict[str, Any],
    task: str,
    prompt: str,
    schema_path: Path,
    process_callback: Any | None = None,
    enable_search: bool = False,
) -> dict[str, Any]:
    cli = resolve_codex_cli()
    run_dir = (WRITING_RUNS_ROOT / project["id"]).resolve()
    recovery = run_dir / "recovery_note.md"
    if recovery.is_file() and recovery.read_text().strip():
        prompt += ("\n\nTroubleshooting context for the current step. Use it to diagnose the failure; "
                   "preserve the supplied scientific evidence and claim boundaries:\n" + recovery.read_text())
    previous_errors = run_dir / "previous_errors.json"
    if previous_errors.is_file():
        prompt += "\n\nPrevious failed step errors, diagnose before retrying:\n" + previous_errors.read_text()
    raw_output = run_dir / "prompts" / f".{task}.last-message.json"
    raw_output.unlink(missing_ok=True)
    command = [
        str(cli),
        "--ask-for-approval",
        "never",
        "--cd",
        str(run_dir),
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--sandbox",
        "read-only",
        "--output-schema",
        str(schema_path.resolve()),
        "--output-last-message",
        str(raw_output),
        "-",
    ]
    if enable_search:
        command.insert(command.index("exec"), "--search")
    ignore_setting = os.environ.get("CODEX_IGNORE_USER_CONFIG", "1")
    if ignore_setting == "1":
        command.insert(command.index("exec") + 1, "--ignore-user-config")
    effort = os.environ.get("CODEX_REASONING_EFFORT")
    if enable_search and not effort:
        effort = os.environ.get("CODEX_RESEARCH_REASONING_EFFORT", "high")
    if effort:
        command[1:1] = ["--config", f'model_reasoning_effort="{effort}"']
    if model := os.environ.get("CODEX_MODEL"):
        command[1:1] = ["--model", model]

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process_callback:
        process_callback(process)
    timeout_seconds = codex_timeout_seconds(enable_search)
    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        process.kill()
        stdout, stderr = process.communicate()
        log_path = write_codex_log(run_dir, task, "timeout", stdout, stderr)
        minutes = timeout_seconds // 60
        task_label = "调研" if enable_search else "生成"
        raise RuntimeError(
            f"Codex {task_label}超过 {minutes} 分钟，任务已停止。运行日志：{log_path}"
        ) from error
    finally:
        if process_callback:
            process_callback(None)
    log_path = write_codex_log(run_dir, task, f"exit-{process.returncode}", stdout, stderr)
    if process.returncode != 0:
        detail = (stderr or stdout or "Unknown Codex error").strip()[-4000:]
        raise RuntimeError(f"Codex agent 任务失败。运行日志：{log_path}\n" + detail)
    if not raw_output.is_file():
        raise RuntimeError("Codex 已结束，但没有返回结构化结果。")
    try:
        response = json.loads(raw_output.read_text(encoding="utf-8"))
    finally:
        raw_output.unlink(missing_ok=True)
    if not isinstance(response, dict):
        raise ValueError("Codex 返回的结构化结果无效。")
    return response


def invoke_codex(
    project: dict[str, Any],
    section: str,
    prompt: str,
    process_callback: Any | None = None,
) -> str:
    response = invoke_codex_json(
        project,
        section,
        prompt,
        OUTPUT_SCHEMA_PATH,
        process_callback=process_callback,
    )
    content = response.get("content")
    try:
        return validate_section_content(section, content)
    except ValueError:
        if section != "abstract":
            raise
        candidate = content if isinstance(content, str) else ""
        refinement_prompt = "\n\n".join(
            (
                "You are revising an Abstract candidate that failed a hard output check. Return only the content field required by the supplied JSON schema.",
                "Follow the original task and preserve only claims already present in the candidate or its source instructions. Do not add citations, claims, components, datasets, metrics, or results.",
                "Rewrite the prose to 200 to 230 English words in six to eight complete sentences. Count the prose words after revising and before returning. The LaTeX begin and end lines are not part of the word count. Keep exactly one paragraph between the literal lines \\begin{abstract} and \\end{abstract}.",
                "The previous candidate failed at least one required structure, length, language, citation, or sentence-count check.",
                "ORIGINAL_TASK=\n" + prompt,
                "PREVIOUS_CANDIDATE_JSON=\n" + json.dumps(candidate, ensure_ascii=False),
            )
        )
        run_dir = WRITING_RUNS_ROOT / project["id"]
        (run_dir / "prompts" / "abstract_refinement.resolved.txt").write_text(
            refinement_prompt.rstrip() + "\n",
            encoding="utf-8",
        )
        refined = invoke_codex_json(
            project,
            "abstract_refinement",
            refinement_prompt,
            OUTPUT_SCHEMA_PATH,
            process_callback=process_callback,
        ).get("content")
        try:
            return validate_section_content(section, refined)
        except ValueError as second_error:
            raise ValueError(f"{second_error} 已自动重写一次但仍未通过校验。") from second_error


def validate_section_content(section: str, value: Any) -> str:
    content = value
    if not isinstance(content, str) or len(content.strip()) < 80:
        raise ValueError("Codex 返回的论文内容为空或过短。")
    content = content.replace("\r\n", "\n").strip()
    if re.search(r"[\u3400-\u9fff]", content):
        raise ValueError("Codex 返回了中文内容；论文输出必须为英文。")
    if section == "abstract":
        if not content.startswith("\\begin{abstract}") or not content.endswith(
            "\\end{abstract}"
        ):
            raise ValueError("Abstract 必须使用完整的 LaTeX abstract 环境。")
        if re.search(r"\\cite[A-Za-z]*\s*(?:\[[^\]]*\]\s*)*\{", content):
            raise ValueError("Abstract 不应包含参考文献引用。")
        prose = re.sub(r"\\(?:begin|end)\{abstract\}", "", content).strip()
        words = re.findall(r"\b[A-Za-z0-9][A-Za-z0-9'/-]*\b", prose)
        if not 180 <= len(words) <= 250:
            raise ValueError(
                f"Abstract 必须包含 180 到 250 个英文单词，当前为 {len(words)} 个。"
            )
        sentences = [item for item in re.split(r"(?<=[.!?])\s+", prose) if item.strip()]
        if not 6 <= len(sentences) <= 9:
            raise ValueError(
                f"Abstract 必须由 6 到 9 个完整句子组成，当前为 {len(sentences)} 个。"
            )
    return content


def citation_keys_in_text(content: str) -> set[str]:
    keys: set[str] = set()
    pattern = re.compile(r"\\cite[A-Za-z]*\s*(?:\[[^\]]*\]\s*)*\{([^{}]+)\}")
    for match in pattern.finditer(content):
        keys.update(item.strip() for item in match.group(1).split(",") if item.strip())
    return keys


def latex_paragraphs(content: str) -> list[str]:
    body = re.sub(r"^\s*\\section\*?\{[^{}]+\}\s*", "", content, count=1)
    return [item.strip() for item in re.split(r"\n\s*\n", body) if item.strip()]


def validate_latex_document(value: Any) -> str:
    content = value.strip() if isinstance(value, str) else ""
    required_tokens = ("\\documentclass", "\\begin{document}", "\\end{document}")
    if len(content) < 200 or any(token not in content for token in required_tokens):
        raise ValueError("Codex 返回的 LaTeX 主文档不完整。")
    if "\\begin{abstract}" not in content or "\\end{abstract}" not in content:
        raise ValueError("适配后的 LaTeX 文档缺少 Abstract 环境。")
    headings = re.findall(r"\\section\*?\s*\{([^{}]+)\}", content)
    expected = {SECTION_LABELS[item].lower() for item in BASE_SECTION_ORDER}
    if len(headings) != len(BASE_SECTION_ORDER) or {item.strip().lower() for item in headings} != expected:
        raise ValueError("适配后的 LaTeX 文档必须恰好包含五个标准论文部分。")
    bibliography_commands = (
        r"\\bibliography\s*\{[^{}]*references[^{}]*\}",
        r"\\addbibresource\s*\{[^{}]*references\.bib\}",
        r"\\begin\s*\{thebibliography\}",
    )
    if not any(re.search(pattern, content, re.IGNORECASE) for pattern in bibliography_commands):
        raise ValueError("适配后的 LaTeX 文档没有加载最终参考文献。")
    return content.replace("\r\n", "\n").strip() + "\n"


def latex_compiler() -> tuple[str, Path] | None:
    configured = os.environ.get("LATEX_COMPILER", "").strip()
    names = (configured,) if configured else LATEX_COMPILER_NAMES
    for name in names:
        if not name:
            continue
        candidate = Path(name)
        local_candidates = [candidate]
        if Path(name).stem.lower() == "tectonic":
            codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
            local_candidates.extend(
                [
                    AUTO_WRITING_ROOT / "tools" / "tectonic" / "tectonic.exe",
                    codex_home
                    / ".tmp"
                    / "bundled-marketplaces"
                    / "openai-bundled"
                    / "plugins"
                    / "latex"
                    / "bin"
                    / "tectonic.exe",
                ]
            )
        resolved = next((item for item in local_candidates if item.is_file()), None)
        if resolved is None:
            discovered = shutil.which(name)
            if discovered:
                resolved = Path(discovered)
        if resolved is not None:
            return resolved.stem.lower(), resolved.resolve()
    return None


def latex_timeout_seconds() -> int:
    try:
        return max(30, int(os.environ.get("LATEX_TIMEOUT_SECONDS", "300")))
    except ValueError:
        return 300


def compile_latex(
    main_tex: Path,
    build_dir: Path,
    log_path: Path,
    process_callback: Any | None = None,
) -> tuple[str, Path]:
    compiler = latex_compiler()
    if compiler is None:
        raise RuntimeError(
            "未找到 LaTeX 编译器。请安装 latexmk、Tectonic、XeLaTeX 或 pdfLaTeX，"
            "也可以通过 LATEX_COMPILER 指定可执行文件。"
        )
    compiler_name, executable = compiler
    build_dir.mkdir(parents=True, exist_ok=True)
    if compiler_name == "latexmk":
        commands = [[
            str(executable),
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"-outdir={build_dir}",
            main_tex.name,
        ]]
    elif compiler_name == "tectonic":
        commands = [[
            str(executable),
            "--keep-logs",
            "--outdir",
            str(build_dir),
            main_tex.name,
        ]]
    else:
        command = [
            str(executable),
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"-output-directory={build_dir}",
            main_tex.name,
        ]
        commands = [command, command]

    chunks: list[str] = []
    for pass_index, command in enumerate(commands, start=1):
        chunks.append(f"[pass {pass_index}] {' '.join(command)}")
        process = subprocess.Popen(
            command,
            cwd=main_tex.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if process_callback:
            process_callback(process)
        try:
            stdout, _ = process.communicate(timeout=latex_timeout_seconds())
        except subprocess.TimeoutExpired as error:
            process.kill()
            stdout, _ = process.communicate()
            chunks.append(stdout)
            log_path.write_text("\n".join(chunks), encoding="utf-8")
            raise RuntimeError(f"LaTeX 编译超时。编译日志：{log_path}") from error
        finally:
            if process_callback:
                process_callback(None)
        chunks.append(stdout)
        if process.returncode != 0:
            log_path.write_text("\n".join(chunks), encoding="utf-8")
            raise RuntimeError(
                f"LaTeX 编译失败（{compiler_name}，退出码 {process.returncode}）。"
                f"编译日志：{log_path}"
            )
    log_path.write_text("\n".join(chunks), encoding="utf-8")
    expected = build_dir / f"{main_tex.stem}.pdf"
    if not expected.is_file():
        matches = sorted(build_dir.glob("*.pdf"), key=lambda item: item.stat().st_mtime)
        if not matches:
            raise RuntimeError(f"编译器已结束，但没有生成 PDF。编译日志：{log_path}")
        expected = matches[-1]
    return compiler_name, expected


def create_latex_zip(source_root: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source_root.rglob("*")):
                if path.is_file() and not path.name.startswith("."):
                    archive.write(path, path.relative_to(source_root).as_posix())
        for attempt in range(5):
            try:
                os.replace(temporary, destination)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def validate_research_result(
    project: dict[str, Any], action: str, result: dict[str, Any]
) -> None:
    serialized = json.dumps(result, ensure_ascii=False)
    if re.search(r"[\u3400-\u9fff]", serialized):
        raise ValueError("Codex 返回了中文调研内容；调研产物必须为英文。")
    placeholder_pattern = re.compile(
        r"^(?:undetermined|unknown|pending|not identified|inaccessible|unavailable)(?:\b|:)",
        re.IGNORECASE,
    )

    def require_substantive(value: Any, field: str) -> str:
        text = value.strip() if isinstance(value, str) else ""
        if not text or placeholder_pattern.search(text):
            raise ValueError(f"调研结果的 {field} 包含占位内容，未通过真实性校验。")
        return text

    def require_web_url(value: Any, field: str) -> None:
        url = value.strip() if isinstance(value, str) else ""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"调研结果的 {field} 缺少可核验的网页来源。")

    def validate_papers(papers: Any, field: str, minimum: int, maximum: int) -> None:
        if not isinstance(papers, list) or not minimum <= len(papers) <= maximum:
            raise ValueError(f"调研结果的 {field} 论文数量不符合要求。")
        for index, paper in enumerate(papers, start=1):
            if not isinstance(paper, dict):
                raise ValueError(f"调研结果的 {field}[{index}] 结构无效。")
            for key in (
                "title",
                "lead_author",
                "authors",
                "venue",
                "mechanism",
                "development_role",
            ):
                require_substantive(paper.get(key), f"{field}[{index}].{key}")
            require_web_url(paper.get("source_url"), f"{field}[{index}].source_url")
            validate_bibtex_entry(
                paper.get("citation_key"), paper.get("bibtex"), f"{field}[{index}]"
            )

    if action == "intro_research":
        require_substantive(result.get("research_direction"), "research_direction")
        evidence = result.get("paragraph_1_evidence")
        if not isinstance(evidence, list) or not 3 <= len(evidence) <= 5:
            raise ValueError("Introduction 调研必须包含 3 到 5 条第一段证据。")
        for index, item in enumerate(evidence, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"paragraph_1_evidence[{index}] 结构无效。")
            for key in ("claim", "evidence", "source_title", "authors", "venue"):
                require_substantive(item.get(key), f"paragraph_1_evidence[{index}].{key}")
            require_web_url(
                item.get("source_url"), f"paragraph_1_evidence[{index}].source_url"
            )
            validate_bibtex_entry(
                item.get("citation_key"),
                item.get("bibtex"),
                f"paragraph_1_evidence[{index}]",
            )
        validate_papers(result.get("paragraph_2_papers"), "paragraph_2_papers", 4, 6)
    if action == "related_work_plan":
        subsections = result.get("subsections")
        if not isinstance(subsections, list) or len(subsections) != 3:
            raise ValueError("Related Work 章节规划必须恰好包含三个 subsection。")
        titles = [item.get("title", "").strip() for item in subsections if isinstance(item, dict)]
        if len(titles) != 3 or any(not title for title in titles) or len(set(titles)) != 3:
            raise ValueError("Related Work 的三个 subsection 名称必须完整且互不重复。")
    if action == "related_work_research":
        plan = research_content(WRITING_RUNS_ROOT / project["id"], "related_work_plan")
        planned = [item["title"] for item in (plan or {}).get("subsections", [])]
        researched = [
            item.get("title")
            for item in result.get("subsections", [])
            if isinstance(item, dict)
        ]
        if len(planned) != 3 or researched != planned:
            raise ValueError("Related Work 调研必须保持已规划的三个 subsection 名称和顺序。")
        for index, subsection in enumerate(result.get("subsections", []), start=1):
            require_substantive(subsection.get("thesis"), f"subsections[{index}].thesis")
            validate_papers(subsection.get("papers"), f"subsections[{index}].papers", 3, 5)
            require_substantive(subsection.get("synthesis"), f"subsections[{index}].synthesis")
            require_substantive(
                subsection.get("unresolved_gap"), f"subsections[{index}].unresolved_gap"
            )
    if action == "reference_insertion":
        references = result.get("references")
        if not isinstance(references, list) or not 20 <= len(references) <= 25:
            raise ValueError("最终参考文献必须包含 20 到 25 条记录。")
        keys: list[str] = []
        identities: set[str] = set()
        dois: set[str] = set()
        allowed_scopes = {
            "intro_p1",
            "intro_p2",
            "related_work",
            "experiments_datasets",
            "experiments_backbones",
            "experiments_baselines",
        }
        for index, reference in enumerate(references, start=1):
            if not isinstance(reference, dict):
                raise ValueError(f"references[{index}] 结构无效。")
            for key in ("title", "authors", "venue"):
                require_substantive(reference.get(key), f"references[{index}].{key}")
            require_web_url(reference.get("source_url"), f"references[{index}].source_url")
            citation_key, _ = validate_bibtex_entry(
                reference.get("citation_key"),
                reference.get("bibtex"),
                f"references[{index}]",
            )
            keys.append(citation_key)
            identity = reference_identity(reference)
            if identity in identities:
                raise ValueError("最终参考文献包含重复的标题。")
            identities.add(identity)
            doi = str(reference.get("doi", "")).strip().lower()
            doi = doi.removeprefix("https://doi.org/").removeprefix("doi:")
            if doi and doi in dois:
                raise ValueError("最终参考文献包含重复的 DOI。")
            if doi:
                dois.add(doi)
            scopes = reference.get("used_in")
            if (
                not isinstance(scopes, list)
                or not scopes
                or any(scope not in allowed_scopes for scope in scopes)
            ):
                raise ValueError(f"references[{index}].used_in 覆盖范围无效。")
        if len(keys) != len(set(keys)):
            raise ValueError("最终参考文献的 citation_key 必须互不重复。")

        bibliography = result.get("bibtex")
        if not isinstance(bibliography, str) or any(
            not bibtex_key_pattern(key).search(bibliography) for key in keys
        ):
            raise ValueError("顶层 bibtex 字段没有完整包含全部参考文献。")
        updated = result.get("updated_sections")
        if not isinstance(updated, dict):
            raise ValueError("参考文献任务缺少更新后的章节。")
        for section in ("intro", "related_work", "experiments"):
            content = updated.get(section)
            if not isinstance(content, str) or len(content.strip()) < 80:
                raise ValueError(f"updated_sections.{section} 内容为空或过短。")
            expected_heading = rf"\section{{{SECTION_LABELS[section]}}}"
            if not content.strip().startswith(expected_heading):
                raise ValueError(f"updated_sections.{section} 缺少标准 LaTeX 章节标题。")

        intro_paragraphs = latex_paragraphs(updated["intro"])
        if len(intro_paragraphs) < 2:
            raise ValueError("Introduction 至少需要两个可验证引用覆盖的段落。")
        intro_p1_keys = citation_keys_in_text(intro_paragraphs[0])
        intro_p2_keys = citation_keys_in_text(intro_paragraphs[1])
        if not intro_p1_keys or not intro_p2_keys:
            raise ValueError("Introduction 第一、二段必须分别包含 LaTeX 引用。")
        related_parts = re.split(r"\\subsection\*?\{[^{}]+\}", updated["related_work"])[1:]
        if not related_parts or any(not citation_keys_in_text(item) for item in related_parts):
            raise ValueError("Related Work 的每个 subsection 都必须包含引用。")

        coverage = result.get("coverage")
        if not isinstance(coverage, dict):
            raise ValueError("参考文献任务缺少引用覆盖清单。")
        simple_coverage = {
            "intro_p1": intro_p1_keys,
            "intro_p2": intro_p2_keys,
            "related_work": citation_keys_in_text(updated["related_work"]),
        }
        key_set = set(keys)
        for scope, actual_keys in simple_coverage.items():
            declared = coverage.get(scope)
            if not isinstance(declared, list) or not declared or not set(declared) <= actual_keys:
                raise ValueError(f"coverage.{scope} 与章节中的实际引用不一致。")
        experiment_keys = citation_keys_in_text(updated["experiments"])
        for scope in (
            "experiments_datasets",
            "experiments_backbones",
            "experiments_baselines",
        ):
            targets = coverage.get(scope)
            if not isinstance(targets, list) or not targets:
                raise ValueError(f"coverage.{scope} 必须列出至少一个已引用目标。")
            for target in targets:
                target_keys = target.get("citation_keys") if isinstance(target, dict) else None
                if (
                    not isinstance(target_keys, list)
                    or not target_keys
                    or not set(target_keys) <= experiment_keys
                ):
                    raise ValueError(f"coverage.{scope} 与 Experiments 中的实际引用不一致。")
        cited_keys = (
            citation_keys_in_text(updated["intro"])
            | citation_keys_in_text(updated["related_work"])
            | experiment_keys
        )
        if cited_keys != key_set:
            missing = sorted(key_set - cited_keys)
            unknown = sorted(cited_keys - key_set)
            raise ValueError(
                "引用键与参考文献列表不一致。"
                f"未引用：{', '.join(missing) or '无'}；未知：{', '.join(unknown) or '无'}。"
            )


class GenerationJob:
    def __init__(self, project_id: str, section: str, previous_status: str):
        self.id = uuid.uuid4().hex[:12]
        self.project_id = project_id
        self.section = section
        self.previous_status = previous_status
        self.created_at = utc_now()
        self.process: subprocess.Popen[str] | None = None
        self.cancelled = threading.Event()

    def set_process(self, process: subprocess.Popen[str] | None) -> None:
        self.process = process
        if process is not None and self.cancelled.is_set() and process.poll() is None:
            process.terminate()

    def cancel(self) -> None:
        self.cancelled.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()


class ResearchJob(GenerationJob):
    def __init__(self, project_id: str, action: str, previous_status: str):
        super().__init__(project_id, action, previous_status)
        self.action = action


class PublicationJob(GenerationJob):
    def __init__(
        self,
        project_id: str,
        previous_status: str,
        main_tex_relative: str,
    ):
        super().__init__(project_id, "latex_publication", previous_status)
        self.main_tex_relative = main_tex_relative


def mark_section_stale(
    project: dict[str, Any], run_dir: Path, section: str, reason: str
) -> None:
    if section_content(run_dir, section):
        project["sections"][section].update({"status": "stale", "error": reason})


def mark_research_stale(
    project: dict[str, Any], run_dir: Path, action: str, reason: str
) -> None:
    if research_content(run_dir, action):
        project["research"][action].update({"status": "stale", "error": reason})


def mark_reference_stale(project: dict[str, Any], reason: str) -> None:
    run_dir = WRITING_RUNS_ROOT / project["id"]
    record = project["research"]["reference_insertion"]
    content = research_content(run_dir, "reference_insertion") or {}
    if content.get("references") or record.get("status") not in {None, "empty"}:
        record.update({"status": "stale", "error": reason, "job_id": None})


def mark_publication_stale(project: dict[str, Any], reason: str) -> None:
    record = project["publication"]
    run_dir = WRITING_RUNS_ROOT / project["id"]
    has_output = (publication_dir(run_dir) / "manuscript-latex.zip").is_file()
    if has_output or record.get("status") not in {None, "empty"}:
        record.update({"status": "stale", "error": reason, "job_id": None})


def invalidate_after_section(project: dict[str, Any], section: str) -> None:
    run_dir = WRITING_RUNS_ROOT / project["id"]
    for dependent in DEPENDENTS[section]:
        mark_section_stale(
            project,
            run_dir,
            dependent,
            f"{SECTION_LABELS[section]} 已更新，请重新生成。",
        )
    if section == "intro":
        for action in ("related_work_plan", "related_work_research"):
            mark_research_stale(
                project,
                run_dir,
                action,
                "Introduction 已更新，请重新完成 Related Work 的规划与调研。",
            )
    if section in {"intro", "related_work", "experiments"}:
        mark_reference_stale(
            project,
            f"{SECTION_LABELS[section]} 已更新，请重新完成参考文献调研与插入。",
        )
    mark_publication_stale(project, f"{SECTION_LABELS[section]} 已更新，请重新排版发布。")


def invalidate_after_research(project: dict[str, Any], action: str) -> None:
    run_dir = WRITING_RUNS_ROOT / project["id"]
    if action == "intro_research":
        for section in ("intro",) + DEPENDENTS["intro"]:
            mark_section_stale(
                project,
                run_dir,
                section,
                "Introduction 论文调研已更新，请重新生成相关内容。",
            )
    elif action == "related_work_plan":
        mark_research_stale(
            project,
            run_dir,
            "related_work_research",
            "Related Work 章节规划已更新，请重新调研。",
        )
        mark_section_stale(
            project,
            run_dir,
            "related_work",
            "Related Work 章节规划已更新，请重新调研并生成。",
        )
    elif action == "related_work_research":
        mark_section_stale(
            project,
            run_dir,
            "related_work",
            "Related Work 论文调研已更新，请重新生成。",
        )
    if action in {"intro_research", "related_work_research"}:
        mark_reference_stale(
            project,
            "已有文献调研已更新，请重新检查并插入全文参考文献。",
        )
    mark_publication_stale(project, "论文调研或章节规划已更新，请重新生成相关章节后再次排版发布。")


class GenerationManager:
    def __init__(self) -> None:
        self.jobs: dict[str, GenerationJob] = {}
        self.lock = threading.RLock()
        self.project_locks: dict[str, threading.Lock] = {}
        self.automation_threads: dict[str, threading.Thread] = {}

    def automation_state(self, project_id: str) -> dict:
        path = safe_project_dir(project_id) / "automation.json"
        with self.lock:
            state = json.loads(path.read_text()) if path.is_file() else {"status": "idle"}
            if state["status"] == "running" and project_id not in self.automation_threads:
                state.update(status="paused", message="服务重启后已暂停，可从当前步骤继续。")
                write_json_atomic(path, state)
            return state

    def set_automation(self, project_id: str, status: str, message: str) -> dict:
        state = {"status": status, "message": message, "updated_at": utc_now()}
        with self.lock:
            write_json_atomic(safe_project_dir(project_id) / "automation.json", state)
        return state

    def start_auto(self, project_id: str, template_file: dict | None = None) -> dict:
        with self.lock:
            project = load_project(project_id)
            if project_id in self.automation_threads:
                raise ValueError("自动写作尚未停止，请稍后继续。")
            if self.has_project_job(project_id):
                raise ValueError("请等待当前步骤结束后再启动自动写作。")
            failures = [r.get("error") for r in [*project["sections"].values(),
                                                *project["research"].values(), project["publication"]]
                        if r.get("status") in {"failed", "partial"} and r.get("error")]
            if failures:
                (safe_project_dir(project_id) / "previous_errors.json").write_text(
                    json.dumps(failures, ensure_ascii=False), encoding="utf-8")
            if template_file is not None:
                _, data = decode_zip_file(template_file)
                if not zipfile.is_zipfile(io.BytesIO(data)):
                    raise ValueError("LaTeX 模板不是有效的 ZIP。")
                write_bytes_atomic(safe_project_dir(project_id) / "input/latex-template.zip", data)
            thread = threading.Thread(target=self._run_auto, args=(project["id"],), daemon=True)
            self.automation_threads[project_id] = thread
            state = self.set_automation(project_id, "running", "自动推进调研、六章节、引用与 PDF；失败时保留当前步骤。")
            thread.start()
            return state

    def pause_auto(self, project_id: str) -> dict:
        return self.set_automation(project_id, "paused", "已暂停自动推进，当前步骤可完成或手动停止。")

    def _run_auto(self, project_id: str) -> None:
        if __package__:
            from .automation import next_step, template_payload
        else:
            from automation import next_step, template_payload

        retry_current = True
        try:
            while True:
                with self.lock:
                    if self.automation_state(project_id)["status"] != "running":
                        return
                    if not self.has_project_job(project_id):
                        project = load_project(project_id)
                        step = next_step(project)
                        if step is None:
                            self.set_automation(project_id, "completed", "论文、参考文献、LaTeX 与 PDF 已生成。")
                            return
                        kind, key, record = step
                        if record.get("status") in {"failed", "partial"} and not retry_current:
                            self.set_automation(project_id, "blocked", record.get("error") or "当前步骤失败，请查看日志并重试。")
                            return
                        retry_current = False
                        if kind == "section":
                            self.start(project_id, key)
                        elif kind == "research":
                            self.start_research(project_id, key)
                        elif record.get("status") == "partial":
                            self.start_recompile(project_id)
                        else:
                            self.start_publication(project_id, template_payload(safe_project_dir(project_id)))
                threading.Event().wait(0.5)
        except Exception as error:
            self.set_automation(project_id, "blocked", str(error))
        finally:
            with self.lock:
                self.automation_threads.pop(project_id, None)

    def start_recompile(self, project_id: str) -> GenerationJob:
        with self.lock:
            project = load_project(project_id)
            if project_has_running_task(project):
                raise ValueError("请等待当前步骤结束。")
            if project["publication"]["status"] not in {"partial", "ready"}:
                raise ValueError("需要先生成当前版本的 LaTeX 源码。")
            job = GenerationJob(project_id, "publication", project["publication"]["status"])
            self.jobs[job.id] = job
            project["publication"].update(status="running", job_id=job.id, error=None)
            save_project(project)
            threading.Thread(target=self._run_recompile, args=(job,), daemon=True).start()
            return job

    def _run_recompile(self, job: GenerationJob) -> None:
        try:
            project = load_project(job.project_id)
            directory = publication_dir(safe_project_dir(job.project_id))
            main = directory / "source" / project["publication"]["template"]["main_tex"]
            compiler, pdf = compile_latex(main, directory / "build", directory / "compile.log",
                                          process_callback=job.set_process)
            if job.cancelled.is_set():
                raise RuntimeError("编译已停止，可再次编译。")
            latex_zip = directory / "manuscript-latex.zip"
            create_latex_zip(directory / "source", latex_zip)
            write_bytes_atomic(directory / "manuscript.pdf", pdf.read_bytes())
            project = load_project(job.project_id)
            project["publication"]["latex_zip"] = {"name": latex_zip.name, "size": latex_zip.stat().st_size}
            project["publication"].update(status="ready", error=None, job_id=None, compiler=compiler,
                                           pdf={"name": "manuscript.pdf", "size": pdf.stat().st_size})
            save_project(project)
        except Exception as error:
            project = load_project(job.project_id)
            project["publication"].update(status="partial", error=str(error), job_id=None)
            save_project(project)
        finally:
            with self.lock:
                self.jobs.pop(job.id, None)

    def start(self, project_id: str, section: str) -> GenerationJob:
        with self.lock:
            project = load_project(project_id)
            if project_has_running_task(project):
                raise ValueError("当前写作已有一个任务正在运行，请等待完成后再继续。")
            missing = unmet_section_requirements(project, section)
            if missing:
                raise GenerationPreconditionError(missing)
            previous_status = str(project["sections"][section].get("status", "empty"))
            job = GenerationJob(project_id, section, previous_status)
            self.jobs[job.id] = job
            project["sections"][section].update(
                {"status": "running", "error": None, "job_id": job.id}
            )
            save_project(project)
            thread = threading.Thread(
                target=self._run,
                args=(job,),
                daemon=True,
                name=f"auto-writing-{job.id}",
            )
            thread.start()
            return job

    def start_research(self, project_id: str, action: str) -> ResearchJob:
        if action not in RESEARCH_ACTIONS:
            raise ValueError("调研步骤不存在。")
        with self.lock:
            project = load_project(project_id)
            if project_has_running_task(project):
                raise ValueError("当前写作已有一个任务正在运行，请等待完成后再继续。")
            missing = unmet_action_requirements(project, action)
            if missing:
                raise GenerationPreconditionError(missing)
            previous_status = str(project["research"][action].get("status", "empty"))
            job = ResearchJob(project_id, action, previous_status)
            self.jobs[job.id] = job
            project["research"][action].update(
                {"status": "running", "error": None, "job_id": job.id}
            )
            save_project(project)
            thread = threading.Thread(
                target=self._run_research,
                args=(job,),
                daemon=True,
                name=f"auto-writing-research-{job.id}",
            )
            thread.start()
            return job

    def start_publication(
        self, project_id: str, template_file: dict[str, Any]
    ) -> PublicationJob:
        with self.lock:
            project = load_project(project_id)
            if project_has_running_task(project):
                raise ValueError("当前写作已有一个任务正在运行，请等待完成后再继续。")
            missing = publication_missing_requirements(project)
            if missing:
                raise GenerationPreconditionError(missing)
            template_name, template_data = decode_zip_file(template_file)
            run_dir = WRITING_RUNS_ROOT / project_id
            final_dir = publication_dir(run_dir)
            staging = run_dir / f".publication-{uuid.uuid4().hex}"
            try:
                source_root = staging / "source"
                source_root.mkdir(parents=True)
                write_bytes_atomic(staging / "template.zip", template_data)
                paths = extract_latex_template(template_data, source_root)
                staged_main = detect_latex_main(paths, source_root)
                main_relative = staged_main.relative_to(source_root).as_posix()
                if final_dir.exists():
                    shutil.rmtree(final_dir)
                os.replace(staging, final_dir)
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)

            previous_status = str(project["publication"].get("status", "empty"))
            job = PublicationJob(project_id, previous_status, main_relative)
            self.jobs[job.id] = job
            project["publication"] = {
                **empty_task_record(),
                "status": "running",
                "job_id": job.id,
                "template": {
                    "name": template_name,
                    "size": len(template_data),
                    "main_tex": main_relative,
                },
                "compiler": None,
                "latex_zip": None,
                "pdf": None,
                "compile_log": str((final_dir / "compile.log").resolve()),
            }
            save_project(project)
            refresh_path_contract(project)
            thread = threading.Thread(
                target=self._run_publication,
                args=(job,),
                daemon=True,
                name=f"auto-writing-publication-{job.id}",
            )
            thread.start()
            return job

    def _run(self, job: GenerationJob) -> None:
        lock = self.project_locks.setdefault(job.project_id, threading.Lock())
        with lock:
            try:
                project = load_project(job.project_id)
                prompt = build_resolved_prompt(project, job.section)
                content = invoke_codex(
                    project,
                    job.section,
                    prompt,
                    process_callback=job.set_process,
                )
                if job.cancelled.is_set():
                    raise RuntimeError("生成已取消。")
                run_dir = WRITING_RUNS_ROOT / job.project_id
                write_json_atomic(
                    section_output_path(run_dir, job.section),
                    {job.section: content},
                )
                project = load_project(job.project_id)
                project["sections"][job.section].update(
                    {
                        "status": "ready",
                        "generated_at": utc_now(),
                        "error": None,
                        "job_id": None,
                    }
                )
                invalidate_after_section(project, job.section)
                save_project(project)
            except Exception as error:
                try:
                    project = load_project(job.project_id)
                    record = project["sections"][job.section]
                    if job.cancelled.is_set():
                        restored = job.previous_status
                        if restored == "running":
                            restored = "ready" if section_content(
                                WRITING_RUNS_ROOT / job.project_id, job.section
                            ) else "empty"
                        record.update(
                            {"status": restored, "error": None, "job_id": None}
                        )
                    else:
                        record.update(
                            {
                                "status": "failed",
                                "error": str(error).strip()[-4000:],
                                "job_id": None,
                            }
                        )
                    save_project(project)
                except Exception:
                    pass
            finally:
                with self.lock:
                    self.jobs.pop(job.id, None)

    def _run_research(self, job: ResearchJob) -> None:
        lock = self.project_locks.setdefault(job.project_id, threading.Lock())
        with lock:
            try:
                project = load_project(job.project_id)
                prompt = build_research_prompt(project, job.action)
                result = invoke_codex_json(
                    project,
                    job.action,
                    prompt,
                    RESEARCH_SCHEMA_PATHS[job.action],
                    process_callback=job.set_process,
                    enable_search=True,
                )
                validate_research_result(project, job.action, result)
                if job.cancelled.is_set():
                    raise RuntimeError("调研已取消。")
                run_dir = WRITING_RUNS_ROOT / job.project_id
                if job.action == "reference_insertion":
                    stored_result = {**result, "phase": "inserted"}
                    write_json_atomic(reference_output_path(run_dir), stored_result)
                    reference_bib_path(run_dir).write_text(
                        str(result["bibtex"]).rstrip() + "\n", encoding="utf-8"
                    )
                    timestamp = utc_now()
                    for section, content in result["updated_sections"].items():
                        write_json_atomic(section_output_path(run_dir, section), {section: content})
                else:
                    write_json_atomic(research_output_path(run_dir, job.action), result)
                project = load_project(job.project_id)
                project["research"][job.action].update(
                    {
                        "status": "ready",
                        "generated_at": utc_now(),
                        "error": None,
                        "job_id": None,
                    }
                )
                if job.action == "reference_insertion":
                    for section in ("intro", "related_work", "experiments"):
                        project["sections"][section].update(
                            {
                                "status": "ready",
                                "generated_at": timestamp,
                                "error": None,
                                "job_id": None,
                            }
                        )
                invalidate_after_research(project, job.action)
                merge_research_references(project, job.action, result)
                save_project(project)
            except Exception as error:
                try:
                    project = load_project(job.project_id)
                    record = project["research"][job.action]
                    if job.cancelled.is_set():
                        restored = job.previous_status
                        if restored == "running":
                            restored = "ready" if research_content(
                                WRITING_RUNS_ROOT / job.project_id, job.action
                            ) else "empty"
                        record.update(
                            {"status": restored, "error": None, "job_id": None}
                        )
                    else:
                        record.update(
                            {
                                "status": "failed",
                                "error": str(error).strip()[-4000:],
                                "job_id": None,
                            }
                        )
                    save_project(project)
                except Exception:
                    pass
            finally:
                with self.lock:
                    self.jobs.pop(job.id, None)

    def _run_publication(self, job: PublicationJob) -> None:
        lock = self.project_locks.setdefault(job.project_id, threading.Lock())
        with lock:
            try:
                project = load_project(job.project_id)
                run_dir = WRITING_RUNS_ROOT / job.project_id
                output_dir = publication_dir(run_dir)
                source_root = output_dir / "source"
                main_tex = source_root.joinpath(*PurePosixPath(job.main_tex_relative).parts)
                write_bytes_atomic(
                    main_tex.parent / "references.bib",
                    reference_bib_path(run_dir).read_bytes(),
                )
                prompt = build_latex_prompt(project, main_tex)
                response = invoke_codex_json(
                    project,
                    "latex_publication",
                    prompt,
                    LATEX_OUTPUT_SCHEMA_PATH,
                    process_callback=job.set_process,
                )
                if job.cancelled.is_set():
                    raise RuntimeError("排版任务已取消。")
                content = validate_latex_document(response.get("content"))
                main_tex.write_text(content, encoding="utf-8")

                latex_zip_path = output_dir / "manuscript-latex.zip"
                create_latex_zip(source_root, latex_zip_path)
                project = load_project(job.project_id)
                project["publication"]["latex_zip"] = {
                    "name": latex_zip_path.name,
                    "size": latex_zip_path.stat().st_size,
                }
                save_project(project)

                log_path = output_dir / "compile.log"
                try:
                    compiler_name, compiled_pdf = compile_latex(
                        main_tex,
                        output_dir / "build",
                        log_path,
                        process_callback=job.set_process,
                    )
                    if job.cancelled.is_set():
                        raise RuntimeError("排版任务已取消。")
                    pdf_path = output_dir / "manuscript.pdf"
                    write_bytes_atomic(pdf_path, compiled_pdf.read_bytes())
                except Exception as compile_error:
                    if not log_path.is_file():
                        log_path.write_text(str(compile_error).strip() + "\n", encoding="utf-8")
                    project = load_project(job.project_id)
                    project["publication"].update(
                        {
                            "status": "failed" if job.cancelled.is_set() else "partial",
                            "generated_at": utc_now(),
                            "error": str(compile_error).strip()[-4000:],
                            "job_id": None,
                            "compiler": (latex_compiler() or (None, None))[0],
                            "pdf": None,
                            "compile_log": str(log_path.resolve()),
                        }
                    )
                    save_project(project)
                    return

                project = load_project(job.project_id)
                project["publication"].update(
                    {
                        "status": "ready",
                        "generated_at": utc_now(),
                        "error": None,
                        "job_id": None,
                        "compiler": compiler_name,
                        "pdf": {"name": pdf_path.name, "size": pdf_path.stat().st_size},
                        "compile_log": str(log_path.resolve()),
                    }
                )
                save_project(project)
            except Exception as error:
                try:
                    project = load_project(job.project_id)
                    project["publication"].update(
                        {
                            "status": "failed",
                            "generated_at": None,
                            "error": str(error).strip()[-4000:],
                            "job_id": None,
                        }
                    )
                    save_project(project)
                except Exception:
                    pass
            finally:
                with self.lock:
                    self.jobs.pop(job.id, None)

    def cancel(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            self.pause_auto(job.project_id)
            job.cancel()
            return True

    def has_project_job(self, project_id: str) -> bool:
        with self.lock:
            return any(job.project_id == project_id for job in self.jobs.values())


GENERATION_MANAGER = GenerationManager()


def project_view(project: dict[str, Any], include_content: bool = True) -> dict[str, Any]:
    run_dir = WRITING_RUNS_ROOT / project["id"]
    contract = refresh_path_contract(project)
    sections = []
    for index, section in enumerate(SECTION_ORDER, start=1):
        record = project["sections"][section]
        missing_dependencies = unmet_dependencies(project, section)
        missing = unmet_section_requirements(project, section)
        sections.append(
            {
                "key": section,
                "index": index,
                "label": SECTION_LABELS[section],
                "description": SECTION_DESCRIPTIONS[section],
                "status": record.get("status", "empty"),
                "generated_at": record.get("generated_at"),
                "error": record.get("error"),
                "job_id": record.get("job_id"),
                "dependencies": list(DEPENDENCIES[section]),
                "research_requirements": list(SECTION_ACTION_REQUIREMENTS[section]),
                "missing_dependencies": missing_dependencies,
                "missing_requirements": missing,
                "content": section_content(run_dir, section) if include_content else None,
                "output_path": contract["entries"][PATH_ENTRY_KEYS[section]]["path"],
            }
        )
    actions = []
    for action in RESEARCH_ACTIONS:
        record = project["research"][action]
        actions.append(
            {
                "key": action,
                "label": ACTION_LABELS[action],
                "description": ACTION_DESCRIPTIONS[action],
                "status": record.get("status", "empty"),
                "generated_at": record.get("generated_at"),
                "error": record.get("error"),
                "job_id": record.get("job_id"),
                "dependencies": list(ACTION_DEPENDENCIES[action]),
                "missing_requirements": unmet_action_requirements(project, action),
                "output_path": contract["entries"][RESEARCH_PATH_ENTRY_KEYS[action]]["path"],
                "content": research_content(run_dir, action) if include_content else None,
            }
        )
    reference_action = next(
        item for item in actions if item["key"] == "reference_insertion"
    )
    reference_value = reference_action.get("content") or {}
    reference = {
        **reference_action,
        "reference_count": len(reference_value.get("references", [])),
        "phase": reference_value.get("phase", "empty"),
        "bib_path": str(reference_bib_path(run_dir).resolve()),
    }
    publication = dict(project["publication"])
    latex_zip_path = publication_dir(run_dir) / "manuscript-latex.zip"
    pdf_path = publication_dir(run_dir) / "manuscript.pdf"
    publication_missing = publication_missing_requirements(project)
    publication.update(
        {
            "available": not publication_missing,
            "missing_sections": publication_missing,
            "latex_zip_url": (
                f"/api/writings/{project['id']}/publication/download/latex"
                if latex_zip_path.is_file()
                else None
            ),
            "pdf_url": (
                f"/api/writings/{project['id']}/publication/download/pdf"
                if pdf_path.is_file()
                else None
            ),
            "compiler_available": latex_compiler() is not None,
        }
    )
    return {
        "id": project["id"],
        "title": project["title"],
        "pipeline_id": project.get("pipeline_id"),
        "automation": GENERATION_MANAGER.automation_state(project["id"]),
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
        "experiment": {
            **project["experiment"],
            "path": contract["entries"]["experiment_description"]["path"],
        },
        "support_files": project.get("support_files", []),
        "sections": sections,
        "actions": actions,
        "reference": reference,
        "publication": publication,
        "path_contract": contract,
        "path_contract_path": str((run_dir / "path_contract.json").resolve()),
        "completed": sum(item["status"] == "ready" for item in sections),
        "total": len(SECTION_ORDER),
    }


def list_projects() -> list[dict[str, Any]]:
    WRITING_RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    projects: list[dict[str, Any]] = []
    for path in WRITING_RUNS_ROOT.glob("*"):
        if not path.is_dir() or not PROJECT_ID_RE.fullmatch(path.name):
            continue
        try:
            project = load_project(path.name)
            if not GENERATION_MANAGER.has_project_job(path.name):
                changed = False
                records = (
                    list(project["sections"].values())
                    + list(project["research"].values())
                    + [project["publication"]]
                )
                for record in records:
                    if record.get("status") == "running":
                        record.update(
                            {
                                "status": "failed",
                                "job_id": None,
                                "error": "服务重启后任务已中断，请重新执行当前步骤。",
                            }
                        )
                        changed = True
                if changed:
                    save_project(project)
            projects.append(project_view(project, include_content=False))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(projects, key=lambda item: item["created_at"], reverse=True)


class AppHandler(SimpleHTTPRequestHandler):
    server_version = "AutoWritingWorkspace/1.0"

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_download(self, path: Path, download_name: str) -> None:
        if not path.is_file():
            self.send_error_json("下载文件不存在，请重新执行排版发布。", HTTPStatus.NOT_FOUND)
            return
        content_type = "application/pdf" if path.suffix.lower() == ".pdf" else "application/zip"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as source:
            shutil.copyfileobj(source, self.wfile)

    def send_error_json(self, error: Exception | str, status: int) -> None:
        message = str(error)
        payload: dict[str, Any] = {"error": message}
        if isinstance(error, GenerationPreconditionError):
            payload["missing_dependencies"] = error.missing
            payload["missing_requirements"] = error.missing
        self.send_json(payload, status)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("请求大小无效或超过限制。")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("请求内容必须是 JSON 对象。")
        return value

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        logs_match = re.fullmatch(r"/api/writings/(" + PROJECT_ID_PATTERN + r")/logs", path)
        if logs_match:
            try:
                directory = safe_project_dir(logs_match.group(1))
                files = sorted((directory / "prompts").glob("*.log"))
                if (directory / "publication/compile.log").is_file():
                    files.append(directory / "publication/compile.log")
                self.send_json({"logs": [{"name": str(p.relative_to(directory)),
                                          "text": p.read_text(encoding="utf-8", errors="replace")}
                                         for p in files]})
            except (ValueError, OSError) as error:
                self.send_error_json(error, HTTPStatus.NOT_FOUND)
            return
        if path == "/api/health":
            cli_available = False
            try:
                resolve_codex_cli()
                cli_available = True
            except RuntimeError:
                pass
            compiler = latex_compiler()
            self.send_json(
                {
                    "status": "ok",
                    "codex_cli": cli_available,
                    "latex_compiler": compiler[0] if compiler else None,
                }
            )
            return
        if path == "/api/writings":
            self.send_json({"writings": list_projects()})
            return
        match = re.fullmatch(
            r"/api/writings/(" + PROJECT_ID_PATTERN + r")/publication/download/(latex|pdf)",
            path,
        )
        if match:
            try:
                run_dir = safe_project_dir(match.group(1))
                kind = match.group(2)
                if kind == "latex":
                    self.send_download(
                        publication_dir(run_dir) / "manuscript-latex.zip",
                        "manuscript-latex.zip",
                    )
                else:
                    self.send_download(
                        publication_dir(run_dir) / "manuscript.pdf",
                        "manuscript.pdf",
                    )
            except ValueError as error:
                self.send_error_json(error, HTTPStatus.NOT_FOUND)
            return
        match = re.fullmatch(r"/api/writings/(" + PROJECT_ID_PATTERN + r")", path)
        if match:
            try:
                self.send_json(project_view(load_project(match.group(1))))
            except ValueError as error:
                self.send_error_json(error, HTTPStatus.NOT_FOUND)
            return

        self.path = "/" if path == "" else self.path
        super().do_GET()

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        auto_match = re.fullmatch(r"/api/writings/(" + PROJECT_ID_PATTERN + r")/(auto-start|auto-pause|recompile)", path)
        if auto_match:
            try:
                project_id, action = auto_match.groups()
                payload = self.read_json()
                if action == "auto-start":
                    list_projects()  # Recover records left running by a previous service instance.
                    result = GENERATION_MANAGER.start_auto(project_id, payload.get("template_file"))
                elif action == "auto-pause":
                    result = GENERATION_MANAGER.pause_auto(project_id)
                else:
                    GENERATION_MANAGER.start_recompile(project_id)
                    result = {"status": "running"}
                self.send_json(result, HTTPStatus.ACCEPTED)
            except (ValueError, OSError, TypeError) as error:
                self.send_error_json(error, HTTPStatus.CONFLICT)
            return
        if path == "/api/writings":
            try:
                payload = self.read_json()
                experiment = payload.get("experiment_file")
                supports = payload.get("support_files", [])
                if not isinstance(experiment, dict):
                    raise ValueError("请上传实验说明文件。")
                if not isinstance(supports, list) or not all(
                    isinstance(item, dict) for item in supports
                ):
                    raise ValueError("补充资料格式无效。")
                project = create_project(str(payload.get("title", "")), experiment, supports)
                self.send_json(project_view(project), HTTPStatus.CREATED)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_error_json(error, HTTPStatus.BAD_REQUEST)
            return

        match = re.fullmatch(
            r"/api/writings/(" + PROJECT_ID_PATTERN + r")/sections/([a-z_]+)/generate",
            path,
        )
        if match:
            try:
                section = match.group(2)
                if section not in SECTION_ORDER:
                    raise ValueError("写作部分不存在。")
                job = GENERATION_MANAGER.start(match.group(1), section)
                project = load_project(match.group(1))
                self.send_json(
                    {"job_id": job.id, "project": project_view(project)},
                    HTTPStatus.ACCEPTED,
                )
            except GenerationPreconditionError as error:
                self.send_error_json(error, HTTPStatus.CONFLICT)
            except ValueError as error:
                self.send_error_json(error, HTTPStatus.CONFLICT)
            return

        match = re.fullmatch(
            r"/api/writings/(" + PROJECT_ID_PATTERN + r")/publication/build",
            path,
        )
        if match:
            try:
                payload = self.read_json()
                template_file = payload.get("template_file")
                if not isinstance(template_file, dict):
                    raise ValueError("请上传 LaTeX 模板 ZIP。")
                job = GENERATION_MANAGER.start_publication(match.group(1), template_file)
                project = load_project(match.group(1))
                self.send_json(
                    {"job_id": job.id, "project": project_view(project)},
                    HTTPStatus.ACCEPTED,
                )
            except GenerationPreconditionError as error:
                self.send_error_json(error, HTTPStatus.CONFLICT)
            except (ValueError, TypeError, OSError, json.JSONDecodeError) as error:
                self.send_error_json(error, HTTPStatus.CONFLICT)
            return

        match = re.fullmatch(
            r"/api/writings/(" + PROJECT_ID_PATTERN + r")/actions/([a-z_]+)/run",
            path,
        )
        if match:
            try:
                action = match.group(2)
                if action not in RESEARCH_ACTIONS:
                    raise ValueError("调研步骤不存在。")
                job = GENERATION_MANAGER.start_research(match.group(1), action)
                project = load_project(match.group(1))
                self.send_json(
                    {"job_id": job.id, "project": project_view(project)},
                    HTTPStatus.ACCEPTED,
                )
            except GenerationPreconditionError as error:
                self.send_error_json(error, HTTPStatus.CONFLICT)
            except ValueError as error:
                self.send_error_json(error, HTTPStatus.CONFLICT)
            return

        match = re.fullmatch(r"/api/generation/([a-f0-9]{12})/cancel", path)
        if match:
            if GENERATION_MANAGER.cancel(match.group(1)):
                self.send_json({"cancelled": True})
            else:
                self.send_error_json("生成任务不存在。", HTTPStatus.NOT_FOUND)
            return
        self.send_error_json("Endpoint not found.", HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        match = re.fullmatch(r"/api/writings/(" + PROJECT_ID_PATTERN + r")", path)
        if not match:
            self.send_error_json("Endpoint not found.", HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self.read_json()
            experiment_file = payload.get("experiment_file")
            if experiment_file is not None and not isinstance(experiment_file, dict):
                raise ValueError("实验说明文件格式无效。")
            project = update_project(
                match.group(1),
                str(payload.get("title", "")),
                experiment_file,
                payload.get("retained_support_paths"),
                payload.get("new_support_files"),
            )
            self.send_json(project_view(project))
        except (ValueError, TypeError, OSError, json.JSONDecodeError) as error:
            self.send_error_json(error, HTTPStatus.CONFLICT)

    def do_DELETE(self) -> None:
        path = unquote(urlparse(self.path).path).rstrip("/")
        match = re.fullmatch(r"/api/writings/(" + PROJECT_ID_PATTERN + r")", path)
        if not match:
            self.send_error_json("Endpoint not found.", HTTPStatus.NOT_FOUND)
            return
        project_id = match.group(1)
        try:
            run_dir = safe_project_dir(project_id)
            if GENERATION_MANAGER.has_project_job(project_id):
                raise ValueError("请先停止正在运行的生成任务。")
            shutil.rmtree(run_dir)
            self.send_json({"deleted": True})
        except ValueError as error:
            self.send_error_json(error, HTTPStatus.CONFLICT)

    def log_message(self, format: str, *args: Any) -> None:
        if not self.path.startswith("/api/"):
            super().log_message(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Auto Writing workspace.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    WRITING_RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    migrate_existing_research_references()
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
