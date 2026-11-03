from copy import deepcopy
from enum import StrEnum
from pathlib import Path
import subprocess
import sys

import pytest

from app.investigations.rules import (
    InvestigationRuleError,
    validate_escalation_eligibility,
    validate_false_positive,
    validate_start_investigation,
)


STATUSES = ("NEW", "IN_REVIEW", "DISMISSED", "ESCALATED")
DECISIONS = (
    (validate_start_investigation, {}, "NEW", "IN_REVIEW"),
    (validate_false_positive, {"justification": "Atividade legítima confirmada."}, "IN_REVIEW", "DISMISSED"),
    (validate_escalation_eligibility, {}, "IN_REVIEW", None),
)


@pytest.mark.parametrize("validate,arguments,source,expected", DECISIONS)
def test_decisoes_permitidas_para_analyst(validate, arguments, source, expected):
    # Arrange
    payload = {"actor_role": "ANALYST", **arguments}

    # Act
    result = validate(source, **payload)

    # Assert
    assert result == expected
    assert result != "ESCALATED"


@pytest.mark.parametrize("validate,arguments,source", [
    (validate, arguments, source)
    for validate, arguments, permitted, _ in DECISIONS
    for source in STATUSES if source != permitted
])
def test_inicio_repetido_terminais_e_reversoes_recusados(validate, arguments, source):
    # Arrange
    payload = {"actor_role": "ANALYST", **arguments}
    before = deepcopy(payload)

    # Act
    with pytest.raises(InvestigationRuleError):
        validate(source, **payload)

    # Assert
    assert payload == before
    assert source in STATUSES


@pytest.mark.parametrize("validate,arguments,source,expected", DECISIONS)
@pytest.mark.parametrize("role", ["ADMIN", None, "analyst", " ANALYST", 0, True, [], {}, b"ANALYST", "UNKNOWN"])
def test_papel_diferente_de_analyst_recusado(validate, arguments, source, expected, role):
    # Arrange
    payload = {"actor_role": role, **arguments}

    # Act
    with pytest.raises(InvestigationRuleError) as error:
        validate(source, **payload)

    # Assert
    assert str(error.value) == "Operação exclusiva de ANALYST."
    assert payload["actor_role"] is role


@pytest.mark.parametrize("validate,arguments,source,expected", DECISIONS)
def test_papel_obrigatorio_sem_analyst_implicito(validate, arguments, source, expected):
    # Arrange
    payload = arguments.copy()

    # Act
    with pytest.raises(TypeError):
        validate(source, **payload)

    # Assert
    assert "actor_role" not in payload


@pytest.mark.parametrize("validate,arguments,source,expected", DECISIONS)
@pytest.mark.parametrize("invalid", [None, "", "new", " NEW", "NEW ", "OPEN", 0, True, [], {}, b"NEW", object()])
def test_status_desconhecido_ou_tipo_invalido(validate, arguments, source, expected, invalid):
    # Arrange
    payload = {"actor_role": "ANALYST", **arguments}

    # Act
    with pytest.raises(InvestigationRuleError) as error:
        validate(invalid, **payload)

    # Assert
    assert str(error.value) == "Estado de Alert inválido."


@pytest.mark.parametrize("invalid", [
    None, "", " ", "\t\r\n", "\u00a0", "\u2003", " \t\u00a0\n",
    0, True, [], {}, b"justificativa", object(),
])
def test_justificativa_ausente_vazia_whitespace_ou_nao_textual(invalid):
    # Arrange
    payload = {"justification": invalid, "actor_role": "ANALYST"}

    # Act
    with pytest.raises(InvestigationRuleError) as error:
        validate_false_positive("IN_REVIEW", **payload)

    # Assert
    assert str(error.value) == "Informe uma justificativa textual não vazia."
    assert payload["justification"] is invalid


def test_justificativa_omitida_recusada():
    # Arrange
    status = "IN_REVIEW"

    # Act
    with pytest.raises(InvestigationRuleError) as error:
        validate_false_positive(status, actor_role="ANALYST")

    # Assert
    assert "justificativa textual não vazia" in str(error.value)


