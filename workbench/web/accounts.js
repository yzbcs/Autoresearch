"use strict";

(() => {
  const message = document.querySelector("#accounts-message");
  const list = document.querySelector("#accounts-list");
  const registration = document.querySelector("#registration-open");
  const dialog = document.querySelector("#reset-password");
  let resetting = null;
  let current = null;

  async function api(path, payload) {
    const response = await fetch(path, {
      cache: "no-store",
      ...(payload
        ? {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }
        : {}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "操作失败。");
    return data;
  }
  function feedback(text, failed = false) {
    message.textContent = text;
    message.style.color = failed ? "#a43838" : "#087d70";
  }
  async function update(user, payload) {
    await api(`/api/admin/users/${user.id}`, payload);
    await refresh();
  }
  function button(label, action) {
    const element = document.createElement("button");
    element.type = "button";
    element.className = "secondary";
    element.textContent = label;
    element.addEventListener("click", async () => {
      element.disabled = true;
      try {
        await action();
      } catch (failure) {
        feedback(failure.message, true);
      } finally {
        element.disabled = false;
      }
    });
    return element;
  }
  async function refresh() {
    const data = await api("/api/admin/users");
    registration.checked = data.registration_open;
    list.replaceChildren(
      ...data.users.map((user) => {
        const row = document.createElement("tr");
        const cells = Array.from({ length: 5 }, () =>
          document.createElement("td"),
        );
        const name = document.createElement("strong");
        name.textContent = user.display_name;
        const detail = document.createElement("small");
        detail.textContent =
          user.username + (user.legacy_owner ? " · 现有项目管理员" : "");
        cells[0].append(name, detail);
        cells[1].textContent = user.role === "admin" ? "管理员" : "成员";
        const status = document.createElement("span");
        status.className = "account-state" + (user.active ? "" : " disabled");
        status.textContent = user.active ? "已启用" : "已停用";
        cells[2].append(status);
        cells[3].textContent = user.last_login
          ? new Date(user.last_login * 1000).toLocaleString("zh-CN")
          : "尚未登录";
        const actions = document.createElement("div");
        actions.className = "account-table-actions";
        if (user.id === current.id) {
          cells[4].textContent = "当前账号";
        } else {
          actions.append(
            button(user.active ? "停用" : "启用", async () => {
              if (
                user.active &&
                !window.confirm(
                  `停用 ${user.username} 后，该账号将退出登录，其控制器会安全停止。科研数据会保留。`,
                )
              )
                return;
              await update(user, { active: !Boolean(user.active) });
              feedback("账号状态已更新。");
            }),
          );
          actions.append(
            button(
              user.role === "admin" ? "设为成员" : "设为管理员",
              async () => {
                if (
                  !window.confirm(
                    `确认更改 ${user.username} 的角色？该账号将需要重新登录。`,
                  )
                )
                  return;
                await update(user, {
                  role: user.role === "admin" ? "member" : "admin",
                });
                feedback("账号角色已更新。");
              },
            ),
          );
          actions.append(
            button("重置密码", () => {
              resetting = user;
              dialog.querySelector("form").reset();
              dialog.querySelector(".account-error").hidden = true;
              document.querySelector("#reset-username").textContent =
                user.username;
              dialog.showModal();
            }),
          );
          cells[4].append(actions);
        }
        row.append(...cells);
        return row;
      }),
    );
  }
  registration.addEventListener("change", async () => {
    registration.disabled = true;
    try {
      await api("/api/admin/settings", {
        registration_open: registration.checked,
      });
      feedback(registration.checked ? "注册入口已开放。" : "注册入口已关闭。");
    } catch (failure) {
      registration.checked = !registration.checked;
      feedback(failure.message, true);
    } finally {
      registration.disabled = false;
    }
  });
  dialog
    .querySelector("button.secondary")
    .addEventListener("click", () => dialog.close());
  dialog.querySelector("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const submit = form.querySelector('[type="submit"]');
    const error = dialog.querySelector(".account-error");
    submit.disabled = true;
    try {
      if (form.elements.password.value !== form.elements.confirmation.value)
        throw new Error("两次输入的新密码不一致。");
      await update(resetting, { password: form.elements.password.value });
      dialog.close();
      feedback("密码已重置，该账号需要重新登录。");
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });
  window.autoresearchAccount
    .then((session) => {
      current = session.user;
      return refresh();
    })
    .catch((failure) => feedback(failure.message, true));
})();
