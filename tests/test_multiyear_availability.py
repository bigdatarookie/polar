"""Invented source-format controls only; no retained source or transport calls."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from polar.codec import canonical
from polar.hyp003_source import Sources,PreparationError,MULTIYEAR,RAW
from polar.hyp003_availability import write_availability,read_availability


def put(root,name,value,ndjson=False):
    raw=b''.join(canonical(row)+b'\n' for row in value) if ndjson else canonical(value)
    (root/name).write_bytes(raw)
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def fixture(tmp_path):
    source=tmp_path/'source';source.mkdir()
    body_hashes=['a'*64,'b'*64]
    profiles=[{'symbol':'A.B','request_ordinal':i,'chunk_index':i,'start':start,'end':end,
               'expected_dates':[start,end],'parameters':{'symbols':'A.B','start':start+'T00:00:00Z',
                    'end':end+'T23:59:59Z','adjustment':'raw','feed':'sip','currency':'USD'}}
              for i,(start,end) in enumerate([('2020-01-01','2020-01-01'),('2020-01-02','2020-01-03')])]
    rows=[]
    for ordinal,day in [(0,'2020-01-01'),(1,'2020-01-03'),(0,'2019-12-31')]:
        rows.append({'source_symbol':'A.B','reference_date':day,'request_ordinal':ordinal,
            'chunk_index':ordinal,'source_array':'bars.A.B','source_row_ordinal':len(rows),
            'source_body_sha256':body_hashes[ordinal],
            'raw_fields_exact_tokens':{'o':'2','h':'3','l':'1','c':'2','v':'0'},
            'adjustment':'raw','feed':'sip','currency':'USD_REQUEST_CONTRACT',
            'observed_historical_available_at':None,'observed_published_at':None,
            'quality_reasons':['SOURCE_DECLARED_NOTE'],'mapping_status':'UNVERIFIED',
            'economic_security_id':None,'causal_K':'NOT_DERIVED','aggregation_label':day+'T05:00:00Z'})
    objects={'bars.ndjson':put(source,'bars.ndjson',rows,True),
             'source-profiles.json':put(source,'source-profiles.json',profiles),
             'quality.json':put(source,'quality.json',{'chunks':[{'request_ordinal':0,'source_coverage_status':'DATA_RETURNED_COVERAGE_CHECKED'},
                           {'request_ordinal':1,'source_coverage_status':'PARTIAL_PAGE_TOKEN'}]})}
    manifest={'schema':MULTIYEAR,'objects':objects,'source_objects':[
        {'request_ordinal':i,'bytes':123,'sha256':h} for i,h in enumerate(body_hashes)]}
    ref=put(source,'content-manifest.json',manifest)
    links={'schema':'polar.hyp003-multiyear-source-record-links/1','links':[
        {'population_record_id':'literal-record-1','source_symbol':'A.B','source_manifest_sha256':ref['sha256']}]}
    linkref=put(tmp_path,'links.json',links)
    popref=put(tmp_path,'population.ndjson',[{'population_record_id':'literal-record-1','literal_symbol':'A.B'},
        {'population_record_id':'literal-record-2','literal_symbol':'B'}],True)
    gridref=put(tmp_path,'grid.json',{'all':['2020-01-01','2020-01-02','2020-01-03'],'note':'REFERENCE_ONLY'})
    config={'schema':'polar.hyp003-availability-config/1','mode':'INVENTED',
        'population_ref':{'path':str(tmp_path/'population.ndjson'),'sha256':popref['sha256']},
        'grid_ref':{'path':str(tmp_path/'grid.json'),'sha256':gridref['sha256']},'inputs':[
        {'directory':str(source),'manifest':'content-manifest.json','manifest_sha256':ref['sha256'],
         'links_ref':{'path':str(tmp_path/'links.json'),'sha256':linkref['sha256']}}]}
    return config,rows,profiles


def lines(root,name):return [json.loads(line) for line in (root/name).read_bytes().splitlines()]


def test_multiyear_preserves_profile_pointer_quality_nulls_and_outside_grid(tmp_path):
    cfg,rows,_=fixture(tmp_path);out=tmp_path/'output';write_availability(cfg,out)
    report=read_availability(out);assert report['source_rows']==3 and report['financial']=='NOT_RUN'
    observations=lines(out,'rows/00000/00000.ndjson')
    assert len(observations)==3  # Not duplicated across the two same-alias chunks.
    assert {r['reference_date'] for r in observations}=={r['reference_date'] for r in rows}
    assert all(r['pointer_status']=='REFERENCED_ONLY' for r in observations)
    assert observations[0]['source_reference']['source_array']=='bars.A.B'
    assert observations[0]['source_metadata']['quality_reasons']==['SOURCE_DECLARED_NOTE']
    assert observations[0]['clocks']['observed_historical_available_at'] is None
    assert observations[0]['field_positions']['volume']['body_token_supplied'] is True
    assert observations[0]['field_positions']['volume']['normalized_supplied'] is False
    pop=lines(out,'population-index.ndjson')[0]
    assert len(pop['coverage'])==2
    assert all(f['profile_binding']=='DECLARED_NOT_VERIFIED' and f['transport_state']=='UNKNOWN'
               and f['canonical_job_id'] is None and f['source_plan_job_id'] is None for f in pop['coverage'])
    assert pop['coverage'][1]['producer_coverage_states']==['PARTIAL_PAGE_TOKEN']
    cells=lines(out,'availability/00000.ndjson')
    assert cells[-1]['state']=='OBSERVED_SOURCE_ROWS'
    assert cells[-1]['profile_states'][1]['state']=='UNKNOWN'  # Inclusive producer end date.
    assert cells[1]['state']=='PARTIAL_OR_UNKNOWN'  # Not complete-empty or unreceived.


def test_default_preparation_does_not_admit_multiyear(tmp_path):
    cfg,_,_=fixture(tmp_path);entry=cfg['inputs'][0]
    with pytest.raises(PreparationError,match='HYP003_UNSUPPORTED_ADAPTER'):
        Sources().add({'adapter':MULTIYEAR,**{k:v for k,v in entry.items() if k!='links_ref'}},True)


@pytest.mark.parametrize('fault',['missing','revision','alias','duplicate'])
def test_multiyear_requires_exact_explicit_unique_record_revision_link(tmp_path,fault):
    cfg,_,_=fixture(tmp_path);entry=cfg['inputs'][0]
    value=json.loads((tmp_path/'links.json').read_bytes())
    if fault=='missing':entry['links_ref']=None
    else:
        if fault=='revision':value['links'][0]['source_manifest_sha256']='f'*64
        if fault=='alias':value['links'][0]['source_symbol']='B'
        if fault=='duplicate':value['links'].append(copy.deepcopy(value['links'][0]))
        ref=put(tmp_path,'links.json',value);entry['links_ref']['sha256']=ref['sha256']
    with pytest.raises(PreparationError):write_availability(cfg,tmp_path/'output')
    assert not (tmp_path/'output/content-manifest.json').exists()


@pytest.mark.parametrize('fault',['body','request','chunk'])
def test_multiyear_row_cannot_borrow_wrong_profile(tmp_path,fault):
    cfg,rows,_=fixture(tmp_path);source=Path(cfg['inputs'][0]['directory'])
    if fault=='body':rows[0]['source_body_sha256']='f'*64
    if fault=='request':rows[0]['request_ordinal']=99
    if fault=='chunk':rows[0]['chunk_index']=99
    manifest=json.loads((source/'content-manifest.json').read_bytes())
    manifest['objects']['bars.ndjson']=put(source,'bars.ndjson',rows,True)
    revision=put(source,'content-manifest.json',manifest)['sha256'];cfg['inputs'][0]['manifest_sha256']=revision
    links=json.loads((tmp_path/'links.json').read_bytes());links['links'][0]['source_manifest_sha256']=revision
    cfg['inputs'][0]['links_ref']['sha256']=put(tmp_path,'links.json',links)['sha256']
    with pytest.raises(PreparationError,match='HYP003_MULTIYEAR_ROW_PROFILE'):write_availability(cfg,tmp_path/'output')


def test_multiyear_member_tamper_fails_before_terminal_publication(tmp_path):
    cfg,_,_=fixture(tmp_path);source=Path(cfg['inputs'][0]['directory'])
    (source/'quality.json').write_bytes(b'{}')
    with pytest.raises(PreparationError,match='HYP003_MEMBER_HASH_OR_LENGTH'):write_availability(cfg,tmp_path/'output')
    assert not (tmp_path/'output/content-manifest.json').exists()


def test_mixed_raw_and_multiyear_keep_old_record_semantics(tmp_path):
    cfg,rows,_=fixture(tmp_path);root=tmp_path/'raw';root.mkdir()
    row={**rows[0],'source_symbol':'B','reference_date':'2020-01-02',
         'source_reference':{'source_array':'bars/B','source_body_sha256':'c'*64,'source_row_ordinal':0}}
    manifest={'schema':RAW,'objects':{
        'bars.ndjson':put(root,'bars.ndjson',[row],True),
        'source-plan.json':put(root,'source-plan.json',{'unit':{'jobs':[]}}),
        'parent-coverage-ledger.ndjson':put(root,'parent-coverage-ledger.ndjson',[],True)}}
    ref=put(root,'content-manifest.json',manifest)
    linkref=put(tmp_path,'rawlinks.json',{'schema':'polar.hyp003-source-record-links/1','links':[
        {'population_record_id':'literal-record-2','source_symbol':'B','request':None,
         'canonical_job_id':None,'source_plan_job_id':None}]})
    cfg['inputs'].append({'directory':str(root),'manifest':'content-manifest.json','manifest_sha256':ref['sha256'],
                         'links_ref':{'path':str(tmp_path/'rawlinks.json'),'sha256':linkref['sha256']}})
    out=tmp_path/'output';write_availability(cfg,out)
    assert read_availability(out)['source_rows']==4
    cells=lines(out,'availability/00001.ndjson')
    assert cells[1]['state']=='OBSERVED_SOURCE_ROWS'
    raw_rows=lines(out,'rows/00001/00000.ndjson')
    assert len(raw_rows)==1 and 'source_metadata' not in raw_rows[0]
    assert raw_rows[0]['source_reference']['source_array']=='bars/B'
