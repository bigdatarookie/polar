"""Captured-source adapter. Structural preparation never computes feature/target values."""
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .history_bundle import read_file, safe_root, relative
from .hyp007_contract import (RAW, ACTIONS, EVIDENCE, PROTOCOL, COHORT, MAX_FILE, check, exact, hexhash,
                              decode, sha, canonical, definitions, stamp)
from .hyp007_clocks import Clock

CONFIG_FIELDS = {"schema", "source_root", "raw_manifest", "action_manifest", "calendar",
                 "tzdata", "qualification_objects"}


def number(token, positive=False):
    check(type(token) is str and len(token) <= 128, "HYP007_SOURCE_NUMBER")
    try:
        value = Decimal(token)
    except InvalidOperation:
        check(False, "HYP007_SOURCE_NUMBER")
    check(value.is_finite() and value >= 0 and (not positive or value > 0), "HYP007_SOURCE_NUMBER")
    return value


def config(value):
    exact(value, CONFIG_FIELDS, "polar.hyp007-config/1")
    check(type(value["source_root"]) is str and Path(value["source_root"]).is_absolute())
    safe_root(Path(value["source_root"]))
    for k in ("raw_manifest", "action_manifest", "calendar", "tzdata"):
        relative(value[k])
    objects = value["qualification_objects"]
    check(type(objects) is dict and 3 <= len(objects) <= 100, "HYP007_QUALIFICATION_NOT_BOUND")
    for name, digest in objects.items():
        relative(name); hexhash(digest)
    check({PROTOCOL, EVIDENCE,
           "5316e711fe2af122e8b6b65a6a89db4748ff36c3bd4217e0a5ed0f036c5e043c",
           "34d7fea739aa47615f9f172a0a4978ee43e3f991005f3cabc06aff95120993de",
           "e10a38e69933081377889020ad313f71355457b2351a95e908988eb3b6e6a7ad",
           "3a48c1d4b3bbfb8abc2fdf5b340a66baec20bce1691e9f76b5980b2af4a66904",
           "a62533a8538876befe9c99643e1baf07afff39eb32c9408dc8fa668c6b2bb973"} <= set(objects.values()),
          "HYP007_QUALIFICATION_NOT_BOUND")
    return value


