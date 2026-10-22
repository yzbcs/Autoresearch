"use strict";

(() => {
  const module =
    document.body.dataset.module?.replace("auto-", "") || "pipeline";
  const definitions = {
    pipeline: ["#pipeline-list [data-flow], #flow-list [data-flow]", "flow"],
    search: ["#ideaList [data-folder-row]", "folderRow"],
    design: ["#task-list [data-delete-task]", "deleteTask"],
    writing: ["#projectList [data-project-id]", "projectId"],
    table: ["#projectList [data-project]", "project"],
    figure: ["#projects [data-id]", "id"],
  };
  const definition = definitions[module];
  if (!definition) return;
  const english = () => document.documentElement.lang === "en";
  let busy = false,
    scheduled = false;
  function decorate() {
    for (const row of document.querySelectorAll(definition[0])) {
      if (row.parentElement.classList.contains("list-delete-row")) continue;
      const wrapper = document.createElement("div");
      wrapper.className = "list-delete-row";
      row.before(wrapper);
      wrapper.append(row);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "list-delete-button";
      button.dataset.userContent = "";
      button.textContent = english() ? "Delete" : "删除";
      button.setAttribute("aria-label", button.textContent);
      button.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (busy) return;
        const title =
          row.querySelector("strong")?.textContent || row.textContent.trim();
        const scope =
          module === "pipeline"
            ? english()
              ? "Delete this workflow and its exclusive task files? Tasks shared with other workflows will be kept."
              : "删除此全流程及其独占任务文件？其他流程共用的任务会保留。"
            : english()
              ? "Delete this task and its input, output and log files?"
              : "删除此任务及其输入、产物和日志文件？";
        if (
          !confirm(
            `${title}\n\n${scope}\n${english() ? "This cannot be undone. Stop running tasks first." : "删除后无法恢复，运行中的任务请先暂停。"}`,
          )
        )
          return;
        busy = true;
        button.disabled = true;
        try {
          const response = await fetch(
            `/api/items/${module}/${encodeURIComponent(row.dataset[definition[1]])}`,
            { method: "DELETE" },
          );
          const result = await response.json();
          if (!response.ok) throw new Error(result.error);
          if (result.cleanup_pending?.length)
            alert(
              (english()
                ? "Task removed; some files require manual cleanup: "
                : "任务已移除，部分文件需手动清理：") +
                result.cleanup_pending.join("\n"),
            );
          location.href = location.pathname;
        } catch (error) {
          alert(error.message);
        } finally {
          busy = false;
          button.disabled = false;
        }
      });
      wrapper.append(button);
    }
  }
  const container = document.querySelector(
    {
      pipeline: location.pathname.endsWith("journey.html")
        ? "#flow-list"
        : "#pipeline-list",
      search: "#ideaList",
      design: "#task-list",
      writing: "#projectList",
      table: "#projectList",
      figure: "#projects",
    }[module],
  );
  if (!container) return;
  new MutationObserver(() => {
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        decorate();
      });
    }
  }).observe(container, { childList: true, subtree: true });
  document.addEventListener("journeylanguagechange", () => {
    for (const b of container.querySelectorAll(".list-delete-button")) {
      b.textContent = english() ? "Delete" : "删除";
      b.setAttribute("aria-label", b.textContent);
    }
  });
  decorate();
})();
