"""Explicit simulated AutoTable output -> real FigureCrafter -> real compiled paper.
Never runs or modifies upstream modules. All data lives in an isolated demonstration root.
"""
import base64
import json
from pathlib import Path
import time
import zipfile

from auto_figure.application import Application
from auto_figure.compiler import compile_latex
from auto_figure.figurecrafter_runner import runtime_environment
from workbench.pipeline import PipelineManager

TEX = r'''\documentclass[11pt]{article}
\usepackage[margin=22mm]{geometry}
\usepackage{amsmath}
\title{Confidence-Gated Local Inspection\\\large Simulated Manuscript for FigureCrafter Integration}
\author{AutoResearch Engineering Demonstration}
\date{}
\begin{document}
\maketitle
\begin{abstract}
This is a synthetic manuscript used solely to test the AutoTable-to-Auto-Figure handoff,
editable figure generation, and LaTeX insertion. The method is a hypothetical image classifier.
No experiments have been conducted and no accuracy or clinical claims are made.
\end{abstract}
\section{Introduction}
A classifier may form an uncertain prediction from a global image. This hypothetical design
uses a single conditional local inspection to refine uncertain examples. The intended overview
must explain which information controls inspection and which image content enters each encoder.
\section{Method}
Given an input image $x$, a shared encoder $E$ produces global features $g=E(x)$.
A coarse classifier $C$ maps $g$ to class probabilities $p=C(g)$. The uncertainty score is
$u=1-\max_k p_k$. A gate compares $u$ with a fixed threshold $\tau$.
If $u\leq\tau$, inference returns the coarse prediction without local inspection.
If $u>\tau$, a region selector $R$ uses the global features to propose one image region;
a crop operator extracts that region from the original input image $x$.
The same encoder $E$ maps the crop to local features $l$.
A fusion module concatenates $g$ and $l$; a refinement classifier $C_r$ predicts the final label.
Only one local inspection is allowed, so there is no recurrent refinement loop.

\subsection{Training and inference}
During training, both the coarse and refinement branches are evaluated for every example.
Their predictions are supervised by the same ground-truth label $y$, using
$\mathcal{L}=\mathrm{CE}(p,y)+\mathrm{CE}(C_r([g,l]),y)$.
The uncertainty threshold gates computation only at inference time.
Ground-truth labels and loss computation are absent during inference.
The region selector and shared encoder are learned together with the classifiers.

\subsection{Representation requirements}
An overview should make the crop's dependence on the original image visible, show that both
encodings share weights, distinguish the coarse exit from the conditional refined exit,
and separate training supervision from inference control. Reference figures provide visual
expression only; their scientific modules are not part of this hypothetical method.
\section{Experimental protocol}
No experiment was run. Table~\ref{tab:status} is a status table, not a result table.
\begin{table}[h]
\centering
\caption{Simulated engineering status; no measured results.}\label{tab:status}
\begin{tabular}{ll}
Item & Status \\\hline
Dataset & Not selected \\
Accuracy & N/A --- not measured \\
Latency & N/A --- not measured \\
Scientific validation & Pending \\
\end{tabular}
\end{table}
\section{Limitations}
This synthetic description is not a validated research contribution. Region selection,
threshold calibration and training stability would require real experiments.
\section{Conclusion}
The manuscript exists only to validate the automated figure integration and artifact delivery.
\end{document}
'''


def main():
    root = Path(__file__).resolve().parent.parent
    demo = root / 'assets/output/figurecrafter-demo-20261020'
    demo.mkdir(exist_ok=True)
    original = demo / 'mock-autotable'
    original.mkdir(exist_ok=True)
    pdf = demo / 'mock-build/main.pdf'
    archive = demo / 'mock-autotable.zip'
    if not pdf.exists() or not archive.exists():
        (original / 'main.tex').write_text(TEX)
        compiler, pdf = compile_latex(original / 'main.tex', demo / 'mock-build', demo / 'mock-compile.log', lambda p: None)
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(original / 'main.tex', 'main.tex')
    source = {'id':'simulated-autotable-fixture', 'title':'模拟论文：置信度门控局部检查', 'mode':'manuscript',
              'status':'ready','attempt':1,'outputs':[{'id':'manuscript','pdf':str(pdf),'zip':str(archive),'manifest':{'main_tex':'main.tex'}}],
              'simulation':True, 'disclosure':'Synthetic upstream record, not an AutoTable model execution or real research result.'}
    (demo / 'simulated-upstream.json').write_text(json.dumps(source, ensure_ascii=False, indent=2))
    class MockTable:
        def load(self, project_id):
            if project_id != source['id']:
                raise ValueError('Unknown synthetic source')
            return source
    table = MockTable()
    app = Application(root, demo / 'auto_figure', table=table)
    pipeline = PipelineManager(demo / 'pipelines', root, None, table, app)
    if pipeline.flows:
        flow = next(iter(pipeline.flows.values()))
        flow.update(status='running', retry=flow['stage'] != 'figure')
    else:
        flow = pipeline.create({'start_stage':'table','source_id':source['id'],'title':'FigureCrafter 模拟上游接入验收'})
    pipeline.tick()
    flow = pipeline.get(flow['id'])
    if flow['figure_id'] is None:
        pipeline.tick()
        flow = pipeline.get(flow['id'])
    figure_id = flow['figure_id']
    p = app.load(figure_id)
    if p['status']=='awaiting_references':
        pipeline.tick()
        assert flow['status']=='waiting_review' and not app.jobs
        (demo / 'reference-gate.json').write_text(json.dumps({'flow_status':flow['status'],'figure_status':p['status'],'no_job_before_confirmation':True},indent=2))
        app.select_references(figure_id, {'confirm':True})
    if p['status'] == 'needs_revision':
        app.start(figure_id, {'retry_review':True})
        flow['retry'] = False
    elif p['status'] in {'failed','paused'}:
        app.start(figure_id)
        flow['retry'] = False
    (demo / 'demo-identity.json').write_text(json.dumps({'flow_id':flow['id'],'figure_id':figure_id,'simulation':True},ensure_ascii=False,indent=2))
    for _ in range(40000):
        pipeline.tick()
        p=app.load(figure_id)
        if p['status'] in {'ready','failed','needs_revision','paused'} and figure_id not in app.jobs:
            break
        time.sleep(.25)
    pipeline.tick()
    (demo / 'outcome.json').write_text(json.dumps({'flow':pipeline.get(flow['id']),'figure':app.load(figure_id)},ensure_ascii=False,indent=2))
    print(json.dumps({'status':p['status'],'message':p['message'],'figure_id':figure_id},ensure_ascii=False),flush=True)
    if p['status']!='ready':
        raise SystemExit(1)


if __name__=='__main__':
    main()
