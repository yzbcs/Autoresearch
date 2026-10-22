"use strict";

(() => {
  const module = document.body.dataset.module;
  if (!module) return;
  const nav = document.createElement("nav");
  nav.className = "module-nav";
  nav.setAttribute("aria-label", "研究模块");
  for (const [path, name] of [["", "工作台"], ["auto-search", "Auto Search"], ["auto-design", "Auto Design"], ["auto-writing", "Auto Writing"], ["auto-table", "Auto Table"], ["auto-figure", "Auto Figure"]]) {
    const link = document.createElement("a");
    link.href = path ? `/${path}/` : "/";
    link.textContent = name;
    if (path === module) link.setAttribute("aria-current", "page");
    nav.append(link);
  }
  document.querySelector(".topbar").append(nav);
  const journey = document.createElement("a");
  journey.href = "/journey.html";
  journey.textContent = "科研航线";
  nav.insertBefore(journey, nav.children[1]);
})();
