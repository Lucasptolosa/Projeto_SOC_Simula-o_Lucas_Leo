export function initUserManagement({user, write, refresh, authError, savingChanged}) {
  const editor = document.querySelector("#user-dialog");
  const confirmation = document.querySelector("#deactivate-dialog");
  const form = document.querySelector("#user-form");
  const fields = document.querySelector("#user-fields");
  const passwordFields = document.querySelector("#password-fields");
  const saveButton = document.querySelector("#save-user");
  const confirmButton = document.querySelector("#confirm-deactivate");
  const createButton = document.querySelector("#create-user");
  const result = document.querySelector("#operation-result");
  let target = null;
  let saving = false;

  function clearPasswords() {
    form.elements.password.value = "";
    form.elements.confirmation.value = "";
  }

  function reset() {
    clearPasswords();
    form.reset();
    target = null;
    document.querySelector("#deactivate-username").textContent = "";
  }

  function close() {
    if (editor.open) editor.close();
    if (confirmation.open) confirmation.close();
    reset();
    result.textContent = "";
  }

  function setSaving(value) {
    saving = value;
    fields.disabled = value;
    saveButton.disabled = value;
    confirmButton.disabled = value;
    for (const dialog of [editor, confirmation]) {
      dialog.setAttribute("aria-busy", String(value));
      dialog.querySelector(".dialog-cancel").disabled = value;
    }
    savingChanged(value);
  }

  function openEditor(item = null) {
    if (saving) return;
    reset();
    target = item;
    result.textContent = "";
    document.querySelector("#user-error").textContent = "";
    document.querySelector("#user-dialog-title").textContent = item ? "Editar usuário" : "Novo usuário";
    document.querySelector("#user-dialog-help").textContent = item
      ? "Altere somente username e papel. O identificador e as associações serão preservados."
      : "A nova conta será criada com estado ACTIVE.";
    saveButton.textContent = item ? "Salvar alterações" : "Criar usuário";
    passwordFields.hidden = Boolean(item);
    form.elements.password.disabled = Boolean(item);
    form.elements.confirmation.disabled = Boolean(item);
    form.elements.username.value = item?.username ?? "";
    form.elements.role.value = item?.role ?? "ANALYST";
    editor.showModal();
    form.elements.username.focus();
  }

  function openConfirmation(item) {
    if (saving) return;
    reset();
    target = item;
    result.textContent = "";
    document.querySelector("#deactivate-error").textContent = "";
    document.querySelector("#deactivate-username").textContent = item.username;
    confirmation.showModal();
    confirmation.querySelector(".dialog-cancel").focus();
  }

  function errorMessage(error) {
    const conflicts = new Map([
      ["Username já cadastrado.", "Username já cadastrado. Escolha outro nome de usuário."],
      ["O último ADMIN ativo deve ser preservado.", "O último ADMIN ativo deve ser preservado. A conta não foi desativada ou alterada."],
      ["Usuário já está inativo.", "Usuário já está inativo. Feche a confirmação e atualize a listagem."],
    ]);
    if (error.status === 409) return conflicts.get(error.detail) ?? "Conflito na operação. Atualize a listagem antes de tentar novamente.";
    if (error.status === 422) return "Dados inválidos. Confira username, papel e campos obrigatórios.";
    if (error.status === 404) return "Usuário não encontrado. Atualize a listagem.";
    return "Não foi possível confirmar a operação no servidor. Feche este formulário e atualize a listagem antes de repetir.";
  }

  async function mutate(path, payload, method, errorElement, successMessage) {
    if (saving) return;
    errorElement.textContent = "";
    setSaving(true);
    let succeeded = false;
    try {
      await write(path, payload, method);
      succeeded = true;
    } catch (error) {
      if (error.status === 401 || error.status === 403) {
        close();
        await authError(error);
      } else {
        errorElement.textContent = errorMessage(error);
      }
    } finally {
      clearPasswords();
      setSaving(false);
    }
    if (succeeded) {
      close();
      result.textContent = successMessage;
      await refresh();
      createButton.focus();
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving || !editor.open) return;
    const error = document.querySelector("#user-error");
    if (!form.elements.username.value.trim() || (!target && !form.elements.password.value.trim())) {
      error.textContent = "Preencha os campos obrigatórios com valores válidos.";
      clearPasswords();
      return;
    }
    if (!target && form.elements.password.value !== form.elements.confirmation.value) {
      error.textContent = "As senhas não coincidem. Informe e confirme a senha novamente.";
      clearPasswords();
      form.elements.password.focus();
      return;
    }
    const payload = {username: form.elements.username.value, role: form.elements.role.value};
    if (!target) payload.password = form.elements.password.value;
    const editing = Boolean(target);
    const path = editing ? `/users/${encodeURIComponent(target.id)}` : "/users";
    clearPasswords();
    await mutate(path, payload, editing ? "PATCH" : "POST", error,
      editing ? "Usuário atualizado com sucesso." : "Usuário cadastrado com sucesso.");
  });

  document.querySelector("#deactivate-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving || !confirmation.open || !target) return;
    await mutate(`/users/${encodeURIComponent(target.id)}/deactivate`, undefined, "POST",
      document.querySelector("#deactivate-error"), "Usuário desativado. O acesso e as sessões foram revogados.");
  });

  createButton.addEventListener("click", () => openEditor());
  for (const dialog of [editor, confirmation]) {
    dialog.querySelector(".dialog-cancel").addEventListener("click", () => { if (!saving) close(); });
    dialog.addEventListener("cancel", (event) => { if (saving) event.preventDefault(); });
    dialog.addEventListener("close", reset);
  }

  function addActions(row, item) {
    const cell = document.createElement("td");
    const actions = document.createElement("div");
    actions.className = "row-actions";
    for (const [label, disabled, action] of [
      ["Editar", item.id === user.id, () => openEditor(item)],
      ["Desativar", item.status === "INACTIVE", () => openConfirmation(item)],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = label === "Editar" ? "quiet" : "quiet deactivate-action";
      button.textContent = label;
      button.setAttribute("aria-label", `${label} ${item.username}`);
      button.disabled = disabled;
      if (disabled) {
        button.dataset.unavailable = "";
        button.title = label === "Editar" ? "A API permite editar somente outra conta." : "A conta já está INACTIVE.";
      }
      button.addEventListener("click", action);
      actions.append(button);
    }
    cell.append(actions);
    if (item.id === user.id) {
      const note = document.createElement("span");
      note.className = "own-account";
      note.textContent = "Sua conta · edição indisponível";
      cell.append(note);
    }
    row.append(cell);
  }

  return {addActions, close, isSaving: () => saving};
}
