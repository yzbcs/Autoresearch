# AutoResearch 项目指令

# AutoDesign GPU 执行上下文

通过 AutoResearch 前端工作台、Auto Design 控制器、`$run-autodesign` 或 `$autodesign-executor` 执行任务时，按本节解析任务目录；需要 GPU 或远端执行时，先读取本节的机器信息。本节是 AutoDesign 的 GPU、SSH 与远端操作目录来源；直接使用这些信息，不创建、不读取 Python/JSON GPU 配置，也不依赖项目中的 GPU 控制器。

本节只声明可用机器、目录和资源边界，不替代 Method Router 对 execution substrate 的 outcome-impact classification，也不提供科学方法、R0、实验命令或结果判断。

## 前端任务与本地产物目录

- 工作台数据根目录默认是 `<启动 workspace>/assets/output/workbench/`；指定 `--data-dir` 时，以实际配置为准。Auto Design 任务索引位于 `<data-dir>/auto_design/tasks.json`，流程关联位于 `<data-dir>/pipelines/`。
- 新建 Auto Design 任务的产物目录为 `<所选 workspace>/assets/output/auto_design/<task-id>/`，其中 `<task-id>` 是前端生成的 `design-<ID>`。始终以任务索引登记的 `run_dir` 为准；导入任务沿用登记的原目录。实现生成的目录名可能含任务标题和时间，不据此推导或重命名目录。
- `workspace` 表示用户在前端选择的实验项目根目录，用于定位机器指令和创建任务目录；任务的 Codex 工作目录是 `run_dir`。
- `idea.md`、`input_brief.md`、`AUTODESIGN_STATE.md`、设计文档、`command_plan.json`、`experiment_schedule.json`、`result_contract.json`、`execution_record.json`、`raw_results.json`、`result_summary.json` 等按项目合同保存在 `run_dir` 根目录；实验代码在 `run_dir/generated_project/`，最终报告入口在 `run_dir/reports/index.html`。
- 控制器调用日志位于 `run_dir/assets/logs/<attempt>-<action>/`。其他任务输入、日志和输出需要使用 `assets/` 时，以 `run_dir` 为根目录；具体实验结果路径仍按 `result_contract.json` 解析。
- 本地项目为 `/Users/yzb/Desktop/research/exp31_autoresearch`；前端选择该项目时，新任务产物位于该项目的 `assets/output/auto_design/` 下。选择其他项目或导入任务时使用其实际 `run_dir`。
- 工作台直接运行在服务器 `/root/autodl-tmp/yzb/autoresearch` 时，该服务器目录就是启动 workspace，登记的 `run_dir` 即任务产物目录；不得将 macOS 路径作为服务器路径，也不需要向自身 SSH 或同步同一目录。
- 项目目录约定依据 `workbench/README.md`、`auto_design/orchestration.py` 和 `auto_design/prompts/references/run-contract.md`；后续实现变化时以项目实际登记路径和合同为准。

## 连接与远端目录

- SSH：`root@connect.westd.seetacloud.com:54025`。
- SSH 认证：使用本机默认 SSH 认证；严格检查 host key；连接超时 `15` 秒。
- 允许根目录：`/root/autodl-tmp/yzb/autoresearch`。
- 同步根目录：`/root/autodl-tmp/yzb/autoresearch`。
- 从本地工作台向远端执行的新任务，远端目录使用 `/root/autodl-tmp/yzb/autoresearch/runs/<task-id>/`，与本地索引中的 `run_dir` 一一对应。已有任务若已登记远端目录，继续使用原路径，不因本规则重命名或搬迁；服务器直接执行的已有任务沿用登记的服务器 `run_dir`。
- 后续 round 需要独立执行目录时，使用该远端任务目录下的 `round_<round_id>/`；保留各轮代码、结果和执行记录。前端仍读取原 `run_dir`，不得仅因进入新一轮而更换其路径。
- 不同任务或 round 不混用 `generated_project`、结果目录或 execution record；恢复同一轮时复用已有目录和记录。
- 实验命令按当前任务的 `command_plan.json` 与运行器约定，从对应的 `generated_project/` 执行；远端工作目录必须位于对应的任务或 round 目录内。
- 远端新写入的代码、环境、缓存、日志、checkpoint 和结果只能位于允许根目录内。
- 在前端登记的 `run_dir/implementation_notes.md` 与 `run_dir/execution_record.json` 中记录本地任务目录、实际远端目录、当前 round 和执行工作目录，供恢复与回收使用。

