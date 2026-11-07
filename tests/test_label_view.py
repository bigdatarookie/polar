"""Author literals recorded before implementation; no peer oracle imported.

At Jan10 14:30Z, end is equal to fit: release Jan10 beats Jan9 even though
both precede that same end. A Jan10 14:31 release is still immature. Target
is future at the original Jan2 decision; that does not exclude it at later fit.
"""
import builtins
import hashlib
import json
import socket

import pytest

from polar.label_view import LabelViewError, label_maturity_view

FIT = "2024-01-10T14:30:00Z"


def row(revision="z", release="2024-01-09T00:00:00Z", **changes):
    result = {"instrument_id": "A", "label_id": "L", "definition_version": "v1",
              "decision_at": "2024-01-02T21:00:00Z",
              "target_start_at": "2024-01-03T14:30:00Z", "target_end_at": FIT,
              "source_revision": revision, "published_at": release,
              "available_at": release, "ingested_at": release,
              "value_unit": "fraction", "value": "0"}
    result.update(changes)
    return result


def envelope(records):
    return {"schema_version": "polar.synthetic-label-input/1", "synthetic": True,
            "timing_model": "synthetic_replay", "labels": records}


def encode(records):
    return json.dumps(envelope(records)).encode()


def view(records, cutoff=FIT, limit=1000):
    return label_maturity_view(encode(records), cutoff, limit=limit)


def test_future_at_decision_mature_at_fit_and_release_rank_excludes_end():
    records = [row(), row("a", "2024-01-10T00:00:00Z", value="2.50"),
               row("late", "2024-01-10T14:31:00Z", value="3")]
    result = view(records)
    assert [r["source_revision"] for r in result["selected"]] == ["a"]
    assert result["selected"][0]["value"] == "2.50"
    assert [(d["source_revision"], d["reason"]) for d in result["diagnostics"]] == [
        ("a", "SELECTED"), ("late", "NOT_MATURE"), ("z", "SUPERSEDED")]
    assert result["diagnostics"][1]["record"]["value"] == "3"
    assert view(records, "2024-01-10T14:29:59Z")["status"] == "NO_MATURE_LABELS"
    assert view(records, "2024-01-10T14:31:00Z")["selected"][0]["source_revision"] == "late"
    assert (result["label_value_qualification"], result["training_eligibility"],
            result["financial_verdict"]) == ("UNVERIFIED", "NOT_ASSESSED", "NOT_RUN")


@pytest.mark.parametrize("field", ["target_end_at", "published_at", "available_at", "ingested_at"])
def test_every_required_clock_and_equality(field):
    changes = {field: "2024-01-10T14:30:01Z"}
    if field == "published_at":
        changes.update(available_at=changes[field], ingested_at=changes[field])
    if field == "available_at":
        changes.update(ingested_at=changes[field])
    assert view([row(**changes)])["selected"] == []
    assert view([row(**changes)], "2024-01-10T14:30:01Z")["status"] == "SELECTED"


def test_six_field_grouping_and_literal_output_order():
    records = [row(instrument_id="B", value="7"), row(label_id="Z", value="6"),
               row(definition_version="v2", value="5"),
               row(target_start_at="2024-01-04T14:30:00Z",
                   target_end_at="2024-01-11T14:30:00Z", value="4"),
               row(target_start_at="2024-01-04T14:30:00Z", value="3"),
               row(value="-1"), row("a", "2024-01-10T00:00:00Z", value="2"),
               row(decision_at="2024-01-01T21:00:00Z", value="1")]
    result = view(records, "2024-01-12T00:00:00Z")
    assert [r["value"] for r in result["selected"]] == ["1", "2", "3", "4", "5", "6", "7"]
    assert [d["record"]["value"] for d in result["diagnostics"]] == ["1", "2", "-1", "3", "4", "5", "6", "7"]


def test_units_are_metadata_not_conversion_or_key():
    result = view([row(), row("a", "2024-01-10T00:00:00Z", value="2.50", value_unit="percent")])
    assert len(result["selected"]) == 1
    assert (result["selected"][0]["value"], result["selected"][0]["value_unit"]) == ("2.50", "percent")
    with pytest.raises(LabelViewError, match="^AMBIGUOUS_REVISION$"):
        view([row(), row("other", value_unit="percent")])


def test_duplicates_winning_and_lower_ties_no_partial_success():
    for records, code in [([row(), row()], "DUPLICATE_REVISION"),
                           ([row(), row("z", "2024-01-11T00:00:00Z")], "DUPLICATE_REVISION"),
                           ([row(), row("other")], "AMBIGUOUS_REVISION")]:
        with pytest.raises(LabelViewError, match=f"^{code}$"):
            view([row(instrument_id="0-other"), *records])
    assert view([row(), row("other"), row("a", "2024-01-10T00:00:00Z")])["selected"][0]["source_revision"] == "a"
    assert view([row("x", "2024-01-11T00:00:00Z"), row("y", "2024-01-11T00:00:00Z")])["status"] == "NO_MATURE_LABELS"


