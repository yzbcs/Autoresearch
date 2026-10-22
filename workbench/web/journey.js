"use strict";

(() => {
  if (location.protocol === "file:") {
    document.querySelector("main").textContent =
      "请从工作台 HTTP 地址打开 /journey.html。";
    return;
  }
  const t = (text) => window.JourneyI18n.t(text);
  const $ = (selector) => document.querySelector(selector);
  const escape = (value) =>
    String(value ?? "").replace(
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
    done: "已完成",
    running: "运行中",
    waiting: "待处理",
    blocked: "需要处理",
    paused: "已暂停",
    pending: "未开始",
    skipped: "未纳入 / 已放弃",
    completed: "已完成",
    waiting_review: "等待审批",
    waiting_selection: "等待选题",
  };
  const symbols = {
    direction: "◎",
    papers: "▤",
    design: "▧",
    execution: "⚗",
    diagnosis: "▥",
    writing: "▤",
    table: "▦",
    figure: "◇",
    r0: "△",
    revision: "◇",
  };
  const stageTitles = {
    search: "调研与选题",
    design: "实验与审计",
    writing: "写作与引用",
    table: "表格与复核",
    figure: "主图与交付",
  };
  const stageModules = {
    search: "Auto Search",
    design: "Auto Design",
    writing: "Auto Writing",
    table: "Auto Table",
    figure: "Auto Figure",
  };
  let flows = [],
    selected =
      new URLSearchParams(location.search).get("flow") ||
      localStorage.getItem("workbench-flow"),
    data = null,
    selectedNode = null,
    selectedEvent = null,
    live = true,
    requestNumber = 0,
    pending = false;
  let camera = null,
    graphFlow = null,
    graphKey = "",
    dragStart = null,
    dragged = false;
  const rendered = new Map();
  function setMarkup(selector, html) {
    if (rendered.get(selector) === html) return;
    const element = $(selector),
      scroll = element.scrollLeft;
    const focused =
      document.activeElement?.closest("[data-event]")?.dataset.event;
    element.innerHTML = html;
    window.JourneyI18n.localize(element);
    rendered.set(selector, html);
    element.scrollLeft = scroll;
    if (selector === "#timeline" && focused)
      element
        .querySelector(`[data-event="${CSS.escape(focused)}"]`)
        ?.focus({ preventScroll: true });
  }
  function statusText(flow) {
    return flow.stage === "figure" && flow.status === "waiting_review"
      ? "等待确认参考图"
      : labels[flow.status] || flow.status;
  }
  function date(value, brief = false) {
    const d = new Date(value);
    if (Number.isNaN(d.valueOf())) return "时间未记录";
    return d.toLocaleString(
      window.JourneyI18n.locale,
      brief
        ? {
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          }
        : { hour12: false },
    );
  }
  function notice(text = "") {
    $("#notice").hidden = !text;
    $("#notice").textContent = text;
    window.JourneyI18n.localize($("#notice"));
  }
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
    const value = await response.json();
    if (!response.ok)
      throw new Error(value.error || `请求失败（${response.status}）`);
    return value;
  }
  function renderList() {
    $("#flow-count").textContent = flows.length;
    const query = $("#filter").value.trim().toLowerCase();
    const matches = flows.filter((f) =>
      `${f.title} ${f.direction || ""}`.toLowerCase().includes(query),
    );
    setMarkup(
      "#flow-list",
      matches
        .map(
          (f) =>
            `<button class="task-button ${f.id === selected ? "active" : ""}" data-flow="${escape(f.id)}" aria-pressed="${f.id === selected}"><span class="task-glyph">◈</span><span class="task-copy"><strong data-user-content>${escape(f.title)}</strong><small>${escape(statusText(f))} · ${escape(stageTitles[f.stage] || f.stage)}</small></span></button>`,
        )
        .join("") ||
        `<p class="muted">${query ? "没有匹配的研究任务。" : "还没有全流程任务。"}</p>`,
    );
  }
  function metrics() {
    const m = data.metrics,
      e = m.experiments;
    const items = [
      ["▤", m.papers, "篇论文", "实际调研记录"],
      ["♧", m.ideas, "个候选 Idea", "来自已保存的方案集"],
      [
        "⚗",
        e ? `${e.done} / ${e.total}` : null,
        "实验单元",
        e ? "已记录观测 / 计划单元" : "尚无可汇总的实验记录",
      ],
      ["⟳", m.iterations, "次设计调用", "设计与方法修改调用记录"],
    ];
    $("#metrics").innerHTML = items
      .map(
        ([symbol, value, label, note]) =>
          `<div class="metric"><span class="metric-icon" aria-hidden="true">${symbol}</span><div><strong>${escape(value ?? "—")}<small>${label}</small></strong><p>${note}</p></div></div>`,
      )
      .join("");
  }
  function renderGraph() {
    const key = JSON.stringify([data.nodes, data.edges, selectedNode]);
    if (key === graphKey) return;
    graphKey = key;
    const nodes = new Map(data.nodes.map((n) => [n.id, n]));
    const marker =
      '<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7" fill="#89aaa3"/></marker><marker id="amber-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7" fill="#d89422"/></marker></defs>';
    const edges = data.edges
      .map((e) => {
        const a = nodes.get(e.source),
          b = nodes.get(e.target);
        if (!a || !b) return "";
        let x = a.x + 140,
          y = a.y + 36,
          tx = b.x - 5,
          ty = b.y + 36;
        if (e.kind === "detour") {
          x = a.x + 70;
          y = a.y + (a.y > b.y ? 0 : 72);
          tx = b.x + 70;
          ty = b.y + (a.y > b.y ? 77 : -5);
        }
        const mx = (x + tx) / 2;
        const path =
          e.kind === "detour"
            ? `M${x} ${y} C${x} ${(y + ty) / 2} ${tx} ${(y + ty) / 2} ${tx} ${ty}`
            : `M${x} ${y} C${mx} ${y} ${mx} ${ty} ${tx} ${ty}`;
        return `<path class="route-edge ${escape(e.kind)} ${a.status === "done" ? "done" : ""}" d="${path}" marker-end="url(#${e.kind === "detour" ? "amber-arrow" : "arrow"})"/>`;
      })
      .join("");
    const markup = data.nodes
      .map((n) => {
        const subtitle =
          n.subtitle ||
          (n.progress
            ? `${n.progress.done} / ${n.progress.total} 观测单元`
            : labels[n.status]);
        return `<g class="route-node ${escape(n.status)} ${selectedNode === n.id ? "selected" : ""}" transform="translate(${n.x},${n.y})" data-node="${escape(n.id)}" role="button" tabindex="0" aria-label="${escape(t(n.title))}，${escape(t(subtitle))}" aria-pressed="${selectedNode === n.id}"><title>${escape(t(n.title))}：${escape(t(n.summary))}</title><rect width="140" height="72" rx="9"/><text class="node-symbol" x="12" y="37">${symbols[n.id] || "♧"}</text><text class="node-title" x="37" y="29" ${t(n.title).length > 13 ? 'textLength="92" lengthAdjust="spacingAndGlyphs"' : ""}>${escape(t(n.title))}</text><text class="node-subtitle" x="37" y="49" ${t(subtitle).length > 15 ? 'textLength="92" lengthAdjust="spacingAndGlyphs"' : ""}>${escape(t(subtitle))}</text>${n.status === "running" ? '<circle class="running-dot" cx="126" cy="13" r="4"/>' : ""}</g>`;
      })
      .join("");

    const fresh = graphFlow !== data.flow.id;
    const focused = document.activeElement?.getAttribute("data-node");
    if (!camera) {
      $("#route-map").innerHTML =
        marker +
        '<g class="svg-pan-zoom_viewport"><g id="route-content"></g></g>';
    }
    $("#route-content").innerHTML = edges + markup;
    if (!camera && window.svgPanZoom) {
      camera = svgPanZoom("#route-map", {
        viewportSelector: ".svg-pan-zoom_viewport",
        fit: true,
        center: true,
        minZoom: 0.3,
        maxZoom: 5,
        dblClickZoomEnabled: false,
        zoomScaleSensitivity: 0.18,
        onUpdatedCTM: updateOverview,
      });
    }
    if (camera) {
      camera.updateBBox();
      if (fresh) {
        camera.resize();
        camera.fit();
        camera.center();
      }
    }
    graphFlow = data.flow.id;
    if (focused)
      $("#route-map")
        .querySelector(`[data-node="${CSS.escape(focused)}"]`)
        ?.focus({ preventScroll: true });
    buildOverview();
    updateOverview();
    window.JourneyI18n.localize($("#route-content"));
  }
  function renderNode() {
    const n = data.nodes.find((n) => n.id === selectedNode);
    if (!n) {
      $("#node-detail").innerHTML =
        '<p class="muted">点击航线上的节点查看详情。</p>';
      return;
    }
    const progress = n.progress;
    const index = data.stages.findIndex((s) => s.id === n.stage),
      next = data.stages[index + 1];
    const pct = progress
      ? Math.min(100, Math.max(0, (progress.done / progress.total) * 100))
      : 0;
    setMarkup(
      "#node-detail",
      `<span class="status-pill ${escape(n.status)}">${escape(labels[n.status])}</span><h3>${escape(t(n.title))}</h3><p class="description" data-user-content>${escape(t(n.summary))}</p>${n.message && n.message !== n.summary ? `<p class="description" data-user-content>${escape(t(n.message))}</p>` : ""}${progress ? `<div class="progress-bar"><span style="width:${pct}%"></span></div><div class="progress-label">${progress.done} / ${progress.total} 观测单元</div><p class="muted">已记录观测不代表实验或审计通过。</p>` : ""}${n.checks?.length ? `<ul class="node-checks">${n.checks.map((c) => `<li><span>${c.done ? "✓" : "○"}</span>${escape(c.label)}<small>${c.done ? "已完成" : "未完成"}</small></li>`).join("")}</ul>` : ""}<h4>关联产物</h4><div>${n.artifacts.length ? n.artifacts.map((a) => `<a class="artifact" href="${escape(a.url)}" target="_blank" rel="noopener"><span class="artifact-icon">▤</span><span><strong data-user-content>${escape(a.name)}</strong><small>${a.size == null ? "打开已登记产物 ↗" : `${(a.size / 1024).toFixed(1)} KB · 查看原始文件 ↗`}</small></span></a>`).join("") : '<p class="muted">尚无可展示产物，完成对应步骤后会在这里出现。</p>'}</div><div class="detail-actions">${n.url ? `<a class="button" href="${escape(n.url)}">进入 ${stageModules[n.stage]} ↗</a>` : '<span class="muted">该模块尚未创建任务。</span>'}</div><div class="next-stop">↗ ${next ? `下一站：${escape(next.title)}` : "最终交付：下载前核对论文与复核记录"}<br><span class="muted">以原模块的证据与审批记录为准</span></div>`,
    );
  }
  function renderTimeline() {
    const events = data.events;
    // Render a bounded window without claiming to have historical state snapshots.
    const recent = events.slice(-120);
    if (!recent.length) {
      $("#timeline").innerHTML =
        '<p class="muted">尚无推进记录。任务开始推进后显示已记录事件。</p>';
      $("#event-detail").textContent = data.flow.message || "等待首次推进。";
      return;
    }
    if (!selectedEvent || !events.some((e) => eventKey(e) === selectedEvent))
      selectedEvent = eventKey(events[events.length - 1]);
    setMarkup(
      "#timeline",
      recent
        .map(
          (e, i) =>
            `<button class="event ${eventKey(e) === selectedEvent ? "selected" : ""}" data-event="${escape(eventKey(e))}" aria-pressed="${eventKey(e) === selectedEvent}" title="${escape(e.message)}"><span>${escape(stageTitles[e.stage] || e.stage)}</span><small>${date(e.at, true)}</small></button>`,
        )
        .join(""),
    );
    const event = events.find((e) => eventKey(e) === selectedEvent);
    window.JourneyI18n.localize($("#timeline"));
    $("#event-detail").textContent = event
      ? `${date(event.at)} · ${t(event.source === "pipeline" ? "流程记录" : "模块记录")} · ${event.message}`
      : "";
  }
  function eventKey(e) {
    return `${e.at}|${e.stage}|${e.message}`;
  }
  function render() {
    const f = data.flow;
    $("#welcome").hidden = true;
    $("#journey-workspace").hidden = false;
    $("#project-title").textContent = f.title;
    $("#updated-at").textContent = `任务更新 ${date(f.updated_at, true)}`;
    const badge = $("#flow-status");
    badge.hidden = false;
    badge.className = `status-pill ${f.status}`;
    badge.textContent = statusText(f);
    $("#manage-flow").href = `/?flow=${encodeURIComponent(f.id)}`;
    $("#pause-flow").hidden = !["running", "waiting_review"].includes(f.status);
    $("#pause-flow").disabled = pending;
    $("#stage-strip").innerHTML = data.stages
      .map(
        (s, i) =>
          `<button data-stage="${s.id}" class="${s.id === f.stage ? "current" : ""}">${String(i + 1).padStart(2, "0")} ${s.title}</button>`,
      )
      .join("");
    if (!data.nodes.some((n) => n.id === selectedNode))
      selectedNode =
        data.nodes.find(
          (n) =>
            n.stage === f.stage &&
            ["running", "waiting", "blocked", "paused"].includes(n.status),
        )?.id || data.nodes.find((n) => n.stage === f.stage)?.id;
    metrics();
    renderGraph();
    renderNode();
    renderTimeline();
    notice(data.warnings.join("；"));
    window.JourneyI18n.localize();
  }
  async function loadDetail() {
    const id = selected,
      number = ++requestNumber;
    const value = await api(`/api/pipelines/${encodeURIComponent(id)}/journey`);
    if (id !== selected || number !== requestNumber) return;
    const changed = JSON.stringify(value) !== JSON.stringify(data);
    data = value;
    if (changed) render();
    $("#refresh-time").textContent =
      `已同步 ${new Date().toLocaleTimeString(window.JourneyI18n.locale, { hour12: false })}`;
  }
  async function refresh() {
    if (!live || document.hidden) return;
    try {
      const listing = await api("/api/pipelines");
      flows = listing.pipelines;
      $("#connection").textContent = "研究服务已连接";
      $("#connection-dot").className = "connected";
      if (!flows.some((f) => f.id === selected)) {
        selected = flows[0]?.id;
        selectedNode = null;
        selectedEvent = null;
      }
      renderList();
      if (!selected) {
        requestNumber++;
        data = null;
        $("#welcome").hidden = false;
        $("#journey-workspace").hidden = true;
        $("#flow-status").hidden = true;
        $("#pause-flow").hidden = true;
        notice();
        return;
      }
      await loadDetail();
    } catch (error) {
      $("#connection").textContent = "连接中断";
      $("#connection-dot").className = "failed";
      notice(
        `${t("无法同步研究服务：")}${error.message}${t("。已保留最近一次画面，可返回工作台恢复服务。")}`,
      );
    }
  }
  async function poll() {
    await refresh();
    window.JourneyI18n.localize();
    setTimeout(poll, data?.flow.status === "running" ? 4000 : 10000);
  }
  function selectNode(id, locate = true) {
    selectedNode = id;
    renderGraph();
    renderNode();
    if (locate) focusNode(id);
  }
  function focusNode(id) {
    const n = data?.nodes.find((n) => n.id === id);
    if (!n || !camera) return;
    camera.resize();
    if (camera.getSizes().realZoom < 0.85)
      camera.zoom((camera.getZoom() * 0.85) / camera.getSizes().realZoom);
    const size = camera.getSizes();
    camera.pan({
      x: size.width / 2 - (n.x + 70) * size.realZoom,
      y: size.height / 2 - (n.y + 36) * size.realZoom,
    });
    updateOverview();
  }
  function updateOverview() {
    if (!data || !camera) return;
    const size = camera.getSizes(),
      pan = camera.getPan(),
      scale = size.realZoom;
    if (!scale) return;
    $("#zoom-level").value = `${Math.round(scale * 100)}%`;
    const windowRect = $("#minimap .mini-window");
    if (windowRect)
      for (const [key, value] of Object.entries({
        x: -pan.x / scale,
        y: -pan.y / scale,
        width: size.width / scale,
        height: size.height / scale,
      }))
        windowRect.setAttribute(key, String(value));
  }
  function buildOverview() {
    const nodes = new Map(data.nodes.map((n) => [n.id, n]));
    $("#minimap").innerHTML =
      data.edges
        .map((e) => {
          const a = nodes.get(e.source),
            b = nodes.get(e.target);
          return a && b
            ? `<path d="M${a.x + 70} ${a.y + 36}L${b.x + 70} ${b.y + 36}"/>`
            : "";
        })
        .join("") +
      data.nodes
        .map(
          (n) =>
            `<rect class="mini-node ${escape(n.status)}" x="${n.x}" y="${n.y}" width="140" height="72" rx="8"/>`,
        )
        .join("") +
      '<rect class="mini-window"/>';
  }

  function toggleSidebar(open) {
    $("#journey-sidebar").inert =
      matchMedia("(max-width:760px)").matches && !open;
    $("#journey-sidebar").classList.toggle("open", open);
    $("#journey-sidebar-toggle").setAttribute("aria-expanded", String(open));
    $("#journey-sidebar-scrim").hidden = !open;
    if (open) $("#filter").focus();
  }
  $("#journey-sidebar-toggle").onclick = () =>
    toggleSidebar(!$("#journey-sidebar").classList.contains("open"));
  $("#journey-sidebar-scrim").onclick = () => toggleSidebar(false);
  document.addEventListener("keydown", (e) => {
    if (
      e.key === "Escape" &&
      $("#journey-sidebar").classList.contains("open")
    ) {
      toggleSidebar(false);
      $("#journey-sidebar-toggle").focus();
    }
  });
  matchMedia("(max-width:760px)").addEventListener("change", () =>
    toggleSidebar(false),
  );
  toggleSidebar(false);
  document.addEventListener("journeylanguagechange", () => {
    graphKey = "";
    rendered.clear();
    renderList();
    if (data) render();
  });
  $("#filter").addEventListener("input", renderList);
  $("#flow-list").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-flow]");
    if (!b) return;
    toggleSidebar(false);
    selected = b.dataset.flow;
    selectedNode = null;
    selectedEvent = null;
    data = null;
    requestNumber++;
    localStorage.setItem("workbench-flow", selected);
    history.replaceState(null, "", `?flow=${encodeURIComponent(selected)}`);
    renderList();
    // Never leave another project's artifacts visible while the new request is in flight.
    $("#journey-workspace").hidden = true;
    $("#pause-flow").hidden = true;
    try {
      await loadDetail();
    } catch (error) {
      notice(error.message);
    }
  });
  $("#route-map").addEventListener("click", (e) => {
    const n = e.target.closest("[data-node]");
    if (n && !dragged) selectNode(n.dataset.node, false);
  });
  $("#route-map").addEventListener("keydown", (e) => {
    if (["Enter", " "].includes(e.key)) {
      const n = e.target.closest("[data-node]");
      if (n) {
        e.preventDefault();
        selectNode(n.dataset.node);
        $("#route-map")
          .querySelector(`[data-node="${CSS.escape(n.dataset.node)}"]`)
          ?.focus();
      }
    }
  });
  $("#stage-strip").addEventListener("click", (e) => {
    const b = e.target.closest("[data-stage]");
    if (b && data)
      selectNode(data.nodes.find((n) => n.stage === b.dataset.stage)?.id);
  });
  $("#timeline").addEventListener("click", (e) => {
    const b = e.target.closest("[data-event]");
    if (b) {
      selectedEvent = b.dataset.event;
      renderTimeline();
    }
  });
  $("#live-toggle").addEventListener("click", () => {
    live = !live;
    $("#live-toggle").setAttribute("aria-pressed", String(live));
    $("#connection").textContent = live ? "正在同步" : "已暂停页面同步";
    window.JourneyI18n.localize($(".connection"));
    if (live) refresh();
  });
  $("#zoom-in").onclick = () => camera?.zoomIn();
  $("#zoom-out").onclick = () => camera?.zoomOut();
  function fitGraph() {
    if (camera) {
      camera.resize();
      camera.fit();
      camera.center();
      updateOverview();
    }
  }
  $("#zoom-fit").onclick = fitGraph;
  $("#focus-current").onclick = () => {
    const n =
      data?.nodes.find(
        (n) =>
          n.stage === data.flow.stage &&
          ["running", "waiting", "blocked", "paused"].includes(n.status),
      ) || data?.nodes.find((n) => n.stage === data.flow.stage);
    if (n) selectNode(n.id);
  };
  new ResizeObserver(() => {
    if (camera) {
      camera.resize();
      updateOverview();
    }
  }).observe($("#canvas-scroll"));
  $("#map-fullscreen").onclick = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await $(".map-panel").requestFullscreen();
    } catch (error) {
      notice(`${t("无法进入全屏：")}${error.message}`);
    }
  };
  document.addEventListener("fullscreenchange", () => {
    fitGraph();
    $("#map-fullscreen").setAttribute(
      "aria-label",
      document.fullscreenElement ? "退出全屏" : "全屏航线",
    );
  });
  $("#export-map").onclick = () => {
    if (!data) return;
    const svg = $("#route-map").cloneNode(true);
    svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    svg.setAttribute("viewBox", "0 0 1580 550");
    svg.setAttribute("width", "1580");
    svg.setAttribute("height", "550");
    svg.removeAttribute("style");
    const group = svg.querySelector(".svg-pan-zoom_viewport");
    group.removeAttribute("transform");
    const style = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "style",
    );
    style.textContent = Array.from(document.styleSheets)
      .flatMap((sheet) => Array.from(sheet.cssRules || []))
      .map((rule) => rule.cssText)
      .filter((rule) => rule.includes(".route-") || rule.includes(":root"))
      .join("\n");
    svg.prepend(style);
    const url = URL.createObjectURL(
      new Blob([new XMLSerializer().serializeToString(svg)], {
        type: "image/svg+xml;charset=utf-8",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${data.flow.title.replace(/[\\/:*?"<>|]/g, "_")}-Research-Journey.svg`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  $("#canvas-scroll").addEventListener("keydown", (e) => {
    if (e.target.closest("[data-node]") || !camera) return;
    const moves = {
      ArrowLeft: { x: 50, y: 0 },
      ArrowRight: { x: -50, y: 0 },
      ArrowUp: { x: 0, y: 50 },
      ArrowDown: { x: 0, y: -50 },
    };
    if (moves[e.key]) {
      e.preventDefault();
      camera.panBy(moves[e.key]);
    } else if (["+", "=", "-", "0"].includes(e.key)) {
      e.preventDefault();
      if (e.key === "0") fitGraph();
      else if (e.key === "-") camera.zoomOut();
      else camera.zoomIn();
    }
  });
  $("#route-map").addEventListener("pointerdown", (e) => {
    dragStart = { x: e.clientX, y: e.clientY };
    dragged = false;
  });
  $("#route-map").addEventListener("pointermove", (e) => {
    if (
      dragStart &&
      Math.hypot(e.clientX - dragStart.x, e.clientY - dragStart.y) > 5
    )
      dragged = true;
  });
  window.addEventListener("pointerup", () => {
    dragStart = null;
  });
  $("#route-map").addEventListener("dblclick", (e) => {
    const n = data?.nodes.find(
      (n) => n.id === e.target.closest("[data-node]")?.dataset.node,
    );
    if (n?.url) location.href = n.url;
  });
  $("#minimap").addEventListener("click", (e) => {
    if (!camera) return;
    const point = $("#minimap").createSVGPoint();
    point.x = e.clientX;
    point.y = e.clientY;
    const p = point.matrixTransform($("#minimap").getScreenCTM().inverse()),
      s = camera.getSizes();
    camera.pan({
      x: s.width / 2 - p.x * s.realZoom,
      y: s.height / 2 - p.y * s.realZoom,
    });
  });
  let touch = null;
  const touchInfo = (e) => {
    const a = e.touches[0],
      b = e.touches[1] || a;
    return {
      x: (a.clientX + b.clientX) / 2,
      y: (a.clientY + b.clientY) / 2,
      d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY),
    };
  };
  $("#route-map").addEventListener(
    "touchstart",
    (e) => {
      if (camera) {
        touch = touchInfo(e);
        dragged = false;
      }
    },
    { passive: true },
  );
  $("#route-map").addEventListener(
    "touchmove",
    (e) => {
      if (!touch || !camera) return;
      e.preventDefault();
      const next = touchInfo(e);
      camera.panBy({ x: next.x - touch.x, y: next.y - touch.y });
      if (touch.d && next.d) {
        const r = $("#route-map").getBoundingClientRect();
        camera.zoomAtPointBy(next.d / touch.d, {
          x: next.x - r.left,
          y: next.y - r.top,
        });
      }
      if (
        Math.hypot(next.x - touch.x, next.y - touch.y) > 2 ||
        next.d !== touch.d
      )
        dragged = true;
      touch = next;
    },
    { passive: false },
  );
  $("#route-map").addEventListener("touchend", (e) => {
    touch = e.touches.length ? touchInfo(e) : null;
  });
  $("#pause-flow").addEventListener("click", async () => {
    if (pending || !data) return;
    pending = true;
    $("#pause-flow").disabled = true;
    const id = data.flow.id;
    try {
      await api(`/api/pipelines/${encodeURIComponent(id)}/pause`, {});
      if (selected === id) await loadDetail();
    } catch (error) {
      notice(error.message);
    } finally {
      pending = false;
      $("#pause-flow").disabled = false;
    }
  });
  poll();
})();
