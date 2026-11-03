from datetime import datetime, timedelta, timezone, tzinfo

import pytest

from app.detection_engine import (
    Alert, DetectionEngine, DetectionRule, Log, SAO_PAULO_TZ,
)


BASE = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


def event(index, seconds=0, kind="AUTH_FAILURE", username="alice", asset="srv-01"):
    return Log(f"evt-{index:03}", asset, BASE + timedelta(seconds=seconds), kind, username)


@pytest.mark.parametrize("end,expected", [(119.999999, 1), (120, 1), (120.000001, 0)])
def test_dr01_window_boundary(end, expected):
    # Arrange
    engine = DetectionEngine()
    logs = [event(i, seconds) for i, seconds in enumerate([0, 30, 60, 90, end])]
    # Act
    result = engine.process_batch(logs)
    # Assert
    assert len(result.accepted_logs) == 5
    assert len(result.alerts) == expected
    if expected:
        assert result.alerts[0].severity == "HIGH"
        assert result.alerts[0].status == "NEW"
        assert [log.event_id for log in result.alerts[0].related_logs] == [log.event_id for log in logs]


@pytest.mark.parametrize("gap,expected", [(120, 0), (120.000001, 1)])
def test_dr01_sequence_boundary(gap, expected):
    # Arrange
    engine = DetectionEngine()
    original = engine.process_batch([event(i, i * 10) for i in range(5)])
    start = 40 + gap
    logs = [event(i + 10, start + i * 10) for i in range(5)]
    # Act
    result = engine.process_batch(logs)
    # Assert
    assert len(original.alerts) == 1
    assert len(result.alerts) == expected


@pytest.mark.parametrize("oldest,expected", [(-300, 1), (-300.000001, 0)])
def test_dr02_lower_boundary(oldest, expected):
    # Arrange
    engine = DetectionEngine()
    logs = [event(0, oldest), event(1, -20), event(2, -10), event(3, 0, "AUTH_SUCCESS")]
    # Act
    result = engine.process_batch(logs)
    # Assert
    assert len(result.accepted_logs) == 4
    assert len(result.alerts) == expected
    if expected:
        assert result.alerts[0].rule_id == "DR02"
        assert result.alerts[0].severity == "MEDIUM"


def test_dr02_excludes_failure_at_success_instant():
    # Arrange
    engine = DetectionEngine()
    logs = [event(0, -20), event(1, -10), event(2), event(3, 0, "AUTH_SUCCESS")]
    # Act
    result = engine.process_batch(logs)
    # Assert
    assert len(result.accepted_logs) == 4
    assert result.alerts == []


@pytest.mark.parametrize("rule", ["DR01", "DR02", "DR03"])
def test_inactive_rule_blocks_matching_events(rule):
    # Arrange
    engine = DetectionEngine()
    engine.set_rule_status(rule, "INACTIVE")
    logs = [event(i, i * 10) for i in range(5)]
    logs += [event(10, 60, "AUTH_SUCCESS"), event(11, 9 * 3600, "ADMIN_ACCESS")]
    # Act
    result = engine.process_batch(logs)
    # Assert
    assert len(result.accepted_logs) == 7
    assert all(alert.rule_id != rule for alert in result.alerts)


@pytest.mark.parametrize("rule,count", [("DR01", 4), ("DR02", 2)])
@pytest.mark.parametrize("other_user,other_asset", [("bob", "srv-01"), ("alice", "srv-02")])
def test_detection_does_not_mix_pairs(rule, count, other_user, other_asset):
    # Arrange
    engine = DetectionEngine()
    logs = [event(i, i * 10) for i in range(count)]
    logs += [event(10, 50, username=other_user, asset=other_asset)]
    if rule == "DR02":
        logs.append(event(11, 60, "AUTH_SUCCESS"))
    # Act
    result = engine.process_batch(logs)
    # Assert
    assert len(result.accepted_logs) == len(logs)
    assert result.alerts == []


def test_equal_timestamps_sort_by_event_id():
    # Arrange
    engine = DetectionEngine()
    logs = [event(2), event(0), event(1)]
    # Act
    result = engine.process_batch(logs)
    # Assert
    assert [log.event_id for log in result.accepted_logs] == ["evt-000", "evt-001", "evt-002"]
    assert result.rejected_logs == []


@pytest.mark.parametrize("seconds", [-0.000001, 0])
def test_later_batch_rejects_old_or_equal_instant(seconds):
    # Arrange
    engine = DetectionEngine()
    engine.process_batch([event(0)])
    old = event(1, seconds, "ADMIN_ACCESS")
    fresh = event(2, 1)
    # Act
    result = engine.process_batch([old, fresh])
    # Assert
    assert result.accepted_logs == [fresh]
    assert len(result.rejected_logs) == 1
    assert result.rejected_logs[0][0] == old
    assert result.alerts == []


