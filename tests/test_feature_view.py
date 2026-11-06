"""Author literal cases; independent review owns acceptance.

Before comparison: observation A/f at Jan1 has revision z at 10:00 and a
at 11:00. At 11:00 the unique winner is a, independent of spelling. Jan2's
observation and instrument B are separate. A future revision of Jan1 at 12:00
is unavailable, not superseded. Tied winning clocks reject the whole request.
"""
import hashlib
import json
import os
import subprocess
import sys

import pytest

from polar.cli import main
from polar.feature_view import FeatureViewError, MAX_INPUT_BYTES, asof_features

CUTOFF = "2024-01-02T11:00:00Z"


def row(revision="z", clock="10:00:00", **changes):
    result = {
        "instrument_id": "A", "feature_id": "f", "value": "0",
        "event_time": "2024-01-01T21:00:00Z",
        "effective_time": "2024-01-01T21:00:00Z",
        "published_at": f"2024-01-02T{clock}Z",
        "available_at": f"2024-01-02T{clock}Z",
        "ingested_at": f"2024-01-02T{clock}Z",
        "source_revision": revision,
    }
    result.update(changes)
    return result


def envelope(records):
    return {"schema_version": "polar.synthetic-feature-view-input/1",
            "synthetic": True, "timing_model": "synthetic_replay", "features": records}


def encode(records):
    return json.dumps(envelope(records)).encode()


def test_literal_grouping_clocks_and_audit():
    rows = [row(), row("a", "11:00:00", value="2.50"),
            row("future", "12:00:00"), row(instrument_id="B"),
            row(event_time="2024-01-02T10:30:00Z"),
            row(effective_time="2024-01-02T10:30:00Z")]
    raw = encode(rows)
    before = bytes(raw)
    result = asof_features(raw, CUTOFF)
    assert raw == before
    assert result == asof_features(raw, CUTOFF)
    assert len(result["selected"]) == 4
    assert [r["source_revision"] for r in result["selected"]] == ["a", "z", "z", "z"]
    assert result["selected"][0]["value"] == "2.50"
    assert result["selected"][-1]["instrument_id"] == "B"
    audit = result["diagnostics"]
    assert [d["reason"] for d in audit[:3]] == [
        "SELECTED", "NOT_AVAILABLE_AT_DECISION", "SUPERSEDED"]
    assert len(audit) == len(rows)
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["decision_at"] == CUTOFF
    assert result["source_qualification"] == "SYNTHETIC_ONLY"
    assert result["investment_evaluation"] == "NOT_RUN"


def test_permutations_and_normalized_cutoff():
    rows = [row(), row("a", "11:00:00"), row(instrument_id="B")]
    left = asof_features(encode(rows), CUTOFF)
    right = asof_features(encode(list(reversed(rows))), "2024-01-02T11:00:00+00:00")
    assert left.pop("source_sha256") != right.pop("source_sha256")
    assert left == right


@pytest.mark.parametrize("field", ["event_time", "effective_time", "published_at",
                                  "available_at", "ingested_at"])
def test_each_future_clock_excludes(field):
    changes = {field: "2024-01-02T11:00:01Z"}
    # Publication <= availability <= ingestion is still authoritative.
    if field == "published_at":
        changes.update(available_at=changes[field], ingested_at=changes[field])
    if field == "available_at":
        changes.update(ingested_at=changes[field])
    result = asof_features(encode([row(**changes)]), CUTOFF)
    assert result["selected"] == []
    assert result["status"] == "NO_ELIGIBLE_FEATURES"
    assert result["diagnostics"][0]["reason"] == "NOT_AVAILABLE_AT_DECISION"


def test_all_clocks_equal_and_empty_vs_zero():
    changes = {key: CUTOFF for key in ["event_time", "effective_time", "published_at",
                                      "available_at", "ingested_at"]}
    result = asof_features(encode([row(**changes)]), CUTOFF)
    assert result["status"] == "SELECTED"
    assert result["selected"][0]["value"] == "0"
    empty = asof_features(encode([]), CUTOFF)
    assert (empty["status"], empty["selected"], empty["diagnostics"]) == ("NO_DATA", [], [])


def test_duplicate_and_winning_tie_have_no_partial_result():
    for rows, code in [([row(), row()], "DUPLICATE_REVISION"),
                       ([row(), row("other")], "AMBIGUOUS_REVISION"),
                       ([row(), row("z", "12:00:00")], "DUPLICATE_REVISION")]:
        with pytest.raises(FeatureViewError, match=f"^{code}$"):
            asof_features(encode([row(instrument_id="0-unrelated"), *rows]), CUTOFF)
    # A tie below the unique eligible maximum does not make its winner ambiguous.
    result = asof_features(encode([row(), row("other"), row("a", "11:00:00")]), CUTOFF)
    assert result["selected"][0]["source_revision"] == "a"


