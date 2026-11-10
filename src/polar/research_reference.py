"""Lossless vendor-adjusted reference-unit input; no model, trading or action inference.

Consumes the existing private DE projection. Raw OHLC is never substituted for
reference_quote. The schedule is a pinned model calendar, not observed PIT.
"""
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path
import hashlib
import json
import os
import re
import stat

from .ci_research import require
from .obs158_math import microprice

BASIS = 'VENDOR_SPLIT_AND_DIVIDEND_ADJUSTED_REFERENCE_CLOSE'
UNIT = 'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE'
MAX_BYTES = 256 * 1024**2
SHA = re.compile('[a-f0-9]{64}')


def decode(raw):
    def unique(items):
        value = {}
        for key, item in items:
            require(key not in value, 'REFERENCE_DUPLICATE_JSON_KEY')
            value[key] = item
        return value
    def invalid(_):
        raise ValueError('REFERENCE_NONFINITE_JSON')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def pinned_bytes(pin):
    require(type(pin) is dict and {'path', 'sha256'} <= pin.keys() <= {'path', 'sha256', 'bytes'},
            'REFERENCE_PIN_FIELDS')
    require(type(pin['sha256']) is str and SHA.fullmatch(pin['sha256']) is not None,
            'REFERENCE_PIN_HASH')
    path = Path(pin['path'])
    require(path.is_absolute() and path.resolve() == path, 'REFERENCE_PATH')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_BYTES, 'REFERENCE_FILE_BOUND')
        if 'bytes' in pin:
            require(type(pin['bytes']) is int and info.st_size == pin['bytes'], 'REFERENCE_FILE_SIZE')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(MAX_BYTES + 1)
        require(len(raw) == info.st_size and hashlib.sha256(raw).hexdigest() == pin['sha256'],
                'REFERENCE_FILE_HASH')
        return raw
    finally:
        os.close(fd)


def _day(value):
    require(type(value) is str and date.fromisoformat(value).isoformat() == value, 'REFERENCE_DATE')
    return value


def _instant(value):
    require(type(value) is str, 'REFERENCE_CLOCK')
    dt = datetime.fromisoformat(value)
    require(dt.utcoffset() is not None, 'REFERENCE_CLOCK_ZONE')
    return dt


def reference_schedule(schedule):
    """Shared structural calendar validation, usable before immutable publication."""
    require(schedule.get('schema') == 'polar.xnys-reference-schedule/1', 'REFERENCE_SCHEDULE_SCHEMA')
    rows = schedule['rows']
    require(type(rows) is list and 1 <= len(rows) <= 10000, 'REFERENCE_SCHEDULE_BOUND')
    days = [_day(r['date']) for r in rows]
    require(days == sorted(set(days)), 'REFERENCE_SCHEDULE_ORDER')
    for i, row in enumerate(rows):
        require(_instant(row['reference_open_utc']) < _instant(row['reference_close_utc']) and
                _instant(row['reference_open_utc']).date().isoformat() == days[i] and
                _instant(row['reference_close_utc']).date().isoformat() == days[i], 'REFERENCE_SESSION_CLOCK')
        require(row['next_reference_date'] == (days[i+1] if i+1 < len(days) else None),
                'REFERENCE_NEXT_SESSION')
    return rows, days


