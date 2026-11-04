from dataclasses import asdict
from datetime import datetime

from app.detection_engine import DetectionEngine, Log


def dump_state(engine: DetectionEngine) -> dict:
    """Serializa somente estado interno."""
    def history(values):
        return [dict(username=key[0], asset_id=key[1], logs=[
            asdict(log) | {"occurred_at": log.occurred_at.isoformat()} for log in logs
        ]) for key, logs in values.items()]

    return {
        "version": 1,
        "dr01_sequence": history(engine._dr01_sequence),
        "dr01_alerted": [dict(username=k[0], asset_id=k[1], alerted=v)
                         for k, v in engine._dr01_alerted.items()],
        "dr02_failures": history(engine._dr02_failures),
        "prev_batch_max_time": [dict(username=k[0], asset_id=k[1], time=v.isoformat())
                                for k, v in engine._prev_batch_max_time.items()],
        "alert_id_counter": engine._alert_id_counter,
    }


def load_state(payload: dict) -> DetectionEngine:
    """Restaura instância por transação."""
    if payload.get("version") != 1:
        raise ValueError("Versão de estado de detecção inválida.")
    engine = DetectionEngine()
    for field in ("dr01_sequence", "dr02_failures"):
        setattr(engine, "_" + field, {
            (item["username"], item["asset_id"]): [Log.from_dict(log) for log in item["logs"]]
            for item in payload[field]
        })
    engine._dr01_alerted = {(item["username"], item["asset_id"]): item["alerted"]
                            for item in payload["dr01_alerted"]}
    engine._prev_batch_max_time = {
        (item["username"], item["asset_id"]): datetime.fromisoformat(item["time"])
        for item in payload["prev_batch_max_time"]
    }
    engine._alert_id_counter = payload["alert_id_counter"]
    return engine
