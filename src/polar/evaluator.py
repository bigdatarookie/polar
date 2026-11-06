"""Bounded technical integrity evaluator. Does not issue a financial verdict."""
import json
from pathlib import Path

from .artifacts import verify
from .codec import canonical


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,default=Path("/input"))
    parser.add_argument("--output",type=Path,default=Path("/output/evaluation.json"))
    args = parser.parse_args()
    manifest = verify(args.input)
    # Exclusive creation preserves rejected and earlier evaluations.
    with args.output.open("xb") as f:
        f.write(canonical({"schema_version":"polar.integrity-evaluation/1", "manifest":manifest,
                           "artifact_integrity":"PASS","financial_verdict":"NOT_RUN",
                           "blinding":"BLINDING_NOT_ENFORCED","holdout_unlocks":0}))


if __name__ == "__main__":
    main()
