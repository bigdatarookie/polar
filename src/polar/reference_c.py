"""Frozen C54 admission and date/coverage adaptation; no model or source acquisition.

The owner date contract references the parent schedule. The executable subset is
separately pinned; neither historical association is rewritten to impersonate the
other. Calendar normalization uses dates only, before quote loading or fitting.
"""
from .ci_research import require
from .gym_contract import canonical, sha

C = 'V033-C-RIDGE-BROADREF100-V1'
INVENTED_C = 'INVENTED-REFERENCE-C54-CONTROL-V1'
LEGS = ['RIDGE_TOP1_OR_CASH', 'MOM252_21_TOP1_OR_CASH', 'EW_ELIGIBLE_MONTHLY', 'CASH']
SYMBOLS = ('A AAL AAME AAOI AAON AAP ABBV ABCB ABEO ABG ABM ABT ABUS ACAD ACCO ACET ACGL ACHC ACHV '
           'ACIW ACLS ACM ACN ACNB ACRS ACTG ADBE ADI ADM ADMA ADP ADSK ADTN ADUS AEE AEHR AEIS AEM '
           'AEMD AEO AEP AER AES AFG AFL AG AGCO AGEN AGI AGIO AGM AGO AGRO AGX').split()
PROFILE = {
    'kind': 'RIDGE', 'registration': C+'-EXPERIMENT-01',
    'protocol': '2622392745f39bf3e8e42c5f46ab39e3fdd64777f2433f82336d823efe529d31',
    'method': 'f4ad21fe2bfa4e6cb9dc53e8b6226126531b92c6ec11387f69dbe395b0fb157a',
    'calendar': 'fd3e31ac99d447697c55f71c574cbf423f42a5f0ebf8ae44b06154f63b54067a',
    'input': 'ebd040aec68824bdc4d5a62dceb886683daec7ea0f3c325dd1c48337648b5e3c'}
SCHEDULE = '94c92b6437accafbfdb97ffc272ce93fe1dd52169a060fb21847a39f5681e20e'
PARENT_SCHEDULE = '67fcf8fd379eb8d2afd447eb5f2ec7085e44bcee41ee9d3958050c5978219098'
QUOTES = 'b1a1106f5a9231f1f903e03107b1c02f9bdef318a30828b0a5a74acc084fd7ad'
RELATIONS = '9b37e96652db57c1383b11a2734f69c103ea9d17bf7ee2e7cf4d1e5ba054b8c5'


def admit_metadata(manifest, contract, schedule, *, retained):
    require(manifest['schema'] == 'polar.synthetic-reference-source-input/2' and
            manifest['quote_basis'] == 'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE' and
            len(manifest['symbols']) == 54, 'REFERENCE_C_SOURCE_PROFILE')
    if retained:
        require(manifest['symbols'] == SYMBOLS and manifest['rows'] == 147312 and
                manifest['schedule']['sha256'] == SCHEDULE and manifest['quotes']['sha256'] == QUOTES and
                manifest['source_relations']['sha256'] == RELATIONS and
                contract['source_schedule']['sha256'] == PARENT_SCHEDULE and
                sum(r['early_close_reference'] is True for r in schedule) == 21,
                'REFERENCE_C_FROZEN_SOURCE')
    else:
        require(contract['source_schedule']['sha256'] == manifest['schedule']['sha256'],
                'REFERENCE_CALENDAR_JOIN')


