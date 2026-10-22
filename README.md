# AutoResearch

AutoResearch 将 **Auto Search、Auto Design、Auto Writing、Auto Table、Auto Figure** 整合到一个网页入口，支持从调研自动交接到实验和论文，同时保留各模块的独立任务。首页可管理全流程、恢复失败步骤并重启研究服务，**Research Journey（科研航线）** 可查看各阶段进展、分支和关联产物。

## 📖 [点击进入 Wiki 图文使用手册 →](https://github.com/yzbcs/Autoresearch/wiki)

第一次使用？从这里开始：**页面操作指引 · 五模块使用步骤 · 科研航线 · 常见问题 · PDF 图文版下载**。

## 五模块工作台

在仓库根目录运行（Python 3.11+）：

```bash
python3 -m workbench --port 8760
```

打开 [AutoResearch 工作台](http://127.0.0.1:8760/)。调用模型需要已安装并登录的 Codex CLI；生成 PDF 还需要 LaTeX 编译器。工作台自身只用 Python 标准库，不需要 Node、Skills 或额外前端构建。

| 模块 | 本地入口 | 功能 |
| --- | --- | --- |
| Auto Search | [/auto-search/](http://127.0.0.1:8760/auto-search/) | 论文调研、Idea 生成、独立评审、人工核验 |
| Auto Design | [/auto-design/](http://127.0.0.1:8760/auto-design/) | 实验设计、R0、执行、暂停恢复、结果诊断与审计 |
| Auto Writing | [/auto-writing/](http://127.0.0.1:8760/auto-writing/) | 文献调研、六章节写作、参考文献、LaTeX 与 PDF |
| Auto Table | [/auto-table/](http://127.0.0.1:8760/auto-table/) | 论文表格整理、实验数据制表、PDF 编译与独立复核 |
| Auto Figure | [/auto-figure/](http://127.0.0.1:8760/auto-figure/) | 方法主图 SVG、局部插入论文、最终 PDF 与复核 |

首页点击“新建全流程”可从研究方向开始，或接续已有调研、实验、写作任务。选题、方法审批、暂停、错误日志、局部重试和模板更换均可在网页处理。设计与恢复边界见 [全流程说明](docs/frontend_workflow.md)。

Auto Table 支持上传论文 ZIP、上传结构化实验结果，或接续 Auto Writing 已生成的论文。保持原始数值、方法名与来源，提供模板规划、失败恢复、表格源码和 PDF 下载。完整说明见 [Auto Table](auto_table/README.md)。新建全流程自动执行 Auto Search → Auto Design → Auto Writing → Auto Table → Auto Figure，最后以方法主图插入、论文编译与复核通过作为交付完成条件；五个模块也可独立启动。历史流程保留原完成语义。AutoFigure 复用已通过复核的 AutoTable 论文副本，保留表格和正文，交付 SVG、LaTeX ZIP 与含图 PDF。绘图依赖与配置见 [Auto Figure](auto_figure/README.md)。

任务数据默认保存在 `assets/output/workbench/`。启动或切换页面不会自动启动研究任务。完整启动参数、功能范围和验收记录见 [工作台说明](workbench/README.md) 与 [开发记录](docs/README.md)。

## Research Journey · 科研航线

启动工作台后，点击顶部「科研航线」，或打开 [Research Journey](http://127.0.0.1:8760/journey.html)。它使用现有全流程记录，不需要额外启动服务或执行前端构建。

- **真实进度**：查看论文数、候选 Idea、实验观测单元和设计调用次数；缺失记录显示 `—`。
- **交互航线**：查看五阶段及已记录的候选、R0 和方法修改分支；支持拖动、缩放、缩略图定位、全屏和 SVG 导出。
- **节点详情**：查看当前状态与关联产物，进入原模块继续操作。
- **事件时间线**：浏览已记录事件，每约 4 秒同步；历史事件不代表历史状态回放。
- **中英文界面**：右上角切换中文 / English，并记住选择；任务名称、研究内容和原始日志保留原文。

关闭「实时更新」只暂停页面同步；「暂停流程」沿用工作台暂停功能，恢复与审批在「管理流程」或原模块处理。观测记录不代表实验或审计通过。详细操作见 [航线使用指南](docs/RESEARCH_JOURNEY.zh-CN.md) 或 [Wiki 补充页](https://github.com/yzbcs/Autoresearch/wiki/Research-Journey)。

## 原有 AutoResearch CLI

仓库原有的证据检索 CLI 继续保留：

```text
research topic -> papers -> paper cards -> field map -> gap evidence report
```

该 CLI 生成支持组会讨论和后续实验设计的研究图谱；论文写作使用上面的 Auto Writing 模块。

## Auto Design

`auto_design/` 提供实验设计与执行工作台：原生 HTML/CSS/JavaScript 前端、Python 服务端、Codex CLI 分阶段编排。无需安装 AutoDesign Skills 或 Node 依赖。

```bash
python3 -m auto_design serve --port 8767
```

需要 Python 3.11+ 和已登录的 Codex CLI。详见 [Auto Design 模块说明](auto_design/README.md)。原有 AutoResearch 搜索命令继续按下文使用。

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

autoresearch search "medical VLM temporal lesion change analysis" --limit 20 --full-text-limit 6
```

AutoResearch can run with an explicit domain profile:

```bash
autoresearch search "medical VLM temporal lesion change analysis" --profile medical-vlm
autoresearch search "GUI agent benchmark real-world workflow" --profile gui-agent
```

To generate a profile from a topic before running search:

```bash
autoresearch profile "GUI agent benchmark real-world workflow"
```

To regenerate the UI from an existing run:

```bash
autoresearch dashboard outputs/medical-vlm-temporal-lesion-change-analysis
```

To regenerate the Chinese synthesis and UI from an existing run:

```bash
autoresearch synthesize outputs/gui-agent-benchmark-real-world-workflow
```

To serve generated dashboards through a small read-only web server:

```bash
AUTORESEARCH_PORT=8766 autoresearch-server
```

Open `http://127.0.0.1:8766/`. Deployment notes for ECS / Nginx are in
`docs/DEPLOY.md`.

To let Codex act as the manual LLM reviewer for MOC, Gap, and opportunities:

```bash
autoresearch codex-packet outputs/gui-agent-benchmark-real-world-workflow
# Ask Codex to read codex_review_packet.json and write codex_review_result.json.
autoresearch codex-apply \
  outputs/gui-agent-benchmark-real-world-workflow \
  outputs/gui-agent-benchmark-real-world-workflow/codex_review_result.json
```

The detailed workflow is documented in `docs/CODEX_REVIEW_WORKFLOW.md`. Codex Review is the current
main research-judgment path: automated code collects evidence, and Codex reviews/refines MOC, Gap,
and research opportunities.

The next search-quality plan is documented in `docs/PROFILE_AWARE_SOURCE_RANKER_PLAN.md`. It keeps
steps small: first label core/adjacent/noise evidence, then connect the labels to ranking and UI.

Optional Semantic Scholar API key:

```bash
export SEMANTIC_SCHOLAR_API_KEY="..."
```

Optional Unpaywall email for open-access PDF enrichment:

```bash
export UNPAYWALL_EMAIL="you@example.com"
```

Experimental API-based paper-card extraction:

```bash
export AUTORESEARCH_LLM_API_KEY="..."
export AUTORESEARCH_LLM_MODEL="..."
export AUTORESEARCH_LLM_BASE_URL="https://api.openai.com/v1"

autoresearch search "medical VLM temporal lesion change analysis" --llm-card-limit 5
```

This is not the current main path. The main path is Codex Review through `codex-packet` and
`codex-apply`.

Outputs are written to:

```text
outputs/<topic-slug>/
  dashboard.html
  domain_profile.json
  raw/
  source_coverage.md
  search_result.json
  synthesis.json
  analysis_report.md
  codex_review_packet.md
  codex_review_packet.json
  codex_review_result.template.json
  paper_cards.json
  paper_insights.json
  influences.json
  open_access.json
  llm_extractions.json
  field_map.json
  topic_moc.json
  topic_moc.md
  comparison_matrix.json
  comparison_matrix.md
  gaps.json
  gap_evidence_chains.md
  research_opportunities.json
  research_opportunities.md
  report.md
  weakness_report.md
```

## Current MVP

- Query planning from a high-level research direction.
- Domain Profile v1: `auto`, `medical-vlm`, `gui-agent`, `llm-agent`, or a custom JSON profile can
  define core concepts, query terms, capability dimensions, benchmark keywords, metric keywords, and
  gap lenses before search starts.
- Multi-source paper collection from arXiv, OpenAlex, PubMed, Europe PMC, CrossRef, and OpenReview.
- Failure-tolerant source execution with warnings.
- DOI / PMID / arXiv / OpenAlex / fuzzy-title deduplication.
- Explainable ranking using lexical relevance, recency, citation count, source reliability, and
  research-signal keywords.
- Optional PDF/HTML full-text fetching for top-ranked papers.
- Section splitting for abstract, methods, experiments, results, limitations, and related sections.
- Source stability guard: local arXiv cache, shorter arXiv timeout, and per-run source skipping after
  repeated consecutive failures.
- Semantic Scholar enrichment for citation counts, influential citation counts, references, fields
  of study, venue, and open-access PDF links.
- Unpaywall enrichment for DOI-based open-access landing pages and PDF links.
- Paper card extraction from title, abstract, metadata, and section-aware full text when available.
- Profile-grounded paper card coverage tags, including capability-specific tags such as
  `capability:real-world-long-horizon-workflow` or
  `capability:lesion-level-temporal-change-reasoning`.
- Paper Card v2 fields with problem, method family, core assumption, evidence type, missing
  capability, relation-to-topic, gap hint, per-field evidence snippets, extraction status, and
  coverage tags.
- Profile-aware non-medical paper-card heuristics so GUI/LLM agent runs do not reuse medical-only
  task, gap-hint, method-family, dataset, metric, or localization templates.
- Optional LLM-backed Paper Card refinement through an OpenAI-compatible chat-completions endpoint.
  It is disabled by default and only updates fields that cite existing evidence snippet IDs.
- Paper Insight Cards that capture problem, method core, evidence, assumption, limitation,
  cross-paper relation, inspiration, and experimentable gap.
- Topic MOC v2 generation for core concepts, paper groups, problem spaces, shared assumptions,
  method families, datasets/benchmarks, covered capabilities, missing capabilities, open questions,
  and possible experiments.
- Cross-paper comparison matrix across paper groups: problem space, method family, temporal input,
  lesion localization, change evaluation, location consistency, benchmark/metric coverage, and gap
  hints.
- Lightweight field mapping by task, method, dataset, metric, and model type.
- Evidence-grounded gap finding with source URLs, snippets, section labels, support/counter counts,
  and confidence score reasons.
- Profile-grounded Gap Finder that can generate coverage, benchmark, and metric gaps for the
  selected domain instead of only using the medical VLM demo rules.
- Gap Evidence Chain v2 paper-level judgments: each paper is marked as support, counter, or unclear
  for each gap, with missing evidence and influence signals.
- Gap evidence chain Markdown export plus evidence-backed research opportunity generation.
- Chinese synthesis layer that lets Codex stand in for the later LLM step by summarizing Domain
  Profile, source quality, MOC takeaways, Gap evidence chains, limitations, and next actions into
  `analysis_report.md` and `synthesis.json`.
- Codex-in-the-loop review mode: `codex-packet` exports evidence for manual Codex review, and
  `codex-apply` imports Codex's structured JSON judgment back into MOC, Gap evidence chains,
  research opportunities, synthesis, reports, and the dashboard.
- Dashboard clearly marks whether current research judgments are `Rule-generated` or
  `Codex-reviewed`.
- Weakness report optimized for research discussion: how each weakness emerges, evidence chain,
  counter evidence, why still open, experimentable idea, and verification plan.
- Static local dashboard UI for source health, paper cards, MOC problem spaces, gap evidence chains,
  research opportunities, and synthesis.
- Dashboard UI labels and rule-generated research signals are localized in Chinese while preserving
  original paper titles and evidence snippets.
- Dashboard top actions switch between Chinese in-page tabs instead of jumping to Markdown exports.
- Dashboard shows the active Domain Profile, core concepts, capability dimensions, benchmark/metric
  keywords, and gap lenses.
- Paper cards, MOC problem spaces, Gap evidence chains, and research opportunities are expandable
  detail panels, with an LLM extraction summary shown at the top of the page.
- Source coverage report and readiness gate for validating search breadth before interpreting
  preliminary weaknesses.
- Markdown and JSON artifact export.

## Design Principle

Every gap should be traceable to evidence. If evidence is weak, AutoResearch should say so.
