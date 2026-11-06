"""Generate safe synthetic inputs/config outside Git. Never imports real data."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from polar.models import Dataset

parser = argparse.ArgumentParser()
parser.add_argument("output",type=Path)
args = parser.parse_args()
generator = Path(__file__).resolve().parents[1]/"tests/fixtures/generate.py"
if hashlib.sha256(generator.read_bytes()).hexdigest() != "2f08c2e15568d8c37a9f7d18d128bdd95f8ab5816e84190dadd3842ef4e2c460":
    raise SystemExit("Synthetic generator hash mismatch")
import subprocess,sys
subprocess.run([sys.executable,str(generator),str(args.output)],check=True)
raw = (args.output/"fixture.json").read_bytes()
if hashlib.sha256(raw).hexdigest() != "a6dd88480836e262c565f1ba4dfd5a056e7bbfd1688787dd2a343a82bf0bba14":
    raise SystemExit("Frozen fixture hash mismatch")
data = Dataset.model_validate_json(raw)
config = {"dataset_id":data.dataset_id,"strategy_version":"accounting-tape-v1",
          "protocol_version":"fixture-protocol-v2:3c124b8371cd4852e1cd98a78fa1d673fc87965e78d71ccfeafbf1f9f0ed1e53",
          "initial_cash":"1000","orders":[{"decision_session_id":"2024-01-02","quantity":"4"},
                                                 {"decision_session_id":"2024-01-04","quantity":"-2"}],
          "scope_ref":"POL.0.4.0.1","qitem_ref":"qitem-20261106111851-80c852ada6e7b9eb",
          "actor":"fixture-operator","seed":0}
with (args.output/"config.json").open("x") as f:
    json.dump(config,f,sort_keys=True,indent=2)
    f.write("\n")
print(json.dumps({"dataset_id":data.dataset_id,"source_sha256":hashlib.sha256(raw).hexdigest()}))
