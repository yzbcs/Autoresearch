"use strict";

const $ = (selector) => document.querySelector(selector);
const moduleBase = location.pathname.startsWith("/auto-design/") ? "/auto-design" : "";
const state = { tasks: [], task: null, activeId: null, tab: "overview", connected: false };
const labels = { created: "待开始", queued: "排队中", running: "执行中", pausing: "正在安全暂停", paused: "已暂停", waiting_review: "待人工审核", blocked: "存在阻塞", failed: "步骤失败", design_ready: "设计完成", completed: "已完成", abandoned: "已废弃" };
const stages = { INPUT_READY: "输入已就绪", WAITING_FOR_R0: "等待 R0 探测", R0_PASSED: "R0 已通过", R0_FAILED_RETURN_TO_DESIGN: "R0 返回设计", EXPERIMENT_DESIGN_READY: "设计已接受", IMPLEMENTATION_READY: "实现已就绪", EXECUTION_IN_PROGRESS: "实验执行中", EXECUTION_COMPLETE: "实验执行完成", RESULT_DIAGNOSIS_READY: "结果诊断完成", WAITING_FOR_METHOD_REVISION_APPROVAL: "等待方法修改批准", INTEGRITY_AUDIT_PASS: "审计通过", COMPLETE: "流程完成", IDEA_ABANDONED: "Idea 已废弃" };
const actionLabels = { design: "实验设计", run: "实验执行", diagnosis: "结果诊断", revision: "方法修改", audit: "独立审计" };

