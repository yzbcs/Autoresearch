"use strict";

(() => {
  const form = document.querySelector("#auth-form");
  const error = document.querySelector("#auth-error");
  const submit = document.querySelector("#auth-submit");
  let mode = "login";
  let registrationOpen = false;
  const next = new URLSearchParams(location.search).get("next") || "/";
  const destination =
    next.startsWith("/") && !next.startsWith("//") && !next.includes("\\")
      ? next
      : "/";

  function setMode(value) {
    mode = value;
    error.hidden = true;
    const creating = mode !== "login";
    document.querySelector("#auth-title").textContent =
      mode === "setup"
        ? "初始化管理员"
        : creating
          ? "创建科研账号"
          : "登录工作台";
    document.querySelector("#auth-description").textContent =
      mode === "setup"
        ? "管理员账号将接管平台现有的科研项目。"
        : creating
          ? "注册后将获得独立的科研项目空间。"
          : "进入你的科研项目与研究流程。";
    document.querySelector("#auth-tabs").hidden = mode === "setup";
    document.querySelector("#setup-field").hidden = mode !== "setup";
    form.elements.setup_token.required = mode === "setup";
    document.querySelector("#confirm-field").hidden = !creating;
    form.elements.confirm_password.required = creating;
    document.querySelector("#password-hint").hidden = !creating;
    form.elements.password.minLength = creating ? 6 : 1;
    form.elements.password.autocomplete = creating
      ? "new-password"
      : "current-password";
    submit.textContent =
      mode === "setup"
        ? "创建管理员并进入平台"
        : creating
          ? "注册并进入平台"
          : "登录";
    document
      .querySelector("#login-tab")
      .setAttribute("aria-pressed", String(!creating));
    document
      .querySelector("#register-tab")
      .setAttribute("aria-pressed", String(creating));
    if (mode === "setup") form.elements.username.value = "admin";
  }

  async function request(path, payload) {
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
    if (!response.ok) throw new Error(data.error || "请求失败，请重试。");
    return data;
  }

  document
    .querySelector("#login-tab")
    .addEventListener("click", () => setMode("login"));
  document.querySelector("#register-tab").addEventListener("click", () => {
    if (registrationOpen) setMode("register");
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    if (
      mode !== "login" &&
      form.elements.password.value !== form.elements.confirm_password.value
    ) {
      error.textContent = "两次输入的密码不一致。";
      error.hidden = false;
      return;
    }
    submit.disabled = true;
    try {
      const data = await request(`/api/auth/${mode}`, {
        username: form.elements.username.value.trim(),
        password: form.elements.password.value,
        setup_token: form.elements.setup_token.value.trim(),
      });
      if (localStorage.getItem("autoresearch-account") !== data.user.id) {
        localStorage.removeItem("workbench-flow");
        localStorage.removeItem("auto-writing-active-project");
      }
      localStorage.setItem("autoresearch-account", data.user.id);
      submit.textContent = "正在准备工作台";
      // Start the account's worker before navigating to its module health checks.
      for (let attempt = 0; attempt < 40; attempt += 1) {
        const state = await request("/api/service");
        if (state.connected) break;
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      location.assign(
        destination.startsWith("/login.html") ? "/" : destination,
      );
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
      setMode(mode);
      error.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });

  request("/api/auth/session")
    .then((data) => {
      const connection = data.connection;
      if (connection?.enabled) {
        const note = document.querySelector("#connection-note");
        note.textContent = connection.message;
        note.hidden = false;
      }
      if (data.authenticated) {
        location.replace(
          destination.startsWith("/login.html") ? "/" : destination,
        );
        return;
      }
      registrationOpen = data.registration_open;
      document.querySelector("#register-tab").hidden = !registrationOpen;
      document.querySelector("#registration-note").hidden =
        registrationOpen || data.setup_required;
      setMode(data.setup_required ? "setup" : "login");
    })
    .catch((failure) => {
      error.textContent = failure.message;
      error.hidden = false;
    });
})();
