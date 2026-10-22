"use strict";

// Kept in its own scope so the module pages can keep their existing state objects.
(() => {
  if (location.protocol === "file:") return;
  const $ = (s) => document.querySelector(s);
  const esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const labels = {
    running: "运行中",
    blocked: "需要处理",
    paused: "已暂停",
    waiting_selection: "等待选题",
    waiting_review: "等待审批",
    completed: "已完成",
  };
  let flows = [],
    selected =
      new URLSearchParams(location.search).get("flow") ||
      localStorage.getItem("workbench-flow"),
    detailKey = "",
    listKey = "",
    connected = false;
  let connectionNotice = false,
    creating = false;
  let sources = { search: [], design: [], writing: [], table: [] };
  async function api(path, payload) {
    const response = await fetch(path, {
      cache: "no-store",
      ...(payload === undefined
        ? {}
        : {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }),
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(data.error || `请求失败：${response.status}`);
    return data;
  }
  function notice(message = "") {
    connectionNotice = false;
    $("#workflow-notice").hidden = !message;
    $("#workflow-notice").textContent = message;
  }
  async function filePayload(file) {
    if (!file) return undefined;
    if (file.size > 20 * 1024 * 1024) throw new Error("模板不能超过 20 MB。");
    const content = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = () => reject(new Error("无法读取模板"));
      reader.readAsDataURL(file);
    });
    return { name: file.name, content_base64: content };
  }
  function renderSources() {
    const stage = $("#pipeline-stage").value,
      previous = $("#pipeline-source").value;
    $("#pipeline-source").innerHTML =
      `<option value="">${stage === "search" ? "新建调研任务" : "请选择已有任务"}</option>` +
      sources[stage]
        .map(
          (s) =>
            `<option value="${esc(s.id)}">${esc(s.title)} · ${esc(s.status)}</option>`,
        )
        .join("");
    if (sources[stage].some((s) => s.id === previous))
      $("#pipeline-source").value = previous;
    $("#direction-field").hidden =
      stage !== "search" || Boolean($("#pipeline-source").value);
  }
  async function loadSources() {
    const [s, d, w, t] = await Promise.all([
      api("/auto-search/api/runs"),
      api("/auto-design/api/tasks"),
      api("/auto-writing/api/writings"),
      api("/auto-table/api/projects"),
    ]);
    sources = {
      search: s.runs.map((r) => ({
        id: r.run_name,
        title: r.direction,
        status: r.status,
      })),
      design: d.tasks,
      writing: w.writings.map((p) => ({
        ...p,
        status: p.automation?.status || "独立写作",
      })),
      table: t.projects.filter((p) => p.mode === "manuscript"),
    };
    renderSources();
  }
  function render() {
    const nextListKey = JSON.stringify([
      selected,
      flows.map((f) => [f.id, f.title, f.status, f.stage, f.updated_at]),
    ]);
    if (nextListKey !== listKey) {
      listKey = nextListKey;
      $("#pipeline-list").innerHTML = flows.length
        ? flows
            .map(
              (f) =>
                `<button type="button" class="pipeline-item ${f.id === selected ? "active" : ""}" data-flow="${esc(f.id)}"><strong>${esc(f.title)}</strong><small>${esc(labels[f.status] || f.status)} · ${esc(f.stage)}<br>${esc(new Date(f.updated_at).toLocaleString("zh-CN"))}</small></button>`,
            )
            .join("")
        : '<p class="empty-copy">还没有全流程任务。现有模块任务可以从“新建全流程”接续。</p>';
    }
    const f = flows.find((item) => item.id === selected);
    if (!f) {
      $("#pipeline-detail").innerHTML =
        '<p class="empty-copy">选择一个全流程查看进展，或新建任务。</p>';
      detailKey = "";
      return;
    }
    const key = JSON.stringify(f);
    if (
      key === detailKey ||
      ($("#pipeline-detail").contains(document.activeElement) &&
        ["INPUT", "TEXTAREA", "SELECT"].includes(
          document.activeElement.tagName,
        ))
    )
      return;
    const note = $("#recovery-note")?.value || "";
    const previousHistory = $(".flow-history");
    const historyOpen =
      previousHistory?.open && previousHistory.dataset.flow === f.id;
    const historyMarkup =
      historyOpen && previousHistory.dataset.loaded
        ? $("#flow-event-items")?.innerHTML
        : null;
    detailKey = key;
    const links = [
      f.search_run &&
        `<a href="/auto-search/?run=${encodeURIComponent(f.search_run)}${f.idea_id ? `#${encodeURIComponent(f.idea_id)}` : ""}">调研与 Idea ↗</a>`,
      f.design_id &&
        `<a href="/auto-design/?task=${encodeURIComponent(f.design_id)}">实验、日志与审批 ↗</a>`,
      f.writing_id &&
        `<a href="/auto-writing/?project=${encodeURIComponent(f.writing_id)}">写作源码 ↗</a>`,
      f.table_id &&
        `<a href="/auto-table/?project=${encodeURIComponent(f.table_id)}">表格、PDF 与下载 ↗</a>`,
      f.figure_id &&
        `<a href="/auto-figure/?project=${encodeURIComponent(f.figure_id)}">方法主图与最终论文 ↗</a>`,
    ]
      .filter(Boolean)
      .join("　");
    $("#pipeline-detail").innerHTML =
      `<h3>${esc(f.title)}</h3><small>${esc(f.id)} · ${esc(f.stage === "figure" && f.status === "waiting_review" ? "等待确认参考图" : labels[f.status])}</small>
      <ol class="flow-stages"><li class="${f.stage === "search" ? "current" : ""}">01 调研与选题</li><li class="${f.stage === "design" ? "current" : ""}">02 实验与审计</li><li class="${f.stage === "writing" ? "current" : ""}">03 论文与 PDF</li><li class="${f.stage === "table" ? "current" : ""}">04 表格与复核</li>${f.figure_enabled || f.figure_id ? `<li class="${f.stage === "figure" ? "current" : ""}">05 主图与最终论文</li>` : ""}</ol>
      <p class="flow-message ${esc(f.status)}">${esc(f.message)}</p><div class="button-row">${links}</div>
      ${f.status !== "completed" ? `<label>恢复说明（可选，将传给当前步骤排查）<textarea id="recovery-note" rows="2" placeholder="描述遇到的问题或已经修复的环境；科学修改仍需专门审批">${esc(note)}</textarea></label><div class="button-row">${["running", "waiting_review"].includes(f.status) ? '<button type="button" data-flow-action="pause" class="secondary">暂停流程</button>' : '<button type="button" data-flow-action="resume">重试 / 继续当前步骤</button>'}<button type="button" data-flow-action="interrupt" class="secondary">停止卡住的控制器</button><button type="button" data-diagnostics class="secondary">查看错误与日志</button></div>` : `<p>${f.figure_id ? "全部阶段已完成，可打开 Auto Figure 下载可编辑 PPTX、独立主图 PDF 与含图完整论文。" : f.table_id ? "全部阶段已完成，可打开 AutoTable 下载最终 LaTeX 与 PDF。" : "历史写作流程已完成；可从已有写作任务新建流程接续 AutoTable。"}</p>`}
      ${f.status === "waiting_selection" ? '<div id="flow-candidates"></div>' : ""}
      ${f.status === "waiting_review" ? '<div id="flow-review"></div>' : ""}
      <div id="flow-diagnostics"></div>
      ${f.status !== "completed" && f.writing_id ? '<details><summary>更换论文模板</summary><label>LaTeX ZIP<input id="replacement-template" type="file" accept=".zip"></label><button type="button" data-template class="secondary">保存模板</button></details>' : ""}
      ${f.direction ? `<details><summary>完整研究方向</summary><pre>${esc(f.direction)}</pre></details>` : ""}<details class="flow-history" data-flow="${esc(f.id)}"><summary>推进与交接记录${f.event_count == null ? "" : ` · ${f.event_count} 条`}</summary><div id="flow-event-items"><p>展开后读取事件记录。</p></div><a href="/api/pipelines/${encodeURIComponent(f.id)}/events?all=1" download="${esc(f.id)}-events.json">下载完整记录 JSON ↗</a></details>`;
    if (historyOpen) {
      if (historyMarkup != null) {
        $("#flow-event-items").innerHTML = historyMarkup;
        $(".flow-history").dataset.loaded = "yes";
      }
      $(".flow-history").open = true;
    }
    if (f.status === "waiting_selection")
      loadCandidates(f).catch((e) => notice(e.message));
    if (f.status === "waiting_review")
      loadReview(f).catch((e) => notice(e.message));
  }
  async function loadEvents(id, before) {
    const block = $(".flow-history");
    if (!block || block.dataset.flow !== id || block.dataset.loading) return;
    block.dataset.loading = "yes";
    const area = $("#flow-event-items");
    try {
      const result = await api(
        `/api/pipelines/${encodeURIComponent(id)}/events${before == null ? "" : `?before=${before}`}`,
      );
      if (selected !== id || !area.isConnected) return;
      area.querySelector("[data-events-before]")?.remove();
      const html =
        result.events
          .map(
            (e) =>
              `<div class="flow-event"><time>${esc(e.at)} · ${esc(e.stage)}</time>${esc(e.message)}</div>`,
          )
          .join("") || "<p>等待首次推进。</p>";
      if (before == null) area.innerHTML = html;
      else area.insertAdjacentHTML("afterbegin", html);
      if (result.before != null)
        area.insertAdjacentHTML(
          "afterbegin",
          `<button type="button" class="secondary" data-events-before="${result.before}">加载较早记录</button>`,
        );
      block.dataset.loaded = "yes";
    } catch (error) {
      notice(`读取事件失败：${error.message}`);
    } finally {
      delete block.dataset.loading;
    }
  }
  $("#pipeline-detail").addEventListener(
    "toggle",
    (event) => {
      const block = event.target;
      if (block.matches(".flow-history") && block.open && !block.dataset.loaded)
        loadEvents(block.dataset.flow);
    },
    true,
  );
  async function loadCandidates(f) {
    const data = await api(`/api/pipelines/${f.id}?summary=1`);
    if (selected !== f.id || !$("#flow-candidates")) return;
    $("#flow-candidates").innerHTML =
      data.candidates
        .map(
          (i) =>
            `<div class="candidate"><strong>${esc(i.idea_title || i.paper_title)}</strong><p>评审：${esc(i.review.verdict)}<br>${esc(i.review.major_risks.join("\n"))}</p><button type="button" data-select-idea="${esc(i.id)}" ${i.eligible ? "" : "disabled"}>${i.eligible ? "采用此 Idea 并继续" : "已放弃，不可交接"}</button></div>`,
        )
        .join("") || "<p>没有可交接的 Idea，请查看调研结果。</p>";
  }
  async function loadReview(f) {
    const task = await api(`/auto-design/api/tasks/${f.design_id}`),
      review = task.review;
    if (selected !== f.id || !$("#flow-review") || !review) return;
    $("#flow-review").innerHTML =
      `<h4>方法修改提案 · ${esc(review.revision_id)}</h4><pre>${esc(review.proposal)}</pre><div class="button-row"><button type="button" data-decision="${review.limit_reached ? "APPROVE_EXCEPTION_METHOD_REVISION" : "APPROVE_MINIMAL_METHOD_REVISION"}" data-revision="${esc(review.revision_id)}" ${review.approved ? "disabled" : ""}>${review.approved ? "已批准" : review.limit_reached ? "批准本次例外修改" : "批准指定修改"}</button><button type="button" class="secondary" data-decision="REJECT_METHOD_REVISION" data-revision="${esc(review.revision_id)}" ${review.approved ? "disabled" : ""}>拒绝并暂停</button></div>`;
  }
  async function diagnostics(f) {
    let html = "";
    if (f.stage === "search" && f.search_run) {
      const data = await api("/auto-search/api/runs"),
        run = data.runs.find((r) => r.run_name === f.search_run);
      html = `<h4>调研错误与事件</h4><pre>${esc(run?.error || "当前没有错误记录。")}</pre><pre>${esc((run?.events || []).map((e) => `${e.at} ${e.message}`).join("\n"))}</pre>`;
    } else if (f.stage === "design" && f.design_id) {
      const task = await api(`/auto-design/api/tasks/${f.design_id}`);
      html =
        `<h4>实验诊断</h4><pre>${esc(task.error || task.activity || task.summary)}</pre>` +
        task.attempts
          .map((a, i) => {
            const dir = `assets/logs/${String(i + 1).padStart(4, "0")}-${a.action}`;
            return `<p>${esc(a.action)} · ${esc(a.started_at)}　<a target="_blank" rel="noopener" href="/auto-design/api/tasks/${f.design_id}/files/${dir}/stderr.log">错误日志</a>　<a target="_blank" rel="noopener" href="/auto-design/api/tasks/${f.design_id}/files/${dir}/events.jsonl">完整事件</a></p>`;
          })
          .join("");
    } else if (f.stage === "figure" && f.figure_id) {
      const p = await api(
        `/auto-figure/api/projects/${encodeURIComponent(f.figure_id)}`,
      );
      html = `<h4>主图生成与复核</h4><p>${esc(p.message)}</p><a href="/auto-figure/?project=${encodeURIComponent(f.figure_id)}">查看日志、复核与最终产物 ↗</a>`;
    } else if (f.stage === "table" && f.table_id) {
      const project = await api(`/auto-table/api/projects/${f.table_id}`);
      html = `<h4>表格诊断与复核</h4><pre>${esc(project.error || project.message)}</pre><pre>${esc(JSON.stringify(project.review, null, 2))}</pre><a href="/auto-table/?project=${encodeURIComponent(f.table_id)}">查看完整日志、修改要求与下载产物 ↗</a>`;
    } else if (f.writing_id) {
      const logs = await api(`/auto-writing/api/writings/${f.writing_id}/logs`);
      html =
        "<h4>写作调用与编译日志</h4>" +
        (logs.logs
          .map(
            (l) =>
              `<details><summary>${esc(l.name)}</summary><pre>${esc(l.text)}</pre></details>`,
          )
          .join("") || "<p>尚无调用日志。</p>");
    }
    if (selected === f.id && $("#flow-diagnostics"))
      $("#flow-diagnostics").innerHTML = html;
  }
  async function refresh() {
    if (document.hidden) {
      setTimeout(refresh, 4000);
      return;
    }
    try {
      const data = await api("/api/pipelines?summary=1");
      connected = true;
      flows = data.pipelines;
      if (!flows.some((f) => f.id === selected)) selected = flows[0]?.id;
      render();
      $("#create-pipeline").disabled = creating;
      if (connectionNotice) notice();
    } catch (e) {
      connected = false;
      $("#create-pipeline").disabled = true;
      notice(
        "研究服务未连接，可在“服务连接与恢复”启动服务。已有任务保留在磁盘。",
      );
      connectionNotice = true;
    }
    setTimeout(refresh, 4000);
  }
  async function serviceState() {
    try {
      const s = await api("/api/service");
      $("#service-status").textContent = s.restarting
        ? "正在重启"
        : s.connected
          ? "已连接"
          : "未连接";
      $("#service-message").textContent = s.message;
      $("#restart-service").disabled = s.restarting;
      $("#save-service").disabled = s.restarting;
      if (!$("#codex-path").dataset.loaded) {
        $("#codex-path").value = s.settings.CODEX_CLI || "";
        $("#latex-path").value = s.settings.LATEX_COMPILER || "";
        $("#codex-path").dataset.loaded = "yes";
      }
    } catch (_) {
      $("#service-status").textContent = connected
        ? "已连接（直接运行）"
        : "服务入口不可用";
      $("#service-message").textContent =
        "浏览器服务恢复需要通过 python3 -m workbench 启动工作台。";
      $("#restart-service").disabled = true;
      $("#save-service").disabled = true;
    }
    setTimeout(serviceState, 3000);
  }
  $("#toggle-create").addEventListener("click", async () => {
    $("#pipeline-form").hidden = !$("#pipeline-form").hidden;
    if (!$("#pipeline-form").hidden)
      try {
        await loadSources();
      } catch (e) {
        notice(e.message);
      }
  });
  $("#pipeline-stage").addEventListener("change", () => {
    $("#pipeline-source").value = "";
    renderSources();
  });
  $("#pipeline-source").addEventListener("change", () => {
    $("#direction-field").hidden =
      $("#pipeline-stage").value !== "search" ||
      Boolean($("#pipeline-source").value);
  });
  $("#pipeline-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (creating) return;
    creating = true;
    const button = $("#create-pipeline");
    button.disabled = true;
    try {
      const payload = Object.fromEntries(new FormData(event.target));
      payload.template_file = await filePayload(
        $("#pipeline-template").files[0],
      );
      const f = await api("/api/pipelines", payload);
      flows.unshift(f);
      selected = f.id;
      localStorage.setItem("workbench-flow", selected);
      notice();
      $("#pipeline-form").hidden = true;
      render();
    } catch (e) {
      notice(e.message);
    } finally {
      creating = false;
      button.disabled = !connected;
    }
  });
  $("#pipeline-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-flow]");
    if (button) {
      selected = button.dataset.flow;
      detailKey = "";
      localStorage.setItem("workbench-flow", selected);
      render();
    }
  });
  $("#pipeline-detail").addEventListener("click", async (event) => {
    const button = event.target.closest("button"),
      f = flows.find((x) => x.id === selected);
    if (!button || !f) return;
    button.disabled = true;
    try {
      if (button.hasAttribute("data-events-before")) {
        await loadEvents(f.id, Number(button.dataset.eventsBefore));
        return;
      }
      notice();
      const note = $("#recovery-note")?.value || "";
      if (button.dataset.flowAction)
        await api(`/api/pipelines/${f.id}/${button.dataset.flowAction}`, {
          recovery_note: note,
        });
      else if (button.dataset.selectIdea)
        await api(`/api/pipelines/${f.id}/select`, {
          idea_id: button.dataset.selectIdea,
        });
      else if (button.dataset.decision)
        await api(`/auto-design/api/tasks/${f.design_id}/decision`, {
          revision_id: button.dataset.revision,
          decision: button.dataset.decision,
        });
      else if (button.hasAttribute("data-diagnostics")) await diagnostics(f);
      else if (button.hasAttribute("data-template")) {
        const template_file = await filePayload(
          $("#replacement-template").files[0],
        );
        if (!template_file) throw new Error("请选择模板 ZIP。");
        await api(`/api/pipelines/${f.id}/template`, { template_file });
      }
    } catch (e) {
      notice(e.message);
    } finally {
      button.disabled = false;
    }
  });
  for (const id of ["restart-service", "save-service"])
    $("#" + id).addEventListener("click", async (event) => {
      event.target.disabled = true;
      try {
        await api(
          "/api/service/restart",
          id === "save-service"
            ? {
                settings: {
                  CODEX_CLI: $("#codex-path").value,
                  LATEX_COMPILER: $("#latex-path").value,
                },
              }
            : {},
        );
        notice("已请求重启。重新连接后，点击任务的继续按钮恢复。");
      } catch (e) {
        notice(e.message);
        event.target.disabled = false;
      }
    });
  if (new URLSearchParams(location.search).get("create") === "1") {
    $("#pipeline-form").hidden = false;
    loadSources().catch((e) => notice(e.message));
  }
  refresh();
  serviceState();
})();
