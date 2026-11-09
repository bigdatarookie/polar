"""Fixed-R0 descriptive metadata projection; no economic admission or price reads."""
from collections import Counter
from datetime import date
import hashlib
import os
from pathlib import Path

from .codec import canonical, digest
from .hyp003_availability import R0_SHA, GRID_SHA, PART_LIMIT, reference
from .hyp003_source import (Sources, check, decode, member_stream, relative,
                            safe_root, JSON_LIMIT, NDJSON_LIMIT, LINE_LIMIT)
from .history_store import fsync_directory

PROTOCOL = 'HYP003_R0_SOURCE_OBSERVABILITY_V028_V1'
STATES = ('OBSERVED_SOURCE_ROWS', 'CONFLICTING', 'COMPLETE_EMPTY',
          'MISSING_WITHIN_COMPLETE_REQUEST', 'PARTIAL_OR_UNKNOWN', 'UNREQUESTED')
APPLICABILITY = ('PROVEN_EXPECTED', 'PROVEN_NOT_APPLICABLE', 'UNKNOWN_APPLICABILITY')
PARENT_SHA = '18ab8b49be41764bd41e8a66b763536efbf4b4dac98241ff66463c8530d2ae6f'
LEDGER_SHA = 'fd092b3f866c5077bb2f75b00ef457e7d1b4133b62da00756a824aa1ac097cde'
INPUT_SHA = '314b9258df9bcd12c2acb0c3f8d4855dc84b25cc67a67f53090c8297e499322b'
FITNESS = {
    'economic_identity_share_episode': {'status': 'UNKNOWN', 'reason': 'NO_ADOPTED_EPISODE_PROOF'},
    'class_continuity': {'status': 'UNKNOWN', 'reason': 'NO_ADOPTED_CONTINUITY_PROOF'},
    'raw_field_unit_feed_currency_action_basis': {'status': 'UNKNOWN', 'reason': 'DECLARED_PROFILE_IS_NOT_QUALIFICATION'},
    'decision_time_eligibility': {'status': 'NOT_QUALIFIED', 'reason': 'NO_BOUND_DECISION_K_RULE'},
    'economic_schedule_windows_guards': {'status': 'UNBOUND', 'reason': 'REFERENCE_DATES_ARE_NOT_ECONOMIC_SCHEDULE'},
}


def vector(counts):
    return {state: counts[state] for state in STATES}


def table(counts):
    return {'positions': vector(counts), 'declared_field_slot_equivalents':
            {state: 3 * counts[state] for state in STATES}}


def rows(root, name, expected, limit):
    """One bounded, descriptor-safe pass. Hash the exact bytes being interpreted."""
    hasher = hashlib.sha256(); size = 0
    with member_stream(root, relative(name), limit) as stream:
        while raw := stream.readline(LINE_LIMIT + 1):
            check(len(raw) <= LINE_LIMIT, 'HYP003_LINE_LIMIT')
            size += len(raw); check(size <= limit, 'HYP003_MEMBER_LIMIT_OR_TYPE')
            hasher.update(raw); value = decode(raw)
            check(type(value) is dict, 'HYP003_NDJSON_ROW_SCHEMA')
            yield value
    check(expected == {'bytes': size, 'sha256': hasher.hexdigest()}, 'HYP003_MEMBER_HASH_OR_LENGTH')


