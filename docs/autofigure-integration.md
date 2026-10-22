# AutoFigure 接入验收（2026-09-10）

新增 `auto_figure/`，将新建全流程扩展为 AutoTable → AutoFigure；原四模块核心处理逻辑未作本轮修改。
工作区原先已有其他未提交改动，本轮保留，不将这些改动计入 AutoFigure 接入。

接入范围包括任务状态、停止/恢复、输入快照与来源版本、方法规划、固定上游绘图进程、
SVG 校验/渲染、确定性正文补丁、原编译器复用、完整 PDF 复核、HTTP 页面和下载。
现有工作台只增加第五阶段、模块注册、导航、任务命名和下游失效处理。

验证按相关范围分批运行：

- AutoFigure 最终测试：23 passed，覆盖逐字补丁、表格保持、多文件/嵌套主文件、占位图 label、
  非法锚点、SVG 位图兜底拒绝、来源哈希、暂停恢复、编译/渲染重试与上游参数传递。
- 工作台原流程、HTTP 与第五阶段接入：35 passed。原流程测试显式保留四阶段模式，新增测试验证
  默认第五阶段、AutoTable 幂等交接、上游版本失效、历史完成状态、API 与下载。
- AutoTable、服务恢复与任务命名：62 passed；另与当时的 18 项 AutoFigure 测试合批得到 80 passed。
- Ruff、本轮相关 JavaScript 语法检查、`git diff --check` 通过。
- 上游源码与 MIT 许可的 SHA-256 与固定版本记录一致，独立环境成功导入上游绘图核心。

真实编译使用项目内 Tectonic 0.17.0，主图 SVG 经 CairoSVG 转为 PDF，再通过原 AutoWriting
编译函数编译论文。首次下载 TeX 资源超时；恢复后复用已完成的图和插图源码，成功生成一页 PDF，
已查看渲染页面，确认主图、图注、引用和原表格存在，无重叠或裁切。
该样例的图和方法/复核响应为明确标记的工程 fixture，不是模型生成的科学结果。
产物保留于 `assets/logs/auto_figure/verification/`，不进入工作台正常任务索引。

未执行真实上游模型端到端绘图：当前 SAM 凭据尚未配置，RMBG 模型权限未验证。
未启动或重启用户的正式研究服务。配置入口和启动命令见 [Auto Figure](../auto_figure/README.md)。

本机新增工具、依赖环境和缓存均位于仓库内：`.venv-autofigure/`、`.tools/tectonic/`、
`.cache/autofigure/`、`.cache/pip/`。测试临时目录已清理。
