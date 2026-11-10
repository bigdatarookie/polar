"""Closed S1 semantic projection and read-only stored proof verification."""
import re

from .hyp008_s1_contract import canonical,ref,require,validate,closed,SEMANTIC,COMMON,STAGES

SCOPE='DESCRIPTIVE_DEVELOPMENT_SOURCE_COHORT'
SHAPES={
 'source.json':('polar.hyp008-s1-source/1',('schema','inputs','graph','metadata_refs','closure_checks','assurance')),
 'transform.json':('polar.hyp008-s1-transform/1',('schema','slots','training_count','columns','training_conversion','training_z')),
 'representations.json':('polar.hyp008-s1-representations/1',('schema','training_ids','training_targets','scoring','targets','history')),
 'tree.json':('polar.hyp008-s1-tree/1',('schema','parameters','parameter_provenance','nominal_estimators','actual_iterations','model_text','native_precision','default_hashes')),
 'linear.json':('polar.hyp008-s1-linear/1',('schema','theta','certificate_request','proof','solver','limits','representation')),
 'forecasts.json':('polar.hyp008-s1-forecasts/1',('schema','order','methods','tree_predictions','linear_predictions')),
 'limitations.json':('polar.hyp008-s1-limitations/1',('schema','claim_scope','source_assurance','native_limits','interpretation_refs','tree_structure')),
}
MASK_FIELDS=('schema','protocol','owner_pins','dataset_revision','source_class','source_binding','metadata_census',
 'F','expected_ready','S','full_census','training','C','I','E','P','lineage_status','reason','scientific_starts','numeric_work_performed')


def tree_structure(tree):
    if tree is None:return {'status':'NOT_OBSERVED','reason':'MODEL_NOT_RETURNED','trees':None}
    text=tree['model_text'];require(type(text) is str and len(text.encode())<=16*1024**2,'MODEL_BOUND')
    trees=[];current=None
    for line in text.splitlines():
        if line.startswith('Tree='):
            require(re.fullmatch(r'Tree=[0-9]{1,6}',line) is not None,'MODEL_TREE_HEADER')
            current={'index':int(line[5:]),'leaves':None,'split_features':[]};trees.append(current)
        elif current is not None and line.startswith('num_leaves='):
            token=line.split('=',1)[1];require(re.fullmatch('[0-9]{1,6}',token) is not None,'MODEL_LEAF_HEADER')
            current['leaves']=int(token)
        elif current is not None and line.startswith('split_feature='):
            tokens=line.split('=',1)[1].split();require(len(tokens)<=10000 and all(re.fullmatch('[0-9]{1,6}',s) for s in tokens),'MODEL_SPLIT_HEADER')
            current['split_features']=[int(s) for s in tokens]
    if not trees or any(t['leaves'] is None for t in trees):
        return {'status':'NOT_OBSERVED','reason':'SERIALIZED_STRUCTURE_NOT_RECOGNIZED','trees':None}
    for tree_row in trees:tree_row['splits']=len(tree_row['split_features'])
    return {'status':'OBSERVED_SERIALIZED_MODEL','reason':None,'trees':trees,
        'actual_iterations':tree['actual_iterations'],'route_claim':'ACTUAL_LOCKED_RUNTIME_REQUIRES_ITS_OWN_EVIDENCE',
        'conditional_interpretation':'NONLINEAR_ADDITIVE_NOT_LEARNED_CROSS_FEATURE_INTERACTION_IF_QUALIFIED_ROUTE',
        'training_metadata_upper_bound':245,'upper_bound_is_not_actual_training_count':True}


def limitations(config,tree):
    return {'schema':'polar.hyp008-s1-limitations/1','claim_scope':SCOPE,
        'source_assurance':'SOURCE_COHORT_CAPABILITY_ONLY;ORIGINAL_HYP_UNTESTED;FINANCIAL_NOT_ASSESSED',
        'native_limits':['SOURCE_BOUND_FLOAT32_LABEL_SCORE','HIGHS_FULL_CPP_REVISION_AND_PER_TARGET_FLAGS_UNKNOWN',
                         'BINARY_BOUND_UNEXPOSED_DEFAULTS','ENV_THREADS_ONE_IS_NOT_PROOF_OF_LP_THREAD_COUNT'],
        'interpretation_refs':config['interpretation_refs'],'tree_structure':tree_structure(tree)}


