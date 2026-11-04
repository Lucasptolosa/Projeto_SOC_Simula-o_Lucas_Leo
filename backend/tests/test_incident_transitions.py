from copy import deepcopy
from itertools import product

import pytest

from app.incidents.transitions import IncidentStatus, IncidentTransitionError, validate_transition


STATUSES = ("OPEN", "UNDER_INVESTIGATION", "CONTAINED", "RESOLVED")
ALLOWED = (
    ("OPEN", "UNDER_INVESTIGATION"),
    ("UNDER_INVESTIGATION", "CONTAINED"),
    ("UNDER_INVESTIGATION", "RESOLVED"),
    ("CONTAINED", "RESOLVED"),
)
TEXT_REQUIRED = (
    ("UNDER_INVESTIGATION", "CONTAINED", "containment_description"),
    ("UNDER_INVESTIGATION", "RESOLVED", "resolution_conclusion"),
    ("CONTAINED", "RESOLVED", "resolution_conclusion"),
)


@pytest.mark.parametrize("current,target", ALLOWED)
def test_transicoes_permitidas_da_secao_9(current, target):
    # Arrange
    texts = {"containment_description": "Asset isolado.", "resolution_conclusion": "Serviço restaurado."}

    # Act
    result = validate_transition(current, target, **texts)

    # Assert
    assert result is IncidentStatus(target)


@pytest.mark.parametrize("current,target", [pair for pair in product(STATUSES, repeat=2) if pair not in ALLOWED])
def test_todas_transicoes_fora_da_matriz_sao_recusadas(current, target):
    # Arrange
    texts = {"containment_description": "Asset isolado.", "resolution_conclusion": "Serviço restaurado."}

    # Act
    with pytest.raises(IncidentTransitionError) as error:
        validate_transition(current, target, **texts)

    # Assert
    assert str(error.value) == "Transição de Incident não permitida."


@pytest.mark.parametrize("current,target", ALLOWED)
def test_aceita_estados_tipados(current, target):
    # Arrange
    source = IncidentStatus(current)
    destination = IncidentStatus(target)

    # Act
    result = validate_transition(
        source, destination, containment_description="Rede isolada.", resolution_conclusion="Causa removida.",
    )

    # Assert
    assert result is destination
    assert source is IncidentStatus(current)


@pytest.mark.parametrize("field", ["current_status", "target_status"])
@pytest.mark.parametrize("invalid", [None, "", "open", " OPEN", "OPEN ", "NEW", 0, True, [], {}, b"OPEN", object()])
def test_status_invalido_recusado_sem_coercao(field, invalid):
    # Arrange
    payload = {"current_status": "OPEN", "target_status": "UNDER_INVESTIGATION"}
    payload[field] = invalid

    # Act
    with pytest.raises(IncidentTransitionError) as error:
        validate_transition(**payload)

    # Assert
    assert str(error.value) == "Status de Incident inválido."
    assert payload[field] is invalid


@pytest.mark.parametrize("current,target,field", TEXT_REQUIRED)
@pytest.mark.parametrize("text", [None, "", " ", "\t\r\n", "\u00a0", "\u2003", " \t\u00a0\n"])
def test_texto_obrigatorio_nao_pode_ser_vazio(current, target, field, text):
    # Arrange
    payload = {field: text}

    # Act
    with pytest.raises(IncidentTransitionError) as error:
        validate_transition(current, target, **payload)

    # Assert
    assert "não vazia" in str(error.value)
    assert payload[field] is text


@pytest.mark.parametrize("current,target,field", TEXT_REQUIRED)
@pytest.mark.parametrize("text", ["x", "  ação com acentuação  ", "ação\nmultilinha", "x" * 10000], ids=["minimo", "espacos-preservados", "multilinha", "sem-limite-inventado"])
def test_texto_valido_preservado(current, target, field, text):
    # Arrange
    payload = {"current_status": current, "target_status": target, field: text}
    before = payload.copy()

    # Act
    result = validate_transition(**payload)

    # Assert
    assert result is IncidentStatus(target)
    assert payload == before and payload[field] is text


@pytest.mark.parametrize("current,target,field", TEXT_REQUIRED)
@pytest.mark.parametrize("invalid", [0, True, [], {}, b"texto", object()])
def test_textos_nao_textuais_recusados(current, target, field, invalid):
    # Arrange
    payload = {field: invalid}

    # Act
    with pytest.raises(IncidentTransitionError) as error:
        validate_transition(current, target, **payload)

    # Assert
    assert str(error.value) == "Os textos do Incident devem ser strings."
    assert payload[field] is invalid


@pytest.mark.parametrize("field", ["containment_description", "resolution_conclusion"])
def test_tipo_invalido_recusado_mesmo_quando_texto_nao_obrigatorio(field):
    # Arrange
    payload = {field: {"texto": "não converter automaticamente"}}
    before = deepcopy(payload)

    # Act
    with pytest.raises(IncidentTransitionError):
        validate_transition("OPEN", "UNDER_INVESTIGATION", **payload)

    # Assert
    assert payload == before


def test_iniciar_investigacao_nao_exige_textos():
    # Arrange
    source = IncidentStatus.OPEN

    # Act
    result = validate_transition(source, IncidentStatus.UNDER_INVESTIGATION)

    # Assert
    assert result is IncidentStatus.UNDER_INVESTIGATION
    assert source is IncidentStatus.OPEN


@pytest.mark.parametrize("current,target,texts", [
    ("OPEN", "RESOLVED", {"resolution_conclusion": "Concluído."}),
    ("UNDER_INVESTIGATION", "OPEN", {}),
    ("UNDER_INVESTIGATION", "CONTAINED", {"containment_description": "  "}),
    ("CONTAINED", "RESOLVED", {"resolution_conclusion": None}),
    ("UNDER_INVESTIGATION", "RESOLVED", {"resolution_conclusion": ["não aceitar lista"]}),
])
def test_rejeicao_preserva_estado_e_dados_de_entrada(current, target, texts):
    # Arrange
    state = {"status": IncidentStatus(current), "observations": ["histórico preservado"]}
    payload = {"target_status": target, **texts}
    before = deepcopy((state, payload))

    # Act
    with pytest.raises(IncidentTransitionError):
        state["status"] = validate_transition(state["status"], **payload)

    # Assert
    assert (state, payload) == before


def test_validacao_nao_altera_estado_nem_reflete_textos_em_erros(caplog, capsys):
    # Arrange
    state = {"status": IncidentStatus.OPEN}
    private_text = "observação privada fictícia"

    # Act
    with pytest.raises(IncidentTransitionError) as error:
        validate_transition(state["status"], IncidentStatus.RESOLVED, resolution_conclusion=private_text)
    result = validate_transition(state["status"], IncidentStatus.UNDER_INVESTIGATION)
    captured = capsys.readouterr()

    # Assert
    assert state == {"status": IncidentStatus.OPEN}
    assert result is IncidentStatus.UNDER_INVESTIGATION
    assert private_text not in str(error.value) + caplog.text + captured.out + captured.err
