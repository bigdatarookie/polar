"""Wholly invented /2 C54 source, all100 metadata, one fit and two short phases.

No retained quote, calendar payload, model, expected outcome or private locator.
"""
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from reference_fixture import fixture as base_fixture, write
from polar.gym_contract import sha
from polar.history_bundle import canonical
from polar.reference_c import INVENTED_C
from polar.reference_service import config_from_seed


def fixture(tmp_path, monkeypatch):
    store, base = base_fixture(tmp_path, monkeypatch)
    root = tmp_path.resolve(); symbols = ['X'+str(i).zfill(3) for i in range(54)]
    aliases = ['X'+str(i).zfill(3) for i in range(100)]
    days = [(date(2018, 1, 1)+timedelta(days=i)).isoformat() for i in range(600)]
    schedule = [{'date': d, 'reference_open_utc': d+'T14:30:00+00:00',
        'reference_close_utc': d+'T21:00:00+00:00', 'early_close_reference': False,
        'next_reference_date': days[i+1] if i+1<len(days) else None,
        'month_end_in_reference_range': days[i+1][:7] != d[:7] if i+1<len(days) else None}
        for i, d in enumerate(days)]
    sp = write(root/'c-schedule.json', {'schema':'polar.xnys-reference-schedule/1','rows':schedule})
    records=[]; ledger=[]; jobs={}; parents={}; parent_hashes={}
    for i, symbol in enumerate(aliases):
        flags = {'literal_alias':symbol, 'source_record_ids':['INVENTED-LISTING-'+symbol],
            'source_complete':i<55, 'raw_overlap_compared':i<54, 'paired_dates':12 if i<54 else 0,
            'common_bar_consistency':'POSITIVE_COMMON_BAR_SOURCE_CONSISTENCY' if i<54 else 'NOT_COMPARABLE',
            'action_check_status':'UNAVAILABLE_NO_MATCHED_ACTION_BOUNDARY_ROWS',
            'economic_mapping_status':'NOT_ADMITTED_SOURCE_ALIAS_ONLY',
            'timing_status':'OBSERVED_NULL_CURRENT_VINTAGE_ASOF_MAPPING_ONLY','scientific_eligibility':'NOT_SELECTED'}
        parent = {'job_id':'INVENTED-PLAN-'+symbol,'source_record_ids':flags['source_record_ids']}
        ph = sha(canonical(parent)); parents[ph]=parent; parent_hashes[symbol]=ph
        jobs['INVENTED-JOB-'+symbol] = {'parent_relation_sha256':ph,'request':{'symbols':symbol},
            'source_plan_job_id':parent['job_id'],'source_record_ids':flags['source_record_ids']}
        records.append({'literal_alias':symbol,'eligible_for_C':i<54,'source_flags':flags})
        ledger.append({'literal_alias':symbol,'source_record_ids':flags['source_record_ids'],'source_flags':flags,
            'reference_eligibility':'ELIGIBLE' if i<54 else 'INELIGIBLE_OR_UNKNOWN',
            'eligibility_reason_codes':[] if i<54 else ['INVENTED_INCOMPLETE_OR_UNPAIRED']})
    relations = {'schema':'polar.reference-source-relations/1', 'records':records,
        'eligibility_ledger':{'rows':ledger},'jobs':jobs,'parent_relations':parents}
    rp = write(root/'c-relations.json', relations)
    raw=[]
    for i, d in enumerate(days):
        for j, s in enumerate(symbols):
            token = f'{10+i//100}.{i%100:02d}{j%10}{(i*(j+1))%10}00'
            raw.append(canonical({'symbol':s,'date':d,'reference_quote':token,'source_adjusted_close_token':token,
                'source_ref':{'normalized_member_sha256':'a'*64,'line_1based':i*54+j+1,'line_sha256':sha((s+d).encode()),
                    'query_symbol':s,'source_symbol':s,'parent_relation_sha256':parent_hashes[s],
                    'original_source_reference':{'raw_file':'INVENTED.json','source_body_sha256':'b'*64,
                        'source_array':'bars/'+s,'source_row_ordinal':i,'job_id':'INVENTED-JOB-'+s,
                        'request_id':None,'page':0 if i==0 else 1}},
                'observed_published_at':None,'observed_historical_available_at':None})+b'\n')
    qpath=root/'c-quotes.ndjson';qpath.write_bytes(b''.join(raw))
    qp={'path':str(qpath),'sha256':hashlib.sha256(qpath.read_bytes()).hexdigest(),'bytes':qpath.stat().st_size}
    manifest = {'schema':'polar.synthetic-reference-source-input/2','quote_basis':'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE',
        'unit_type':'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE','double_action_policy':'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL',
        'symbols':symbols,'dates':{'count':600,'start':days[0],'end':days[-1]},'rows':600*54,
        'schedule':sp,'quotes':qp,'source_relations':rp,'source_members':[{'sha256':'a'*64}],
        'parent_dataset_revision':'INVENTED-C54-PUBLIC','rights':'INVENTED_PUBLIC_TEST',
        'provenance':{'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'}}
    mp=write(root/'c-manifest.json',manifest)
    contract={'schema':'polar.prospective-calendar-contract/1','source_schedule':sp,'reference_dates':600,
        'start':days[0],'end':days[-1],'training_cycles':[{'signal':days[i],'entry':days[i+1],'exit':days[i+22]} for i in (252,274)],
        'training_rows':108,'training_reference_aliases':54,'validation_bounds':[days[333],days[423]],
        'final_bounds':[days[423],days[599]]}
    for phase,lo,hi in [('validation',333,423),('final',423,599)]:
        count=sum(r['month_end_in_reference_range'] is True and days[lo]<=r['date']<days[hi]
                  and r['next_reference_date']<days[hi] for r in schedule)
        contract.update({phase+'_nav':hi-lo+1,phase+'_returns':hi-lo,
                         phase+'_complete_origins':count-1,phase+'_label_rows':(count-1)*54})
    cp=write(root/'c-calendar.json',contract)
    pp=write(root/'c-protocol.json',{'schema':'polar.invented-reference-protocol/1','profile_id':INVENTED_C,
        'classification':'INVENTED','fit_event':days[310]+'T00:00:30+00:00','calendar_sha256':cp['sha256'],
        'timezone_sha256':base['timezone_ref']['sha256'],'input_sha256':mp['sha256']})
    config=config_from_seed({'namespace':'INVENTED','profile_id':INVENTED_C,'protocol_path':pp['path'],
        'input_path':mp['path'],'calendar_path':cp['path'],'timezone_path':base['timezone_ref']['path'],
        'code_revision':base['code_revision'],'runtime_image_id':base['runtime_image_id'],
        'candidate_id':'INVENTED-C54','experiment_id':'INVENTED-C54-ONE-FIT'})
    return store,config
