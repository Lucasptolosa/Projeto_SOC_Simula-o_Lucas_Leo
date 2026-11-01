(() => {
  "use strict";

  const page = document.body.dataset.page;
  const feedback = document.querySelector("#feedback");
  const form = document.querySelector("#login-form");
  const panel = document.querySelector("#query-panel");
  const results = document.querySelector("#results");
  const logout = document.querySelector("#logout");
  const retry = document.querySelector("#retry");
  let csrf = null;
  let currentPage = 1;
  let busy = false;
  let hasNext = false;

  class ApiError extends Error {
    constructor(status) { super("Falha na requisição"); this.status = status; }
  }

  async function request(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, {
        ...options, credentials: "same-origin", cache: "no-store", signal: controller.signal,
      });
      if (!response.ok) throw new ApiError(response.status);
      return response.status === 204 ? null : await response.json();
    } finally {
      clearTimeout(timeout);
    }
  }

  function notify(message, error = false) {
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.toggle("error", error);
  }

  function returnToLogin(reason = "session") {
    csrf = null;
    if (results) results.replaceChildren();
    window.location.replace(`/login?reason=${reason}`);
  }

  function handleError(error) {
    if (error.status === 401) { returnToLogin(); return; }
    if (error.status === 403) {
      notify("Acesso negado. Suas permissões podem ter mudado. Volte à visão geral.", true);
    } else if (error.status === 422) {
      notify("Parâmetros inválidos. Revise os filtros e tente novamente.", true);
    } else {
      notify("Não foi possível acessar o servidor. Tente novamente em instantes.", true);
    }
    if (retry) retry.hidden = false;
  }

  if (form) {
    const reason = new URLSearchParams(window.location.search).get("reason");
    if (reason === "session") notify("Sua sessão não está disponível. Entre novamente.");
    if (reason === "logout") notify("Você saiu do Mini SOC com segurança.");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button");
      button.disabled = true;
      form.setAttribute("aria-busy", "true");
      notify("Autenticando…");
      try {
        await request("/auth/login", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({username: form.elements.username.value, password: form.elements.password.value}),
        });
        window.location.replace("/app");
      } catch (error) {
        if (error.status === 401) notify("Credenciais inválidas ou acesso indisponível.", true);
        else if (error.status === 403) notify("Origem não autorizada. Confira o endereço do ambiente.", true);
        else if (error.status === 422) notify("Informe nome de usuário e senha válidos.", true);
        else notify("Não foi possível acessar o servidor. Tente novamente em instantes.", true);
      } finally {
        form.elements.password.value = "";
        button.disabled = false;
        form.setAttribute("aria-busy", "false");
      }
    });
    return;
  }

  if (!logout) return;

  function setBusy(value) {
    busy = value;
    if (!panel) return;
    panel.setAttribute("aria-busy", String(value));
    panel.querySelectorAll("button, select").forEach((element) => { element.disabled = value; });
    document.querySelector("#previous-page").disabled = value || currentPage <= 1;
    document.querySelector("#next-page").disabled = value || !hasNext;
  }

  function messageRow(message) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = page === "users" ? 3 : 6;
    cell.className = "empty-state";
    cell.textContent = message;
    row.append(cell);
    results.replaceChildren(row);
  }

  function cell(row, value, className = "") {
    const element = document.createElement("td");
    element.textContent = value ?? "—";
    element.className = className;
    row.append(element);
    return element;
  }

  function renderRows(items) {
    const fragment = document.createDocumentFragment();
    const actions = {USER_CREATED: "Usuário criado", USER_UPDATED: "Usuário alterado", USER_DEACTIVATED: "Usuário desativado"};
    const dateFormat = new Intl.DateTimeFormat("pt-BR", {dateStyle: "medium", timeStyle: "medium", timeZone: "America/Sao_Paulo"});
    for (const item of items) {
      const row = document.createElement("tr");
      if (page === "users") {
        cell(row, item.username, "username-cell");
        cell(row, item.role);
        const status = cell(row, "");
        const badge = document.createElement("span");
        badge.className = item.status === "ACTIVE" ? "badge active" : "badge inactive";
        badge.textContent = item.status;
        status.append(badge);
      } else {
        const date = new Date(item.occurred_at);
        const time = document.createElement("time");
        time.dateTime = item.occurred_at;
        time.textContent = Number.isNaN(date.getTime()) ? "Data indisponível" : dateFormat.format(date);
        cell(row, "").append(time);
        cell(row, item.author_id, "identifier");
        cell(row, actions[item.action] ?? item.action);
        cell(row, `${item.entity_type} · ${item.entity_id}`, "identifier");
        cell(row, item.old_role);
        cell(row, item.new_role);
      }
      fragment.append(row);
    }
    results.replaceChildren(fragment);
    if (!items.length) messageRow("Nenhum registro encontrado.");
  }

  async function loadRecords() {
    if (busy || !panel) return;
    setBusy(true);
    retry.hidden = true;
    notify("");
    messageRow("Carregando registros…");
    hasNext = false;
    const summary = document.querySelector("#page-summary");
    try {
      const size = document.querySelector("#page-size").value;
      const params = new URLSearchParams({page: currentPage, page_size: size});
      if (page === "users") {
        const role = document.querySelector("#role-filter").value;
        const status = document.querySelector("#status-filter").value;
        if (role) params.set("role", role);
        if (status) params.set("status", status);
      }
      const data = await request(`${page === "users" ? "/users" : "/audit-logs"}?${params}`);
      renderRows(data.items);
      currentPage = data.page;
      hasNext = data.page < 10000 && data.page * data.page_size < data.total;
      summary.textContent = `Página ${data.page} · ${data.total} registro(s)`;
    } catch (error) {
      messageRow("Consulta indisponível.");
      summary.textContent = "Nenhum dado carregado";
      handleError(error);
    } finally {
      setBusy(false);
    }
  }

  async function identify() {
    const user = await request("/auth/me");
    csrf = user.csrf_token;
    document.querySelector("#current-username").textContent = user.username;
    document.querySelector("#current-role").textContent = user.role;
    document.querySelectorAll("[data-admin]").forEach((element) => { element.hidden = user.role !== "ADMIN"; });
    logout.disabled = false;
    if (panel && user.role !== "ADMIN") {
      panel.hidden = true;
      throw new ApiError(403);
    }
    return user;
  }

  async function start() {
    retry.hidden = true;
    try {
      await identify();
      if (panel) { panel.hidden = false; await loadRecords(); }
    } catch (error) { handleError(error); }
  }

  logout.addEventListener("click", async () => {
    logout.disabled = true;
    try {
      await request("/auth/logout", {method: "POST", headers: {"X-CSRF-Token": csrf}});
      returnToLogin("logout");
    } catch (error) { handleError(error); logout.disabled = false; }
  });
  retry.addEventListener("click", start);
  document.querySelector("#user-filters")?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!busy) { currentPage = 1; loadRecords(); }
  });
  document.querySelector("#page-size")?.addEventListener("change", () => { currentPage = 1; loadRecords(); });
  document.querySelector("#previous-page")?.addEventListener("click", () => { if (!busy && currentPage > 1) { currentPage--; loadRecords(); } });
  document.querySelector("#next-page")?.addEventListener("click", () => { if (!busy && hasNext) { currentPage++; loadRecords(); } });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) identify().catch(handleError);
  });
  window.addEventListener("pageshow", (event) => { if (event.persisted) window.location.reload(); });
  start();
})();
