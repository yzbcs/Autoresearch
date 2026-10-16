const state = {
  data: null,
  activeId: null,
  activeRun: "medical-vlm-10",
  runs: [],
  datasets: new Map(),
  expandedRuns: new Set(),
  tab: "overview",
  pollTimer: null,
  contextRun: null,
  confirmAction: null,
};

const verdictLabels = {
  strong: "强",
  promising: "潜力",
  weak: "待加强",
  pass: "PASS",
  unreviewed: "未评审",
};

const scoreLabels = {
  problem_grounding: "问题扎根",
  root_cause_quality: "成因质量",
  point_to_point_alignment: "逐点对应",
  terminology_discipline: "术语纪律",
  novelty_plausibility: "创新性",
  implementation_feasibility: "实现可行性",
  benchmark_readiness: "Benchmark",
  resource_feasibility: "资源可行性",
  annotation_compliance: "标注合规",
  validation_strength: "验证强度",
  contribution_clarity: "贡献清晰度",
};

const activeStatuses = new Set(["queued", "researching", "generating", "evaluating", "cancelling"]);
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function icon(name, className = "") {
  return `<svg class="${className}" aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function inlineMarkdown(value = "") {
  let safe = escapeHtml(value);
  safe = safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  safe = safe.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  return safe;
}

function renderMarkdown(markdown = "") {
  const lines = String(markdown).replaceAll("\r\n", "\n").split("\n");
  const output = [];
  let paragraph = [];
  let listType = null;
  const flushParagraph = () => {
    if (paragraph.length) output.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  };
  lines.forEach((line) => {
    const trimmed = line.trim();
    const ordered = trimmed.match(/^\d+\.\s+(.+)$/);
    const unordered = trimmed.match(/^[-*]\s+(.+)$/);
    if (!trimmed) {
      flushParagraph();
      closeList();
    } else if (ordered || unordered) {
      flushParagraph();
      const nextType = ordered ? "ol" : "ul";
      if (listType !== nextType) {
        closeList();
        listType = nextType;
        output.push(`<${listType}>`);
      }
      output.push(`<li>${inlineMarkdown((ordered || unordered)[1])}</li>`);
    } else {
      closeList();
      paragraph.push(trimmed);
    }
  });
  flushParagraph();
  closeList();
  return output.join("");
}

function runLabel(run) {
  return run.run_name === "medical-vlm-10" ? "Medical VLM 方案集" : run.direction;
}

function runStatusText(run) {
  if (run.status === "ready") return `${run.ideas.length} Ideas`;
  if (run.status === "failed") return run.stage || "任务失败";
  if (run.status === "cancelling") return "正在取消";
  return `${run.stage || "等待开始"} · ${run.progress || 0}%`;
}

function matchingRuns() {
  return state.runs;
}

function renderFolderTree() {
  const runs = matchingRuns();
  $("#resultCount").textContent = `${runs.length} 个调研文件夹`;
  $("#emptyState").hidden = runs.length > 0;
  $("#ideaList").innerHTML = runs.map((run) => {
    const running = activeStatuses.has(run.status);
    const expanded = run.status === "ready" && state.expandedRuns.has(run.run_name);
    const selected = state.activeRun === run.run_name;
    const statusClass = running ? (run.status === "cancelling" ? "cancelling" : "running") : run.status;
    const action = running
      ? `<span class="run-action" title="${escapeHtml(runStatusText(run))}">
          ${icon("loader", "run-spinner")}
          <button class="stop-run" type="button" data-stop-job="${escapeHtml(run.job_id || "")}" data-run="${escapeHtml(run.run_name)}" title="中止调研" aria-label="中止调研" ${run.job_id && run.status !== "cancelling" ? "" : "disabled"}>${icon("circle-stop")}</button>
        </span>`
      : run.status === "ready" ? `<span class="folder-count">${run.ideas.length}</span>` : `<button type="button" class="button secondary" data-resume-run="${escapeHtml(run.run_name)}">继续</button>`;
    const children = expanded ? `<div class="folder-children">${run.ideas.map((idea) => {
      const stateMarker = idea.human_review === "approved"
        ? icon("circle-check", "human-state-icon approved")
        : idea.human_review === "discarded"
          ? icon("circle-x", "human-state-icon discarded")
          : `<span class="model-verdict ${escapeHtml(idea.verdict)}">${escapeHtml(verdictLabels[idea.verdict] || "未评审")}</span>`;
      return `
      <button class="idea-child ${selected && state.activeId === idea.id ? "active" : ""}" type="button" data-run="${escapeHtml(run.run_name)}" data-idea="${escapeHtml(idea.id)}">
        <span class="item-index">${String(idea.index).padStart(2, "0")}</span>
        <span class="item-title">${escapeHtml(idea.title)}</span>
        ${stateMarker}
      </button>`;
    }).join("")}</div>` : "";
    return `<div class="folder-node ${expanded ? "expanded" : ""}" data-run-node="${escapeHtml(run.run_name)}">
      <div class="folder-row ${statusClass} ${selected ? "selected" : ""}" data-folder-row="${escapeHtml(run.run_name)}">
        <button class="folder-toggle" type="button" data-toggle-run="${escapeHtml(run.run_name)}" title="${expanded ? "收起" : "展开"}" aria-label="${expanded ? "收起" : "展开"}" ${run.status === "ready" ? "" : "disabled"}>${icon("chevron-right")}</button>
        ${icon(expanded ? "folder-open" : "folder", "folder-icon")}
        <button class="folder-label" type="button" data-folder-label="${escapeHtml(run.run_name)}" ${run.status === "ready" ? "" : "disabled"}>
          <strong title="${escapeHtml(runLabel(run))}">${escapeHtml(runLabel(run))}</strong>
          <small>${escapeHtml(runStatusText(run))}</small>
        </button>
        ${action}
      </div>
      ${children}
      ${run.error || run.status === "failed" || run.status === "cancelled" ? `<details style="padding:10px;font-size:12px"><summary>错误与恢复记录</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${escapeHtml(run.error || run.stage)}\n${escapeHtml((run.events || []).map((e) => `${e.at} ${e.message}`).join("\n"))}</pre></details>` : ""}
    </div>`;
  }).join("");
}

function contributionCard(item, index, causes) {
  const cause = causes[index];
  return `<article class="contribution-card">
    <header><span>CONTRI ${String(item.number).padStart(2, "0")}</span><span class="cause-tag">${cause ? `对应：${escapeHtml(cause.title)}` : ""}</span></header>
    <div class="prose">${renderMarkdown(item.text)}</div>
  </article>`;
}

function resourceCard(item, type) {
  const label = type === "dataset" ? "DATASET" : "BENCHMARK";
  const title = item.url
    ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.name)}${icon("external-link")}</a>`
    : `<span>${escapeHtml(item.name)}</span>`;
  return `<article class="resource-card ${type} ${item.legacy ? "legacy" : ""}">
    <header>
      <span>${label} ${String(item.number).padStart(2, "0")}</span>
      <h4>${title}</h4>
    </header>
    <dl>${item.fields.map((field) => `
      <div><dt>${escapeHtml(field.label)}</dt><dd class="prose">${renderMarkdown(field.body)}</dd></div>
    `).join("")}</dl>
  </article>`;
}

