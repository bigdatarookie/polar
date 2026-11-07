"""Frozen same-revision retrospective tables. No jobs, model, financial verdict or IO writes."""
from decimal import Decimal, DecimalException, localcontext
from importlib.resources import files as resources

from .history_bundle import BASES, HistoryError, canonical, decode, hex_hash, identifier, label, numeric, require, revision_id, sha
from .history_numeric import DEFINITION_SHA256, context, derived_text, indicators, references
from .history_series import admitted_rows

PROTOCOL_SHA256 = "072ed6d5ec76999943039e69492be6f159880407ea822143d86241549670b168"
CODE_FILES = ("descriptive.py", "descriptive_store.py", "descriptive_service.py", "history_bundle.py",
              "history_numeric.py", "history_calendar.py", "history_series.py", "history_store.py")


def protocol():
    raw = resources("polar").joinpath("descriptive_protocol.json").read_bytes()
    require(sha(raw) == PROTOCOL_SHA256, "DESCRIPTIVE_PROTOCOL_INTEGRITY")
    result = decode(raw)
    require(canonical(result) == raw, "DESCRIPTIVE_PROTOCOL_INTEGRITY")
    return result


def identity(prefix, value):
    return prefix + "-" + sha(canonical(value))


def code_projection():
    return {"schema": "polar.descriptive-code/1", "files":
            {name: sha(resources("polar").joinpath(name).read_bytes()) for name in CODE_FILES}}


def configuration(value):
    required = {"dataset_id", "dataset_revision", "import_receipt_id", "manifest_sha256", "instrument_ids",
                "benchmark_instrument_id", "start", "end"}
    require(type(value) is dict and set(value) == required, "DESCRIPTIVE_INVALID_CONFIG")
    identifier(value["dataset_id"]); revision_id(value["dataset_revision"])
    hex_hash(value["import_receipt_id"]); hex_hash(value["manifest_sha256"])
    identifier(value["benchmark_instrument_id"])
    assets = value["instrument_ids"]
    require(type(assets) is list and 1 <= len(assets) <= 4 and all(type(x) is str for x in assets) and
            len(set(assets)) == len(assets), "DESCRIPTIVE_INVALID_CONFIG")
    for asset in assets: identifier(asset)
    first, last = label(value["start"]), label(value["end"])
    require(first < last and (last-first).days <= 20*366, "DESCRIPTIVE_INVALID_CONFIG")
    return {"schema": "polar.descriptive-config/1", **value, "instrument_ids": sorted(assets)}


def price(row):
    if row is None: return None
    try:
        return numeric(row["close"], "close")
    except (HistoryError, KeyError):
        return None


def ndjson(rows):
    return b"".join(canonical(row)+b"\n" for row in rows)


def reason_counts(rows):
    result = {}
    for row in rows:
        for reason in row["reasons"]: result[reason] = result.get(reason, 0) + 1
    return result


