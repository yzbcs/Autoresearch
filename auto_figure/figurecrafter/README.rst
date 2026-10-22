Drawing harness v2.5.1 — 独立运行版
=================================

输入缺方法主图PDF与三张参考PNG，模型生成单页16:9可编辑方法主图。
科学理解、参考解读、六类对象选择、布局、作者代码、像素审核及版本选择均由模型执行。
代码负责机械工具、API传输、导出、证据与冻结；没有固定scene模板、自动审美评分或外层进化。

本目录是v2.5的新衍生版本。原始恢复文件、v3.5以及GitHub保持不动。
provenance/source.json与adaptations.json区分继承文件和新实现。原始执行器复制后增加
公开LibreOffice路径配置、修复mm单位换算、调整指南目录；三个学习指南字节保持一致。
不包含也不要求Codex skill、@oai/artifact-tool、Node或厂商代理SDK。

安装与环境
----------

推荐Python3.13（这次实际3.13.5）。在本目录运行::

  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python run.py --soffice /absolute/path/to/soffice doctor

LibreOffice是公开安装的系统依赖，不能用python-pptx保存成功冒充渲染成功。
macOS示例路径为/Applications/LibreOffice.app/Contents/MacOS/soffice；Linux可通过系统
包管理器安装libreoffice-impress；Windows用LibreOffice安装目录中的soffice.exe。
也可以设置DRAWING_SOFFICE，或将可执行文件放进PATH。本次验证单独从官方渠道下载
25.8.7.3，放在runtime/LibreOffice.app，没有使用Codex运行时的LibreOffice。
下载来源和SHA256见runtime/libreoffice-download.json；此本机安装不属于可携带源码包。

字体须在自己的系统中合法安装。Times New Roman只是候选，并非跨系统必有。
记录PPTX声明、实际PDF字体和回退；系统字体不随包分发。依赖公开来源：
https://python-pptx.readthedocs.io/en/latest/ 和 https://www.libreoffice.org/download/ 。
requirements.txt锁定五项直接依赖；requirements.lock.txt记录本次完整Python依赖。

模型接口与生产
--------------

输入目录包含paper-without-main-figure.pdf和style-reference-01/02/03.png。
可选input-hashes.json会在准备时校验科学输入。CAFE同一份四文件位于inputs/cafe。
每次创建新的工作目录，不可覆盖已有run::

  .venv/bin/python run.py prepare --workspace runs/NEW --inputs inputs/cafe --model ACTUAL_MODEL

HTTP运行模式：复制examples配置到自己的配置文件，填写真实模型ID、完整端点与密钥
环境变量名（密钥只放环境，不写文件）。然后运行::

  .venv/bin/python run.py --soffice /absolute/path/to/soffice run --workspace runs/NEW --config YOUR_CONFIG.json

openai-compatible适配Chat Completions的文字、图片和function tools协议，可接提供兼容
接口的GPT/Qwen/DeepSeek/本地网关；不保证所有同名模型或服务都支持相同能力。必须选择
具有视觉与工具调用能力的模型，或由操作者提供等价的多模态网关。纯文本模型无法履行
实际像素审核合同，不默默用文字摘要替代。某些GPT服务只提供其他协议，需要增加适配器。
Gemini采用generateContent原生REST，保留functionCall的thoughtSignature和图像返回。
API参考：https://ai.google.dev/gemini-api/docs/function-calling 与
https://ai.google.dev/gemini-api/docs/image-understanding 。
JSON Schema工具声明使用parametersJsonSchema，参见
https://ai.google.dev/api/generate-content#FunctionDeclaration 。兼容服务返回的
reasoning_content也原样保留并回传，参见https://api-docs.deepseek.com/guides/thinking_mode/ 。

框架在HTTP模式中实际调用模型、执行其选择的工具、把文本及像素送回模型，直到模型
选择finish或达到轮次限制。限制到达会报未完成并保留conversation.json，可再次执行run
继续。不得把模型普通结束文本当作交付成功。服务返回的model与usage记录在events.jsonl。

通用会话桥接模式：当前Codex或其他代理可以使用相同工具入口，不需要skill::

  .venv/bin/python run.py tools
  .venv/bin/python run.py call --workspace runs/NEW --json TOOL_REQUEST.json

TOOL_REQUEST.json示例：
{"name":"read_text","arguments":{"path":"run/inputs/paper-text.txt"}}。
模型读取MODEL.txt与四份指南，通过write_file写理解、表征、决策、builder.py、审核和图注，
execute运行作者代码，view_image观察渲染，review记录判断，finish明确选择并冻结。
桥接工具返回image_path，代理必须真正打开像素，不能将路径返回视为视觉理解证明。
本轮CAFE就是当前模型经此通用接口执行，没有假称远端API调用或外部模型测试。

作者后端
--------

默认公开python-pptx接口；模型自由写Python作者代码，不由框架生成布局或挑选颜色。
builder.py接收sys.argv[1]为iteration输出目录，保存candidate.pptx。公开API支持文本、
形状、连线、图片、表格、原生chart和group；需要OfficeMath时可由模型编写标准OOXML。
没有限制模型必须使用全部六类组件。公式OOXML及不同Office应用的渲染要实测；不能
声称所有公式构造都已兼容。CAFE本次验证实际OMML公式与公开LibreOffice渲染。

隔离、交付与验证边界
------------------

每轮科学输入仅为本样本四文件；生产workspace不复制原图、原PPTX、历史生成或teacher。
指南包含跨样本历史学习经验，不授权读取其中链接。通用工具限制路径到workspace，写入
限于work。模型作者Python是自由代码，这不是OS沙箱；外部运行时应另提供容器/账号边界。
当前会话有项目历史，因此本次验证是文件输入隔离复验，不能声称新模型上下文盲测。
联合学习指南中的旧离线命令是历史说明，本版不实现或自动调用该离线入口；本版独立
运行范围是正式drawing生产闭环。CAFE的指南快照保留prepare当时文本，之后仅纠正
顶层指南中关于CLI模型调用能力的旧描述；科学策略未因此变化。

delivery中包含PPTX/PDF/PNG、180mm宽150dpi预览、图注、设计与审核；freeze.json记录
工作区文件哈希。代码只核验比例、输入一致性与真实文件，不自动判定科学或视觉质量::

  .venv/bin/python run.py verify --workspace runs/NEW
  DRAWING_SOFFICE=/absolute/path/to/soffice .venv/bin/python -m unittest discover -s tests -v

不带LibreOffice时真实渲染集成测试会skip，不能把skip报告成通过。HTTP集成测试使用
本地脚本端点验证消息、图片、工具往返、真实渲染和冻结，明确不是外部模型质量实验。
CAFE图稿、测试证据与运行限制见verification/validation.json和runs/cafe-20261012/delivery。
