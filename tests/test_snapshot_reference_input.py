"""Public invented single-symbol snapshots; no retained source payloads."""
import json
from copy import deepcopy
from pathlib import Path
import pytest
from test_reference_input import put
from test_selected_reference_input import selected_fixture
from polar.reference_input import prepare_input
from polar.snapshot_reference_input import PROFILE
from polar.research_reference import load_reference
from polar.history_bundle import sha


def fixture(tmp_path, mutate=None):
    parent=tmp_path/'parent';parent.mkdir()
    root,cfg,_,_=selected_fixture(parent,targets=['SHY'])
    native=prepare_input(cfg,root,10**8)['input_ref']
    days=[r['date'] for r in json.loads(Path(cfg['schedule']['path']).read_bytes())['rows']]
    bars=[{'t':d+'T05:00:00Z','c':12.125} for d in days]
    plan={'mode':'INVENTED','method':'GET','request_url_without_credentials':'https://data.alpaca.markets/v2/stocks/TEST/bars?timeframe=1Day&feed=sip&currency=USD&adjustment=all&sort=asc'}
    if mutate:mutate(bars,plan)
    raw=put(tmp_path/'raw.json',{'symbol':'TEST','bars':bars,'next_page_token':None})
    planpin=put(tmp_path/'plan.json',plan)
    receipt=put(tmp_path/'receipt.json',{'http_status':200,'body_complete_under_cap':True,
        'next_page_token_present':False,'transport_error_class':None,'plan_sha256':planpin['sha256'],
        'body_sha256':raw['sha256']})
    lex=json.loads(Path(raw['path']).read_bytes(),parse_int=str,parse_float=str)
    selected=tmp_path/'selected.ndjson'
    selected.write_text(''.join(json.dumps({'symbol':'TEST','aggregation_label':r['t'][:10],
        'adjusted_reference_close_token':r['c']})+'\n' for r in lex['bars']))
    sp={'path':str(selected),'sha256':sha(selected.read_bytes())}
    definition=put(tmp_path/'definition.json',{'schema':'invented-definition/1','unknowns':['HISTORICAL_PIT','INVESTOR_TOTAL_RETURN']})
    question=put(tmp_path/'question.json',{'schema':'invented-question/1'})
    # Original source pins in this disposition use the same path+hash contract.
    qualification=put(tmp_path/'qualification.json',{'status':'COMPATIBLE_FOR_FROZEN_COHORT_VENDOR_REFERENCE_SEMANTICS_WITH_LIMITS',
        'compatibility':{'per_source_basis':{'adjustment':'all','selected_field':'c','timeframe':'1Day','feed':'sip','currency':'USD'}},
        'source_pins':{k:{a:p[a] for a in ('path','sha256')} for k,p in
            {'parent':native,'raw':raw,'selected':sp,'receipt':receipt,'definition':definition}.items()}})
    return root,{'schema':'polar.reference-input-conversion-config/8','profile_id':PROFILE,'namespace':'INVENTED',
        'inputs':[native],'captures':[{'symbol':'TEST','plan':planpin,'receipt':receipt,'raw':raw,
        'selected':sp,'source_definition':definition}], 'qualification':qualification,'consumer_question':question,
        'schedule':cfg['schedule'],'date_range':cfg['date_range']}


def test_lossless_union_and_native_reader(tmp_path):
    root,cfg=fixture(tmp_path)
    result=prepare_input(cfg,root,10**8)
    assert prepare_input(cfg,root,10**8)==result
    market=load_reference(result['input_ref'])
    assert market['symbols']==['SHY','TEST']
    for day in market['dates']:
        assert market['prices_micro'][day]['TEST']==12125000
        evidence=market['source_evidence'][day]['TEST']
        assert evidence['observed_published_at'] is None
        assert evidence['source_ref']['kind']=='CAPTURED_SINGLE_SYMBOL_ALL_ADJUSTED_SOURCE'
    relation=next(iter(market['source_relations']['single_symbol_captures'].values()))
    assert relation['source_definition']==cfg['captures'][0]['source_definition']
    assert relation['qualification']==cfg['qualification']
    manifest=json.loads(Path(result['input_ref']['path']).read_bytes())
    assert manifest['conversion_metadata']['source_qualification']==cfg['qualification']


@pytest.mark.parametrize('case,error',[('raw','REQUEST'),('duplicate','DUPLICATE_DATE'),
    ('negative','LOSSLESS_6DP_REQUIRED'),('scale','LOSSLESS_6DP_REQUIRED'),('namespace','NAMESPACE'),('unqualified','QUALIFIED_BINDING'),
    ('token','EXACT_TOKEN'),('grid','GRID')])
def test_rehashed_invalid_snapshot_never_publishes(tmp_path,case,error):
    def mutate(bars,plan):
        if case=='raw':plan['request_url_without_credentials']=plan['request_url_without_credentials'].replace('adjustment=all','adjustment=raw')
        if case=='duplicate':bars[1]['t']=bars[0]['t']
        if case=='negative':bars[0]['c']=-1
        if case=='scale':bars[0]['c']=1.1234567
        if case=='namespace':plan.pop('mode')
        if case=='grid':bars.pop()
    root,cfg=fixture(tmp_path,mutate)
    if case=='unqualified':
        q=json.loads(Path(cfg['qualification']['path']).read_bytes());q['source_pins'].pop('raw')
        cfg['qualification']=put(tmp_path/'bad-qualification.json',q)
    if case=='token':
        selected=Path(cfg['captures'][0]['selected']['path']);lines=selected.read_text().splitlines()
        row=json.loads(lines[0]);row['adjusted_reference_close_token']='99.0';lines[0]=json.dumps(row)
        selected.write_text('\n'.join(lines)+'\n');cfg['captures'][0]['selected']['sha256']=sha(selected.read_bytes())
        q=json.loads(Path(cfg['qualification']['path']).read_bytes());q['source_pins']['selected']=cfg['captures'][0]['selected']
        cfg['qualification']=put(tmp_path/'rehashed-qualification.json',q)
    before=set((root/'reference-inputs').iterdir())
    with pytest.raises(ValueError,match=error):prepare_input(cfg,root,10**8)
    assert set((root/'reference-inputs').iterdir())==before
