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
  function askPassphrase(title, scope) {
    return new Promise((resolve) => {
      const dialog = document.createElement("dialog");
      dialog.className = "delete-passphrase-dialog";
      const form = document.createElement("form");
      form.method = "dialog";
      const heading = document.createElement("h2");
      heading.textContent = english() ? "Confirm deletion" : "验证删除口令";
      const description = document.createElement("p");
      description.textContent = `${title}\n${scope}`;
      const label = document.createElement("label");
      label.textContent = english() ? "Deletion passphrase" : "删除口令";
      const input = document.createElement("input");
      input.type = "password";
      input.autocomplete = "off";
      input.required = true;
      input.maxLength = 1024;
      label.append(input);
      const warning = document.createElement("p");
      warning.textContent = english() ? "Associated server files will be permanently deleted. Stop tasks first." : "将永久删除服务器上的关联文件，请先暂停任务。";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = english() ? "Cancel" : "取消";
      cancel.addEventListener("click", () => dialog.close());
      const submit = document.createElement("button");
      submit.type = "submit";
      submit.textContent = english() ? "Verify and delete" : "验证并删除";
      form.append(heading, description, label, warning, cancel, submit);
      let value = null;
      form.addEventListener("submit", () => { value = input.value; });
      dialog.addEventListener("close", () => {
        input.value = "";
        dialog.remove();
        resolve(value);
      }, {once: true});
      dialog.append(form);
      document.body.append(dialog);
      dialog.showModal();
      input.focus();
    });
  }
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
        busy = true;
        let passphrase = await askPassphrase(title, scope);
        if (passphrase === null) { busy = false; return; }
        button.disabled = true;
        try {
          const response = await fetch(
            `/api/items/${module}/${encodeURIComponent(row.dataset[definition[1]])}`,
            { method: "DELETE", headers: {"Content-Type": "application/json"}, body: JSON.stringify({passphrase}) },
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
          passphrase = null;
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
