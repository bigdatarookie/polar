"""Invented request-state association regression; review before invocation."""
import pytest

from test_raw_sip_aggregate import setup,ref,execute,body,collection,index_config
from polar.import_raw_sip import job_id
from polar.hyp003_availability import write_availability
from polar.hyp003_source import PreparationError


@pytest.mark.parametrize('parent_state',['RECEIVED_COMPLETE','RECEIVED_EMPTY'])
def test_uncaptured_request_cannot_borrow_parent_completion(tmp_path,parent_state):
    service,cfg,jobs=setup(tmp_path/'capture',1);pid=service.plan(cfg)['plan_id']
    response=body() if parent_state=='RECEIVED_COMPLETE' else {'bars':{},'next_page_token':None}
    result=execute(service,pid,[response]);source,_=collection(service,result)
    config=index_config(tmp_path,source,rows=[{'population_record_id':'record-0','literal_symbol':'INVENTED0'}])
    # The request and canonical ID are internally consistent, but this request
    # was never captured. Same record/alias cannot supply its transport status.
    different={**jobs[0]['request'],'start':'2019-12-31T00:00:00Z'}
    identity={'population_record_id':'record-0','source_symbol':'INVENTED0',
              'request':different,'canonical_job_id':job_id(different),
              'source_plan_job_id':'uncaptured-source-plan'}
    config['inputs'][0]['links_ref']=ref(tmp_path,'links.json',{
        'schema':'polar.hyp003-source-record-links/1','links':[identity]})
    dest=tmp_path/'availability'
    with pytest.raises(PreparationError,match='HYP003_AVAILABILITY_PRODUCER_LINK_MISMATCH'):
        write_availability(config,dest)
    assert not (dest/'content-manifest.json').exists()
