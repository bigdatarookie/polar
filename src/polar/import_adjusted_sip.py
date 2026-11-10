"""Finite vendor-all-adjusted profile for the existing evidence-first executor."""
import re
from .import_contract import canonical,decode,digest,sha,require,exact

PROFILE='all-adjusted100'
ADAPTER='alpaca-all-adjusted-sip-broad100/1'
SCOPE_SHA='d123cb78e0e1e5e091bbc6de04e1693ebc08181775eb72ebe3434fd89d21c077'
CREDENTIAL='/Users/garry/Documents/git/polar/.artifacts/alpaca-api-credentials.json'
POLICY={'schema':'polar.adjusted-sip-policy/1','basis':'INTERNAL_BROAD100_ALL_ADJUSTED_REFERENCE',
 'jobs':100,'gets':200,'pages':2,'body_bytes':1048576,'total_bytes':209715200,
 'wall_seconds':1800,'spacing_seconds':1,'request_seconds':45,'retries':0,'redirects':False,
 'additional_bytes':2*1024**3,'partition_bytes':16*1024**2,
 'materialization_reserve_seconds':120,'terminal_reserve_bytes':64*1024**2}
TEMPLATE={'endpoint':'https://data.alpaca.markets/v2/stocks/bars','symbols':'ONE_LITERAL_ALIAS_PER_JOB',
 'adjustment':'all','feed':'sip','currency':'USD','timeframe':'1Day','asof':'2020-09-02',
 'limit':10000,'sort':'asc','start':'2016-01-04T00:00:00Z','end':'2026-11-07T00:00:00Z'}


def request(value):
    exact(value,tuple(TEMPLATE))
    require(type(value['symbols']) is str and re.fullmatch(r'[A-Za-z0-9._-]{1,40}',value['symbols'])
      and type(value['limit']) is int and {**value,'symbols':TEMPLATE['symbols']}==TEMPLATE,
      'IMPORT_REQUEST_SEMANTICS')
    return value


def unit(value,fixture):
    from .import_service import bound_file
    exact(value,('schema','adapter','mode','scope_ref','seed_refs'))
    require(value['schema']=='polar.adjusted-sip-import-config/1' and value['adapter']==ADAPTER,
            'IMPORT_POLICY_MISMATCH')
    raw=bound_file(value['scope_ref']);scope=decode(raw)
    require(fixture or sha(raw)==SCOPE_SHA,'IMPORT_SCOPE_MISMATCH')
    require(scope.get('schema')=='polar.v033-broad-acquisition-scope/1'
      and scope.get('request_template')==TEMPLATE,'IMPORT_SCOPE_MISMATCH')
    aliases=scope.get('aliases');rows=scope.get('source_records')
    require(type(aliases) is list and 0<len(aliases)<=100 and len(set(aliases))==len(aliases)
      and (fixture or len(aliases)==100) and type(rows) is list and bool(rows),'IMPORT_SCOPE_MISMATCH')
    require(all(type(v) is dict and v.get('literal_symbol') in aliases
      and type(v.get('population_record_id')) is str for v in rows),'IMPORT_SCOPE_MISMATCH')
    require(len({v['population_record_id'] for v in rows})==len(rows),'IMPORT_DUPLICATE_JOB')
    jobs=[]
    for ordinal,alias in enumerate(aliases):
        relations=[v for v in rows if v['literal_symbol']==alias]
        require(bool(relations),'IMPORT_SCOPE_MISMATCH')
        req=request({**TEMPLATE,'symbols':alias})
        jobs.append({'job_id':'literal-request-'+digest(req),'population_record_id':None,
          'request':req,'frozen_alias_ordinal':ordinal,'source_records':relations,
          'source_record_ids':[v['population_record_id'] for v in relations],
          'economic_identity_admission':'NOT_ISSUED'})
    return {'jobs':jobs,'scope_sha256':sha(raw),'scope_ref':value['scope_ref'],
      'lineage':{'new_adjustment_namespace':True,'raw_request_cache_equivalent':False,
                 'prior_attempts_preserved':True},'credentials':{'reference':CREDENTIAL},
      'basis':'VENDOR_ALL_ADJUSTED_REFERENCE_NEVER_RAW_SHARES_OR_CERTIFIED_TOTAL_RETURN'}


def source_row(row):
    """Relabel only the new profile; source lexical tokens and pointers stay exact."""
    row=dict(row)
    row['source_fields_exact_tokens']=row.pop('raw_fields_exact_tokens')
    for name in ('open','high','low','close','volume'):
        row['vendor_adjusted_'+name]=row.pop('raw_'+name)
    row.update(capture_origin='ALL_ADJUSTED_SIP_IMPORT_ADAPTER_V1',adjustment='all',
      price_basis='VENDOR_ALL_ADJUSTED_REFERENCE',
      volume_basis='VENDOR_RESPONSE_UNITS_ADJUSTMENT_ALL_NOT_RAW_SHARES',
      asof_semantics='REQUEST_ALIAS_MAPPING_NOT_HISTORICAL_VINTAGE',
      investor_total_return='NOT_ESTABLISHED',corporate_action_completeness='UNKNOWN',
      supplemental_reasons=['SOURCE_FITNESS_UNRESOLVED','VENDOR_ADJUSTMENT_MODEL_UNVERIFIED'])
    return row
