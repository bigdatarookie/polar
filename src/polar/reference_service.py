"""Selected chronological research through the existing immutable store/result API.

No source provider, task tracker, retry loop, account reset or dynamic strategy.
Scientific originals require exact method/candidate/technical authority bindings.
"""
import io
import importlib.metadata
import os
from pathlib import Path
import platform
import re
import sys
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from .ci_research import require, TZ_SHA
from .ci_research_service import root_identity, bounded_native
from .gym_contract import canonical, sha, read_ref, decode
from .gym_service import code_binding
from .history_bundle import read_file
from .history_store import HistoryStore
from .research_results import ResearchResults
from .research_reference import load_reference
from .research_learning import fit_ridge, diagnostic_mse, diagnostic_from_records
from .reference_ridge_plan import ridge_phase_plan, LEGS
from .reference_evaluation import evaluate_reference
from .reference_projection import public_reference
from . import reference_c

A='V033-A-RIDGE-LONG4-ADJREF-V1'
INVENTED_A='INVENTED-REFERENCE-RIDGE-CONTROL-V1'
B='V033-B-PPO-LONG4-ADJREF-V1'
INVENTED_B='INVENTED-REFERENCE-PPO-CONTROL-V1'
PROFILES={A:{'kind':'RIDGE','protocol':'078966157ce332e7c870b76030d5c6670633abb9a76bdd8ca15004f65d4835a0',
    'method':'780c13e99226029507616752b75af349cceaa03bf28b16c4f86dfbc027abac96',
    'calendar':'4c4d27655b543a4961a2ffc83474bb0d7e3e4df27ef0e2197fe675e0bc49259d',
    'registration':A+'-EXPERIMENT-01'}}
PROFILES[INVENTED_A]={'kind':'RIDGE','registration':'INVENTED-REFERENCE-RIDGE-CONTROL-V1'}
PROFILES[B]={'kind':'PPO','protocol':'9abfb523089c37d4f67c3b1f490273948a70c3b57aff1b1103c1bcb9b0a75b15',
    'method':'4f1312f36b88f9315ff26030bf3ee8025b8dad00b1150db76af7a84d9fb1d019',
    'calendar':'6953950f2b8811f42515d667a807a988586620452ec63185981e419851cc3823','registration':B+'-EXPERIMENT-01'}
PROFILES[INVENTED_B]={'kind':'PPO','registration':INVENTED_B}
PROFILES[reference_c.C] = reference_c.PROFILE
PROFILES[reference_c.INVENTED_C] = {'kind':'RIDGE', 'registration':reference_c.INVENTED_C}
INPUT='070ea3eb9363894aa37ec4254997be34116b745166b173e1ab1e7dcc4182e3cd'


def config_from_seed(seed):
    def pin(name):
        path=Path(seed[name]);raw=read_file(path.parent,path.name,32*1024**2)
        return {'path':str(path),'sha256':sha(raw)}
    return {'schema':'polar.reference-research-config/1','namespace':seed['namespace'],'profile_id':seed['profile_id'],
        'protocol_ref':pin('protocol_path'),'input_ref':pin('input_path'),'calendar_ref':pin('calendar_path'),
        'timezone_ref':pin('timezone_path'),'code':code_binding(),'code_revision':seed['code_revision'],
        'runtime_image_id':seed['runtime_image_id'],'candidate_id':seed['candidate_id'],'experiment_id':seed['experiment_id'],
        'execution_authority_ref':pin('execution_authority_path') if seed.get('execution_authority_path') else None,
        'artifact_root_identity':root_identity(Path(os.environ.get('POLAR_ARTIFACT_ROOT','/data/artifacts')))}


def portable(value):
    if type(value) is float:
        require(__import__("math").isfinite(value),"REFERENCE_ARTIFACT_NONFINITE")
        return repr(value)
    if type(value) in (list,tuple):return [portable(x) for x in value]
    if type(value) is dict:return {k:portable(v) for k,v in value.items()}
    return value


def binding(config):
    return {k:v for k,v in config.items() if k!='execution_authority_ref'}


