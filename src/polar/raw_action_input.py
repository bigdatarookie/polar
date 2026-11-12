"""Distinct raw-price/action admission; never an adjusted-reference fallback.

Metadata is admissible before FIRST_START. Source value decoding belongs only
inside the debited original. Source quality is bound, not re-fetched or inferred.
"""
from datetime import datetime, date, time, timedelta, timezone

from .ci_research import require
from .distribution_claims import Action
from .gym_contract import canonical, sha
from .obs158_math import microprice
from .reference_ridge_plan import nanoseconds
from .research_reference import decode, pinned_bytes, reference_schedule

INPUT = 'polar.raw-action-input/1'
PRIVATE = 'SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION'


def instant(text):
    return nanoseconds(datetime.fromisoformat(text.replace('Z', '+00:00')))


def metadata(pin, namespace):
    d = decode(pinned_bytes(pin))
    require(type(d) is dict and set(d) == {'schema','packet_ref','dates_ref','clocks_ref',
        'quotes_ref','actions_ref','source_instrument','source_symbol','event_dates',
        'split_records','rights','provenance','historical_K','limitations'}, 'RAW_INPUT_FIELDS')
    require(d['schema'] == INPUT and d['historical_K'] is None and d['split_records'] == 0,
            'RAW_INPUT_BASIS_SPLITS_CLOCK')
    require(d['rights'] == ('INVENTED_PUBLIC_TEST' if namespace == 'INVENTED' else PRIVATE), 'RAW_INPUT_RIGHTS')
    require(type(d['limitations']) is list and d['limitations'] and
            all(type(x) is str and 0 < len(x) <= 2048 for x in d['limitations']), 'RAW_INPUT_LIMITS')
    if namespace == 'INVENTED':
        require(d['provenance'] == {'kind':'DETERMINISTIC_INVENTED_FIXTURE','source_payloads':'NONE'},
                'RAW_INVENTED_PROVENANCE')
    packet = decode(pinned_bytes(d['packet_ref']))
    require(packet.get('schema') == 'polar.private-raw-price-action-consumer-dataset/1' and
            packet.get('source_instrument') == d['source_instrument'] and
            packet.get('source_symbol') == d['source_symbol'] and packet.get('observed_historical_K') is None,
            'RAW_PACKET_IDENTITY')
    members = {(p['sha256'], p['bytes']) for p in packet['members']}
    for k in ('quotes_ref','actions_ref','clocks_ref','dates_ref'):
        p = d[k]
        require((p['sha256'],p['bytes']) in members, 'RAW_PACKET_MEMBER_BINDING')
    days = decode(pinned_bytes(d['dates_ref']))
    require(type(days) is list and len(days) >= 3 and days == sorted(set(days)) and
            all(date.fromisoformat(x).isoformat() == x for x in days), 'RAW_DATES')
    rows = [decode(line) for line in pinned_bytes(d['clocks_ref']).splitlines()]
    reference_schedule({'schema':'polar.xnys-reference-schedule/1','rows':rows})
    require([r['date'] for r in rows] == days and
            packet['window'] == {'start_inclusive':days[0], 'end_inclusive':days[-1]}, 'RAW_GRID_BINDING')
    events = d['event_dates']
    require(type(events) is list and len(events) <= 10000 and
            len({e['event_id'] for e in events}) == len(events), 'RAW_EVENT_IDENTITIES')
    for e in events:
        require(type(e) is dict and set(e) == {'event_id','ex_date','payment_date','availability_date'} and
                e['ex_date'] in days and e['payment_date'] >= e['ex_date'] and
                e['availability_date'] == next((x for x in days if x > e['payment_date']), None) and
                e['availability_date'] is not None, 'RAW_ACTION_DATE_METADATA')
    return d, days, rows


