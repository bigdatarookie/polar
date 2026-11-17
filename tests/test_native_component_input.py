"""Invented exact native subset/union and immutable source/purpose boundaries."""
import json
from copy import deepcopy
from pathlib import Path
import pytest
from test_selected_reference_input import selected_fixture
from test_reference_input import put
from polar.reference_input import prepare_input
from polar.reference_composition import COMPONENT_PROFILE
from polar.research_reference import load_reference


def component_fixture(tmp_path):
    inputs=[];qualifications=[]
    for name,targets,selected in [('left',['AAA','BBB'],['AAA']),('right',['DDD','EEE'],['DDD'])]:
        folder=tmp_path/name;folder.mkdir()
        root,cfg,_,_=selected_fixture(folder,targets=targets)
        result=prepare_input(cfg,root,10**8)
        item={'input_ref':result['input_ref'],'symbols':selected};inputs.append(item)
        decision=put(folder/'existing-source-qualification.json',{'schema':'invented-existing-source-qualification/1',
            'source_input':result['input_ref'],'rights':'INVENTED_PUBLIC_TEST','limits':['HISTORICAL_K_UNKNOWN']})
        qualifications.append({**item,'qualification':decision})
    source=tmp_path/'source-schedule.json'
    parent=json.loads(Path(inputs[0]['input_ref']['path']).read_bytes())
    source.write_bytes(Path(parent['schedule']['path']).read_bytes())
    schedule=put(source,json.loads(source.read_bytes()))
    config={'schema':'polar.reference-input-conversion-config/9','profile_id':COMPONENT_PROFILE,'namespace':'INVENTED',
        'inputs':inputs,'purpose':None,'schedule':schedule,'date_range':parent['dates']}
    purpose={'schema':'polar.reference-input-composition-purpose/3','inputs':deepcopy(inputs),'symbols':['AAA','DDD'],
        'schedule':schedule,'date_range':parent['dates'],'rights':'INVENTED_PUBLIC_TEST',
        'source_qualifications':qualifications,'consumer_protocol':put(tmp_path/'question.json',{'fixed_rule':'INVENTED_ONLY'}),
        'source_acceptance':put(tmp_path/'source-acceptance.json',{'existing_source_inputs':inputs}),
        'rights_source_refs':[q['qualification'] for q in qualifications]}
    config['purpose']=put(tmp_path/'purpose.json',purpose)
    output=tmp_path/'output';output.mkdir()
    return output,config


def repurpose(tmp_path,cfg,edit):
    purpose=json.loads(Path(cfg['purpose']['path']).read_bytes());edit(purpose)
    cfg['purpose']=put(tmp_path/'updated-purpose.json',purpose)


def test_selected_union_is_lossless_preserves_source_and_prefix(tmp_path):
    root,cfg=component_fixture(tmp_path)
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result=prepare_input(cfg,root,10**8)
    assert prepare_input(cfg,root,10**8)==result
    market=load_reference(result['input_ref']);assert market['symbols']==['AAA','DDD']
    assert market['schedule']==json.loads(Path(cfg['schedule']['path']).read_bytes())['rows']
    manifest=json.loads(Path(result['input_ref']['path']).read_bytes())
    output=Path(manifest['quotes']['path']).read_bytes().splitlines(keepends=True)
    expected=[]
    for item in cfg['inputs']:
        parent=json.loads(Path(item['input_ref']['path']).read_bytes())
        expected.extend(line for line in Path(parent['quotes']['path']).read_bytes().splitlines(keepends=True)
                        if json.loads(line)['symbol'] in item['symbols'])
    assert output==sorted(expected,key=lambda line:(json.loads(line)['date'],json.loads(line)['symbol']))
    assert market['source_relations']['source_qualifications']==json.loads(Path(cfg['purpose']['path']).read_bytes())['source_qualifications']
    assert all(Path(p).read_bytes()==raw for p,raw in before.items())
    # Same exact source lines and source evidence survive a calendar clip.
    clipped=deepcopy(cfg);days=market['dates'];clipped['date_range']={'start':days[1],'end':days[-1],'count':len(days)-1}
    repurpose(tmp_path,clipped,lambda p:p.update(date_range=clipped['date_range']))
    second=prepare_input(clipped,root,10**8);m2=load_reference(second['input_ref'])
    assert m2['dates']==days[1:]
    for day in m2['dates']:
        assert m2['source_evidence'][day]==market['source_evidence'][day]
        assert m2['prices_micro'][day]==market['prices_micro'][day]


@pytest.mark.parametrize('case,error',[
    ('duplicate','DUPLICATE_INPUT'),('overlap','SYMBOL_SET'),('missing_symbol','SYMBOL_SET'),
    ('missing_date','CONVERSION_SCHEDULE'),('basis','BASIS_RIGHTS'),('rights','BASIS_RIGHTS'),
    ('purpose','PURPOSE'),('qualification_binding','QUALIFICATION_BINDING'),
    ('qualification_bytes','REFERENCE_FILE_HASH'),('parent_bytes','REFERENCE_FILE_HASH'),
    ('token','REFERENCE_SCALE_CHANGED'),('session_clock','COMPONENT_CALENDAR')])
