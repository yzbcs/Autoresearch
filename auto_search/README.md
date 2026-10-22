# Auto Search: Weakness to Concept

Auto Search 是 LL-AutoResearch 中面向科研选题与方法设计的交互式模块。它支持从一个明确的研究 Weakness 直接生成解决方案，也支持从宽泛研究方向开始，自动调研论文、提取可核验 Weakness、生成三项 Contribution 和完整 Idea，并在网页中统一浏览与人工核验。

## 功能概览

- **Weakness 直达 Idea**：输入当前领域的具体问题，通过 Codex CLI 生成结构化 Markdown 方案。
- **研究方向自动调研**：检索并核验论文，逐篇提取 Weakness，再生成 Contribution、Method 和实验设计。
- **可行性门槛**：至少一个公开 Benchmark 必须能够检验最终任务，三个 Contribution 的关键机制还需由已发布标注或确定性诊断独立验证；Benchmark 数量不足三个不再被错误地视为自动失败。
- **独立评审**：对候选 Idea 进行评分、风险分析和排序。
- **网页工作台**：以文件夹树管理调研任务，分板块展示 Weakness、成因、Contribution、方法、评审和人工核验。
- **人工核验**：支持“通过”与“废弃”，再次点击已选状态可取消核验。

## 目录结构

```text
auto_search/
├── generate_idea.py          # Weakness -> Idea
├── direction_research.py     # 研究方向 -> 论文与 Weakness
├── research_pipeline.py      # 批量 Idea 生成与评审
├── run.ps1                   # Windows 统一启动入口
├── prompt.md                 # Idea 生成提示词
├── evaluation_prompt.md      # 评审提示词
├── schemas/                  # 结构化输出 Schema
├── sources/                  # 示例论文清单
├── inputs/                   # 示例输入
├── tests/                    # 单元测试
└── web/                      # 本地交互网页与服务端
```

`ideas/`、`research_runs/`、`web/data/` 和服务日志属于本地运行产物，不提交到仓库。

## 环境要求

- Windows PowerShell
- Python 3.10 或更高版本
- 已安装并完成登录的 Codex CLI

项目本身不依赖第三方 Python 包。`run.ps1` 会优先使用 `W2C_PYTHON`，随后尝试寻找 Codex Desktop 自带的 Python 运行时。

如需显式指定 Python：

```powershell
$env:W2C_PYTHON = "C:\path\to\python.exe"
```

如需显式指定 Codex CLI：

```powershell
$env:CODEX_CLI = "C:\path\to\codex.exe"
```

Auto Search 的论文调研、Idea 生成和独立评审默认统一使用 `gpt-5.6-sol`。如需临时覆盖：

```powershell
$env:AUTO_SEARCH_CODEX_MODEL = "gpt-5.6-sol"
```

## 快速开始

进入模块目录：

```powershell
cd .\auto_search
```

### 1. 从 Weakness 生成 Idea

```powershell
.\run.ps1 "现有医学视觉语言模型在深层视觉编码过程中会逐渐丢失微小病灶的局部表征"
```

不传参数时，命令行会提示输入 Weakness：

```powershell
.\run.ps1
```

从文件读取并指定输出路径：

```powershell
.\run.ps1 --weakness-file .\inputs\micro-lesion-token-erosion.txt -o .\ideas\micro-lesion.md
```

默认结果写入 `ideas/idea-<timestamp>.md`。

### 2. 批量生成与评审

```powershell
.\run.ps1 --pipeline all
```

也可以分阶段运行：

```powershell
.\run.ps1 --pipeline generate
.\run.ps1 --pipeline evaluate
```

### 3. 启动网页工作台

```powershell
python .\web\serve.py
```

访问 [http://127.0.0.1:8765/](http://127.0.0.1:8765/)。

网页中的“新建调研”支持输入具体或宽泛的研究方向。任务会依次执行论文调研、Weakness 提取、Idea 生成和评审，并把结果保存在独立的 `research_runs/direction-*` 目录中。

论文数量是上限而不是凑数指标。调研会把模型类型、模态、目标现象和任务作为范围约束；当直接相关的一手论文不足时返回较少论文，不用宽泛 VQA、普通定位或仅共享数据模态的论文补足数量。

每个网页调研任务的 Codex 工作目录和子进程当前目录均为该任务的独立运行目录；论文调研、Idea 生成及评审共用同一任务目录。源码、提示词和 Schema 仍从模块安装位置读取。在三模块工作台中，任务根目录由工作台指定，默认是 `assets/output/workbench/auto_search/`。

批量 CLI 使用 `--run-dir` 指定的目录作为执行目录；单篇 Weakness CLI 使用输出 Markdown 所在目录。目录参数逐次传入调用，不会修改 Python 服务的全局当前目录。

## 输出结构

通过可行性门槛的 Idea 按以下顺序生成：

1. Weakness
2. 三项成因分析
3. 三项逐点对应的 Contribution
4. 每项 Contribution 的具体实现
5. 数据集与 Benchmark
6. 完整训练、推理和评估流程

生成文档不使用公式或伪代码。方案必须说明组件输入、处理步骤、输出与衔接，并禁止伪造引用、数据集、指标或实验结果。

## 测试

```powershell
.\run.ps1 --test
```

也可以直接运行：

```powershell
python -m unittest discover -s tests -v
```

## 说明

- 推理时不得读取测试病例的真实掩膜、边界框、答案或其他 Oracle 信息。
- 可以复用公开数据已经发布的医生标注，但不得把新增医生复核作为方案成立的必要条件。
- `research_runs/` 包含论文证据、Prompt、Idea、评审和人工核验结果，应按实际需要自行备份。

### 网页恢复与自动交接

网页“停止并保留”终止当前调研调用并保留产物，失败/中断任务的“继续”在原目录复用已完成的 manifest、合格 Idea 和评审。服务重启后同样可以继续原任务。错误与事件可以在任务列表展开查看；旧取消并删除接口仍保留，但不再作为网页的停止动作。

在统一工作台创建全流程，可自动或手动选定 Idea 并交接 Auto Design；后续实验与论文自动衔接。详见 [前端全流程说明](../docs/frontend_workflow.md)。

## 新任务目录命名

新建任务采用 `任务标题-search-YYYYMMDD-HHMMSS-ffffff`（北京时间，含微秒）。保留中文，特殊字符清理为连字符，标题部分最多 60 字符；重名冲突追加短编号。历史任务目录保持原路径。统一规则见 [工作台说明](../workbench/README.md#任务目录命名)。
