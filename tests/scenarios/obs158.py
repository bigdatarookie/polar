"""Full PUBLIC deterministic 158x253 Service/native/immutable/replay CI path.

Expected vector is the independently reviewed v13 public control; metadata is
copied exactly except private protocol paths are deliberately not distributed.
No retained input, provider, host receipt, window or rig operation is consumed.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

from polar.obs158_contract import canonical, decode, sha, source_code, ENGINEERING_CHECKS, COMPOSITION_SHA, FILES
from polar.obs158_data import PUBLIC_SHA, METRIC_SHA, known_by
from polar.obs158_service import Obs158Service
from polar.obs158_store import Obs158Store


def execute(report):
    phases=[];temporary=None
    value={'schema':'polar.synthetic-scenario/1','scenario':'obs158','classification':'PUBLIC_DETERMINISTIC_SYNTHETIC',
           'phases':phases,'compute_status':'NOT_RUN','cleanup_status':'NOT_RUN','financial':'NOT_ASSESSED'}
    @contextmanager
    def phase(name):
        r={'name':name,'status':'RUNNING'};phases.append(r);start=time.monotonic()
        try:yield r;r['status']='PASS'
        except BaseException as exc:r.update(status='FAIL',error=type(exc).__name__,reason=str(exc)[:500]);raise
        finally:r['seconds']=round(time.monotonic()-start,6)
    try:
        with tempfile.TemporaryDirectory(prefix='polar-ci-obs158-') as directory:
            temporary=Path(directory); root=temporary/'store';root.mkdir()
            metadata=Path(__file__).parents[1]/'fixtures/obs158-public'
            def write(name,obj):
                p=temporary/name;p.write_bytes(canonical(obj));return ref(p)
            def ref(p):return {'path':str(p.resolve()),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())}
            with phase('public_fixture_preparation') as r:
                members={n:json.loads((metadata/n).read_text()) for n in
                         ['cohort-order-v1.json','calendar-profile-v1.json','action-profile-v1.json']}
                aliases=members['cohort-order-v1.json']['symbols_in_route_order']
                dates=members['calendar-profile-v1.json']['reference_dates']
                calendar=json.loads((metadata/'calendar.json').read_text())['sessions']
                tz=ZoneInfo.from_file(BytesIO((metadata/'timezone.tzif').read_bytes()))
                rows=[]
                for i,day in enumerate(dates):
                    k=known_by(day,calendar,tz)
                    sec,nano=divmod(k,10**9);assert nano==0
                    known=datetime.fromtimestamp(sec,timezone.utc).isoformat()
                    for j,alias in enumerate(aliases):
                        tokens={'o':'31.5000','h':'31.500250','l':'31.500000','c':'31.500250',
                                'v':'0' if i*158+j<960 else '1000000'}
                        row={'source_symbol':alias,'reference_date':day,'adjustment':'raw','feed':'sip',
                             'currency':'USD_REQUEST_CONTRACT','asof':'2020-09-02',
                             'raw_fields_exact_tokens':tokens,'aggregation_label':datetime.fromisoformat(day+'T16:00:00').replace(tzinfo=tz).isoformat(),
                             'estimated_K':known}
                        row.update({n:None for n in ['event_open_at','event_close_at','observed_published_at',
                                                   'observed_historical_available_at','economic_security_id']})
                        row.update({name:tokens[key] for name,key in [('raw_open','o'),('raw_high','h'),
                                    ('raw_low','l'),('raw_close','c'),('raw_volume','v')]})
                        rows.append(row)
                profile=write('public-profile.json',{'public_sha256':PUBLIC_SHA,'metric_sha256':METRIC_SHA,
                    'members':members,'projection':'EXACT_PUBLIC_COHORT_CALENDAR_ACTION_MEMBERS_NO_PRIVATE_PATHS'})
                fixture=write('fixture.json',{'schema':'polar.obs158-invented-input/1','rows':rows,
                    'context':{'pointer_scope':'PUBLIC_DETERMINISTIC_SYNTHETIC_NO_PROVIDER'}})
                assert len(rows)==39974
                r.update(aliases=158,dates=253,rows=39974,zero_volume_cells=960,private_source_reads=0)
            with phase('exact_checkout_ci_runtime_and_data_preflight') as r:
                code=source_code()
                controls_ref=ref(metadata/'expected.json')
                controls=write('controls.json',{'schema':'polar.obs158-controls-binding/1',
                    'public_sha256':PUBLIC_SHA,'metric_sha256':METRIC_SHA,'source_code_sha256':sha(canonical(code)),
                    'output_contract_sha256':code['obs158_output_schema.json']['sha256'],
                    'composition_sha256':COMPOSITION_SHA,'checks':{k:controls_ref for k in ENGINEERING_CHECKS}})
                composition=write('ci-composition.json',{'kind':'OBSERVED_LOCKED_CI_JOB'})
                config={'schema':'polar.obs158-run-config/1','source_class':'INVENTED',
                    'input_config':{'schema':'polar.obs158-ci-input-config/1','profile_ref':profile,
                         'fixture_ref':fixture,'calendar_ref':ref(metadata/'calendar.json'),
                         'timezone_ref':ref(metadata/'timezone.tzif')},'source_code':code,
                    'candidate':{'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                                 'tree':subprocess.check_output(['git','rev-parse','HEAD^{tree}'],text=True).strip()},
                    'image_id':os.environ['POLAR_CI_RUNTIME_IMAGE_ID'],'composition_ref':composition,
                    'controls_ref':controls,'authorization_ref':controls_ref,'preparation_path':'CI_MANAGED'}
                service=Obs158Service(Obs158Store(root,512*1024**2))
                bindings=service.binding(config)
                config['authorization_ref']=write('public-job-authorization.json',{
                    'schema':'polar.obs158-execution-authorization/1','bindings_sha256':sha(canonical(bindings)),
                    'artifact_root':str(root.resolve()),'operations':['PREFLIGHT','RUN','REPLAY'],
                    'purpose':'INVENTED_FIXED_PAIR','family':'PUBLIC_CI_OBS158','max_full_packet_starts':2,
                    'limits':{'total_wall_seconds':600,'native_wall_seconds':480,'cleanup_reserve_seconds':30}})
                prepared=service.preflight(config); assert prepared['native_execution']=='NOT_RUN'
                r.update(candidate=config['candidate'],actual_runtime=prepared['actual_runtime'],
                         converted_sha256=prepared['converted_sha256'])
            import polar.obs158_service as implementation
            original=implementation._simulate;calls=0
            def simulate(converted,aliases,code,directory,seconds):
                nonlocal calls
                with phase('native_full_pair_'+str(calls+1)) as r:
                    calls+=1;out=original(converted,aliases,code,directory,seconds)
                    assert out['engine_runs']==2 and out['native_bar_round_trips']==39974 and out['matching_full_bars']==0
                    r.update(engine_runs=2,native_bar_round_trips=39974,matching_full_bars=0)
                    return out
            implementation._simulate=simulate
            try:
                with phase('service_original_evaluate_and_persist') as r:
                    result=service.run(config); assert result['status']=='SUCCESS'
                    identity=result['finish']['experiment_id'];r.update(experiment_id=identity,attempt_id=result['attempt_id'])
                with phase('independent_accounting_barrier_action_and_report_readback') as r:
                    saved=service.report(identity);assert set(saved['files'])==set(FILES)
                    simulation=saved['files']['simulation.json'];converted=saved['files']['converted.json']
                    assert len(converted['executor_quotes'])==1896
                    assert len(converted['private_close_marks'])==39974 and len(converted['eligible_bars'])==39974
                    assert len(converted['barriers'])==518 and len(converted['unit_events'])==2
                    assert len(converted['sample_grid'])==253
                    r['observed_boundary_accounts']=[{'strategy':t['strategy_id'],
                        'cash_first':t['samples'][0]['cash_cents'],
                        'nav_first':t['samples'][0]['price_ledger_value_cents'],
                        'nav_first_entry':t['samples'][3]['price_ledger_value_cents'],
                        'cash_last':t['samples'][-1]['cash_cents'],
                        'nav_last':t['samples'][-1]['price_ledger_value_cents'],
                        'AAPL_last_physical':t['samples'][-1]['positions']['AAPL'],
                        'TSLA_last_physical':t['samples'][-1]['positions']['TSLA'],
                        'fills':len(t['fills']), 'unit_events':t['unit_events']}
                        for t in simulation['strategies']]
                    summaries=[]
                    for strategy in simulation['strategies']:
                        samples=strategy['samples'];fills=strategy['fills']
                        assert len(samples)==253 and len(fills)==158
                        assert sum(int(f['fee_cents']) for f in fills)==15800
                        assert all(int(s['price_ledger_value_cents'])==10000000 for s in samples[:3])
                        assert all(int(s['price_ledger_value_cents'])==9984200 and int(s['cash_cents'])==30200 for s in samples[3:-1])
                        assert int(samples[-1]['price_ledger_value_cents'])==10425204
                        assert samples[-1]['date']=='2020-08-31'
                        assert int(samples[-1]['positions']['AAPL'])==80 and int(samples[-1]['positions']['TSLA'])==100
                        assert all(int(q)==20 for alias,q in samples[-1]['positions'].items() if alias not in ['AAPL','TSLA'])
                        assert len(strategy['unit_events'])==2 and all(int(u['native_quantity'])==20 for u in strategy['unit_events'])
                        assert all(int(b['observed_aliases'])==158 for b in strategy['barriers'])
                        summaries.append({'strategy':strategy['strategy_id'],'samples':253,'fills':158,
                            'fees_cents':15800,'post_entry_nav_cents':9984200,'cash_cents':30200,
                            'terminal_physical':{'other_aliases':20,'AAPL':80,'TSLA':100},'terminal_nav_cents':10425204,'unit_events':strategy['unit_events']})
                    r.update(strategies=summaries,semantic_files=list(FILES),manifest=saved['manifest'],
                             converted_counts={'marks':39974,'eligible':39974,'quotes':1896,'barriers':518,'samples':253,'units':2})
                with phase('fresh_native_semantic_replay_and_immutable_readback') as r:
                    replay=service.replay(config,identity);assert replay['status']=='SUCCESS'
                    assert replay['finish']['experiment_id']==identity
                    assert service.report(identity)==saved
                    r.update(semantic_identity_unchanged=True,engine_runs=2,report_unchanged=True)
                value['compute_status']='PASS'
            finally:implementation._simulate=original
        value['cleanup_status']='PASS_TASK_DIRECTORY_REMOVED'
    except BaseException:
        if value['compute_status']!='PASS':value['compute_status']='FAIL'
        raise
    finally:
        value['cleanup_status']=('PASS_TASK_DIRECTORY_REMOVED' if temporary is not None and not temporary.exists()
                                 else 'FAIL_TASK_DIRECTORY_REMAINS' if temporary is not None else 'NOT_CREATED')
        value['status']='PASS' if value['compute_status']=='PASS' and value['cleanup_status'].startswith('PASS') else 'FAIL'
        import resource
        value['resource_usage']={'self_maxrss_linux_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                                 'children_maxrss_linux_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}
        report.write_text(json.dumps(value,indent=2)+'\n')


if __name__=='__main__':execute(Path(sys.argv[1]))