@pytest.mark.parametrize("text", [
    "x", "  ação legítima confirmada  ", "Evidência revisada.\nOperação autorizada.", "x" * 10000,
], ids=["minimo", "acentos-espacos", "multilinha", "sem-truncamento"])
def test_justificativa_valida_sem_alterar_original(text):
    # Arrange
    state = {"status": "IN_REVIEW", "observations": ["Evidência original."]}
    payload = {"justification": text, "actor_role": "ANALYST"}
    before = deepcopy((state, payload))

    # Act
    result = validate_false_positive(state["status"], **payload)

    # Assert
    assert result == "DISMISSED"
    assert (state, payload) == before
    assert payload["justification"] is text


@pytest.mark.parametrize("validate,arguments,source,expected", DECISIONS)
def test_compatibilidade_com_valores_strenum_sem_enum_de_producao(validate, arguments, source, expected):
    # Arrange
    status_type = StrEnum("TestStatus", {source: source})
    role_type = StrEnum("TestRole", {"ANALYST": "ANALYST"})

    # Act
    result = validate(status_type(source), actor_role=role_type.ANALYST, **arguments)

    # Assert
    assert result == expected


def test_elegibilidade_nao_marca_alert_como_escalated():
    # Arrange
    state = {"status": "IN_REVIEW", "incident_id": None, "observations": ["histórico"]}
    before = deepcopy(state)

    # Act
    result = validate_escalation_eligibility(state["status"], actor_role="ANALYST")

    # Assert
    assert result is None
    assert state == before


@pytest.mark.parametrize("source,arguments", [
    ("NEW", {"justification": "Válida."}),
    ("DISMISSED", {"justification": "Válida."}),
    ("IN_REVIEW", {"justification": " \t\n"}),
    ("IN_REVIEW", {"justification": ["Não converter lista"]}),
])
def test_rejeicao_nao_altera_estado_ou_payload(source, arguments):
    # Arrange
    state = {"status": source, "observations": ["original"]}
    before = deepcopy((state, arguments))

    # Act
    with pytest.raises(InvestigationRuleError):
        state["status"] = validate_false_positive(state["status"], actor_role="ANALYST", **arguments)

    # Assert
    assert (state, arguments) == before


@pytest.mark.parametrize("source,role,justification", [
    ("NEW", "ANALYST", "observação privada fictícia"),
    ("IN_REVIEW", "ADMIN", "observação privada fictícia"),
    ("observação privada fictícia", "ANALYST", "outra observação"),
    ("IN_REVIEW", "ANALYST", ["observação privada fictícia"]),
])
def test_erros_nao_expoem_observacoes(source, role, justification, caplog, capsys):
    # Arrange
    private_text = "observação privada fictícia"

    # Act
    with pytest.raises(InvestigationRuleError) as error:
        validate_false_positive(source, justification, actor_role=role)
    captured = capsys.readouterr()

    # Assert
    assert private_text not in str(error.value) + caplog.text + captured.out + captured.err
    assert not caplog.text and not captured.out and not captured.err


def test_nucleo_sem_banco_pacotes_externos_ou_io(tmp_path):
    # Arrange
    backend = Path(__file__).resolve().parents[1]
    program = """
import builtins, socket, sys
sys.path.insert(0, sys.argv[1])
from app.investigations.rules import (
    validate_start_investigation, validate_false_positive, validate_escalation_eligibility,
)
def forbidden(*args, **kwargs):
    raise AssertionError('I/O não permitido')
builtins.open = forbidden
socket.socket = forbidden
socket.create_connection = forbidden
assert validate_start_investigation('NEW', actor_role='ANALYST') == 'IN_REVIEW'
assert validate_false_positive('IN_REVIEW', 'Atividade legítima.', actor_role='ANALYST') == 'DISMISSED'
assert validate_escalation_eligibility('IN_REVIEW', actor_role='ANALYST') is None
assert not {'sqlalchemy', 'psycopg', 'app.incidents', 'app.detection_engine'}.intersection(sys.modules)
"""

    # Act
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", program, str(backend)], cwd=tmp_path,
        capture_output=True, text=True, timeout=10,
    )

    # Assert
    assert result.returncode == 0, result.stderr
    assert not result.stdout and not result.stderr
