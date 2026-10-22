# Auto Figure · FigureCrafter

AutoResearch 最后一个阶段。新任务统一使用自有 FigureCrafter（固定 drawing harness v2.5.1），不再执行 AutoFigure-Edit，不需要 SAM、生图服务或抠图服务。

完整流程保持 Auto Search → Auto Design → Auto Writing → Auto Table → Auto Figure。
本次只修改 auto_figure/ 和 workbench 中第五阶段的交接/展示；前四模块内部逻辑不变。

## 作者操作

AutoTable 完整论文达到 ready 后，现有 pipeline 自动复制最终 LaTeX ZIP、PDF、来源轮次和哈希，创建绘图任务。流程停在“确认三张参考图”，不自动调用模型。
打开 `/auto-figure/?project=任务ID`，查看三张参考，逐张选择默认图或上传 PNG/JPEG（每张最多 6 MB）；确认后开始绘图。默认三张来自固定 FigureCrafter 包自带的显式参考图片，仅提供图片，不读取其配套论文/PPTX。
独立入口也可上传 LaTeX ZIP。缺图 PDF 由源码副本真实编译，明确的主图 placeholder 仅在绘图输入副本中移除。原始上游产物不改。

生成过程：读取论文 → 规划插图位置 → 准备缺图 PDF → FigureCrafter → 局部插图 → 编译 PDF → 全文复核。
FigureCrafter 独立读取完整缺图 PDF 和三张 PNG，模型决定科学理解、参考迁移、16:9 构图、原生对象、作者代码与像素审查；不启用外层进化。

最终下载：含图完整论文 PDF、独立主图 PDF、可编辑 PPTX、PNG、含图 LaTeX ZIP、完整交付包。ready 必须真实绘图 finish、冻结验证、真实论文编译和完整页面模型复核均通过。模型复核不代表科研结论已被证实。

## 环境

工作台使用原环境；绘图单独使用项目 `.venv-figurecrafter`：

```sh
mkdir -p assets/tmp/auto_figure .cache/pip
python3 -m venv .venv-figurecrafter
TMPDIR="$PWD/assets/tmp/auto_figure" PIP_CACHE_DIR="$PWD/.cache/pip" \
  .venv-figurecrafter/bin/pip install -r auto_figure/requirements.txt
cc -shared -fPIC -O2 auto_figure/tools/lo_project_tmp.c -o auto_figure/tools/libfc_lo_tmp.so -ldl
.venv-figurecrafter/bin/python auto_figure/figurecrafter/run.py --soffice /usr/bin/soffice doctor
```

LibreOffice 为已有系统工具，不安装或修改系统包。服务器验证使用 7.3.7.2；字体和公式仍需真实看图。
模型复用既有项目 Codex 登录，通过 Auto Figure 自己的结构化桥接：禁用本轮模型 shell/unified_exec，直接传入全文和实际图片附件，由宿主执行固定 FigureCrafter 工具。此修改不触及前四模块的 Codex 调用或全局配置。
模型写的 builder 仍通过固定 harness 执行。Linux worker 增加 Landlock 普通写入边界，仅允许本次生成/日志和项目内专用缓存、临时目录、既有 Codex 状态目录。当前内核 ABI 1 不支持独立 truncate 权限，不声称是完整的恶意代码隔离；未更改内核或其他模块的沙箱。LibreOffice 7.3 的 IPC 固定优先使用 /tmp；项目内 soffice wrapper 仅对自己的 LibreOffice 子进程加载可审计的 C shim，将 OSL_PIPE_* UNIX socket 映射至 .cache/fc-ipc，并允许非持久的 /dev/null 输出。普通临时文件、profile、字体缓存仍在项目目录，系统二进制和其他模块不改。

| 环境变量 | 用途 |
|---|---|
| FIGURECRAFTER_PYTHON | 绘图 Python；默认项目 .venv-figurecrafter/bin/python |
| FIGURECRAFTER_MODEL | 模型；未设置沿用 CODEX_MODEL |
| FIGURECRAFTER_REASONING_EFFORT | 未设置沿用 CODEX_REASONING_EFFORT |
| FIGURECRAFTER_TIMEOUT_SECONDS | 整次绘图超时，默认 3600 秒 |
| FIGURECRAFTER_MODEL_TIMEOUT_SECONDS | 单次结构化模型调用超时，默认 900 秒 |
| DRAWING_SOFFICE | 既有 LibreOffice 路径，默认从 PATH 查找 |
| CODEX_CLI / LATEX_COMPILER | 沿用既有入口，凭据不写进任务 JSON |

任务绘图配置仅允许 model、reasoning_effort、timeout_seconds。新增缓存与临时文件均在项目内。
FigureCrafter 的 Tectonic wrapper 优先尝试缓存资源，失败才走原编译器的正常下载。仅 Auto Figure 子进程采用该 wrapper，不修改上游编译器配置。

## 恢复与历史

停止会终止当前模型/绘图子进程，保留会话和中间稿；继续时复用已完成步骤。模型连续性通过持久的结构化对话/工具记录与实际图片重传维持，每次结构化调用为独立 CLI 会话。编译失败只重试编译。已完成绘图和编译的任务可通过 retry_review 单独补证重试复核，旧复核保存在 review-history，主图和原 attempt 保持不变。第五阶段被阻塞后会继续观察自己关联的绘图任务，识别作者在绘图页面完成的手动恢复；不会重试上游模块。参考图、要求或配置变化建立新 attempt；上游轮次或哈希变化使原图失效。
完成的历史 AutoFigure-Edit 产物保留下载，旧任务不能再启动第三方生成；请从原始论文新建 FigureCrafter 任务。
生产任务目录仍在 `assets/output/workbench/auto_figure/`，不更名历史任务。

API 在既有 `/auto-figure/api` 下新增 `POST /projects/<id>/references`：

```json
{"slots":[{"default":1},{"keep":true},{"name":"custom.png","content_base64":"..."}],"confirm":true}
```

三槽一次保存，原子验证后产生独立 selection-N 快照。确认后可 start；流水线会在下个 tick 开始。任务的引用图和 PDF/ZIP 被篡改则拒绝恢复。

## 验证与模拟论文

`auto_figure/demo.py` 在 `assets/output/figurecrafter-demo-20261020/` 生成明确标注的模拟论文与模拟 AutoTable 只读记录，通过真正 PipelineManager 交接到真实绘图、编译和模型复核。它不执行或修改 AutoTable 生成逻辑，不把模拟数据冒充研究结果。演示有自己的流程目录，不推进已有研究任务。

工程测试含显式 synthetic 模型/复核 fixture；本机 LibreOffice 和文件回填为真实执行。真实模型演示与 fixture 报告分开记录在 `assets/logs/figurecrafter-integration-20261020/`。

```sh
TMPDIR="$PWD/assets/tmp/auto_figure" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:auto_search \
 .venv-autofigure/bin/python -m pytest --import-mode=importlib auto_figure/tests workbench/tests -q \
 --basetemp="$PWD/assets/tmp/auto_figure/pytest-crafter-final"
```

接入前快照、前四模块源码哈希和最终保护对照记录也位于该日志目录。
