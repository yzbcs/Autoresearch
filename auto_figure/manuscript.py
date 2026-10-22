"""Exact source anchors and deterministic, auditable LaTeX edits."""

from __future__ import annotations

import difflib
import hashlib
import io
import json
import re
import shutil
import zipfile
from pathlib import Path

from auto_table.engine.manuscript import _find_main_tex, manuscript_sources


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def inside(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if root not in path.parents:
        raise ValueError(f"路径必须在 {root} 内：{path}")
    return path


def extract(data: bytes, destination: Path):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(i.file_size for i in entries) > 200 * 1024 * 1024:
            raise ValueError("论文解压后超过 200 MB 或文件过多。")
        for entry in entries:
            inside(destination, destination / entry.filename)
            if "\\" in entry.filename or entry.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError("论文 ZIP 不支持符号链接或反斜杠路径。")
        destination.mkdir(parents=True, exist_ok=True)
        archive.extractall(destination)


def inspect(archive, destination, main_file=None):
    if destination.exists():
        shutil.rmtree(destination)
    extract(Path(archive).read_bytes(), destination)
    main = _find_main_tex(destination, main_file)
    sources = manuscript_sources(destination, main)
    return {
        "main_tex": str(main.relative_to(destination)),
        "sources": [
            {"file": str(p.relative_to(destination)), "text": p.read_bytes().decode("utf-8")}
            for p in sources
        ],
        "hashes": {
            str(p.relative_to(destination)): digest(p)
            for p in destination.rglob("*")
            if p.is_file()
        },
    }


FIGURE = re.compile(r"\\begin\{(figure\*?)\}.*?\\end\{\1\}", re.DOTALL)
TABLE = re.compile(r"\\begin\{(table\*?)\}.*?\\end\{\1\}", re.DOTALL)


def validate_plan(plan, inspection):
    sources = {s["file"]: s["text"] for s in inspection["sources"]}
    if plan.get("source_file") not in sources:
        raise ValueError("插图位置不在主论文引用的源码中。")
    text = sources[plan["source_file"]]
    anchor = plan.get("anchor", "")
    if not isinstance(anchor, str) or not anchor.strip() or text.count(anchor) != 1:
        raise ValueError("插入锚点必须逐字匹配唯一一处源码。")
    for key in ("method_text", "caption", "rationale"):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            raise ValueError(f"主图规划缺少 {key}。")
    if len(plan["caption"]) > 2500:
        raise ValueError("图注过长。")
    if plan.get("placement") not in {"column", "wide"}:
        raise ValueError("主图宽度必须为 column 或 wide。")
    if plan.get("action") not in {"insert_after", "replace_placeholder"}:
        raise ValueError("未知插图动作。")
    # Every proposed method must have exact, auditable evidence in the input manuscript.
    evidence = plan.get("evidence", [])
    if not evidence:
        raise ValueError("方法规划必须包含原文证据。")
    for item in evidence:
        if not item.get("quote", "").strip() or item.get("file") not in sources:
            raise ValueError("方法证据无效。")
        if item["quote"] not in sources[item["file"]]:
            raise ValueError("方法证据未在论文中找到。")
    start, end = text.index(anchor), text.index(anchor) + len(anchor)
    if plan["action"] == "replace_placeholder":
        if not FIGURE.fullmatch(anchor):
            raise ValueError("仅能整体替换一个明确的 figure 占位环境。")
        if not re.search(r"placeholder|TODO|待绘|占位", anchor, re.IGNORECASE):
            raise ValueError("已有主图不是明确占位图，不能自动替换。")
        if len(re.findall(r"\\label\{([^{}]+)\}", anchor)) > 1:
            raise ValueError("占位图包含多个 label，不能自动替换。")
    else:
        # Insert only at a paragraph/heading boundary, outside nested environments and comments.
        boundary = text[end:]
        heading = re.fullmatch(r"\\(?:sub)*section\*?(?:\[[^]]*\])?\{[^{}]+\}", anchor.strip())
        next_section = re.match(r"\s*\\(?:(?:sub)*section\*?|end\{document\})", boundary)
        if not (
            re.match(r"\s*\n\s*\n", boundary) or anchor.endswith("\n\n") or heading or next_section
        ):
            raise ValueError("插入锚点必须结束于完整段落或标题后的空行。")
        if plan["source_file"] == inspection.get("main_tex"):
            doc_start = text.find(r"\begin{document}")
            doc_end = text.find(r"\end{document}")
            if doc_start < 0 or start < doc_start or (doc_end >= 0 and end > doc_end):
                raise ValueError("不能在正文范围之外插图。")
        uncommented = re.sub(r"(?<!\\)%[^\n]*", "", text[:end])
        stack = []
        for match in re.finditer(r"\\(begin|end)\{([^{}]+)\}", uncommented):
            if match[1] == "begin":
                stack.append(match[2])
            elif stack and stack[-1] == match[2]:
                stack.pop()
            else:
                raise ValueError("锚点之前的 LaTeX 环境无法解析。")
        if any(name != "document" for name in stack):
            raise ValueError("不能在表格、公式或其他环境内部插图。")
        if any(m.start() < end < m.end() for m in FIGURE.finditer(text)):
            raise ValueError("不能在现有图中插入主图。")
    return start, end


def latex_text(text):
    mapping = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(mapping.get(c, c) for c in text.replace("\n", " "))


def patch(original, target, inspection, plan, svg, figure_pdf):
    start, end = validate_plan(plan, inspection)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(original, target)
    asset_name = "autofigure-method"
    if (target / asset_name).exists():
        raise ValueError("输入论文已有 AutoFigure 资源；请从原始上游版本创建新轮次。")
    assets = target / asset_name
    assets.mkdir()
    # Preserve native authoring format; the PDF is the exact rendered insertion asset.
    native = Path(svg)
    shutil.copy2(native, assets / ("method-overview" + native.suffix.lower()))
    shutil.copy2(figure_pdf, assets / "method-overview.pdf")
    texts = {s["file"]: s["text"] for s in inspection["sources"]}
    existing_labels = set(re.findall(r"\\label\{([^{}]+)\}", "\n".join(texts.values())))
    label = "fig:autofigure-method"
    suffix = 1
    while label in existing_labels:
        suffix += 1
        label = f"fig:autofigure-method-{suffix}"
    old_labels = re.findall(r"\\label\{([^{}]+)\}", plan["anchor"])
    if plan["action"] == "replace_placeholder" and old_labels:
        label = old_labels[0]
    if not re.fullmatch(r"[A-Za-z0-9:._-]+", label):
        raise ValueError("占位图 label 包含不支持的字符。")
    env = "figure*" if plan["placement"] == "wide" else "figure"
    # Paths resolve from the main TeX's directory, including nested main files.
    import os

    main = inside(target, target / inspection["main_tex"])
    asset_path = Path(os.path.relpath(assets / "method-overview.pdf", main.parent)).as_posix()
    figure = (
        f"\\begin{{{env}}}[t]\n\\centering\n"
        f"\\includegraphics[width=\\linewidth]{{{asset_path}}}\n"
        f"\\caption{{{latex_text(plan['caption'])}}}\n\\label{{{label}}}\n"
        f"\\end{{{env}}}"
    )
    has_reference = bool(
        re.search(
            r"\\(?:ref|autoref|cref|Cref)\{" + re.escape(label) + r"\}", "\n".join(texts.values())
        )
    )
    reference = (
        ""
        if has_reference
        else f"An overview of the method is shown in Figure~\\ref{{{label}}}.\n\n"
    )
    block = "% AUTOFIGURE BEGIN\n" + reference + figure + "\n% AUTOFIGURE END"
    source_file = plan["source_file"]
    text = texts[source_file]
    if plan["action"] == "replace_placeholder":
        changed = text[:start] + block + text[end:]
    else:
        changed = text[:end] + "\n\n" + block + text[end:]
    changes = {source_file: changed}
    main_name = inspection["main_tex"]
    main_text = changes.get(main_name, texts[main_name])
    preamble = main_text.split(r"\begin{document}", 1)[0]
    if not re.search(
        r"\\(?:usepackage|RequirePackage)(?:\[[^]]*\])?\{[^}]*\bgraphicx\b[^}]*\}", preamble
    ):
        if main_text.count(r"\begin{document}") != 1:
            raise ValueError("无法定位唯一的 document 起点。")
        changes[main_name] = main_text.replace(
            r"\begin{document}", "\\usepackage{graphicx}\n\\begin{document}", 1
        )
    patches = []
    for name, content in changes.items():
        before = texts[name]
        if [m[0] for m in TABLE.finditer(before)] != [m[0] for m in TABLE.finditer(content)]:
            raise ValueError("插图补丁改变了表格，已拒绝。")
        inside(target, target / name).write_bytes(content.encode("utf-8"))
        patches.extend(
            difflib.unified_diff(
                before.splitlines(True),
                content.splitlines(True),
                fromfile="a/" + name,
                tofile="b/" + name,
            )
        )
    # Unmodified files, including bibliography and table fragments, must be byte identical.
    for name, sha in inspection["hashes"].items():
        if name not in changes and digest(target / name) != sha:
            raise ValueError(f"插图过程中意外改变了文件：{name}")
    return {
        "main_tex": main_name,
        "label": label,
        "changed_files": sorted(changes),
        "patch": "".join(patches),
        "table_sources_unchanged": True,
        "source_hashes": inspection["hashes"],
    }