def test_invalid_components_fail_before_publication(tmp_path,case,error):
    root,cfg=component_fixture(tmp_path)
    if case=='duplicate':
        cfg['inputs'][1]['input_ref']=cfg['inputs'][0]['input_ref']
        repurpose(tmp_path,cfg,lambda p:p.update(inputs=cfg['inputs']))
    elif case=='overlap':
        # Different manifest digest with the same actual selected symbol still rejects.
        old=json.loads(Path(cfg['inputs'][0]['input_ref']['path']).read_bytes());old['annotation']='distinct pin'
        cfg['inputs'][1]={'input_ref':put(tmp_path/'alias.json',old),'symbols':['AAA']}
        def edit(p):
            p['inputs']=cfg['inputs'];p['source_qualifications'][1].update(cfg['inputs'][1])
        repurpose(tmp_path,cfg,edit)
    elif case=='missing_symbol':
        cfg['inputs'][1]['symbols']=['MISSING']
        def edit(p):
            p['inputs']=cfg['inputs'];p['source_qualifications'][1]['symbols']=['MISSING']
        repurpose(tmp_path,cfg,edit)
    elif case=='missing_date':
        cfg['date_range']['start']='2020-01-01'
        repurpose(tmp_path,cfg,lambda p:p.update(date_range=cfg['date_range']))
    elif case=='purpose':
        repurpose(tmp_path,cfg,lambda p:p['inputs'][0].update(symbols=['BBB']))
    elif case=='qualification_binding':
        repurpose(tmp_path,cfg,lambda p:p['source_qualifications'][0].update(symbols=['BBB']))
    elif case=='qualification_bytes':
        p=json.loads(Path(cfg['purpose']['path']).read_bytes())['source_qualifications'][0]['qualification']
        path=Path(p['path']);path.write_bytes(b' '*path.stat().st_size)
    elif case=='parent_bytes':
        path=Path(cfg['inputs'][0]['input_ref']['path']);path.chmod(0o600);path.write_bytes(b' '*path.stat().st_size)
    else:
        m=json.loads(Path(cfg['inputs'][0]['input_ref']['path']).read_bytes())
        if case=='basis':m['quote_basis']='SPLIT_ONLY_PRICE'
        elif case=='rights':m['rights']='UNQUALIFIED_PURPOSE'
        elif case=='token':
            quotes=Path(m['quotes']['path']);lines=quotes.read_text().splitlines();v=json.loads(lines[0]);v['reference_quote']='99.0';lines[0]=json.dumps(v)
            new=tmp_path/'changed-quotes.ndjson';new.write_text('\n'.join(lines)+'\n')
            from polar.history_bundle import sha
            m['quotes']={'path':str(new),'sha256':sha(new.read_bytes())}
        elif case=='session_clock':
            s=json.loads(Path(m['schedule']['path']).read_bytes());s['rows'][0]['reference_close_utc']='2024-01-31T20:00:00Z'
            m['schedule']=put(tmp_path/'changed-schedule.json',s)
        cfg['inputs'][0]['input_ref']=put(tmp_path/'rehashed-parent.json',m)
        def edit(p):
            p['inputs']=cfg['inputs'];p['source_qualifications'][0]['input_ref']=cfg['inputs'][0]['input_ref']
        repurpose(tmp_path,cfg,edit)
    with pytest.raises(ValueError,match=error):prepare_input(cfg,root,10**8)
    assert not (root/'reference-inputs').exists()


def test_existing_captured_pointer_survives_component_selection(tmp_path):
    from test_snapshot_reference_input import fixture as snapshot_fixture
    root,cfg=component_fixture(tmp_path)
    captured=tmp_path/'captured';captured.mkdir()
    store,snapshot=snapshot_fixture(captured)
    native=prepare_input(snapshot,store,10**8)['input_ref']
    cfg['inputs'][1]={'input_ref':native,'symbols':['TEST']}
    def edit(p):
        p['inputs']=cfg['inputs'];p['symbols']=['AAA','TEST']
        p['source_qualifications'][1]={'input_ref':native,'symbols':['TEST'],
            'qualification':put(tmp_path/'capture-qualification.json',{'source':native})}
    repurpose(tmp_path,cfg,edit)
    converted=prepare_input(cfg,root,10**8);market=load_reference(converted['input_ref'])
    assert market['symbols']==['AAA','TEST']
    assert market['source_relations']['single_symbol_captures']
    for day in market['dates']:
        assert market['source_evidence'][day]['TEST']['source_ref']['kind']=='CAPTURED_SINGLE_SYMBOL_ALL_ADJUSTED_SOURCE'


def test_reader_bound_is_rejected_before_publish(tmp_path):
    from test_snapshot_reference_input import wide_parent
    root,cfg=component_fixture(tmp_path)
    folder=tmp_path/'wide';folder.mkdir()
    parent=wide_parent(folder,cfg['inputs'][0]['input_ref'],64)
    symbols=json.loads(Path(parent['path']).read_bytes())['symbols']
    cfg['inputs'][0]={'input_ref':parent,'symbols':symbols}
    def edit(p):
        p['inputs']=cfg['inputs'];p['symbols']=sorted(symbols+['DDD'])
        p['source_qualifications'][0].update(cfg['inputs'][0])
    repurpose(tmp_path,cfg,edit)
    with pytest.raises(ValueError,match='REFERENCE_COMPONENT_SYMBOL_SET'):prepare_input(cfg,root,10**8)
    assert not (root/'reference-inputs').exists()
