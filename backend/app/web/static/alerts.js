export function initAlerts({request, notify, authError}) {
  const panel = document.querySelector("#alerts-panel");
  const identifier = panel.dataset.alertId;
  const filters = document.querySelector("#alert-filters");
  const size = document.querySelector("#page-size");
  const previous = document.querySelector("#previous-page");
  const next = document.querySelector("#next-page");
  const summary = document.querySelector("#page-summary");
  const retry = document.querySelector("#retry");
  const results = document.querySelector("#alerts-results");
  const evidence = document.querySelector("#alert-evidence");
  const detail = document.querySelector("#alert-data");
  const links = document.querySelector("#alert-links");
  let page = 1;
  let total = 0;
  let busy = false;
  let generation = 0;
  let applied = new URLSearchParams();

  function link(path, label) {
    const anchor = document.createElement("a");
    anchor.href = path;
    anchor.textContent = label;
    return anchor;
  }

  function row(body, values) {
    const item = body.insertRow();
    for (const value of values) {
      const cell = item.insertCell();
      if (value instanceof HTMLElement) cell.append(value);
      else cell.textContent = value;
      cell.className = "incident-text";
    }
  }

  function empty(body, columns) {
    const cell = body.insertRow().insertCell();
    cell.colSpan = columns;
    cell.textContent = "Nenhum registro encontrado.";
  }

  function controls() {
    panel.setAttribute("aria-busy", String(busy));
    panel.querySelectorAll("input, select, button").forEach(element => { element.disabled = busy; });
    if (previous) previous.disabled = busy || page <= 1;
    if (next) next.disabled = busy || page >= 10000 || page * Number(size.value) >= total;
  }

  function clear() {
    results?.replaceChildren();
    evidence?.replaceChildren();
    links?.replaceChildren();
    for (const element of panel.querySelectorAll("[data-alert-field]")) {
      element.textContent = "";
      element.removeAttribute("datetime");
    }
    if (detail) detail.hidden = true;
  }

  function close() {
    generation++;
    busy = false;
    clear();
    panel.hidden = true;
  }

  function renderDetail(item) {
    for (const element of panel.querySelectorAll("[data-alert-field]")) {
      const value = item[element.dataset.alertField];
      element.textContent = value;
      if (element.tagName === "TIME") element.dateTime = value;
    }
    if (item.investigation_id) {
      links.append(link(`/app/investigations/${encodeURIComponent(item.investigation_id)}`, "Abrir Investigation"));
    } else if (item.status === "NEW") {
      links.append(link(`/app/investigations?alert_id=${encodeURIComponent(item.id)}`, "Iniciar Investigation"));
    }
    if (item.incident_id) links.append(link(`/app/incidents/${encodeURIComponent(item.incident_id)}`, "Abrir Incident"));
    for (const log of item.related_logs) row(evidence, [log.event_id, log.event_type, log.username, log.occurred_at]);
    if (!item.related_logs.length) empty(evidence, 4);
    detail.hidden = false;
  }

  function renderList(data) {
    for (const item of data.items) {
      const anchor = link(`/app/alerts/${encodeURIComponent(item.id)}`, item.id);
      row(results, [anchor, item.severity, item.status, item.rule_id, item.asset_id, item.created_at]);
    }
    if (!data.items.length) empty(results, 6);
    page = data.page;
    total = data.total;
    summary.textContent = `Página ${page} · ${total} registro(s)`;
  }

  async function load() {
    if (busy) return;
    const current = generation;
    busy = true;
    retry.hidden = true;
    panel.hidden = false;
    total = 0;
    clear();
    controls();
    notify("");
    if (summary) summary.textContent = "Carregando registros…";
    try {
      if (identifier) {
        const data = await request(`/alerts/${encodeURIComponent(identifier)}`);
        if (current === generation) renderDetail(data);
      } else {
        const params = new URLSearchParams(applied);
        params.set("page", page);
        params.set("page_size", size.value);
        const data = await request(`/alerts?${params}`);
        if (current === generation) renderList(data);
      }
    } catch (error) {
      if (current !== generation) return;
      if (summary) summary.textContent = "Nenhum dado carregado";
      if (error.status === 401 || error.status === 403) { close(); await authError(error); }
      else {
        notify(error.status === 404 ? "Alert não encontrado." : error.status === 422
          ? "Parâmetros inválidos. Revise os filtros."
          : "Não foi possível consultar Alerts. Tente novamente.", true);
        retry.hidden = false;
      }
    } finally {
      if (current === generation) { busy = false; controls(); }
    }
  }

  filters?.addEventListener("submit", event => {
    event.preventDefault();
    if (busy) return;
    const params = new URLSearchParams();
    for (const [name, value] of new FormData(filters)) {
      if (!value) continue;
      if (name.startsWith("created_")) {
        const instant = new Date(value);
        if (Number.isNaN(instant.getTime())) { notify("Informe uma data válida.", true); return; }
        params.set(name, instant.toISOString());
      } else params.set(name, value);
    }
    applied = params;
    page = 1;
    load();
  });
  size?.addEventListener("change", () => { page = 1; load(); });
  previous?.addEventListener("click", () => { if (!busy && page > 1) { page--; load(); } });
  next?.addEventListener("click", () => { if (!busy && !next.disabled) { page++; load(); } });
  return {load, close, isSaving: () => false};
}
