export function initLogImport({write, notify, authError, savingChanged}) {
  const panel = document.querySelector("#log-import-panel");
  const form = document.querySelector("#log-import-form");
  const file = document.querySelector("#log-file");
  const result = document.querySelector("#log-import-result");
  let saving = false;

  function clearResult() {
    result.hidden = true;
    for (const id of ["ingestion-summary", "detection-summary", "ingestion-rejections", "detection-rejections"]) document.getElementById(id).replaceChildren();
  }
  function close() { file.value = ""; clearResult(); panel.hidden = true; }
  function setSaving(value) {
    saving = value; savingChanged(value); panel.setAttribute("aria-busy", String(value));
    form.querySelectorAll("input, button").forEach(el => { el.disabled = value; });
  }
  function rows(id, values) {
    const body = document.getElementById(id); body.replaceChildren();
    if (!values.length) {
      const tr = document.createElement("tr"), td = document.createElement("td");
      td.colSpan = 3; td.textContent = "Nenhuma rejeição."; tr.append(td); body.append(tr);
    }
    for (const item of values) {
      const tr = document.createElement("tr");
      for (const value of [item.position, item.reason, item.detail]) {
        const td = document.createElement("td"); td.textContent = value; tr.append(td);
      }
      body.append(tr);
    }
  }
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (saving || !file.files.length) return;
    const selected = file.files[0];
    setSaving(true); clearResult(); notify("Validando arquivo…");
    let payload;
    try { payload = JSON.parse(await selected.text()); }
    catch { notify("Arquivo JSON inválido. Revise o formato sem reenviar automaticamente.", true); setSaving(false); return; }
    if (!Array.isArray(payload) || payload.length < 1 || payload.length > 1000) {
      notify("O arquivo deve conter uma lista de 1 a 1.000 registros.", true); setSaving(false); return;
    }
    try {
      notify("Importando e avaliando o lote…");
      const response = await write("/logs/import", payload);
      document.querySelector("#ingestion-summary").textContent = `Aceitos: ${response.accepted} · Rejeitados: ${response.rejected}`;
      document.querySelector("#detection-summary").textContent = `Avaliados: ${response.detection.evaluated} · Rejeitados para detecção: ${response.detection.rejected} · Alerts criados: ${response.detection.alerts_created}`;
      rows("ingestion-rejections", response.rejections); rows("detection-rejections", response.detection.rejections);
      result.hidden = false; notify("Lote confirmado. Consulte separadamente ingestão e detecção.");
      file.value = "";
    } catch (error) {
      file.value = ""; clearResult();
      if (error.status === 401 || error.status === 403) { close(); await authError(error); }
      else notify(error.status === 422 ? "Lote inválido. Revise o arquivo antes de reenviar."
        : "Não foi possível confirmar a importação. Verifique os registros antes de reenviar.", true);
    } finally { payload = null; setSaving(false); }
  });
  return {open: () => { panel.hidden = false; }, close, isSaving: () => saving};
}
