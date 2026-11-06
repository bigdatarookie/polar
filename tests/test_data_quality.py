"""Author checks; independent QA/Validator acceptance is separate."""
import hashlib
import json
import os
import subprocess
import sys

import pytest

from polar.cli import main
from polar.data_quality import MAX_INPUT_BYTES, InspectionError, inspect_dataset


def encode(value):
    return json.dumps(value).encode()


def test_frozen_fixture_identity_and_counts(raw_fixture, data):
    before = bytes(raw_fixture)
    report = inspect_dataset(raw_fixture)
    assert report == inspect_dataset(raw_fixture)
    assert raw_fixture == before
    assert report["source_sha256"] == "a6dd88480836e262c565f1ba4dfd5a056e7bbfd1688787dd2a343a82bf0bba14"
    assert report["dataset_id"] == data.dataset_id
    assert report["content_hash"] == data.dataset_id[3:]
    assert report["counts"]["expected_sessions"] == 6
    assert report["counts"]["observed_bars"] == 5
    assert report["counts"]["settlement_only_bars"] == 1
    assert report["counts"]["missing_price_sessions"] == 0
    assert report["investment_evaluation"] == "NOT_RUN"
    reformatted = encode(json.loads(raw_fixture))
    other = inspect_dataset(reformatted)
    assert other["dataset_id"] == report["dataset_id"]
    assert other["source_sha256"] != report["source_sha256"]
    changed = json.loads(raw_fixture)
    changed["dataset_name"] = "changed"
    assert inspect_dataset(encode(changed))["dataset_id"] != report["dataset_id"]


def test_absent_and_declared_missing(raw_fixture):
    value = json.loads(raw_fixture)
    value["bars"].pop(0)
    value["bars"][0].update(price_status="MISSING", tradable=False,
                             open=None, high=None, low=None, close=None)
    report = inspect_dataset(encode(value))
    counts = report["counts"]
    assert (counts["expected_sessions"], counts["present_bars"],
            counts["observed_bars"], counts["settlement_only_bars"],
            counts["missing_price_sessions"]) == (6, 5, 3, 1, 2)


def test_empty_tape(raw_fixture):
    value = json.loads(raw_fixture)
    value.update(sessions=[], bars=[], actions=[], features=[])
    report = inspect_dataset(encode(value))
    assert report["status"] == "NO_DATA"
    assert report["observed_fraction"] is None
    assert report["missing_fraction"] is None
    assert all(v == 0 for k, v in report["counts"].items() if k != "actions_by_kind")
    assert set(report["counts"]["actions_by_kind"].values()) == {0}


def test_declared_sessions_without_bars(raw_fixture):
    value = json.loads(raw_fixture)
    value["bars"] = []
    report = inspect_dataset(encode(value))
    assert report["status"] == "NO_DATA"
    assert report["counts"]["expected_sessions"] == 6
    assert report["counts"]["missing_price_sessions"] == 6
    assert report["counts"]["present_bars"] == 0
    assert report["counts"]["observed_bars"] == 0
    assert report["counts"]["settlement_only_bars"] == 0
    assert report["observed_fraction"] == "0"
    assert report["missing_fraction"] == "1"


@pytest.mark.parametrize("raw,code", [
    (b'{"password":"sensitive"', "INVALID_DATASET"),
    (b"{}", "INVALID_DATASET"),
    (b"x" * (MAX_INPUT_BYTES + 1), "INPUT_TOO_LARGE"),
])
def test_sanitized_errors(raw, code):
    with pytest.raises(InspectionError) as exc:
        inspect_dataset(raw)
    assert str(exc.value) == code


def test_unsupported_schema(raw_fixture):
    value = json.loads(raw_fixture)
    value["schema_version"] = "unsupported-secret"
    with pytest.raises(InspectionError, match="^INVALID_DATASET$"):
        inspect_dataset(encode(value))


def test_cli_offline_import_boundary_and_unchanged_source(tmp_path, raw_fixture):
    source = tmp_path / "fixture.json"
    source.write_bytes(raw_fixture)
    script = '''
import sys
class BlockServices:
    def find_spec(self, fullname, *args):
        if fullname in {"polar.config", "polar.service", "psycopg"}:
            raise AssertionError("offline CLI imported " + fullname)
sys.meta_path.insert(0, BlockServices())
from polar.cli import main
main(["inspect-dataset", sys.argv[1]])
'''
    env = {k: v for k, v in os.environ.items() if not k.startswith("POLAR_")}
    result = subprocess.run([sys.executable, "-c", script, str(source)],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == inspect_dataset(raw_fixture)
    assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(raw_fixture).digest()
    assert list(tmp_path.iterdir()) == [source]


def test_cli_invalid_and_unreadable(tmp_path, capsys):
    source = tmp_path / "secret-name"
    for payload, code in [(b"secret-password", "INVALID_DATASET"),
                          (b"x" * (MAX_INPUT_BYTES + 1), "INPUT_TOO_LARGE")]:
        source.write_bytes(payload)
        with pytest.raises(SystemExit) as exc:
            main(["inspect-dataset", str(source)])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert json.loads(captured.err) == {"status": "ERROR", "code": code}
    source.unlink()
    with pytest.raises(SystemExit):
        main(["inspect-dataset", str(source)])
    assert json.loads(capsys.readouterr().err)["code"] == "INPUT_READ_ERROR"
