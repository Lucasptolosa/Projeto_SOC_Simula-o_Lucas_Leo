export function initIncidents({request, write, notify, authError, savingChanged}) {
  const panel = document.querySelector("#incident-panel");
  const results = document.querySelector("#incident-results");
  const filters = document.querySelector("#incident-filters");
  const summary = document.querySelector("#page-summary");
  const previous = document.querySelector("#previous-page");
  const next = document.querySelector("#next-page");
  const size = document.querySelector("#page-size");
  const retry = document.querySelector("#retry");
  const data = document.querySelector("#incident-data");
  const actions = document.querySelector("#incident-actions");
  const dialog = document.querySelector("#incident-dialog");
  const form = document.querySelector("#incident-transition-form");
  const text = document.querySelector("#incident-text");
  let page = 1;
  let total = 0;
  let busy = false;
  let saving = false;
  let ready = false;
  let target = null;
  let applied = new URLSearchParams();

  function controls() {
    panel.setAttribute("aria-busy", String(busy || saving));
    panel.querySelectorAll("button, input, select").forEach((element) => { element.disabled = busy || saving; });
    if (previous) previous.disabled = busy || page <= 1;
    if (next) next.disabled = busy || page >= 10000 || page * Number(size.value) >= total;
    actions?.querySelectorAll("button").forEach((button) => { button.disabled = busy || saving || !ready; });
    if (dialog) {
      dialog.setAttribute("aria-busy", String(saving));
      dialog.querySelectorAll("button, fieldset").forEach((element) => { element.disabled = saving; });
    }
  }

  function closeDialog() {
    if (!dialog) return;
    if (dialog.open) dialog.close();
    form.reset();
    target = null;
    document.querySelector("#incident-form-error").textContent = "";
  }

  function clearDetail() {
    ready = false;
    if (!data) return;
    data.hidden = true;
    panel.querySelectorAll("[data-incident-field]").forEach((element) => { element.textContent = ""; element.removeAttribute("datetime"); });
    actions.replaceChildren();
  }

  function close() {
    closeDialog();
    clearDetail();
    results?.replaceChildren();
    panel.hidden = true;
  }

  async function failure(error) {
    if (error.status === 401 || error.status === 403) {
      close();
      await authError(error);
    } else {
      notify(error.status === 404 ? "Incident não encontrado." : error.status === 422
        ? "Parâmetros inválidos. Revise os filtros e tente novamente."
        : "Não foi possível acessar o servidor. Tente novamente em instantes.", true);
      retry.hidden = false;
    }
  }

  function cell(row, value, className = "") {
    const element = document.createElement("td");
    element.textContent = value;
    element.className = className;
    row.append(element);
    return element;
  }

  function renderList(items) {
    const fragment = document.createDocumentFragment();
    for (const item of items) {
      const row = document.createElement("tr");
      cell(row, item.id, "identifier");
      cell(row, item.severity);
      cell(row, item.status);
      const time = document.createElement("time");
      time.dateTime = item.opened_at;
      time.textContent = item.opened_at;
      cell(row, "").append(time);
      const link = document.createElement("a");
      link.textContent = "Abrir detalhes";
      link.href = `/app/incidents/${encodeURIComponent(item.id)}`;
      link.setAttribute("aria-label", `Abrir detalhes do Incident ${item.id}`);
      cell(row, "").append(link);
      fragment.append(row);
    }
    if (!items.length) {
      const row = document.createElement("tr");
      const empty = cell(row, "Nenhum Incident encontrado.", "empty-state");
      empty.colSpan = 5;
      fragment.append(row);
    }
    results.replaceChildren(fragment);
  }

  function openForm(status) {
    if (busy || saving || !ready) return;
    closeDialog();
    target = status;
    const containment = status === "CONTAINED";
    document.querySelector("#incident-dialog-title").textContent = containment ? "Registrar contenção" : "Resolver Incident";
    document.querySelector("#incident-text-label").textContent = containment ? "Descrição da contenção" : "Conclusão da resolução";
    dialog.showModal();
    text.focus();
  }

  function renderDetail(item) {
    for (const element of panel.querySelectorAll("[data-incident-field]")) {
      const value = item[element.dataset.incidentField];
      element.textContent = value ?? "Não registrado";
      if (element.tagName === "TIME" && value) element.dateTime = value;
    }
    document.querySelector("#incident-containment").hidden = item.containment_description === null;
    document.querySelector("#incident-resolution").hidden = item.resolution_conclusion === null;
    actions.replaceChildren();
    const visible = {
      OPEN: [["UNDER_INVESTIGATION", "Iniciar tratamento"]],
      UNDER_INVESTIGATION: [["CONTAINED", "Registrar contenção"], ["RESOLVED", "Resolver diretamente"]],
      CONTAINED: [["RESOLVED", "Resolver"]], RESOLVED: [],
    }[item.status] ?? [];
    for (const [status, label] of visible) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "primary";
      button.textContent = label;
      button.addEventListener("click", () => status === "UNDER_INVESTIGATION" ? mutate(status) : openForm(status));
      actions.append(button);
    }
    if (item.status === "RESOLVED") {
      const note = document.createElement("p");
      note.textContent = "Incident resolvido. Somente consulta.";
      actions.append(note);
    }
    data.hidden = false;
    ready = true;
  }

  async function load() {
    if (busy) return false;
    busy = true;
    ready = false;
    panel.hidden = false;
    retry.hidden = true;
    notify("");
    controls();
    clearDetail();
    results?.replaceChildren();
    try {
      if (results) {
        const params = new URLSearchParams(applied);
        params.set("page", page);
        params.set("page_size", size.value);
        const response = await request(`/incidents?${params}`);
        renderList(response.items);
        page = response.page;
        total = response.total;
        summary.textContent = `Página ${page} · ${total} registro(s)`;
      } else {
        renderDetail(await request(`/incidents/${encodeURIComponent(panel.dataset.incidentId)}`));
      }
      return true;
    } catch (error) {
      if (summary) summary.textContent = "Nenhum dado carregado";
      await failure(error);
      return false;
    } finally {
      busy = false;
      controls();
    }
  }

  async function mutate(status, content) {
    if (saving || busy || !ready) return;
    const payload = {target_status: status};
    if (status === "CONTAINED") payload.containment_description = content;
    if (status === "RESOLVED") payload.resolution_conclusion = content;
    saving = true;
    savingChanged(true);
    controls();
    try {
      const item = await write(`/incidents/${encodeURIComponent(panel.dataset.incidentId)}/transitions`, payload);
      closeDialog();
      renderDetail(item);
      notify(`Operação concluída. Novo Status: ${item.status}.`);
    } catch (error) {
      if (error.status === 409) {
        closeDialog();
        const refreshed = await load();
        notify(refreshed ? "Conflito: o Incident foi alterado. Estado atualizado; revise antes de decidir."
          : "Conflito: não foi possível atualizar o estado. Use Tentar novamente antes de decidir.", true);
      } else if (error.status === 422 && dialog.open) {
        document.querySelector("#incident-form-error").textContent = "Dados inválidos. Revise o texto obrigatório.";
      } else {
        closeDialog();
        ready = false;
        actions.replaceChildren();
        await failure(error);
        if (error.status !== 401 && error.status !== 403) notify("Não foi possível confirmar a operação. Atualize o detalhe antes de repetir.", true);
      }
    } finally {
      saving = false;
      savingChanged(false);
      controls();
    }
  }

  filters?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (busy) return;
    const params = new URLSearchParams();
    for (const name of ["status", "severity", "asset_id"]) {
      if (filters.elements[name].value) params.set(name, filters.elements[name].value);
    }
    const dates = {};
    for (const name of ["opened_from", "opened_to"]) {
      const value = filters.elements[name].value;
      if (value) {
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) { notify("Informe uma data válida.", true); return; }
        dates[name] = date;
        params.set(name, date.toISOString());
      }
    }
    if (dates.opened_from && dates.opened_to && dates.opened_from > dates.opened_to) {
      notify("O início não pode ser posterior ao fim do intervalo.", true);
      return;
    }
    applied = params;
    page = 1;
    load();
  });
  size?.addEventListener("change", () => { if (!busy) { page = 1; load(); } });
  previous?.addEventListener("click", () => { if (!busy && page > 1) { page--; load(); } });
  next?.addEventListener("click", () => { if (!busy && page < 10000 && page * Number(size.value) < total) { page++; load(); } });
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (saving || !dialog.open || !target) return;
    if (!text.value.trim()) { document.querySelector("#incident-form-error").textContent = "Preencha o texto obrigatório."; return; }
    mutate(target, text.value);
  });
  dialog?.querySelector(".dialog-cancel").addEventListener("click", () => { if (!saving) closeDialog(); });
  dialog?.addEventListener("cancel", (event) => { if (saving) event.preventDefault(); else closeDialog(); });
  return {load, close, isSaving: () => saving};
}
