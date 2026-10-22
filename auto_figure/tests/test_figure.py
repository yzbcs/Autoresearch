"""Engineering fixtures: model responses are synthetic; SVG rendering and file edits are real."""

import base64
import io
import json
import time
import zipfile
from pathlib import Path

import pytest

from auto_figure import manuscript, rendering
from auto_figure.application import STEPS, Application
from auto_table.tests.test_application import fake_compile

METHOD = "The encoder maps input images to features. The classifier predicts labels from features."
TEX = (
    r"""\documentclass{article}
\begin{document}
\section{Method}

"""
    + METHOD
    + r"""

\section{Experiments}
\begin{table}[t]
\caption{Engineering values}\label{tab:results}
\begin{tabular}{lc}Baseline & 42.5\\\end{tabular}
\end{table}
The baseline result is reported in Table~\ref{tab:results}.
\end{document}
"""
)
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="100" viewBox="0 0 600 100"><rect x="10" y="10" width="580" height="80" fill="#e1f2ec"/><text x="25" y="55" font-size="20">Input → Encoder → Classifier → Label</text></svg>'


def bundle(files=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, text in (
            files or {"main.tex": TEX, "references.bib": "% Unchanged bibliography\n"}
        ).items():
            archive.writestr(name, text)
    return stream.getvalue()


def payload():
    return {
        "title": "主图工程验收",
        "files": [{"name": "paper.zip", "content_base64": base64.b64encode(bundle()).decode()}],
    }


def plan():
    return {
        "method_text": METHOD,
        "caption": "Method overview.",
        "source_file": "main.tex",
        "anchor": METHOD,
        "action": "insert_after",
        "placement": "column",
        "rationale": "After the method overview paragraph.",
        "evidence": [{"file": "main.tex", "quote": METHOD}],
    }


class Runner:
    def __init__(self):
        self.calls = []
        self.pass_review = True
        self.all_pages = True

    def __call__(self, prompt, schema, directory, logs, name, job):
        self.calls.append(name)
        if name == "plan":
            return plan()
        return {
            "passed": self.pass_review,
            "findings": ["Synthetic engineering reviewer; not scientific validation."],
            "inspected_pages": [str(p) for p in (directory / "pages").glob("*.png")]
            if self.all_pages
            else [],
        }


def generate(inputs, destination, config, logs, job):
    """Explicit synthetic drawing/review; real native PPTX and LibreOffice rendering."""
    import subprocess
    from auto_figure.figurecrafter_runner import python_path, ROOT, runtime_environment
    destination.mkdir(parents=True, exist_ok=True)
    builder = destination / 'fixture.py'
    builder.write_text("""import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from pptx import Presentation
from pptx.util import Inches
from pptx.enum.shapes import MSO_SHAPE
from harness.model_led_drawing import render, inventory
p=Path(sys.argv[2]);r=Presentation();r.slide_width=Inches(16);r.slide_height=Inches(9)
s=r.slides.add_slide(r.slide_layouts[6])
s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1), Inches(2), Inches(4), Inches(3))
s.shapes.add_textbox(Inches(1), Inches(1), Inches(12), Inches(1)).text='Synthetic engineering fixture: Input - Encoder - Classifier'
r.save(p/'main-figure.pptx'); render(p/'main-figure.pptx',p/'render')
(p/'validation.json').write_text(json.dumps({'freeze':{'errors':[],'unexpected_files':[]},'fixture':True,'native_objects':inventory(p/'main-figure.pptx')}))
(p/'caption.md').write_text('Synthetic engineering fixture; no scientific validation.')
(p/'freeze.json').write_text(json.dumps({'fixture':True}))
""")
    # Rendering is done once per fixture destination; compile retry must not redraw.
    import shutil
    if (destination / 'render').exists():
        shutil.rmtree(destination / 'render')
    subprocess.run([python_path(), str(builder), str(ROOT / 'figurecrafter'), str(destination)], check=True, env=runtime_environment(), capture_output=True)
    return {k: str(destination / n) for k,n in {'pptx':'main-figure.pptx','pdf':'render/main-figure.pdf',
            'png':'render/slide-01.png','caption':'caption.md','validation':'validation.json','freeze':'freeze.json'}.items()}


def wait(app, project_id):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if project_id not in app.jobs:
            return app.load(project_id)
        time.sleep(0.02)
    raise AssertionError("Figure fixture did not finish")


@pytest.fixture
def app(tmp_path):
    instance = Application(tmp_path, runner=Runner(), generator=generate, compiler=fake_compile)
    yield instance
    instance.close()


def test_complete_keeps_original_and_all_table_bytes(app):
    p = app.create(payload())
    original = (app.directory(p["id"]) / "input/manuscript.zip").read_bytes()
    app.select_references(p["id"], {"confirm": True})
    app.start(p["id"])
    result = wait(app, p["id"])
    assert result["status"] == "ready", result["message"]
    assert result["completed_steps"] == STEPS
    directory = app.directory(p["id"]) / "attempt-1"
    content = (directory / "source/main.tex").read_text()
    assert content.count("% AUTOFIGURE BEGIN") == 1
    assert r"\label{tab:results}" in content and "42.5" in content
    assert [m[0] for m in manuscript.TABLE.finditer(content)] == [
        m[0] for m in manuscript.TABLE.finditer(TEX)
    ]
    assert original == (app.directory(p["id"]) / "input/manuscript.zip").read_bytes()
    assert (directory / "source/references.bib").read_text() == "% Unchanged bibliography\n"
    with zipfile.ZipFile(directory / "deliverables.zip") as archive:
        assert "method-overview.pptx" in archive.namelist()
        assert "method-overview.pdf" in archive.namelist()
        assert "manuscript-with-figure.pdf" in archive.namelist()


def test_compile_retry_reuses_plan_and_generation(app):
    calls = []

    def compile_once(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("Synthetic compiler interruption")
        return fake_compile(*args)

    app.compiler = compile_once
    p = app.create(payload())
    app.select_references(p["id"], {"confirm": True})
    app.start(p["id"])
    assert wait(app, p["id"])["step"] == "compile"
    app.start(p["id"])
    assert wait(app, p["id"])["status"] == "ready"
    assert app.runner.calls == ["plan", "review"]
    assert (app.directory(p["id"]) / "attempt-1/source/main.tex").read_text().count(
        "% AUTOFIGURE BEGIN"
    ) == 1


def test_review_must_cover_all_pages_and_revision_preserves_attempt(app):
    app.runner.all_pages = False
    p = app.create(payload())
    app.select_references(p["id"], {"confirm": True})
    app.start(p["id"])
    assert wait(app, p["id"])["status"] == "needs_revision"
    app.runner.all_pages = True
    app.start(p["id"], {"revise": True, "feedback": "Inspect all pages"})
    assert wait(app, p["id"])["status"] == "ready"
    assert (app.directory(p["id"]) / "attempt-1/review.json").is_file()
    assert (app.directory(p["id"]) / "attempt-2/review.json").is_file()


def test_restart_pauses_without_starting_job(app):
    p = app.create(payload())
    p["status"] = "running"
    app.save(p)
    recovered = Application(app.workspace)
    assert recovered.load(p["id"])["status"] == "paused"
    assert not recovered.jobs


@pytest.mark.parametrize(
    "change",
    [
        {"anchor": "not in manuscript"},
        {"anchor": "The encoder"},
        {"source_file": "../main.tex"},
        {"evidence": [{"file": "main.tex", "quote": "Invented scientific method"}]},
        {"action": "rewrite"},
    ],
)
def test_rejects_ambiguous_or_unfounded_plans(change):
    info = {"sources": [{"file": "main.tex", "text": TEX}]}
    with pytest.raises(ValueError):
        manuscript.validate_plan({**plan(), **change}, info)


def test_rejects_insertion_inside_table():
    source = TEX.replace("Baseline & 42.5", METHOD + "\n\nBaseline & 42.5").replace(
        METHOD + "\n\n\\section", "Overview.\n\n\\section", 1
    )
    with pytest.raises(ValueError, match="环境内部"):
        manuscript.validate_plan(plan(), {"sources": [{"file": "main.tex", "text": source}]})


def test_heading_anchor_without_blank_lines():
    compact = TEX.replace("\n\n", "\n")
    manuscript.validate_plan(
        {**plan(), "anchor": r"\section{Method}"},
        {"main_tex": "main.tex", "sources": [{"file": "main.tex", "text": compact}]},
    )


def test_placeholder_preserves_label_and_existing_reference(tmp_path):
    block = r"\begin{figure}\centering TODO method placeholder\caption{TODO}\label{fig:method}\end{figure}"
    source = TEX.replace(METHOD, METHOD + "\n\n" + block + "\nSee Figure~\\ref{fig:method}.")
    archive = tmp_path / "paper.zip"
    archive.write_bytes(bundle({"main.tex": source}))
    info = manuscript.inspect(archive, tmp_path / "original")
    svg, pdf = tmp_path / "figure.svg", tmp_path / "figure.pdf"
    svg.write_text(SVG)
    rendering.render(svg, pdf, tmp_path / "preview.png")
    result = manuscript.patch(
        tmp_path / "original",
        tmp_path / "patched",
        info,
        {**plan(), "action": "replace_placeholder", "anchor": block},
        svg,
        pdf,
    )
    assert result["label"] == "fig:method"
    final = (tmp_path / "patched/main.tex").read_text()
    assert final.count(r"\label{fig:method}") == 1
    assert "An overview of the method" not in final


@pytest.mark.parametrize("name", ["../escape.tex", "/absolute.tex"])
def test_zip_cannot_escape(tmp_path, name):
    with pytest.raises(ValueError):
        manuscript.extract(bundle({name: TEX}), tmp_path / "source")


@pytest.mark.parametrize(
    "svg",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AAA"/></svg>',
        SVG.replace("<rect", "<script>alert(1)</script><rect"),
        SVG.replace("<rect", '<image href="file:///etc/passwd"/><rect'),
    ],
)
def test_svg_rejects_raster_wrapper_or_external_content(tmp_path, svg):
    path = tmp_path / "bad.svg"
    path.write_text(svg)
    with pytest.raises(ValueError):
        rendering.validate_svg(path)


def test_nested_main_and_method_source(tmp_path):
    source = TEX.replace(METHOD, r"\input{sections/method}")
    archive = tmp_path / "paper.zip"
    archive.write_bytes(
        bundle({"paper/main.tex": source, "paper/sections/method.tex": METHOD + "\n\n"})
    )
    info = manuscript.inspect(archive, tmp_path / "original")
    svg, pdf = tmp_path / "figure.svg", tmp_path / "figure.pdf"
    svg.write_text(SVG)
    rendering.render(svg, pdf, tmp_path / "preview.png")
    p = {
        **plan(),
        "source_file": "paper/sections/method.tex",
        "evidence": [{"file": "paper/sections/method.tex", "quote": METHOD}],
    }
    manuscript.patch(tmp_path / "original", tmp_path / "source", info, p, svg, pdf)
    changed = (tmp_path / "source/paper/sections/method.tex").read_text()
    assert "../autofigure-method/method-overview.pdf" in changed


def test_input_hash_change_cannot_resume(app):
    p = app.create(payload())
    (app.directory(p["id"]) / "input/manuscript.zip").write_bytes(bundle({"main.tex": "changed"}))
    app.select_references(p["id"], {"confirm": True})
    app.start(p["id"])
    assert wait(app, p["id"])["status"] == "failed"
    assert not app.runner.calls


def test_stop_preserves_completed_steps_and_can_resume(app):
    import threading

    entered = threading.Event()

    def waiting_generator(method, destination, config, logs, job):
        entered.set()
        while not job.cancelled.wait(0.02):
            pass
        job.check()

    app.generator = waiting_generator
    p = app.create(payload())
    app.select_references(p["id"], {"confirm": True})
    app.start(p["id"])
    assert entered.wait(3)
    app.stop(p["id"])
    assert wait(app, p["id"])["status"] == "paused"
    assert app.load(p["id"])["completed_steps"] == ["inspect", "plan", "prepare"]
    app.generator = generate
    app.start(p["id"])
    assert wait(app, p["id"])["status"] == "ready"
    assert app.runner.calls == ["plan", "review"]


def test_runtime_cache_paths_stay_inside_repository():
    from auto_figure.upstream_runner import REPO, runtime_environment

    env = runtime_environment()
    for key in ("HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME", "TMPDIR", "PYTHONPYCACHEPREFIX"):
        assert Path(env[key]).is_relative_to(REPO)


def test_references_gate_and_snapshots(app):
    p = app.create(payload())
    assert p['status'] == 'awaiting_references'
    with pytest.raises(ValueError, match='三张参考图'):
        app.start(p['id'])
    with pytest.raises(ValueError):
        app.select_references(p['id'], {'slots': [{'default':1}], 'confirm':True})
    p = app.select_references(p['id'], {'slots':[{'default':3},{'keep':True},{'default':1}], 'confirm':True})
    assert p['references_confirmed'] and len(p['references']) == 3
    assert p['references'][0]['default'] == 3
    assert len(list((app.directory(p['id'])/'input/references').iterdir())) == 2


def test_reference_tampering_cannot_resume(app):
    p = app.create(payload())
    p = app.select_references(p['id'], {'confirm':True})
    (app.directory(p['id'])/p['references'][0]['path']).write_bytes(b'changed')
    app.start(p['id'])
    assert wait(app,p['id'])['status']=='failed'
    assert not app.runner.calls


def test_replacing_references_creates_new_attempt(app):
    p=app.create(payload());app.select_references(p['id'], {'confirm':True});app.start(p['id'])
    assert wait(app,p['id'])['status']=='ready'
    p=app.select_references(p['id'], {'slots':[{'default':3},{'default':2},{'default':1}],'confirm':True})
    assert p['attempt']==2 and not p['outputs'] and not p['completed_steps']
    assert (app.directory(p['id'])/'attempt-1/method-overview.pptx').is_file()


def test_old_tasks_cannot_launch_removed_backend(app):
    p=app.create(payload());p.pop('backend');app.save(p)
    with pytest.raises(ValueError, match='旧 AutoFigure-Edit'):
        app.start(p['id'])


def test_review_retry_preserves_native_figure_and_previous_review(app):
    app.runner.pass_review=False
    p=app.create(payload());app.select_references(p['id'],{'confirm':True});app.start(p['id'])
    assert wait(app,p['id'])['status']=='needs_revision'
    directory=app.directory(p['id'])/'attempt-1'
    original=(directory/'method-overview.pptx').read_bytes()
    app.runner.pass_review=True
    app.start(p['id'],{'retry_review':True})
    result=wait(app,p['id'])
    assert result['status']=='ready' and result['attempt']==1
    assert (directory/'method-overview.pptx').read_bytes()==original
    assert app.runner.calls==['plan','review','review']
    assert json.loads((directory/'review-history/review-001.json').read_text())['passed'] is False
    assert (directory/'native-inspection.json').is_file()


def test_cannot_skip_drawing_with_review_retry(app):
    p=app.create(payload());app.select_references(p['id'],{'confirm':True})
    with pytest.raises(ValueError,match='单独重试复核'):
        app.start(p['id'],{'retry_review':True})