class ReferenceResearchService:
    def __init__(self,root,limit):
        self.store=HistoryStore(root,limit);self.results=ResearchResults(root,limit)

    def prepare(self,config):
        if config.get('schema')=='polar.calendar-study-config/1':
            from .calendar_study_service import prepare
            return prepare(self,config)
        if config.get('schema') == 'polar.raw-action-config/1':
            from .raw_action_service import prepare
            return prepare(self, config)
        if config.get('schema') == 'polar.scheduled-reference-config/1':
            from .scheduled_service import prepare
            return prepare(self, config)
        fields={'schema','namespace','profile_id','protocol_ref','input_ref','calendar_ref','timezone_ref','code',
                'code_revision','runtime_image_id','candidate_id','experiment_id','execution_authority_ref','artifact_root_identity'}
        require(type(config) is dict and set(config)==fields and config['schema']=='polar.reference-research-config/1'
                and config['namespace'] in ('INVENTED','RETAINED') and config['profile_id'] in PROFILES,'REFERENCE_CONFIG')
        require(config['artifact_root_identity']==root_identity(self.store.root),'PERSISTENT_ARTIFACT_ROOT_IDENTITY')
        require(config['code']==code_binding() and re.fullmatch('[a-f0-9]{40}',config['code_revision']) and
                re.fullmatch('sha256:[a-f0-9]{64}',config['runtime_image_id']),'REFERENCE_CODE_RUNTIME')
        profile=PROFILES[config['profile_id']]
        is_c = config['profile_id'] in (reference_c.C, reference_c.INVENTED_C)
        require((config['namespace']=='RETAINED' and config['profile_id'] in (A,B,reference_c.C)) or
                (config['namespace']=='INVENTED' and config['profile_id'] in (INVENTED_A,INVENTED_B,reference_c.INVENTED_C)),'REFERENCE_PROFILE_NAMESPACE')
        protocol=read_ref(config['protocol_ref']);calendar_raw=read_ref(config['calendar_ref']);tzraw=read_ref(config['timezone_ref'])
        retained=config['namespace']=='RETAINED'
        if retained:
            require(sha(protocol)==profile['protocol'] and sha(calendar_raw)==profile['calendar'] and
                    config['input_ref']['sha256']==profile.get('input',INPUT) and sha(tzraw)==TZ_SHA,'REFERENCE_FROZEN_PINS')
            require(platform.system()=='Linux' and platform.machine() in ('aarch64','x86_64') and
                    platform.python_version()=='3.13.18' and os.environ.get('POLAR_RUNTIME_IMAGE_ID')==config['runtime_image_id']
                    and sys.pycache_prefix is not None and os.environ.get('PYTHONDONTWRITEBYTECODE')=='1','REFERENCE_ACTUAL_RUNTIME')
            for name,version in [('numpy','2.2.6'),('scipy','1.15.3'),('nautilus-trader','1.231.0'),('threadpoolctl','3.6.0')]:
                require(importlib.metadata.version(name)==version,'REFERENCE_RUNTIME_VERSION')
        else:
            require(config['input_ref']['sha256'] not in (INPUT,reference_c.PROFILE['input']),'RETAINED_AS_INVENTED_FORBIDDEN')
        manifest=decode(read_ref(config['input_ref']))
        calendar=decode(calendar_raw)
        if not is_c:
            require((calendar['source_schedule']['sha256'] if profile['kind']=='RIDGE' else
                     calendar['source_reference_schedule_sha256'])==manifest['schedule']['sha256'], 'REFERENCE_CALENDAR_JOIN')
        if not retained:
            require(str(manifest.get('parent_dataset_revision','')).startswith('INVENTED-')
                    and manifest.get('rights')=='INVENTED_PUBLIC_TEST', 'REFERENCE_INVENTED_RIGHTS_PROVENANCE')
            require(manifest.get('provenance')=={'kind':'DETERMINISTIC_INVENTED_FIXTURE',
                    'producer':'polar-public-tests','source_payloads':'NONE'},'REFERENCE_INVENTED_RIGHTS_PROVENANCE')
            control=decode(protocol)
            require(set(control)=={'schema','profile_id','classification','fit_event','calendar_sha256','timezone_sha256','input_sha256'}
                    and control['schema']=='polar.invented-reference-protocol/1'
                    and control['profile_id']==config['profile_id'] and control['classification']=='INVENTED'
                    and control['calendar_sha256']==sha(calendar_raw) and control['timezone_sha256']==sha(tzraw)
                    and control['input_sha256']==config['input_ref']['sha256'],'REFERENCE_INVENTED_PROTOCOL_BINDING')
        if is_c:
            from .research_reference import pinned_bytes, reference_schedule
            require(retained or manifest['quotes']['sha256'] != reference_c.QUOTES, 'RETAINED_AS_INVENTED_FORBIDDEN')
            rows, _ = reference_schedule(decode(pinned_bytes(manifest['schedule'])))
            reference_c.admit_metadata(manifest, calendar, rows, retained=retained)
            calendar = reference_c.executable_calendar(calendar, rows, retained=retained)
            if retained:
                require(config['experiment_id'] == profile['registration'], 'REFERENCE_C_EXPERIMENT_BINDING')
        market=load_reference(config['input_ref'])
        if is_c:
            market['coverage'] = reference_c.coverage(market, retained=retained)
        tz=ZoneInfo.from_file(io.BytesIO(tzraw),key='America/New_York')
        fit_event=(datetime(2021,1,1,0,0,30,tzinfo=tz) if retained else datetime.fromisoformat(decode(protocol)['fit_event'])) if profile['kind']=='RIDGE' else None
        if retained and not is_c:
            require(market['symbols']==['AAPL','AMZN','TSLA','VTI'] and len(market['dates'])==2770 and
                    (calendar['training_rows']==192 if profile['kind']=='RIDGE' else
                     [(p['partition'],p['nav_points'],p['step_intervals']) for p in calendar['partitions']]==
                     [('TRAIN',1241,1240),('DEV',504,503),('TEST',967,966)]),'REFERENCE_SELECTED_COHORT')
        if profile['kind']=='PPO':
            from .reference_ppo import runtime_manifest
            runtime_manifest()
        return market,calendar,tz,fit_event

    def preflight(self,config):
        if config.get('schema')=='polar.calendar-study-config/1':
            from .calendar_study_service import preflight
            return preflight(self,config)
        if config.get('schema') == 'polar.raw-action-config/1':
            from .raw_action_service import preflight
            return preflight(self, config)
        if config.get('schema') == 'polar.scheduled-reference-config/1':
            from .scheduled_service import preflight
            return preflight(self, config)
        market,calendar,_,_=self.prepare(config)
        return {'schema':'polar.reference-preflight/1','status':'READY_FOR_BOUND_OPERATION',
            'profile_id':config['profile_id'],'operation_binding_sha256':sha(canonical(binding(config))),
            'input_rows':len(market['dates'])*len(market['symbols']),'training_rows':calendar.get('training_rows'),
            'strategy_execution':'NOT_RUN','scientific_starts':0}

    def _authority(self,config):
        if config['namespace']=='INVENTED':return None
        authority=decode(read_ref(config['execution_authority_ref']));profile=PROFILES[config['profile_id']]
        require(authority.get('schema')=='polar.reference-research-operation/1' and authority.get('action')=='ORIGINAL'
                and authority.get('binding_sha256')==sha(canonical(binding(config))),'REFERENCE_OPERATION_NOT_BOUND')
        methodraw=read_ref(authority['method_ref']);method=decode(methodraw)
        method_pass = (method.get('method_verdict') == 'PASS' and method.get('protocol',{}).get('sha256') == profile['protocol']
                       if config['profile_id'] == reference_c.C else
                       method.get('method_definition_verdict') == 'PASS' and method.get('protocol_sha256') == profile['protocol'])
        require(sha(methodraw)==profile['method'] and method_pass,'REFERENCE_METHOD_PIN')
        candidate=decode(read_ref(authority['candidate_ref']))
        require(candidate.get('schema')=='polar.native-hypothesis-reservation/1' and candidate.get('state')=='RESERVED'
                and candidate.get('candidate_id')==config['candidate_id']
                and candidate.get('experiment_registration_id')==profile['registration'],'REFERENCE_CANDIDATE_PIN')
        qualification=__import__('json').loads(read_ref(authority['qualification_ref']))
        required_test=('tests/test_reference_c_service.py' if config['profile_id']==reference_c.C else
                       'tests/test_reference_ppo_service.py' if profile['kind']=='PPO' else 'tests/test_reference_service.py')
        require(qualification.get('schema')=='polar.ci-result/1' and qualification.get('status')=='PASS' and
                qualification.get('candidate_sha')==config['code_revision'] and
                any(s in ('tests',required_test) for s in qualification.get('selection',[])),
                'REFERENCE_EXACT_TECHNICAL_QUALIFICATION')
        return authority

    def run(self,config):
        if config.get('schema')=='polar.calendar-study-config/1':
            from .calendar_study_service import run
            return run(self,config)
        if config.get('schema') == 'polar.raw-action-config/1':
            from .raw_action_service import run
            return run(self, config)
        if config.get('schema') == 'polar.scheduled-reference-config/1':
            from .scheduled_service import run
            return run(self, config)
        market,calendar,tz,fit_event=self.prepare(config);authority=self._authority(config)
        is_c = config['profile_id'] in (reference_c.C, reference_c.INVENTED_C)
        legs = reference_c.LEGS if is_c else LEGS
        if PROFILES[config['profile_id']]['kind']=='PPO':
            from .reference_ppo_service import run_ppo
            return run_ppo(self,config,market,calendar,tz,authority)
        family=sha(canonical({'profile':config['profile_id'],'input':config['input_ref']['sha256'],'namespace':config['namespace']}))
        parent='reference-research-attempts/'+family;aid=str(uuid.uuid4());directory=self.store.root/parent
        with self.store.locked():
            prior=sorted(p.name for p in directory.iterdir()) if directory.exists() else []
            require(not directory.is_symlink() and not prior,'REFERENCE_ORIGINAL_ALREADY_RECORDED')
            if authority is not None:require(authority.get('expected_prior_attempts')==prior,'REFERENCE_ATTEMPT_HISTORY')
            self.store._publish(parent,aid,{'start.json':canonical({'schema':'polar.reference-start/1','attempt_id':aid,
                'binding':binding(config),'status':'INTENT_CONSERVATIVE_DEBIT','actual_fit_state':'UNKNOWN_UNTIL_MATCHED_MODEL',
                'started_ns':time.time_ns()}),'config.json':canonical(config),'authority.json':canonical(authority)})
        try:
            # One fit for both phases. No future rows enter its scaler or labels.
            fitted=fit_ridge(market,calendar['training_cycles'],fit_event,tz)
            with self.store.locked():self.store._publish(parent+'/'+aid,'fit',{'model.json':canonical(fitted)})
            diagnostics={'TRAIN':diagnostic_mse(market,fitted,calendar['training_cycles'])}
            phases={}
            for phase,key,cycles in [('VALIDATION','validation_financial_grid','validation_complete_label_cycles'),
                                     ('FINAL','final_financial_grid','final_complete_label_cycles')]:
                plan=ridge_phase_plan(market,fitted,calendar[key],tz,legs=legs)
                simulation=bounded_native(plan)
                evaluation=evaluate_reference(simulation,kind='RIDGE',strategy=legs[0],simple=legs[1],benchmark=legs[2],phase=phase)
                diagnostics[phase]=diagnostic_mse(market,fitted,calendar[cycles])
                phases[phase]={'simulation':simulation,'evaluation':evaluation,'forecasts':plan['forecasts']}
            # Model-only binary64 fields remain explicit Python JSON numbers in private artifacts;
            # monetary/evaluation fields are exact cents or canonical strings, never these floats.
            files={'model.json':canonical(fitted),'phases.json':canonical(portable(phases)),'diagnostics.json':canonical(diagnostics),
                   'bindings.json':canonical(binding(config))}
            if is_c:
                files['coverage.json'] = canonical(market['coverage'])
                files['calendar.json'] = canonical(calendar)
            manifest={'schema':'polar.reference-semantic-manifest/1','files':{n:{'sha256':sha(b),'bytes':len(b)} for n,b in files.items()}}
            raw=canonical(manifest);sid='reference-experiment-'+sha(raw)
            with self.store.locked():self.store._publish('reference-research-experiments',sid,{**files,'manifest.json':raw},file_limit=32*1024**2)
            modelhash=sha(files['model.json']);publications={}
            for phase,items in phases.items():
                public=self._public_config(config,modelhash)
                if is_c:
                    self._c_public(public, market, calendar, sha(files['coverage.json']), sha(files['calendar.json']))
                public['forecast_diagnostics']={'TRAIN':diagnostics['TRAIN'],'PHASE':diagnostics[phase]}
                record=public_reference(public,items['simulation'],items['evaluation'],semantic_id=sid,semantic_hash=sha(raw),phase=phase)
                publications[phase]=self.results.publish(record)
            finish={'status':'SUCCESS','attempt_id':aid,'semantic_id':sid,'results':publications,'fit_calls':1,
                    'native_accounts':8,'financial_acceptance':'NOT_REVIEWED','actual_fit_state':'COMPLETED_MATCHED_MODEL',
                    'finished_ns':time.time_ns()}
        except BaseException as exc:
            finish={'status':'FAILED_UNFINALIZED','attempt_id':aid,'error':str(exc)[:240],
                    'actual_fit_state':'COMPLETED_MATCHED_MODEL' if 'fitted' in locals() else 'UNKNOWN',
                    'refund':False,'automatic_retry':False,'finished_ns':time.time_ns()}
            with self.store.locked():self.store._publish(parent+'/'+aid,'finish',{'record.json':canonical(finish),
                    'diagnostics.json':canonical(portable(getattr(exc,'events',[])))},file_limit=32*1024**2)
            raise
        with self.store.locked():self.store._publish(parent+'/'+aid,'finish',{'record.json':canonical(finish)})
        return finish

    @staticmethod
    def _c_public(public, market, calendar, coverage_hash, calendar_hash):
        public['primary_benchmark'] = reference_c.LEGS[2]
        public['question_label'] = 'Fixed54 conditional vendor-alias ridge reference-unit allocation'
        public['question_summary'] = 'One pooled fixed ridge versus matched momentum and EW_ELIGIBLE_MONTHLY on 54 source-conditioned vendor aliases; economic security count is not established.'
        early = sum(r.get('early_close_reference') is True for r in market['schedule'])
        public['clock_description'] = f"C uses its pinned {len(market['dates'])}-date vendor-all reference schedule including {early} modeled early closes. K next New York midnight, D one minute later, execution next reference close; observed source clocks remain unknown."
        public['partition_description'] = (f"One TRAIN fit on {calendar['training_rows']} rows; fresh VALIDATION "
            f"{calendar['validation_financial_grid']['nav_points']} NAV and FINAL {calendar['final_financial_grid']['nav_points']} NAV points. "
            f"Complete diagnostic labels: TRAIN{calendar['training_rows']}, VALIDATION{len(calendar['validation_complete_label_cycles'])*54}, "
            f"FINAL{len(calendar['final_complete_label_cycles'])*54}; no tuning or refit.")
        public['cohort_limitation'] = ('CONDITIONAL_54_VENDOR_ALIASES', 'Fixed54 source aliases selected from 100 by whole-period completeness and positive common-bar evidence, conditional on acquisition convenience, alphabetical frame, current relations and vintage. Economic security N50 is NOT_ESTABLISHED; no broad-US or point-in-time universe claim.')
        public['additional_limitations'] = [
            ('ALL100_METADATA_COVERAGE', 'All100 flags and eligibility reasons are supplied in source_coverage and the immutable coverage artifact. Completeness-only55 versus joint54; 46 excluded or unknown aliases have NOT_EVALUATED financial outcomes, not zero returns.'),
            ('UNKNOWN_ACTION_TIMING_MAPPING', 'All100 action checks unavailable without matched action boundaries; observed timing null and economic identity not admitted. Vendor-all adjustment is not independently certified investor total return.'),
            ('EXPOSED_A_HISTORY', 'C full freeze follows exposure to the four-asset A negative result. C is not a pristine process holdout; A-versus-C differences do not identify a clean causal effect.'),
            ('NO_FINANCIAL_COHORT_SENSITIVITY', 'Financial sensitivity to incomplete or unpaired aliases is NOT_ASSESSED. No robustness bounds, alternative cohort fit or economic N50 claim is supplied.')]
        public['source_coverage'] = market['coverage']['rows']
        public['provenance'] += [{'role':'all100_source_coverage','id':'coverage-'+coverage_hash,'sha256':coverage_hash},
            {'role':'executable_calendar','id':'calendar-'+calendar_hash,'sha256':calendar_hash}]

    def _public_config(self,config,modelhash):
        return {'protocol_id':config['profile_id'],'primary_strategy':LEGS[0],'primary_benchmark':LEGS[2],
            'question_label':'Fixed chronological ridge reference-unit allocation',
            'question_summary':'Pooled fixed ridge versus monthly momentum and equal weight under the frozen synthetic adjusted-reference-unit model.',
            'bindings':{'protocol_id':config['profile_id'],'protocol_sha256':config['protocol_ref']['sha256'],
                'data_revision':'selected-'+config['input_ref']['sha256'],'data_sha256':config['input_ref']['sha256'],
                'code_revision':config['code_revision'],'evaluator_revision':config['code_revision'],'runtime_id':config['runtime_image_id'],
                'producer_id':'polar-reference-research','candidate_id':config['candidate_id'],'experiment_id':config['experiment_id']},
            'clock_description':'A uses exact pinned reference closes including early closes; K next New York midnight and D one minute later; executions use next reference close.',
            'partition_description':'One TRAIN fit on matured 2016-2020 cycles; fixed VALIDATION 2021-2022 and separate FINAL 2023-2026 portfolios, no tuning or refit.',
            'provenance':[{'role':'trained_model','id':'model-'+modelhash,'sha256':modelhash},
                          {'role':'reference_input','id':'source-projection','sha256':config['input_ref']['sha256']},
                          {'role':'calendar_contract','id':'calendar-contract','sha256':config['calendar_ref']['sha256']}],
            'evidence_level':'RETAINED_DESCRIPTIVE' if config['namespace']=='RETAINED' else 'INVENTED_CONTROL'}

    def recompute(self,semantic_id):
        if semantic_id.startswith('calendar-study-experiment-'):
            from .calendar_study_service import recompute
            return recompute(self,semantic_id)
        if semantic_id.startswith('raw-action-experiment-'):
            from .raw_action_service import recompute
            return recompute(self, semantic_id)
        if semantic_id.startswith('scheduled-reference-experiment-'):
            from .scheduled_service import recompute
            return recompute(self, semantic_id)
        require(re.fullmatch('reference-experiment-[a-f0-9]{64}',semantic_id),'REFERENCE_EXPERIMENT_ID')
        parent='reference-research-experiments/'+semantic_id
        raw=read_file(self.store.root,parent+'/manifest.json',32*1024**2);require(semantic_id=='reference-experiment-'+sha(raw),'REFERENCE_MANIFEST_HASH')
        manifest=decode(raw);files={}
        names = set(manifest['files'])
        c_members = {'model.json','phases.json','diagnostics.json','bindings.json','coverage.json','calendar.json'}
        require(manifest['schema']=='polar.reference-ppo-semantic-manifest/1' or
                names in ({'model.json','phases.json','diagnostics.json','bindings.json'}, c_members),'REFERENCE_SEMANTIC_MEMBERS')
        for name,pin in manifest['files'].items():
            body=read_file(self.store.root,parent+'/'+name,32*1024**2)
            require(len(body)==pin['bytes'] and sha(body)==pin['sha256'],'REFERENCE_SEMANTIC_HASH')
            files[name]=body
        if manifest['schema']=='polar.reference-ppo-semantic-manifest/1':
            from .reference_ppo_service import recompute_ppo
            return {**recompute_ppo(files),'semantic_id':semantic_id}
        diagnostics=decode(files['diagnostics.json'])
        is_c = decode(files['bindings.json'])['profile_id'] in (reference_c.C, reference_c.INVENTED_C)
        require((names == c_members) == is_c, 'REFERENCE_C_SEMANTIC_MEMBERS')
        legs = reference_c.LEGS if is_c else LEGS
        for diagnostic in diagnostics.values():
            require(canonical(diagnostic_from_records(diagnostic['rows']))==canonical(diagnostic),'REFERENCE_DIAGNOSTIC_RECOMPUTE')
        phases=decode(files['phases.json'])
        for phase,items in phases.items():
            expected=evaluate_reference(items['simulation'],kind='RIDGE',strategy=legs[0],simple=legs[1],benchmark=legs[2],phase=phase)
            require(canonical(expected)==canonical(items['evaluation']),'REFERENCE_RECOMPUTE_MISMATCH')
        return {'status':'REPRODUCED','semantic_id':semantic_id,'model_calls':0,'native_calls':0,'store_writes':0}
