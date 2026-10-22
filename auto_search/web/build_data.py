from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = PROJECT_ROOT / "research_runs" / "medical-vlm-10"
DEFAULT_MANIFEST = PROJECT_ROOT / "sources" / "medical_vlm_10_papers.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "data" / "ideas.json"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
CAUSE_TITLE_RE = re.compile(r"^(?:原因|Cause)\s*\((\d+)\)[：:]\s*(.+)$")
CONTRIBUTION_RE = re.compile(
    r"\\noindent\s+\\textbf\{\((\d+)\)\}\s*(.*?)(?=\n\s*\\noindent\s+\\textbf\{\(\d+\)\}|\Z)",
    re.DOTALL,
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def split_headings(markdown: str) -> list[dict[str, Any]]:
    matches = list(HEADING_RE.finditer(markdown))
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        level = len(match.group(1))
        body_end = len(markdown)
        for following in matches[index + 1 :]:
            if len(following.group(1)) <= level:
                body_end = following.start()
                break
        sections.append(
            {
                "level": level,
                "title": match.group(2).strip(),
                "body": markdown[body_start:body_end].strip(),
            }
        )
    return sections


def clean_inline_latex(text: str) -> str:
    cleaned = text.replace("\\noindent", "").strip()
    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", cleaned)
    return cleaned


def clean_heading(text: str) -> str:
    return clean_inline_latex(text).replace("**", "").strip()


def section_by_title(sections: list[dict[str, Any]], title: str, level: int = 2) -> dict[str, Any]:
    for section in sections:
        if section["level"] == level and clean_heading(section["title"]) == title:
            return section
    raise ValueError(f"Missing heading: {title}")


def descendants(
    sections: list[dict[str, Any]], parent_title: str, child_level: int = 3
) -> list[dict[str, Any]]:
    parent_index = next(
        index
        for index, section in enumerate(sections)
        if section["level"] == 2 and clean_heading(section["title"]) == parent_title
    )
    children: list[dict[str, Any]] = []
    for section in sections[parent_index + 1 :]:
        if section["level"] <= 2:
            break
        if section["level"] == child_level:
            children.append(section)
    return children


def parse_contributions(body: str) -> list[dict[str, str]]:
    contributions = [
        {"number": match.group(1), "text": clean_inline_latex(match.group(2).strip())}
        for match in CONTRIBUTION_RE.finditer(body)
    ]
    if contributions:
        return contributions

    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", body) if item.strip()]
    return [
        {"number": str(index), "text": clean_inline_latex(paragraph)}
        for index, paragraph in enumerate(paragraphs, start=1)
    ]


def slugify(value: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return ascii_slug or "section"


def parse_bold_fields(body: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^\*\*([^*\n]+?)[：:]\*\*\s*", body))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        fields[match.group(1).strip()] = body[match.end() : end].strip()
    return fields


def parse_dataset_benchmark(body: str) -> dict[str, Any]:
    card_pattern = re.compile(
        r"^(数据集|Dataset|Benchmark)\s*\((\d+)\)[：:]\s*\[([^\]]+)\]\((https?://[^\s)]+)\)$"
    )
    datasets: list[dict[str, Any]] = []
    benchmarks: list[dict[str, Any]] = []
    for section in split_headings(body):
        if section["level"] != 4:
            continue
        match = card_pattern.fullmatch(clean_heading(section["title"]))
        if not match:
            continue
        card_type, number, name, url = match.groups()
        fields = parse_bold_fields(clean_inline_latex(section["body"]))
        if card_type in {"数据集", "Dataset"}:
            field_names = (
                ("使用阶段", "发布内容", "使用方法")
                if card_type == "数据集"
                else ("Usage Stage", "Released Content", "Usage Method")
            )
            target = datasets
        else:
            field_names = (
                ("任务类型", "使用方式", "评测方法", "对应贡献")
                if "任务类型" in fields
                else ("Task Type", "Usage Mode", "Evaluation Method", "Mapped Contributions")
            )
            target = benchmarks
        target.append(
            {
                "number": int(number),
                "name": name.strip(),
                "url": url,
                "fields": [
                    {"label": field_name, "body": fields[field_name]}
                    for field_name in field_names
                    if fields.get(field_name)
                ],
            }
        )

    all_fields = parse_bold_fields(clean_inline_latex(body))
    if not datasets and not benchmarks:
        primary = all_fields.get("主数据集") or all_fields.get("Primary Datasets")
        if primary:
            datasets.append(
                {
                    "number": 1,
                    "name": "现有数据集配置" if "主数据集" in all_fields else "Existing Dataset Configuration",
                    "url": "",
                    "fields": [{"label": "使用说明" if "主数据集" in all_fields else "Usage", "body": primary}],
                    "legacy": True,
                }
            )
        adaptation = all_fields.get("Benchmark 适配") or all_fields.get("Benchmark Adaptation")
        mapping = all_fields.get("Contribution 对应") or all_fields.get("Contribution Mapping")
        if adaptation or mapping:
            legacy_fields = []
            if adaptation:
                legacy_fields.append({"label": "使用方式" if "Benchmark 适配" in all_fields else "Usage Mode", "body": adaptation})
            if mapping:
                legacy_fields.append({"label": "评测方法" if "Contribution 对应" in all_fields else "Evaluation Method", "body": mapping})
            benchmarks.append(
                {
                    "number": 1,
                    "name": "现有 Benchmark 配置" if "Benchmark 适配" in all_fields else "Existing Benchmark Configuration",
                    "url": "",
                    "fields": legacy_fields,
                    "legacy": True,
                }
            )

    return {
        "datasets": datasets,
        "benchmarks": benchmarks,
        "downstream_tasks": all_fields.get("下游任务") or all_fields.get("Downstream Tasks", ""),
        "annotation_source": all_fields.get("标注来源") or all_fields.get("Annotation Source", ""),
        "gaps": all_fields.get("缺口与处理") or all_fields.get("Gaps and Handling", ""),
        "structured": bool(any(not card.get("legacy") for card in datasets + benchmarks)),
    }


def normalize_method_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_title = {section["title"]: section for section in sections}
    implementation_titles = [
        "Contribution (1) 的实现",
        "Contribution (2) 的实现",
        "Contribution (3) 的实现",
    ]
    dataset_title = "数据集与 Benchmark"
    process_title = "完整实现流程"
    if not all(title in by_title for title in implementation_titles + [dataset_title]):
        implementation_titles = [
            "Contribution (1) Implementation",
            "Contribution (2) Implementation",
            "Contribution (3) Implementation",
        ]
        dataset_title = "Datasets and Benchmark"
        process_title = "Complete Implementation Process"

    normalized = [by_title[title] for title in implementation_titles if title in by_title]
    if dataset_title in by_title:
        normalized.append(by_title[dataset_title])
    if process_title in by_title:
        normalized.append(by_title[process_title])
        return normalized

    is_chinese = dataset_title == "数据集与 Benchmark"
    framework = by_title.get("整体框架" if is_chinese else "Overall Framework", {}).get("body", "")
    training = by_title.get("训练流程" if is_chinese else "Training Procedure", {}).get("body", "")
    inference = by_title.get("推理流程" if is_chinese else "Inference Procedure", {}).get("body", "")
    if framework or training or inference:
        if is_chinese:
            body = (
                f"**整体机制：**\n\n{framework}\n\n"
                f"**数据准备：**\n\n按照数据集与 Benchmark 中的公开输入、发布标注和确定性预处理准备数据。\n\n"
                f"**端到端步骤：**\n\n{training}\n\n{inference}\n\n"
                "**最终输出：**\n\n输出最终任务预测及方案中已定义的置信度或证据结果，并使用公开 Benchmark 指标进行核验。"
            )
        else:
            body = (
                f"**Overall Mechanism:**\n\n{framework}\n\n"
                "**Data Preparation:**\n\nUse the released inputs, labels, and deterministic preprocessing defined by the benchmark.\n\n"
                f"**End-to-End Steps:**\n\n{training}\n\n{inference}\n\n"
                "**Final Outputs:**\n\nReturn the final task prediction and defined confidence or evidence artifacts for evaluation on released benchmark metrics."
            )
        normalized.append(
            {
                "id": f"method-complete-{slugify(process_title)}",
                "title": process_title,
                "body": body,
            }
        )
    return normalized


def parse_idea(path: Path) -> dict[str, Any]:
    markdown = path.read_text(encoding="utf-8")
    sections = split_headings(markdown)
    title_section = next(section for section in sections if section["level"] == 1)
    title = re.sub(r"^Idea[：:]\s*", "", clean_heading(title_section["title"]), flags=re.IGNORECASE)

    weakness = clean_inline_latex(section_by_title(sections, "Weakness")["body"])
    if clean_heading(title_section["title"]).upper().startswith("PASS:"):
        pass_sections = [
            {
                "id": f"pass-{index}-{slugify(clean_heading(section['title']))}",
                "title": clean_heading(section["title"]),
                "body": clean_inline_latex(section["body"]),
            }
            for index, section in enumerate(sections, start=1)
            if section["level"] == 2 and clean_heading(section["title"]) != "Weakness"
        ]
        return {
            "idea_title": title,
            "weakness": weakness,
            "causes": [],
            "contributions": [],
            "method_sections": pass_sections,
            "is_pass": True,
        }
    contribution_body = section_by_title(sections, "Contribution")["body"]

    causes: list[dict[str, str]] = []
    cause_heading = "成因分析" if any(
        section["level"] == 2 and clean_heading(section["title"]) == "成因分析"
        for section in sections
    ) else "Root-Cause Analysis"
    for index, section in enumerate(descendants(sections, cause_heading), start=1):
        heading = clean_heading(section["title"])
        title_match = CAUSE_TITLE_RE.match(heading)
        number = title_match.group(1) if title_match else str(index)
        cause_title = title_match.group(2) if title_match else heading
        causes.append(
            {
                "id": f"cause-{number}",
                "number": number,
                "title": cause_title.strip(),
                "body": clean_inline_latex(section["body"]),
            }
        )

    method_sections = []
    for index, section in enumerate(descendants(sections, "Method"), start=1):
        section_title = clean_heading(section["title"])
        method_sections.append(
            {
                "id": f"method-{index}-{slugify(section_title)}",
                "title": section_title,
                "body": clean_inline_latex(section["body"]),
            }
        )
    method_sections = normalize_method_sections(method_sections)
    for section in method_sections:
        if section["title"] in {"数据集与 Benchmark", "Datasets and Benchmark"}:
            section["dataset_benchmark"] = parse_dataset_benchmark(section["body"])

    contributions = parse_contributions(contribution_body)
    if len(causes) != 3 or len(contributions) != 3:
        raise ValueError(
            "A non-PASS idea must expose exactly three root causes and three contributions."
        )

    return {
        "idea_title": title,
        "weakness": weakness,
        "causes": causes,
        "contributions": contributions,
        "method_sections": method_sections,
        "is_pass": False,
    }


def normalize_manifest(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return raw
    for key in ("papers", "sources", "items"):
        if isinstance(raw, dict) and isinstance(raw.get(key), list):
            return raw[key]
    raise ValueError("Manifest must be a list or contain a papers/sources/items list")


def build_dataset(
    run_dir: Path = DEFAULT_RUN_DIR,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    papers = normalize_manifest(read_json(manifest_path))
    evaluation_path = run_dir / "evaluation.json"
    evaluation_raw = read_json(evaluation_path) if evaluation_path.exists() else {"evaluations": []}
    evaluations = {
        item["paper_id"]: item for item in evaluation_raw.get("evaluations", []) if item.get("paper_id")
    }

    ideas = []
    for index, paper in enumerate(papers, start=1):
        paper_id = paper["id"]
        idea_path = run_dir / "papers" / paper_id / "idea.md"
        if not idea_path.exists():
            continue
        idea = parse_idea(idea_path)
        evaluation = evaluations.get(paper_id, {})
        ideas.append(
            {
                "index": index,
                "id": paper_id,
                "paper_title": paper.get("title", paper_id),
                "authors": paper.get("authors", ""),
                "year": paper.get("year"),
                "venue": paper.get("venue", ""),
                "domain": paper.get("domain", ""),
                "source_url": paper.get("source_url", ""),
                "scholar_url": paper.get("scholar_url", ""),
                **idea,
                "review": {
                    "verdict": evaluation.get("verdict", "unreviewed"),
                    "scores": evaluation.get("scores", {}),
                    "strengths": evaluation.get("strengths", []),
                    "major_risks": evaluation.get("major_risks", []),
                    "required_revisions": evaluation.get("required_revisions", []),
                },
            }
        )

    verdicts: dict[str, int] = {}
    for idea in ideas:
        verdict = idea["review"]["verdict"]
        verdicts[verdict] = verdicts.get(verdict, 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_name": run_dir.name,
        "summary": {"total": len(ideas), "verdicts": verdicts},
        "ideas": ideas,
    }


def write_dataset(dataset: dict[str, Any], output_path: Path = DEFAULT_OUTPUT) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build web data from generated idea Markdown files.")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = write_dataset(build_dataset(args.run_dir, args.manifest), args.output)
    print(f"Built {output}")


if __name__ == "__main__":
    main()
