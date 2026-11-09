"""Fixed native model adapter. No CLI/authority; native calls require observed binding."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import importlib.metadata
import json
import os
import struct
import sys
from .hyp008_s1_numeric import dyadic
from .hyp008_s1_linear import generate,predict_linear
from .hyp008_s1_evaluation import METHODS,historical,evaluate_common

DEFAULT_HASHES={
 'TREE-DEFAULTS.json':'90d6cf6510ff638ac2f33ecc5d1ece9a7e0b7cbc08edd5192c6c3da7cfe57ec1',
 'HIGHS-DEFAULTS.json':'286eef4f65f852674974beed0f4f841e9778cb7535ba1b156b64336c6a096a35',
 'BUILD-MANIFEST.json':'3bfbf750596ff356fdd7f3e350cea39c70f735122085a982e459a97b07143581'}
THREADS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS',
         'NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')


class FamilyUnavailable(ValueError):pass


def require(ok,reason):
    if not ok:raise FamilyUnavailable(reason)


def digest(raw):return hashlib.sha256(raw).hexdigest()


def read_lock(path,expected):
    path=Path(path);require(path.is_file() and path.stat().st_size<=2*1024**2,'LOCK_BOUND')
    raw=path.read_bytes();require(digest(raw)==expected,'LOCK_HASH')
    return json.loads(raw)


@dataclass(frozen=True)
class NativeBinding:
    candidate: dict
    image_id: str
    preparation_path: str
    defaults_directory: str

    def verify(self):
        require(self.preparation_path=='/polar-launch/preparation.json','AUTOMATIC_PREPARATION_PATH')
        p=Path(self.preparation_path);require(p.is_file() and p.stat().st_size<=2*1024**2,'PREPARATION_BOUND')
        prep=json.loads(p.read_bytes());observed=prep['observed'];expected=prep['expected']
        require(prep['preparation']=='PREPARED' and prep['scenario_started'] is False
                and expected['candidate']==self.candidate and expected['image_id']==self.image_id
                and observed['image_id']==self.image_id and observed['os']=='linux'
                and observed['architecture']=='arm64' and all(observed['matches'].values())
                and os.geteuid()==10001 and sys.platform=='linux' and sys.version_info[:3]==(3,13,18),
                'ACTUAL_RUNTIME_IDENTITY')
        binding=prep['source_binding']
        require(binding['packaged_source_independently_observed'] is True
                and binding['observed_container_id']==observed['container_id'],'SOURCE_OBSERVATION')
        # Require full packaged source-map equality, not a selected-module subset.
        root=Path(__file__).resolve().parent;source=binding['observed_files']
        actual={str(path):{'bytes':path.stat().st_size,'sha256':digest(path.read_bytes())}
                for path in root.rglob('*') if path.is_file() and path.suffix in ('.py','.json','.sql')}
        require(type(source) is dict and set(source)==set(actual)
                and all(source[path]==ref for path,ref in actual.items()),'LOADED_SOURCE_BYTES')
        require(str(root)=='/app/src/polar','SOURCE_ORIGIN')
        locks={name:read_lock(Path(self.defaults_directory)/name,sha) for name,sha in DEFAULT_HASHES.items()}
        build=locks['BUILD-MANIFEST.json']
        native_files={v['path']:v['sha256'] for v in build['actual_introspection_runtime']['files'].values()}
        native_files.update(build['selected_HiGHS_runtime_sha256'])
        for path,sha in native_files.items():require(digest(Path(path).read_bytes())==sha,'NATIVE_LIBRARY_BYTES')
        require(all(os.environ.get(k)=='1' for k in THREADS),'THREAD_ENVIRONMENT')
        for name,version in (('numpy','2.2.6'),('scipy','1.15.3'),('lightgbm','4.6.0')):
            require(importlib.metadata.version(name)==version,'NATIVE_VERSION')
        return locks


def native_float(bits):
    dyadic(bits);return struct.unpack('>d',bytes.fromhex(bits))[0]


def native_bits(value):
    raw=struct.pack('>d',float(value)).hex();x=dyadic(raw)
    return {'bits':'0000000000000000' if x==0 else raw,'native_bits':raw}


def fit_tree(z_bits,y_bits,binding):
    locks=binding.verify()  # Before importing NumPy/LightGBM.
    import numpy as np
    import lightgbm
    require(str(Path(np.__file__).resolve().parent)=='/usr/local/lib/python3.13/site-packages/numpy'
            and str(Path(lightgbm.__file__).resolve().parent)=='/usr/local/lib/python3.13/site-packages/lightgbm',
            'NATIVE_IMPORT_ORIGIN')
    require(type(z_bits) is tuple and type(y_bits) is tuple and 1<=len(z_bits)<=10000
            and len(z_bits)==len(y_bits) and all(type(r) is tuple and len(r)==5 for r in z_bits),
            'TREE_INPUT_SHAPE')
    X=np.array([[native_float(b) for b in row] for row in z_bits],dtype=np.float64)
    y=np.array([native_float(b) for b in y_bits],dtype=np.float64)
    parameter_provenance=locks['TREE-DEFAULTS.json']['wrapper_effective_parameters']
    parameters={name:record['value'] for name,record in parameter_provenance.items()}
    model=lightgbm.LGBMRegressor(**parameters)
    require(model.get_params(deep=False)==parameters,'TREE_EFFECTIVE_PARAMETERS')
    model.fit(X,y)  # Exactly one fit, no eval set/weights/callbacks or forced iterations.
    text=model.booster_.model_to_string()
    require(len(text.encode())<=16*1024**2,'MODEL_BYTE_BOUND')
    restored=lightgbm.Booster(model_str=text)  # Readback, no second fit.
    require(restored.current_iteration()==model.booster_.current_iteration(),'MODEL_READBACK_ITERATIONS')
    return restored,{'schema':'polar.hyp008-s1-tree/1','parameters':parameters,
        'parameter_provenance':parameter_provenance,
        'nominal_estimators':50,'actual_iterations':model.booster_.current_iteration(),
        'model_text':text,'native_precision':'SOURCE_BOUND_FLOAT32_LABEL_SCORE',
        'default_hashes':dict(DEFAULT_HASHES)}


def fit_linear(row_ids,z_bits,y_bits,binding):
    binding.verify()
    from scipy.optimize import linprog
    from scipy.sparse import csr_matrix
    import scipy
    require(str(Path(scipy.__file__).resolve().parent)=='/usr/local/lib/python3.13/site-packages/scipy',
            'NATIVE_IMPORT_ORIGIN')
    return generate(row_ids,z_bits,y_bits,linprog,csr_matrix)


def fixed_family(training_ids,training_z,training_y,score_z,history_windows,targets,masks,binding,start):
    """Stage callback is mandatory; Service later binds durable authority/charges.

    This component never creates real authority. All actual invocations in the
    selected engineering package must use independently reviewed invented data.
    """
    require(callable(start),'DURABLE_STAGE_CALLBACK_REQUIRED')
    require(type(masks) is dict and masks.get('schema')=='polar.hyp008-s1-masks/1'
            and type(masks.get('I')) is list and len(masks['I'])<=10000
            and len(set(masks['I']))==len(masks['I']),'FIXED_MASK_DOMAIN')
    require(type(score_z) is dict and list(score_z)==masks['I']
            and type(history_windows) is dict and list(history_windows)==masks['I'],
            'FIXED_ISSUE_ROWS')
    if not masks['I']:
        return {'status':'NOT_STARTED','reason':'NO_ISSUE_COMPARISON','stages':{},
                'forecasts':None,'evaluation':None}
    require(tuple(training_ids)==tuple(r['opportunity_id'] for r in masks['training'] if r['admitted'])
            and type(training_z) is tuple and type(training_y) is tuple
            and len(training_ids)==len(training_z)==len(training_y)
            and type(targets) is dict and set(targets)==set(masks['P'])
            and all(type(row) is tuple and len(row)==5 for row in score_z.values()),'FIXED_TRAINING_TARGET_ROWS')
    binding.verify()  # Reject missing/incorrect runtime/default locks before stage charges.
    artifacts={};stages={name:'NOT_RUN' for name in ('TREE','LINEAR','HISTORICAL_PASS')}
    forecasts={k:{} for k in METHODS};current='TREE'
    try:
        start('TREE_START');stages['TREE']='STARTED'
        tree,artifacts['tree']=fit_tree(training_z,training_y,binding);stages['TREE']='SUCCESS'
        current='LINEAR';start('LINEAR_START');stages['LINEAR']='STARTED'
        artifacts['linear']=fit_linear(training_ids,training_z,training_y,binding);stages['LINEAR']='SUCCESS'
        current='HISTORICAL_PASS';start('HISTORICAL_PASS_START');stages['HISTORICAL_PASS']='STARTED'
        for identity in masks['I']:
            window=history_windows[identity]
            require(tuple(window['ids'])==tuple(next(row['history_window'] for row in masks['C']
                                                   if row['opportunity_id']==identity)),'HISTORY_MASK_BINDING')
            artifacts.setdefault('history',{})[identity]=historical(tuple(window['ids']),tuple(window['bits']))
            forecasts['HISTORICAL'][identity]=artifacts['history'][identity]['bits']
        stages['HISTORICAL_PASS']='SUCCESS';current='FORECASTS'
        # Predict only after both fits and the historical pass succeeded.
        import numpy as np
        values=tree.predict(np.array([[native_float(b) for b in score_z[i]] for i in masks['I']],dtype=np.float64))
        require(len(values)==len(masks['I']),'TREE_PREDICTION_SHAPE')
        for identity,value in zip(masks['I'],values):
            record=native_bits(value);artifacts.setdefault('tree_predictions',{})[identity]=record
            forecasts['TREE'][identity]=record['bits']
            record=predict_linear(artifacts['linear']['theta'],score_z[identity])
            artifacts.setdefault('linear_predictions',{})[identity]=record
            forecasts['LINEAR'][identity]=record['bits']
        evaluation=evaluate_common(masks,forecasts,targets)
        require(evaluation['status'] in ('OK','INSUFFICIENT_EVIDENCE'),'INCOMPLETE_FAMILY')
        return {'status':'COMPLETE','reason':None,'stages':stages,'artifacts':artifacts,
                'forecasts':forecasts,'evaluation':evaluation}
    except Exception as exc:
        if current in stages and stages[current]=='STARTED':stages[current]='FAILED'
        return {'status':'PLANNED_FAMILY_UNAVAILABLE','reason':type(exc).__name__,
                'stage':current,'detail':str(exc)[:256],'stages':stages,'artifacts':artifacts,
                'forecasts':forecasts,'evaluation':None}
