"""Public invented no-fit input/profile, built from the existing reference fixture."""
from datetime import datetime
import hashlib
import json
from pathlib import Path

from reference_fixture import fixture as reference_fixture, write
from polar.scheduled_service import config_from_seed


def fixture(tmp_path, monkeypatch):
    root, old = reference_fixture(tmp_path, monkeypatch)
    manifest = json.loads(Path(old['input_ref']['path']).read_bytes())
    schedule = json.loads(Path(manifest['schedule']['path']).read_bytes())['rows']
    days = [r['date'] for r in schedule]
    def grid(lo, hi):
        selected = days[lo:hi+1]
        decisions = [{'signal_date': days[i], 'signal_index': i, 'execution_date': days[i+1],
                      'execution_reference_close_utc': schedule[i+1]['reference_close_utc']}
                     for i in range(lo, hi) if schedule[i]['month_end_in_reference_range'] is True and i+1 < hi]
        return {'initial': days[lo], 'terminal': days[hi], 'nav_dates': selected,
                'nav_points': len(selected), 'return_count': len(selected)-1,
                'decisions': decisions, 'decision_count': len(decisions)}
    calendar = {'schema': 'polar.scheduled-policy-calendar/1', 'source_schedule': manifest['schedule'],
                'phases': {'VALIDATION': grid(320, 350), 'FINAL': grid(351, 399)}}
    cp = write(tmp_path/'scheduled-calendar.json', calendar)
    protocol = write(tmp_path/'scheduled-protocol.json', {'schema': 'polar.invented-scheduled-protocol/1',
        'classification': 'INVENTED', 'mechanism': 'NO_FIT_ABSOLUTE_SLEEVES', 'rightsholder': 'PUBLIC_TEST'})
    def criterion(kind, identity, right=None, **extra):
        return {'kind': kind, 'id': identity, 'description': identity.replace('_', ' '),
                'left_id': 'SLEEVES', **({'right_id': right} if right else {}), **extra}
    profile = {'schema': 'polar.scheduled-reference-profile/1', 'protocol_id': 'INVENTED-SCHEDULED-V1',
        'protocol_sha256': protocol['sha256'], 'input_sha256': old['input_ref']['sha256'],
        'calendar_sha256': cp['sha256'], 'timezone_sha256': old['timezone_ref']['sha256'],
        'symbols': ['AAA', 'BBB', 'CCC', 'DDD'],
        'policy': {'kind': 'ABSOLUTE_MOMENTUM_SLEEVES', 'lookback': 252, 'skip': 21},
        'legs': [{'id': i, 'label': label, 'rule': rule, 'scale': scale} for i, label, rule, scale in [
            ('SLEEVES', 'Fixed equal positive-trend sleeves', 'SLEEVES', [1,1]),
            ('EW', 'Monthly equal weight', 'EQUAL_WEIGHT', [1,1]),
            ('EW_HALF', 'Monthly half exposure', 'EQUAL_WEIGHT', [1,2]),
            ('MOM', 'Positive relative momentum', 'MOMENTUM', [1,1]),
            ('CASH', 'Cash control', 'CASH', [1,1])]],
        'primary_strategy': 'SLEEVES', 'primary_benchmark': 'EW', 'decision_delay_seconds': 60,
        'criteria': [criterion('SR_DELTA_GE', 'SR_GT_EW', 'EW', threshold='0.10'),
            criterion('SR_DELTA_GE', 'SR_GT_HALF', 'EW_HALF', threshold='0.10'),
            criterion('TERMINAL_GE', 'GROWTH_NOT_LESS_HALF', 'EW_HALF'),
            criterion('POSITIVE_GROWTH', 'POSITIVE_GROWTH'), criterion('DRAWDOWN_LE', 'DD_NOT_WORSE_EW', 'EW')],
        'question_label': 'Invented no-fit trend comparison',
        'question_summary': 'Exact positive absolute trend sleeves versus full and half monthly equal weight.',
        'clock_description': 'Invented modeled early-close schedule; next New York midnight K and D sixty seconds later.',
        'partition_description': 'No fit or model. Separate fresh-capital validation and final phases, no selection.',
        'additional_limitations': [['NO_LEARNED_MODEL', 'This is a fixed no-fit rule, not a predictive model or general alpha claim.']],
        'subperiods': [[days[352], days[370]], [days[371], days[399]]]}
    pp = write(tmp_path/'scheduled-profile.json', profile)
    cfg = config_from_seed({'schema': 'polar.scheduled-reference-seed/1', 'namespace': 'INVENTED',
        'profile_path': pp['path'], 'protocol_path': protocol['path'], 'input_path': old['input_ref']['path'],
        'calendar_path': cp['path'], 'timezone_path': old['timezone_ref']['path'],
        'code_revision': old['code_revision'], 'runtime_image_id': old['runtime_image_id'],
        'candidate_id': 'INVENTED-SCHEDULED', 'experiment_id': 'INVENTED-NOFIT-ORIGINAL'})
    return root, cfg, profile, calendar
