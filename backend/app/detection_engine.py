from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from zoneinfo import ZoneInfo
    SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
except Exception:
    SAO_PAULO_TZ = timezone(timedelta(hours=-3))


@dataclass
class Log:
    event_id: str
    asset_id: str
    occurred_at: Union[datetime, str]
    event_type: str
    username: str

    def __post_init__(self):
        if isinstance(self.occurred_at, str):
            self.occurred_at = datetime.fromisoformat(self.occurred_at)
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at deve conter fuso horário explícito.")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Log":
        return cls(
            event_id=data["event_id"],
            asset_id=data["asset_id"],
            occurred_at=data["occurred_at"],
            event_type=data["event_type"],
            username=data["username"],
        )


@dataclass
class DetectionRule:
    rule_id: str
    name: str
    severity: str
    status: str = "ACTIVE"  # "ACTIVE" or "INACTIVE"

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"


@dataclass
class Alert:
    alert_id: str
    rule_id: str
    asset_id: str
    username: str
    severity: str
    created_at: datetime
    related_logs: List[Log]
    status: str = "NEW"


@dataclass
class ProcessingResult:
    accepted_logs: List[Log]
    rejected_logs: List[Tuple[Log, str]]
    alerts: List[Alert]


class DetectionEngine:
    def __init__(self):
        self.rules: Dict[str, DetectionRule] = {
            "DR01": DetectionRule(
                rule_id="DR01",
                name="Multiple Failed Logins",
                severity="HIGH",
                status="ACTIVE",
            ),
            "DR02": DetectionRule(
                rule_id="DR02",
                name="Successful Login After Multiple Failures",
                severity="MEDIUM",
                status="ACTIVE",
            ),
            "DR03": DetectionRule(
                rule_id="DR03",
                name="Administrative Access Outside Allowed Hours",
                severity="MEDIUM",
                status="ACTIVE",
            ),
        }

        # Hist?rico DR01
        self._dr01_sequence: Dict[Tuple[str, str], List[Log]] = {}
        self._dr01_alerted: Dict[Tuple[str, str], bool] = {}

        # Hist?rico DR02
        self._dr02_failures: Dict[Tuple[str, str], List[Log]] = {}

        self._prev_batch_max_time: Dict[Tuple[str, str], datetime] = {}
        self._last_processed_time: Dict[Tuple[str, str], datetime] = {}

        self._alert_id_counter: int = 1
        self._evaluators: Dict[str, Callable[[Log], Optional[Alert]]] = {
            "DR01": self._evaluate_dr01,
            "DR02": self._evaluate_dr02,
            "DR03": self._evaluate_dr03,
        }

    def register_rule(
        self, rule: DetectionRule, evaluator: Callable[[Log], Optional[Alert]]
    ) -> None:
        """Registra uma extensão de desenvolvimento, sem substituir regras existentes."""
        if rule.rule_id in self.rules:
            raise ValueError("Detection Rule já registrada.")
        if not callable(evaluator):
            raise TypeError("O avaliador deve ser chamável.")
        self.rules[rule.rule_id] = rule
        self._evaluators[rule.rule_id] = evaluator

    def set_rule_status(self, rule_id: str, status: str) -> None:
        if rule_id in self.rules:
            self.rules[rule_id].status = status

    def _next_alert_id(self) -> str:
        alert_id = f"alt-{self._alert_id_counter:03d}"
        self._alert_id_counter += 1
        return alert_id

    def process_batch(self, input_logs: List[Union[Log, Dict[str, Any]]]) -> ProcessingResult:
        # Normalize logs
        logs: List[Log] = [
            log if isinstance(log, Log) else Log.from_dict(log)
            for log in input_logs
        ]

        # Ordena eventos
        sorted_logs = sorted(logs, key=lambda l: (l.occurred_at, l.event_id))

        accepted_logs: List[Log] = []
        rejected_logs: List[Tuple[Log, str]] = []
        generated_alerts: List[Alert] = []

        prev_max_snapshot = dict(self._prev_batch_max_time)

        for log in sorted_logs:
            key = (log.username, log.asset_id)

            # Rejeita atraso
            if key in prev_max_snapshot and log.occurred_at <= prev_max_snapshot[key]:
                rejected_logs.append(
                    (log, f"Log fora de ordem: ocorrido em {log.occurred_at.isoformat()} <= último processado {prev_max_snapshot[key].isoformat()}")
                )
                continue

            accepted_logs.append(log)
            self._last_processed_time[key] = log.occurred_at

            # Atualiza histórico
            self._observe_failures(log)
            for rule_id, evaluator in self._evaluators.items():
                if self.rules[rule_id].is_active:
                    alert = evaluator(log)
                    if alert is not None:
                        generated_alerts.append(alert)
            if log.event_type == "AUTH_SUCCESS":
                self._dr02_failures[key] = []

        for key, ts in self._last_processed_time.items():
            self._prev_batch_max_time[key] = ts

        return ProcessingResult(
            accepted_logs=accepted_logs,
            rejected_logs=rejected_logs,
            alerts=generated_alerts,
        )

    def _observe_failures(self, log: Log) -> None:
        if log.event_type != "AUTH_FAILURE":
            return

        key = (log.username, log.asset_id)
        sequence = self._dr01_sequence.get(key, [])
        alerted = self._dr01_alerted.get(key, False)

        if sequence:
            last_fail = sequence[-1]
            delta = (log.occurred_at - last_fail.occurred_at).total_seconds()
            if delta > 120:
                # Reinicia sequ?ncia

                sequence = [log]
                alerted = False
            else:
                sequence.append(log)
        else:
            sequence = [log]
            alerted = False

        self._dr01_sequence[key] = sequence
        self._dr01_alerted[key] = alerted
        self._dr02_failures.setdefault(key, []).append(log)

    def _evaluate_dr01(self, log: Log) -> Optional[Alert]:
        if log.event_type != "AUTH_FAILURE":
            return None
        key = (log.username, log.asset_id)
        sequence = self._dr01_sequence[key]
        alerted = self._dr01_alerted[key]

        rule = self.rules.get("DR01")
        if rule and rule.is_active and not alerted:

            if len(sequence) >= 5:
                window_delta = (sequence[-1].occurred_at - sequence[-5].occurred_at).total_seconds()
                if window_delta <= 120:
                    self._dr01_alerted[key] = True
                    return Alert(
                        alert_id=self._next_alert_id(),
                        rule_id="DR01",
                        asset_id=log.asset_id,
                        username=log.username,
                        severity=rule.severity,
                        created_at=log.occurred_at,
                        related_logs=list(sequence),
                        status="NEW",
                    )

        return None

    def _evaluate_dr02(self, log: Log) -> Optional[Alert]:
        key = (log.username, log.asset_id)

        if log.event_type == "AUTH_SUCCESS":
            failures = self._dr02_failures.get(key, [])
            t_success = log.occurred_at

            # Janela anterior
            matching_failures = [
                f for f in failures
                if f.occurred_at < t_success and (t_success - f.occurred_at).total_seconds() <= 300
            ]

            alert: Optional[Alert] = None
            rule = self.rules.get("DR02")
            if len(matching_failures) >= 3 and rule and rule.is_active:
                alert = Alert(
                    alert_id=self._next_alert_id(),
                    rule_id="DR02",
                    asset_id=log.asset_id,
                    username=log.username,
                    severity=rule.severity,
                    created_at=log.occurred_at,
                    related_logs=matching_failures + [log],
                    status="NEW",
                )

            return alert

        return None

    def _evaluate_dr03(self, log: Log) -> Optional[Alert]:
        if log.event_type != "ADMIN_ACCESS":
            return None

        rule = self.rules.get("DR03")
        if not rule or not rule.is_active:
            return None

        # Converte fuso
        local_dt = log.occurred_at.astimezone(SAO_PAULO_TZ)

        is_weekday = local_dt.weekday() < 5
        is_working_hours = time(8, 0, 0) <= local_dt.time() < time(18, 0, 0)

        if not (is_weekday and is_working_hours):
            return Alert(
                alert_id=self._next_alert_id(),
                rule_id="DR03",
                asset_id=log.asset_id,
                username=log.username,
                severity=rule.severity,
                created_at=log.occurred_at,
                related_logs=[log],
                status="NEW",
            )

        return None