function renderDatasetBenchmark(section) {
  const resource = section.dataset_benchmark;
  if (!resource) return `<div class="prose">${renderMarkdown(section.body)}</div>`;
  const datasetCards = resource.datasets.length
    ? resource.datasets.map((item) => resourceCard(item, "dataset")).join("")
    : `<p class="resource-empty">不使用额外训练或构建数据集。</p>`;
  const benchmarkCards = resource.benchmarks.length
    ? resource.benchmarks.map((item) => resourceCard(item, "benchmark")).join("")
    : `<p class="resource-empty">未解析到 Benchmark 配置。</p>`;
  const footerItems = [
    ["下游任务", resource.downstream_tasks],
    ["标注来源", resource.annotation_source],
    ["缺口与处理", resource.gaps],
  ].filter(([, body]) => body);
  return `<div class="resource-groups">
    <section class="resource-group">
      <div class="resource-group-heading"><h3>数据集</h3><span>${resource.datasets.length}</span></div>
      <div class="resource-card-grid">${datasetCards}</div>
    </section>
    <section class="resource-group">
      <div class="resource-group-heading"><h3>Benchmark</h3><span>${resource.benchmarks.length}</span></div>
      <div class="resource-card-grid benchmark-grid">${benchmarkCards}</div>
    </section>
    ${footerItems.length ? `<div class="resource-notes">${footerItems.map(([label, body]) => `
      <section><h3>${escapeHtml(label)}</h3><div class="prose">${renderMarkdown(body)}</div></section>
    `).join("")}</div>` : ""}
  </div>`;
}

