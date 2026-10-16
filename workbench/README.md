# AutoResearch 四模块工作台

一个网页入口分别进入 Auto Search、Auto Design、Auto Writing 和 Auto Table。四个模块保留各自的完整前端、后台任务管理器、提示词、Schema、科学约束和独立启动方式。

## 启动

在仓库根目录使用 Python 3.11+：

```bash
python3 -m workbench --port 8760
```

本机已有环境可直接使用：

```bash
.venv/bin/python3 -m workbench --port 8760
```

Windows PowerShell：

```powershell
$env:AUTORESEARCH_PYTHON = "C:\path\to\python.exe"
.\run_workbench.ps1 -Port 8760
```

打开 [工作台](http://127.0.0.1:8760/)。工作台服务使用 Python 标准库；Auto Table 的 PDF 页面渲染使用仓库依赖 PyMuPDF；模型调用需要已安装并登录的 Codex CLI。PDF 编译使用 Auto Writing 原有的编译器发现逻辑，支持 Tectonic、latexmk、XeLaTeX 或 pdfLaTeX。

请使用服务的 HTTP 地址。直接打开 `index.html` 只会进入本地文件预览，五个页面现在都会展示对应服务入口，不会从 `file://` 发起任务接口请求。自定义端口或单独启动模块时，使用启动终端打印的地址。

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 对外监听地址 |
| `--port` | `8760` | 唯一浏览器入口端口 |
| `--workspace` | 当前目录 | 新建 Auto Design 任务的默认项目根目录，同时决定默认数据根目录 |
| `--data-dir` | `<workspace>/assets/output/workbench` | 四模块任务索引与运行数据根目录 |

首页的连接状态来自真实健康接口。没有任务时显示空状态；打开页面和切换模块均不启动研究任务。浏览器切换不停止后台任务，退出服务则应先在模块内完成停止或安全暂停。

## 保留的功能

| 模块 | 浏览器入口 | 完整功能 |
| --- | --- | --- |
| Auto Search | `/auto-search/` | 新建方向调研、论文与 Weakness 提取、Idea 生成、可选独立评审、进度与日志、取消、调研文件夹删除、分板块阅读 Idea、人工通过或废弃及撤销核验 |
| Auto Design | `/auto-design/` | 新建任务、文本或文件输入 Idea、仅设计或完整流程、旧运行导入、R0 与正式执行、暂停恢复、Revision ID 审核、执行日志、结果表、诊断与独立审计、报告和产物文件浏览 |
| Auto Writing | `/auto-writing/` | 新建与修改资料、删除项目、Introduction 调研、Related Work 规划与调研、六章节逐步生成、任务停止、依赖与失效状态、参考文献调研与插入、路径约束、模板 ZIP 上传、LaTeX 适配、PDF 编译与 ZIP/PDF 下载 |

Auto Search 的 Weakness 直达 Idea 和批量生成命令仍保存在模块目录，原有 `src/autoresearch` CLI 也完整保留。单模块用法见 [Auto Search](../auto_search/README.md)、[Auto Design](../auto_design/README.md)、[Auto Writing](../auto_writing/README.md)。

首页“新建全流程”支持 Search → Design → Writing 自动交接，也可从已有模块任务接续。自动选题仅采用独立评审为 `promising` 且未被人工废弃的首选 Idea；可改为手动选题。实验完成后检查磁盘 `COMPLETE`、审计 PASS 和原始证据，再复制写作资料并自动运行全部写作步骤。失败时停止自动推进，由网页继续当前步骤；方法审批仍需明确决定。详见 [全流程设计与恢复说明](../docs/frontend_workflow.md)。

## 任务目录命名

新建任务统一为 `<任务标题>-<模块>-<北京时间戳>`，模块分别为 `search`、`design`、`writing`、`table`。时间戳格式为 `YYYYMMDD-HHMMSS-ffffff`（微秒），例如 `图像分类-search-20260908-153000-123456`。如果名称仍冲突，追加短编号，原目录不会被覆盖。

保留中文、字母、数字、下划线和连字符，其他字符替换为连字符；标题部分最多 60 字符。网页仍保留完整标题。单独 Search 使用研究方向，全流程 Search 使用全流程标题。创建后目录名固定，修改标题不会移动已有产物。历史及导入任务沿用原路径，列表、下载和恢复兼容旧编号。

Auto Table 的输入、日志目录也使用相同任务名。内部关联以实际任务记录为准，不从目录名称推断标题或任务状态。

## 数据与运行结构

```text
assets/output/workbench/
  auto_search/                 调研运行目录
  auto_design/tasks.json       实验任务索引
  auto_writing/                写作项目与上传、生成文件
```

Auto Design 的具体运行产物仍写入用户选定工作目录下的 `assets/output/auto_design/<任务标题>-design-<时间戳>/`；工作台索引记录其实际路径。现有独立模块的数据不自动复制到工作台；接续已有 Auto Design 实验使用页面里的导入功能。工程验收数据和日志写入 `assets/logs/workbench/`，不进入正常任务索引，也不提交到 Git。

三个模块均以独立任务目录作为 Codex 工作目录。Auto Search 使用 `auto_search/<任务标题>-search-<时间戳>/`；Auto Writing 使用 `auto_writing/<任务标题>-writing-<时间戳>/`；Auto Design 使用任务索引中已登记的 `run_dir`。Auto Design 的 `workspace` 继续表示用户选择的项目根目录，用于定位机器指令和创建任务目录，不再作为 Codex 的执行目录。已有目录及任务编号保留，正式实验命令继续使用执行计划和运行器规定的工作目录。

`python3 -m workbench` 启动独立网页入口及一个研究工作进程；入口在工作进程退出时仍保留首页、日志、启动与重启接口。研究工作进程内启动四个绑定到 `127.0.0.1` 临时端口的原模块 HTTP 服务，由入口按路径前缀转发请求。GET、HEAD、POST、PUT、DELETE、查询参数、上传请求体和二进制下载均由原模块处理；原 32 MB 请求上限保留。只在模块主页注入共享导航，生成的 HTML 报告维持原内容和相对资源路径。开发时可用 `python3 -m workbench.server` 直接运行工作进程，但此方式没有独立服务恢复入口。

前端只为 API 和下载地址增加模块前缀，因此独立启动时仍使用原路径。桌面与 390px 窄屏均可使用统一导航和原模块侧栏。

Auto Writing 默认传入 `--ignore-user-config`，与另外两个模块保持一致，避免本机全局 Codex 配置解析失败；不修改全局配置。确需读取自定义全局配置时设置 `CODEX_IGNORE_USER_CONFIG=0`。模型、推理强度、CLI 路径和 LaTeX 编译器仍由各模块原有参数控制。

## 验收记录

2026-09-05，Python 3.12 环境：

- 完整测试：**234 passed、4 skipped、3 subtests passed**。4 项跳过来自原 Auto Search 测试依赖的历史调研目录缺失；另有原依赖产生的 5 条 SWIG 弃用警告。
- 新增 HTTP 整合测试使用真实服务、文件与任务管理器，仅在模型调用边界使用明确标注的工程 fixture，覆盖各模块工作流、隔离存储、上传编辑、人工审核、取消、恢复与二进制下载。
- 三模块分别通过各自真实 Codex CLI 适配器返回预期结构；此项验证连接与调用兼容性，不代表科研输出质量验收。
- Auto Writing 原编译函数使用真实 `latexmk` 成功生成 **15,582 bytes** 的最小 PDF，并成功打包 LaTeX ZIP。
- 浏览器确认首页、三模块导航、调研表单、实验任务创建、写作文件上传与项目创建、六章节展示、依赖提示、下载链接和 390px 窄屏。页面宽度均为 390px，无横向溢出；控制台无 error/warn。
- Ruff 检查新增 Python 代码通过；五个新增或修改的 JavaScript 文件语法检查通过。

没有启动远端 GPU、科研训练或正式数据集评估。模型服务、网络和实际科研输入带来的运行结果仍以各模块执行日志及科学契约为准。

2026-09-06 统一任务执行目录后的回归为 **236 passed、4 skipped、3 subtests passed**。新增真实子进程验收覆盖两个调研任务的全部阶段，以及 Auto Design 的新建、导入和项目指令来源；详细结果与本轮目录变更见 [Round 4 开发记录](../docs/README.md)。

同日补充了文件预览入口与连接恢复处理：`node --test workbench/tests/test_file_entry.mjs` 的 5 项前端启动测试通过，并在 Edge 的 HTTP 页面确认三模块的新建表单及首页连接状态正常。这些前端开发测试使用 Node 内置测试工具，不增加工作台运行依赖。

复现自动测试：

```bash
python3 -m pip install -e '.[dev]'
PYTHONPATH=auto_search python3 -m pytest --import-mode=importlib tests auto_design/tests auto_search/tests auto_writing/tests workbench/tests -q
```

本机验收文件：

| 路径 | 内容 |
| --- | --- |
| `assets/logs/workbench/tests-final.log` | 完整回归结果 |
| `assets/logs/workbench/cli-smoke/summary.json` | 三模块真实 CLI 与 LaTeX 验收汇总 |
| `assets/logs/workbench/cli-smoke/` | 原始提示、返回、事件、编译日志与最小 PDF/ZIP |
| `assets/logs/workbench/ui-qa/` | 独立界面测试服务、任务与工程 fixture |
| `assets/logs/workbench/server.log` | 正常工作台服务日志 |

## 前端自动流程与恢复验收（2026-09-06）

新增全流程入口、Search 同目录恢复、Design 控制器中断、Writing 自动推进与单独 PDF 重编译，以及独立网页服务恢复入口。设计、使用方式和实现映射见 [前端全流程说明](../docs/frontend_workflow.md)。

全仓库回归为 **249 passed、4 skipped、3 subtests passed**；日志位于 `assets/logs/workbench/workflow-tests-final.log`。浏览器工程验收产物位于 `assets/logs/workbench/workflow-ui/`，正常任务索引保持独立。正式 8760 已运行新入口，可从首页恢复工作进程。没有运行真实科研实验。


## Auto Table 接入

`test-v1` 已合入 `auto_table` 分支，在原三个模块之外新增 `/auto-table/`，沿用相同导航、灰白/青绿色视觉系统和任务式交互。主页提供第四个入口；其他模块的完整流程保持可用。表格任务独立管理，在页面中可以上传论文 ZIP 或实验数据，也可复制已有 Auto Writing 的 LaTeX ZIP / PDF 开始整理。

表格后台使用 `auto_table.application.Application`，复用原编译器配置，设计与复核提示词随代码版本化；不依赖安装 Paper2Table Skill。表格任务状态纳入 `/api/runtime` 的 `active_tables` 与 `idle`，服务重启时会停止本任务的 Codex/编译进程并保留可恢复的进度。

源码、输入/输出目录、配置与 API 详见 [Auto Table](../auto_table/README.md)。工作台默认的表格状态目录为 `assets/output/workbench/auto_table/`。测试示例和实测验收项目与正常任务目录隔离，不自动填充网页示例任务。


首页全流程已接入 AutoTable：写作完整完成后复制 LaTeX ZIP 和 PDF 到独立表格任务，整理、编译、逐页复核通过后才结束流程。最终下载入口指向 AutoTable，原写作源码保留。没有表格的论文保持源码不变并编译复核，不自动添加表格。编译失败复用源码；复核不通过会阻塞流程，点击继续开启同任务下一轮并携带复核意见。替换论文模板会回到写作，并重新交接新的表格任务；此前的表格产物保留。历史已完成的三阶段流程不会自动启动额外工作，可从其 Writing 任务新建流程接续。

可选真实末段验收：`PYTHONPATH=src:auto_search .venv/bin/python3 -m workbench.tests.smoke_pipeline_live --serve`。它在独立的 `assets/output/pipeline-table-smoke/` 目录使用明确的调研、实验和写作工程响应，运行真实 TeX 编译及 AutoTable Codex 设计/复核，不启动科研 GPU。默认验收端口 8769；中断后使用 `--resume <原验收目录>`，保留原任务继续。
