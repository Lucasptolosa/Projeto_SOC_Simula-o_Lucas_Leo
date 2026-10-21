from datetime import datetime, timedelta

from app.detection_engine import SAO_PAULO_TZ, DetectionEngine, Log



def test_dr01_five_failures_within_120s_triggers_high_alert():
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)

    # 4 failures -> no alert
    batch_4 = [
        Log(f"evt-0{i}", "srv-01", base_time + timedelta(seconds=i * 20), "AUTH_FAILURE", "user1")
        for i in range(1, 5)
    ]
    res1 = engine.process_batch(batch_4)
    assert len(res1.alerts) == 0

    # 5th failure at t=100s: after the previous batch's last event (t=80s)
    # and within the 120s window measured from the first failure (t=20s).
    batch_5th = [
        Log("evt-05", "srv-01", base_time + timedelta(seconds=100), "AUTH_FAILURE", "user1")
    ]
    res2 = engine.process_batch(batch_5th)
    assert len(res2.accepted_logs) == 1
    assert len(res2.rejected_logs) == 0
    assert len(res2.alerts) == 1
    alert = res2.alerts[0]
    assert alert.rule_id == "DR01"
    assert alert.severity == "HIGH"
    assert alert.asset_id == "srv-01"
    assert alert.username == "user1"
    assert len(alert.related_logs) == 5


def test_dr01_deduplication_and_sequence_reset():
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)

    # 5 failures -> 1 alert
    batch1 = [
        Log(f"evt-{i:02d}", "srv-01", base_time + timedelta(seconds=i * 10), "AUTH_FAILURE", "user1")
        for i in range(1, 6)
    ]
    res1 = engine.process_batch(batch1)
    assert len(res1.alerts) == 1

    # 6th failure at t=60s (delta=10s <= 120s) -> no duplicate alert
    batch2 = [
        Log("evt-06", "srv-01", base_time + timedelta(seconds=60), "AUTH_FAILURE", "user1")
    ]
    res2 = engine.process_batch(batch2)
    assert len(res2.alerts) == 0

    # AUTH_SUCCESS does not break DR01 sequence
    batch_success = [
        Log("evt-succ", "srv-01", base_time + timedelta(seconds=70), "AUTH_SUCCESS", "user1")
    ]
    engine.process_batch(batch_success)

    # 7th failure at t=80s (delta from 6th fail = 20s <= 120s) -> still no duplicate alert
    batch3 = [
        Log("evt-07", "srv-01", base_time + timedelta(seconds=80), "AUTH_FAILURE", "user1")
    ]
    res3 = engine.process_batch(batch3)
    assert len(res3.alerts) == 0

    # 8th failure at t=210s (delta from 7th fail = 130s > 120s) -> sequence resets!
    # Followed by 4 more failures in a new sequence (5 fails total in new sequence)
    batch_new_seq = [
        Log(f"evt-new-{i}", "srv-01", base_time + timedelta(seconds=210 + i * 10), "AUTH_FAILURE", "user1")
        for i in range(5)
    ]
    res4 = engine.process_batch(batch_new_seq)
    assert len(res4.alerts) == 1
    assert res4.alerts[0].rule_id == "DR01"


def test_dr01_failures_spread_over_120s_no_alert():
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)

    # 5 failures spaced 40s apart (total 160s) -> no 5 failures within 120s window
    batch = [
        Log(f"evt-{i}", "srv-01", base_time + timedelta(seconds=i * 40), "AUTH_FAILURE", "user1")
        for i in range(5)
    ]
    res = engine.process_batch(batch)
    assert len(res.alerts) == 0


def test_dr02_success_after_three_failures_in_300s():
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)

    # 2 failures followed by success -> no alert
    batch1 = [
        Log("evt-01", "srv-01", base_time, "AUTH_FAILURE", "user1"),
        Log("evt-02", "srv-01", base_time + timedelta(seconds=10), "AUTH_FAILURE", "user1"),
        Log("evt-03", "srv-01", base_time + timedelta(seconds=20), "AUTH_SUCCESS", "user1"),
    ]
    res1 = engine.process_batch(batch1)
    assert len(res1.alerts) == 0

    # Gap >120s since the preceding failure resets DR01's failure sequence.
    # These 3 failures and the success are still within DR02's 300s window.
    batch2 = [
        Log("evt-04", "srv-01", base_time + timedelta(seconds=200), "AUTH_FAILURE", "user1"),
        Log("evt-05", "srv-01", base_time + timedelta(seconds=210), "AUTH_FAILURE", "user1"),
        Log("evt-06", "srv-01", base_time + timedelta(seconds=220), "AUTH_FAILURE", "user1"),
        Log("evt-07", "srv-01", base_time + timedelta(seconds=230), "AUTH_SUCCESS", "user1"),
    ]
    res2 = engine.process_batch(batch2)
    assert len(res2.accepted_logs) == 4
    assert len(res2.rejected_logs) == 0
    assert len(res2.alerts) == 1
    alert = res2.alerts[0]
    assert alert.rule_id == "DR02"
    assert alert.severity == "MEDIUM"
    assert len(alert.related_logs) == 4  # 3 failures + 1 success

    # Subsequent success without new failures -> no alert (failures were consumed)
    batch3 = [
        Log("evt-08", "srv-01", base_time + timedelta(seconds=240), "AUTH_SUCCESS", "user1")
    ]
    res3 = engine.process_batch(batch3)
    assert len(res3.alerts) == 0


