# AutoResearch 开发交接

## 当前开发仓库

自 2026-10-16 起，本项目在 [yzbcs/Autoresearch](https://github.com/yzbcs/Autoresearch) 的 `main` 分支继续开发。本地 `origin` 指向该仓库，当前分支跟踪 `origin/main`；原 `wanghao1118/LL-AutoResearch` 保留为 `upstream`，用于查阅上游历史。日常 `git pull`、`git push` 使用自己的仓库。

迁移保留当前分支的提交历史、许可证、四模块工作台，以及本地尚未提交的任务目录命名修改和内测使用说明。本机 `assets/` 中的实验输入、输出、日志，`tmp/`、预览草稿及前端依赖和构建缓存留在本地，不作为源码上传。迁移后将 `test-v1` 重命名为 `main` 并设为 GitHub 默认分支；原本地上游 `main` 保留为 `codex/upstream-main`。其他本地分支和关联工作树保留原状。

当前分支为 `main`，已将 Auto Search、Auto Design、Auto Writing、Auto Table 整合到 [同一个工作台](http://127.0.0.1:8760/)。完整说明见 [workbench/README.md](../workbench/README.md)。启动命令为 `.venv/bin/python3 -m workbench --port 8760`，首页可明确启动四模块自动流程，模块页仍支持独立操作。设计、恢复语义与接口见 [前端全流程说明](frontend_workflow.md)。

此前的独立 Auto Design 已提交并推送到 GitHub：`49da8d80c738259bad1fb7b88668b945606878b7`，远端分支 [auto_design](https://github.com/wanghao1118/LL-AutoResearch/tree/auto_design)。该分支基于 `main` 的 `01615b8`；旧 `autodesign` 分支 `af51260` 是科学规则和运行工具的迁移来源。以下 Round 1、Round 2 记录其重构过程，Round 3 记录三模块整合。

## 当前代码与运行方式

- 新模块位于 [`auto_design/`](../auto_design/README.md)，不需要安装 AutoDesign Skills、React、Node 或 Codex SDK。
- Python 编排在 `orchestration.py`；CLI 调用和日志在 `codex_runner.py`；普通提示词位于 `prompts/`，路径注入在 `prompting.py`。
- 原有状态、结果单元校验、均值与样本标准差、设计目标对比和五阶段执行工具已迁入模块，原科学约束保持有效。
- 网页支持新建、仅设计、完整执行、旧运行导入、暂停、恢复、方法修改批准和真实结果浏览。
- 原仓库 `src/autoresearch` 与打包配置保持原样；旧分支和用户安装的 Skills 未修改。

本机使用已有 Python 3.11+ 虚拟环境启动：

```bash
.venv/bin/python3 -m auto_design serve --port 8767
```

访问 [本地 AutoDesign](http://127.0.0.1:8767/)。任务索引位于 `assets/output/auto_design/tasks.json`，服务日志位于 `assets/logs/auto_design_server.log`。启动服务不自动启动实验。

## 验证与产物

- 原 AutoResearch 测试和新模块测试合计 **139 passed**；测试记录：`assets/logs/auto_design_refactor/tests.log`。原依赖还输出 5 条 SWIG 类型弃用警告。
- Ruff 和 JavaScript 语法检查通过。
- 完整工作流测试用工程 fixture 覆盖设计、实际本地测试命令、结果摄取、诊断、独立审计和最终完成。
- 额外覆盖了仅设计不启动实验、暂停不继续派发、阶段内成功命令不重复运行、服务重启不自动重跑、Revision ID 匹配、拒绝后重新批准、已批准决定持续有效、修改次数上限、未关闭 iteration 不进入最终审计、HTTP 接口及真实子进程日志。
- 真实 Codex CLI 连接验收通过，返回 `outcome: completed`、`summary: CLI连接验收通过`、`next_action: none`。完整命令、时间、退出码和事件记录位于 `assets/logs/auto_design_refactor/cli-smoke-isolated/`。
- 浏览器确认了首页、任务表单、任务详情和空结果展示，控制台无 error/warn。界面验收任务明确标注“界面工程验收（不运行实验）”，全部放在 `assets/logs/auto_design_refactor/ui-qa/`，没有进入正常任务索引。
- 本轮没有启动科研模型训练、远端 GPU 实验或数据集评估，没有产生可用于科研结论的观测结果。

## 实验推进历程

### Round 1：统一系统组成方式

**设计动机。** Auto Search 与 Auto Writing 采用 Python 网页系统驱动 Codex CLI，而旧 AutoDesign 使用 Skills 和 Node/React 控制台。用户要求新建与另外两个模块并列的 `auto_design` 分支，统一工程结构。

**具体方案与关键参数。** 从 `main` 创建新分支，将旧分支的确定性工具迁入 `auto_design/`，把五个 Skills 的研究规则转成普通提示词，Python 根据持久化状态派发独立 CLI 调用。默认端口 8767；一个活动任务；编排模型默认延续 `gpt-5.6-sol`、`xhigh`。实验科学模型、数据、split、metrics、seeds 和 budget 仍由接受的设计决定。

**结果数据。** 139 项测试通过；真实 CLI 返回预期结构；原生网页接通本地真实 API。无科研实验结果。

**核心发现与失败原因。** 本机原全局 `config.toml` 在 CLI 启动时产生 `invalid type: map, expected a boolean in features`，已采用与 Auto Search 相同的 `--ignore-user-config` 隔离方式，保留当前登录认证，并未修改全局配置。失败日志保存在 `cli-smoke/`。新增完整流程测试曾因工程 fixture 漏写 `schema_version` 被正确拦截，补齐后通过。暂停接入暴露了阶段内命令恢复需求，已保留成功命令前缀以避免重复昂贵工作。

**下一步洞察。** 工程结构已经统一。后续若继续整合，应在三个模块之间增加明确的 Idea 选择、写作交接和真实结果更新入口。当前仍沿用文件交接；不需要先统一一套大型前端框架或重写科学契约。

### Round 2：统一三个模块的前端风格

**设计动机。** 用户查看 Auto Search 与 Auto Writing 的原版页面后，要求 AutoDesign 使用同样的视觉风格。

**具体方案与关键参数。** 复用 Auto Writing 的 The ThAInker Logo，以及两模块共有的字体、颜色、间距和控件样式。桌面顶栏为 70px、侧栏为 322px，主背景为 `#f4f6f7`，侧栏为 `#eef1f2`，主操作色为 `#087d70`。首页改为居中的实验入口；任务详情、状态标签、结果表、新建与导入弹窗使用统一样式。760px 以下采用可展开的侧栏，表单内容可滚动，底部操作保持可见。修改集中在 `auto_design/web/index.html`、`styles.css`、`app.js` 和品牌图片；Python 服务及实验编排没有改动。

**结果数据。** JavaScript 语法检查通过；浏览器确认首页、新建弹窗、已有任务概览、结果页和 390px 窄屏菜单可以使用。窄屏页面宽度与文档宽度均为 390px，没有页面横向溢出；控制台没有 error/warn。复用上一轮明确标注的界面验收任务，没有启动生成或实验，正常任务索引仍为空。

**核心发现与失败原因。** 原版 AutoDesign 的侧栏品牌、大标题和绿色底色与另外两个模块不同；统一顶栏品牌、灰色工作区和紧凑控件后，三个模块的外观已对齐。完整任务名称、路径和结果仍保留换行显示。

**下一步洞察。** 当前工程组成和视觉风格均已统一，后续可围绕真实任务继续打通三个模块间的文件交接。界面预览仍使用 [本地 AutoDesign](http://127.0.0.1:8767/)。

### Round 3：在 test-v1 整合完整三模块

**设计动机。** 用户要求先推送当前 `auto_design`，再新建 `test-v1`，把三个模块放入同一个前端入口，点击模块进入相应功能，保留全部能力。

**具体方案与关键参数。** 推送并核对 `auto_design` 远端提交后，从该提交创建 `test-v1`。完整引入 `origin/auto_search` 的 `3d28a34` 和 `origin/auto_writing` 的 `8aae3dc` 下对应模块，包括提示词、Schema、命令行入口、前后端和测试。新建 `workbench/`，公共端口为 8760，按 `/auto-search/`、`/auto-design/`、`/auto-writing/` 转发到三个原模块 HTTP 服务；模块页共享导航，原业务处理器和任务管理器继续工作。请求体、查询参数、PUT 编辑、DELETE、文件及 ZIP/PDF 下载均透传，HTML 报告不注入导航。默认运行数据位于 `assets/output/workbench/`，Auto Design 实际产物目录保留原约定。新增 `run_workbench.ps1`，原独立启动方式继续保留。

**结果数据。** 原仓库、三个模块及新增整合测试共 **234 passed、4 skipped、3 subtests passed**，耗时 18.83 秒。跳过项均来自原测试依赖的历史调研目录缺失，5 条 warning 来自原 SWIG 依赖。三个真实 Codex CLI 适配器均成功返回预期结构。Auto Writing 使用真实 `latexmk` 生成 15,582 bytes 的最小 PDF，并生成 LaTeX ZIP。浏览器验证了模块跳转、调研表单、仅设计任务创建、写作文件上传与创建、六章节及依赖提示、下载链接；工作台与三模块在 390px 下均无页面横向溢出，控制台没有 error/warn。Ruff 和五个 JavaScript 文件语法检查通过。日志见 `assets/logs/workbench/tests-final.log`、`cli-smoke/summary.json` 和 `ui-qa/`。工程 fixture 与正常任务分离，本轮没有科研实验结果。

**核心发现与失败原因。** 页面原先使用根路径 API，直接合并会使请求和下载进入错误模块，现按模块前缀统一生成地址，并保留单模块运行路径。跨模块完整流程测试还暴露了 Auto Search 在英文 Idea 中漏读 `Root-Cause Analysis` 与 `Cause` 的问题，现同时识别中英文标题。Auto Search 健康接口原先固定声称 CLI 已配置，现根据实际发现结果返回。Auto Writing 原先读取本机不兼容的全局 Codex 配置，现默认与其他模块一样隔离该配置，并保留 `CODEX_IGNORE_USER_CONFIG=0` 的显式选项。首次整合测试另有一处工程 fixture 把拒绝修改后的正确状态 `paused` 写成 `waiting_review`，已纠正预期；业务拒绝语义没有改变。

**下一步洞察。** 统一入口已能复用完整原功能，未引入第二套业务状态。实际使用可从调研模块选择 Idea，再通过文档交给实验模块，最后将真实实验说明和产物上传到写作模块。若将来增加“一键交接”，应明确传递用户选中的 Idea 和真实结果文件，继续保留各阶段的显式启动及科学批准边界；本轮不自动发起这些研究步骤。

### Round 4：统一每个任务的 Codex 执行目录

**设计动机。** 用户核查新建任务的默认目录后，希望 Auto Search 使用与 Auto Writing 相同的任务目录方式，并询问 Auto Design 是否也应统一。代码确认：Auto Search 原先固定 `--cd` 到源码目录；Auto Design 虽已为每个任务创建独立 `run_dir`，但调用 Codex 时仍传入项目根目录 `workspace`。

**具体方案与关键参数。** Auto Search 将任务目录逐层传入调研、Idea 生成和评审函数，同时设置 Codex 的 `--cd` 和子进程 `cwd`。网页继续自动创建 `direction-<时间戳>-<ID>` 目录；批量 CLI 使用已有 `--run-dir`，单篇 Weakness CLI 使用输出文件所在目录。Auto Design 将各阶段 Codex 调用改到已登记的 `run_dir`，`workspace` 保留为项目根目录及机器指令来源，页面字段同步改为“项目根目录”和“任务工作目录”。提示词、Schema 和确定性工具仍按源码绝对路径读取。已有任务编号、目录和产物不迁移，科学契约及实际实验命令的目录约定没有改变。

**结果数据。** 2026-09-06 完整回归为 **236 passed、4 skipped、3 subtests passed**，耗时 21.88 秒；4 个跳过项仍为历史调研数据缺失，另有 5 条原 SWIG 警告。新增工程验收通过真实子进程执行两个独立调研任务，每个任务覆盖调研、两次 Idea 生成和评审，共 8 次调用；各调用记录的实际当前目录与 `--cd` 均为所属任务目录。Auto Design 验证了两个新任务、一个导入任务，以及真实子进程的相对文件写入位置。测试日志为 `assets/logs/workbench/task-directories-full-tests.log`，没有科研训练或评测结果。

**核心发现与失败原因。** 执行目录切换还要求已发现的 CLI 可执行文件使用绝对路径，否则配置中的相对路径会在进入任务目录后失效；已在 Auto Search 和 Auto Design 的 CLI 定位函数中修复，并用相对 CLI 路径完成验收。修改过的 Auto Design 代码和整合测试通过 Ruff，JavaScript 语法及 diff 检查通过。Auto Search 四个相关文件在原提交已有 25 条 lint 提示，本轮逐项对比未新增，记录见 `assets/logs/workbench/task-directories-lint.json`。

**下一步洞察。** 三个模块的 Codex 工作目录现均对应独立任务目录；“项目根目录”负责组织项目和提供机器上下文，“任务工作目录”负责承载当前流程。后续跨模块交接可以直接引用任务目录里的真实产物，无需依赖源码目录作为执行起点。

### Round 5：处理本地文件预览的 Failed to fetch

**设计动机。** 用户再次报告页面显示 `Failed to fetch`。当前 Edge 标签打开的是本地 `auto_design/web/index.html`，而 8760 服务仍正常运行并返回任务接口成功响应。此前仅重新打开 HTTP 地址，没有在直接打开 HTML 的场景提供明确入口。

**具体方案与关键参数。** 四个前端入口在 `file:` 协议下展示对应的本地服务链接，并停止绑定任务操作和发起 API 请求。默认引导至 `http://127.0.0.1:8760/` 及对应模块路径；自定义端口使用启动终端显示的地址。工作台首页的 CSS 和 JavaScript 引用改为相对路径，保证文件预览能加载入口提示。Auto Design 在连接恢复后清除旧连接错误，同时保留正常连接期间的操作错误提示。

**结果数据。** Node 内置测试运行完整前端脚本，4 个文件入口均未发起 API 请求或启动轮询，另 1 项验证连接错误恢复及操作错误保留，共 **5 passed**。四个 JavaScript 文件语法检查及 diff 检查通过。Edge 的 HTTP 页面验证了 Auto Design、Auto Search、Auto Writing 新建表单及工作台首页，三个模块均显示服务已连接，控制台没有 error/warn。未创建研究任务或启动实验。

**核心发现与失败原因。** 本地 HTML 预览缺少 HTTP API 来源，不能作为运行中的程序入口；此前统一显示底层 fetch 错误，未向使用者说明正确入口。另一个显示问题是 Auto Design 的网络错误提示不会随连接恢复清除，现已修复。

**下一步洞察。** 日常打开工作台应使用服务 URL；文件预览只负责给出运行入口。后续交付页面继续直接展示 HTTP 服务地址，避免把源码文件链接作为应用入口。

### Round 6：前端恢复闭环与三模块自动交接（2026-09-06）

**设计动机。** 用户希望日常从前端启动全流程，中途卡住也能在网页处理并继续。原统一入口只有导航：Search 没有同任务恢复，Design 的安全暂停无法解除静默控制器，Writing 需要逐步点击，工作服务退出后网页也没有重启入口。

**具体方案与关键参数。** 新增 `workbench/pipeline.py` 持久化模块关联，首页统一提供全流程创建、起点选择、自动/手动选题、暂停、控制器停止、恢复说明、审批、日志与模板更换。自动选题沿用原 `evaluation.json` 排序，只选 `promising` 且未被人工废弃的 Idea。Search 在同目录复用 manifest、合格 Idea 与评审；Design 可中断本任务 CLI，保留实验训练，并在恢复前核对原执行；排队暂停不再等待前一个任务。Writing 自动执行 11 个原有步骤，首个失败处停止，显式继续只重试尚未完成的步骤；PDF 失败可只重新编译。`pipeline_id` 把模块任务与流程关联，恢复交接先查已有任务。实验到写作同时要求磁盘 COMPLETE、审计 PASS、证据与路线检查通过。默认 article 模板可替换为上传 ZIP。

`python3 -m workbench` 现在启动独立网页入口和研究工作进程。前端可查看服务日志、修正 CLI/编译器路径并重启工作进程；重启先停派发与控制器，45 秒未排空则保留服务。服务器重启不自动重跑研究，前端点击继续后接续原任务。详细接口、代码路径和边界见 [前端全流程说明](frontend_workflow.md)。

**结果数据。** 全仓库回归 **249 passed、4 skipped、3 subtests passed**，61.16 秒；5 条 warning 来自原 SWIG 依赖。日志：`assets/logs/workbench/workflow-tests-final.log`。新增 13 项工程测试覆盖 Search 保留进度与重启恢复、完整跨模块交接、人工选题与方法审批、伪完成拦截、写作单步重试、编译单独重试、静默 CLI 中断、排队暂停、交接中断去重、人工废弃不自动选中，以及独立入口在工作进程退出后的恢复。5 项文件入口/连接恢复测试与相关 JavaScript 语法检查通过，Ruff 的 E9/F 检查与 diff 检查通过。

浏览器在隔离目录 `assets/logs/workbench/workflow-ui/` 实际创建“工程验收：前端全流程（不含科研结果）”，完成手动选题、自动实验交接、自动写作、注入 Method 失败、网页填写说明并继续，最终进入对应论文的 LaTeX/PDF 下载页。桌面可操作，390px 首页与新建表单的文档宽度均为 390px；检查的页面没有控制台 error/warn。模型和编译响应使用明确标注的工程 fixture，产物只证明软件链路，不作为科研证据。

**核心发现与失败原因。** 新增负向测试暴露了旧交接函数在“等待方法审批”状态会返回 revision：因此不能只检查任务标签或假设调用不抛错就已完成，自动交接现在显式确认磁盘 COMPLETE 且校验返回无后续动作。还修复了全局实验队列中第二个任务无法及时暂停的问题。工程排版 fixture 最初漏写 Abstract 和标准章节，被现有论文格式检查拦截，补全 fixture 后继续；两处旧测试的 subprocess 打桩路径同步到实际调用入口，未放宽检查。服务恢复后清除过期连接错误，创建请求处理中持续禁用提交，避免把恢复状态或重复请求误呈现给用户。

**当前执行现况。** 正式 <http://127.0.0.1:8760/> 已切换为独立入口，浏览器已实际操作空闲后台重启并恢复连接。切换前核对三模块任务列表为空；正常索引没有混入工程验收任务。没有启动远端 GPU、科研训练或正式评估，未提交或推送本轮代码。

**下一步洞察。** 日常推进与常见任务/工作进程故障已可在前端处理。真实科研链路下一步应使用用户选择的研究方向和既定资源运行，保留失败证据；不以本轮工程 fixture 宣称研究效果。账号重新登录、机器关闭、独立入口自身未启动，以及真实 GPU/网络资源不可用仍属于外部条件，不能由一个静态网页保证消除。


### Round 7：将 Paper2Table 重构为 Auto Table 系统模块（2026-09-06）

**设计动机。** 用户希望把 `goya4140/AutoTable` 的 Skill 能力接入 AutoResearch，采用与现有三个模块一致的系统代码、前端形式和配色，并交付到 `auto_table` 分支。用户随后要求先保存当前 `test-v1` 工作；该批源码与文档已提交为 `49bb2d14` 并推送。输入、日志、实验输出和临时文件保留在本机。

**具体方案与关键参数。** `auto_table` 从远端 `auto_writing` 的 `8aae3dc7` 创建，随后以 `b1bcb954` 合入已保存的 `test-v1` 三模块工作台。Paper2Table 引擎基于上游 `5c59714` / `0.11.0` 迁入 `auto_table/engine/`，保留 MIT 许可、七类模板、六类科学角色、原始观测与已报告汇总的区分。Skill 中的科学口径、保留数值/名称、层级与高亮规则转为 `prompts/system.md` 及设计/复核 Schema；运行不依赖安装 Skill。

后端使用持久化项目与五个阶段：读取 → 设计 → 生成/替换 → 编译 → 独立复核。支持论文 ZIP（可附 PDF）、结构化结果文件，以及从 Auto Writing 复制已生成论文。论文扫描扩展到静态 `\input{...}` / `\include{...}` 子文件，可显式选择主 TeX；按全工程唯一替换名定位表格，保留 label 和非表格正文。CSV/TSV/JSON/JSONL 保留逐次来源、mean、sample SD 与 n。Codex 在独立任务目录中返回结构化计划；服务器执行确定性代码与 LaTeX 编译。每轮产物与日志独立保存，失败只重试未完成步骤；重新设计保留前轮。状态只有在真实 PDF 生成且复核覆盖全部渲染页后才为 `ready`。

前端新增 `/auto-table/`、第四张首页卡片与所有模块的导航入口，使用同一灰白背景、青绿色操作、侧边项目列表、步骤进度、结果页和运行文件页。提供网页上传、要求修改、停止/继续、源码/PDF/ZIP 下载及实际 PDF 页面。Auto Table 任务纳入工作台的 `active_tables` / `idle` 和服务重启停止流程。原三个模块的自动研究顺序保持原有语义，表格整理可独立启动。

**结果数据。** 四模块完整回归为 **311 passed、4 skipped、3 subtests passed**，耗时 74.14 秒；跳过项仍是缺少历史调研样本，SWIG 警告沿用现有环境。文件预览入口 Node 测试为 **6 passed**。后续编译 manifest 同步修复的局部回归为 **8 passed**；新业务代码 Ruff、JavaScript 语法和 diff 检查通过。

真实 Codex 与 LaTeX 验收使用明确标注的合成工程数据，与正常任务索引隔离。数据制表任务 `table-c1266d26c97a` 从 16 个指标观测生成 8 个单元格，保留 2 次运行的均值和样本 SD，产出 1 页 PDF 并复核通过。论文任务 `table-45b1054e273a` 由网页实际上传 ZIP 启动，在 `sections/results.tex` 中发现、替换 2 张表格，保留正文、标签、数值与不确定性，产出 1 页论文 PDF 并复核通过。桌面布局、手机 390px 页面和文件下载入口已在浏览器核对；390px 文档宽度为 390px。上述为软件验收，不是本次产生的科学实验结果。

可核查记录：`assets/logs/auto_table/full-tests.xml`、`targeted-tests.xml`、`live-results.json`、`live-manuscript.json`；真实任务输入、提示词、CLI 日志、表格、PDF 和复核记录在 `assets/output/auto_table/qa-workspace/assets/`。它们不提交 Git，也不填充正常使用的项目列表。可用 `auto_table/tests/smoke_live.py` 显式重跑真实工具验收。

**核心发现与失败原因。** 原 Skill 的论文工具只扫描主文件，系统上传常见分文件工程时会漏表；现已支持静态子文件和主文件选择。异步上传表单在等待 API 后必须保留 form 引用，否则不能可靠执行后续启动；已修正并通过真实网页上传。编译阶段需同步更新 manifest 的 PDF/编译器字段，避免产物已生成但记录仍显示未编译；已加入回归。负面复核、编译错误、取消和重启恢复均有持久化状态测试，未用样例状态替代实际后端。

**下一步洞察。** 模块现可接续实际论文或实验结果进入使用。完整 LaTeX 解析并非当前范围：动态宏构造的引用需提供可直接解析的工程；特殊模板依赖仍需安装并选择相应编译器。独立复核是 Agent 判断，数值规格验证不是科学结论认证，原始输入与来源记录持续保留以便人工核对。未来应根据实际论文中的具体失败扩展支持，而不是预先堆叠兼容层。

### Round 8：在 test-v1 接通 AutoTable 全流程（2026-09-06）

**设计动机。** 用户要求切回 `test-v1`，确认 AutoTable 已接入，并把首页 Pipeline 的自动交接推进到表格整理和最终交付。原远端 `test-v1` 停留在 `49bb2d14`，本轮先将其快进到 `auto_table` 的 `599ed0dc`，再补齐第四阶段。

**具体方案与关键参数。** Pipeline 顺序为 Search → Design → Writing → Table。原选题与实验科学门槛保持有效；写作步骤完整且仍有效后，复制 LaTeX ZIP 和已就绪 PDF，表格任务创建时一次保存 `pipeline_id` 与 `writing_project_id`。重启或交接中断后复用原任务。表格整理、编译、所有 PDF 页面的复核通过后才标记流程完成。暂停会停止本表格任务的当前步骤；编译失败复用源码，复核不通过时显式继续会在原任务开启下一轮并带入复核意见。无表格的论文保持源码不变，仍编译并复核。更新写作模板会回到 Writing，并重新交接后续表格任务，旧产物保留。历史三阶段已完成流程不自动追加执行。

首页展示四个阶段、AutoTable 项目直达链接与当前表格诊断；最终下载入口指向表格任务。独立模块入口继续可用。另修复 Writing 的重编译交付：用修复后的源码重新生成 ZIP，使下载源码与新 PDF 一致。

**结果数据。** 四模块完整回归 **313 passed、4 skipped、3 subtests passed**，耗时 86.58 秒；记录在 `assets/logs/pipeline-table/tests.xml`。之后修复 ZIP 同步问题，相关写作失败恢复回归 **1 passed**，记录在 `assets/logs/pipeline-table/recompile-regression.xml`。文件预览 Node 测试 **6 passed**。工程回归覆盖四模块交接、PDF 实际下载、编译失败复用、审阅否决阻止完成、同任务重新设计、模板重置与中断恢复不重复创建。

**核心发现与失败原因。** 第一次真实末段验收使用的写作工程样例漏写 BibTeX 样式及引用命令，真实 latexmk 正确报错；补齐样例后恢复发现 PDF 更新而 ZIP 未更新，AutoTable 因而再次编译旧源码失败。该问题已修复并加入测试。失败现场保存在 `assets/output/pipeline-table-smoke/20260906-160650/`。后续验收从完整四阶段重新运行，以真实 TeX 与 AutoTable CLI 验证新交接；调研、实验和写作内容仍明确标为工程响应，不构成科研结果。

**真实末段与当前运行现况。** 新验收 `flow-3131ac5af603` 已达到 `completed`，对应表格任务 `table-3d5404a73952` 的五步均完成、复核 `passed: true`。真实 latexmk 输出 2 页 PDF，独立 Codex 复核确认 Baseline 81.0、Candidate 85.0 与输入一致，标题、标签、正文和参考文献保留。最终汇总在 `assets/output/pipeline-table-smoke/20260906-161039/summary.json`；PDF、LaTeX ZIP、替换表格、逐页 PNG 和 `deliverables.zip` 位于该目录下 `assets/output/workbench/auto_table/table-3d5404a73952/attempt-1/`。浏览器已验证四阶段完成状态、AutoTable 项目直达、PDF 与源码下载入口。常用 `http://127.0.0.1:8760/` 已重载当前 `test-v1` 代码，四模块均已连接；正常任务列表没有混入工程样例。

**下一步洞察。** 表格模块已经成为交付链路的一部分，后续真实论文使用应保留现有失败恢复与科学审批边界；任何正式科研效果仍需对应设计契约下的真实实验和独立审计，工程验收不替代这些证据。
