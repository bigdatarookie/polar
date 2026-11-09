"""Focused invented PR38 identity regression; nonauthor review before invocation."""
import json

import pytest

from test_raw_sip_aggregate import setup,ref,execute,body,collection,index_config
from polar.import_raw_sip import job_id
from polar.hyp003_availability import write_availability
from polar.hyp003_source import PreparationError


def captured(tmp_path):
    service,cfg,jobs=setup(tmp_path/'capture',1);pid=service.plan(cfg)['plan_id']
    result=execute(service,pid,[body()]);source,_=collection(service,result)
    config=index_config(tmp_path,source,rows=[{'population_record_id':'record-0','literal_symbol':'INVENTED0'}])
    identity={'population_record_id':'record-0','source_symbol':'INVENTED0',
              'request':jobs[0]['request'],'canonical_job_id':job_id(jobs[0]['request']),
              'source_plan_job_id':jobs[0]['job_id']}
    return config,identity


@pytest.mark.parametrize('wrong_field',['canonical_job_id','source_plan_job_id'])
def test_mismatched_producer_identity_is_not_verified(tmp_path,wrong_field):
    config,identity=captured(tmp_path);identity[wrong_field]='wrong-id'
    config['inputs'][0]['links_ref']=ref(tmp_path,'links.json',{
        'schema':'polar.hyp003-source-record-links/1','links':[identity]})
    dest=tmp_path/'availability'
    with pytest.raises(PreparationError,match='HYP003_AVAILABILITY_PRODUCER_LINK_MISMATCH'):
        write_availability(config,dest)
    assert not (dest/'content-manifest.json').exists()


@pytest.mark.parametrize('explicit',[False,True])
def test_complete_auto_or_explicit_pair_comes_from_same_producer(tmp_path,explicit):
    config,identity=captured(tmp_path)
    if explicit:
        config['inputs'][0]['links_ref']=ref(tmp_path,'links.json',{
            'schema':'polar.hyp003-source-record-links/1','links':[identity]})
    dest=tmp_path/'availability';write_availability(config,dest)
    row=json.loads((dest/'population-index.ndjson').read_bytes().splitlines()[0])
    fact=row['coverage'][0]
    assert fact['profile_binding']=='VERIFIED_PRODUCER_JOB'
    assert fact['canonical_job_id']==identity['canonical_job_id']
    assert fact['source_plan_job_id']==identity['source_plan_job_id']
    assert row['source_record']['population_record_id']==identity['population_record_id']
