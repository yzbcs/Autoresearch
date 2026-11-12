"use strict";

(() => {
  const nativeFetch = window.fetch.bind(window);
  const ready = nativeFetch("/api/auth/session", { cache: "no-store" }).then(
    (response) => response.json(),
  );
  window.autoresearchAccount = ready;
  window.fetch = async (input, options) => {
    const request = new Request(input, options);
    if (
      new URL(request.url).origin !== location.origin ||
      !new URL(request.url).pathname.includes("/api/")
    )
      return nativeFetch(input, options);
    const session = await ready;
    const headers = new Headers(request.headers);
    if (session.authenticated) {
      headers.set("X-AutoResearch-Account", session.user.id);
      if (!["GET", "HEAD"].includes(request.method))
        headers.set("X-CSRF-Token", session.csrf_token);
    }
    const response = await nativeFetch(new Request(request, { headers }));
    if (response.status === 401)
      location.replace(
        "/login.html?next=" +
          encodeURIComponent(location.pathname + location.search),
      );
    return response;
  };

  function clearSelection() {
    localStorage.removeItem("workbench-flow");
    localStorage.removeItem("auto-writing-active-project");
    localStorage.removeItem("autoresearch-account");
  }

  async function installAccountMenu() {
    const session = await ready;
    if (!session.authenticated) {
      location.replace("/login.html");
      return;
    }
    const header = document.querySelector(".topbar");
    if (!header) return;
    if (session.user.role !== "admin") {
      const saveService = document.querySelector("#save-service");
      if (saveService) saveService.hidden = true;
      for (const selector of ["#codex-path", "#latex-path"]) {
        const input = document.querySelector(selector);
        if (input) input.disabled = true;
      }
    }
    const menu = document.createElement("details");
    menu.className = "account-menu";
    menu.innerHTML =
      '<summary aria-label="账号菜单"><span class="account-avatar"></span><span class="account-username"></span></summary><div class="account-dropdown"><small></small></div>';
    menu.querySelector(".account-avatar").textContent =
      session.user.display_name[0].toUpperCase();
    menu.querySelector(".account-username").textContent =
      session.user.display_name;
    const dropdown = menu.querySelector(".account-dropdown");
    dropdown.querySelector("small").textContent =
      session.user.username +
      (session.user.role === "admin" ? " · 管理员" : " · 科研账号");
    if (session.user.role === "admin") {
      const management = document.createElement("a");
      management.href = "/accounts.html";
      management.textContent = "账号管理";
      dropdown.append(management);
    }
    const password = document.createElement("button");
    password.type = "button";
    password.textContent = "修改密码";
    const logout = document.createElement("button");
    logout.type = "button";
    logout.textContent = "退出登录";
    if (session.connection?.enabled) {
      const network = document.createElement("button");
      network.type = "button";
      network.textContent = "本机代理连接";
      dropdown.append(network);
      const networkDialog = document.createElement("dialog");
      networkDialog.className = "account-dialog";
      networkDialog.innerHTML = '<h2>本机代理连接</h2><p class="connection-note" role="status"></p><p class="field-hint">科研任务使用发起时的 SSH 代理连接。请保持本机代理和 SSH 隧道在线。</p><div class="account-dialog-actions"><button class="secondary" type="button">关闭</button><button class="connection-test" type="button">测试 Codex 连接</button></div>';
      document.body.append(networkDialog);
      const note = networkDialog.querySelector(".connection-note");
      const test = networkDialog.querySelector(".connection-test");
      let timer;
      function showConnection(state) {
        const running = state.test.status === "running";
        note.textContent = state.connected && state.test.status !== "idle"
          ? state.test.message : state.message;
        test.disabled = !state.connected || running;
        test.textContent = running ? "正在测试" : "测试 Codex 连接";
        clearTimeout(timer);
        if (networkDialog.open) timer = setTimeout(refreshConnection, running ? 1500 : 5000);
      }
      async function refreshConnection() {
        try {
          const response = await fetch("/api/connection", { cache: "no-store" });
          const state = await response.json();
          if (!response.ok) throw new Error(state.error);
          showConnection(state);
        } catch (error) {
          note.textContent = error.message;
          test.disabled = true;
        }
      }
      network.addEventListener("click", () => {
        menu.open = false;
        networkDialog.showModal();
        refreshConnection();
      });
      networkDialog.querySelector(".secondary").addEventListener("click", () => networkDialog.close());
      networkDialog.addEventListener("close", () => clearTimeout(timer));
      test.addEventListener("click", async () => {
        test.disabled = true;
        try {
          const response = await fetch("/api/connection/test", { method: "POST" });
          const state = await response.json();
          if (!response.ok) throw new Error(state.error);
          showConnection(state);
        } catch (error) {
          note.textContent = error.message;
          test.disabled = false;
        }
      });
    }
    dropdown.append(password, logout);
    header.append(menu);
    document.addEventListener("click", (event) => {
      if (!menu.contains(event.target)) menu.open = false;
    });
    logout.addEventListener("click", async () => {
      logout.disabled = true;
      try {
        const response = await fetch("/api/auth/logout", { method: "POST" });
        if (!response.ok) throw new Error("退出失败，请重试。");
        clearSelection();
        location.assign("/login.html");
      } catch (failure) {
        logout.textContent = failure.message;
        logout.disabled = false;
      }
    });
    const dialog = document.createElement("dialog");
    dialog.className = "account-dialog";
    dialog.innerHTML =
      '<form><h2>修改密码</h2><p class="account-error" role="alert" hidden></p><label>当前密码<input name="current_password" type="password" autocomplete="current-password" required maxlength="128"></label><label>新密码<input name="password" type="password" autocomplete="new-password" required minlength="6" maxlength="128"></label><label>确认新密码<input name="confirmation" type="password" autocomplete="new-password" required minlength="6" maxlength="128"></label><div class="account-dialog-actions"><button class="secondary" type="button">取消</button><button type="submit">更新密码</button></div></form>';
    document.body.append(dialog);
    password.addEventListener("click", () => {
      menu.open = false;
      dialog.querySelector("form").reset();
      dialog.querySelector(".account-error").hidden = true;
      dialog.showModal();
    });
    dialog
      .querySelector("button.secondary")
      .addEventListener("click", () => dialog.close());
    dialog.querySelector("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.target;
      const error = dialog.querySelector(".account-error");
      const button = form.querySelector('[type="submit"]');
      button.disabled = true;
      try {
        if (form.elements.password.value !== form.elements.confirmation.value)
          throw new Error("两次输入的新密码不一致。");
        const response = await fetch("/api/auth/password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            current_password: form.elements.current_password.value,
            password: form.elements.password.value,
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        clearSelection();
        location.assign("/login.html");
      } catch (failure) {
        error.textContent = failure.message;
        error.hidden = false;
      } finally {
        button.disabled = false;
      }
    });
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", () =>
      installAccountMenu().catch(() => location.replace("/login.html")),
    );
  else installAccountMenu().catch(() => location.replace("/login.html"));
})();
