# AutoResearch 服务器账号版部署

当前安装目录为 `/root/autodl-tmp/yzb/autoresearch`，Python 使用项目现有的 `.conda-env/bin/python3`。工作台数据目录为 `assets/output/workbench/`，账号库位于该目录下的 `accounts.sqlite3`。

## 启动与访问

在服务器执行启动脚本。守护程序会后台运行，重复启动会通过文件锁合并到同一实例。

```bash
bash /root/autodl-tmp/yzb/autoresearch/deployment/start.sh
```

默认监听服务器 `127.0.0.1:8760`。在个人电脑建立 SSH 隧道后，用浏览器打开 `http://127.0.0.1:18760/`。

```bash
ssh -N -S none -p 54025 \
  -o StrictHostKeyChecking=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -L 127.0.0.1:18760:127.0.0.1:8760 \
  -R 127.0.0.1:0:127.0.0.1:7890 \
  root@connect.westd.seetacloud.com
```

每位成员在自己的电脑开启 HTTP 代理后运行上述命令，`7890` 替换为本人实际代理端口。SSH 自动分配服务器端反向转发端口，成员之间无需协调端口。`-S none` 为本次访问建立独立 SSH 连接。请保持代理程序和 SSH 终端在线。登录后从账号菜单打开“本机代理连接”，可以测试真实 Codex 模型与命令工具。

服务器已创建管理员 `admin` 并绑定历史科研目录，新成员注册后获得独立工作空间。

当前连接代理模式通过上述 SSH 隧道识别访问设备。手机与外网网页入口需要另行接入访问服务，并设计相应的代理会话绑定。现有 6006、6007、6008 端口已有服务，本轮入口使用 8760。HTTPS 代理应保留浏览器请求的 Host，包含显式端口，并将 `AUTORESEARCH_SECURE_COOKIES=1` 传给工作台入口。

## 本轮适配

| 项目 | 当前实现 |
| --- | --- |
| 服务器 Python | 使用项目现有 Python 3.12 |
| 启动守护 | 用匿名可访问的 `/api/auth/session` 检查登录入口健康 |
| 科研进程 | 各账号从自己的页面管理研究进程与任务恢复 |
| 科研文件 | 绑定服务器原有 `workspace` 和 `data-dir` |
| 原服务修复 | 增量更新账号相关文件，校验其余 25 个已修改源码文件 |
| 账号迁移 | 通过 SQLite backup API 生成并导入账号库快照，本次快照包含 0 个用户 |
| Codex | 已安装 0.167.2，凭据位于项目 `.cache/codex`，网络出口按当前 SSH 连接分配 |

