import copy
import hashlib
import json
from pathlib import Path

import pytest

from polar.codec import canonical, digest
from polar.hyp003_observability import write_observability, STATES
from polar.hyp003_source import PreparationError


def put(path, value, ndjson=False):
    raw = b''.join(canonical(r)+b'\n' for r in value) if ndjson else canonical(value)
    path.write_bytes(raw)
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def fixture(tmp_path):
    src = tmp_path/'input'; src.mkdir()
    population = [{'population_record_id':'same-alias-'+str(i), 'literal_symbol':'SAME', **extra}
                  for i,extra in enumerate([{'acquisition_decile':1},{'acquisition_decile':10},{'acquisition_decile':False}])]
    grid = ['2020-06-30','2020-07-01','2020-08-31','2020-09-01','2020-09-30','2020-10-01']
    poppin = put(src/'r0.ndjson',population,True); gridpin=put(src/'grid.json',{'all':grid})
    objects={}; indexes=[]; ledger=[]
    for i,record in enumerate(population):
        cells=[]
        for j,day in enumerate(grid):
            cells.append({'population_record_id':record['population_record_id'], 'reference_date':day,'state':STATES[(i+j)%6],
                'profile_states':[{'source_manifest_sha256':'s','profile_id':'p','state':'PERMANENT_HTTP_400'},
                                  {'source_manifest_sha256':'s','profile_id':'q','state':'OUTSIDE_REQUEST_INTERVAL'}],
                'observations':[{'source_manifest_sha256':'s','profile_id':'p','pointer_status':'REFERENCED_ONLY'}]*2})
        name=f'availability/{i:05d}.ndjson'; (src/'availability').mkdir(exist_ok=True)
        objects[name]=put(src/name,cells,True)
        indexes.append({'ordinal':i,'source_record':record,'availability_member':name,
                        'coverage':[{'profile_id':'p','transport_state':'PERMANENT_HTTP_400'}]})
        ledger.append({'ordinal':i,'population_record_id':record['population_record_id'],'frozen_R0_record':record,
                       'adopted_exceptions':[],'intervals':[{'from_grid_index':0,'to_grid_index_exclusive':len(grid),'state':'EXPECTED_DEFAULT'}]})
    objects['population-index.ndjson']=put(src/'population-index.ndjson',indexes,True)
    parent={'schema':'polar.hyp003-source-availability-content/1','objects':objects,'population':poppin,'grid':gridpin,
            'records':3,'reference_dates':6,'source_record_date_slots':18,'states':{s:3 for s in STATES}}
    parent['revision']='hyp003availability-'+digest(parent)
    put(src/'parent.json',parent)
    files={'ledger.ndjson':put(src/'ledger.ndjson',ledger,True),
           'reference-grid.json':put(src/'reference-grid.json',{'all':grid,'fields':['raw_open','raw_close','raw_volume']})}
    put(src/'ledger-manifest.json',{'schema':'polar.derived-artifact-manifest/1','files':files})
    put(src/'evidence.json',{'prospective':'invented'})
    def ref(name):return {'path':str(src/name),'sha256':hashlib.sha256((src/name).read_bytes()).hexdigest()}
    config={'schema':'polar.hyp003-observability-config/1','mode':'INVENTED','availability_ref':ref('parent.json'),
            'population_ref':ref('r0.ndjson'),'grid_ref':ref('grid.json'),'ledger_ref':ref('ledger-manifest.json'),
            'evidence_refs':[ref('evidence.json')]}
    return config,src


def data(root,name):return json.loads((root/name).read_bytes())
def lines(root,name):return [json.loads(line) for line in (root/name).read_bytes().splitlines()]


def rebind_parent(config,src,member,values):
    parent=data(src,'parent.json'); parent['objects'][member]=put(src/member,values,True)
    parent.pop('revision');parent['revision']='hyp003availability-'+digest(parent)
    pin=put(src/'parent.json',parent);config['availability_ref']['sha256']=pin['sha256']


