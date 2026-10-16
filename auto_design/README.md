# Auto Design

AutoResearch 的实验设计与执行模块。原生 HTML/CSS/JavaScript 前端通过 Python 标准库服务调用 Codex CLI，完成设计、R0、执行、诊断和审计。无需安装 AutoDesign Skills，也不依赖 Node、React 或 Codex SDK。

`auto_design` 分支从仓库 `main` 创建。科学规则和确定性工具迁自 `autodesign` 分支的 `af51260`；原 AutoResearch 包、命令和目录继续保留。旧 `autodesign` 分支及用户已经安装的 Skills 不受这个模块影响。

## 启动

需要 Python 3.11 或更高版本，以及已安装、已登录的 Codex CLI。模块服务本身只使用 Python 标准库；具体实验依赖仍由每次运行的 `generated_project/environment.yml` 声明。

在仓库根目录运行：

```bash
python3 -m auto_design serve --port 8767
```

如果系统 `python3` 版本较旧，可使用已有的 Python 3.11+ 虚拟环境：

```bash
.venv/bin/python3 -m auto_design serve --port 8767
```

直接启动脚本也可以：

```bash
python3 auto_design/web/serve.py --port 8767 --workspace /absolute/path/to/project
```

Windows PowerShell：

```powershell
cd auto_design
.\run_web.ps1 -Port 8767 -Workspace C:\research\project
```

