"""Affected public C54 /2 admission, full-close native batch and saved coverage."""
import json
from pathlib import Path
import pytest
from polar.gym_contract import canonical, sha
from polar.reference_service import ReferenceResearchService, PROFILES, binding
from polar import reference_c
from polar.research_results import ResearchResults, validate_result
from reference_fixture import write
from reference_c_fixture import fixture


def test_c54_one_fit_two_phases_all_quotes_fees_marks_and_stored_reproduction(tmp_path, monkeypatch):
    root,config=fixture(tmp_path,monkeypatch); svc=ReferenceResearchService(root,256*1024**2)
    ready=svc.preflight(config);assert ready['input_rows']==32400 and ready['training_rows']==108
    market,calendar,_,_=svc.prepare(config)
    result=svc.run(config);assert result['fit_calls']==1 and result['native_accounts']==8
    for phase,pub in result['results'].items():
        record=ResearchResults(root,256*1024**2).read(pub['result_id'])['record']
        assert record['primary_benchmark_id']=='EW_ELIGIBLE_MONTHLY'
        assert len(record['source_coverage'])==100
        assert sum(r['eligibility']=='ELIGIBLE' for r in record['source_coverage'])==54
        assert all(r['financial_result']=='NOT_EVALUATED_FOR_FIXED_CONDITIONAL_COHORT'
                   for r in record['source_coverage'][54:])
        assert not any('FOUR_ASSETS' in r['code'] for r in record['limitations'])
        assert canonical(validate_result(record))==canonical(record)
        if phase=='FINAL':
            from copy import deepcopy
            from datetime import date,timedelta
            from polar.research_results import MAX_RESULT
            long=deepcopy(record)
            long['grid']=[(date(2023,1,1)+timedelta(days=i)).isoformat()+'T21:00:00Z' for i in range(967)]
            for series in long['series']:
                series['values'] += [deepcopy(series['values'][-1]) for _ in range(967-len(series['values']))]
                series['ledger'] += [deepcopy(series['ledger'][-1]) for _ in range(967-len(series['ledger']))]
            assert len(canonical(validate_result(long)))<MAX_RESULT
        ew=next(s for s in record['series'] if s['id']=='EW_ELIGIBLE_MONTHLY')
        assert len(ew['values'])==calendar[phase.lower()+'_financial_grid']['nav_points']
        from decimal import Decimal, ROUND_HALF_EVEN, localcontext, Context
        with localcontext(Context(prec=50,rounding=ROUND_HALF_EVEN)):
            for stamp,value,row in zip(record['grid'],ew['values'],ew['ledger']):
                marks=sum((Decimal(q)*Decimal(market['prices_micro'][stamp[:10]][s])/1000000).quantize(Decimal('.01'))
                          for s,q in row['positions'].items())
                assert Decimal(value['value'])==Decimal(row['cash'])+marks
        # With public cheap quotes all54 fit. The native risk engine must not drop
        # orders beyond its historical20/sec limit or sample a partial batch.
        funded=next(p for p in ew['ledger'] if any(p['positions'].values()))
        assert len(funded['positions'])==54 and all(q>0 for q in funded['positions'].values())
        assert funded['cumulative_flat_fees']=='54.00'
        assert all(q==0 for q in ew['ledger'][-1]['positions'].values())
    semantic=root/'reference-research-experiments'/result['semantic_id']
    assert set(json.loads((semantic/'manifest.json').read_bytes())['files'])=={
        'model.json','phases.json','diagnostics.json','bindings.json','calendar.json','coverage.json'}
    before={str(p):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    import polar.reference_service as source
    def forbidden(*a,**k):raise AssertionError('STORED_RECOMPUTE_CALLED_MODEL_OR_NATIVE')
    monkeypatch.setattr(source,'fit_ridge',forbidden);monkeypatch.setattr(source,'bounded_native',forbidden)
    assert svc.recompute(result['semantic_id'])['status']=='REPRODUCED'
    assert before=={str(p):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    with pytest.raises(ValueError,match='REFERENCE_ORIGINAL_ALREADY_RECORDED'):svc.run(config)


def test_c_source_and_calendar_admission_before_numeric_loader(tmp_path,monkeypatch):
    root,config=fixture(tmp_path,monkeypatch)
    path=Path(config['input_ref']['path']);manifest=json.loads(path.read_bytes())
    manifest['symbols'].pop();config['input_ref']=write(path,manifest)
    import polar.reference_service as source
    monkeypatch.setattr(source,'load_reference',lambda *a:pytest.fail('NUMERIC_LOADER_BEFORE_ADMISSION'))
    # Rebind the invented protocol so this tests source dimension admission itself.
    protocol=Path(config['protocol_ref']['path']);control=json.loads(protocol.read_bytes())
    control['input_sha256']=config['input_ref']['sha256'];config['protocol_ref']=write(protocol,control)
    with pytest.raises(ValueError,match='REFERENCE_C_SOURCE_PROFILE'):ReferenceResearchService(root,10**8).preflight(config)


def test_c_coverage_missing_alias_fails_without_fit(tmp_path,monkeypatch):
    root,config=fixture(tmp_path,monkeypatch)
    path=Path(config['input_ref']['path']);manifest=json.loads(path.read_bytes())
    rp=Path(manifest['source_relations']['path']);relations=json.loads(rp.read_bytes());relations['eligibility_ledger']['rows'].pop()
    manifest['source_relations']=write(rp,relations);config['input_ref']=write(path,manifest)
    pp=Path(config['protocol_ref']['path']);control=json.loads(pp.read_bytes());control['input_sha256']=config['input_ref']['sha256']
    config['protocol_ref']=write(pp,control)
    with pytest.raises(ValueError,match='REFERENCE_C_ALL100_COVERAGE'):ReferenceResearchService(root,10**8).preflight(config)


def test_c_authority_does_not_accept_old_A_test_selection(tmp_path,monkeypatch):
    root,config=fixture(tmp_path,monkeypatch)
    config.update(namespace='RETAINED',profile_id=reference_c.C)
    method=write(tmp_path/'method.json',{'method_verdict':'PASS','protocol':{'sha256':reference_c.PROFILE['protocol']}})
    monkeypatch.setitem(PROFILES,reference_c.C,{**reference_c.PROFILE,'method':method['sha256']})
    candidate=write(tmp_path/'candidate.json',{'schema':'polar.native-hypothesis-reservation/1','state':'RESERVED',
        'candidate_id':config['candidate_id'],'experiment_registration_id':reference_c.PROFILE['registration']})
    qualification={'schema':'polar.ci-result/1','status':'PASS','candidate_sha':config['code_revision'],
                   'selection':['tests/test_reference_service.py']}
    qref=write(tmp_path/'qualification.json',qualification)
    def bind():
        config['execution_authority_ref']=write(tmp_path/'authority.json',{
            'schema':'polar.reference-research-operation/1','action':'ORIGINAL',
            'binding_sha256':sha(canonical(binding(config))),'method_ref':method,'candidate_ref':candidate,
            'qualification_ref':qref})
    bind();svc=ReferenceResearchService(root,10**8)
    with pytest.raises(ValueError,match='REFERENCE_EXACT_TECHNICAL_QUALIFICATION'):svc._authority(config)
    qualification['selection']=['tests/test_reference_c_service.py'];qref=write(tmp_path/'qualification.json',qualification)
    bind();assert svc._authority(config)['action']=='ORIGINAL'
