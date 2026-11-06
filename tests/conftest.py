import json
import subprocess
import sys
from pathlib import Path

import pytest

from polar.models import Dataset,RunConfig

PROTOCOL = "fixture-protocol-v2:3c124b8371cd4852e1cd98a78fa1d673fc87965e78d71ccfeafbf1f9f0ed1e53"


@pytest.fixture(scope="session")
def raw_fixture(tmp_path_factory):
    target = tmp_path_factory.mktemp("synthetic-source")
    subprocess.run([sys.executable,str(Path(__file__).parent/"fixtures/generate.py"),str(target)],check=True,capture_output=True)
    return (target/"fixture.json").read_bytes()


@pytest.fixture
def data(raw_fixture):
    return Dataset.model_validate_json(raw_fixture)


@pytest.fixture
def config(data):
    return RunConfig.model_validate({"dataset_id":data.dataset_id,"protocol_version":PROTOCOL,
        "orders":[{"decision_session_id":"2024-01-02","quantity":"4"},
                  {"decision_session_id":"2024-01-04","quantity":"-2"}],
        "actor":"author-test","scope_ref":"POL.0.4.0.1","qitem_ref":"qitem-20261106111851-80c852ada6e7b9eb"})