`deployment/env.sh` 管理项目路径、缓存、编译器和统一 Codex 入口。可用 `AUTORESEARCH_CODEX_CLI` 指定 CLI。所有新写入目录均在本项目内。Codex 的本地状态和文件登录凭据随 `CODEX_HOME` 定位，相关行为依据官方文档。[配置与状态目录](https://learn.chatgpt.com/docs/config-file/config-advanced) · [认证](https://learn.chatgpt.com/docs/auth)

## Codex 与绘图环境恢复

2026-11-12 已复用 `/root/autodl-tmp/wh` 中的 Codex 0.167.2 和现有 ChatGPT 登录，在本项目建立独立运行副本。凭据文件权限为 `0600`，凭据目录权限为 `0700`。团队各账号通过共享的服务配置使用该后端。

| 组件 | 服务器项目内相对路径 |
| --- | --- |
| Codex 入口 | `.tools/codex/bin/codex` |
| CLI 原生程序与 Code Mode Host | `.tools/codex/libexec/` |
| 公共启动包装 | `deployment/ycodex`、`deployment/tools/codex` |
| 登录凭据 | `.cache/codex/auth.json` |
| 绘图 Python 3.12.14 | `.venv-figurecrafter/bin/python` |
| LibreOffice 26.8.2.2 | `.tools/libreoffice/opt/libreoffice26.8/program/soffice` |
| 无桌面渲染入口 | `deployment/tools/soffice` |
| 原绘图环境备份 | `assets/output/backend-restoration/python-env-backup/` |

独立绘图环境安装 `auto_figure/requirements.txt` 和 CairoSVG。平台 `.conda-env` 补充 Pillow 与 CairoSVG，供案例图输入和 SVG 处理使用。LibreOffice 官方 Linux 包解压到项目 `.tools/`，通过 `svp` 无桌面模式运行，临时文件沿用绘图执行器的项目内写入目录。绘图子进程可从现有 PATH 发现 Codex 和 LibreOffice。

验收通过 **37 项** Figure、写入边界和 Table → Figure 流程测试，实际生成了可编辑 PPTX、PDF 与 PNG。绘图子进程在项目写入边界内调用真实 `gpt-6-astra`，成功识别渲染图中的 `Input`、`Output` 标签。该记录用于工程运行验收，科研任务的绘图与审核仍按各自任务合同执行。

服务器当前没有运行中的 Clash/Mihomo，服务器 `127.0.0.1:7890` 未监听。平台已采用每位访问者通过 SSH 提供本机代理的方案。此前的 120 秒、180 秒及后续 300 秒 CLI 超时记录已保留。显式配置 ChatGPT SSE provider 后，真实 Codex 命令读取随机文件及 AutoTable 模型调用均通过验证。代理连接模式的启动包装关闭无限连接重试，并优先使用当前任务对应的代理。SSE 传输配置依据官方配置参考。[Codex 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)

```bash
cd /root/autodl-tmp/yzb/autoresearch
source deployment/env.sh
deployment/tools/codex --version
deployment/tools/codex login status
.venv-figurecrafter/bin/python --version
deployment/tools/soffice --headless --version
```

验收清单位于 `assets/output/backend-restoration/restoration.json`，绘图样例位于同目录的 `drawing-smoke/`，测试与模型调用记录位于 `assets/logs/backend-restoration/`。

## 按 SSH 连接分配代理

`deployment/env.sh` 中的 `AUTORESEARCH_CONNECTION_PROXY=1` 启用本模式。默认开发启动继续使用原有环境配置。

1. 登录入口通过 Linux `/proc` 中的 TCP 连接与 SSH 进程文件描述符，找到网页请求所属的 SSH 连接及其反向转发端口。
2. 每条 SSH 连接获得独立的本地代理中继。中继在接入时核对原 SSH 进程身份和监听 socket，连接失效后拒绝新的请求。
3. 入口覆盖客户端提供的连接标头，通过研究进程的内部认证标头传递实际连接标识。后台线程捕获该请求的连接上下文。
4. 每次模型调用前，研究进程通过内部连接接口获取该连接的代理地址，清除继承的公共代理变量，再启动 Codex。FigureCrafter 子进程也携带此连接标识。
5. 全流程任务保存发起连接标识，自动跨模块交接沿用该连接。用户重新建立 SSH 并点击继续后，后续任务使用新连接。离线编译和本地渲染独立于代理可用状态。

同一账号可以同时从不同 SSH 连接发起任务，各任务使用发起时的连接。Codex 登录身份和调用额度由服务器统一配置。隧道断开时，网页中的任务记录和产物继续保存在服务器，模型调用会报错并支持重新连接后继续。

| 文件 | 职责 |
| --- | --- |
| `workbench/connection_proxy.py` | SSH 识别、独立中继和真实 Codex 连接测试 |
| `workbench/connection_context.py` | HTTP 请求上下文、后台线程与模型子进程环境 |
| `workbench/supervisor.py` | 当前连接状态、内部连接接口、可信标头 |
| `workbench/pipeline.py` | 自动交接和继续任务时的连接归属 |
| `deployment/ycodex` | 当前任务代理、SSE 和有限重试配置 |

最终回归 **184 项通过**，正式入口已启用连接代理并完成真实 Codex 命令读取校验。相关记录位于 `assets/logs/connection-proxy/` 与 `assets/output/connection-proxy/`。双连接验收在同一台电脑上模拟两个客户端，第二条连接指向返回 HTTP 407 的测试代理，用于核验失败请求的归属。关闭第二条 SSH 连接后，内部接口拒绝该失效连接，正常连接继续保持独立。

图片适配器的新连接复验两次遇到 `Selected model is at capacity` 并超时，当前记录为容量受限。独立绘图 Python、实际 PPTX/PDF/PNG 渲染以及绘图回归测试已通过，图片模型调用需要在容量恢复后再次核验。

## 日志、备份与验证

| 位置 | 内容 |
| --- | --- |
| `assets/logs/workbench/gateway.log` | 登录入口日志，权限为 `0600` |
| `assets/logs/workbench/guard.log` | 入口守护日志 |
| `assets/output/workbench/runtime/` | 守护锁和 PID |
| `assets/logs/account-deployment/tests.xml` | 26 项服务器测试的 JUnit 记录 |
| `assets/logs/account-deployment/tests.log` | 完整测试输出 |
| `assets/output/account-deployment/backup/` | 本轮覆盖前的源码备份 |
| `assets/output/account-deployment/deployment.json` | 部署清单与源码保留核验 |

2026-11-12 账号部署验收通过 26 项账号、独立进程、历史目录归属、服务恢复及守护测试。此后服务器已创建 `admin` 管理员并绑定历史科研目录。后端恢复另通过上述 37 项绘图相关测试。
