"""Invented composer-shaped source-only role projection; never retained data."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import pytest
from test_reference_input import put, sha
from test_selected_reference_composition import selected_composition_fixture
from polar.reference_input import prepare_input, schedule_binding_matches
from polar.reference_composition import VIEW_PROFILE, source_view_metadata
from polar.research_reference import load_reference
from polar.history_bundle import canonical


def view_fixture(tmp_path):
    root,cfg=selected_composition_fixture(tmp_path)
    old=prepare_input(cfg,root,10**8)['input_ref'];m=json.loads(Path(old['path']).read_bytes())
    # Invented explicit reference dates, not a reconstructed real venue calendar.
    warm=[(date(2023,3,16)+timedelta(days=i)).isoformat() for i in range(199)]+['2023-12-29']
    nav=[(date(2024,1,2)+timedelta(days=i)).isoformat() for i in range(715)]+['2026-11-06']
    days=['2023-03-15']+warm+nav+['2026-11-09']
    schedule=json.loads(Path(m['schedule']['path']).read_bytes());template=deepcopy(schedule['rows'][0]);rows=[]
    for i,d in enumerate(days):
        r=deepcopy(template);r.update(date=d,reference_open_utc=d+'T14:30:00+00:00',reference_close_utc=d+'T21:00:00+00:00',
            next_reference_date=days[i+1] if i+1<len(days) else None,month_end_in_reference_range=(days[i+1][:7]!=d[:7]) if i+1<len(days) else None)
        rows.append(r)
    schedule['rows']=rows;sp=put(tmp_path/'invented-full-schedule.json',schedule)
    originals={json.loads(line)['symbol']:json.loads(line) for line in Path(m['quotes']['path']).read_bytes().splitlines()}
    lines=[]
    for i,d in enumerate(days):
        for symbol in m['symbols']:
            r=deepcopy(originals[symbol]);r['date']=d
            if symbol=='BIL':
                p=r['source_ref'];p.update(source_row_index=i,source_pointer=f'/bars/BIL/{i}/c',exact_token_pointer=f'/rows/{i}/tokens/c')
            else:
                r['source_ref'].update(line_1based=i+1,line_sha256=sha((d+symbol).encode()))
                r['source_ref']['original_source_reference']['source_row_ordinal']=i
            # Preserve lexemes, including redundant trailing zeros, in this fixture.
            r['reference_quote']=r['source_adjusted_close_token']='10.130000'
            lines.append(canonical(r)+b'\n')
    qp=put(tmp_path/'invented-full-quotes.ndjson',b''.join(lines))
    m.update(schedule=sp,quotes=qp,dates={'start':days[0],'end':days[-1],'count':len(days)},rows=len(lines))
    meta=m['conversion_metadata'];meta['parent_schedule']=sp
    meta['semantic']['config'].update(schedule=sp,date_range=m['dates'])
    meta['semantic'].update(quotes_sha256=qp['sha256'],schedule_sha256=sp['sha256'])
    parent=put(tmp_path/'invented-parent-composer2.json',m)
    original_purpose=json.loads(Path(cfg['purpose']['path']).read_bytes())
    purpose={'schema':'polar.reference-input-selected-view-purpose/1','input_ref':parent,'symbols':['BIL','VTI'],
        'schedule':sp,'date_range':{'start':warm[0],'end':nav[-1],'count':916},'roles':{'nav_dates':nav,'warmup_dates':warm,'warmup_symbol':'VTI','context_symbol':'BIL'},
        **{k:original_purpose[k] for k in ['consumer_protocol','source_acceptance','rights_source_refs','rights']},
        'event_panel':put(tmp_path/'invented-panel.json',{'schema':'invented-event-panel','members':33,'planned':32,'cancelled':1}),
        'date_association':put(tmp_path/'invented-date-association.json',{'schema':'invented-date-association','no_observed_K':True})}
    purpose_pin=put(tmp_path/'view-purpose.json',purpose)
    config={'schema':'polar.reference-input-conversion-config/6','profile_id':VIEW_PROFILE,'namespace':'INVENTED',
            'input_ref':parent,'purpose':purpose_pin,'schedule':sp,'date_range':purpose['date_range']}
    out=tmp_path/'view-out';out.mkdir()
    return out,config,purpose,b''.join(lines)


def test_exact_rectangle_roles_lexemes_pointers_null_clocks_and_idempotency(tmp_path):
    out,cfg,purpose,parent_raw=view_fixture(tmp_path)
    parent=Path(cfg['input_ref']['path']);before=(parent.read_bytes(),parent.stat().st_mtime_ns)
    result=prepare_input(cfg,out,10**8);market=load_reference(result['input_ref'])
    assert result['rows']==1832 and market['symbols']==['BIL','VTI'] and len(market['dates'])==916
    assert result['role_counts']=={'source_dates':916,'source_rows':1832,'NAV_dates':716,'NAV_rows':1432,'VTI_warmup_rows':200,'BIL_unused_context_rows':200}
    m=json.loads(Path(result['input_ref']['path']).read_bytes())
    before_lines={(json.loads(line)['date'],json.loads(line)['symbol']):line for line in parent_raw.splitlines(keepends=True)}
    for line in Path(m['quotes']['path']).read_bytes().splitlines(keepends=True):
        r=json.loads(line);assert r['symbol']!='SHY' and line==before_lines[r['date'],r['symbol']]
        assert r['reference_quote']=='10.130000'
        assert r['observed_published_at'] is r['observed_historical_available_at'] is None
    role=json.loads(Path(result['date_roles']['path']).read_bytes())
    assert role['NAV']['dates']==purpose['roles']['nav_dates']
    assert role['WARMUP_CANDIDATE']['dates']==role['UNUSED_WARMUP_CONTEXT']['dates']==purpose['roles']['warmup_dates']
    assert set(role['NAV']['dates']).isdisjoint(role['WARMUP_CANDIDATE']['dates'])
    assert role['UNUSED_WARMUP_CONTEXT']['symbols']==['BIL'] and role['clock_eligibility']=='NOT_DERIVED'
    assert schedule_binding_matches(m,cfg['schedule'])
    assert {r['literal_alias'] for r in market['source_relations']['records']}=={'BIL','VTI'}
    assert market['source_relations']['source_view_parent']==cfg['input_ref']
    assert prepare_input(cfg,out,10**8)==result
    assert (parent.read_bytes(),parent.stat().st_mtime_ns)==before


@pytest.mark.parametrize('case', ['extra','shy','nav_duplicate','warmup_future','date_gap','count_bool','role_alias','namespace','basis','producer','semantic','purpose_pin','event_pin'])
def test_bad_metadata_rejected_before_values_or_output(tmp_path,monkeypatch,case):
    out,cfg,purpose,_=view_fixture(tmp_path)
    if case=='extra':cfg['unbound']=True
    elif case=='shy':purpose['symbols']=['BIL','SHY','VTI']
    elif case=='nav_duplicate':purpose['roles']['nav_dates'][1]=purpose['roles']['nav_dates'][0]
    elif case=='warmup_future':purpose['roles']['warmup_dates'][-1]=purpose['roles']['nav_dates'][0]
    elif case=='date_gap':purpose['roles']['nav_dates'][1]='2024-01-01'
    elif case=='count_bool':cfg['date_range']={**cfg['date_range'],'count':True};purpose['date_range']=cfg['date_range']
    elif case=='role_alias':purpose['roles']['warmup_symbol']='BIL'
    elif case=='purpose_pin':cfg['purpose']['sha256']='0'*64
    elif case=='event_pin':purpose['event_panel']['sha256']='0'*64
    else:
        m=json.loads(Path(cfg['input_ref']['path']).read_bytes())
        if case=='namespace':
            from polar.selected_reference_input import RIGHTS
            cfg['namespace']='RETAINED';purpose['rights']=RIGHTS;m['rights']=RIGHTS;m['parent_dataset_revision']='declared-retained'
        elif case=='basis':m['quote_basis']='RAW'
        elif case=='producer':m['conversion_metadata']['converter']='other'
        else:m['conversion_metadata']['semantic']['quotes_sha256']='0'*64
        cfg['input_ref']=put(tmp_path/'bad-parent.json',m);purpose['input_ref']=cfg['input_ref']
    if case!='purpose_pin':cfg['purpose']=put(tmp_path/'bad-purpose.json',purpose)
    def forbidden(*a,**k):raise AssertionError('NUMERIC_VALUE_OPEN_BEFORE_METADATA_REJECT')
    monkeypatch.setattr('polar.reference_composition.load_reference',forbidden)
    import polar.reference_composition as module
    old_read=module.pinned_bytes
    def metadata_read_only(pin):
        assert not str(pin.get('path','')).endswith('invented-full-quotes.ndjson'), 'NUMERIC_PIN_OPEN'
        return old_read(pin)
    monkeypatch.setattr(module,'pinned_bytes',metadata_read_only)
    with pytest.raises((ValueError,OSError)):prepare_input(cfg,out,10**8)
    assert not (out/'reference-inputs').exists()


def test_original_reader_rejects_sparse_output_and_never_uses_roles_to_relax_grid(tmp_path):
    out,cfg,_,_=view_fixture(tmp_path);r=prepare_input(cfg,out,10**8)
    m=json.loads(Path(r['input_ref']['path']).read_bytes());raw=Path(m['quotes']['path']).read_bytes()
    m['quotes']=put(tmp_path/'sparse-quotes.ndjson',b''.join(raw.splitlines(keepends=True)[1:]))
    bad=put(tmp_path/'sparse-manifest.json',m)
    with pytest.raises(ValueError,match='ROW_COUNT'):load_reference(bad)


def test_view_not_reaccepted_as_composer2_parent(tmp_path,monkeypatch):
    out,cfg,purpose,_=view_fixture(tmp_path);r=prepare_input(cfg,out,10**8)
    cfg['input_ref']=r['input_ref'];purpose['input_ref']=r['input_ref']
    cfg['purpose']=put(tmp_path/'nested-view-purpose.json',purpose)
    def forbidden(*a,**k):raise AssertionError('VALUE_READ')
    monkeypatch.setattr('polar.reference_composition.load_reference',forbidden)
    with pytest.raises(ValueError,match='PARENT'):prepare_input(cfg,tmp_path/'nested',10**8)