打开 [http://127.0.0.1:8767/](http://127.0.0.1:8767/)。默认端口与 Auto Search 的 8765、Auto Writing 的 8766 分开。无需 npm 安装或前端构建。

## 使用

1. 新建任务，填写项目绝对路径，粘贴或读取包含 Motivation 与 Contribution 的 Idea；Benchmark 可选，已经给出的科学约束原样保留。
2. 选择完整流程，或仅设计。创建只保存输入，点击“开始执行”才调用 Codex。
3. Python 分别派发 `design`、`run`、`diagnosis`、`audit`。每一步运行一个独立的 `codex exec --ephemeral` 进程，通过运行目录中的文件交接。
4. 需要 R0 时，`run` 只运行已注册探测，再回到 `design`。仅设计模式在发布设计后停止，点击“开始实验”才授权 R0 或完整执行。
5. 普通执行故障由执行步骤按原有边界修复规则处理。方法修改先生成完整中文提案和 Revision ID，网页收到明确决定后才允许继续。批准记录对后续恢复持续有效。
6. 查看真实执行记录、逐 seed 结果、汇总、诊断和报告。尚无结果时显示空状态；目标模拟值不进入结果表。

Auto Search 的 `PASS:` 文档表示放弃方案，创建入口会拒绝把它当作实验 Idea。

## 暂停和恢复

“安全暂停”写入当前运行的 `pause_requested.json`。本地命令执行器在每条新命令前检查它；执行提示词也要求在每个实验单元边界检查。当前单元自然完成并收集结果后暂停，不终止训练或重置 GPU。

“停止卡住的控制器”会停止本任务的 Codex CLI，保留训练进程和已有产物。它不等同于终止训练；恢复仍需核对原执行。排队中的任务可以直接暂停，无需等待前一个实验结束。

点击“继续执行”可附带恢复说明，会启动新的 CLI 会话，读取原状态、错误、执行记录、在途进程和实际产物。当前命令计划中已经成功的前缀继续复用，包括同一阶段内部已经成功的命令。

服务重启后，原来的活动任务显示为暂停。继续前先核对旧进程和已有结果，不能因 CLI 断线就重新启动同一个实验。暂停依赖执行器和 agent 在边界读取标记，不保证任意第三方脚本立即停止调度。

“接续已有实验”只读取并登记包含 `AUTODESIGN_STATE.md` 的目录，不自动执行。可以接续原 AutoDesign 运行，不要求 Codex thread ID；原状态中的 `Next Skill` 标签仅在后续明确写入状态时改为 `Next action`。

## 目录与职责

```text
auto_design/
  web/
    serve.py                 HTTP API 和静态页面服务
    index.html               页面结构
    styles.css               页面样式
    app.js                   原生前端交互
  orchestration.py           任务、队列、步骤派发、暂停、恢复和审核
  codex_runner.py            Codex CLI 子进程与完整调用日志
  prompting.py               普通提示词装载、运行路径注入
  prompts/
    workflow.md              跨阶段研究规则与总流程
    design.md                实验设计与修改规则
    run.md                   R0、实现、执行与恢复规则
    diagnosis.md             结果解释与迭代路线
    audit.md                 独立审计规则
    action.md                Python 与 agent 的当前步骤交接约定
    references/              原有科学和产物契约
  schemas/action.schema.json agent 返回结构
  state.py                   AUTODESIGN_STATE.md 与状态门
  runner.py                  五阶段本地命令执行与恢复
  results.py                 结果单元完整性与确定性聚合
  effects.py                 设计结构校验与观测目标对比
  io.py                      产物读写工具
  cli.py                     命令入口
  scripts/run_stage.py       单条命令执行记录器
  tests/                     原有科学契约测试与新增应用测试
  run_web.ps1                Windows 启动入口
```

修改某个研究步骤的内容，编辑对应的 `prompts/*.md`；修改步骤顺序、任务状态或人工入口，编辑 `orchestration.py`；修改输入输出结构校验，编辑确定性工具。提示词是模块自带的普通文件，不需要安装或发现 Skills。

## 运行目录

任务索引默认保存到启动工作区的 `assets/output/auto_design/tasks.json`。每个新实验在所选项目内创建独立目录：

```text
<workspace>/assets/output/auto_design/<任务标题>-design-<时间戳>/
  idea.md
  input_brief.md
  AUTODESIGN_STATE.md
  experiment_design.md
  expected_effects.json
  r0_plan.md
  r0_record.json
  generated_project/
  implementation_notes.md
  command_plan.json
  experiment_schedule.json
  result_contract.json
  execution_record.json
  raw_results.json
  result_summary.json
  effect_comparison.md
  result_diagnosis.md
  result_route.md
  integrity_audit.md
  reports/
  assets/logs/<attempt>-<action>/
    prompt.txt
    events.jsonl
    stderr.log
    execution.json
    response.json
```

R0 文件仅在需要时生成。方法修改文件、决策历史与恢复记录按实际断点生成。单次 CLI 调用记录工作目录、完整命令、进程 ID、开始结束时间和退出状态。

新建实验目录使用“任务标题-design-时间戳”，保留中文，空白和路径特殊字符替换为连字符，标题部分最多 60 字符；同名任务分别保存。内部任务编号保持稳定，已有及导入任务不改名，始终以索引中的 `run_dir` 为准。

新建表单中的“实验项目根目录”决定任务目录的存放位置和机器指令来源。每个任务的 Codex 调用在自己的 `run_dir` 中执行，设计、执行编排、诊断与审计均使用该目录。导入任务使用已登记的原运行目录，不移动已有产物。提示词、Schema 与确定性工具通过绝对路径读取；实际实验命令的工作目录仍按已登记的执行计划和运行器约定处理。

## 模型、机器与资源

| 环境变量 | 用途 |
| --- | --- |
| `CODEX_CLI` | Codex 可执行文件路径，默认从 PATH 查找 |
| `CODEX_MODEL` | 编排模型，默认延续旧控制台的 `gpt-5.6-sol` |
| `CODEX_REASONING_EFFORT` | 推理强度，默认 `xhigh` |
| `AUTODESIGN_PYTHON` | PowerShell 启动脚本使用的 Python 路径 |

CLI 使用 `--ignore-user-config` 隔离全局 `config.toml`，认证仍使用当前 Codex 登录。机器上下文仍从实际工作区和用户的 `AGENTS.md`/`CLAUDE.md` 读取，不写入 Python GPU 配置。实验模型、数据、split、metrics、seeds 和 budget 继续由已接受的科学契约决定，与这里的编排模型设置分开。

服务一次推进一个实验任务。完整实验的 GPU 分配和并行上限仍由机器指令与当前 `command_plan.json` 约束。

## HTTP 接口

| 方法与路径 | 行为 |
| --- | --- |
| `GET /api/health` | 服务、CLI 路径和默认工作目录 |
| `GET /api/tasks` | 真实任务列表 |
| `POST /api/tasks` | 保存新任务：`title`、`idea`、`workspace`、`scope` |
| `POST /api/tasks/import` | 登记已有运行：`title`、`run_dir`、`workspace` |
| `GET /api/tasks/<id>` | 任务详情、文档、执行记录和结果 |
| `POST /api/tasks/<id>/start` | 启动或恢复；可显式将 `scope` 改为 `full` |
| `POST /api/tasks/<id>/pause` | 请求安全暂停 |
| `POST /api/tasks/<id>/decision` | 记录指定 `revision_id` 的明确 `decision` |
| `GET /api/tasks/<id>/files/<relative-path>` | 读取当前运行目录中的产物 |

## 验证

```bash
.venv/bin/python3 -m pytest auto_design/tests -q
.venv/bin/ruff check auto_design
node --check auto_design/web/app.js
```

Node 只用于可选的 JavaScript 语法检查，运行服务不需要 Node。测试使用明确标注的工程 fixture，不启动科研模型训练或远端 GPU 实验。真实 CLI 连接验收也只检查结构化返回，不产生科学结果。当前交付证据见 [docs/README.md](../docs/README.md)。

工作台已支持 Search → Design → Writing 自动文件交接和来源记录，见 [前端全流程说明](../docs/frontend_workflow.md)。单模块运行仍保留独立任务。
