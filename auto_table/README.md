# Auto Table

Auto Table 是 The ThAInker 的第四个系统模块。后端将 Paper2Table 的 Skill 工作流转为持久化任务、Codex 提示词、确定性制表引擎和 HTTP API，前端沿用其他三个模块的灰白底色、青绿色操作、侧边项目列表和步骤工作区。

## 启动

在仓库根目录安装现有依赖并启动：

```bash
python3 -m pip install -e .
python3 -m workbench --port 8760
```

进入 `http://127.0.0.1:8760/auto-table/`。也可独立启动：

```bash
python3 -m auto_table --port 8767
```

自动设计和独立复核使用已登录的 Codex CLI；沿用 `CODEX_CLI`、`CODEX_MODEL`、`CODEX_REASONING_EFFORT`、`CODEX_TIMEOUT_SECONDS` 和 `CODEX_IGNORE_USER_CONFIG`。模型默认继承 CLI 默认值，不固定模型。PDF 编译沿用 Auto Writing 的编译器发现和 `LATEX_COMPILER` / `LATEX_TIMEOUT_SECONDS` 配置。支持 latexmk、Tectonic、XeLaTeX、pdfLaTeX；需要 XeLaTeX 的工程请明确配置相应编译器。页面健康状态显示缺失的工具。

## 工作流

- **论文 ZIP**：上传一个 LaTeX 工程 ZIP，可附一个参考 PDF。系统提取 `table/table*`，由 Codex 根据论文语义设计表格，按原 label 替换，编译并逐页复核。支持主文件中的静态 `\\input{path}` / `\\include{path}`；多个主文件时可在高级设置指定相对路径。动态宏路径需要提供可直接解析的工程。
- **实验数据**：上传 CSV、TSV、JSON、JSONL。自动规划科学角色、指标方向、模板、比较范围与说明，确定性引擎生成 caption、description、LaTeX、HTML 和 PDF。可用 JSON 覆盖配置，或直接使用明确配置跳过设计。
- **接续 Auto Writing**：选择已生成 LaTeX ZIP 的写作任务，复制其 ZIP / PDF 为新任务输入，原写作产物保持不变。该功能在统一工作台中使用。

新建并启动后，后台依次执行读取、设计、生成、编译、复核。刷新或切换页面不会停止任务。失败后点击“从当前步骤继续”复用已完成步骤；编译失败不会重跑设计。停止仅针对当前表格任务。重启服务后任务显示已暂停，不会自行重新运行。修改要求会创建新一轮并保留之前的产物和日志。

`ready` 需要实际 PDF 编译成功，且独立 Codex 复核返回通过并列出全部渲染页面。复核为 Agent 判断，不等同于数学证明；代码保留原始数据、聚合来源、原表格、替换文件和复核报告供核对。数据生成的 `verification.valid` 仅代表语义规格通过检查。任何失败或负面复核均真实显示，不伪造成功状态。

## 文件与代码

| 位置 | 职责 |
|---|---|
| `application.py` | 项目、步骤、停止/重试、产物与复核状态 |
| `codex_runner.py` | 独立任务目录中的 Codex CLI、日志、超时与停止 |
| `prompting.py`、`prompts/` | 从 Skill 提炼的系统契约、设计和独立复核 Schema |
| `engine/` | 标准化、均值/样本 SD、排名、渲染、LaTeX 工程替换 |
| `templates/`、`references/` | 七类模板、六类科学角色与排版语法 |
| `web/` | HTTP API、项目列表、双输入流程、预览、下载与恢复 |
| `tests/` | 上游语义回归及系统工作流测试 |

输入位于 `assets/input/auto_table/<id>/`；独立服务输出位于 `assets/output/auto_table/<id>/`，统一工作台输出位于其 `data-dir/auto_table/<id>/`；提示词、命令和执行日志位于 `assets/logs/auto_table/<id>/`。每轮使用 `attempt-N`，包含计划、来源、表格、PDF、页面渲染和复核。最终下载包为 `deliverables.zip`，原始输入和内部记录也可单独下载。

API（统一入口加 `/auto-table` 前缀）：`GET /api/health`、`GET /api/catalog`、`GET/POST /api/projects`、`GET /api/projects/<id>`、`POST /api/projects/<id>/start`、`POST /api/projects/<id>/stop`、`GET /api/projects/<id>/files/<kind>/<path>`、`GET /api/writing-projects`、`POST /api/import-writing`。输入通过 JSON 的 `files: [{name, content_base64}]` 上传。

确定性 CLI 仍可直接使用：

```bash
python3 -m auto_table.engine list-templates
python3 -m auto_table.engine generate auto_table/examples/gallery/family_banded.csv \
  --config auto_table/examples/gallery/family_banded.json --out assets/output/auto_table/example
```

`examples/gallery` 是版式测试示例；它们不会进入网页项目列表。`examples/exp40` 保留上游已公开的汇总来源样例与 `SOURCE_NOTES.md`，不作为本次开发产生的科研结果。

## 来源与测试

确定性引擎、模板和参考规则来自 [goya4140/AutoTable](https://github.com/goya4140/AutoTable)，基于 `5c59714`，上游包版本 `0.11.0`，保留 MIT 许可于 `UPSTREAM_LICENSE`。系统不依赖安装该 Skill，项目中的提示词与代码可随 Git 一起交付。

```bash
PYTHONPATH=src:auto_search python3 -m pytest --import-mode=importlib auto_table/tests workbench/tests -q
node --check auto_table/web/app.js
```

具体运行验收与本轮交付记录见仓库 `docs/README.md`。

## 新任务目录命名

新建任务采用 `任务标题-table-YYYYMMDD-HHMMSS-ffffff`（北京时间，含微秒）。保留中文，特殊字符清理为连字符，标题部分最多 60 字符；重名冲突追加短编号。历史任务目录保持原路径。统一规则见 [工作台说明](../workbench/README.md#任务目录命名)。