def load_reference(manifest_pin):
    """Read full declared grid without eligibility, returns, fits or source reconstruction."""
    manifest = decode(pinned_bytes(manifest_pin))
    require(type(manifest) is dict and manifest.get('schema') in
            ('polar.synthetic-reference-source-input/1', 'polar.synthetic-reference-source-input/2'),
            'REFERENCE_MANIFEST_SCHEMA')
    version2 = manifest['schema'].endswith('/2')
    expected_basis = 'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE' if version2 else BASIS
    require(manifest.get('quote_basis') == expected_basis and manifest.get('unit_type') == UNIT and
            manifest.get('double_action_policy') == 'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL',
            'REFERENCE_BASIS')
    symbols = manifest['symbols']
    require(type(symbols) is list and 1 <= len(symbols) <= 256 and len(set(symbols)) == len(symbols)
            and all(type(s) is str and re.fullmatch('[A-Z][A-Z0-9.]{0,31}', s) for s in symbols),
            'REFERENCE_SYMBOLS')
    schedule = decode(pinned_bytes(manifest['schedule']))
    rows, days = reference_schedule(schedule)
    require(manifest['dates'] == {'count': len(days), 'start': days[0], 'end': days[-1]} and
            type(manifest['rows']) is int and manifest['rows'] == len(days)*len(symbols), 'REFERENCE_DECLARED_GRID')
    members = {p['sha256'] for p in manifest['source_members']}
    require(members and all(type(h) is str and SHA.fullmatch(h) for h in members), 'REFERENCE_SOURCE_MEMBERS')
    relations = decode(pinned_bytes(manifest['source_relations'])) if version2 else None
    if version2:
        require(relations.get('schema') == 'polar.reference-source-relations/1', 'REFERENCE_RELATIONS_SCHEMA')
    raw = pinned_bytes(manifest['quotes'])
    lines = raw.splitlines(keepends=True)
    require(len(lines) == manifest['rows'], 'REFERENCE_ROW_COUNT')
    prices, evidence = {}, {}
    fields = {'symbol', 'date', 'reference_quote', 'source_adjusted_close_token', 'source_ref',
              'observed_published_at', 'observed_historical_available_at'}
    for line, (day, symbol) in zip(lines, ((d, s) for d in days for s in symbols)):
        value = decode(line)
        require(type(value) is dict and set(value) == fields and value['symbol'] == symbol and
                value['date'] == day, 'REFERENCE_ROW_IDENTITY_ORDER')
        quote = microprice(value['reference_quote'])
        require(quote == microprice(value['source_adjusted_close_token']), 'REFERENCE_SCALE_CHANGED')
        source = value['source_ref']
        if version2:
            from .reference_input import validate_source
            validate_source(value, members, relations)
        else:
            require(type(source) is dict and set(source) == {'normalized_member_sha256', 'line_1based',
                'line_sha256', 'raw_object_sha256', 'source_row_index'}, 'REFERENCE_SOURCE_POINTER')
            require(source['normalized_member_sha256'] in members and
                all(type(source[k]) is str and SHA.fullmatch(source[k]) for k in
                    ('normalized_member_sha256', 'line_sha256', 'raw_object_sha256')) and
                type(source['line_1based']) is int and source['line_1based'] > 0 and
                type(source['source_row_index']) is int and source['source_row_index'] >= 0,
                'REFERENCE_SOURCE_POINTER')
        prices.setdefault(day, {})[symbol] = quote
        # Preserve unknown clocks verbatim. Protocol eligibility is a separate layer.
        evidence.setdefault(day, {})[symbol] = {'source_ref': source,
            'observed_published_at': value['observed_published_at'],
            'observed_historical_available_at': value['observed_historical_available_at']}
    return {'manifest_ref': {k: manifest_pin[k] for k in ('sha256', 'bytes') if k in manifest_pin},
            'dataset_revision': manifest['parent_dataset_revision'], 'symbols': list(symbols), 'dates': days,
            'schedule': rows, 'prices_micro': prices, 'source_evidence': evidence,
            'quote_basis': expected_basis, 'unit_type': UNIT, 'eligibility': 'NOT_DERIVED',
            'rights': manifest['rights'], 'action_credit': 'NONE'}


def trailing_return(market, symbol, end_index, lag):
    """Causal exact ratio; caller chooses the frozen feature/horizon definition."""
    require(type(end_index) is int and type(lag) is int and lag > 0 and
            0 <= end_index-lag < end_index < len(market['dates']), 'REFERENCE_FEATURE_WINDOW')
    days = market['dates']; prices = market['prices_micro']
    return Fraction(prices[days[end_index]][symbol], prices[days[end_index-lag]][symbol]) - 1