function methodSections(idea) {
  const weaknessSection = {
    id: "method-weakness",
    title: "Weakness",
    customHtml: `<div class="prose lead-prose">${renderMarkdown(idea.weakness)}</div>`,
  };
  const causeSection = {
    id: "root-causes",
    title: "成因分析",
    customHtml: `<div class="cause-blocks">${idea.causes.map((cause) => `
      <article class="cause-block"><h3>原因 (${escapeHtml(cause.number)})：${escapeHtml(cause.title)}</h3><div class="prose">${renderMarkdown(cause.body)}</div></article>`).join("")}</div>`,
  };
  const contributionSection = {
    id: "method-contributions",
    title: "Contribution",
    customHtml: `<div class="contribution-grid">${idea.contributions.length
      ? idea.contributions.map((item, index) => contributionCard(item, index, idea.causes)).join("")
      : `<article class="contribution-card"><header><span>PASS</span></header><div class="prose"><p>公开 Benchmark 不足，未生成 Contribution。</p></div></article>`}</div>`,
  };
  return idea.causes.length
    ? [weaknessSection, causeSection, contributionSection, ...idea.method_sections]
    : [weaknessSection, contributionSection, ...idea.method_sections];
}

function renderMethod(idea) {
  const sections = methodSections(idea);
  $("#sectionNav").innerHTML = sections.map((section, index) =>
    `<a href="#${escapeHtml(section.id)}" class="${index === 0 ? "active" : ""}"><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(section.title)}</strong></a>`
  ).join("");
  $("#methodContent").innerHTML = sections.map((section, index) => `
    <section class="method-section" id="${escapeHtml(section.id)}">
      <span class="section-kicker">IDEA / ${String(index + 1).padStart(2, "0")}</span>
      <h2>${escapeHtml(section.title)}</h2>
      ${section.customHtml || (section.dataset_benchmark
        ? renderDatasetBenchmark(section)
        : `<div class="prose">${renderMarkdown(section.body)}</div>`)}
    </section>`).join("");
}

function renderReview(idea) {
  const review = idea.review;
  const label = verdictLabels[review.verdict] || review.verdict;
  $("#reviewVerdict").textContent = `${label}方案`;
  $("#scoreOverview").innerHTML = Object.entries(review.scores).map(([key, value]) => `
    <div class="score-item"><div class="score-label"><span>${scoreLabels[key] || key}</span><strong>${value}/5</strong></div><div class="score-track"><span style="width:${Math.max(0, Math.min(100, value * 20))}%"></span></div></div>`).join("");
  const fillList = (selector, values) => {
    $(selector).innerHTML = values.length ? values.map((item) => `<li>${escapeHtml(item)}</li>`).join("") : "<li>暂无评审记录</li>";
  };
  fillList("#strengthList", review.strengths);
  fillList("#riskList", review.major_risks);
  fillList("#revisionList", review.required_revisions);
}

function renderHumanReview(idea) {
  const labels = { approved: "已人工核验：通过", discarded: "已人工核验：废弃" };
  $("#humanReviewStatus").textContent = labels[idea.human_review] || "尚未人工核验";
  $$("[data-human-review]").forEach((button) => {
    const selected = button.dataset.humanReview === idea.human_review;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
    button.disabled = false;
  });
}

function renderIdea(idea) {
  $("#ideaNumber").textContent = String(idea.index).padStart(2, "0");
  $("#ideaTitle").textContent = idea.idea_title;
  $("#paperTitle").textContent = idea.paper_title;
  $("#paperMeta").innerHTML = [idea.authors, [idea.venue, idea.year].filter(Boolean).join(" · "), idea.domain]
    .filter(Boolean).map((value) => `<span>${escapeHtml(value)}</span>`).join("");
  const badge = $("#verdictBadge");
  badge.className = `verdict-badge ${idea.review.verdict}`;
  badge.textContent = verdictLabels[idea.review.verdict] || idea.review.verdict;
  $("#sourceLink").href = idea.source_url || idea.scholar_url || "#";
  $("#weaknessContent").innerHTML = renderMarkdown(idea.weakness);
  $("#overviewCauses").innerHTML = idea.causes.map((cause) => `
    <article class="overview-cause">
      <header><span>CAUSE ${String(cause.number).padStart(2, "0")}</span><h3>${escapeHtml(cause.title)}</h3></header>
      <div class="prose">${renderMarkdown(cause.body)}</div>
    </article>`).join("");
  $("#contributionGrid").innerHTML = idea.contributions.length
    ? idea.contributions.map((item, index) => contributionCard(item, index, idea.causes)).join("")
    : `<article class="contribution-card"><header><span>PASS</span></header><div class="prose"><p>公开数据或 Benchmark 暂时不足以支持可核验的 Contribution，因此保留为可行性审计结果。</p></div></article>`;
  renderMethod(idea);
  renderReview(idea);
  renderHumanReview(idea);
  showTab(state.tab);
}

