"""Invented exact VTI subset plus unchanged captured BIL/selected SHY union."""
from pathlib import Path
import json
from copy import deepcopy
import pytest
from test_reference_input import put
from test_selected_reference_input import selected_fixture
from test_captured_reference_input import captured_fixture
from polar.reference_input import prepare_input
from polar.reference_composition import PROFILE,SELECTED_PROFILE
from polar.research_reference import load_reference


def selected_composition_fixture(tmp_path):
    capture=tmp_path/'capture';capture.mkdir();root,cfg,shy=captured_fixture(capture)
    a=prepare_input(cfg,root,10**8)['input_ref'];b=prepare_input(shy,root,10**8)['input_ref']
    p=json.loads(Path(cfg['purpose']['path']).read_bytes())
    common={k:p[k] for k in ('consumer_protocol','source_acceptance','rights_source_refs','rights')}
    bp=put(tmp_path/'b9-purpose.json',{'schema':'polar.reference-input-composition-purpose/1',
        'inputs':[a,b],'symbols':['BIL','SHY'],'schedule':cfg['schedule'],'date_range':cfg['date_range'],**common})
    b9=prepare_input({'schema':'polar.reference-input-conversion-config/3','profile_id':PROFILE,'namespace':'INVENTED',
        'inputs':[a,b],'purpose':bp,'schedule':cfg['schedule'],'date_range':cfg['date_range']},root,10**8)['input_ref']
    v=tmp_path/'a3';v.mkdir();vr,vc,_,_=selected_fixture(v,targets=['GLD','IEF','VTI'])
    vti=prepare_input(vc,vr,10**8)['input_ref']
    inputs=[{'input_ref':vti,'symbols':['VTI']},{'input_ref':b9,'symbols':['BIL','SHY']}]
    purpose=put(tmp_path/'b10-purpose.json',{'schema':'polar.reference-input-composition-purpose/2',
        'inputs':inputs,'symbols':['BIL','SHY','VTI'],'schedule':cfg['schedule'],'date_range':cfg['date_range'],**common})
    out=tmp_path/'out';out.mkdir()
    return out,{'schema':'polar.reference-input-conversion-config/5','profile_id':SELECTED_PROFILE,
        'namespace':'INVENTED','inputs':inputs,'purpose':purpose,'schedule':cfg['schedule'],'date_range':cfg['date_range']}


def test_exact_subset_excludes_other_symbols_preserves_lines_origin_graph_and_reuse(tmp_path):
    root,cfg=selected_composition_fixture(tmp_path);before={}
    for item in cfg['inputs']:
        m=json.loads(Path(item['input_ref']['path']).read_bytes())
        for line in Path(m['quotes']['path']).read_bytes().splitlines(keepends=True):
            v=json.loads(line)
            if v['symbol'] in item['symbols']:before[v['date'],v['symbol']]=line
    input_before={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in tmp_path.rglob('*.json')}
    result=prepare_input(cfg,root,10**8);assert result['rows']==9 and result['symbols']==3
    market=load_reference(result['input_ref']);assert market['symbols']==['BIL','SHY','VTI']
    m=json.loads(Path(result['input_ref']['path']).read_bytes())
    for line in Path(m['quotes']['path']).read_bytes().splitlines(keepends=True):
        v=json.loads(line);assert line==before[v['date'],v['symbol']]
        assert v['observed_published_at'] is v['observed_historical_available_at'] is None
    rel=market['source_relations'];assert {x['literal_alias'] for x in rel['records']}=={'BIL','SHY','VTI'}
    assert rel['eligibility_ledger']['selected_aliases_fixed_order']==['BIL','SHY','VTI']
    assert rel['captures'] and rel['jobs'] and rel['parent_relations']
    assert [x['source_input'] for x in rel['source_components']]==[x['input_ref'] for x in cfg['inputs']]
    assert prepare_input(cfg,root,10**8)==result
    for name,(raw,mtime) in input_before.items():assert Path(name).read_bytes()==raw and Path(name).stat().st_mtime_ns==mtime


@pytest.mark.parametrize('case',['broader','missing','swap','duplicate','purpose','namespace'])
def test_selection_rejected_before_numeric_reads(tmp_path,monkeypatch,case):
    root,cfg=selected_composition_fixture(tmp_path)
    if case=='broader':cfg['inputs'][0]['symbols']=['GLD','IEF','VTI']
    if case=='missing':cfg['inputs'][0]['symbols']=[]
    if case=='swap':cfg['inputs'][0]['symbols'],cfg['inputs'][1]['symbols']=cfg['inputs'][1]['symbols'],cfg['inputs'][0]['symbols']
    if case=='duplicate':cfg['inputs'][0]['input_ref']=cfg['inputs'][1]['input_ref']
    if case=='purpose':
        p=json.loads(Path(cfg['purpose']['path']).read_bytes());p['symbols']=['BIL','SHY'];cfg['purpose']=put(tmp_path/'bad-purpose.json',p)
    if case=='namespace':cfg['namespace']='RETAINED'
    # Match purpose entries to isolate selected-source and duplicate predicates.
    if case in ('swap','duplicate'):
        p=json.loads(Path(cfg['purpose']['path']).read_bytes());p['inputs']=cfg['inputs'];cfg['purpose']=put(tmp_path/'bad-purpose.json',p)
    def forbidden(*a):raise AssertionError('NUMERIC_READ_BEFORE_METADATA_REJECT')
    monkeypatch.setattr('polar.reference_composition.load_reference',forbidden)
    with pytest.raises(ValueError):prepare_input(cfg,root,10**8)
    assert not (root/'reference-inputs').exists()


def test_rehashed_fixture_provenance_cannot_be_relabelled_retained(tmp_path,monkeypatch):
    from polar.selected_reference_input import RIGHTS
    root,cfg=selected_composition_fixture(tmp_path)
    first=cfg['inputs'][0]['input_ref'];m=json.loads(Path(first['path']).read_bytes())
    m.update(rights=RIGHTS,parent_dataset_revision='declared-retained-without-fixture-prefix')
    cfg['inputs'][0]['input_ref']=put(tmp_path/'rehashed-manifest.json',m);cfg['namespace']='RETAINED'
    p=json.loads(Path(cfg['purpose']['path']).read_bytes());p.update(inputs=cfg['inputs'],rights=RIGHTS)
    cfg['purpose']=put(tmp_path/'rehashed-purpose.json',p)
    def forbidden(*a):raise AssertionError('VALUE_READ_BEFORE_POSITIVE_FIXTURE_REJECT')
    monkeypatch.setattr('polar.reference_composition.load_reference',forbidden)
    with pytest.raises(ValueError,match='NAMESPACE'):prepare_input(cfg,root,10**8)
    assert not (root/'reference-inputs').exists()
