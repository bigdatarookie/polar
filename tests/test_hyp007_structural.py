"""Invented fixtures only. No native learner calls and no real-cohort label calculation."""
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from polar.hyp007_clocks import Clock
from polar.hyp007_contract import COHORT, DiagnosticError, canonical, decode, sha, stamp, definitions
from polar.hyp007_panel import Panel, action_terms
from polar.hyp007_service import DiagnosticService
from polar.hyp007_store import DiagnosticStore


def calendar(start="2015-01-01", end="2025-02-01"):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    days = [first+timedelta(days=i) for i in range((last-first).days+1)]
    return Clock([d.isoformat() for d in days if d.weekday() < 5], ZoneInfo("America/New_York"))


def source(clock):
    bars = {symbol: {} for symbol in COHORT}
    for symbol in COHORT:
        for i,day in enumerate(clock.sessions):
            text = day.isoformat()
            bars[symbol][text] = {"tokens": {"o": "100", "h": "101", "l": "99", "c": "100", "v": "2"},
                                 "K": clock.known_by(text), "pointer": {"file": "invented", "row": i}}
    return SimpleNamespace(clock=clock, bars=bars, actions={s: {} for s in COHORT},
                           conflicts={s: set() for s in COHORT}, roster=clock.opportunities())


def event(clock, day, family="cash_dividends", subject="AAPL", **fields):
    item = {"id": "INVENTED-EVENT", "family": family, "subject": subject, "fields": fields,
            "dates": {"ex_date": day, "process_date": day}, "currency": None,
            "pointer": {"file": "invented-action", "row": 0}, "roles": {"symbol": subject},
            "reason": None, "K": clock.known_by(day)}
    evidence = {item["id"]: {"source_id": item["id"], "subject_symbol": subject,
                            "direct_cohort_share_effect": True, "required_dated_evidence": [],
                            "historical_event_K": stamp(item["K"])}}
    return item, evidence


class ClocksAndPanel(unittest.TestCase):
    def test_dst_two_strict_sessions_and_equality(self):
        clock = calendar()
        self.assertEqual(stamp(clock.known_by("2022-10-28")), "2022-11-02T04:00:00.000000Z")
        self.assertEqual(stamp(clock.opening("2022-11-04")), "2022-11-04T13:30:00.000000Z")
        self.assertEqual(stamp(clock.opening("2022-11-07")), "2022-11-07T14:30:00.000000Z")
        self.assertIsNone(clock.known_by(clock.sessions[-1]))
        self.assertGreater(clock.known_by("2022-10-28"), clock.civil("2022-11-01", datetime.max.time()))

    def test_full_roster_and_phase(self):
        rows = calendar().opportunities()
        self.assertEqual([r["instrument"] for r in rows[:4]], list(COHORT))
        self.assertEqual(rows[0]["decision_date"], "2017-01-03")
        self.assertEqual(len(rows)%4, 0)
        self.assertTrue(any(r["instrument"] == "TWTR" and r["decision_date"].startswith("2024") for r in rows))

    def test_zero_volume_constant_returns_and_full_ancestors(self):
        c = calendar()
        s = source(c)
        panel = Panel(s,{})
        p = panel.packets(True)["AAPL"][0]
        self.assertEqual(p["features"], [0.,0.,0.,0.,200.,1.])
        self.assertEqual(p["ancestor_end"]-p["ancestor_start"],252)
        self.assertEqual(p["last_operand_indices"][2], p["index"]-21)
        anchor = p["anchor"]
        s.bars["AAPL"][anchor]["tokens"]["v"] = "0"
        self.assertEqual(Panel(s,{}).packets(True)["AAPL"][0]["features"][-1],0.)
        for j in range(p["index"]-20,p["index"]):
            s.bars["AAPL"][c.sessions[j].isoformat()]["tokens"]["v"] = "0"
        self.assertEqual(Panel(s,{}).packets(False)["AAPL"][0]["reason"], "ZERO_PRIOR_DOLLAR_VOLUME")
        # A missing early ancestor permanently breaks C; endpoint algebra cannot bridge it.
        del s.bars["AAPL"][c.sessions[100].isoformat()]
        self.assertEqual(Panel(s,{}).packets(True)["AAPL"], [])

    def test_split_cash_close_index_and_event_collision(self):
        c = calendar()
        s = source(c)
        day = c.sessions[300].isoformat()
        ev, evidence = event(c,day,"forward_splits",new_rate="2",old_rate="1")
        s.actions["AAPL"][day] = [ev]
        for d,b in s.bars["AAPL"].items():
            if d >= day: b["tokens"]["c"] = "50"
        packet = next(p for p in Panel(s,evidence).packets(True)["AAPL"] if p["anchor"] == day)
        self.assertEqual(packet["features"][:4], [0.,0.,0.,0.])
        s.actions["AAPL"][day].append(ev.copy())
        self.assertFalse(any(p["anchor"] >= day for p in Panel(s,evidence).packets(True)["AAPL"]))

    def test_target_entry_is_post_event_and_cash_reinvests_at_open(self):
        c = calendar()
        s = source(c)
        opp = next(r for r in s.roster if r["instrument"] == "AAPL")
        day = opp["open_dates"][1]
        ev,evidence = event(c,day,rate="10")
        s.actions["AAPL"][day] = [ev]
        target = Panel(s,evidence).target(opp)
        self.assertAlmostEqual(target["value"], .1)
        # An entry-day cash boundary does not give prior detached entitlement.
        s.actions["AAPL"] = {opp["open_dates"][0]: [ev]}
        self.assertEqual(Panel(s,evidence).target(opp)["value"],0.)

    def test_twtr_three_endpoint_cases_without_real_prices(self):
        c = calendar()
        s = source(c)
        ev,evidence = event(c,"2022-10-28","cash_mergers",subject="TWTR",rate="54.20")
        s.actions["TWTR"]["2022-10-28"] = [ev]
        panel = Panel(s,evidence)
        def opp(first,last):
            return {"instrument": "TWTR", "open_dates": [first,"2022-10-24","2022-10-25","2022-10-26","2022-10-27",last]}
        self.assertEqual(panel.target(opp("2022-10-27","2022-11-03"))["reason"], "EFFECTIVE_DAY_ORDERING_UNRESOLVED")
        self.assertEqual(panel.target(opp("2022-10-28","2022-11-04"))["reason"], "POSTTERMINAL_ENTRY_UNDEFINED")
        crossing = panel.target(opp("2022-10-21","2022-10-28"))
        self.assertAlmostEqual(crossing["value"], -.458)
        self.assertEqual(crossing["mark_kind"], "NOMINAL_GROSS_NONSPENDABLE_RECEIVABLE")
        self.assertEqual(crossing["intermediate_mark"], "UNKNOWN_EFFECTIVE_DAY")

    def test_late_label_does_not_censor_score(self):
        c = calendar()
        s = source(c)
        p = Panel(s,{})
        def target(row):
            return {"value": None, "reason": "LATE_UNKNOWN_LABEL", "K": None}
        p.target = target
        rows,masks = p.realize(datetime(2026,1,1,tzinfo=timezone.utc))
        self.assertTrue(any(m["M_score"] and not m["M_eval"] for m in masks))
        self.assertEqual(len(masks),3*len(s.roster))
        self.assertEqual(len(rows),len(s.roster))

    def test_source_role_and_dated_assertion_k(self):
        c = calendar()
        ev,evidence = event(c,"2020-08-31","forward_splits",new_rate="4",old_rate="1")
        evidence[ev["id"]]["required_dated_evidence"] = [{"document_date":"2020-07-30"}]
        # The owner artifact uses ISO offset seconds; compare instants, not spellings.
        evidence[ev["id"]]["historical_event_K"] = ev["K"].isoformat()
        self.assertEqual(action_terms([ev],evidence,c)["K"],ev["K"])
        self.assertEqual(action_terms([ev,ev],evidence,c)["reason"],"UNRESOLVED_EVENT")
        self.assertEqual(action_terms([ev],{},c)["reason"],"EVIDENCE_NOT_BOUND")