def project(config,source,masks,components,result, *, unresolved_native=False):
    require(set(components)<=set(SEMANTIC)-COMMON,'SEMANTIC_COMPONENT_NAMES')
    if result['status']=='COMPLETE':
        artifacts=result['artifacts']
        for key,name in (('tree','tree.json'),('linear','linear.json'),('history','history.json')):
            if key in artifacts:components[name]=artifacts[key]
    elif result.get('artifacts'):
        for key,name in (('tree','tree.json'),('linear','linear.json'),('history','history.json')):
            if key in result['artifacts']:components[name]=result['artifacts'][key]
    if result.get('forecasts') is not None:
        artifacts=result.get('artifacts',{})
        components['forecasts.json']={'schema':'polar.hyp008-s1-forecasts/1','order':masks['I'],
            'methods':result['forecasts'],'tree_predictions':artifacts.get('tree_predictions',{}),
            'linear_predictions':artifacts.get('linear_predictions',{})}
    if result.get('evaluation') is not None:components['evaluation.json']=result['evaluation']
    raw={name:canonical(value) for name,value in components.items()}
    component_status={}
    stage_for={'tree.json':'TREE','linear.json':'LINEAR','history.json':'HISTORICAL_PASS'}
    for name in set(SEMANTIC)-COMMON:
        stage=result.get('stages',{}).get(stage_for.get(name),'NOT_RUN')
        status=('PRODUCED' if name in raw else 'ARTIFACT_NOT_RETURNED' if stage!='NOT_RUN'
            else 'UNAVAILABLE' if result['status']=='PLANNED_FAMILY_UNAVAILABLE'
            and name not in stage_for else 'NOT_RUN')
        component_status[name]={'status':status,'reason':None if name in raw else result.get('reason') or 'NOT_PRODUCED',
                                'ref':ref(raw[name]) if name in raw else None}
    status=result['status']
    if unresolved_native and status=='COMPLETE':status='PLANNED_FAMILY_UNAVAILABLE'
    family={'schema':'polar.hyp008-s1-family/1','status':status,'component_status':result['status'],
        'reason':'NATIVE_CALL_EVIDENCE_UNRESOLVED' if unresolved_native else result.get('reason'),
        'stage':result.get('stage'),'detail':result.get('detail'),
        'stages':result.get('stages',dict.fromkeys(STAGES,'NOT_RUN')),'components':component_status,'claim_scope':SCOPE}
    validate('Family',family)
    values={'config.json':config,'source.json':source,'masks.json':masks,'family.json':family,
            'limitations.json':limitations(config,components.get('tree.json')),**components}
    validate_producers(values)
    return {n:canonical(v) for n,v in values.items()}


def validate_producers(values):
    validate('Config',values['config.json']);validate('Family',values['family.json'])
    closed(values['masks.json'],MASK_FIELDS,'polar.hyp008-s1-masks/1')
    for name,(schema,keys) in SHAPES.items():
        if name in values:closed(values[name],keys,schema)
    masks=values['masks.json'];I=masks['I'];P=masks['P']
    _nested(values)
    if 'history.json' in values:require(set(values['history.json'])<=set(I),'HISTORY_MEMBER_SET')
    if 'evaluation.json' in values:
        v=values['evaluation.json'];fields=('schema','status','reason','I','P','rows','aggregate')
        require(set(v) in (set(fields),set(fields)|{'financial'}) and v['schema']=='polar.hyp008-s1-evaluation/1'
                and v['I']==I and v['P']==P,'EVALUATION_SCHEMA')
    if values['family.json']['status']=='COMPLETE':
        require(set(values)==set(SEMANTIC),'COMPLETE_FILE_SET')
        require(all(set(values['forecasts.json']['methods'][k])==set(I) for k in ('TREE','LINEAR','HISTORICAL')),'COMPLETE_FORECASTS')
        require(set(values['history.json'])==set(I),'COMPLETE_HISTORY')


