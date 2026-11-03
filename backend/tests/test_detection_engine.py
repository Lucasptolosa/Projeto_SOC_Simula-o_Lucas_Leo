from datetime import datetime, timedelta

from app.detection_engine import SAO_PAULO_TZ, DetectionEngine, Log


def test_dr01_five_failures_within_120s_triggers_high_alert():
    # Arrange
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)


    batch_4 = [
        Log(f"evt-0{i}", "srv-01", base_time + timedelta(seconds=i * 20), "AUTH_FAILURE", "user1")
        for i in range(1, 5)
    ]
    # Act
    res1 = engine.process_batch(batch_4)
    # Assert
    assert len(res1.alerts) == 0


    # Arrange
    batch_5th = [
        Log("evt-05", "srv-01", base_time + timedelta(seconds=100), "AUTH_FAILURE", "user1")
    ]
    # Act
    res2 = engine.process_batch(batch_5th)
    # Assert
    assert len(res2.accepted_logs) == 1
    assert len(res2.rejected_logs) == 0
    assert len(res2.alerts) == 1
    # Arrange
    alert = res2.alerts[0]
    # Assert
    assert alert.rule_id == "DR01"
    assert alert.severity == "HIGH"
    assert alert.asset_id == "srv-01"
    assert alert.username == "user1"
    assert len(alert.related_logs) == 5


def test_dr01_deduplication_and_sequence_reset():
    # Arrange
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)


    batch1 = [
        Log(f"evt-{i:02d}", "srv-01", base_time + timedelta(seconds=i * 10), "AUTH_FAILURE", "user1")
        for i in range(1, 6)
    ]
    # Act
    res1 = engine.process_batch(batch1)
    # Assert
    assert len(res1.alerts) == 1


    # Arrange
    batch2 = [
        Log("evt-06", "srv-01", base_time + timedelta(seconds=60), "AUTH_FAILURE", "user1")
    ]
    # Act
    res2 = engine.process_batch(batch2)
    # Assert
    assert len(res2.alerts) == 0


    # Arrange
    batch_success = [
        Log("evt-succ", "srv-01", base_time + timedelta(seconds=70), "AUTH_SUCCESS", "user1")
    ]
    # Act
    engine.process_batch(batch_success)


    # Arrange
    batch3 = [
        Log("evt-07", "srv-01", base_time + timedelta(seconds=80), "AUTH_FAILURE", "user1")
    ]
    # Act
    res3 = engine.process_batch(batch3)
    # Assert
    assert len(res3.alerts) == 0


    # Arrange
    batch_new_seq = [
        Log(f"evt-new-{i}", "srv-01", base_time + timedelta(seconds=210 + i * 10), "AUTH_FAILURE", "user1")
        for i in range(5)
    ]
    # Act
    res4 = engine.process_batch(batch_new_seq)
    # Assert
    assert len(res4.alerts) == 1
    assert res4.alerts[0].rule_id == "DR01"


def test_dr01_failures_spread_over_120s_no_alert():
    # Arrange
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)


    batch = [
        Log(f"evt-{i}", "srv-01", base_time + timedelta(seconds=i * 40), "AUTH_FAILURE", "user1")
        for i in range(5)
    ]
    # Act
    res = engine.process_batch(batch)
    # Assert
    assert len(res.alerts) == 0


def test_dr02_success_after_three_failures_in_300s():
    # Arrange
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)


    batch1 = [
        Log("evt-01", "srv-01", base_time, "AUTH_FAILURE", "user1"),
        Log("evt-02", "srv-01", base_time + timedelta(seconds=10), "AUTH_FAILURE", "user1"),
        Log("evt-03", "srv-01", base_time + timedelta(seconds=20), "AUTH_SUCCESS", "user1"),
    ]
    # Act
    res1 = engine.process_batch(batch1)
    # Assert
    assert len(res1.alerts) == 0


    # Arrange
    batch2 = [
        Log("evt-04", "srv-01", base_time + timedelta(seconds=200), "AUTH_FAILURE", "user1"),
        Log("evt-05", "srv-01", base_time + timedelta(seconds=210), "AUTH_FAILURE", "user1"),
        Log("evt-06", "srv-01", base_time + timedelta(seconds=220), "AUTH_FAILURE", "user1"),
        Log("evt-07", "srv-01", base_time + timedelta(seconds=230), "AUTH_SUCCESS", "user1"),
    ]
    # Act
    res2 = engine.process_batch(batch2)
    # Assert
    assert len(res2.accepted_logs) == 4
    assert len(res2.rejected_logs) == 0
    assert len(res2.alerts) == 1
    # Arrange
    alert = res2.alerts[0]
    # Assert
    assert alert.rule_id == "DR02"
    assert alert.severity == "MEDIUM"
    assert len(alert.related_logs) == 4


    # Arrange
    batch3 = [
        Log("evt-08", "srv-01", base_time + timedelta(seconds=240), "AUTH_SUCCESS", "user1")
    ]
    # Act
    res3 = engine.process_batch(batch3)
    # Assert
    assert len(res3.alerts) == 0


