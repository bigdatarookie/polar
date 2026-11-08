"""Conditional close index, fixed opening wealth and prospective D-keyed masks."""
import math
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone

from .hyp007_contract import COHORT, FOLDS, check, finite, stamp, utc
from .hyp007_source import number


def value(token, positive=False):
    return finite(float(number(token, positive)))


def action_terms(events, evidence, clock):
    """No action aggregation: one direct event maximum per boundary."""
    if not events:
        return {"reason": None, "K": None, "event": None}
    if len(events) != 1:
        return {"reason": "UNRESOLVED_EVENT", "K": None, "event": None}
    event = events[0]
    reason = event["reason"]
    binding = evidence.get(event["id"])
    if binding is None:
        reason = "EVIDENCE_NOT_BOUND"
    k = event["K"]
    if binding:
        check(binding["source_id"] == event["id"] and binding["subject_symbol"] == event["subject"],
              "HYP007_EVIDENCE_MAPPING")
        if not binding["direct_cohort_share_effect"]:
            reason = "UNRESOLVED_EVENT"
        for assertion in binding["required_dated_evidence"]:
            day = assertion["document_date"]
            ek = clock.known_by(day)
            if ek is None:
                reason = "UNAVAILABLE_K"
            elif k is not None:
                k = max(k, ek)
        if k is not None:
            expected = datetime.fromisoformat(binding["historical_event_K"].replace("Z", "+00:00"))
            check(expected.tzinfo is not None and k == expected, "HYP007_EVIDENCE_CLOCK_MISMATCH")
    return {"reason": reason, "K": k, "event": event}


def effect(term):
    event = term["event"]
    check(not term["reason"], "HYP007_UNRESOLVED_EVENT")
    if event is None:
        return 1., 0.
    fields = event["fields"]
    if event["family"] == "forward_splits":
        return finite(value(fields["new_rate"], True)/value(fields["old_rate"], True)), 0.
    if event["family"] == "cash_dividends":
        return 1., value(fields["rate"])
    check(False, "HYP007_UNSUPPORTED_ORDINARY_EVENT")