## GPU 与调度

- 可见 GPU：`0,1`；GPU 数量：`2`。
- 默认多 GPU 命令设置 `CUDA_VISIBLE_DEVICES=0,1` 和 `AUTODESIGN_MAX_PARALLEL_JOBS=1`。
- 只有 `command_plan.json` 明确声明两个任务可分别绑定单卡时，才允许 `AUTODESIGN_MAX_PARALLEL_JOBS=2`；两个任务分别使用 GPU `0` 和 GPU `1`。
- 不允许两个并行任务同时声明 `CUDA_VISIBLE_DEVICES=0,1`。
- 单条命令最长运行时间：`86400` 秒。
- 每次启动前只读检查两张卡的显存与已有计算进程；保留所有已有进程。
- 不执行 `kill`、`pkill`、`killall`、`nvidia-smi --gpu-reset`，也不暂停、重启或修改其他进程。
- 显存不足时依次降低单进程 batch size、使用 gradient accumulation、减少并行 worker；保持已声明的有效 batch 和比较预算。仍不足时停止新任务并报告资源缺口。

## 环境与执行

- 传输方式：`rsync`；按已登记的本地与远端任务目录同步，保留任务内部相对路径，不要删除远端额外文件。
- `collect` 阶段将 `result_contract.json` 声明的结果及所需日志、执行记录回收到原本地 `run_dir` 的对应路径；合同中的项目相对结果路径以 `generated_project/` 为基准。完成结果导入、汇总与报告生成后，确保前端读取的 `run_dir/raw_results.json`、`run_dir/result_summary.json`、`run_dir/reports/` 等产物就位；不能仅保留在远端或工作台索引目录。服务器直接执行时，在登记的 `run_dir` 完成同样的归集。
- Conda 可执行文件：`/root/miniconda3/bin/conda`。
- Conda 环境逻辑名：`autodesign-gpu`；各自实验项目创建各自的 Conda 环境。使用显式 `--prefix <远端任务目录>/.conda-envs/autodesign-gpu`，运行时使用该 prefix，不使用会写入项目外共享环境目录的 `conda create -n`。已有任务沿用其登记且位于允许根目录内的环境。
- 环境包缓存、模型缓存与临时目录显式配置在允许根目录内，例如当前远端任务目录下的 `.cache/conda-pkgs/`、`.cache/huggingface/` 与 `assets/tmp/`。
- 真实实验依赖以当前 run 的 `generated_project/environment.yml` 为准。
- 实验命令以当前 run 的 `command_plan.json` 为准；结果路径以 `result_contract.json` 为准，不在本节固定具体实验命令。
- 固定顺序：`preflight → smoke → experiment → aggregate → collect`；smoke 成功后才能开始完整实验。
- 每次执行记录工作目录、GPU、环境、完整命令、stdout、stderr、开始/结束时间和 exit status；失败时保留日志、checkpoint 与已有结果，从项目支持的恢复入口继续。

## 下载与计算预算计时

- 模型、数据及依赖的网络下载单独记录 NETWORK_TRANSFER 耗时、字节数、续传偏移及结果，不计入 CPU/GPU 实验计算预算；下载等待也不作为 R0 科学失败或返回设计的原因。
- 保留部分文件，使用服务端支持的断点续传；网络超时保留现有进度，恢复前核对已有进程。单次连接/读取超时仍适用；不因网络慢削减样本、候选或比较预算。
- CPU 检查、数据处理、模型推理等实际计算仍遵守原注册预算；混合计算与传输命令分别记录，不能直接把整个命令的墙钟时长作为 CPU 计算量。旧执行记录不改写，恢复时按类别重算计算预算，剔除明确的下载等待。

## 数据隔离检查的适用范围

隔离规则必须针对当前任务可达的具体泄漏途径，使用实际可取得的来源、样本/文档ID、图像及标注信息。配置选择与正式评测的样本和图像应独立；不同图像共享常见文字不自动构成泄漏。除非科学输入明确要求文本去污染或已有证据表明同文档复用，不得将完整页面转写、通用文本shingle相似度或无法取得的上游字段设为必过门槛。缺少与实际估计目标无关的字段，记录为核验局限，不伪装成实验失败。真实样本重叠、标签流入配置选择或正式范围改变仍须阻止执行。已有不适用门槛由design在新一轮修订并冻结，保留旧失败证据；run不得将失败改写为通过。不新增无实际用途的哈希、评分器或防御性检查。每项检查说明具体检测的失败及失败后改变的动作。