def verify_stored_values(values):
    validate_producers(values)
    from .hyp008_s1_linear import verify_saved_linear
    from .hyp008_s1_evaluation import evaluate_common
    if 'linear.json' in values:
        proof=verify_saved_linear(values['linear.json'])
        require(canonical(proof)==canonical(values['linear.json']['proof']),'STORED_FULL_PROOF')
    if 'evaluation.json' in values:
        targets={r['opportunity_id']:r['rounding']['bits'] for r in values['representations.json']['targets']}
        checked=evaluate_common(values['masks.json'],values['forecasts.json']['methods'],targets)
        require(canonical(checked)==canonical(values['evaluation.json']),'STORED_EVALUATION')
    # No fit/generate/LP/historical/predict/source conversion on this path.
    return {'status':'STORED_RECORDS_VERIFIED','numeric_proof_status':'REPRODUCED' if 'linear.json' in values else 'NOT_PRODUCED','family_status':values['family.json']['status'],
            'scientific_starts':0,'financial':'NOT_ASSESSED'}


def _keys(value,names,reason):
    require(type(value) is dict and set(value)==set(names),reason)


def _bits(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{16}',value) is not None,'STORED_BITS')
    raw=int(value,16);require(((raw>>52)&2047)!=2047 and raw!=1<<63,'STORED_FINITE_CANONICAL_ZERO')


def _rounding(value):
    _keys(value,('bits','dyadic','residual'),'ROUNDING_SCHEMA');_bits(value['bits'])
    for key in ('dyadic','residual'):_keys(value[key],('numerator','denominator'),'RATIO_SCHEMA')


def _nested(values):
    from .hyp008_s1_numeric import SLOTS
    from .hyp008_s1_source import OWNER_PINS,PROTOCOL
    m=values['masks.json'];cfg=values['config.json'];I=m['I'];P=m['P']
    require(m['protocol']==PROTOCOL and m['owner_pins']==list(OWNER_PINS) and
        canonical(m['source_binding'])==canonical(cfg['source_binding']) and
        m['source_class']==cfg['source_binding']['source_class'] and
        m['dataset_revision']==cfg['source_binding']['dataset_revision'],'MASK_BINDING')
    require(type(m['full_census']) is list and len(set(m['full_census']))==len(m['full_census'])
        and m['full_census']==[r['opportunity_id'] for r in m['metadata_census']],'FULL_CENSUS')
    for r in m['training']:
        _keys(r,('opportunity_id','admitted','reasons'),'TRAINING_MASK_SCHEMA')
        require(type(r['admitted']) is bool and r['opportunity_id'] in m['full_census'],'TRAINING_MASK')
    for r in m['C']:
        _keys(r,('opportunity_id','I','E','P','I_reasons','E_reasons','history_anchor','history_window'),'CENSUS_MASK_SCHEMA')
        require(all(type(r[k]) is bool for k in ('I','E','P')) and r['P']==(r['I'] and r['E']),'PAIRED_MASK')
        require(r['opportunity_id'] in m['full_census'],'CENSUS_MASK')
        if r['I']:require(len(r['history_window'])==52 and len(set(r['history_window']))==52
            and set(r['history_window'])<=set(m['full_census']),'HISTORY_MASK')
    require(I==[r['opportunity_id'] for r in m['C'] if r['I']] and
            P==[r['opportunity_id'] for r in m['C'] if r['P']] and
            m['E']==[r['opportunity_id'] for r in m['C'] if r['E']],'ORDERED_MASKS')
    require(values['source.json']['inputs']==cfg['inputs'],'SOURCE_INPUTS')
    if 'tree.json' in values:
        tree=values['tree.json'];provenance=tree['parameter_provenance']
        require(type(provenance) is dict and provenance,'TREE_PARAMETER_PROVENANCE')
        for r in provenance.values():
            _keys(r,('origin','value'),'PARAMETER_RECORD')
            require(type(r['origin']) is str and (r['value'] is None or type(r['value']) in (str,int,float,bool)),'PARAMETER_SCALAR')
        require(tree['parameters']=={k:r['value'] for k,r in provenance.items()},'TREE_PARAMETER_VALUES')
        require(type(tree['actual_iterations']) is int and 0<tree['actual_iterations']<=50 and tree['nominal_estimators']==50,'TREE_ITERATIONS')
    if 'linear.json' in values:
        linear=values['linear.json']
        _keys(linear['certificate_request'],('row_ids','z_bits','y_bits','theta','dual','secondary'),'CERTIFICATE_REQUEST_SCHEMA')
        _keys(linear['proof'],('status','theta','primary_objective','dual_objective','proof_id','format_version',
            'checks','failure_codes','scope_status','exact_operations'),'CERTIFICATE_PROOF_SCHEMA')
        _keys(linear['solver'],('method','options','status','iterations','dual_binary64','secondary_iterations','generation_operations'),'SOLVER_SCHEMA')
    if 'representations.json' in values:
        r=values['representations.json'];training=[v['opportunity_id'] for v in m['training'] if v['admitted']]
        require(r['training_ids']==training and [v['opportunity_id'] for v in r['training_targets']]==training
            and [v['opportunity_id'] for v in r['scoring']]==I and
            [v['opportunity_id'] for v in r['targets']]==P and
            [v['opportunity_id'] for v in r['history']]==I,'REPRESENTATION_ORDER')
        for record in r['training_targets']+r['targets']+[v for h in r['history'] for v in h['values']]:
            _keys(record,('opportunity_id','source_ref','represented_fraction','rounding'),'B_REPRESENTATION_SCHEMA')
            _rounding(record['rounding'])
        for row in r['scoring']:
            _keys(row,('opportunity_id','values'),'SCORING_SCHEMA');require(len(row['values'])==5,'SCORING_SLOTS')
            for cell in row['values']:
                _keys(cell,('source','conversion','z'),'SCORING_CELL_SCHEMA');_rounding(cell['conversion']);_rounding(cell['z'])
        windows={c['opportunity_id']:c['history_window'] for c in m['C']}
        for h in r['history']:
            _keys(h,('opportunity_id','window_ids','values'),'REPRESENTED_HISTORY_SCHEMA')
            require(h['window_ids']==windows[h['opportunity_id']]
                and [v['opportunity_id'] for v in h['values']]==h['window_ids'],'REPRESENTED_HISTORY_ORDER')
    if 'transform.json' in values:
        t=values['transform.json'];require(t['slots']==list(SLOTS) and t['training_count']==len(t['training_z'])
            ==len(t['training_conversion']) and len(t['columns'])==5,'TRANSFORM_SHAPE')
        for column,slot in zip(t['columns'],SLOTS):
            require(column['slot']==slot and type(column['constant']) is bool,'TRANSFORM_SLOT')
            _keys(column,('slot','constant','mean','variance','scale','exact_provenance','limitation')
                if column['constant'] else ('slot','constant','mean','variance','scale'),'TRANSFORM_COLUMN_SCHEMA')
        for row in t['training_z']:
            require(len(row)==5,'TRANSFORM_SLOTS')
            for cell in row:_rounding(cell)
    if 'history.json' in values:
        for rid,h in values['history.json'].items():
            _keys(h,('bits','rank','window_ids'),'HISTORY_SCHEMA');_bits(h['bits'])
            require(h['rank']==6 and h['window_ids']==next(c['history_window'] for c in m['C'] if c['opportunity_id']==rid),'HISTORY_WINDOW')
    if 'forecasts.json' in values:
        f=values['forecasts.json'];require(f['order']==I and set(f['methods'])=={'TREE','LINEAR','HISTORICAL'},'FORECAST_METHODS')
        for forecast in f['methods'].values():
            require(set(forecast)<=set(I),'FORECAST_ID')
            for bit in forecast.values():_bits(bit)
    if values['family.json']['status']=='COMPLETE':
        require(all(v=='SUCCESS' for v in values['family.json']['stages'].values()),'COMPLETE_STAGES')