def calendar(d, days, rows):
    """Closed date-driven formations. No amounts, target or cash arithmetic."""
    mapped = {r['date']:r for r in rows}; terminal = days[-1]
    annual = [days[0]] + [max(x for x in days if date.fromisoformat(x).year == y)
        for y in range(date.fromisoformat(days[0]).year, date.fromisoformat(terminal).year)]
    annual = list(dict.fromkeys(annual))
    payments = sorted({e['availability_date'] for e in d['event_dates']
        if mapped[e['availability_date']]['next_reference_date'] is not None and
        mapped[e['availability_date']]['next_reference_date'] < terminal})
    formations = sorted(set(annual + payments + [days[-2]]))
    out = []
    for g in formations:
        entry = mapped[g]['next_reference_date']
        k = datetime.combine(date.fromisoformat(g)+timedelta(days=1), time(), tzinfo=timezone.utc)
        known = nanoseconds(k); decision = nanoseconds(k+timedelta(seconds=60))
        q = instant(mapped[entry]['reference_close_utc']) if entry else None
        require(q is not None and known < decision < q and
                (entry < terminal or g == days[-2]), 'RAW_K_D_Q_TERMINAL')
        out.append({'formation':g,'execution_date':entry,'known_ns':known,'decision_ns':decision,
            'close_ns':q,'initial':g == days[0], 'annual':g in annual,
            'payment':g in payments, 'terminal':entry == terminal})
    return {'schema':'polar.raw-action-calendar/1','dates':days,'events':out,
            'source_event_dates':d['event_dates'],'clock':'MODELED_UTC_NEXT_MIDNIGHT_D60_NEXT_REFERENCE_CLOSE'}


def load(d, days, rows):
    quotes = [decode(line) for line in pinned_bytes(d['quotes_ref']).splitlines()]
    require(len(quotes) == len(days), 'RAW_QUOTE_COUNT')
    prices = {}; quote_evidence = []
    for r, day in zip(quotes, days):
        require(r['session_date'] == day and r['instrument'] == d['source_instrument'] and
                r['source_symbol'] == d['source_symbol'] and r['currency'] == 'USD' and
                r['basis'] == 'VENDOR_RAW_UNADJUSTED_USD_PER_SHARE' and r['historical_known_by'] is None,
                'RAW_QUOTE_IDENTITY_BASIS')
        op, cl = microprice(r['open_token']), microprice(r['close_token'])
        require(type(r['open_micro']) is int and r['open_micro'] == op and
                type(r['close_micro']) is int and r['close_micro'] == cl, 'RAW_PRICE_LEXEME_LOSS')
        prices[day] = {'open_micro':op,'close_micro':cl}
        quote_evidence.append(r)  # Private saved source pointers/tokens, never common wire.
    wrappers = [decode(line) for line in pinned_bytes(d['actions_ref']).splitlines()]
    expected = {e['event_id']:e for e in d['event_dates']}; actions = []
    require(len(wrappers) == len(expected), 'RAW_ACTION_COUNT')
    seen = set()
    for w in wrappers:
        a = dict(w['action']); a['reference_dates'] = tuple(a['reference_dates']); action = Action(**a)
        require(action.event_id in expected and action.event_id not in seen and
                action.instrument == d['source_instrument'] and action.reference_dates == tuple(days),
                'RAW_ACTION_IDENTITY')
        seen.add(action.event_id); e = expected[action.event_id]
        require((action.ex_date,action.payment_date,action.availability_date) ==
                (e['ex_date'],e['payment_date'],e['availability_date']), 'RAW_ACTION_DATE_BINDING')
        original = w['original_fields_as_supplied']; raw = w['source_raw']; rec = w['raw_record']
        require(original['unadjustedValue'] == action.amount_token and original['date'] == action.ex_date and
                original['paymentDate'] == action.payment_date and original['currency'] == action.currency,
                'RAW_ORIGINAL_NOMINAL_BINDING')
        material = {'source_sha256':raw['sha256'],'json_pointer':rec['json_pointer'],'record_sha256':rec['sha256']}
        require(action.source_ref == 'sha256:'+raw['sha256'] and action.raw_pointer == rec['json_pointer'] and
                action.event_id == 'eodhd-vti-div-'+sha(canonical(material)), 'RAW_CONTENT_EVENT_ID')
        avail = w['modeled_cash_availability']
        require(avail['date'] == action.availability_date and avail['historical_known_by'] is None and
                avail['actual_broker_receipt'] is None, 'RAW_MODELED_NOT_OBSERVED_PAYMENT')
        actions.append(a)
    return {'prices':prices,'actions':actions,'source_rows':quote_evidence,'action_rows':wrappers,
            'schedule':rows,'dates':days,'source_identity':d}