class Panel:
    def __init__(self, source, evidence):
        self.source, self.clock, self.evidence = source, source.clock, evidence
        self.terms = {s: {day: action_terms(events, evidence, self.clock)
                          for day, events in source.actions[s].items()} for s in COHORT}

    def packets(self, compute=False):
        result = {}
        for symbol in COHORT:
            bars = self.source.bars[symbol]
            packets, levels, index_k = [], {}, None
            ordered = sorted(bars)
            if not ordered:
                result[symbol] = packets
                continue
            start = self.clock.index[date.fromisoformat(ordered[0])]
            broken = None
            previous = None
            for i in range(start, len(self.clock.sessions)):
                day = self.clock.sessions[i].isoformat()
                if day > ordered[-1]:
                    break
                if symbol == "TWTR" and day >= "2022-10-28":
                    break
                bar = bars.get(day)
                term = self.terms[symbol].get(day, {"reason": None, "K": None, "event": None})
                if bar is None or day in self.source.conflicts[symbol]:
                    broken = broken or "MISSING_OR_AMBIGUOUS_C_ANCESTOR"
                if i > start and term["reason"]:
                    broken = broken or term["reason"]
                if bar is not None:
                    if bar["K"] is None:
                        broken = broken or "UNAVAILABLE_K"
                    elif index_k is None:
                        index_k = bar["K"]
                    else:
                        index_k = max(index_k, bar["K"])
                if i > start and term["K"] is not None and index_k is not None:
                    index_k = max(index_k, term["K"])
                if compute and not broken:
                    if previous is None:
                        levels[i] = 1.
                    else:
                        split, cash = effect(term)
                        levels[i] = finite(levels[i-1]*split*(value(bar["tokens"]["c"], True)+cash) /
                                           value(previous["tokens"]["c"], True))
                        check(levels[i] > 0, "HYP007_NUMERICAL_INVALID")
                if i - start >= 252 and not broken:
                    # Full ancestors are represented by this contiguous range and the pinned raw/action objects.
                    packet = {"anchor": day, "index": i, "ancestor_start": start, "ancestor_end": i,
                              "K": stamp(index_k), "close_proxy": stamp(self.clock.completion(day)),
                              "features": None, "reason": None,
                              "last_operand_indices": [i, i, i-21, i, i, i],
                              "raw_volume_range": [i-20, i],
                              "flags": ["LAST_QUOTED_REFERENCE_MARK"] if symbol == "TWTR" and day == "2022-10-27" else []}
                    # Zero denominator is a source-domain predicate; no feature value is computed during prepare.
                    prior = [bars[self.clock.sessions[j].isoformat()]["tokens"] for j in range(i-20, i)]
                    if all(number(r["v"]) == 0 for r in prior):
                        packet["reason"] = "ZERO_PRIOR_DOLLAR_VOLUME"
                    elif compute:
                        returns = [finite(levels[j]/levels[j-1]-1) for j in range(i-19, i+1)]
                        mean = finite(math.fsum(returns)/20)
                        vol = finite(math.sqrt(math.fsum(finite((r-mean)**2) for r in returns)/19))
                        dv = [finite(value(bars[self.clock.sessions[j].isoformat()]["tokens"]["c"], True)*
                                     value(bars[self.clock.sessions[j].isoformat()]["tokens"]["v"]))
                              for j in range(i-20, i+1)]
                        denom = finite(math.fsum(dv[:-1])/20)
                        packet["features"] = [finite(levels[i]/levels[i-1]-1), finite(levels[i]/levels[i-5]-1),
                            finite(levels[i-21]/levels[i-252]-1), vol, finite(math.fsum(dv[1:])/20), finite(dv[-1]/denom)]
                    packets.append(packet)
                previous = bar
            result[symbol] = packets
        return result

    def terminal_k(self):
        terminal = self.terms["TWTR"].get("2022-10-28")
        return terminal["K"] if terminal and not terminal["reason"] else None

    def structural(self, packets):
        out = []
        for opp in self.source.roster:
            symbol = opp["instrument"]
            decision = utc(opp["D"])
            eligible = [p for p in packets[symbol] if not p["reason"] and utc(p["K"]) <= decision and
                        utc(p["close_proxy"]) <= decision]
            packet = eligible[-1] if eligible else None
            reason = None if packet else "NO_COMPLETE_READY_PACKET"
            tk = self.terminal_k()
            if symbol == "TWTR" and tk is not None and tk <= decision:
                reason = "KNOWN_TERMINAL_CONVERSION"
            out.append({**opp, "packet": packet, "M_info": reason is None, "info_reason": reason})
        return out

    def target(self, opp):
        symbol, days = opp["instrument"], opp["open_dates"]
        bars = self.source.bars[symbol]
        undefined = lambda reason: {"value": None, "reason": reason, "K": None,
                                    "mark_kind": None, "dependencies": [], "intermediate_mark": None}
        if symbol == "TWTR":
            if days[0] == "2022-10-27":
                return undefined("EFFECTIVE_DAY_ORDERING_UNRESOLVED")
            if days[0] >= "2022-10-28":
                return undefined("POSTTERMINAL_ENTRY_UNDEFINED")
            if days[-1] == "2022-10-27":
                return undefined("EFFECTIVE_DAY_ORDERING_UNRESOLVED")
        entry = bars.get(days[0])
        if entry is None or days[0] in self.source.conflicts[symbol]:
            return undefined("ENTRY_MISSING_OR_AMBIGUOUS")
        if entry["K"] is None:
            return undefined("UNAVAILABLE_K")
        # Entry is post-event ownership. No entry-boundary detached cash entitlement.
        initial = value(entry["tokens"]["o"], True)
        shares, k = 1., entry["K"]
        dependencies = [entry["pointer"]]
        terminal = symbol == "TWTR" and days[-1] >= "2022-10-28"
        for day in days[1:]:
            if terminal and day >= "2022-10-28":
                term = self.terms[symbol].get("2022-10-28")
                if not term or term["reason"] or term["event"]["family"] != "cash_mergers":
                    return undefined("UNRESOLVED_TERMINAL_EVIDENCE")
                check(value(term["event"]["fields"]["rate"], True) == 54.20, "HYP007_TERMINAL_VALUE_CONFLICT")
                k = max(k, term["K"])
                dependencies.append(term["event"]["pointer"])
                return {"value": finite(shares*54.20/initial-1), "reason": None, "K": stamp(k),
                        "mark_kind": "NOMINAL_GROSS_NONSPENDABLE_RECEIVABLE",
                        "dependencies": dependencies, "intermediate_mark": "UNKNOWN_EFFECTIVE_DAY"}
            term = self.terms[symbol].get(day, {"reason": None, "K": None, "event": None})
            if term["reason"]:
                return undefined(term["reason"])
            if term["event"]:
                if term["event"]["family"] == "cash_mergers":
                    return undefined("UNSUPPORTED_TERMINAL_EVENT")
                split, cash = effect(term)
                if cash:
                    current = bars.get(day)
                    if current is None or day in self.source.conflicts[symbol]:
                        return undefined("REINVESTMENT_OPEN_MISSING")
                    shares = finite(shares*split*(1+cash/value(current["tokens"]["o"], True)))
                    if current["K"] is None:
                        return undefined("UNAVAILABLE_K")
                    k = max(k, current["K"])
                    dependencies.append(current["pointer"])
                else:
                    shares = finite(shares*split)
                k = max(k, term["K"])
                dependencies.append(term["event"]["pointer"])
        endpoint = bars.get(days[-1])
        if endpoint is None or days[-1] in self.source.conflicts[symbol]:
            return undefined("ENDPOINT_MISSING_OR_AMBIGUOUS")
        if endpoint["K"] is None:
            return undefined("UNAVAILABLE_K")
        k = max(k, endpoint["K"])
        dependencies.append(endpoint["pointer"])
        return {"value": finite(shares*value(endpoint["tokens"]["o"], True)/initial-1), "reason": None,
                "K": stamp(k), "mark_kind": "CONDITIONAL_EX_OPEN_WEALTH", "dependencies": dependencies,
                "intermediate_mark": None}

    def realize(self, sealed_at):
        structural = self.structural(self.packets(compute=True))
        rows = [{**row, "target": self.target(row)} for row in structural]
        masks = []
        for year in FOLDS:
            cutoff = datetime(year, 1, 1, tzinfo=timezone.utc)
            ready = cutoff + timedelta(seconds=900)
            # Frozen target intervals for the full eval-year roster, irrespective of future validity.
            edges = {(r["instrument"], a, b) for r in rows if int(r["decision_date"][:4]) == year
                     for a, b in zip(r["open_dates"], r["open_dates"][1:])}
            for row in rows:
                target = row["target"]
                valid = target["reason"] is None
                maturity = valid and utc(row["openings"][-1]) <= cutoff and utc(target["K"]) <= cutoff
                overlap = any((row["instrument"], a, b) in edges for a,b in zip(row["open_dates"], row["open_dates"][1:]))
                train = utc(row["D"]) < cutoff and row["M_info"] and maturity and not overlap
                score = int(row["decision_date"][:4]) == year and row["M_info"] and ready <= utc(row["I_D"])
                evaluation = score and valid and utc(target["K"]) <= sealed_at
                reasons = []
                if not row["M_info"]: reasons.append(row["info_reason"])
                if not valid: reasons.append(target["reason"])
                if overlap: reasons.append("PURGED_SHARED_OPEN_TRANSITION")
                if valid and not maturity: reasons.append("NOT_TRAIN_MATURE_AT_F")
                if valid and utc(target["K"]) > sealed_at: reasons.append("LABEL_NOT_READY_AT_S")
                masks.append({"fold": year, "key": row["key"], "M_info": row["M_info"], "M_train": train,
                              "M_score": score, "M_eval": evaluation, "reasons": reasons})
        return rows, masks
