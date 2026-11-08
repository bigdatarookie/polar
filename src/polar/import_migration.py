"""Offline adapter for the frozen roster/sample producer; no capture_root trust or network."""
from pathlib import Path

from .history_bundle import read_file, safe_root, relative
from .import_contract import (MAX_FILE, exact, require, hash_value, decode, canonical, wire, sha,
                              digest, request, job_id, alignment, seconds)


def migration(config, store):
    exact(config,{"schema","roots","current_manifest_sha256","ancestry_objects"})
    require(config["schema"] == "polar.import-migration/1" and type(config["roots"]) is list and
            1 <= len(config["roots"]) <= 20)
    current = hash_value(config["current_manifest_sha256"])
    roots, inventory, historical, total = {}, {}, [], 0
    ancestry_hashes = set()
    require(type(config["ancestry_objects"]) is list and len(config["ancestry_objects"]) <= 30)
    for item in config["ancestry_objects"]:
        exact(item,{"root","path","sha256"})
        root = safe_root(Path(item["root"]))
        raw = read_file(root,relative(item["path"]),limit=MAX_FILE)
        require(sha(raw)==hash_value(item["sha256"]),"IMPORT_MIGRATION_ANCESTRY_HASH")
        ancestry_hashes.add(sha(raw));total += len(raw)
    for item in config["roots"]:
        exact(item,{"root","manifest","sha256"})
        require(Path(item["root"]).is_absolute() and item["root"] not in roots,"IMPORT_MIGRATION_ROOT")
        root = safe_root(Path(item["root"]))
        manifest_path = relative(item["manifest"])
        raw = read_file(root,manifest_path,limit=MAX_FILE)
        require(sha(raw) == hash_value(item["sha256"]),"IMPORT_MIGRATION_HASH")
        manifest = decode(raw)
        require(manifest["schema"] in ("polar.current-class-roster-content/1","polar.current-class-sample-content/1"),
                "IMPORT_MIGRATION_SCHEMA")
        files = {}
        prefix = Path(manifest_path).parent
        for name,entry in manifest["objects"].items():
            key = str(prefix/relative(name))
            data = read_file(root,key,limit=MAX_FILE)
            total += len(data)
            require(total <= 512*1024**2,"IMPORT_MIGRATION_SIZE")
            require(sha(data)==entry["sha256"] and len(data)==entry["bytes"],"IMPORT_MIGRATION_HASH")
            files[key] = data
        info = {"root":root,"manifest":manifest,"files":files,"manifest_sha256":sha(raw),"prefix":prefix}
        roots[str(root)] = info
        info["body_cache"] = {}
        inventory[str(root)] = {"manifest":manifest_path,"manifest_sha256":sha(raw),
                                "objects":manifest["objects"]}
        if manifest["schema"] == "polar.current-class-roster-content/1":
            receipts = decode(files[str(prefix/"receipts.json")])
            require(type(receipts) is list,"IMPORT_MIGRATION_RECEIPT")
            for index,receipt in enumerate(receipts):
                requests = receipt["request_body"]
                require(sha(wire(requests))==receipt["request_sha256"],"IMPORT_ORIGINAL_WIRE_HASH")
                historical.append({"root":str(root),"receipt_ordinal":index,"receipt":receipt,
                                   "requests":requests,
                                   "response_assignment":"VERIFIED_PER_SUCCESS_ONLY"})
            info["receipt_by_source"] = {str(prefix/f"responses/batch-{r['batch_ordinal']:04d}.json"):r for r in receipts}
        else:
            receipt = decode(files[str(prefix/"receipt.json")])
            requests = decode(files[str(prefix/"request.json")])
            # request.json is already the exact original newline-bearing wire.
            require(sha(files[str(prefix/"request.json")]) == receipt["request_sha256"],"IMPORT_ORIGINAL_WIRE_HASH")
            historical.append({"root":str(root),"receipt_ordinal":0,"receipt":receipt,
                               "requests":requests,
                               "response_assignment":"VERIFIED_PER_SUCCESS_ONLY"})
            info["sample_receipt"] = receipt
            info["sample_requests"] = requests
    require(sum(info["manifest_sha256"]==current for info in roots.values())==1,"IMPORT_MIGRATION_CURRENT")
    manifest_hashes = {info["manifest_sha256"] for info in roots.values()}
    for info in roots.values():
        parent = info["manifest"].get("parent_source_sha256")
        if parent:
            require(parent in manifest_hashes|ancestry_hashes,"IMPORT_MIGRATION_ANCESTRY_MISSING")
    jobs = {}
    appearances = {}
    for old in historical:
        for req in old["requests"]:
            jid = job_id(req)
            appearances[jid] = appearances.get(jid,0)+1
    for info in roots.values():
        prefix,files = info["prefix"],info["files"]
        if info["manifest"]["schema"] == "polar.current-class-sample-content/1":
            requests = decode(files[str(prefix/"request.json")])
            response = files[str(prefix/"response.json")]
            items,kinds = alignment(response,requests)
            entries = {r["idValue"]:{"response":items[i],"source":str(prefix/"response.json"),
                       "source_sha256":sha(response),"job_ordinal":i,"capture_root":str(info["root"])}
                       for i,r in enumerate(requests)}
        else:
            entries = decode(files[str(prefix/"job-results.json")])
            require(type(entries) is dict,"IMPORT_MIGRATION_JOBS")
        for symbol,entry in entries.items():
            capture = roots.get(entry["capture_root"])
            require(capture is not None,"IMPORT_CAPTURE_ROOT_NOT_ALLOWED")
            source = relative(entry["source"])
            require(source in capture["files"],"IMPORT_SOURCE_NOT_MANIFEST_MEMBER")
            body = capture["files"][source]
            require(sha(body)==entry["source_sha256"],"IMPORT_ORIGINAL_RESPONSE_HASH")
            cp = capture["prefix"]
            if source not in capture["body_cache"]:
                if capture["manifest"]["schema"] == "polar.current-class-sample-content/1":
                    receipt = capture["sample_receipt"]
                    original_requests = capture["sample_requests"]
                    captured_at = receipt["actual_completed_at"]
                else:
                    require(source in capture["receipt_by_source"],"IMPORT_RECEIPT_ASSOCIATION")
                    receipt = capture["receipt_by_source"][source]
                    original_requests = receipt["request_body"]
                    captured_at = receipt["completed_at"]
                require(receipt["http_status"]==200 and receipt["response_sha256"]==sha(body) and
                        receipt["response_bytes"]==len(body),"IMPORT_RECEIPT_INTEGRITY")
                seconds(captured_at)
                require(sha(wire(original_requests))==receipt["request_sha256"],"IMPORT_ORIGINAL_WIRE_HASH")
                values,kinds = alignment(body,original_requests)
                capture["body_cache"][source] = (receipt,original_requests,captured_at,values,kinds)
            receipt,original_requests,captured_at,values,kinds = capture["body_cache"][source]
            ordinal = entry["job_ordinal"]
            require(type(ordinal) is int and 0<=ordinal<len(values),"IMPORT_POSITIONAL_ASSOCIATION")
            req = request(symbol)
            require(original_requests[ordinal]==req and values[ordinal]==entry["response"] and
                    kinds[ordinal] in ("CANDIDATES","WARNING_NO_MATCH"),"IMPORT_POSITIONAL_ASSOCIATION")
            jid = job_id(req)
            item_hash = digest(values[ordinal])
            source_ref = {"capture_root":str(capture["root"]),"source":source,"source_sha256":sha(body),
                          "job_ordinal":ordinal,"request_wire_sha256":receipt["request_sha256"],
                          "actual_capture_at":captured_at,"manifest_sha256":capture["manifest_sha256"]}
            version = {"job_id":jid,"request":req,"kind":kinds[ordinal],"response":values[ordinal],
                       "response_sha256":item_hash,"sources":[source_ref]}
            versions = jobs.setdefault(jid,{})
            old = versions.get(item_hash)
            if old:
                aliases = {digest(s):s for s in old["sources"]+[source_ref]}
                version["sources"] = [aliases[k] for k in sorted(aliases)]
            versions[item_hash] = version
    record = {"schema":"polar.import-cache-commit/1","jobs":{k:list(v.values()) for k,v in sorted(jobs.items())},
              "migration":{"config":config,"inventory":inventory,"historical_requests":historical,
                           "historical_job_appearances_minimum":appearances,
                           "historical_attempts_exact":None,"historical_counts_meaning":"KNOWN_RECEIPTS_MINIMUM_NOT_RESET",
                           "source_bytes_verified":total}}
    identifier = digest(record)
    with store.locked():
        store.admit_storage()
        store.write("cache-imports/"+identifier+".json",record)
        cached = store.commits()
    return {"schema":"polar.import-migration-result/1","import_id":identifier,"imported_jobs":len(jobs),
            "cached_jobs":len(cached),"no_match":sum(all(v["kind"]=="WARNING_NO_MATCH" for v in versions)
                                                     for versions in cached.values()),
            "historical_receipts":len(historical),"historical_attempts_exact":None,
            "source_bytes_verified":total,"provider_requests":0,"scientific_fitness":"NOT_ASSESSED"}