function populateMobilePicker() {
  if (!state.data) return;
  $("#mobileIdeaSelect").innerHTML = state.data.ideas.map((idea) =>
    `<option value="${escapeHtml(idea.id)}" ${idea.id === state.activeId ? "selected" : ""}>${String(idea.index).padStart(2, "0")} · ${escapeHtml(idea.idea_title)}</option>`
  ).join("");
}

function showIdeaView() {
  $("#loadingState").hidden = true;
  $("#errorState").hidden = true;
  $("#mobilePicker").hidden = false;
  $("#ideaView").hidden = false;
}

function clearActiveIdea() {
  state.data = null;
  state.activeId = null;
  state.activeRun = null;
  state.tab = "overview";
  $("#loadingState").hidden = true;
  $("#errorState").hidden = true;
  $("#mobilePicker").hidden = true;
  $("#mobileIdeaSelect").innerHTML = "";
  $("#ideaView").hidden = true;

  const url = new URL(location.href);
  url.searchParams.delete("run");
  url.hash = "";
  history.replaceState(null, "", `${url.pathname}${url.search}`);

  renderFolderTree();
  closeSidebar();
  window.scrollTo({ top: 0, behavior: "instant" });
}

function selectIdea(id, updateUrl = true) {
  const idea = state.data?.ideas.find((item) => item.id === id);
  if (!idea) return;
  state.activeId = id;
  showIdeaView();
  renderFolderTree();
  populateMobilePicker();
  renderIdea(idea);
  if (updateUrl) {
    const url = new URL(location.href);
    url.searchParams.set("run", state.activeRun);
    url.hash = id;
    history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }
  closeSidebar();
  window.scrollTo({ top: 0, behavior: "instant" });
}

function showTab(tab) {
  state.tab = tab;
  $$("#viewTabs button").forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === tab));
}

const moduleBase = location.pathname.startsWith("/auto-search/") ? "/auto-search" : "";