def write_observability(config, output_dir):
    check(type(config) is dict and set(config) == {'schema', 'mode', 'availability_ref',
          'population_ref', 'grid_ref', 'ledger_ref', 'evidence_refs'} and
          config['schema'] == 'polar.hyp003-observability-config/1' and
          config['mode'] in ('INVENTED', 'RETAINED') and len(canonical(config)) <= 65536,
          'HYP003_OBSERVABILITY_CONFIG')
    inputs = {}; values = {}
    for key in ('availability_ref', 'population_ref', 'grid_ref', 'ledger_ref'):
        values[key], inputs[key] = reference(config[key], NDJSON_LIMIT if key == 'population_ref' else JSON_LIMIT)
    parent = decode(values['availability_ref']); ledger = decode(values['ledger_ref'])
    parent_core = dict(parent); rev = parent_core.pop('revision', None)
    check(parent_core.get('schema') == 'polar.hyp003-source-availability-content/1' and
          rev == 'hyp003availability-' + digest(parent_core), 'HYP003_AVAILABILITY_IDENTITY')
    check(type(config['evidence_refs']) is list and 1 <= len(config['evidence_refs']) <= 16,
          'HYP003_OBSERVABILITY_EVIDENCE')
    evidence = []
    for ref in config['evidence_refs']:
        _, pin = reference(ref, JSON_LIMIT); evidence.append(pin)
    if config['mode'] == 'RETAINED':
        check([inputs[k]['sha256'] for k in ('availability_ref', 'population_ref', 'grid_ref', 'ledger_ref')]
              == [PARENT_SHA, R0_SHA, GRID_SHA, LEDGER_SHA] and INPUT_SHA in [p['sha256'] for p in evidence],
              'HYP003_OBSERVABILITY_FIXED_SCOPE')
    population = values['population_ref']; grid = decode(values['grid_ref'])['all']
    check(type(population) is list and 1 <= len(population) <= 3514 and type(grid) is list
          and 1 <= len(grid) <= 1008 and len(set(grid)) == len(grid), 'HYP003_OBSERVABILITY_SCOPE')
    for day in grid:
        check(type(day) is str and date.fromisoformat(day).isoformat() == day
              and day < '2023-09-01', 'HYP003_OBSERVABILITY_GRID')
    check(grid == sorted(grid), 'HYP003_OBSERVABILITY_GRID')
    ids = [r.get('population_record_id') for r in population]
    check(all(type(rid) is str and rid for rid in ids) and len(set(ids)) == len(ids), 'HYP003_OBSERVABILITY_POPULATION')
    check(parent['population'] == inputs['population_ref'] and parent['grid'] == inputs['grid_ref']
          and parent['records'] == len(ids) and parent['reference_dates'] == len(grid)
          and parent['source_record_date_slots'] == len(ids)*len(grid), 'HYP003_OBSERVABILITY_PARENT_SCOPE')
    parent_root = Path(config['availability_ref']['path']).parent
    ledger_root = Path(config['ledger_ref']['path']).parent
    check(ledger.get('schema') == 'polar.derived-artifact-manifest/1', 'HYP003_OBSERVABILITY_LEDGER')
    ledger_grid_raw, _ = Sources().read(ledger_root, 'reference-grid.json', JSON_LIMIT, ledger['files']['reference-grid.json'])
    ledger_grid = decode(ledger_grid_raw)
    check(ledger_grid['all'] == grid and ledger_grid['fields'] == ['raw_open', 'raw_close', 'raw_volume'],
          'HYP003_OBSERVABILITY_LEDGER_GRID')
    ledger_rows = rows(ledger_root, 'ledger.ndjson', ledger['files']['ledger.ndjson'], NDJSON_LIMIT)
    index = rows(parent_root, 'population-index.ndjson', parent['objects']['population-index.ndjson'], NDJSON_LIMIT)
    root = Path(output_dir); check(root.is_absolute(), 'HYP003_ABSOLUTE_OUTPUT_REQUIRED')
    check(all(not (p/'.git').exists() for p in (root, *root.parents)), 'HYP003_OUTPUT_INSIDE_REPOSITORY')
    safe_root(root.parent); check(not root.exists(), 'HYP003_OBSERVABILITY_OUTPUT_EXISTS'); root.mkdir(mode=0o700)
    objects = {}

    def emit(name, iterable):
        target = root/name; hasher = hashlib.sha256(); size = 0
        with target.open('xb') as stream:
            for raw in iterable:
                size += len(raw); check(size <= NDJSON_LIMIT, 'HYP003_OBSERVABILITY_OUTPUT_LIMIT')
                stream.write(raw); hasher.update(raw)
            stream.flush(); os.fsync(stream.fileno())
        target.chmod(0o400); fsync_directory(root)
        objects[name] = {'bytes': size, 'sha256': hasher.hexdigest()}

    totals = Counter(); dates = [Counter() for _ in grid]; joint = Counter()
    profile_states = Counter(); observations = Counter(); coverage = Counter(); pointers = Counter()
    used = set(); strata = {(d[:4]+'-Q'+str((int(d[5:7])-1)//3+1), decile,
              'WARMUP' if d < '2020-09-01' else 'STUDY') for d in grid for decile in [str(n) for n in range(1,11)]+['UNKNOWN']}

    def record_summaries():
        for ordinal, original in enumerate(population):
            record = next(index, None); adopted = next(ledger_rows, None); rid = ids[ordinal]
            check(type(record) is dict and record['ordinal'] == ordinal and record['source_record'] == original,
                  'HYP003_OBSERVABILITY_INDEX_JOIN')
            check(type(adopted) is dict and adopted['ordinal'] == ordinal and adopted['population_record_id'] == rid
                  and adopted['frozen_R0_record'] == original and adopted['adopted_exceptions'] == []
                  and adopted['intervals'] == [{'from_grid_index': 0, 'to_grid_index_exclusive': len(grid), 'state': 'EXPECTED_DEFAULT'}],
                  'HYP003_OBSERVABILITY_ADOPTED_LEDGER')
            raw_decile = original.get('acquisition_decile')
            decile = str(raw_decile) if type(raw_decile) is int and 1 <= raw_decile <= 10 else 'UNKNOWN'
            name = relative(record['availability_member'])
            check(name.startswith('availability/') and name not in used and name in parent['objects'],
                  'HYP003_OBSERVABILITY_MEMBER_JOIN'); used.add(name)
            counts = Counter(); n = 0
            for cell in rows(parent_root, name, parent['objects'][name], PART_LIMIT):
                check(n < len(grid) and cell['population_record_id'] == rid and cell['reference_date'] == grid[n]
                      and cell['state'] in STATES, 'HYP003_OBSERVABILITY_CELL_JOIN')
                day = grid[n]; state = cell['state']; counts[state] += 1; totals[state] += 1; dates[n][state] += 1
                quarter = day[:4]+'-Q'+str((int(day[5:7])-1)//3+1)
                joint[(quarter, decile, 'WARMUP' if day < '2020-09-01' else 'STUDY', state)] += 1
                check(type(cell['profile_states']) is list and type(cell['observations']) is list, 'HYP003_OBSERVABILITY_DIAGNOSTICS')
                for fact in cell['profile_states']:
                    profile_states[(fact['source_manifest_sha256'], fact['profile_id'], fact['state'])] += 1
                for fact in cell['observations']:
                    observations[(fact['source_manifest_sha256'], fact['profile_id'])] += 1
                    pointers[fact['pointer_status']] += 1
                n += 1
            check(n == len(grid), 'HYP003_OBSERVABILITY_RECORD_CONSERVATION')
            for fact in record['coverage']:
                coverage[canonical(fact).decode()] += 1
            yield canonical({'ordinal': ordinal, 'population_record_id': rid, 'acquisition_decile': raw_decile,
                  'decile_stratum': decile, 'date_count': n, **table(counts),
                  'applicability': {'UNKNOWN_APPLICABILITY': n, 'PROVEN_EXPECTED': 0, 'PROVEN_NOT_APPLICABLE': 0},
                  'ASSUMED_EXPECTED_DEFAULT': n, 'fitness': FITNESS}) + b'\n'
        check(next(index, None) is None and next(ledger_rows, None) is None, 'HYP003_OBSERVABILITY_INDEX_CONSERVATION')
        check(used == {name for name in parent['objects'] if name.startswith('availability/')}, 'HYP003_OBSERVABILITY_MEMBER_JOIN')
    emit('records.ndjson', record_summaries())
    check(vector(totals) == vector(Counter(parent['states'])) and sum(totals.values()) == len(ids)*len(grid)
          and all(sum(c.values()) == len(ids) for c in dates), 'HYP003_OBSERVABILITY_CONSERVATION')
    emit('dates.ndjson', (canonical({'reference_date': day, 'record_count': len(ids), **table(c)})+b'\n' for day,c in zip(grid,dates)))

    def joint_rows():
        for quarter,decile,scope in sorted(strata):
            for state in STATES:
                count = joint[(quarter,decile,scope,state)]
                for applicability in APPLICABILITY:
                    for default in (False,True):
                        n = count if applicability == 'UNKNOWN_APPLICABILITY' and default else 0
                        yield canonical({'quarter':quarter,'decile':decile,'date_scope':scope,'source_state':state,
                              'applicability':applicability,'ASSUMED_EXPECTED_DEFAULT':default,
                              'positions':n,'declared_field_slot_equivalents':3*n})+b'\n'
    check(sum(joint.values()) == sum(totals.values()), 'HYP003_OBSERVABILITY_CONSERVATION')
    emit('joint.ndjson', joint_rows())
    emit('diagnostics.json', [canonical({'unit_warning':'OVERLAPPING_COUNTS_NOT_DENSE_POSITIONS',
        'profile_date_occurrences':[{'source_manifest_sha256':k[0],'profile_id':k[1],'state':k[2],'count':v} for k,v in sorted(profile_states.items())],
        'observation_occurrences':[{'source_manifest_sha256':k[0],'profile_id':k[1],'count':v} for k,v in sorted(observations.items())],
        'pointer_status_occurrences':dict(sorted(pointers.items())),
        'coverage_facts':[{'fact':decode(k),'record_occurrences':v} for k,v in sorted(coverage.items())]})])
    total = sum(totals.values()); absent = total-totals['OBSERVED_SOURCE_ROWS']-totals['CONFLICTING']
    summary = {'scope':'FIXED_R0_SOURCE_RECORD_DATE_EVIDENCE_ONLY', 'positions':total,
        'declared_field_slot_equivalents':3*total, 'source_states':table(totals),
        'applicability':{'UNKNOWN_APPLICABILITY':total,'PROVEN_EXPECTED':0,'PROVEN_NOT_APPLICABLE':0},
        'ASSUMED_EXPECTED_DEFAULT':total,'applicability_reason':'NO_ADOPTED_PROOF_IN_THIS_PACKET_NOT_GLOBAL_ABSENCE',
        'fitness':FITNESS,'applicable_denominator':{'status':'NOT_IDENTIFIED','bounds':[0,3*total]},
        'true_required_source_absent_field_slots':{'status':'NOT_IDENTIFIED','logical_bounds':[0,3*absent]},
        'unusable_required_field_slots':{'status':'NOT_IDENTIFIED','logical_bounds':[0,3*total]},
        'positive_denominator_coverage':{'status':'UNKNOWN','logical_bounds':[0,1],'proven_zero_denominator':'N/A'},
        'unavailable_predicates': ['economic_episode_applicability','field_specific_fitness','decision_schedule',
            '253_close_window','63_DV_window','formation_eligibility','ranks','held_terminal_obligations','all_13026_T_status_exclusions'],
        'inherited_context': {'status':'PUBLISHED_NOT_REMEASURED_NOT_IN_DENSE_TOTALS',
            'unlinked_observations':1639 if config['mode']=='RETAINED' else None,
            'outside_grid_linked_observations':4707 if config['mode']=='RETAINED' else None},
        'broader_frame_context':{'original_T_source_records':13026, 'attribution':'INHERITED_SCIENTIFIC_PACKET_NOT_RECOUNTED',
            'all_T_status_exclusion_explanation':'UNBOUND_NOT_DISCHARGED_BY_FIXED_R0'},
        'historical_default99_failure':'PRESERVED_NOT_AN_ECONOMIC_COVERAGE_ESTIMATE',
        'financial':'NOT_RUN','original_HYP003_admission':'NOT_ESTABLISHED'}
    emit('summary.json',[canonical(summary)])
    code = {n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in
            ('hyp003_observability.py','hyp003_observability_schema.json','hyp003_availability.py','hyp003_source.py','codec.py','cli.py')}
    manifest = {'schema':'polar.hyp003-observability-content/1','protocol':PROTOCOL,'mode':config['mode'],
        'inputs':inputs,'evidence':sorted(evidence,key=lambda p:p['sha256']),'parent_revision':rev,
        'scientific_contract':{
            'packet_sha256':'51d0272bdf2db4afb24ffa9fb8e5356d88f630775d4d2a56dfd0a08b897c8f88',
            'proposal_sha256':'804b65e373c772a97e9f7af47d64f37e1a99e4e59bd3057c4e8420a25ceaa77e',
            'input_binding_sha256':INPUT_SHA,
            'validator_review_sha256':'ae7f05cd577e35245bc7f2c8d02093500daffc65c976f23156a71af54fa8d490'},
        'objects':dict(objects),'code':code,'records':len(ids),'dates':len(grid),'positions':total,
        'physical_exclusions':['output_dir','input_paths','attempt_time','receipt'],
        'integrity_scope':'PINNED_PARENT_IDENTITY_AND_SELECTED_METADATA_MEMBERS;PRIOR_RAW_GRAPH_RECEIPTS_REUSED'}
    manifest['revision'] = 'hyp003observability-'+digest(manifest)
    # Physical receipt cannot enter semantic identity; terminal marker is last.
    emit('physical-receipt.json',[canonical({'input_paths':config,'output_dir':str(root),
         'revision':manifest['revision']})])
    emit('content-manifest.json',[canonical(manifest)])
    return manifest
