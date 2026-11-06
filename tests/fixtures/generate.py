"""Offline, deterministic synthetic inputs; no financial simulation or network."""
import argparse
import hashlib
import json
from pathlib import Path


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def clock(day, time):
    return f"2024-01-{day}T{time}Z"


def provenance(day, time, revision="r1"):
    return dict(event_time=clock(day, time + ":00"),
                effective_time=clock(day, time + ":00"),
                published_at=clock(day, time + ":01"),
                available_at=clock(day, time + ":01"),
                ingested_at=clock(day, time + ":02"), source_revision=revision)


def inputs():
    days = ["02", "03", "04", "05", "08", "09"]
    prices = [("100", "100"), ("100", "110"), ("55", "54"),
              ("54", "53"), ("52", "52"), (None, None)]
    sessions = [dict(session_id="2024-01-" + day,
                     open_at=clock(day, "14:30:00"), close_at=clock(day, "21:00:00"))
                for day in days]
    bars = []
    for day, (opening, closing) in zip(days, prices):
        numeric = [int(opening), int(closing)] if opening else None
        bars.append(dict(instrument_id="SYNTH-001", session_id="2024-01-" + day,
                         open=opening, close=closing,
                         high=str(max(numeric)) if numeric else None,
                         low=str(min(numeric)) if numeric else None,
                         tradable=bool(opening), price_status="OBSERVED" if opening else "SETTLEMENT_ONLY",
                         open_provenance=provenance(day, "14:30"),
                         **provenance(day, "21:00")))
    actions = [
        dict(action_id="split-01", kind="split", instrument_id="SYNTH-001",
             ratio_numerator="2", ratio_denominator="1", **provenance("04", "14:30")),
        dict(action_id="dividend-01", kind="dividend", instrument_id="SYNTH-001",
             cash_per_share="1", currency="USD", entitlement_at=clock("04", "21:00:00"),
             ex_at=clock("05", "14:30:00"), pay_at=clock("05", "14:30:00"),
             **provenance("05", "14:30")),
        dict(action_id="delisting-01", kind="delisting_cash_settlement", instrument_id="SYNTH-001",
             cash_per_share="50", currency="USD", **provenance("09", "14:30")),
    ]
    # Actions are announced the preceding session: execute at effective time, not announcement.
    for action, prior in zip(actions, ["03", "04", "08"]):
        action.update(published_at=clock(prior, "21:01:00"),
                      available_at=clock(prior, "21:01:00"), ingested_at=clock(prior, "21:01:01"))
    features = [dict(feature_id="marker", instrument_id="SYNTH-001", value="1",
                     **provenance("02", "21:00"))]
    revision = dict(features[0], value="9", source_revision="r2",
                    published_at=clock("05", "21:01:00"), available_at=clock("05", "21:01:00"),
                    ingested_at=clock("05", "21:01:01"))
    features.append(revision)
    fixture = dict(schema_version="polar.synthetic-data/1", dataset_name="polar-six-session-v1",
                   seed="literal-tape-v1-no-rng", synthetic=True,
                   timing_model="synthetic_replay", price_basis="raw_unadjusted",
                   market_profile=dict(currency="USD", price_unit="USD/share", timezone="America/New_York",
                                       calendar="EXPLICIT_SIX_SESSIONS_V1", frequency="daily"),
                   instruments=[dict(instrument_id="SYNTH-001", synthetic=True, currency="USD",
                                     ticker_history=[dict(ticker="SYN", effective_from=clock("02", "14:30:00"),
                                                          effective_until=clock("09", "14:30:00"),
                                                          **provenance("02", "14:30"))])],
                   sessions=sessions, bars=bars, actions=actions, features=features)
    cases = [
        dict(case_id="missing-mark", patch=[dict(op="replace", path="/bars/2/close", value=None)],
             expected_status="INVALID", diagnostic="MISSING_REQUIRED_MARK"),
        dict(case_id="missing-settlement", patch=[dict(op="remove", path="/actions/2/cash_per_share")],
             expected_status="INVALID", diagnostic="MISSING_DELISTING_SETTLEMENT"),
        dict(case_id="future-feature", selection="features/1", decision_at=clock("03", "21:02:00"),
             expected_status="EXCLUDED", diagnostic="FEATURE_NOT_YET_AVAILABLE"),
        dict(case_id="late-ingestion", selection="features/0", decision_at=clock("03", "21:02:00"),
             patch=[dict(op="replace", path="/features/0/ingested_at", value=clock("05", "21:01:01"))],
             expected_status="EXCLUDED", diagnostic="FEATURE_NOT_YET_INGESTED"),
        dict(case_id="future-bar", selection="bars/2", decision_at=clock("03", "21:02:00"),
             expected_status="EXCLUDED", diagnostic="BAR_EVENT_AFTER_DECISION"),
        dict(case_id="future-publication", selection="features/0", decision_at=clock("03", "21:02:00"),
             patch=[dict(op="replace", path="/features/0/published_at", value=clock("05", "21:01:00"))],
             expected_status="EXCLUDED", diagnostic="FEATURE_NOT_YET_PUBLISHED"),
        dict(case_id="empty-bars", patch=[dict(op="replace", path="/bars", value=[])],
             expected_status="INVALID", diagnostic="NO_DATA"),
    ]
    stamp = dict(type="string", format="date-time", pattern="Z$")
    decimal = dict(type="string", pattern=r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
    timing = {key: stamp for key in ["event_time", "effective_time", "published_at", "available_at", "ingested_at"]}
    timing["source_revision"] = dict(type="string", minLength=1)
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
              "required": list(fixture), "properties": {
                  "schema_version": {"const": "polar.synthetic-data/1"}, "synthetic": {"const": True},
                  "timing_model": {"const": "synthetic_replay"}, "price_basis": {"const": "raw_unadjusted"},
                  "dataset_name": {"type": "string"}, "seed": {"type": "string"},
                  "market_profile": {"type": "object", "required": ["currency", "price_unit", "timezone", "calendar", "frequency"]},
                  "instruments": {"type": "array", "minItems": 1, "maxItems": 3,
                                  "items": {"type": "object", "required": ["instrument_id", "synthetic", "currency", "ticker_history"]}},
                  "sessions": {"type": "array", "minItems": 1, "maxItems": 20,
                               "items": {"type": "object", "required": ["session_id", "open_at", "close_at"],
                                         "properties": {"session_id": {"type": "string"}, "open_at": stamp, "close_at": stamp}}},
                  "bars": {"type": "array", "minItems": 1, "items": {
                      "type": "object", "required": list(bars[0]),
                      "properties": {**timing, **{key: {"anyOf": [decimal, {"type": "null"}]} for key in ["open", "high", "low", "close"]},
                                     "tradable": {"type": "boolean"}, "price_status": {"enum": ["OBSERVED", "SETTLEMENT_ONLY"]},
                                     "instrument_id": {"type": "string"}, "session_id": {"type": "string"},
                                     "open_provenance": {"type": "object", "required": list(timing), "properties": timing}}}},
                  "actions": {"type": "array", "items": {"type": "object", "required": ["action_id", "kind", "instrument_id", *timing],
                               "properties": {**timing, "kind": {"enum": ["split", "dividend", "delisting_cash_settlement"]},
                                              "cash_per_share": decimal, "ratio_numerator": decimal, "ratio_denominator": decimal}}},
                  "features": {"type": "array", "items": {"type": "object", "required": ["feature_id", "instrument_id", "value", *timing],
                                "properties": {**timing, "value": decimal}}},
              }, "additionalProperties": False}
    return {"fixture.json": fixture, "schema.json": schema, "negative-cases.json": cases}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, value in inputs().items():
        payload = encoded(value)
        (args.output / name).write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    hashes["generate.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.output / "inputs.sha256").write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())))
    print(json.dumps(hashes, sort_keys=True))


if __name__ == "__main__":
    main()