async function fetchJson(url, options = {}) {
  const response = await fetch(`${moduleBase}${url}`, { cache: "no-store", ...options });
  let payload = {};
  try { payload = await response.json(); } catch (_) { payload = {}; }
  if (!response.ok) {
    const error = new Error(payload.error || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function loadRunDataset(runName) {
  if (state.datasets.has(runName)) return state.datasets.get(runName);
  const dataset = await fetchJson(`/api/runs/${encodeURIComponent(runName)}/ideas`);
  state.datasets.set(runName, dataset);
  return dataset;
}

async function openRunIdea(runName, ideaId) {
  try {
    const dataset = await loadRunDataset(runName);
    if (!dataset.ideas?.length) {
      state.datasets.delete(runName);
      clearActiveIdea();
      return;
    }
    state.data = dataset;
    state.activeRun = runName;
    state.expandedRuns.add(runName);
    state.tab = "overview";
    selectIdea(ideaId || dataset.ideas[0]?.id);
  } catch (error) {
    if (error.status === 404) {
      state.datasets.delete(runName);
      state.runs = state.runs.filter((run) => run.run_name !== runName);
      state.expandedRuns.delete(runName);
      clearActiveIdea();
      await refreshRuns(true);
      return;
    }
    showFatalError(error.message);
  }
}

async function refreshRuns(scheduleNext = true) {
  try {
    const payload = await fetchJson("/api/runs");
    state.runs = payload.runs;
    renderFolderTree();
    clearTimeout(state.pollTimer);
    if (scheduleNext && state.runs.some((run) => activeStatuses.has(run.status))) {
      state.pollTimer = setTimeout(() => refreshRuns(true), 1500);
    }
  } catch (error) {
    console.error(error);
  }
}

function toggleRun(runName) {
  const run = state.runs.find((item) => item.run_name === runName);
  if (!run || run.status !== "ready") return;
  if (state.expandedRuns.has(runName)) state.expandedRuns.delete(runName);
  else state.expandedRuns.add(runName);
  renderFolderTree();
}

function openNewResearchDialog() {
  $("#researchForm").reset();
  $("#directionLength").textContent = "0";
  $("#researchFormError").hidden = true;
  $("#submitResearch").disabled = false;
  $("#submitResearch").textContent = "创建调研";
  checkApi();
  $("#researchDialog").showModal();
  requestAnimationFrame(() => $("#directionInput").focus());
}

async function checkApi() {
  try {
    const health = await fetchJson("/api/health");
    $("#apiState").textContent = health.codex_cli ? "Codex CLI 已连接" : "Codex CLI 未配置";
    $("#apiState").className = health.codex_cli ? "api-state ready" : "api-state failed";
  } catch (_) {
    $("#apiState").textContent = "后端不可用";
    $("#apiState").className = "api-state failed";
  }
}

async function startResearch(event) {
  event.preventDefault();
  const errorElement = $("#researchFormError");
  const direction = $("#directionInput").value.trim();
  errorElement.hidden = true;
  if (direction.length < 3) {
    errorElement.textContent = "请输入至少 3 个字符的研究方向。";
    errorElement.hidden = false;
    return;
  }
  const button = $("#submitResearch");
  button.disabled = true;
  button.textContent = "正在创建";
  try {
    const job = await fetchJson("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        direction,
        paper_count: Number($("input[name=paperCount]:checked").value),
        evaluate: $("#evaluateToggle").checked,
      }),
    });
    $("#researchDialog").close();
    state.runs.unshift({ ...job, ideas: [], deletable: true });
    renderFolderTree();
    refreshRuns(true);
    openSidebar();
  } catch (error) {
    errorElement.textContent = error.message;
    errorElement.hidden = false;
    button.disabled = false;
    button.textContent = "创建调研";
  }
}

function openConfirm({ title, message, actionLabel, danger = true, action }) {
  state.confirmAction = action;
  $("#confirmTitle").textContent = title;
  $("#confirmMessage").textContent = message;
  const button = $("#confirmAction");
  button.textContent = actionLabel;
  button.className = danger ? "button danger" : "button primary";
  button.disabled = false;
  $("#confirmDialog").showModal();
}

async function confirmCurrentAction() {
  if (!state.confirmAction) return;
  const button = $("#confirmAction");
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "处理中";
  try {
    await state.confirmAction();
    state.confirmAction = null;
    $("#confirmDialog").close();
  } catch (error) {
    $("#confirmMessage").textContent = error.message;
    button.disabled = false;
    button.textContent = original;
  }
}

function requestStop(runName, jobId) {
  const run = state.runs.find((item) => item.run_name === runName);
  if (!run || !jobId) return;
  openConfirm({
    title: "停止调研并保留进度",
    message: `停止“${runLabel(run)}”的当前调用，保留论文、Idea 与评审产物，之后可以继续。`,
    actionLabel: "停止并保留",
    action: async () => {
      await fetchJson(`/api/jobs/${jobId}/stop`, { method: "POST" });
      state.datasets.delete(runName);
      renderFolderTree();
      await refreshRuns(true);
    },
  });
}

async function fallbackToDefaultRun() {
  try {
    const dataset = await loadRunDataset("medical-vlm-10");
    state.data = dataset;
    state.activeRun = "medical-vlm-10";
    state.activeId = dataset.ideas[0]?.id || null;
    state.expandedRuns.add("medical-vlm-10");
    if (state.activeId) selectIdea(state.activeId);
    else clearActiveIdea();
  } catch (error) {
    if (error.status === 404) {
      state.datasets.delete("medical-vlm-10");
      clearActiveIdea();
      return;
    }
    showFatalError(error.message);
  }
}

