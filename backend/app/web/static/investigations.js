export function initInvestigations({request, write, notify, authError, savingChanged}) {
  const panel = document.querySelector("#investigation-panel");
  const identifier = panel.dataset.investigationId;
  const data = document.querySelector("#investigation-data");
  const results = document.querySelector("#observation-results");
  const dialog = document.querySelector("#dismiss-dialog");
  const start = document.querySelector("#start-investigation");
  const find = document.querySelector("#find-investigation");
  const observation = document.querySelector("#observation-form");
  const dismissal = document.querySelector("#dismiss-form");
  const retry = document.querySelector("#retry");
  const previous = document.querySelector("#previous-page");
  const next = document.querySelector("#next-page");
  const size = document.querySelector("#page-size");
  let page = 1, total = 0;
  let busy = false, saving = false, ready = false;
  let current = null, created = null;

  function controls() {
    panel.setAttribute("aria-busy", String(busy || saving));
    panel.querySelectorAll("button, input, textarea, select").forEach(el => { el.disabled = busy || saving; });
    for (const form of [start, observation]) form?.querySelectorAll("button").forEach(el => { el.disabled = busy || saving || !ready; });
    if (previous) previous.disabled = busy || saving || page <= 1;
    if (next) next.disabled = busy || saving || page >= 10000 || page * Number(size.value) >= total;
    if (dialog) dialog.querySelectorAll("button, textarea").forEach(el => { el.disabled = saving; });
    if (data) {
      const enabled = ready && current?.status === "IN_REVIEW";
      document.querySelector("#investigation-decisions").hidden = !enabled;
      document.querySelector("#investigation-terminal").hidden = !ready || current?.status === "IN_REVIEW";
    }
  }

  function closeDialog() {
    if (dialog?.open) dialog.close(); dismissal?.reset();
    const error = document.querySelector("#dismiss-error"); if (error) error.textContent = "";
  }
  function close() {
    ready = false; current = null; created = null;
    closeDialog(); observation?.reset(); start?.reset(); find?.reset();
    results?.replaceChildren();
    const createdSummary = document.querySelector("#created-incident-summary");
    if (createdSummary) { createdSummary.textContent = ""; document.querySelector("#created-incident-link").removeAttribute("href"); }
    document.querySelector("#investigation-alert-link")?.removeAttribute("href");
    panel.querySelectorAll("[data-investigation-field]").forEach(el => { el.textContent = ""; el.removeAttribute("datetime"); });
    if (data) data.hidden = true;
    panel.hidden = true;
  }

  async function failure(error) {
    if (error.status === 401 || error.status === 403) { close(); await authError(error); return; }
    notify(error.status === 404 ? "Registro não encontrado." : error.status === 422
      ? "Dados inválidos. Revise UUID e textos obrigatórios."
      : "Não foi possível confirmar a operação. Atualize antes de repetir.", true);
    retry.hidden = false;
  }

  function render(row, observations) {
    current = row;
    panel.querySelectorAll("[data-investigation-field]").forEach(el => {
      const value = row[el.dataset.investigationField];
      el.textContent = value ?? "Não registrado";
      if (el.tagName === "TIME" && value) el.dateTime = value;
    });
    document.querySelector("#investigation-dismissal").hidden = row.justification === null;
    results.replaceChildren();
    for (const item of observations.items) {
      const tr = document.createElement("tr");
      for (const value of [item.content, item.analyst_id, item.occurred_at]) {
        const td = document.createElement("td"); td.textContent = value; td.className = "incident-text"; tr.append(td);
      }
      results.append(tr);
    }
    if (!observations.items.length) {
      const tr = document.createElement("tr"), td = document.createElement("td");
      td.colSpan = 3; td.textContent = "Nenhuma observação registrada."; tr.append(td); results.append(tr);
    }
    page = observations.page; total = observations.total;
    document.querySelector("#page-summary").textContent = `Página ${page} · ${total} registro(s)`;
    const incident = document.querySelector("#created-incident");
    const incidentId = row.incident_id;
    incident.hidden = !incidentId;
    document.querySelector("#investigation-alert-link").href = `/app/alerts/${encodeURIComponent(row.alert_id)}`;
    if (!incident.hidden) {
      document.querySelector("#created-incident-summary").textContent = created?.id === incidentId
        ? `${incidentId} · ${created.severity} · ${created.status}` : incidentId;
      document.querySelector("#created-incident-link").href = `/app/incidents/${encodeURIComponent(incidentId)}`;
    }
    data.hidden = false; ready = true;
  }

  async function load() {
    if (busy) return false;
    busy = true; ready = false; panel.hidden = false; retry.hidden = true; notify(""); controls();
    if (data) data.hidden = true;
    try {
      if (identifier) {
        const row = await request(`/investigations/${encodeURIComponent(identifier)}?include_incident=true`);
        const observations = await request(`/investigations/${encodeURIComponent(identifier)}/observations?page=${page}&page_size=${size.value}`);
        render(row, observations);
      } else ready = true;
      return true;
    } catch (error) { await failure(error); return false; }
    finally { busy = false; controls(); }
  }

  async function mutate(path, payload, confirmed) {
    if (busy || saving || !ready) return;
    let focusTarget = null;
    saving = true; savingChanged(true); controls();
    try {
      const result = await write(path, payload);
      ready = false; closeDialog();
      await confirmed(result);
      if (identifier) focusTarget = document.querySelector(data.hidden ? "#feedback" : '[data-investigation-field="status"]');
    } catch (error) {
      if (error.status === 409) {
        closeDialog(); ready = false;
        const refreshed = identifier && await load();
        notify(refreshed ? "Conflito: estado atualizado. Revise antes de decidir."
          : "Conflito: consulte a Investigation existente antes de repetir a decisão.", true);
        focusTarget = document.querySelector(refreshed ? '[data-investigation-field="status"]' : "#feedback");
      } else {
        if (error.status !== 422) { closeDialog(); ready = false; }
        else if (dialog?.open) document.querySelector("#dismiss-error").textContent = "Dados inválidos. Revise a justificativa.";
        await failure(error);
        if (error.status !== 401 && error.status !== 403) focusTarget = error.status === 422 && dialog?.open
          ? dismissal.elements.justification : document.querySelector("#feedback");
      }
    } finally {
      saving = false; savingChanged(false); controls();
      if (focusTarget) {
        if (focusTarget.tagName !== "TEXTAREA") focusTarget.setAttribute("tabindex", "-1");
        focusTarget.focus();
      }
    }
  }

  start?.addEventListener("submit", event => {
    event.preventDefault();
    mutate("/investigations", {alert_id: start.elements.alert_id.value}, result => {
      window.location.assign(`/app/investigations/${encodeURIComponent(result.id)}`);
    });
  });
  start?.elements.alert_id.addEventListener("input", () => { if (!busy && !saving) { ready = true; controls(); } });
  find?.addEventListener("submit", event => {
    event.preventDefault(); if (busy || saving) return;
    window.location.assign(`/app/investigations/${encodeURIComponent(find.elements.investigation_id.value)}`);
  });
  observation?.addEventListener("submit", event => {
    event.preventDefault();
    if (!observation.elements.content.value.trim()) { notify("Informe uma observação não vazia.", true); return; }
    mutate(`/investigations/${identifier}/observations`, {content: observation.elements.content.value}, async () => {
      observation.reset(); page = 1; const refreshed = await load();
      if (refreshed) notify("Observação registrada com sucesso.");
    });
  });
  document.querySelector("#dismiss-investigation")?.addEventListener("click", () => {
    if (busy || saving || !ready) return; dismissal.reset(); dialog.showModal(); dismissal.elements.justification.focus();
  });
  dismissal?.addEventListener("submit", event => {
    event.preventDefault();
    if (!dismissal.elements.justification.value.trim()) { document.querySelector("#dismiss-error").textContent = "Informe uma justificativa não vazia."; return; }
    mutate(`/investigations/${identifier}/false-positive`, {justification: dismissal.elements.justification.value}, async () => {
      if (await load()) notify("False Positive confirmado. Status: DISMISSED.");
    });
  });
  document.querySelector("#escalate-investigation")?.addEventListener("click", () => {
    mutate(`/investigations/${identifier}/escalate`, undefined, async result => {
      created = result;
      if (await load()) notify("Escalonamento confirmado. Status: ESCALATED.");
    });
  });
  dialog?.querySelector(".dialog-cancel").addEventListener("click", () => { if (!saving) closeDialog(); });
  dialog?.addEventListener("cancel", event => { if (saving) event.preventDefault(); else closeDialog(); });
  previous?.addEventListener("click", () => { if (!busy && !saving && page > 1) { page--; load(); } });
  next?.addEventListener("click", () => { if (!busy && !saving && page * Number(size.value) < total && page < 10000) { page++; load(); } });
  size?.addEventListener("change", () => { if (!busy && !saving) { page = 1; load(); } });
  return {load, close, isSaving: () => saving};
}