class DurableFamily(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DiagnosticStore(Path(self.tmp.name).resolve(),64*1024**2)
        self.aid = str(uuid.uuid4())
        self.seal = {"seal_id": "1"*64, "sealed_at": "2026-01-01T00:00:00.000000Z"}

    def test_failure_consumes_slot_and_restart_never_resets(self):
        self.store.begin(self.seal,self.aid)
        self.store.start_slot(self.aid,0)
        self.store.finish_slot(self.aid,0,"FAILED",code="INVENTED_FAILURE")
        with self.assertRaises(DiagnosticError): self.store.start_slot(self.aid,1)
        other = DiagnosticStore(Path(self.tmp.name).resolve(),64*1024**2)
        with self.assertRaises(DiagnosticError): other.begin(self.seal,str(uuid.uuid4()))
        with self.assertRaises(DiagnosticError): other.start_slot(self.aid,0)
        rows = other.slots(self.aid)
        self.assertEqual(rows[0]["status"],"FAILED")
        self.assertTrue(all(r["status"] == "NOT_RUN" for r in rows[1:]))

    def test_nine_slots_and_unfinalized_read(self):
        self.store.begin(self.seal,self.aid)
        for i in range(9):
            self.store.start_slot(self.aid,i)
            self.store.finish_slot(self.aid,i,"SUCCESS",model_hash="2"*64)
        with self.assertRaises(DiagnosticError): self.store.start_slot(self.aid,9)
        self.assertEqual(self.store.attempt(self.aid)["status"],"UNFINALIZED")
        self.store.finish(self.aid,"FAILED","INVENTED_INTERRUPTION",{})
        self.assertEqual(self.store.attempt(self.aid)["status"],"FAILED")

    def test_not_bound_does_not_start_family(self):
        prepared = {"schema":"polar.hyp007-prepare/1","status":"PREPARED_STRUCTURAL_ONLY","config":{},
                    "inventory":{},"roster":[],"structural":{},"definitions":definitions()}
        prepared["prepare_id"] = sha(canonical(prepared))
        seal = {"schema":"polar.hyp007-seal/1","prepared":prepared,
                "sealed_at":"2026-01-01T00:00:00.000000Z","bindings":{}}
        seal["seal_id"] = sha(canonical(seal))
        result = DiagnosticService(self.store).run(seal)
        self.assertEqual(result["status"],"NOT_BOUND")
        self.assertFalse((Path(self.tmp.name)/"hyp007-families").exists())

    def test_duplicate_json_and_immutable_tamper(self):
        with self.assertRaises(DiagnosticError): decode(b'{"a":1,"a":2}')
        self.store.begin(self.seal,self.aid)
        path = Path(self.tmp.name)/"hyp007-attempts"/self.aid/"start"/"record.json"
        path.chmod(0o600);path.write_text('{"schema":"corrupt"}')
        with self.assertRaises((DiagnosticError,KeyError)): self.store.attempt(self.aid)


if __name__ == "__main__":
    unittest.main()