async function saveHumanReview(decision) {
  const idea = state.data?.ideas.find((item) => item.id === state.activeId);
  if (!idea || !["approved", "discarded"].includes(decision)) return;
  const nextDecision = idea.human_review === decision ? null : decision;

  const buttons = $$('[data-human-review]');
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const result = await fetchJson(
      `/api/runs/${encodeURIComponent(state.activeRun)}/ideas/${encodeURIComponent(idea.id)}/human-review`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: nextDecision }),
      }
    );
    idea.human_review = result.decision;
    const run = state.runs.find((item) => item.run_name === state.activeRun);
    const metadata = run?.ideas.find((item) => item.id === idea.id);
    if (metadata) metadata.human_review = result.decision;
    renderHumanReview(idea);
    renderFolderTree();
  } catch (error) {
    $("#humanReviewStatus").textContent = `保存失败：${error.message}`;
    buttons.forEach((button) => { button.disabled = false; });
  }
}

function requestDelete(run) {
  openConfirm({
    title: "删除调研文件夹",
    message: `确认永久删除“${runLabel(run)}”及其中全部论文证据、Weakness、Contribution、Idea 和评审文件？`,
    actionLabel: "删除文件夹",
    action: async () => {
      const deletingActiveRun = state.activeRun === run.run_name;
      await fetchJson(`/api/runs/${encodeURIComponent(run.run_name)}`, { method: "DELETE" });
      state.runs = state.runs.filter((item) => item.run_name !== run.run_name);
      state.datasets.delete(run.run_name);
      state.expandedRuns.delete(run.run_name);
      if (deletingActiveRun) clearActiveIdea();
      else renderFolderTree();
    },
  });
}

function showRunConfig(run) {
  const created = new Date(run.created_at);
  const createdText = Number.isNaN(created.getTime()) ? run.created_at : created.toLocaleString("zh-CN");
  $("#configDetails").innerHTML = `<dl>
    <div class="config-row"><dt>研究方向</dt><dd>${escapeHtml(run.direction)}</dd></div>
    <div class="config-row"><dt>论文数量</dt><dd>${run.paper_count}</dd></div>
    <div class="config-row"><dt>独立评审</dt><dd>${run.evaluate ? "开启" : "关闭"}</dd></div>
    <div class="config-row"><dt>创建时间</dt><dd>${escapeHtml(createdText)}</dd></div>
    <div class="config-row"><dt>当前状态</dt><dd>${escapeHtml(runStatusText(run))}</dd></div>
    <div class="config-row"><dt>文件夹</dt><dd>${escapeHtml(run.run_name)}</dd></div>
  </dl>`;
  $("#configDialog").showModal();
}

function openContextMenu(event, runName) {
  event.preventDefault();
  const run = state.runs.find((item) => item.run_name === runName);
  if (!run || activeStatuses.has(run.status)) return;
  state.contextRun = run;
  const menu = $("#folderContextMenu");
  menu.querySelector('[data-context-action="delete"]').hidden = !run.deletable;
  menu.hidden = false;
  const width = 156;
  const height = run.deletable ? 78 : 44;
  menu.style.left = `${Math.min(event.clientX, window.innerWidth - width - 8)}px`;
  menu.style.top = `${Math.min(event.clientY, window.innerHeight - height - 8)}px`;
  menu.querySelector("button:not([hidden])")?.focus({ preventScroll: true });
}

function closeContextMenu() {
  $("#folderContextMenu").hidden = true;
  state.contextRun = null;
}

function openSidebar() {
  $("#sidebar").classList.add("open");
  $("#sidebarScrim").hidden = false;
}

function closeSidebar() {
  $("#sidebar").classList.remove("open");
  $("#sidebarScrim").hidden = true;
}

function showFatalError(message) {
  $("#loadingState").hidden = true;
  $("#mobilePicker").hidden = true;
  $("#ideaView").hidden = true;
  $("#errorState").hidden = false;
  $("#errorState strong").textContent = "无法加载研究数据";
  $("#errorState span").textContent = message;
}