@pytest.mark.parametrize("hour,minute,expected", [(10, 59, 1), (11, 0, 0), (20, 59, 0), (21, 0, 1)])
def test_dr03_converts_utc_to_sao_paulo(hour, minute, expected):
    # Arrange
    engine = DetectionEngine()
    instant = BASE.replace(hour=hour, minute=minute)
    log = Log("utc-event", "srv-01", instant, "ADMIN_ACCESS", "alice")
    # Act
    result = engine.process_batch([log])
    # Assert
    assert len(result.alerts) == expected
    if expected:
        assert result.alerts[0].rule_id == "DR03"


class MissingOffset(tzinfo):
    def utcoffset(self, dt):
        return None


@pytest.mark.parametrize("instant", ["2026-10-13T12:00:00", datetime(2026, 10, 13, 12), datetime(2026, 10, 13, 12, tzinfo=MissingOffset())])
def test_log_rejects_missing_timezone(instant):
    # Arrange
    payload = dict(event_id="invalid", asset_id="srv-01", occurred_at=instant, event_type="AUTH_FAILURE", username="alice")
    # Act
    with pytest.raises(ValueError, match="fuso"):
        Log.from_dict(payload)
    # Assert
    assert payload["occurred_at"] == instant


@pytest.mark.parametrize("instant", ["2026-10-13T12:00:00Z", "2026-10-13T09:00:00-03:00", BASE, BASE.astimezone(SAO_PAULO_TZ)])
def test_log_preserves_explicit_instant(instant):
    # Arrange
    payload = dict(event_id="valid", asset_id="srv-01", occurred_at=instant, event_type="AUTH_FAILURE", username="alice")
    # Act
    log = Log.from_dict(payload)
    # Assert
    assert log.occurred_at == BASE


def test_extension_preserves_builtin_results():
    # Arrange
    engine = DetectionEngine()
    reference = DetectionEngine()
    extra = DetectionRule("TEST", "Test evaluator", "LOW")
    seen = []

    def evaluate(log):
        seen.append(log.event_id)
        return Alert("test-alert", "TEST", log.asset_id, log.username, "LOW", log.occurred_at, [log])

    logs = [event(i, i * 10) for i in range(5)]
    logs += [event(6, 60, "AUTH_SUCCESS"), event(7, 9 * 3600, "ADMIN_ACCESS")]
    # Act
    engine.register_rule(extra, evaluate)
    actual = engine.process_batch(logs)
    expected = reference.process_batch(logs)
    # Assert
    assert [alert for alert in actual.alerts if alert.rule_id != "TEST"] == expected.alerts
    assert seen == [log.event_id for log in logs]
    assert len([alert for alert in actual.alerts if alert.rule_id == "TEST"]) == len(logs)


def test_inactive_extension_is_not_evaluated():
    # Arrange
    engine = DetectionEngine()
    seen = []
    engine.register_rule(DetectionRule("TEST", "Test evaluator", "LOW", "INACTIVE"), lambda log: seen.append(log))
    # Act
    result = engine.process_batch([event(0)])
    # Assert
    assert seen == []
    assert result.alerts == []


def test_duplicate_registration_preserves_existing_rule():
    # Arrange
    engine = DetectionEngine()
    original = engine.rules["DR01"]
    # Act
    with pytest.raises(ValueError):
        engine.register_rule(DetectionRule("DR01", "Replacement", "LOW"), lambda log: None)
    # Assert
    assert engine.rules["DR01"] is original


def test_invalid_evaluator_does_not_register_rule():
    # Arrange
    engine = DetectionEngine()
    rule = DetectionRule("TEST", "Invalid evaluator", "LOW")
    # Act
    with pytest.raises(TypeError):
        engine.register_rule(rule, None)
    # Assert
    assert "TEST" not in engine.rules


@pytest.mark.parametrize("rule", ["DR01", "DR02"])
def test_reactivation_preserves_failure_history(rule):
    # Arrange
    engine = DetectionEngine()
    engine.set_rule_status(rule, "INACTIVE")
    count = 4 if rule == "DR01" else 3
    first = engine.process_batch([event(i, i * 10) for i in range(count)])
    kind = "AUTH_FAILURE" if rule == "DR01" else "AUTH_SUCCESS"
    engine.set_rule_status(rule, "ACTIVE")
    # Act
    result = engine.process_batch([event(10, 60, kind)])
    # Assert
    assert first.alerts == []
    assert [alert.rule_id for alert in result.alerts] == [rule]


def test_success_while_inactive_consumes_dr02_failures():
    # Arrange
    engine = DetectionEngine()
    engine.set_rule_status("DR02", "INACTIVE")
    engine.process_batch([event(i, i * 10) for i in range(3)] + [event(3, 30, "AUTH_SUCCESS")])
    engine.set_rule_status("DR02", "ACTIVE")
    # Act
    result = engine.process_batch([event(4, 40, "AUTH_SUCCESS")])
    # Assert
    assert result.alerts == []


def test_status_change_preserves_previous_alert():
    # Arrange
    engine = DetectionEngine()
    alert = engine.process_batch([event(i, i * 10) for i in range(5)]).alerts[0]
    previous = (alert.severity, alert.status, list(alert.related_logs))
    # Act
    engine.set_rule_status("DR01", "INACTIVE")
    engine.set_rule_status("DR01", "ACTIVE")
    # Assert
    assert (alert.severity, alert.status, alert.related_logs) == previous
