"""Original pre-execution literal vectors, no private QA oracle or market data."""
from decimal import Decimal, ROUND_DOWN, getcontext, localcontext

import pytest

from polar.history_numeric import context, derived_text, indicators, references
from polar.history_bundle import HistoryError


def calculate(values, n=3, **periods):
    dates = [f"2024-01-{i+1:02}" for i in range(len(values))]
    observations = {d:v for d,v in zip(dates,values) if v is not None}
    rows, metadata, resets = indicators(dates, observations,
        {k:periods.get(k) for k in ("sma","ema","bb","rsi")})
    return rows, metadata, resets


def test_sma_ema_seed_and_recurrence_literals():
    rows, _, _ = calculate(["1","1","4","10","10"], sma=3,ema=3)
    assert [r["values"]["sma"] for r in rows] == [None,None,"2","5","8"]
    assert [r["values"]["ema"] for r in rows] == [None,None,"2","6","8"]
    assert rows[0]["statuses"]["ema"] == {"status":"UNAVAILABLE","reason":"WARMUP"}


@pytest.mark.parametrize('values,expected', [(["1","5"],["3","7","-1"]),(["2","2"],["2","2","2"])])
def test_population_bands_flat_and_unclipped_lower(values, expected):
    rows,_,_ = calculate(values,bb=2)
    assert [rows[-1]["values"][k] for k in ("bb_middle","bb_upper","bb_lower")] == expected


@pytest.mark.parametrize('values,expected', [(["1","2","3"],"1E+2"),(["3","2","1"],"0"),
    (["2","2","2"],"5E+1"),(["1","3","2","3"],"8E+1")])
def test_wilder_seeds_and_next_recurrence(values,expected):
    rows,_,_ = calculate(values,rsi=2)
    assert rows[1]["values"]["rsi"] is None
    assert rows[-1]["values"]["rsi"] == expected


@pytest.mark.parametrize('bad,reason',[(None,"GAP"),("0","INVALID_PRICE"),("NaN","INVALID_PRICE")])
def test_gap_invalid_resets_instead_of_skipping(bad,reason):
    rows,metadata,resets = calculate(["1","1",bad,"4","10","10"],sma=3,ema=3,rsi=2)
    assert rows[2]["statuses"]["sma"]["reason"] == reason
    assert rows[4]["values"]["ema"] is None
    assert rows[5]["values"]["ema"] == "8"
    assert rows[5]["segment_origin"] == "2024-01-04"
    assert metadata["ema"]["reset_count"] == 1 and len(resets) == 1


def test_fixed_common_anchor_missing_pair_and_recovery():
    rows,_,_ = calculate(["10","20",None,"40"])
    a = dict(zip([r["session_date"] for r in rows],["10","20",None,"40"]))
    b = dict(zip(a,["100","100","110","200"]))
    meta = references(rows,a,b,"RAW_PRICE_RELATIVE")
    assert meta["anchor_session"] == "2024-01-01"
    assert [(r["values"]["asset_reference"],r["values"]["benchmark_reference"]) for r in rows] == [
        ("1E+2","1E+2"),("2E+2","1E+2"),(None,None),("4E+2","2E+2")]


def test_private_context_precision_and_flags_do_not_depend_on_caller():
    values = ["1.123456789012345678","2.234567890123456789","4.345678901234567890","9.456789012345678901"]
    baseline = calculate(values,sma=3,ema=3,bb=3,rsi=2)
    with localcontext() as ambient:
        ambient.prec=2; ambient.rounding=ROUND_DOWN
        for signal in ambient.traps: ambient.traps[signal]=True
        before = ambient.copy()
        assert calculate(values,sma=3,ema=3,bb=3,rsi=2) == baseline
        assert ambient.flags == before.flags and ambient.traps == before.traps and ambient.prec == 2
    assert len(baseline[0][-1]["values"]["ema"]) > 20


def test_canonical_no_context_normalize_or_negative_zero():
    with localcontext() as ctx:
        ctx.prec=1
        assert [derived_text(Decimal(v)) for v in ["-0","100.00","1.2300","-0.1250"]] == ["0","1E+2","123E-2","-125E-3"]


def test_unresolved_and_disabled_not_observed_zero():
    rows,meta,_=indicators(["2024-01-01"],{"2024-01-01":"1"},{"sma":2,"ema":None,"bb":None,"rsi":None},qualified=False)
    assert rows[0]["statuses"]["sma"]["reason"] == "UNRESOLVED_GAPS"
    assert meta["ema"]["status"] == "DISABLED" and rows[0]["values"]["ema"] is None


def test_duplicate_session_is_error():
    with pytest.raises(HistoryError):
        indicators(["2024-01-01"]*2,{},dict.fromkeys(("sma","ema","bb","rsi")))