function wireEvents() {
  $("#mobileIdeaSelect").addEventListener("change", (event) => selectIdea(event.target.value));
  $("#viewTabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-tab]");
    if (button) showTab(button.dataset.tab);
  });
  $("#humanReviewActions").addEventListener("click", (event) => {
    const button = event.target.closest("[data-human-review]");
    if (button) saveHumanReview(button.dataset.humanReview);
  });
  $("#ideaList").addEventListener("click", (event) => {
    const resume = event.target.closest("[data-resume-run]");
    if (resume) {
      resume.disabled = true;
      fetchJson(`/api/runs/${encodeURIComponent(resume.dataset.resumeRun)}/resume`, { method: "POST" })
        .then(() => refreshRuns(true)).catch((error) => showFatalError(error.message)).finally(() => { resume.disabled = false; });
      return;
    }
    const stop = event.target.closest("[data-stop-job]");
    if (stop) {
      event.stopPropagation();
      requestStop(stop.dataset.run, stop.dataset.stopJob);
      return;
    }
    const idea = event.target.closest("[data-idea]");
    if (idea) {
      openRunIdea(idea.dataset.run, idea.dataset.idea);
      return;
    }
    const toggle = event.target.closest("[data-toggle-run], [data-folder-label]");
    if (toggle) toggleRun(toggle.dataset.toggleRun || toggle.dataset.folderLabel);
  });
  $("#ideaList").addEventListener("contextmenu", (event) => {
    const target = event.target.closest("[data-folder-row], [data-idea]");
    const runName = target?.dataset.folderRow || target?.dataset.run;
    if (runName) openContextMenu(event, runName);
  });
  $("#researchLaunch").addEventListener("click", openNewResearchDialog);
  $("#researchForm").addEventListener("submit", startResearch);
  $("#directionInput").addEventListener("input", (event) => {
    $("#directionLength").textContent = event.target.value.length;
  });
  $$('[data-close-dialog]').forEach((button) => button.addEventListener("click", () => {
    $("#" + button.dataset.closeDialog).close();
  }));
  $("#confirmCancel").addEventListener("click", () => {
    state.confirmAction = null;
    $("#confirmDialog").close();
  });
  $("#confirmAction").addEventListener("click", confirmCurrentAction);
  $("#folderContextMenu").addEventListener("click", (event) => {
    const action = event.target.closest("[data-context-action]")?.dataset.contextAction;
    const run = state.contextRun;
    closeContextMenu();
    if (!run) return;
    if (action === "config") showRunConfig(run);
    if (action === "delete") requestDelete(run);
  });
  $("#sidebarToggle").addEventListener("click", openSidebar);
  $("#sidebarScrim").addEventListener("click", closeSidebar);
  $(".brand").addEventListener("click", (event) => {
    event.preventDefault();
    fallbackToDefaultRun();
  });
  document.addEventListener("click", (event) => {
    if (event.button === 0 && !event.target.closest("#folderContextMenu")) closeContextMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeContextMenu();
  });
  window.addEventListener("resize", closeContextMenu);
  window.addEventListener("scroll", closeContextMenu);
}

async function init() {
  if (location.protocol === "file:") {
    document.body.innerHTML = '<main style="max-width:640px;margin:12vh auto;padding:28px;line-height:1.8"><h1>请从本地服务打开 Auto Search</h1><p>当前是 HTML 文件预览，无法连接任务接口。</p><p><a class="button primary" href="http://127.0.0.1:8760/auto-search/">打开 Auto Search 工作台</a></p><p>默认服务地址为 http://127.0.0.1:8760/。如果启动时设置了其他端口，请使用终端显示的地址。</p></main>';
    return;
  }
  wireEvents();
  try {
    const requestedRun = new URLSearchParams(location.search).get("run");
    const runName = requestedRun && /^(medical-vlm-10|direction-\d{8}-\d{6}-[a-f0-9]{6}|[\p{L}\p{N}_-]{1,60}-search-\d{8}-\d{6}-\d{6}(?:-[a-f0-9]{8})?)$/u.test(requestedRun)
      ? requestedRun : "medical-vlm-10";
    const dataset = await loadRunDataset(runName);
    if (!dataset.ideas?.length) {
      await refreshRuns(true);
      clearActiveIdea();
      return;
    }
    state.data = dataset;
    state.activeRun = runName;
    state.activeId = dataset.ideas.some((idea) => idea.id === location.hash.slice(1))
      ? location.hash.slice(1) : dataset.ideas[0]?.id;
    state.expandedRuns.add(runName);
    await refreshRuns(true);
    populateMobilePicker();
    if (state.activeId) renderIdea(dataset.ideas.find((idea) => idea.id === state.activeId));
    showIdeaView();
  } catch (error) {
    if (error.status === 404) {
      await refreshRuns(true);
      clearActiveIdea();
      return;
    }
    console.error(error);
    showFatalError(error.message);
  }
}

init();