def test_conservation_axes_diagnostics_and_determinism(tmp_path):
    config,src=fixture(tmp_path); out=tmp_path/'report'
    result=write_observability(config,out)
    summary=data(out,'summary.json'); records=lines(out,'records.ndjson'); dates=lines(out,'dates.ndjson');joint=lines(out,'joint.ndjson')
    assert summary['positions']==18 and summary['declared_field_slot_equivalents']==54
    assert all(sum(r['positions'].values())==6 for r in records)
    assert all(sum(d['positions'].values())==3 for d in dates)
    assert sum(r['positions'] for r in joint)==18
    assert sum(r['declared_field_slot_equivalents'] for r in joint)==54
    assert {r['decile'] for r in joint}==set(map(str,range(1,11)))|{'UNKNOWN'}
    assert all(r['positions']==0 for r in joint if r['applicability']!='UNKNOWN_APPLICABILITY' or not r['ASSUMED_EXPECTED_DEFAULT'])
    assert sum(r['positions'] for r in joint if r['date_scope']=='WARMUP')==9
    assert {r['quarter'] for r in joint}=={'2020-Q2','2020-Q3','2020-Q4'}
    assert records[2]['decile_stratum']=='UNKNOWN'
    assert all(r['population_record_id'].startswith('same-alias-') for r in records)
    diagnostic=data(out,'diagnostics.json')
    assert sum(r['count'] for r in diagnostic['profile_date_occurrences'])==36
    assert sum(r['count'] for r in diagnostic['observation_occurrences'])==36
    assert diagnostic['coverage_facts'][0]['record_occurrences']==3
    assert summary['applicable_denominator']['status']=='NOT_IDENTIFIED'
    assert summary['true_required_source_absent_field_slots']['logical_bounds']==[0,36]
    assert summary['fitness']['economic_schedule_windows_guards']['status']=='UNBOUND'
    assert data(out,'content-manifest.json')==result
    assert 'physical-receipt.json' not in result['objects']
    # Moving every input path and output changes only the physical receipt.
    import shutil
    src2=tmp_path/'other-input';shutil.copytree(src,src2); changed=copy.deepcopy(config)
    for key in ('availability_ref','population_ref','grid_ref','ledger_ref'):
        changed[key]['path']=str(src2/Path(config[key]['path']).name)
    changed['evidence_refs'][0]['path']=str(src2/'evidence.json')
    other=write_observability(changed,tmp_path/'report2')
    assert other==result
    assert data(out,'physical-receipt.json')!=data(tmp_path/'report2','physical-receipt.json')
    with pytest.raises(PreparationError):write_observability(config,out)


@pytest.mark.parametrize('mutation',['record','date','missing','duplicate','state','hash','index','parent_count','extra_member','ledger'])
def test_fail_closed_integrity(tmp_path,mutation):
    config,src=fixture(tmp_path); member='availability/00000.ndjson'; cells=lines(src,member)
    if mutation=='record':cells[0]['population_record_id']='other'
    if mutation=='date':cells[0]['reference_date']='2020-07-01'
    if mutation=='missing':cells.pop()
    if mutation=='duplicate':cells.append(cells[-1])
    if mutation=='state':cells[0]['state']='READY'
    if mutation in ('record','date','missing','duplicate','state'):rebind_parent(config,src,member,cells)
    elif mutation=='hash':(src/member).write_bytes((src/member).read_bytes()+b' ')
    elif mutation=='index':
        ix=lines(src,'population-index.ndjson');ix[0]['source_record']['population_record_id']='other'
        rebind_parent(config,src,'population-index.ndjson',ix)
    elif mutation in ('parent_count','extra_member'):
        parent=data(src,'parent.json');parent.pop('revision')
        if mutation=='parent_count':parent['records']=2
        else:parent['objects']['availability/extra.ndjson']={'bytes':0,'sha256':hashlib.sha256(b'').hexdigest()}
        parent['revision']='hyp003availability-'+digest(parent)
        config['availability_ref']['sha256']=put(src/'parent.json',parent)['sha256']
    else:
        rows=lines(src,'ledger.ndjson');rows[0]['adopted_exceptions']=['NEW_PROOF']
        ledger=data(src,'ledger-manifest.json');ledger['files']['ledger.ndjson']=put(src/'ledger.ndjson',rows,True)
        config['ledger_ref']['sha256']=put(src/'ledger-manifest.json',ledger)['sha256']
    out=tmp_path/'bad'
    with pytest.raises((PreparationError,ValueError)):write_observability(config,out)
    assert not (out/'content-manifest.json').exists()


def test_retained_cannot_use_invented_pins(tmp_path):
    config,_=fixture(tmp_path);config['mode']='RETAINED'
    with pytest.raises(PreparationError,match='FIXED_SCOPE'):write_observability(config,tmp_path/'bad')


def test_cli_dispatch(tmp_path,monkeypatch,capsys):
    from polar.cli import main
    config,_=fixture(tmp_path); path=tmp_path/'config.json';put(path,config)
    monkeypatch.setattr('sys.argv',['polar','hyp003-observability',str(path),'--output-dir',str(tmp_path/'cli')])
    main()
    assert json.loads(capsys.readouterr().out)['schema']=='polar.hyp003-observability-content/1'
