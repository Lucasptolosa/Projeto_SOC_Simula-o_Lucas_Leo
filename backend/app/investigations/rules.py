class InvestigationRuleError(ValueError):
    pass


_KNOWN_STATUSES = frozenset({"NEW", "IN_REVIEW", "DISMISSED", "ESCALATED"})


def _validate_context(current_status: str, actor_role: str) -> None:
    if not isinstance(actor_role, str) or actor_role != "ANALYST":
        raise InvestigationRuleError("Operação exclusiva de ANALYST.")
    if not isinstance(current_status, str) or current_status not in _KNOWN_STATUSES:
        raise InvestigationRuleError("Estado de Alert inválido.")


def validate_start_investigation(current_status: str, *, actor_role: str) -> str:
    _validate_context(current_status, actor_role)
    if current_status != "NEW":
        raise InvestigationRuleError("Iniciar investigação exige Alert NEW.")
    return "IN_REVIEW"


def validate_false_positive(
    current_status: str, justification: str | None = None, *, actor_role: str,
) -> str:
    _validate_context(current_status, actor_role)
    if current_status != "IN_REVIEW":
        raise InvestigationRuleError("Descartar falso positivo exige Alert IN_REVIEW.")
    if not isinstance(justification, str) or not justification.strip():
        raise InvestigationRuleError("Informe uma justificativa textual não vazia.")
    return "DISMISSED"


def validate_escalation_eligibility(current_status: str, *, actor_role: str) -> None:
    """Verifica somente elegibilidade."""
    _validate_context(current_status, actor_role)
    if current_status != "IN_REVIEW":
        raise InvestigationRuleError("Escalonamento exige Alert IN_REVIEW.")