def test_dr02_failures_older_than_300s_ignored():
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)

    # 2 failures 400s ago, 1 failure 10s ago, followed by success -> only 1 failure in 300s window -> no alert
    batch = [
        Log("evt-01", "srv-01", base_time - timedelta(seconds=450), "AUTH_FAILURE", "user1"),
        Log("evt-02", "srv-01", base_time - timedelta(seconds=400), "AUTH_FAILURE", "user1"),
        Log("evt-03", "srv-01", base_time - timedelta(seconds=10), "AUTH_FAILURE", "user1"),
        Log("evt-04", "srv-01", base_time, "AUTH_SUCCESS", "user1"),
    ]
    res = engine.process_batch(batch)
    assert len(res.alerts) == 0


def test_dr03_admin_access_hours():
    engine = DetectionEngine()

    # Tuesday 08:00 -> inclusive allowed -> no alert
    # Process this boundary case first to avoid rejection by the batch ordering rule.
    tue_08am = datetime(2026, 10, 13, 8, 0, 0, tzinfo=SAO_PAULO_TZ)
    res1 = engine.process_batch([Log("e1", "srv-01", tue_08am, "ADMIN_ACCESS", "admin1")])
    assert len(res1.accepted_logs) == 1
    assert len(res1.rejected_logs) == 0
    assert len(res1.alerts) == 0

    # Tuesday 10:00 -> allowed -> no alert
    tue_10am = datetime(2026, 10, 13, 10, 0, 0, tzinfo=SAO_PAULO_TZ)
    res2 = engine.process_batch([Log("e2", "srv-01", tue_10am, "ADMIN_ACCESS", "admin1")])
    assert len(res2.accepted_logs) == 1
    assert len(res2.alerts) == 0

    # Tuesday 18:00 -> outside allowed (18:00 is exclusive) -> triggers DR03
    tue_18pm = datetime(2026, 10, 13, 18, 0, 0, tzinfo=SAO_PAULO_TZ)
    res3 = engine.process_batch([Log("e3", "srv-01", tue_18pm, "ADMIN_ACCESS", "admin1")])
    assert len(res3.alerts) == 1
    assert res3.alerts[0].rule_id == "DR03"
    assert res3.alerts[0].severity == "MEDIUM"

    # Tuesday 20:00 -> outside allowed -> triggers DR03
    tue_20pm = datetime(2026, 10, 13, 20, 0, 0, tzinfo=SAO_PAULO_TZ)
    res4 = engine.process_batch([Log("e4", "srv-01", tue_20pm, "ADMIN_ACCESS", "admin1")])
    assert len(res4.alerts) == 1

    # Sunday 10:00 -> weekend -> triggers DR03
    sun_10am = datetime(2026, 10, 18, 10, 0, 0, tzinfo=SAO_PAULO_TZ)
    res5 = engine.process_batch([Log("e5", "srv-01", sun_10am, "ADMIN_ACCESS", "admin1")])
    assert len(res5.alerts) == 1


def test_batch_sorting_and_out_of_order_rejection():
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)

    # Batch 1 with unsorted logs
    batch1 = [
        Log("evt-02", "srv-01", base_time + timedelta(seconds=20), "AUTH_FAILURE", "user1"),
        Log("evt-01", "srv-01", base_time + timedelta(seconds=10), "AUTH_FAILURE", "user1"),
    ]
    res1 = engine.process_batch(batch1)
    assert [l.event_id for l in res1.accepted_logs] == ["evt-01", "evt-02"]

    # Batch 2 contains a log with timestamp <= last processed timestamp of Batch 1 (14:00:20)
    batch2 = [
        Log("evt-old", "srv-01", base_time + timedelta(seconds=15), "AUTH_FAILURE", "user1"),
        Log("evt-03", "srv-01", base_time + timedelta(seconds=30), "AUTH_FAILURE", "user1"),
    ]
    res2 = engine.process_batch(batch2)
    assert len(res2.accepted_logs) == 1
    assert res2.accepted_logs[0].event_id == "evt-03"
    assert len(res2.rejected_logs) == 1
    assert res2.rejected_logs[0][0].event_id == "evt-old"


def test_inactive_rules_do_not_generate_alerts():
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)

    engine.set_rule_status("DR01", "INACTIVE")
    engine.set_rule_status("DR03", "INACTIVE")

    # 5 failures
    batch_dr01 = [
        Log(f"evt-{i}", "srv-01", base_time + timedelta(seconds=i * 10), "AUTH_FAILURE", "user1")
        for i in range(1, 6)
    ]
    res1 = engine.process_batch(batch_dr01)
    assert len(res1.alerts) == 0

    # Admin access on Sunday
    sun_10am = datetime(2026, 10, 18, 10, 0, 0, tzinfo=SAO_PAULO_TZ)
    res2 = engine.process_batch([Log("e-sun", "srv-01", sun_10am, "ADMIN_ACCESS", "admin1")])
    assert len(res2.alerts) == 0


def test_multi_user_and_multi_asset_isolation():
    engine = DetectionEngine()
    base_time = datetime(2026, 10, 8, 14, 0, 0, tzinfo=SAO_PAULO_TZ)

    # 4 failures for user1/srv-01 and 4 failures for user2/srv-02
    batch = []
    for i in range(1, 5):
        batch.append(Log(f"u1-{i}", "srv-01", base_time + timedelta(seconds=i * 10), "AUTH_FAILURE", "user1"))
        batch.append(Log(f"u2-{i}", "srv-02", base_time + timedelta(seconds=i * 10), "AUTH_FAILURE", "user2"))

    res1 = engine.process_batch(batch)
    assert len(res1.alerts) == 0

    # 5th failure for user1/srv-01 only
    res2 = engine.process_batch([
        Log("u1-5", "srv-01", base_time + timedelta(seconds=50), "AUTH_FAILURE", "user1")
    ])
    assert len(res2.alerts) == 1
    assert res2.alerts[0].username == "user1"
    assert res2.alerts[0].asset_id == "srv-01"
