"""Prospective Unit2 invented component control; not invoked by its author."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys


def digest(raw):return hashlib.sha256(raw).hexdigest()


def read(path):
    p=Path(path)
    assert p.is_file() and p.stat().st_size<=1024*1024,'REFERENCE_BOUND'
    return p.read_bytes()


def publish(root,name,value):
    raw=(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
    assert len(raw)<=16*1024**2,'OUTPUT_BOUND'
    with (root/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    (root/name).chmod(0o444)


def main(input_file,expected_file,config_file,output):
    root=Path(output)
    assert root==Path('/polar-output') and root.is_dir(),'OUTPUT_ROOT'
    prep_raw=read('/polar-launch/preparation.json');prep=json.loads(prep_raw)
    cfg=json.loads(read(config_file))
    for role,p in (('harness',__file__),('input',input_file),('expectations',expected_file),('config',config_file)):
        ref=prep['expected']['refs'][role]
        assert ref['path']==str(Path(p)) and ref['sha256']==digest(read(p)),'REFERENCE_BINDING'
    assert cfg['schema']=='polar.hyp008-s1-unit2-control/1','CONTROL_SCHEMA'
    assert cfg['scope']=='INVENTED_COMPONENT_ONLY' and cfg['real_starts_authorized']==0,'NO_REAL_AUTHORITY'
    assert cfg['candidate']==prep['expected']['candidate'] and cfg['image_id']==prep['observed']['image_id'],'CANDIDATE_BINDING'
    material=json.loads(read(input_file));expected=json.loads(read(expected_file))
    defaults=root/'defaults';defaults.mkdir(mode=0o700)
    for name,item in material['defaults'].items():
        assert name in ('TREE-DEFAULTS.json','HIGHS-DEFAULTS.json','BUILD-MANIFEST.json'),'DEFAULT_MEMBER'
        raw=base64.b64decode(item['base64'],validate=True)
        assert digest(raw)==item['sha256'],'DEFAULT_BYTES'
        with (defaults/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        (defaults/name).chmod(0o444)
    from polar.hyp008_s1_models import NativeBinding,fixed_family
    from polar.hyp008_s1_linear import verify_saved_linear
    binding=NativeBinding(cfg['candidate'],cfg['image_id'],'/polar-launch/preparation.json',str(defaults))
    binding.verify()
    publish(root,'PRE-SCENARIO.json',{'schema':'polar.hyp008-s1-unit2-prestart/1',
        'candidate':cfg['candidate'],'image_id':cfg['image_id'],'container_id':prep['observed']['container_id'],
        'preparation_sha256':digest(prep_raw),'input_sha256':digest(read(input_file)),
        'expected_sha256':digest(read(expected_file)),'config_sha256':digest(read(config_file)),
        'scope':'INVENTED_COMPONENT_ONLY','source_binding':prep['source_binding'],
        'native_calls_before_receipt':0})
    stages=[]
    def charge(stage):
        assert stage not in stages,'REPEATED_STAGE'
        stages.append(stage)
        publish(root,stage+'.json',{'schema':'polar.hyp008-s1-unit2-stage/1',
            'stage':stage,'scope':'INVENTED_COMPONENT_ONLY','real_family_charged':False})
    f=material['fixture']
    result=fixed_family(tuple(f['training_ids']),tuple(tuple(r) for r in f['training_z']),tuple(f['training_y']),
        {k:tuple(v) for k,v in f['score_z'].items()},f['history_windows'],f['targets'],f['masks'],binding,charge)
    publish(root,'FAMILY-RESULT.json',result)
    assert result['status']=='COMPLETE','COMPLETE_FIXED_FAMILY'
    assert stages==['TREE_START','LINEAR_START','HISTORICAL_PASS_START'],'STAGE_ORDER'
    proof=verify_saved_linear(result['artifacts']['linear'])
    assert proof['status']=='EXACT_REPRESENTED_INPUT_CERTIFIED','STORED_PROOF'
    assert result['artifacts']['linear']['theta']==[tuple(p) for p in expected['linear_theta']],'EXACT_LINEAR_THETA'
    assert result['forecasts']['LINEAR']==expected['linear_bits'],'LINEAR_PREDICTION'
    assert result['forecasts']['HISTORICAL']==expected['historical_bits'],'HISTORICAL_RANK'
    assert result['evaluation']['aggregate']['count']==expected['P_count'],'COMMON_P'
    assert 0<result['artifacts']['tree']['actual_iterations']<=50,'INTRINSIC_ITERATIONS'
    publish(root,'CONTROL-RESULT.json',{'schema':'polar.hyp008-s1-unit2-control-result/1',
        'status':'PASS','scope':'INVENTED_COMPONENT_ONLY','proof_id':proof['proof_id'],
        'stages':stages,'real_starts':0,'production_Service':'NOT_IMPLEMENTED_IN_UNIT2'})


if __name__=='__main__':main(*sys.argv[1:])
