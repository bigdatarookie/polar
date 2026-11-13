"""Manifest-bound report-only projection. No execution, recompute or publication."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from .gym_contract import canonical, sha, decode, GymError
from .gym_service import code_binding
from .history_bundle import read_file, safe_root, HistoryError
from .reference_projection import public_reference
from .research_results import validate_result, MAX_RESULT, ResearchError
from .scheduled_policy import profile_value
from .scheduled_service import public_config, project_diagnostics, MEMBERS, SEMANTIC


class Incomplete(ValueError):
    pass


def need(value, keys, location):
    if not isinstance(value,dict):raise ValueError('SAVED_REPORT_FIELD_TYPE')
    missing=set(keys)-set(value)
    if missing:raise Incomplete(location+':'+','.join(sorted(missing)))


def require(ok, code):
    if not ok:raise ValueError(code)


def diagnostic_inputs(value, profile):
    """Require saved operands used by the formatter; never fill missing state."""
    ids=[leg['id'] for leg in profile['legs']]
    need(value,ids,'diagnostics')
    for identity in ids:
        d=value[identity];need(d,['daily_tail','drawdown','calendar_months','worst_horizons','subperiods'],identity)
        need(d['daily_tail'],['actual_tail_fraction','lower_tail_mean_return','lower_return_threshold','expected_shortfall_loss','k'],'daily_tail')
        need(d['drawdown'],['status','time_underwater_fraction','peak','trough','recovery','peak_to_trough_intervals','peak_to_recovery_intervals','censored_peak_to_terminal_intervals'],'drawdown')
        need(d['calendar_months'],['complete_count','partial_count','worst_full_month'],'months')
        need(d['calendar_months']['worst_full_month'],['net_return'],'worst_month')
        need(d['worst_horizons'],['1','21','63'],'horizons')
        for h in ('1','21','63'):need(d['worst_horizons'][h],['net_return'],'horizon')
        values=[d['daily_tail'][k] for k in ('actual_tail_fraction','lower_tail_mean_return','lower_return_threshold','expected_shortfall_loss','k')]
        values += [d['drawdown']['time_underwater_fraction'],d['calendar_months']['complete_count'],d['calendar_months']['worst_full_month']['net_return']]
        values += [d['worst_horizons'][h]['net_return'] for h in ('1','21','63')]
        for value in values:
            if type(value) is not int:need(value,['value','status','reason'],'diagnostic_value')
        require(isinstance(d['subperiods'],list),'SAVED_REPORT_SEGMENTS')
        if len(d['subperiods'])!=len(profile['subperiods']):raise Incomplete('subperiod_count')
        for segment in d['subperiods']:
            need(segment,['first_return_date','last_return_date','initial_date','intervals','metrics','costs'],'segment')
            if 'requested_initial_anchor' in segment:need(segment,['status','reason'],'segment_anchor')
            need(segment['metrics'],['net_total_return','sharpe_252_rf0','max_drawdown','net_cagr_act36525','annual_vol_252'],'segment_metrics')
            need(segment['costs'],['total_fee_usd','normalization_initial_nav_cents','gross_exact_notional_usd','gross_settled_notional_usd','positive_fill_count','gross_notional_over_initial'],'segment_costs')
            for section,keys in [('metrics',('net_total_return','sharpe_252_rf0','max_drawdown','net_cagr_act36525','annual_vol_252')),('costs',('total_fee_usd','gross_exact_notional_usd','gross_settled_notional_usd','positive_fill_count','gross_notional_over_initial'))]:
                for key in keys:need(segment[section][key],['value','status','reason'],'segment_value')


def project_saved_report(store_root, semantic_id, *, candidate_id, experiment_id, report_revision, runtime_image_id):
    """Read five original members; return a separate private technical artifact.

    Declared revision/runtime require independent launch custody. Actual code/schema
    hashes are recorded separately. Original calculation bindings are never edited.
    """
    require(bool(re.fullmatch(SEMANTIC+'[a-f0-9]{64}',semantic_id)),'SAVED_REPORT_SEMANTIC_ID')
    require(bool(re.fullmatch('[a-f0-9]{40}',report_revision)) and bool(re.fullmatch('sha256:[a-f0-9]{64}',runtime_image_id)),'SAVED_REPORT_RUNTIME_ID')
    root=safe_root(store_root)
    relative_directory='reference-research-experiments/'+semantic_id
    body={'schema':'polar.saved-report-projection/1','original_semantic_id':semantic_id,
          'candidate_id':candidate_id,'experiment_id':experiment_id,
          'report_source':{'declared_revision':report_revision,'declared_runtime_image':runtime_image_id,
                           'code':code_binding(),'runtime_custody':'DECLARED_NOT_AUTHENTICATED_BY_THIS_FUNCTION'},
          'meaning':'Technical report/schema admission only; no financial or execution verdict',
          'input_store_writes':0,'native_calls':0,'policy_calls':0,'evaluation_recomputations':0,
          'diagnostic_recomputations':0,'source_loads':0,'publications':0,'registry_writes':0,'quote_valuations':0,
          'original_attempt_transition':'NONE','missing_historical_witnesses':'NOT_RECONSTRUCTED'}
    pins={}
    def member(name):
        path=root/relative_directory/name
        if not path.exists() and not path.is_symlink():raise Incomplete(name)
        return read_file(root,relative_directory+'/'+name,32*1024**2)
    try:
        folder=root/relative_directory
        if not folder.exists() and not folder.is_symlink():raise Incomplete('semantic_directory')
        safe_root(folder)
        raw=member('manifest.json');require(semantic_id==SEMANTIC+sha(raw),'SAVED_REPORT_MANIFEST_ID')
        manifest=decode(raw);need(manifest,['schema','files'],'manifest')
        require(set(manifest)=={'schema','files'} and manifest['schema']=='polar.scheduled-reference-semantic-manifest/1' and isinstance(manifest['files'],dict),'SAVED_REPORT_MANIFEST')
        require(not set(manifest['files'])-MEMBERS,'SAVED_REPORT_MEMBER_SET')
        if set(manifest['files'])!=MEMBERS:raise Incomplete('manifest_members')
        files={}
        for name,pin in manifest['files'].items():
            require(type(pin) is dict and set(pin)=={'sha256','bytes'} and type(pin['sha256']) is str and bool(re.fullmatch('[a-f0-9]{64}',pin['sha256'])) and type(pin['bytes']) is int and 0<pin['bytes']<=32*1024**2,'SAVED_REPORT_MEMBER_PIN')
            value=member(name);require(len(value)==pin['bytes'] and sha(value)==pin['sha256'],'SAVED_REPORT_MEMBER_HASH')
            pins[name]=dict(pin);files[name]=decode(value)
        p=profile_value(files['profile.json']);require(p['schema']=='polar.scheduled-reference-profile/10','SAVED_REPORT_PROFILE')
        cfg=files['bindings.json'];need(cfg,['code','code_revision','runtime_image_id','namespace','profile_ref','protocol_ref','input_ref','calendar_ref','timezone_ref','candidate_id','experiment_id'],'bindings')
        require(cfg['candidate_id']==candidate_id and cfg['experiment_id']==experiment_id,'SAVED_REPORT_CALCULATION_IDENTITY')
        for key in ('profile','protocol','input','calendar','timezone'):
            need(cfg[key+'_ref'],['sha256'],'binding_ref')
            require(type(cfg[key+'_ref']['sha256']) is str and bool(re.fullmatch('[a-f0-9]{64}',cfg[key+'_ref']['sha256'])),'SAVED_REPORT_REFERENCE_HASH')
        for key in ('protocol','input','calendar','timezone'):
            require(cfg[key+'_ref']['sha256']==p[key+'_sha256'],'SAVED_REPORT_PROFILE_BINDING')
        require(type(cfg['code']) is dict and bool(cfg['code']) and all(type(v) is str and bool(re.fullmatch('[a-f0-9]{64}',v)) for v in cfg['code'].values()),'SAVED_REPORT_CALCULATION_CODE')
        require(bool(re.fullmatch('[a-f0-9]{40}',cfg['code_revision'])) and bool(re.fullmatch('sha256:[a-f0-9]{64}',cfg['runtime_image_id'])),'SAVED_REPORT_CALCULATION_SOURCE')
        need(files['calendar.json'],['phases'],'calendar')
        require(set(files['phases.json'])==set(files['calendar.json']['phases'])=={'FINAL'},'SAVED_REPORT_PHASE_IDENTITY')
        grid=files['calendar.json']['phases']['FINAL'];need(grid,['nav_dates','nav_points','return_count'],'calendar_grid')
        require(type(grid['nav_dates']) is list and type(grid['nav_points']) is int and type(grid['return_count']) is int and grid['nav_points']==len(grid['nav_dates'])==grid['return_count']+1,'SAVED_REPORT_CALENDAR_COUNT')
        need(files['diagnostics.json'],['FINAL'],'diagnostic_phases')
        data=files['phases.json']['FINAL'];need(data,['simulation','evaluation'],'phase')
        ids={leg['id'] for leg in p['legs']}
        for key in ('simulation','evaluation'):
            need(data[key],['legs'],key)
            require(len(data[key]['legs'])==len(ids) and {x['id'] for x in data[key]['legs']}==ids,'SAVED_REPORT_LEG_IDENTITY')
        diagnostic_inputs(files['diagnostics.json']['FINAL'],p)
        public=public_config(cfg,p);public['model_price_mapping']=p['model_price_mapping']
        record=public_reference(public,data['simulation'],data['evaluation'],semantic_id=semantic_id,semantic_hash=sha(raw),phase='FINAL')
        require([x[:10] for x in record['grid']]==grid['nav_dates'],'SAVED_REPORT_GRID_IDENTITY')
        for series in record['series']:series['label']=next(x['label'] for x in p['legs'] if x['id']==series['id'])
        project_diagnostics(record,files['diagnostics.json']['FINAL'])
        record=validate_result(record);require(len(canonical(record))<=MAX_RESULT,'SAVED_REPORT_RESULT_SIZE')
        body.update(status='REPORT_SCHEMA_VALID',records={'FINAL':record},original_calculation={'code_revision':cfg['code_revision'],'runtime_image_id':cfg['runtime_image_id'],'bindings_sha256':pins['bindings.json']['sha256']})
    except Incomplete as exc:
        body.update(status='INCOMPLETE_INPUT',missing=[str(exc)])
    except (KeyError,IndexError) as exc:
        body.update(status='INCOMPLETE_INPUT',missing=['SAVED_PROJECTION_FIELD'])
    except (ValueError,TypeError,HistoryError,GymError,ResearchError) as exc:
        body.update(status='INVALID_INPUT',reason=str(exc) if re.fullmatch('[A-Z][A-Z0-9_]{1,100}',str(exc)) else 'SAVED_REPORT_INVALID')
    body['verified_members']=pins
    return {**body,'technical_artifact_id':'saved-report-projection-'+sha(canonical(body))}


def write_artifact(output, artifact, *, input_store_root):
    """Exclusive private file in an existing task-owned directory outside inputs."""
    output=Path(output).absolute();parent=safe_root(output.parent);source=safe_root(input_store_root)
    require(not parent.is_relative_to(source) and parent.stat().st_uid==os.geteuid() and bool(re.fullmatch('[A-Za-z0-9_.-]+',output.name)) and output.name not in ('.','..'),'SAVED_REPORT_OUTPUT_LOCATION')
    # No store/registry or existing artifact is modified. A failed write is retained
    # as a task-owned partial rather than silently replacing another artifact.
    fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        f=os.open(output.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        with os.fdopen(f,'wb') as stream:stream.write(canonical(artifact));stream.flush();os.fsync(stream.fileno())
        os.fsync(fd)
    finally:os.close(fd)


def main():
    p=argparse.ArgumentParser();p.add_argument('--store-root',required=True);p.add_argument('--semantic-id',required=True);p.add_argument('--candidate-id',required=True);p.add_argument('--experiment-id',required=True);p.add_argument('--report-revision',required=True);p.add_argument('--runtime-image-id',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    value=project_saved_report(a.store_root,a.semantic_id,candidate_id=a.candidate_id,experiment_id=a.experiment_id,report_revision=a.report_revision,runtime_image_id=a.runtime_image_id)
    write_artifact(a.output,value,input_store_root=a.store_root)
    print(json.dumps({'status':value['status'],'technical_artifact_id':value['technical_artifact_id']}))
    return 0 if value['status']=='REPORT_SCHEMA_VALID' else 2


if __name__=='__main__':sys.exit(main())
