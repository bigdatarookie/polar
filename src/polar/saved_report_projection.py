"""Manifest-bound report-only projection. No execution, recompute or publication."""
from datetime import datetime, timedelta
import argparse
import json
import os
from pathlib import Path
import re
import sys

from .gym_contract import canonical, sha, decode, GymError
from .ci_research import utc_text
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
        for operand in values:
            if type(operand) is not int:need(operand,['value','status','reason'],'diagnostic_value')
        require(isinstance(d['subperiods'],list),'SAVED_REPORT_SEGMENTS')
        if len(d['subperiods'])!=len(profile['subperiods']):raise Incomplete('subperiod_count')
        for segment in d['subperiods']:
            need(segment,['first_return_date','last_return_date','initial_date','intervals','metrics','costs'],'segment')
            if 'requested_initial_anchor' in segment:need(segment,['status','reason'],'segment_anchor')
            need(segment['metrics'],['net_total_return','sharpe_252_rf0','max_drawdown','net_cagr_act36525','annual_vol_252'],'segment_metrics')
            need(segment['costs'],['total_fee_usd','normalization_initial_nav_cents','gross_exact_notional_usd','gross_settled_notional_usd','positive_fill_count','gross_notional_over_initial'],'segment_costs')
            for section,keys in [('metrics',('net_total_return','sharpe_252_rf0','max_drawdown','net_cagr_act36525','annual_vol_252')),('costs',('total_fee_usd','gross_exact_notional_usd','gross_settled_notional_usd','positive_fill_count','gross_notional_over_initial'))]:
                for key in keys:need(segment[section][key],['value','status','reason'],'segment_value')


def report_calendar(calendar):
    """Validate saved date/clock metadata only; never follow schedule refs."""
    require(type(calendar) is dict,'SAVED_REPORT_CALENDAR_FORM')
    if calendar.get('schema')=='polar.prospective-fixed-allocation-calendar/1':
        fields={'schema','parent_schedule','dates','initial_date','terminal_date','nav_points','returns',
                'annual_targets','terminal_EXIT','clock_scope','source_schedule_rows'}
        need(calendar,fields,'fixed_calendar')
        require(set(calendar)==fields,'SAVED_REPORT_CALENDAR_FORM')
        rows=calendar['source_schedule_rows']
        require(type(rows) is list and bool(rows),'SAVED_REPORT_SCHEDULE')
        for row in rows:
            need(row,['date','reference_close_utc','next_reference_date'],'source_schedule_row')
            require(type(row['date']) is str and type(row['reference_close_utc']) is str and
                    (row['next_reference_date'] is None or type(row['next_reference_date']) is str),
                    'SAVED_REPORT_METADATA_TYPE')
        require(type(calendar['dates']) is list and all(type(d) is str for d in calendar['dates']) and
                type(calendar['initial_date']) is str and type(calendar['terminal_date']) is str and
                type(calendar['annual_targets']) is list,'SAVED_REPORT_METADATA_TYPE')
        for event in calendar['annual_targets']+[calendar['terminal_EXIT']]:
            keys=['formation_date','K','D','execution_date','reference_execution_close_utc']
            need(event,keys,'calendar_event')
            require(all(type(event[k]) is str for k in keys),'SAVED_REPORT_METADATA_TYPE')
        # parent_schedule and clock_scope are opaque producer annotations. Their
        # exact saved bytes stay manifest-bound; never follow or reinterpret them.
        from .scheduled_fixed import calendar_value
        from .reference_ridge_plan import nanoseconds
        grid=calendar_value({k:v for k,v in calendar.items() if k!='source_schedule_rows'},rows)['FINAL']
        by_date={row['date']:row for row in rows};closes=[]
        for day in grid['nav_dates']:
            close=datetime.fromisoformat(by_date[day]['reference_close_utc'].replace('Z','+00:00'))
            require(close.utcoffset()==timedelta(0) and close.date().isoformat()==day,'SAVED_REPORT_SCHEDULE_CLOCK')
            closes.append(nanoseconds(close))
        return grid,closes
    require(calendar.get('schema') in (None,'polar.scheduled-policy-calendar/1') and
            not set(calendar)&{'dates','initial_date','terminal_date','nav_points','returns','annual_targets','terminal_EXIT'},
            'SAVED_REPORT_CALENDAR_FORM')
    need(calendar,['phases'],'calendar')
    require(set(calendar['phases'])=={'FINAL'},'SAVED_REPORT_PHASE_IDENTITY')
    return calendar['phases']['FINAL'],None


