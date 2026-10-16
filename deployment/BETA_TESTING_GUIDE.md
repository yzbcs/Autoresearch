# AutoResearch 内测使用说明

本文面向通过个人电脑连接远程服务器的内测用户。内测用户只需要在自己的电脑上建立 SSH 隧道，然后用浏览器访问本机地址；代码、模型调用和任务数据都运行在服务器上。

## 1. 开始前需要准备

- 一台可以运行 `ssh` 的电脑（macOS、Linux 或 Windows PowerShell 均可）。
- 服务器管理员提供的 SSH 用户名、服务器地址、SSH 端口和登录认证。
- 浏览器（Chrome、Edge 或 Firefox）。

内测用户不需要克隆 GitHub 仓库、不需要安装 Python/Node，也不要在浏览器中直接打开服务器文件。每位用户使用同一个内测服务，请在提交任务前确认当前服务是否允许进行新的长任务。

## 2. 连接内测页面

先在本机终端执行下面的命令，并保持这个终端窗口运行：

```bash
ssh -N -p 45017 \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -L 18760:127.0.0.1:8760 \
  root@connect.westd.seetacloud.com
```

如果管理员为你提供了不同的账号或地址，只替换命令最后的 SSH 目标；`18760` 是你电脑上的本机端口，`8760` 是服务器上的工作台端口。

看到 SSH 认证成功且命令持续运行后，在浏览器打开：

```text
http://127.0.0.1:18760/
```

关闭终端中的 SSH 进程会断开页面连接；重新执行同一条命令即可恢复。不要把 `127.0.0.1:8760` 直接暴露到公网，也不要把 SSH 窗口关闭后再使用页面。

## 3. 首页和连接状态

首页是四个模块的统一入口：Auto Search、Auto Design、Auto Writing、Auto Table。页面显示“服务已连接”后再开始操作。

如果页面打不开，先检查：SSH 命令是否仍在运行、浏览器地址是否为 `127.0.0.1:18760`、本机的 `18760` 端口是否被其他程序占用。若页面能打开但显示服务未连接，等待几秒后刷新；仍未恢复时联系管理员，不要重复启动多个服务器服务。

## 4. 各模块怎么使用

### Auto Search：调研和选题

输入研究方向后创建调研任务，按页面提示等待检索、论文整理、Weakness 提取和 Idea 生成。完成后先阅读论文证据、领域图谱、Gap 和候选 Idea，再进行人工通过或废弃。搜索任务的结果应以页面中的证据和报告为准，不要只依据模型生成的摘要。

### Auto Design：实验设计和执行

可以从 Search 通过的 Idea 创建任务，也可以独立粘贴 Idea 或上传输入文件。先运行设计阶段，检查方法、数据、指标和资源约束；确认后再开始正式实验。实验运行期间可以查看日志、暂停、恢复或重试。GPU 实验可能持续较长时间，请不要在未确认任务状态前重复点击启动。

### Auto Writing：论文写作和 PDF

创建写作项目并上传论文资料或模板，按 Introduction、Related Work、方法、实验、结果和结论等步骤推进。每个章节完成后先检查引用、数值和证据，再继续下一步。最终可下载 LaTeX 源码、ZIP 和 PDF。

### Auto Table：论文表格整理

上传论文 ZIP、实验数据，或从已完成的 Writing 项目接续。先让系统规划表格，再检查表格中的实验名称、数值、单位和来源；确认后编译并执行复核。最终下载表格源码和 PDF。表格整理不会替换原始实验结果，发现数值不一致时应停止并反馈。

首页的“新建全流程”可以把 Search → Design → Writing → Table 串起来。任何阶段失败时，保留当前任务并从页面的恢复入口继续，不要删除任务目录后重新提交同一任务。

## 5. 产物在哪里

所有产物保存在服务器项目目录：

```text
/root/autodl-tmp/yzb/autoresearch/
```

主要位置如下：

| 内容 | 服务器路径 |
| --- | --- |
| 工作台任务索引、状态和恢复数据 | `assets/output/workbench/` |
| Auto Search 调研任务 | `assets/output/workbench/auto_search/` |
| Auto Design 任务索引 | `assets/output/workbench/auto_design/tasks.json` |
| Auto Design 具体任务 | 任务索引中记录的 `run_dir`，通常为 `assets/output/auto_design/<task-id>/` |
| Auto Writing 项目 | `assets/output/workbench/auto_writing/` |
| Auto Table 项目 | `assets/output/workbench/auto_table/` |
| 工作台入口和模块日志 | `assets/logs/workbench/` |
| 服务启动日志 | `deployment/workbench.log` |
| 工作进程日志 | `assets/logs/workbench/service.log` |
| 服务器环境和部署说明 | `deployment/` |

任务目录内常见文件包括输入 brief、提示词、JSON 结果、Markdown 报告、LaTeX 源码、PDF、执行日志和恢复记录。以页面显示的任务详情和任务索引中的实际路径为准；不要根据任务名称猜测路径，也不要手动移动或改名任务目录。

## 6. 内测反馈建议

反馈时请提供模块、任务名称或 task ID、操作步骤、页面错误信息、发生时间，以及 `assets/logs/workbench/` 中对应日志的文件名。若涉及结果质量，请同时指出原始输入、页面输出和你认为不正确的具体位置。不要在反馈中粘贴 Codex token、服务器认证信息或其他用户的任务内容。

## 7. 常见情况

- 页面显示任务运行中：先查看日志和任务状态；不要重复启动同一任务。
- 页面刷新后任务还在：这是正常的，任务状态保存在服务器，刷新不会自动停止任务。
- SSH 断开：任务通常仍由服务器保留；重新建立 SSH 隧道后刷新页面确认状态。
- PDF 生成失败：保留任务和日志，记录失败步骤；管理员会检查 Tectonic/LaTeX 日志。
- Codex 连接失败：先确认页面仍显示服务已连接，再联系管理员检查服务器端 Codex 配置；内测用户不需要修改项目代码或凭证。

内测结束后请在页面中停止或安全暂停仍在运行的任务，并向管理员提交反馈。服务器上的正式任务、实验结果和研究数据由管理员统一归档。
