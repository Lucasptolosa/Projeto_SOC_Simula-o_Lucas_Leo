export function initOperations({write, notify, authError, savingChanged}) {
  const panel = document.querySelector("#operations-panel");
  const output = document.querySelector("#operation-result");
  let saving = false;

  function setSaving(value) {
    saving = value;
    savingChanged(value);
    panel.setAttribute("aria-busy", String(value));
    panel.querySelectorAll("input, select, button").forEach(control => {
      control.disabled = value || control.hasAttribute("data-unavailable");
    });
  }

  function close() {
    output.textContent = "";
    panel.hidden = true;
  }

  panel.querySelectorAll("form[data-path]").forEach(form => {
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (saving || panel.hidden) return;
      if (form.hasAttribute("data-deactivate") && !window.confirm("Desativar o Asset selecionado?")) return;
      const payload = Object.fromEntries(new FormData(form));
      setSaving(true);
      output.textContent = "";
      notify("Confirmando operação…");
      try {
        const result = await write(form.dataset.path, payload, form.dataset.method);
        if (panel.hidden) return;
        const row = form.closest("[data-asset-row], [data-rule-row]");
        if (row) row.querySelector("[data-record-status]").textContent = result.status;
        if (form.hasAttribute("data-deactivate")) form.querySelector("button").setAttribute("data-unavailable", "");
        if (row?.hasAttribute("data-asset-row") && form.dataset.method === "PATCH") row.querySelector("h3").textContent = result.name;
        if (form.dataset.path === "/assets") form.reset();
        output.textContent = `Registro ${result.id} · ${result.status}`;
        notify("Operação confirmada.");
      } catch (error) {
        if (error.status === 401 || error.status === 403) { close(); await authError(error); }
        else notify(error.status === 422 ? "Dados inválidos. Revise os campos."
          : "Não foi possível confirmar a operação. Atualize a lista antes de tentar novamente.", true);
      } finally { setSaving(false); }
    });
  });
  return {open: () => { panel.hidden = false; }, close, isSaving: () => saving};
}