async function api(path, body) {
  const response = await fetch(`${moduleBase}${path}`, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

function notice(message = "") { $("#notice").textContent = message; $("#notice").hidden = !message; }
function element(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = String(text); if (className) node.className = className; return node; }
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${name}`); svg.setAttribute("aria-hidden", "true"); svg.append(use); return svg;
}
function empty(container, text) { container.replaceChildren(element("div", text, "empty-state")); }
function documentText(id, text, fallback = "尚未生成。完成对应步骤后，真实产物会显示在这里。") { $(id).textContent = text || fallback; }
function fileUrl(path) { return `${moduleBase}/api/tasks/${state.activeId}/files/${path.split("/").map(encodeURIComponent).join("/")}`; }
function fileLink(path, label) { const a = element("a", label); a.href = fileUrl(path); a.target = "_blank"; a.rel = "noopener"; return a; }
function selectTab(name) { state.tab = name; document.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name))); document.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== name; }); }

function renderList() {
  $("#task-count").textContent = `${state.tasks.length} 个实验任务`;
  const buttons = state.tasks.map((task) => {
    const button = element("button", undefined, "task-item" + (task.id === state.activeId ? " selected" : ""));
    button.dataset.deleteTask = task.id;
    const label = element("span", undefined, "task-label");
    label.append(element("strong", task.title), element("small", `${labels[task.status] || task.status} · ${new Date(task.created_at).toLocaleDateString("zh-CN")}`));
    button.append(icon("folder"), label);
    button.addEventListener("click", () => { setSidebar(false); selectTask(task.id).catch((error) => notice(error.message)); });
    return button;
  });
  $("#task-list").replaceChildren(...buttons);
  $("#task-list").hidden = !buttons.length;
  $("#sidebar-empty").hidden = Boolean(buttons.length);
}

function renderTable(container, headers, rows) {
  const table = element("table"); const head = element("thead"); const tr = element("tr");
  headers.forEach((h) => tr.append(element("th", h))); head.append(tr); table.append(head);
  const body = element("tbody");
  rows.forEach((row) => { const tr = element("tr"); row.forEach((value) => tr.append(element("td", value))); body.append(tr); });
  table.append(body); const wrap = element("div", undefined, "table-wrap"); wrap.append(table); container.replaceChildren(wrap);
}

function renderTask() {
  const task = state.task; if (!task) return;
  $("#welcome").hidden = true; $("#workspace").hidden = false;
  $("#task-title").textContent = task.title; $("#task-status").textContent = labels[task.status] || task.status;
  $("#task-status").dataset.status = task.status;
  $("#task-stage").textContent = stages[task.stage] || task.stage;
  $("#task-summary").textContent = task.summary; $("#task-error").textContent = task.error || ""; $("#task-error").hidden = !task.error;
  const active = ["queued", "running", "pausing"].includes(task.status);
  const pendingReview = Boolean(task.review && !task.review.approved);
  $("#run-task").hidden = active || pendingReview || ["completed", "abandoned"].includes(task.status);
  $("#run-task").textContent = task.status === "created" ? "开始执行" : task.status === "design_ready" ? "开始实验" : "继续执行";
  $("#pause-task").hidden = !active; $("#pause-task").disabled = task.status === "pausing";
  $("#pause-task").textContent = task.status === "pausing" ? "等待安全收尾" : "安全暂停";
  $("#interrupt-task").hidden = !active; $("#interrupt-help").hidden = !active;
  $("#recovery-field").hidden = active || pendingReview || ["completed", "abandoned"].includes(task.status);
  $("#task-scope").textContent = task.scope === "design_only" ? "本轮仅设计" : "完整实验流程";
  const paths = $("#task-paths"); paths.replaceChildren();
  [["项目根目录", task.workspace], ["任务工作目录", task.run_dir], ["任务编号", task.id]].forEach(([key, value]) => paths.append(element("dt", key), element("dd", value)));
  const docs = task.documents;
  documentText("#input-document", docs["input_brief.md"]); documentText("#state-document", docs["AUTODESIGN_STATE.md"]);
  documentText("#plan-document", docs["experiment_design.md"]); documentText("#diagnosis-document", docs["result_diagnosis.md"]);
  documentText("#effects-document", docs["effect_comparison.md"]); documentText("#audit-document", docs["integrity_audit.md"]);
  const execution = $("#execution-content"); const commands = task.execution?.commands || [];
  if (commands.length) {
    execution.replaceChildren();
    commands.forEach((command) => {
      const box = element("details", undefined, "log-item");
      box.append(element("summary", `${command.stage} / ${command.command_index ?? "未编号"} · exit ${command.exit_status ?? "未记录"}`));
      box.append(element("pre", `命令：${command.command}\n工作目录：${command.cwd || "见 command_plan.json"}\n\nSTDOUT\n${command.stdout || ""}\n\nSTDERR\n${command.stderr || ""}`, "document"));
      execution.append(box);
    });
  } else empty(execution, "尚无实验执行记录。设计阶段不会生成实验结果。");
  const attempts = $("#attempt-content"); attempts.replaceChildren();
  if (!task.attempts.length) empty(attempts, "工作流尚未启动。");
  task.attempts.forEach((attempt, i) => {
    const box = element("article", undefined, "log-item");
    box.append(element("strong", `${String(i + 1).padStart(2, "0")} · ${actionLabels[attempt.action] || attempt.action}`));
    box.append(element("p", attempt.response?.summary || `开始于 ${new Date(attempt.started_at).toLocaleString("zh-CN")}`));
    const relative = `assets/logs/${String(i + 1).padStart(4, "0")}-${attempt.action}`;
    box.append(fileLink(`${relative}/execution.json`, "执行记录"), document.createTextNode("　"), fileLink(`${relative}/events.jsonl`, "完整事件"), document.createTextNode("　"), fileLink(`${relative}/stderr.log`, "错误日志")); attempts.append(box);
  });
  const results = $("#result-content"); const aggregates = task.results?.aggregates || [];
  if (aggregates.length) {
    renderTable(results, ["实验 / 变体", "任务 / 指标", "均值", "样本标准差", "Seeds 数量", "逐 Seed 值"], aggregates.map((r) => [`${r.experiment_id}\n${r.variant_id}`, `${r.benchmark_task_id}\n${r.metric}`, r.mean, r.n > 1 ? r.sample_std : "N/A（单 seed）", r.n, JSON.stringify(r.values)]));
    results.prepend(element("p", task.results.status === "READY_FOR_GPT_DIAGNOSIS" ? "以下为已校验的观测汇总；贡献结论以结果诊断与审计为准。" : "INCOMPLETE：以下值仅供诊断，不能视为完整科学证据。", "muted"));
  } else empty(results, "尚无观测结果。模拟目标不会作为实验结果展示。");
  $("#report-link").hidden = !task.reports_ready; $("#report-link").href = fileUrl("reports/index.html");
  $("#review-count").textContent = pendingReview ? "1" : "";
  $("#revision-id").textContent = task.review?.revision_id || "";
  documentText("#review-document", task.review?.proposal, "当前没有需要批准的方法修改。");
  $("#review-actions").hidden = active || !pendingReview;
  $("#approve-revision").textContent = task.review?.limit_reached ? "批准一次例外修改" : "批准指定修改";
  selectTab(state.tab);
}

async function selectTask(id) { state.activeId = id; state.task = await api(`/api/tasks/${id}`); renderList(); renderTask(); }
async function refresh() {
  const reconnecting = !state.connected;
  try {
    const health = await api("/api/health"); state.connected = true;
    $("#connection").textContent = health.codex_cli ? "本地服务已连接" : "服务已连接 · Codex 未配置";
    $("#connection-dot").classList.add("connected");
    for (const form of [$("#task-form"), $("#import-form")]) if (!form.elements.workspace.value) form.elements.workspace.value = health.workspace;
    state.tasks = (await api("/api/tasks")).tasks; renderList();
    if (state.activeId) { state.task = await api(`/api/tasks/${state.activeId}`); renderTask(); }
    if (reconnecting) notice();
  } catch (error) { state.connected = false; $("#connection").textContent = "本地服务未连接"; $("#connection-dot").classList.remove("connected"); notice(error.message); }
}

async function action(path, body = {}) { notice(); await api(path, body); await refresh(); }
function handle(button, fn) { button.addEventListener("click", async () => { button.disabled = true; try { await fn(); } catch (error) { notice(error.message); } finally { button.disabled = false; } }); }
function setSidebar(open) {
  $("#sidebar").classList.toggle("open", open);
  $("#sidebar-scrim").hidden = !open;
  $("#sidebar-toggle").setAttribute("aria-expanded", String(open));
}
function init() {
  if (location.protocol === "file:") {
    document.body.innerHTML = '<main style="max-width:640px;margin:12vh auto;padding:28px;line-height:1.8"><h1>请从本地服务打开 Auto Design</h1><p>当前是 HTML 文件预览，无法连接任务接口。</p><p><a class="button primary" href="http://127.0.0.1:8760/auto-design/">打开 Auto Design 工作台</a></p><p>默认服务地址为 http://127.0.0.1:8760/。如果启动时设置了其他端口，请使用终端显示的地址。</p></main>';
    return;
  }
  $("#sidebar-toggle").addEventListener("click", () => setSidebar(!$("#sidebar").classList.contains("open")));
  state.activeId = new URLSearchParams(location.search).get("task");
  $("#sidebar-scrim").addEventListener("click", () => setSidebar(false));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") setSidebar(false); });
  window.matchMedia("(max-width: 760px)").addEventListener("change", () => setSidebar(false));
  for (const id of ["#new-task", "#welcome-create"]) $(id).addEventListener("click", () => { setSidebar(false); $("#task-dialog").showModal(); });
  $("#import-task").addEventListener("click", () => { setSidebar(false); $("#import-dialog").showModal(); });
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => document.getElementById(button.dataset.close).close()));
  document.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => selectTab(button.dataset.tab)));
  $("#idea-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (file) { $("#task-form").elements.idea.value = await file.text(); $("#idea-file-label").textContent = file.name; }
  });
  for (const [formId, endpoint, dialogId] of [["#task-form", "/api/tasks", "#task-dialog"], ["#import-form", "/api/tasks/import", "#import-dialog"]]) {
    $(formId).addEventListener("submit", async (event) => {
      event.preventDefault(); const button = event.target.querySelector("button[type=submit]"); button.disabled = true;
      try { const task = await api(endpoint, Object.fromEntries(new FormData(event.target))); $(dialogId).close(); notice(); await refresh(); await selectTask(task.id); }
      catch (error) { notice(error.message); } finally { button.disabled = false; }
    });
  }
  handle($("#run-task"), () => action(`/api/tasks/${state.activeId}/start`, { ...(state.task.status === "design_ready" ? { scope: "full" } : {}), recovery_note: $("#recovery-note").value }));
  handle($("#pause-task"), () => action(`/api/tasks/${state.activeId}/pause`));
  handle($("#interrupt-task"), () => action(`/api/tasks/${state.activeId}/interrupt`));
  handle($("#approve-revision"), () => action(`/api/tasks/${state.activeId}/decision`, { revision_id: state.task.review.revision_id, decision: state.task.review.limit_reached ? "APPROVE_EXCEPTION_METHOD_REVISION" : "APPROVE_MINIMAL_METHOD_REVISION" }));
  handle($("#reject-revision"), () => action(`/api/tasks/${state.activeId}/decision`, { revision_id: state.task.review.revision_id, decision: "REJECT_METHOD_REVISION" }));
  handle($("#abandon-idea"), () => action(`/api/tasks/${state.activeId}/decision`, { revision_id: state.task.review.revision_id, decision: "ABANDON_IDEA" }));
  async function poll() { await refresh(); window.setTimeout(poll, 3000); }
  poll();
}
init();