def fixed_plan_metadata(data,profile,grid,closes):
    """Join saved plan metadata to the saved calendar, without reading prices."""
    need(data,['plan'],'fixed_phase');plan=data['plan']
    need(plan,['grid','decisions','model_price_mapping','quantity_unit'],'fixed_plan')
    need(data['simulation'],['quantity_unit'],'fixed_simulation')
    mapping=profile['model_price_mapping']
    require(canonical(plan['model_price_mapping'])==canonical(mapping) and plan['quantity_unit']==data['simulation']['quantity_unit']==mapping['active_unit'],
            'SAVED_REPORT_MODEL_MAPPING')
    require(type(plan['grid']) is list and len(plan['grid'])==len(closes),'SAVED_REPORT_PLAN_GRID')
    for i,row in enumerate(plan['grid']):
        expected={'date':grid['nav_dates'][i],'nominal_ns':closes[i],'sample_ns':closes[i]+1000,
                  'initial':i==0,'terminal':i==len(closes)-1}
        need(row,expected,'plan_grid_row')
        require(all(type(row[k]) is type(v) and row[k]==v for k,v in expected.items()),'SAVED_REPORT_PLAN_GRID')
    events=grid['decisions']+[grid['terminal_exit']]
    require(type(plan['decisions']) is list and len(plan['decisions'])==len(events),'SAVED_REPORT_PLAN_EVENTS')
    for i,(row,event) in enumerate(zip(plan['decisions'],events)):
        expected={'day':event['execution_date'],'formation':event['signal_date'],'known_ns':event['known_ns'],
                  'decision_ns':event['decision_ns'],'open_ns':closes[grid['nav_dates'].index(event['execution_date'])],'kind':'REFERENCE'}
        need(row,[*expected,'instructions'],'plan_event')
        require(all(type(row[k]) is type(v) and row[k]==v for k,v in expected.items()),'SAVED_REPORT_PLAN_EVENTS')
        require(type(row['instructions']) is dict and set(row['instructions'])=={leg['id'] for leg in profile['legs']},'SAVED_REPORT_PLAN_INSTRUCTIONS')
        for leg in profile['legs']:
            instruction=row['instructions'][leg['id']]
            need(instruction,['kind'],'plan_instruction')
            kind='EXIT' if i==len(events)-1 else 'HOLD' if leg['rule']=='CASH' else 'TARGET'
            require(instruction['kind']==kind,'SAVED_REPORT_PLAN_INSTRUCTIONS')
            if kind=='TARGET':
                need(instruction,['weights'],'plan_instruction')
                require(canonical(instruction['weights'])==canonical(leg['weights']),'SAVED_REPORT_PLAN_INSTRUCTIONS')


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
        grid,calendar_closes=report_calendar(files['calendar.json'])
        require(set(files['phases.json'])=={'FINAL'},'SAVED_REPORT_PHASE_IDENTITY')
        need(grid,['nav_dates','nav_points','return_count'],'calendar_grid')
        require(type(grid['nav_dates']) is list and type(grid['nav_points']) is int and type(grid['return_count']) is int and grid['nav_points']==len(grid['nav_dates'])==grid['return_count']+1,'SAVED_REPORT_CALENDAR_COUNT')
        need(files['diagnostics.json'],['FINAL'],'diagnostic_phases')
        data=files['phases.json']['FINAL'];need(data,['simulation','evaluation'],'phase')
        ids={leg['id'] for leg in p['legs']}
        for key in ('simulation','evaluation'):
            need(data[key],['legs'],key)
            require(len(data[key]['legs'])==len(ids) and {x['id'] for x in data[key]['legs']}==ids,'SAVED_REPORT_LEG_IDENTITY')
        # The public formatter uses the first leg's timestamps and consumes only
        # nav_count-1 returns. Check every saved operand before those details can
        # be discarded; formatting must not conceal conflicting saved evidence.
        common=None
        for leg in data['simulation']['legs']:
            need(leg,['nav'],'simulation_leg')
            require(type(leg['nav']) is list and len(leg['nav'])==grid['nav_points'],'SAVED_REPORT_LEG_GRID')
            for row in leg['nav']:need(row,['nominal_ns'],'nav_row')
            timestamps=[row['nominal_ns'] for row in leg['nav']]
            require(all(type(t) is int for t in timestamps) and
                    all(a<b for a,b in zip(timestamps,timestamps[1:])),'SAVED_REPORT_LEG_GRID')
            if common is None:common=timestamps
            require(timestamps==common,'SAVED_REPORT_LEG_GRID')
        require([utc_text(t)[:10] for t in common]==grid['nav_dates'],'SAVED_REPORT_GRID_IDENTITY')
        if calendar_closes is not None:
            require(common==calendar_closes,'SAVED_REPORT_CALENDAR_CLOCK')
            fixed_plan_metadata(data,p,grid,calendar_closes)
        for leg in data['evaluation']['legs']:
            need(leg,['returns'],'evaluation_leg')
            require(type(leg['returns']) is list and len(leg['returns'])==grid['return_count'],'SAVED_REPORT_RETURN_COUNT')
        diagnostic_inputs(files['diagnostics.json']['FINAL'],p)
        if calendar_closes is not None:
            for leg in p['legs']:
                d=files['diagnostics.json']['FINAL'][leg['id']]
                need(d,['schema'],'fixed_diagnostic')
                require(d['schema']=='polar.fixed-allocation-saved-diagnostics/1','SAVED_REPORT_FIXED_DIAGNOSTIC_SCHEMA')
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
    except (ValueError,TypeError,OverflowError,HistoryError,GymError,ResearchError) as exc:
        body.update(status='INVALID_INPUT',reason=str(exc) if re.fullmatch('[A-Z][A-Z0-9_]{1,100}',str(exc)) else 'SAVED_REPORT_INVALID')
    body['verified_members']=pins
    return {**body,'technical_artifact_id':'saved-report-projection-'+sha(canonical(body))}


def write_artifact(output, artifact, *, input_store_root):
    """Exclusive private file in an existing task-owned directory outside inputs."""
    require(type(artifact) is dict and artifact.get('schema')=='polar.saved-report-projection/1' and
            artifact.get('technical_artifact_id')=='saved-report-projection-'+sha(canonical({k:v for k,v in artifact.items() if k!='technical_artifact_id'})), 'SAVED_REPORT_ARTIFACT_ID')
    output=Path(output).absolute();parent=safe_root(output.parent).resolve();source=safe_root(input_store_root).resolve()
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