def compile_files(config, summary, bundle, sessions, calendar):
    """Caller has verified registered bytes and exact adopted reference-calendar binding."""
    definition = protocol()
    require(sessions is not None and calendar["status"] == "QUALIFIED_REFERENCE_DATES_ONLY",
            "DESCRIPTIVE_CALENDAR_UNRESOLVED")
    require(summary["basis"] == BASES and summary["fitness"]["rights_status"] == "ADMITTED",
            "DESCRIPTIVE_INPUT_UNQUALIFIED")
    for key in ("dataset_id", "dataset_revision", "import_receipt_id", "manifest_sha256"):
        require(config[key] == summary[key], "DESCRIPTIVE_INPUT_IDENTITY")
    names = sorted(set(config["instrument_ids"] + [config["benchmark_instrument_id"]]))
    available = {a["instrument_id"]: a for a in summary["instruments"]}
    require(all(name in available for name in names), "DESCRIPTIVE_ASSET_NOT_FOUND")
    require(all(available[name]["currency"] == available[names[0]]["currency"] for name in names),
            "DESCRIPTIVE_CURRENCY_MISMATCH")
    bars = {name: admitted_rows(bundle, name) for name in names}
    require(all(r["session_date"] in sessions for rows in bars.values() for r in rows),
            "DESCRIPTIVE_OUTSIDE_CALENDAR")
    code = code_projection()
    protocol_id, config_id, code_id = (identity(prefix, value) for prefix, value in
                                      (("protocol", definition), ("config", config), ("code", code)))
    inputs = {"schema": "polar.descriptive-inputs/1", "protocol_id": protocol_id, "config_id": config_id,
              "code_id": code_id, **{k: config[k] for k in ("dataset_id", "dataset_revision", "import_receipt_id", "manifest_sha256")},
              "basis": BASES, "calendar": calendar,
              "objects": {name: sha(bundle.files["bars/"+name+".ndjson"]) for name in names}}
    input_id = identity("input", inputs)
    candidates = [s for s in sessions if config["start"] <= s < config["end"]]
    index = {s:i for i,s in enumerate(sessions)}
    maps = {name: {r["session_date"]: r for r in rows} for name,rows in bars.items()}
    feature_rows, label_rows, reference_rows, counts, reference_metadata = [], [], [], {}, {}
    benchmark = maps[config["benchmark_instrument_id"]]
    for name in config["instrument_ids"]:
        source = maps[name]
        indicator_rows, _, _ = indicators(sessions, {s:r["close"] for s,r in source.items()},
                                         {"sma":20,"ema":None,"bb":None,"rsi":None})
        reference_metadata[name] = references(indicator_rows, {s:r["close"] for s,r in source.items()},
                                              {s:r["close"] for s,r in benchmark.items()}, "RAW_PRICE_RELATIVE")
        generated = {r["session_date"]:r for r in indicator_rows}
        asset_features, asset_labels, asset_references = [], [], []
        with localcontext(context()):
            for session in candidates:
                point, original = generated[session], source.get(session)
                close = price(original)
                feature_value, feature_reasons = None, []
                sma = point["values"]["sma"]
                if sma is None: feature_reasons.append(point["statuses"]["sma"]["reason"])
                else:
                    try: feature_value = derived_text(close / Decimal(sma) - Decimal(1))
                    except (DecimalException, HistoryError): feature_reasons.append("ARITHMETIC_ERROR")
                asset_features.append({"instrument_id":name,"session_date":session,
                    "close":original["close"] if original else None,"sma20":sma,"value":feature_value,
                    "status":"VALID" if feature_value is not None else "UNAVAILABLE",
                    "reasons":sorted(set(feature_reasons)),"segment_origin":point["segment_origin"]})
                position = index[session]
                horizon = sessions[position:position+6]
                endpoint = sessions[position+5] if position+5 < len(sessions) else None
                missing, invalid, label_reasons = [], [], []
                if endpoint is None: label_reasons.append("TAIL_ENDPOINT_UNAVAILABLE")
                for offset, expected in enumerate(horizon):
                    raw = source.get(expected)
                    role = "START" if offset == 0 else "ENDPOINT" if offset == 5 else "INTERIOR"
                    if raw is None:
                        missing.append(expected); label_reasons.append("MISSING_"+role)
                    elif price(raw) is None:
                        invalid.append(expected); label_reasons.append("INVALID_"+role)
                target_value = None
                if not label_reasons:
                    try: target_value = derived_text(price(source[endpoint]) / close - Decimal(1))
                    except (DecimalException, HistoryError): label_reasons.append("ARITHMETIC_ERROR")
                last = source.get(endpoint) if endpoint else None
                asset_labels.append({"instrument_id":name,"session_date":session,"target_session":endpoint,
                    "horizon_sessions":5,"start_close":original["close"] if original else None,
                    "end_close":last["close"] if last else None,"value":target_value,
                    "status":"VALID" if target_value is not None else "UNAVAILABLE",
                    "reasons":sorted(set(label_reasons)),"missing_sessions":missing,"invalid_sessions":invalid})
                a, b = point["values"]["asset_reference"], point["values"]["benchmark_reference"]
                valid_reference = a is not None and b is not None
                asset_references.append({"instrument_id":name,"session_date":session,"asset_value":a,"benchmark_value":b,
                    "status":"VALID" if valid_reference else "UNAVAILABLE",
                    "reasons":[] if valid_reference else [point["statuses"]["asset_reference"]["reason"]]})
        f = sum(r["status"] == "VALID" for r in asset_features)
        y = sum(r["status"] == "VALID" for r in asset_labels)
        paired = sum(a["status"] == b["status"] == "VALID" for a,b in zip(asset_features,asset_labels))
        counts[name] = {"candidate_expected":len(candidates),"observed_candidate":sum(s in source for s in candidates),
            "feature_valid":f,"target_valid":y,"paired_valid":paired,"unique_excluded":len(candidates)-paired,
            "reference_valid":sum(r["status"] == "VALID" for r in asset_references),
            "reason_counts":{"feature":reason_counts(asset_features),"label":reason_counts(asset_labels),
                             "reference":reason_counts(asset_references)}}
        feature_rows.extend(asset_features); label_rows.extend(asset_labels); reference_rows.extend(asset_references)
    values = {"protocol.json":canonical(definition),"config.json":canonical(config),"code.json":canonical(code),
              "inputs.json":canonical(inputs),"features.ndjson":ndjson(feature_rows),"labels.ndjson":ndjson(label_rows),
              "reference.ndjson":ndjson(reference_rows),"counts.json":canonical({"schema":"polar.descriptive-counts/1","assets":counts}),
              "reference-metadata.json":canonical({"schema":"polar.descriptive-reference-metadata/1","assets":reference_metadata})}
    views = {}
    for kind,table in (("feature","features.ndjson"),("label","labels.ndjson"),("reference","reference.ndjson")):
        core = {"schema":"polar.descriptive-view/1","input_id":input_id,"protocol_id":protocol_id,"config_id":config_id,
                "code_id":code_id,"table":table,"rows_sha256":sha(values[table]),"row_count":len(feature_rows),
                "metadata_sha256":sha(values["reference-metadata.json"]) if kind == "reference" else sha(values["counts.json"])}
        view_id = identity(kind+"-view", core)
        views[kind] = view_id
        values[kind+"-view.json"] = canonical({**core,"view_id":view_id})
    core = {"schema":"polar.descriptive-experiment/1","input_id":input_id,"protocol_id":protocol_id,"config_id":config_id,
            "code_id":code_id,"feature_view_id":views["feature"],"label_view_id":views["label"],
            "reference_view_id":views["reference"],"counts_sha256":sha(values["counts.json"]),
            "fitness":{"purpose":"RETROSPECTIVE_DESCRIPTIVE_ONLY","historical_known_by":"UNKNOWN_NULL",
                       "causal_PIT_fitness":"INSUFFICIENT_EVIDENCE","financial_evaluation":"NOT_RUN"}}
    experiment_id = identity("experiment", core)
    values["experiment.json"] = canonical({**core,"experiment_id":experiment_id})
    values["manifest.json"] = canonical({"schema":"polar.descriptive-manifest/1","experiment_id":experiment_id,
        "files":{name:{"sha256":sha(raw),"bytes":len(raw)} for name,raw in values.items()}})
    require(set(values) == set(definition["files"]), "DESCRIPTIVE_FILE_SET")
    # Exact field sets are part of the pre-invocation projection, not an outcome-selected subset.
    for name, fields in definition["metadata_fields"].items():
        require(set(decode(values[name])) == set(fields), "DESCRIPTIVE_FIELD_SET")
    for rows,key in ((feature_rows,"feature_fields"),(label_rows,"label_fields"),(reference_rows,"reference_fields")):
        require(all(set(r) == set(definition[key]) for r in rows), "DESCRIPTIVE_FIELD_SET")
    return experiment_id, values