class Source:
    def __init__(self, cfg):
        self.config = config(cfg)
        self.root = Path(cfg["source_root"])
        self.inventory = {}
        self.bytes_read = 0
        self.read_passes = 0
        self.raw = self.manifest(cfg["raw_manifest"], RAW)
        self.action_content = self.manifest(cfg["action_manifest"], ACTIONS)
        self.clock = Clock.pinned(self.read(cfg["calendar"]), self.read(cfg["tzdata"]))
        self.qualification = {name: self.read(name, digest) for name, digest in cfg["qualification_objects"].items()}
        maps = [decode(raw) for raw in self.qualification.values() if sha(raw) == EVIDENCE]
        check(len(maps) == 1 and maps[0]["root_protocol_sha256"] == PROTOCOL, "HYP007_EVIDENCE_NOT_BOUND")
        self.evidence = {row["source_id"]: row for row in maps[0]["entries"]}
        required = {item[key] for row in self.evidence.values() for item in row["static_qualification_evidence"]
                    for key in ("artifact_sha256", "report_sha256") if key in item}
        check(required <= set(cfg["qualification_objects"].values()), "HYP007_QUALIFICATION_NOT_BOUND")
        self.bars = {s: {} for s in COHORT}
        self.conflicts = {s: set() for s in COHORT}
        raw_path = str(Path(cfg["raw_manifest"]).parent/"bars.ndjson")
        for ordinal, line in enumerate(self.objects[raw_path].splitlines()):
            row = decode(line)
            symbol, day = row["source_symbol"], row["reference_date"]
            check(symbol in COHORT and date.fromisoformat(day) in self.clock.index, "HYP007_SOURCE_MAPPING")
            check(row["currency"] == "USD_REQUEST_CONTRACT" and row["adjustment"] == "raw" and
                  row["feed"] == "sip", "HYP007_SOURCE_BASIS")
            tokens = row["raw_fields_exact_tokens"]
            for key in ("o", "h", "l", "c"):
                number(tokens[key], True)
            number(tokens["v"])
            check(number(tokens["l"]) <= min(number(tokens["o"]), number(tokens["c"])) <=
                  max(number(tokens["o"]), number(tokens["c"])) <= number(tokens["h"]), "HYP007_SOURCE_DOMAIN")
            old = self.bars[symbol].get(day)
            signature = {k: tokens[k] for k in ("o", "h", "l", "c", "v")}
            if old and old["tokens"] != signature:
                self.conflicts[symbol].add(day)
            elif old:
                old["aliases"].append(ordinal)
            else:
                self.bars[symbol][day] = {"tokens": signature, "pointer": {"file": raw_path, "row": ordinal,
                    "sha256": sha(line), "source_body_sha256": row["source_body_sha256"],
                    "source_row_ordinal": row["source_row_ordinal"]}, "aliases": [ordinal],
                    "K": self.clock.known_by(day)}
        self.actions = {s: {} for s in COHORT}
        action_path = str(Path(cfg["action_manifest"]).parent/"actions.ndjson")
        seen = {}
        for ordinal, line in enumerate(self.objects[action_path].splitlines()):
            row = decode(line)
            fields, roles = row["source_fields_exact_tokens"], row["source_symbol_roles"]
            family = row["source_family"]
            subject = roles.get("acquiree_symbol") if family == "cash_mergers" else roles.get("symbol")
            if subject not in COHORT:  # acquirer-only query relation is retained in the inventory, never a cash credit
                continue
            event = {"id": row["source_id"], "family": family, "subject": subject,
                     "fields": fields, "dates": row["source_date_fields"], "currency": row["source_currency"],
                     "pointer": {"file": action_path, "row": ordinal, "sha256": sha(line)},
                     "roles": roles}
            identity = (subject, event["id"])
            sig = canonical({k: v for k, v in event.items() if k != "pointer"})
            if identity in seen:
                check(seen[identity] == sig, "HYP007_CONFLICTING_ACTION_VERSION")
                continue
            seen[identity] = sig
            day = event["dates"].get("ex_date") or event["dates"].get("effective_date")
            event["reason"] = None
            process = event["dates"].get("process_date")
            if not day or not process:
                event["reason"] = "UNAVAILABLE_K"
                event["K"] = None
            else:
                base = max(day, process, "2022-10-28" if subject == "TWTR" and family == "cash_mergers" else day)
                event["K"] = self.clock.known_by(base)
                if event["K"] is None:
                    event["reason"] = "UNAVAILABLE_K"
            if event["currency"] not in (None, "USD") or family not in ("cash_dividends", "forward_splits", "cash_mergers"):
                event["reason"] = "UNRESOLVED_EVENT"
            if subject == "TWTR" and family == "cash_mergers":
                day = "2022-10-28"  # modeled recognition, original effective date remains in event.dates
            if not day:
                check(False, "HYP007_EVENT_BOUNDARY_MISSING")
            self.actions[subject].setdefault(day, []).append(event)
        self.roster = self.clock.opportunities()

    def read(self, name, digest=None, limit=MAX_FILE):
        raw = read_file(self.root, name, limit=limit)
        self.bytes_read += len(raw); self.read_passes += 1
        if digest is not None:
            check(sha(raw) == digest, "HYP007_SOURCE_HASH")
        info = {"sha256": sha(raw), "bytes": len(raw)}
        if name in self.inventory:
            check(self.inventory[name] == info, "HYP007_SOURCE_CHANGED")
        self.inventory[name] = info
        return raw

    def manifest(self, name, digest):
        if not hasattr(self, "objects"):
            self.objects = {}
        raw = self.read(name, digest)
        manifest = decode(raw)
        check(type(manifest.get("objects")) is dict)
        for key, item in manifest["objects"].items():
            child = str(Path(name).parent/relative(key))
            value = self.read(child, item["sha256"])
            check(len(value) == item["bytes"], "HYP007_SOURCE_SIZE")
            self.objects[child] = value
        # Physical receipt is separate from content identity and remains an explicitly hashed input.
        receipt = decode(self.read(str(Path(name).parent/"import-receipt.json")))
        check(receipt["revision"] == ("multisiphist-" if digest == RAW else "multiactions-")+digest,
              "HYP007_RECEIPT_IDENTITY")
        capture = Path(name).parent.parent
        self.read(str(capture/"receipts.json"), receipt["actual_capture_receipts_sha256"])
        plan_key = "frozen_physical_plan_sha256" if digest == RAW else "physical_plan_sha256"
        self.read(str(capture/"plan.json"), receipt[plan_key])
        if digest == RAW:
            self.read(str(capture/"capture-summary.json"), receipt["actual_capture_summary_sha256"])
        for source in manifest["source_objects"]:
            ordinal = source["request_ordinal"]
            child = capture/(f"raw/response-{ordinal:02d}.json" if digest == RAW else f"response-{ordinal}.json")
            response = self.read(str(child), source["sha256"])
            check(len(response) == source["bytes"], "HYP007_SOURCE_SIZE")
        return manifest

    def preparation(self):
        structural = {}
        for symbol in COHORT:
            bars = self.bars[symbol]
            structural[symbol] = {"bar_rows": len(bars), "conflicting_dates": sorted(self.conflicts[symbol]),
                "first": min(bars) if bars else None, "last": max(bars) if bars else None,
                "action_rows": sum(map(len, self.actions[symbol].values())),
                "finite_feature_target_masks": "NOT_COMPUTED",
                "observed_historical_clocks": None}
        out = {"schema": "polar.hyp007-prepare/1", "status": "PREPARED_STRUCTURAL_ONLY",
               "config": self.config, "inventory": self.inventory, "roster": self.roster,
               "structural": structural, "definitions": definitions()}
        out["prepare_id"] = sha(canonical(out))
        return out