def test_empty_no_mature_zero_and_request_identity():
    assert view([])["status"] == "NO_DATA"
    assert view([row()], "2024-01-09T00:00:00Z")["status"] == "NO_MATURE_LABELS"
    result = view([row()], limit=1)
    assert result["status"] == "SELECTED" and result["selected"][0]["value"] == "0"
    def digest(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    expected_input = digest(envelope([row()]))
    assert result["canonical_input_hash"] == expected_input
    assert result["request_hash"] == digest({"canonical_input_hash": expected_input,
                                             "fit_cutoff": FIT, "limit": 1})
    assert view([row()], limit=2)["request_hash"] != result["request_hash"]
    assert view([row()], "2024-01-11T00:00:00Z", limit=1)["request_hash"] != result["request_hash"]


def test_permutation_format_and_no_operation_io(monkeypatch):
    raw = encode([row(), row("a", "2024-01-10T00:00:00Z"), row(instrument_id="B")])
    before = bytes(raw)
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected I/O")
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    left = label_maturity_view(raw, FIT, limit=3)
    assert left == label_maturity_view(raw, FIT, limit=3) and raw == before
    assert left["source_sha256"] == hashlib.sha256(raw).hexdigest()
    changed = json.loads(raw)
    changed["labels"].reverse()
    right = label_maturity_view(json.dumps(changed,indent=2).encode(),"2024-01-10T14:30:00+00:00",limit=3)
    assert left.pop("source_sha256") != right.pop("source_sha256")
    assert left == right


@pytest.mark.parametrize("field", ["instrument_id", "label_id", "definition_version",
                                  "source_revision", "value_unit"])
@pytest.mark.parametrize("value", ["", "x" * 65])
def test_id_and_unit_bounds(field, value):
    with pytest.raises(LabelViewError, match="^INVALID_LABEL_INPUT$"):
        view([row(**{field: value})])


@pytest.mark.parametrize("changes", [
    {"value": None}, {"value": 0}, {"value": "NaN"}, {"value": "Infinity"},
    {"value": "1e13"}, {"value": "0.0000000000001"},
    {"decision_at": "2024-01-04T00:00:00Z"}, {"target_end_at": "2024-01-03T14:30:00Z"},
    {"published_at": "2024-01-10T00:00:00Z"}, {"available_at": "2024-01-10T00:00:00Z"},
    {"target_end_at": "2024-01-10T14:30:00"},
    {"target_start_at": "2024-01-03T14:30:00+01:00"}, {"decision_at": 1700000000},
    {"target_end_at": "2024-01-10T14:30:00.0000001Z"},
    {"secret": "do-not-echo"},
])
def test_invalid_records_code_only(changes):
    with pytest.raises(LabelViewError) as error:
        view([row(**changes)])
    assert str(error.value) == error.value.code == "INVALID_LABEL_INPUT"


@pytest.mark.parametrize("cutoff", [None, 1700000000, "secret", "2024-01-10",
                                   "2024-01-10T14:30:00", "2024-01-10T14:30:00+01:00",
                                   "2024-01-10T14:30:00.0000001Z"])
def test_invalid_cutoff(cutoff):
    with pytest.raises(LabelViewError, match="^INVALID_FIT_CUTOFF$"):
        view([], cutoff)


@pytest.mark.parametrize("limit", [0, -1, 1001, True, None, 1.0, "1"])
def test_limit_is_explicit_bounded_integer(limit):
    with pytest.raises(LabelViewError, match="^INVALID_LIMIT$"):
        view([], limit=limit)


def test_envelope_and_count_limits_no_truncation():
    for changes in [{"synthetic": False}, {"synthetic": 1}, {"schema_version": "secret"},
                    {"timing_model": "historical"}, {"secret": "do-not-echo"}]:
        data = envelope([])
        data.update(changes)
        with pytest.raises(LabelViewError, match="^INVALID_LABEL_INPUT$"):
            label_maturity_view(json.dumps(data).encode(), FIT, limit=1000)
    with pytest.raises(TypeError):
        label_maturity_view(encode([]), FIT)
    with pytest.raises(LabelViewError, match="^RECORD_LIMIT_EXCEEDED$"):
        view([row(instrument_id="A"), row(instrument_id="B")], limit=1)
    rows = [row(instrument_id=str(i)) for i in range(1000)]
    assert len(view(rows)["selected"]) == 1000
    with pytest.raises(LabelViewError, match="^INVALID_LABEL_INPUT$"):
        view([*rows, row(instrument_id="extra")])
    for raw, code in [(b"", "INVALID_LABEL_INPUT"), (b"{secret", "INVALID_LABEL_INPUT"),
                      (b"x" * (1024**2 + 1), "INPUT_TOO_LARGE"), ("{}", "INVALID_INPUT_TYPE")]:
        with pytest.raises(LabelViewError, match=f"^{code}$"):
            label_maturity_view(raw, FIT, limit=1)
    raw = encode([row()])
    assert label_maturity_view(raw + b" " * (1024**2 - len(raw)), FIT, limit=1)["status"] == "SELECTED"


def test_microsecond_endpoint_does_not_round_into_maturity():
    supplied = row(target_end_at="2024-01-10T14:30:00.000001Z")
    assert view([supplied])["status"] == "NO_MATURE_LABELS"
    assert view([supplied], "2024-01-10T14:30:00.000001+00:00")["status"] == "SELECTED"