def executable_calendar(contract, rows, *, retained):
    days = [r['date'] for r in rows]; indices = {d: i for i, d in enumerate(days)}
    require(days == sorted(set(days)) and len(days) == contract['reference_dates'] and
            (days[0], days[-1]) == (contract['start'], contract['end']), 'REFERENCE_C_DATE_GRID')
    for i, row in enumerate(rows):
        nxt = days[i+1] if i+1 < len(days) else None
        require(row['next_reference_date'] == nxt and row['month_end_in_reference_range'] ==
                (nxt[:7] != row['date'][:7] if nxt else None), 'REFERENCE_C_MONTH_GRID')
    def cycle(signal, entry, exit):
        require(signal in indices and entry in indices and exit in indices and
                indices[entry] == indices[signal]+1 and signal < entry < exit and
                indices[signal] >= 252, 'REFERENCE_C_LABEL_GRID')
        return {'signal': signal, 'signal_index': indices[signal], 'entry': entry, 'label_exit': exit}
    training = [cycle(c['signal'], c['entry'], c['exit']) for c in contract['training_cycles']]
    require(len(training)*54 == contract['training_rows'] and
            contract['training_reference_aliases'] == 54, 'REFERENCE_C_TRAINING_ROWS')
    result = {'source_schedule': contract['source_schedule'], 'training_cycles': training,
              'training_rows': contract['training_rows']}
    for phase in ('validation', 'final'):
        bounds = (('2020-12-31', '2022-12-30') if phase == 'validation' else
                  ('2022-12-30', '2026-11-06')) if retained else tuple(contract[phase+'_bounds'])
        initial, terminal = bounds
        require(initial in indices and terminal in indices and initial < terminal, 'REFERENCE_C_PHASE_GRID')
        origins = [r for r in rows if initial <= r['date'] < terminal and
                   r['month_end_in_reference_range'] is True and r['next_reference_date'] < terminal]
        complete = [cycle(a['date'], a['next_reference_date'], b['next_reference_date'])
                    for a, b in zip(origins, origins[1:])]
        nav = indices[terminal]-indices[initial]+1
        require(nav == contract[phase+'_nav'] and nav-1 == contract[phase+'_returns'] and
                len(complete) == contract[phase+'_complete_origins'] and
                len(complete)*54 == contract[phase+'_label_rows'], 'REFERENCE_C_PHASE_COUNTS')
        result[phase+'_financial_grid'] = {'initial': initial, 'terminal': terminal,
            'first_execution': days[indices[initial]+1], 'nav_points': nav, 'returns': nav-1,
            'monthly_decisions': len(origins)}
        result[phase+'_complete_label_cycles'] = complete
    if retained:
        require(len(days) == 2728 and len(training) == 46 and result['training_rows'] == 2484 and
                [(result[p+'_financial_grid']['nav_points'], result[p+'_financial_grid']['monthly_decisions'],
                  len(result[p+'_complete_label_cycles'])*54) for p in ('validation', 'final')] ==
                [(504, 24, 1242), (967, 47, 2484)] and
                [(c['signal'], c['entry'], c['label_exit']) for c in (training[0], training[-1])] ==
                [('2017-01-31', '2017-02-01', '2017-03-01'), ('2020-10-30', '2020-11-02', '2020-12-01')],
                'REFERENCE_C_FROZEN_CALENDAR')
    return result


def coverage(market, *, retained):
    """Sanitize existing converter ledger, preserving unknowns and all exclusions.

    Private acquisition paths/requests are not part of the public result. The
    immutable semantic bundle also retains this full typed ledger and its pin.
    """
    relations = market['source_relations']; ledger = relations['eligibility_ledger']
    rows = ledger['rows']; records = relations['records']
    require(len(rows) == len(records) == 100 and len({r['literal_alias'] for r in rows}) == 100 and
            sorted(r['literal_alias'] for r in rows if r['reference_eligibility'] == 'ELIGIBLE') == market['symbols'] and
            sorted(r['literal_alias'] for r in records if r['eligible_for_C'] is True) == market['symbols'],
            'REFERENCE_C_ALL100_COVERAGE')
    result = []
    by_alias = {r['literal_alias']: r for r in records}
    for row in rows:
        flags = row['source_flags']; require(flags == by_alias[row['literal_alias']]['source_flags'], 'REFERENCE_C_FLAG_JOIN')
        result.append({'alias': row['literal_alias'], 'eligibility': row['reference_eligibility'],
            'reason_codes': row['eligibility_reason_codes'], 'source_record_ids': row['source_record_ids'],
            'source_complete': flags['source_complete'], 'raw_overlap_compared': flags['raw_overlap_compared'],
            'paired_dates': flags['paired_dates'], 'common_bar_consistency': flags['common_bar_consistency'],
            'action_status': flags['action_check_status'], 'timing_status': flags['timing_status'],
            'economic_mapping_status': flags['economic_mapping_status'],
            'scientific_eligibility': flags['scientific_eligibility'],
            'financial_result': 'MODELED_CONDITIONAL_COHORT' if row['reference_eligibility'] == 'ELIGIBLE' else
                                'NOT_EVALUATED_FOR_FIXED_CONDITIONAL_COHORT'})
    if retained:
        require(sum(r['source_complete'] is True for r in result) == 55 and
                all(r['action_status'] == 'UNAVAILABLE_NO_MATCHED_ACTION_BOUNDARY_ROWS' and
                    r['timing_status'] == 'OBSERVED_NULL_CURRENT_VINTAGE_ASOF_MAPPING_ONLY' and
                    r['economic_mapping_status'] == 'NOT_ADMITTED_SOURCE_ALIAS_ONLY' for r in result),
                'REFERENCE_C_COVERAGE_COUNTS')
    return {'schema': 'polar.reference-C-coverage/1', 'rows': result,
            'source_relations_sha256': market['source_relations_ref']['sha256'], 'economic_security_N50': 'NOT_ESTABLISHED'}
