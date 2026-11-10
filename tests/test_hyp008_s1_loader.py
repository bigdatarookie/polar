"""Invented direct-reference fixtures, never retained c478 operands or models."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path

import pytest

from polar.hyp008_s1_contract import canonical,sha,ref,S1ContractError,NumberToken,decode
from polar.hyp008_s1_loader import prepare_source,SourceGraph,pointer,typed_equal
from polar.hyp008_s1_numeric import SLOTS
from polar.hyp008_s1_source import OWNER_PINS
from polar.hyp008_s1_service import S1Service,INTERPRETATIONS
from test_hyp008_s1_store import store


def dataset(tmp_path,issue=False):
    root=tmp_path/'source';root.mkdir();locators={};refs={}
    def save(name,value,ndjson=False):
        path=root/name;raw=b''.join(canonical(v) for v in value) if ndjson else canonical(value)
        path.write_bytes(raw);pin=ref(raw);locators[pin['sha256']]=str(path)
        return path,pin
    dates=[(datetime(2017,1,3)+timedelta(days=7*i)).date().isoformat() for i in range(52)]+['2022-01-03']
    def instant(day):return day+'T09:00:00Z'
    def finish(day):return (datetime.fromisoformat(day)+timedelta(days=6)).date().isoformat()+'T14:30:00Z'
    def ratio():return {'numerator':'0','denominator':'1'}
    def payload(slot):
        sqrt=slot in ('VOL20','DOWN20')
        return {'decimal80_projection':'0','exact_radicand' if sqrt else 'exact_fraction':ratio(),
            'projection_squared_minus_exact_radicand' if sqrt else 'projection_minus_exact':ratio(),
            'method':'DECIMAL80_DIVIDE_THEN_SQRT_ROUND_HALF_EVEN' if sqrt else 'DECIMAL80_DIVIDE_ROUND_HALF_EVEN'}
    roster=[{'key':day+':'+symbol,'D':instant(day)} for day in dates for symbol in ('AAPL','AMZN','TSLA','TWTR')]
    roster_path,roster_pin=save('roster.ndjson',roster,True)
    raw_roster=roster_path.read_bytes().splitlines(keepends=True)
    originals=[];metadata=[];histories=[]
    for index,day in enumerate(dates):
        available=index<52 or issue;K=(datetime.fromisoformat(day)-timedelta(days=1)).date().isoformat()+'T00:00:00Z'
        parts=[{'key':day+':'+symbol,'stored_K':finish(day),'reason':None,'mark_kind':'INVENTED_OPEN'}
               for symbol in ('AAPL','AMZN','TSLA','TWTR')]
        original={'D_date':day,'D':instant(day),'A_status':'READY_CONDITIONAL' if available else 'UNAVAILABLE',
            'A_reasons':[] if available else ['INVENTED_UNAVAILABLE'],'A_required_K':K,
            'A_values':{('LIQUIDITY' if slot=='MEDIAN_DV20' else slot):payload(slot) for slot in SLOTS} if available else None,
            'B_open_dates':[day]*6,'B_required_K':finish(day),'B_constituents':parts,
            'B_value_represented_fraction':ratio(),'B_binary64_projection':0}
        originals.append(save('row-'+day+'.json',original))
        pointers=[{'key':day+':'+symbol,'line_1based':index*4+j+1,
                   'raw_line_sha256':sha(raw_roster[index*4+j])} for j,symbol in enumerate(('AAPL','AMZN','TSLA','TWTR'))]
        metadata.append({'decision_date':day,'D':instant(day),'end':finish(day),'component_metadata':parts,'roster_pointers':pointers})
        histories.append({'index':index,'decision_date':day,'D':instant(day)})
    op_path,op_pin=save('opportunity-metadata.ndjson',metadata,True);hist_path,hist_pin=save('history-metadata.ndjson',histories,True)
    def declared(path,pin,role):
        refs[str(path)]={**pin,'path':str(path),'roles':[role]};locators[str(path)]=str(path)
    declared(roster_path,roster_pin,'DECLARED_PRIMITIVE_OR_OPERATOR_ANCESTRY')
    declared(op_path,op_pin,'HISTORY_METADATA_MEMBER');declared(hist_path,hist_pin,'HISTORY_METADATA_MEMBER')
    rows=[]
    for index,day in enumerate(dates):
        path,pin=originals[index];declared(path,pin,'CENSUS_MEMBER')
        original=json.loads(path.read_bytes());source_ref={**pin,'path':str(path)};available=original['A_values'] is not None
        rows.append({'index':index,'opportunity_id':'invented-'+str(index),'decision_date':day,'D':instant(day),
            'capability_basis':'invented-basis','clock_assurance':'INVENTED_ESTIMATED',
            'A':{'A_status':original['A_status'],'A_reasons':original['A_reasons'],'A_required_K':original['A_required_K'],
                 'A_raw_K_floor':None,'A_action_indices':[],'A_anchor':day,'A_window_end':day,'A_window_start':day},
            'B':{'status':'DEFINED_CONDITIONAL','reasons':[],'represented_fraction':ratio(),'required_K':finish(day),
                 'scheduled_end':finish(day),'open_dates':original['B_open_dates'],'component_metadata':metadata[index]['component_metadata'],
                 'original_source_roster_refs':metadata[index]['roster_pointers'],'unit':'invented-target',
                 'numeric_source_ref':{**source_ref,'json_pointer':'/B_value_represented_fraction'},
                 'binary64_projection_ref':{**source_ref,'json_pointer':'/B_binary64_projection'},
                 'source_constituents_ref':{**source_ref,'json_pointer':'/B_constituents'},'own_D_maturity':'NOT_A_FIT_OR_SCORE_MASK'},
            'X':{slot:{'numeric_status':'AVAILABLE_AS_STORED' if available else 'UNAVAILABLE_AS_STORED',
                      'represented_source_payload':payload(slot) if available else None,'unit':'u'+str(j),
                      'source_field':'LIQUIDITY' if slot=='MEDIAN_DV20' else slot,
                      'source_ref':{**source_ref,'json_pointer':'/A_values/'+('LIQUIDITY' if slot=='MEDIAN_DV20' else slot)}}
                 for j,slot in enumerate(SLOTS)},
            'source_row_ref':source_ref,'opportunity_metadata_ref':{**op_pin,'path':str(op_path),'line_1based':index+1},
            'history_metadata_ref':{**hist_pin,'path':str(hist_path),'line_1based':index+1},
            'observed_clocks':{'published_at':None,'available_at':None,'ingested_at':None},
            'historical_D_feature_information_check':'INVENTED','Ghist_W_fold_S_transform_solver_fit_score_masks':'UNBOUND_NOT_SELECTED'})
    _,row_pin=save('rows.ndjson',rows,True)
    _,refs_pin=save('references.json',{'schema':'polar.private-consumer-source-refs/1','closure_scope':'invented','references':refs})
    revision='invented-source'
    _,content=save('content-manifest.json',{'schema':'polar.hyp008-private-consumer-content/1','revision':revision,'rows':len(rows),
        'feature_order':list(SLOTS),'objects':{'rows.ndjson':row_pin,'references.json':refs_pin}})
    _,delivery=save('delivery-manifest.json',{'schema':'polar.private-dataset-delivery-package/1','revision':revision,
        'files':{'content-manifest.json':content,'rows.ndjson':row_pin,'references.json':refs_pin}})
    _,descriptor=save('descriptor.json',{'schema':'invented-value-free-descriptor'})
    _,meta=save('metadata.json',{'schema':'invented-metadata'})
    config={'schema':'polar.hyp008-s1-config/1','candidate_id':'HYP008','variant_id':'HYP008_STANDARD_SOURCE_COHORT_FORECAST_S1',
        'owner_pins':list(OWNER_PINS),'source_binding':{'source_class':'INVENTED','dataset_revision':revision,
            'content_sha256':content['sha256'],'delivery_sha256':delivery['sha256'],'x_basis':'invented-basis',
            'x_version':revision,'x_units':['u'+str(i) for i in range(5)],'b_basis':'invented-target-basis',
            'b_version':revision,'b_units':'invented-target','census_count':len(rows)},
        'inputs':{'content_manifest':content,'delivery_manifest':delivery,'rows':row_pin,'references':refs_pin,'descriptor':descriptor},
        'defaults':dict.fromkeys(('package','tree','highs','build'),meta),'source_projection':meta,
        'interpretation_refs':[{'sha256':h,'bytes':1} for h in INTERPRETATIONS]}
    return config,locators,root


def test_complete_closure_preserves_opaque_payload_and_masks(tmp_path):
    config,locators,_=dataset(tmp_path,True)
    masks,source,rows=prepare_source(config,locators)
    assert len(masks['full_census'])==53 and masks['I']==['invented-52'] and masks['P']==['invented-52']
    assert len(masks['C'][0]['history_window'])==52 and masks['numeric_work_performed'] is False
    assert source['assurance']['financial']=='NOT_ASSESSED'
    assert rows[0]['X']['RET1']['represented_source_payload']['decimal80_projection']=='0'
    assert any(c['status']=='MATCHED_ROSTER_RAW_LINE_KEY' for c in source['closure_checks'])


def test_unavailable_parent_does_not_dereference_child_under_null(tmp_path):
    config,locators,_=dataset(tmp_path,False)
    masks,source,rows=prepare_source(config,locators)
    assert not masks['I'] and masks['reason']=='NO_ISSUE_COMPARISON'
    assert all(x['represented_source_payload'] is None for x in rows[-1]['X'].values())


def test_graph_ref_replacement_and_symlink_fail_before_any_numeric(tmp_path):
    config,locators,root=dataset(tmp_path,True)
    first=root/'row-2017-01-03.json';first.write_bytes(first.read_bytes()+b' ')
    with pytest.raises(S1ContractError,match='SOURCE_BYTE_HASH'):prepare_source(config,locators)


def test_pointer_is_rfc6901_and_type_preserving():
    v={'with/slash':{'a~b':[NumberToken('1.00'),'1.00']}}
    assert pointer(v,'/with~1slash/a~0b/0')==NumberToken('1.00')
    assert not typed_equal(NumberToken('1.00'),'1.00')
    for path in ('/with~2slash','/with~1slash/a~0b/01','/with~1slash/a~0b/9'):
        with pytest.raises(S1ContractError):pointer(v,path)


def test_public_cli_does_not_offer_root_or_authorize_option(monkeypatch,capsys):
    import polar.hyp008_s1_service as service
    from polar.cli import main
    monkeypatch.setattr(service,'PROFILE',Path('/nonexistent-s1-test-profile'))
    with pytest.raises(SystemExit) as result:main(['hyp008-s1-report','s1-'+'a'*64])
    assert result.value.code==1
    assert json.loads(capsys.readouterr().out)['reason']=='TRUSTED_S1_DEPLOYMENT_NOT_CONFIGURED'


def metadata_pins_for_service(config,locators,monkeypatch):
    # This invented unit supplies metadata bytes, not alternate production owners.
    import polar.hyp008_s1_service as module
    pin=config['source_projection'];config['interpretation_refs']=[pin,pin]
    monkeypatch.setattr(module,'INTERPRETATIONS',(pin['sha256'],pin['sha256']))


def test_no_issue_publishes_only_lineage_and_stored_read_is_readonly(tmp_path,monkeypatch):
    config,locators,_=dataset(tmp_path,False);metadata_pins_for_service(config,locators,monkeypatch)
    s=store(tmp_path);service=S1Service(s,locators)
    prepared=service.prepare(config)
    assert prepared['readiness']=='NO_ISSUE_COMPARISON' and prepared['numeric_work_performed'] is False
    assessment=s._read('s1-assessments',prepared['prepare_id'])
    report=service.report(assessment['experiment_id'])
    assert report['files']['family.json']['status']=='NOT_STARTED'
    assert set(report['manifest']['files'])=={'config.json','source.json','masks.json','family.json','limitations.json'}
    assert not (s.root/s.family()).exists() and report['qualified_score'] is None
    before={str(p):p.read_bytes() for p in s.root.rglob('*') if p.is_file()}
    result=service.verify_stored(assessment['experiment_id'])
    assert result['numeric_proof_status']=='NOT_PRODUCED'
    assert before=={str(p):p.read_bytes() for p in s.root.rglob('*') if p.is_file()}


def test_nonempty_no_authority_starts_no_runtime_and_does_not_reparse_source(tmp_path,monkeypatch):
    from test_hyp008_s1_store import seal
    import polar.hyp008_s1_service as module
    config,locators,_=dataset(tmp_path,True);metadata_pins_for_service(config,locators,monkeypatch)
    s=store(tmp_path);service=S1Service(s,locators,lambda *args:pytest.fail('runtime must not start'))
    prepared=service.prepare(config);assert prepared['readiness']=='READY_FOR_SEAL'
    value=seal(s,False);value['prepared_ref']=s.object(prepared);value.pop('seal_id');value['seal_id']=sha(canonical(value))
    monkeypatch.setattr(module,'prepare_source',lambda *args:pytest.fail('no authority: no new source parse'))
    result=service.run(value)
    assert result['status']=='NOT_BOUND' and result['reason']=='EXECUTION_NOT_AUTHORIZED'
    assert not (s.root/s.family()).exists()


def test_wrong_interpretation_pin_rejected_before_source_read(tmp_path):
    config,locators,_=dataset(tmp_path,True)
    config['interpretation_refs'][0]['sha256']='0'*64
    s=store(tmp_path);result=S1Service(s,{}).prepare(config)
    assert result['reason']=='INTERPRETATION_BINDING' and not (s.root/s.family()).exists()


def test_after_family_reservation_numeric_failure_is_final_and_no_stage_or_runtime_retry(tmp_path,monkeypatch):
    from test_hyp008_s1_store import seal
    import polar.hyp008_s1_service as module
    from polar.hyp008_s1_numeric import S1NumericError
    from polar.hyp008_s1_contract import GRANT,FAMILY
    from types import SimpleNamespace as N
    config,locators,_=dataset(tmp_path,True);metadata_pins_for_service(config,locators,monkeypatch)
    s=store(tmp_path);calls=[];prep=tmp_path/'runtime-preparation.json';prep.write_text('{}\n')
    candidate={'commit':'a'*40,'tree':'b'*40};image='sha256:'+'c'*64
    def runtime_factory(*args):
        calls.append('factory')
        return N(candidate=candidate,image_id=image,preparation_path=str(prep),verify=lambda:calls.append('verify'))
    service=S1Service(s,locators,runtime_factory);prepared=service.prepare(config)
    value=seal(s,False);value['prepared_ref']=s.object(prepared);value.pop('seal_id');value['seal_id']=sha(canonical(value))
    registration=s.get(value['registration_ref'])
    authority={'schema':'polar.hyp008-s1-authority/1','seal_id':value['seal_id'],
        'registration_id':sha(canonical(registration)),'store_binding_id':s.deployment.binding_id,
        'family_key':FAMILY,'execution_assignment_ref':value['execution_assignment_ref'],'grant':GRANT}
    (s.deployment.authority_directory/(value['seal_id']+'.json')).write_bytes(canonical(authority))
    monkeypatch.setattr(service,'_qualification',lambda *args:({'candidate':candidate},{'image_id':image}))
    def numeric_failure(*args):
        assert (s.root/s.family()/'start'/'record.json').exists()
        raise S1NumericError('INVENTED_SOURCE_PROOF_FAILURE')
    monkeypatch.setattr(service,'_represent',numeric_failure)
    result=service.run(value)
    assert result['status']=='PLANNED_FAMILY_UNAVAILABLE' and result['reason']=='NUMERIC_UNVERIFIED'
    terminal=service.attempt(result['attempt_id'])
    assert not any(terminal['stage_records'].values())
    assert terminal['terminal_status']=='PLANNED_FAMILY_UNAVAILABLE'
    assert service.report(result['experiment_id'])['qualified_score'] is None
    before=list(calls)
    assert service.run(value)['reason']=='FAMILY_ALREADY_STARTED' and calls==before


def qualified_service(tmp_path,monkeypatch):
    """Invented source/runtime doubles, actual closed seal and admission records."""
    from test_hyp008_s1_store import seal
    from polar.hyp008_s1_contract import GRANT,FAMILY
    from types import SimpleNamespace as N
    config,locators,_=dataset(tmp_path,True);metadata_pins_for_service(config,locators,monkeypatch)
    s=store(tmp_path);candidate={'commit':'a'*40,'tree':'b'*40};image='sha256:'+'c'*64
    code={'schema':'polar.hyp008-s1-code-projection/1','candidate':candidate,
          'files':{'/app/src/polar/invented.py':{'bytes':1,'sha256':'0'*64}}}
    raw=canonical(code);path=tmp_path/'code.json';path.write_bytes(raw)
    config['source_projection']=ref(raw);locators[sha(raw)]=str(path)
    prep=tmp_path/'runtime.json';prep.write_bytes(canonical({'scope':'PURE_TEST_DOUBLE_NOT_NATIVE_PROOF'}))
    service=S1Service(s,locators,lambda *args:N(candidate=candidate,image_id=image,
        preparation_path=str(prep),verify=lambda:None))
    prepared=service.prepare(config);assert prepared['readiness']=='READY_FOR_SEAL'
    code_ref=s.object(code);registration=seal(s,False)['registration_ref'];proof=s.object({'invented':'qualification'})
    build=s.object({'commit':candidate['commit'],'tree':candidate['tree'],'image_id':image,'source_files':code['files']})
    qa=s.object({'schema':'polar.hyp008-s1-qualification/1','code_ref':code_ref,'build_ref':build,
        'verdicts':{'code':'PASS','numeric':'PASS','system':'PASS'},'proof_refs':[proof]})
    plan=s.object({'schema':'polar.hyp008-s1-runtime-plan/1','candidate':candidate,'image_id':image,
        'source_build_ref':build,'launcher_refs':[proof],'store_profile_ref':s.deployment.profile_ref})
    assignment=s.object({'schema':'polar.hyp008-s1-execution-assignment/1','prepared_ref':s.object(prepared),
        'registration_ref':registration,'native_qitem':'qitem-invented-unit3','scope':'INVENTED'})
    value=service.seal(s.object(prepared),registration,code_ref,build,qa,assignment,plan)
    assert value['schema']=='polar.hyp008-s1-seal/1'
    authority={'schema':'polar.hyp008-s1-authority/1','seal_id':value['seal_id'],
        'registration_id':sha(canonical(s.get(registration))),'store_binding_id':s.deployment.binding_id,
        'family_key':FAMILY,'execution_assignment_ref':assignment,'grant':GRANT}
    (s.deployment.authority_directory/(value['seal_id']+'.json')).write_bytes(canonical(authority))
    return service,value


def complete_family_double(ids,z,y,score,windows,targets,masks,binding,start,observe):
    """No model/LP/quantile: supplied all-zero certificate and serialized doubles."""
    from dataclasses import asdict
    from polar.exact_certificate import ExactCertificateRequest,verify_exact_certificate
    from polar.hyp008_s1_linear import VERIFIER_LIMITS
    from polar.hyp008_s1_evaluation import evaluate_common
    n=len(ids);zero='0000000000000000';pairs=(('0','1'),)*n
    request=ExactCertificateRequest(ids,z,y,(('0','1'),)*6,pairs,pairs)
    proof=asdict(verify_exact_certificate(request,limits=VERIFIER_LIMITS))
    assert proof['status']=='EXACT_REPRESENTED_INPUT_CERTIFIED'
    tree={'schema':'polar.hyp008-s1-tree/1','parameters':{'alpha':0.1},
        'parameter_provenance':{'alpha':{'origin':'INVENTED','value':0.1}},
        'nominal_estimators':50,'actual_iterations':1,'model_text':'Tree=0\nnum_leaves=1\nsplit_feature=\n',
        'native_precision':'INVENTED','default_hashes':{}}
    linear={'schema':'polar.hyp008-s1-linear/1','theta':proof['theta'],'certificate_request':asdict(request),
        'proof':proof,'solver':{'method':'INVENTED_NO_LP','options':{},'status':0,'iterations':0,
            'dual_binary64':[zero]*n,'secondary_iterations':0,'generation_operations':0},
        'limits':asdict(VERIFIER_LIMITS),'representation':'INVENTED_ZERO_CERTIFICATE'}
    history={i:{'bits':zero,'rank':6,'window_ids':list(w['ids'])} for i,w in windows.items()}
    evidence={'TREE':{'model_text_sha256':sha(tree['model_text'].encode())},
        'LINEAR':{'proof_id':proof['proof_id']},
        'HISTORICAL_PASS':{'history_sha256':sha(json.dumps(history,sort_keys=True,separators=(',',':')).encode())}}
    for name in ('TREE','LINEAR','HISTORICAL_PASS'):
        start(name+'_START');observe(name,'CALL_BOUNDARY_OBSERVED',{'scope':'MOCK_NOT_NATIVE'})
        observe(name,'COMPLETED',evidence[name])
    methods={k:dict.fromkeys(masks['I'],zero) for k in ('TREE','LINEAR','HISTORICAL')}
    return {'status':'COMPLETE','reason':None,'stages':dict.fromkeys(evidence,'SUCCESS'),
        'artifacts':{'tree':tree,'linear':linear,'history':history},'forecasts':methods,
        'evaluation':evaluate_common(masks,methods,targets)}


def test_complete_facade_publishes_twelve_and_stored_verify_does_not_recompute(tmp_path,monkeypatch):
    import polar.hyp008_s1_models as models
    service,value=qualified_service(tmp_path,monkeypatch)
    monkeypatch.setattr(models,'fixed_family',complete_family_double)
    result=service.run(value);assert result['status']=='SUCCESS'
    report=service.report(result['experiment_id'])
    assert len(report['manifest']['files'])==12 and report['qualified_score']['aggregate']['count']==1
    assert report['files']['tree.json']['parameters']=={'alpha':0.1}
    before={str(p):p.read_bytes() for p in service.store.root.rglob('*') if p.is_file()}
    def forbidden(*args,**kwargs):pytest.fail('stored verification must not rerun')
    monkeypatch.setattr(service,'_represent',forbidden);monkeypatch.setattr(models,'fixed_family',forbidden)
    monkeypatch.setattr(__import__('polar.hyp008_s1_service',fromlist=['prepare_source']),'prepare_source',forbidden)
    assert service.verify_stored(result['experiment_id'])['numeric_proof_status']=='REPRODUCED'
    assert before=={str(p):p.read_bytes() for p in service.store.root.rglob('*') if p.is_file()}
    assert service.run(value)['reason']=='FAMILY_ALREADY_STARTED'


def test_manifest_publication_interruption_does_not_refund_or_repeat_models(tmp_path,monkeypatch):
    import polar.hyp008_s1_models as models
    service,value=qualified_service(tmp_path,monkeypatch);calls=[]
    def family(*args,**kwargs):calls.append('family');return complete_family_double(*args,**kwargs)
    monkeypatch.setattr(models,'fixed_family',family)
    monkeypatch.setattr(service.store,'publish',lambda *args:(_ for _ in ()).throw(OSError('invented disk failure')))
    with pytest.raises(OSError):service.run(value)
    start=service.store._read(service.store.family(),'start');aid=start['attempt_id']
    assert service.attempt(aid)['terminal_status']=='UNFINALIZED'
    assert service.run(value)['reason']=='FAMILY_ALREADY_STARTED' and calls==['family']


def test_facade_lost_attempt_link_reports_consumed_family_not_zero_charge(tmp_path,monkeypatch):
    service,value=qualified_service(tmp_path,monkeypatch);original=service.store._record
    def fail(parent,name,record):
        if parent.startswith('s1-attempts/'):raise OSError('invented lost attempt link')
        return original(parent,name,record)
    monkeypatch.setattr(service.store,'_record',fail)
    result=service.run(value)
    assert result['status']=='UNFINALIZED' and result['family_charged'] is True
    assert result['scientific_starts']==1 and result['resumption_allowed'] is False
    assert service.store._read(service.store.family(),'start')['attempt_id']==result['attempt_id']
    assert service.run(value)['reason']=='FAMILY_ALREADY_STARTED'