@pytest.mark.parametrize("decision", ["2024-01-02", "secret", "2024-01-02T11:00:00",
                                      "2024-01-02T11:00:00+01:00", "x" * 65])
def test_invalid_cutoff(decision):
    with pytest.raises(FeatureViewError, match="^INVALID_DECISION_AT$"):
        asof_features(encode([]), decision)


@pytest.mark.parametrize("changes", [
    {"instrument_id": ""}, {"instrument_id": "x" * 65},
    {"feature_id": ""}, {"feature_id": "x" * 65},
    {"source_revision": ""}, {"source_revision": "x" * 65},
    {"value": 1}, {"value": "NaN"}, {"value": "1e13"}, {"value": "0.0000000000001"},
    {"event_time": "2024-01-01T21:00:00"},
    {"event_time": "2024-01-01T21:00:00+01:00"},
    {"published_at": "2024-01-02T12:00:00Z"}, {"secret": "do-not-echo"},
])
def test_record_bounds(changes):
    with pytest.raises(FeatureViewError, match="^INVALID_FEATURE_INPUT$"):
        asof_features(encode([row(**changes)]), CUTOFF)


def test_envelope_bounds_and_payload_errors():
    for changes in [{"synthetic": False}, {"synthetic": 1}, {"timing_model": "historical"},
                    {"schema_version": "unsupported"}, {"secret": "hidden"}]:
        value = envelope([])
        value.update(changes)
        with pytest.raises(FeatureViewError, match="^INVALID_FEATURE_INPUT$"):
            asof_features(json.dumps(value).encode(), CUTOFF)
    with pytest.raises(FeatureViewError, match="^INVALID_FEATURE_INPUT$"):
        asof_features(encode([row(feature_id=str(i)) for i in range(1001)]), CUTOFF)
    with pytest.raises(FeatureViewError, match="^INPUT_TOO_LARGE$"):
        asof_features(b" " * (MAX_INPUT_BYTES + 1), CUTOFF)
    with pytest.raises(FeatureViewError, match="^INVALID_FEATURE_INPUT$"):
        asof_features(b"{secret", CUTOFF)
    with pytest.raises(FeatureViewError, match="^INVALID_INPUT_TYPE$"):
        asof_features("{}", CUTOFF)
    assert len(asof_features(encode([row(feature_id=str(i)) for i in range(1000)]),
                             CUTOFF)["selected"]) == 1000


def test_cli_offline_and_sanitized(tmp_path, capsys):
    path = tmp_path / "source.json"
    raw = encode([row()])
    path.write_bytes(raw)
    script = '''
import sys
class BlockServices:
    def find_spec(self, fullname, *args):
        if fullname in {"polar.config", "polar.service", "psycopg", "socket"}:
            raise AssertionError("offline path imported a service/network module")
sys.meta_path.insert(0, BlockServices())
from polar.cli import main
main(["asof-features",sys.argv[1],"--decision-at",sys.argv[2]])
'''
    env = dict(os.environ, POLAR_DATABASE_URL="invalid-secret-dsn", POLAR_ENV="invalid")
    outcome = subprocess.run([sys.executable, "-c", script, str(path), CUTOFF],
                             env=env,capture_output=True,text=True)
    assert outcome.returncode == 0, outcome.stderr
    assert json.loads(outcome.stdout) == asof_features(raw, CUTOFF)
    assert path.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [path]
    for payload, decision, code in [(b"secret-body", CUTOFF, "INVALID_FEATURE_INPUT"),
                                    (raw, "secret-cutoff", "INVALID_DECISION_AT"),
                                    (b"x" * (MAX_INPUT_BYTES + 1), CUTOFF, "INPUT_TOO_LARGE")]:
        path.write_bytes(payload)
        with pytest.raises(SystemExit) as error:
            main(["asof-features",str(path),"--decision-at",decision])
        assert error.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert json.loads(captured.err) == {"status": "ERROR", "code": code}
    path.unlink()
    with pytest.raises(SystemExit):
        main(["asof-features",str(path),"--decision-at",CUTOFF])
    assert json.loads(capsys.readouterr().err)["code"] == "INPUT_READ_ERROR"
