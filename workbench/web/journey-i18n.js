"use strict";

(() => {
  const messages = {
    "无法同步研究服务：": "Unable to sync: ",
    "。已保留最近一次画面，可返回工作台恢复服务。":
      ". The last view is retained. Restore the service in the workbench.",
    "无法进入全屏：": "Unable to enter fullscreen: ",
    工作台: "Workbench",
    科研航线: "Research Journey",
    科研航线图: "Research Journey",
    研究模块: "Research modules",
    "AutoResearch 工作台": "AutoResearch workbench",
    研究任务: "Research projects",
    搜索研究任务: "Search projects",
    "搜索任务名称或研究方向…": "Search title or research topic…",
    "正在读取研究任务…": "Loading projects…",
    "＋ 新建研究": "＋ New research",
    新建研究: "New research",
    沿用原有任务与科学审批: "Existing tasks and research approvals",
    点击航线节点查看证据和产物: "Select a node to inspect evidence and outputs",
    "返回完整工作台 ↗": "Open workbench ↗",
    正在连接: "Connecting",
    研究服务已连接: "Research service connected",
    连接中断: "Connection lost",
    正在同步: "Syncing",
    已暂停页面同步: "Page updates paused",
    打开研究任务: "Open projects",
    关闭研究任务: "Close projects",
    研究全程可追溯: "Traceable research",
    "让每一次探索、调整与发现，都有迹可循。":
      "Follow every exploration, revision and discovery.",
    "管理流程 ↗": "Manage workflow ↗",
    "Ⅱ 暂停流程": "Ⅱ Pause workflow",
    "从一个问题，出发。": "Start with a question.",
    "还没有全流程任务。创建研究后，论文、选题、实验与最终交付会在这里连接成一条航线。":
      "Create a research workflow to connect literature, ideas, experiments and final deliverables.",
    "＋ 创建第一项研究": "＋ Create your first research",
    "已有独立任务？在工作台新建全流程时选择接续。":
      "Have an existing task? Continue it through a new workflow in the workbench.",
    "没有匹配的研究任务。": "No matching projects.",
    "还没有全流程任务。": "No research workflows yet.",
    研究概况: "Research overview",
    篇论文: "papers",
    实际调研记录: "Saved literature records",
    "个候选 Idea": "candidate ideas",
    来自已保存的方案集: "From saved idea portfolios",
    实验单元: "experiment cells",
    "已记录观测 / 计划单元": "Observed / planned cells",
    尚无可汇总的实验记录: "No experiment records yet",
    次设计调用: "design calls",
    设计与方法修改调用记录: "Design and method revision calls",
    已完成: "Completed",
    运行中: "Running",
    待处理: "Awaiting action",
    需要处理: "Needs attention",
    已暂停: "Paused",
    未开始: "Not started",
    "未纳入 / 已放弃": "Skipped / discarded",
    等待审批: "Awaiting review",
    等待选题: "Select an idea",
    等待确认参考图: "Confirm references",
    调研与选题: "Search & ideas",
    实验与审计: "Experiments & audit",
    写作与引用: "Writing & citations",
    表格与复核: "Tables & review",
    主图与交付: "Figures & delivery",
    研究方向: "Research scope",
    论文证据: "Literature",
    "已选 Idea": "Selected idea",
    "候选 Idea": "Candidate idea",
    实验设计: "Design",
    实验执行: "Execution",
    诊断与审计: "Review & audit",
    "R0 探测": "R0 probe",
    方法修改审批: "Method review",
    论文写作: "Writing",
    表格复核: "Table review",
    已选定: "Selected",
    已放弃: "Discarded",
    待核验: "To verify",
    尚未生成: "Not generated",
    科研航线画布: "Research journey canvas",
    五阶段进度: "Research stages",
    "航线画布，拖动平移，滚轮缩放，方向键平移，数字零适应画布":
      "Journey canvas: drag to pan, wheel to zoom, arrow keys to pan, 0 to fit",
    "研究航线，使用 Tab 选择节点，回车查看详情":
      "Journey nodes: Tab to select, Enter for details",
    "拖动画布 · 滚轮缩放 · 双击节点进入模块":
      "Drag to pan · Scroll to zoom · Double-click a node to open",
    航线总览: "Overview",
    航线缩略图: "Journey minimap",
    放大航线: "Zoom in",
    缩小航线: "Zoom out",
    缩放比例: "Zoom level",
    全览: "Fit",
    定位当前: "Current step",
    全屏航线: "Fullscreen",
    退出全屏: "Exit fullscreen",
    "导出 SVG": "Export SVG",
    研究事件时间线: "Research event timeline",
    "◷ 研究足迹": "◷ Research timeline",
    实时更新: "Live updates",
    "时间线仅展示已记录事件；上方航线与节点详情始终显示最近一次同步的状态。":
      "The timeline shows recorded events. The map and details show the latest synced state.",
    节点详情: "Node details",
    "点击航线上的节点查看详情。": "Select a node to inspect its details.",
    关联产物: "Outputs",
    "打开已登记产物 ↗": "Open saved output ↗",
    "查看原始文件 ↗": "View original file ↗",
    "尚无可展示产物，完成对应步骤后会在这里出现。":
      "Outputs appear here when the relevant steps are completed.",
    "该模块尚未创建任务。": "No task has been created for this module.",
    "已记录观测不代表实验或审计通过。":
      "Recorded observations do not imply experiment or audit approval.",
    "最终交付：下载前核对论文与复核记录":
      "Final delivery: check the manuscript and review records before downloading",
    以原模块的证据与审批记录为准:
      "Refer to the original module for evidence and approvals",
    "尚无推进记录。任务开始推进后显示已记录事件。":
      "No events yet. Recorded progress will appear here.",
    "等待首次推进。": "Waiting for the first step.",
    流程记录: "Workflow event",
    模块记录: "Module event",
    时间未记录: "Time not recorded",
    "真实任务数据 · 不推断未记录的研究过程":
      "Real task data · Unrecorded research steps are not inferred",
    读取输入: "Read inputs",
    设计表格: "Design tables",
    生成表格: "Generate tables",
    "编译 PDF": "Compile PDF",
    独立复核: "Independent review",
    读取论文: "Read manuscript",
    规划插图: "Plan figure",
    准备论文: "Prepare manuscript",
    "FigureCrafter 绘图": "Generate with FigureCrafter",
    插入论文: "Insert figure",
    图文复核: "Review figure and text",
    未完成: "Incomplete",
    "尚未创建调研任务。": "No literature task yet.",
    "等待选题交接或接续已有实验。":
      "Waiting for an idea handoff or an existing experiment.",
    "尚无实验执行记录。": "No execution record yet.",
    "实验完成后进行科学诊断与完整性审计。":
      "Scientific diagnosis and integrity audit follow execution.",
    "等待上游交接。": "Waiting for an upstream handoff.",
    "基于实验材料完成六章节、引用与排版。":
      "Draft six sections, citations and publication layout from experiment evidence.",
    "前置探测返回设计，请查看原探测记录。":
      "The probe returned to design. Inspect the original probe record.",
    "按登记的 R0 探测记录展示。": "Based on the saved R0 probe record.",
    "请在实验模块查看指定 Revision ID 的提案和决定。":
      "See the proposal and decision for the relevant Revision ID in Auto Design.",
    "本流程未记录研究方向。":
      "No research scope was recorded for this workflow.",
    选择语言: "Choose language",
    "请从工作台 HTTP 地址打开 /journey.html。":
      "Open /journey.html from the workbench HTTP address.",
  };
  const storageKey = "autoresearch-language";
  let locale = localStorage.getItem(storageKey) === "en" ? "en" : "zh-CN";
  const original = new WeakMap();
  function t(source) {
    if (locale !== "en") return source;
    const text = String(source ?? "");
    if (messages[text]) return messages[text];
    if (text.startsWith("↗ ")) return `↗ ${t(text.slice(2))}`;
    let match = text.match(/^候选 Idea (\d+)$/);
    if (match) return `Candidate ${match[1]}`;
    match = text.match(
      /^(\d+) (调研与选题|实验与审计|写作与引用|表格与复核|主图与交付)$/,
    );
    if (match) return `${match[1]} ${messages[match[2]]}`;
    match = text.match(/^(\d+) \/ (\d+) 观测单元$/);
    if (match) return `${match[1]} / ${match[2]} observed cells`;
    match = text.match(/^(\d+(?:\.\d+)? KB) · 查看原始文件 ↗$/);
    if (match) return `${match[1]} · View original ↗`;
    match = text.match(/^进入 (.+) ↗$/);
    if (match) return `Open ${match[1]} ↗`;
    match = text.match(/^下一站：(.+)$/);
    if (match) return `Next: ${t(match[1])}`;
    match = text.match(/^任务更新 (.+)$/);
    if (match) return `Updated ${match[1]}`;
    match = text.match(/^已同步 (.+)$/);
    if (match) return `Synced ${match[1]}`;
    match = text.match(
      /^(.+) · (调研与选题|实验与审计|写作与引用|表格与复核|主图与交付)$/,
    );
    if (match) return `${t(match[1])} · ${t(match[2])}`;
    match = text.match(/^(.+)，(.+)$/);
    if (
      match &&
      (messages[match[1]] || messages[match[2]] || t(match[2]) !== match[2])
    )
      return `${t(match[1])}, ${t(match[2])}`;
    return text;
  }
  function localize() {
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
    );
    while (walker.nextNode()) {
      const node = walker.currentNode,
        parent = node.parentElement;
      if (!parent || parent.closest("script,style,[data-user-content],option"))
        continue;
      const raw = node.textContent,
        trimmed = raw.trim();
      if (!trimmed) continue;
      let record = original.get(node);
      if (!record || record.last !== raw) record = { source: raw };
      const result = record.source.replace(
        record.source.trim(),
        t(record.source.trim()),
      );
      record.last = result;
      original.set(node, record);
      if (raw !== result) node.textContent = result;
    }
    for (const element of document.querySelectorAll(
      "[placeholder],[aria-label],[title]",
    )) {
      if (element.closest("[data-user-content]") || element.tagName === "TITLE")
        continue;
      let record = original.get(element) || {};
      for (const attr of ["placeholder", "aria-label", "title"]) {
        const raw = element.getAttribute(attr);
        if (!raw) continue;
        const entry = record[attr];
        const source = entry && entry.last === raw ? entry.source : raw;
        const result = t(source);
        record[attr] = { source, last: result };
        if (raw !== result) element.setAttribute(attr, result);
      }
      original.set(element, record);
    }
  }
  function applyLanguage(value) {
    locale = value === "en" ? "en" : "zh-CN";
    localStorage.setItem(storageKey, locale);
    document.documentElement.lang = locale;
    document.querySelector("#language").value = locale;
    localize();
    document.dispatchEvent(new Event("journeylanguagechange"));
  }
  window.JourneyI18n = {
    t,
    localize,
    get locale() {
      return locale;
    },
  };
  document
    .querySelector("#language")
    .addEventListener("change", (e) => applyLanguage(e.target.value));
  let scheduled = false;
  new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => {
      scheduled = false;
      localize();
    });
  }).observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });
  applyLanguage(locale);
})();
