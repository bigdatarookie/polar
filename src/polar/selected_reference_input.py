"""Metadata-only selected-source purpose binding for the existing lossless converter."""
from .ci_research import require
from .research_reference import decode,pinned_bytes
from .import_adjusted_sip import selected_unit

PROFILE='SELECTED-ALL-ADJUSTED-REFERENCE-INPUT-V1'
RIGHTS='SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION'


def metadata(config):
    purpose=decode(pinned_bytes(config['purpose']));binding=decode(pinned_bytes(config['binding']))
    fields={'schema','source_collection','source_plan_id','source_config','acquisition_order','portfolio_symbol_order',
            'schedule','date_grid','date_range','consumer_protocol','source_acceptance','rights_source_refs','rights'}
    require(type(purpose) is dict and set(purpose)==fields and
            purpose['schema']=='polar.selected-reference-source-purpose/1','REFERENCE_SELECTED_PURPOSE')
    require(config['namespace'] in ('INVENTED','RETAINED') and purpose['date_range']==config['date_range'] and
            purpose['schedule']==config['schedule'],'REFERENCE_SELECTED_PURPOSE_GRID')
    source_config=decode(pinned_bytes(purpose['source_config']))
    invented=config['namespace']=='INVENTED'
    require(source_config.get('mode')==('fixture' if invented else 'provider'),'REFERENCE_SELECTED_SOURCE_MODE')
    unit=selected_unit(source_config,invented)  # Pure metadata validation; no plan or credential/provider call.
    targets=[j['request']['symbols'] for j in unit['jobs']]
    require(purpose['acquisition_order']==targets and purpose['portfolio_symbol_order']==sorted(targets),
            'REFERENCE_SELECTED_TARGET_ORDER')
    prefix='adjustedsipselectedfixture-' if invented else 'adjustedsipselected-'
    plan=purpose['source_plan_id']
    import re
    require(type(plan) is str and re.fullmatch(prefix+unit['scope_sha256']+'-[a-f0-9]{64}',plan),
            'REFERENCE_SELECTED_PLAN')
    require(type(binding) is dict and set(binding)=={'schema','source_collection','source_plan_id',
            'portfolio_symbol_order','records','rights','provenance'} and
            binding['schema']=='polar.selected-source-consumer-metadata-binding/1' and
            binding['source_collection']==purpose['source_collection'] and binding['source_plan_id']==plan and
            binding['portfolio_symbol_order']==purpose['portfolio_symbol_order'],'REFERENCE_SELECTED_BINDING')
    rights='INVENTED_PUBLIC_TEST' if invented else RIGHTS
    require(purpose['rights']==binding['rights']==rights,'REFERENCE_SELECTED_RIGHTS')
    if invented:
        require(binding['provenance']=={'kind':'DETERMINISTIC_INVENTED_FIXTURE'},
                'REFERENCE_INVENTED_POSITIVE_PROVENANCE_REQUIRED')
    else:
        require(binding['provenance']=={'kind':'OWNER_SELECTED_SOURCE_ONLY','historical_K':'UNKNOWN',
                'asof':'MAPPING_ONLY_NOT_VINTAGE','economic_identity_admission':'NOT_ISSUED'},
                'REFERENCE_SELECTED_PROVENANCE')
    require(type(purpose['rights_source_refs']) is list and 1<=len(purpose['rights_source_refs'])<=16,
            'REFERENCE_SELECTED_RIGHTS_REFS')
    for ref in purpose['rights_source_refs']:pinned_bytes(ref)
    for key in ('consumer_protocol','source_acceptance'):
        value=decode(pinned_bytes(purpose[key]))
        require(type(value) is dict,'REFERENCE_SELECTED_PURPOSE_REF')
    calendar=decode(pinned_bytes(purpose['date_grid']))
    require(type(calendar.get('dates')) is list and calendar.get('parent_schedule')==config['schedule'],
            'REFERENCE_SELECTED_DATE_GRID')
    records=binding['records'];by_symbol={j['request']['symbols']:j for j in unit['jobs']}
    require(type(records) is list and len(records)==len(targets) and
            [r.get('literal_alias') for r in records]==sorted(targets),'REFERENCE_SELECTED_RECORD_SET')
    for record in records:
        symbol=record['literal_alias'];job=by_symbol[symbol]
        require(record.get('selected_for_purpose') is True and 'eligible_for_C' not in record and
                record['source_plan_job_id']==job['job_id'] and record['request']==job['request'] and
                record['source_records']==[] and record['source_record_ids']==[],
                'REFERENCE_SELECTED_SOURCE_ONLY_RECORD')
    ledger={'schema':'polar.selected-source-purpose-membership/1','selected_aliases_fixed_order':sorted(targets)}
    return binding,sorted(targets),records,ledger,calendar['dates']
