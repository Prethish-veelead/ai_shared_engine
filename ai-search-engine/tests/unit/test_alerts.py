"""Pure-logic unit tests for the resource-threshold alert checker
(app/monitoring/alerts.py) - no real DB or psutil call needed. Everything
here uses monkeypatched stand-ins for get_resources()/record_event()/the
debounce query, so these run instantly and never touch Postgres.

Stateful behavior (a real threshold crossing actually writing an EventLog
row, and the debounce genuinely surviving across two real checks) was
verified live, consistent with how the rest of this repo's work has been
verified throughout.
"""
import app.monitoring.alerts as alerts_module
from app.monitoring.alerts import check_resource_thresholds


class _FakeDb:
    """Stands in for the Session - only .execute()/.commit() are ever
    touched by check_resource_thresholds/_recently_alerted."""

    def __init__(self, recently_alerted: bool = False):
        self._recently_alerted = recently_alerted
        self.committed = False

    def execute(self, *args, **kwargs):
        class _Result:
            def __init__(self, hit):
                self._hit = hit

            def first(self):
                return (1,) if self._hit else None

        return _Result(self._recently_alerted)

    def commit(self):
        self.committed = True


def _patch_resources(monkeypatch, memory_pct: float, disk_pct: float):
    monkeypatch.setattr(alerts_module, "get_resources", lambda: {
        "memory": {"usedBytes": 0, "limitBytes": 0, "pct": memory_pct},
        "cpu": {"pct": 0.0},
        "disk": {"totalBytes": 0, "usedBytes": 0, "freeBytes": 0, "pct": disk_pct},
        "process": {"rssBytes": 0, "cpuPct": 0.0},
        "containers": None, "containersAvailable": False,
        "source": "psutil", "note": "",
    })


def _capture_record_event(monkeypatch):
    calls = []
    monkeypatch.setattr(alerts_module, "record_event",
                        lambda db, *, type, message, bot_id=None: calls.append({"type": type, "message": message}))
    return calls


def test_below_threshold_records_nothing(monkeypatch):
    _patch_resources(monkeypatch, memory_pct=50.0, disk_pct=40.0)
    calls = _capture_record_event(monkeypatch)

    check_resource_thresholds(_FakeDb(recently_alerted=False))

    assert calls == []


def test_above_threshold_records_an_alert(monkeypatch):
    _patch_resources(monkeypatch, memory_pct=95.0, disk_pct=40.0)
    calls = _capture_record_event(monkeypatch)

    check_resource_thresholds(_FakeDb(recently_alerted=False))

    assert len(calls) == 1
    assert calls[0]["type"] == "resource"
    assert "Memory usage" in calls[0]["message"]
    assert "95.0%" in calls[0]["message"]


def test_both_metrics_above_threshold_records_two_alerts(monkeypatch):
    _patch_resources(monkeypatch, memory_pct=91.0, disk_pct=99.0)
    calls = _capture_record_event(monkeypatch)

    check_resource_thresholds(_FakeDb(recently_alerted=False))

    labels = {c["message"].split(" at ")[0] for c in calls}
    assert labels == {"Memory usage", "Disk usage"}


def test_debounce_suppresses_a_repeat_alert(monkeypatch):
    # Same metric already alerted recently (per the fake db) - must NOT
    # record a second one, or a sustained high-usage period would spam a
    # new notification every check interval forever.
    _patch_resources(monkeypatch, memory_pct=95.0, disk_pct=40.0)
    calls = _capture_record_event(monkeypatch)

    check_resource_thresholds(_FakeDb(recently_alerted=True))

    assert calls == []


def test_get_resources_failure_does_not_raise(monkeypatch):
    def _boom():
        raise RuntimeError("psutil exploded")
    monkeypatch.setattr(alerts_module, "get_resources", _boom)
    calls = _capture_record_event(monkeypatch)

    check_resource_thresholds(_FakeDb())  # must not raise

    assert calls == []
