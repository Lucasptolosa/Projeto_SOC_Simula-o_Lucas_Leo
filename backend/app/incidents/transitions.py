from enum import StrEnum


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CONTAINED = "CONTAINED"
    RESOLVED = "RESOLVED"


class IncidentTransitionError(ValueError):
    pass


_ALLOWED_TRANSITIONS = frozenset({
    (IncidentStatus.OPEN, IncidentStatus.UNDER_INVESTIGATION),
    (IncidentStatus.UNDER_INVESTIGATION, IncidentStatus.CONTAINED),
    (IncidentStatus.UNDER_INVESTIGATION, IncidentStatus.RESOLVED),
    (IncidentStatus.CONTAINED, IncidentStatus.RESOLVED),
})


def validate_transition(
    current_status: IncidentStatus | str,
    target_status: IncidentStatus | str,
    *,
    containment_description: str | None = None,
    resolution_conclusion: str | None = None,
) -> IncidentStatus:
    """Valida sem efeitos."""
    try:
        current = IncidentStatus(current_status)
        target = IncidentStatus(target_status)
    except (ValueError, TypeError):
        raise IncidentTransitionError("Status de Incident inválido.") from None
    if (current, target) not in _ALLOWED_TRANSITIONS:
        raise IncidentTransitionError("Transição de Incident não permitida.")
    if any(
        value is not None and not isinstance(value, str)
        for value in (containment_description, resolution_conclusion)
    ):
        raise IncidentTransitionError("Os textos do Incident devem ser strings.")
    if target is IncidentStatus.CONTAINED and (
        containment_description is None or not containment_description.strip()
    ):
        raise IncidentTransitionError("Informe uma descrição de contenção não vazia.")
    if target is IncidentStatus.RESOLVED and (
        resolution_conclusion is None or not resolution_conclusion.strip()
    ):
        raise IncidentTransitionError("Informe uma conclusão de resolução não vazia.")
    return target
