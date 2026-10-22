"""Validate editable SVG structure and render the exact source used by LaTeX."""

import re
import xml.etree.ElementTree as ET


def validate_svg(path):
    data = path.read_bytes()
    if len(data) > 40 * 1024 * 1024 or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("SVG 过大或包含不支持的 XML 声明。")
    root = ET.fromstring(data)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("输出不是有效 SVG。")
    tags = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        tags.append(tag)
        if tag in {"script", "foreignObject", "animate", "set"}:
            raise ValueError("SVG 包含非静态绘图元素。")
        for key, value in element.attrib.items():
            key = key.rsplit("}", 1)[-1]
            if key.lower().startswith("on"):
                raise ValueError("SVG 不支持事件处理程序。")
            if key in {"href", "src"} and not value.startswith(
                ("#", "data:image/png;base64,", "data:image/jpeg;base64,")
            ):
                raise ValueError("SVG 必须自包含，不得引用外部图片或文件。")
    text = data.decode("utf-8")
    for url in re.findall(r"url\(\s*['\"]?([^)'\"]+)", text, re.IGNORECASE):
        if not url.strip().startswith("#"):
            raise ValueError("SVG 样式不支持外部资源。")
    if re.search(r"@import", text, re.IGNORECASE):
        raise ValueError("SVG 样式不支持外部导入。")
    if "text" not in tags or not any(
        t in tags for t in ("path", "rect", "line", "polyline", "polygon")
    ):
        raise ValueError("SVG 缺少可编辑文字或图形；整图位图封装不能通过验收。")
    return {
        "editable_texts": tags.count("text"),
        "embedded_images": tags.count("image"),
        "elements": len(tags),
    }


def render(svg, pdf, preview):
    import cairosvg

    report = validate_svg(svg)
    cairosvg.svg2pdf(url=str(svg), write_to=str(pdf))
    cairosvg.svg2png(url=str(svg), write_to=str(preview), output_width=1800)
    return report