def test_dr02_failures_older_than_300s_ignored():
    # Arrange
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)


    batch = [
        Log("evt-01", "srv-01", base_time - timedelta(seconds=450), "AUTH_FAILURE", "user1"),
        Log("evt-02", "srv-01", base_time - timedelta(seconds=400), "AUTH_FAILURE", "user1"),
        Log("evt-03", "srv-01", base_time - timedelta(seconds=10), "AUTH_FAILURE", "user1"),
        Log("evt-04", "srv-01", base_time, "AUTH_SUCCESS", "user1"),
    ]
    # Act
    res = engine.process_batch(batch)
    # Assert
    assert len(res.alerts) == 0


def test_dr03_admin_access_hours():
    # Arrange
    engine = DetectionEngine()


    tue_08am = datetime(2026, 10, 13, 8, 0, 0, tzinfo=SAO_PAULO_TZ)
    # Act
    res1 = engine.process_batch([Log("e1", "srv-01", tue_08am, "ADMIN_ACCESS", "admin1")])
    # Assert
    assert len(res1.accepted_logs) == 1
    assert len(res1.rejected_logs) == 0
    assert len(res1.alerts) == 0


    # Arrange
    tue_10am = datetime(2026, 10, 13, 10, 0, 0, tzinfo=SAO_PAULO_TZ)
    # Act
    res2 = engine.process_batch([Log("e2", "srv-01", tue_10am, "ADMIN_ACCESS", "admin1")])
    # Assert
    assert len(res2.accepted_logs) == 1
    assert len(res2.alerts) == 0


    # Arrange
    tue_18pm = datetime(2026, 10, 13, 18, 0, 0, tzinfo=SAO_PAULO_TZ)
    # Act
    res3 = engine.process_batch([Log("e3", "srv-01", tue_18pm, "ADMIN_ACCESS", "admin1")])
    # Assert
    assert len(res3.alerts) == 1
    assert res3.alerts[0].rule_id == "DR03"
    assert res3.alerts[0].severity == "MEDIUM"


    # Arrange
    tue_20pm = datetime(2026, 10, 13, 20, 0, 0, tzinfo=SAO_PAULO_TZ)
    # Act
    res4 = engine.process_batch([Log("e4", "srv-01", tue_20pm, "ADMIN_ACCESS", "admin1")])
    # Assert
    assert len(res4.alerts) == 1


    # Arrange
    sun_10am = datetime(2026, 10, 18, 10, 0, 0, tzinfo=SAO_PAULO_TZ)
    # Act
    res5 = engine.process_batch([Log("e5", "srv-01", sun_10am, "ADMIN_ACCESS", "admin1")])
    # Assert
    assert len(res5.alerts) == 1


def test_batch_sorting_and_out_of_order_rejection():
    # Arrange
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)


    batch1 = [
        Log("evt-02", "srv-01", base_time + timedelta(seconds=20), "AUTH_FAILURE", "user1"),
        Log("evt-01", "srv-01", base_time + timedelta(seconds=10), "AUTH_FAILURE", "user1"),
    ]
    # Act
    res1 = engine.process_batch(batch1)
    # Assert
    assert [l.event_id for l in res1.accepted_logs] == ["evt-01", "evt-02"]


    # Arrange
    batch2 = [
        Log("evt-old", "srv-01", base_time + timedelta(seconds=15), "AUTH_FAILURE", "user1"),
        Log("evt-03", "srv-01", base_time + timedelta(seconds=30), "AUTH_FAILURE", "user1"),
    ]
    # Act
    res2 = engine.process_batch(batch2)
    # Assert
    assert len(res2.accepted_logs) == 1
    assert res2.accepted_logs[0].event_id == "evt-03"
    assert len(res2.rejected_logs) == 1
    assert res2.rejected_logs[0][0].event_id == "evt-old"


def test_inactive_rules_do_not_generate_alerts():
    # Arrange
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)

    engine.set_rule_status("DR01", "INACTIVE")
    engine.set_rule_status("DR03", "INACTIVE")

    # 5 failures
    batch_dr01 = [
        Log(f"evt-{i}", "srv-01", base_time + timedelta(seconds=i * 10), "AUTH_FAILURE", "user1")
        for i in range(1, 6)
    ]
    # Act
    res1 = engine.process_batch(batch_dr01)
    # Assert
    assert len(res1.alerts) == 0


    # Arrange
    sun_10am = datetime(2026, 10, 18, 10, 0, 0, tzinfo=SAO_PAULO_TZ)
    # Act
    res2 = engine.process_batch([Log("e-sun", "srv-01", sun_10am, "ADMIN_ACCESS", "admin1")])
    # Assert
    assert len(res2.alerts) == 0


def test_multi_user_and_multi_asset_isolation():
    # Arrange
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)


    batch = []
    for i in range(1, 5):
        batch.append(Log(f"u1-{i}", "srv-01", base_time + timedelta(seconds=i * 10), "AUTH_FAILURE", "user1"))
        batch.append(Log(f"u2-{i}", "srv-02", base_time + timedelta(seconds=i * 10), "AUTH_FAILURE", "user2"))

    # Act
    res1 = engine.process_batch(batch)
    # Assert
    assert len(res1.alerts) == 0


    # Act
    res2 = engine.process_batch([
        Log("u1-5", "srv-01", base_time + timedelta(seconds=50), "AUTH_FAILURE", "user1")
    ])
    # Assert
    assert len(res2.alerts) == 1
    assert res2.alerts[0].username == "user1"
    assert res2.alerts[0].asset_id == "srv-01"
