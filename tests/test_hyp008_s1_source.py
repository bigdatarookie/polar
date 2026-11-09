"""Metadata-only literal controls: nominal window selection precedes value/K."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from polar.hyp008_s1_source import Eligibility,Opportunity,SourceBinding,prepare_metadata,S1SourceError,clock


def iso(dt):return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def eligible(known='2016-01-01T00:00:00Z',unit='X'):
    return Eligibility('OK',(),known,'basis','v1',unit,'literal-reference')


def inputs():
    start=datetime(2020,1,1,tzinfo=timezone.utc);rows=[]
    dates=[start+timedelta(days=7*i) for i in range(60)]+[datetime(2022,1,10,tzinfo=timezone.utc)]
    for i,d in enumerate(dates):
        end=d+timedelta(days=3)
        rows.append(Opportunity(f'id{i}',iso(d),iso(end),iso(end),eligible(unit='A_PACKET'),
             tuple(eligible() for _ in range(5)),eligible(iso(end),'B'),'literal-source',d.strftime('%Y-%m-%d')))
    binding=SourceBinding('INVENTED','v1','a'*64,'b'*64,'basis','v1',('X',)*5,'basis','v1','B',len(rows))
    return tuple(rows),binding


def test_full_census_train_mask_and_fixed_window():
    rows,binding=inputs();result=prepare_metadata(rows,binding)
    assert result['full_census']==[r.opportunity_id for r in rows]
    assert len(result['training'])==60 and all(r['admitted'] for r in result['training'])
    assert result['I']==result['P']==['id60']
    assert result['C'][0]['history_window']==[f'id{i}' for i in range(8,60)]
    assert result['scientific_starts']==0 and not result['numeric_work_performed']


def test_bad_anchor_not_slid_or_topped_up():
    rows,binding=inputs();row=rows[59]
    bad=replace(row.B,status='UNAVAILABLE',reasons=('ABSENT',))
    rows=rows[:59]+(replace(row,B=bad),)+rows[60:]
    result=prepare_metadata(rows,binding)
    assert result['I']==[] and result['reason']=='NO_ISSUE_COMPARISON'
    assert result['C'][0]['history_anchor']=='id59'
    assert result['C'][0]['history_window'][-1]=='id59'
    assert any('HISTORY:id59' in r for r in result['C'][0]['I_reasons'])


def test_current_label_does_not_change_issue_mask():
    rows,binding=inputs();last=rows[-1]
    rows=rows[:-1]+(replace(last,B=replace(last.B,status='UNAVAILABLE',reasons=('TAIL',))),)
    result=prepare_metadata(rows,binding)
    assert result['I']==['id60'] and result['E']==result['P']==[]


def test_training_maturity_and_feature_historical_k_independent():
    rows,binding=inputs();first=rows[0]
    rows=(replace(first,common_A=replace(first.common_A,known_by='2023-01-01T00:00:00Z')),)+rows[1:]
    result=prepare_metadata(rows,binding)
    assert not result['training'][0]['admitted']
    assert 'A:KNOWN_BY_AFTER_CUTOFF' in result['training'][0]['reasons']
    assert result['I']==['id60']


def test_duplicate_and_unknown_clock_rejected_or_unavailable():
    rows,binding=inputs()
    with pytest.raises(S1SourceError,match='DUPLICATE'):
        prepare_metadata((rows[0],)*len(rows),binding)
    last=rows[-1];rows=rows[:-1]+(replace(last,common_A=replace(last.common_A,known_by=None)),)
    assert prepare_metadata(rows,binding)['I']==[]
    assert clock('2022-01-01T01:00:00+01:00')==clock('2022-01-01T00:00:00Z')


def test_delivered_shape_adapter_is_value_free_and_preserves_unknown_observed_clocks():
    import json
    from polar.hyp008_s1_source import adapt_metadata_row
    rows,b=inputs();binding=replace(b,x_units=('X',)*5,x_version='v1')
    ref={'path':'/literal/source.json','bytes':10,'sha256':'c'*64}
    payload=object()  # Deliberately not serializable or castable by this interface.
    row={'index':0,'opportunity_id':'invented-row','D':'2022-01-10T00:00:00+00:00',
         'decision_date':'2022-01-10','A':{'A_status':'READY_CONDITIONAL','A_reasons':[],
             'A_required_K':'2022-01-09T00:00:00Z'},
         'B':{'status':'DEFINED_CONDITIONAL','reasons':[],'required_K':'2022-01-20T00:00:00Z',
             'scheduled_end':'2022-01-20T00:00:00Z','unit':'B','represented_fraction':payload,
             'numeric_source_ref':ref},
         'X':{s:{'numeric_status':'AVAILABLE_AS_STORED','represented_source_payload':payload,
                'unit':'X','source_ref':ref,'source_field':'LIQUIDITY' if s=='MEDIAN_DV20' else s}
              for s in ('RET1','RET5','VOL20','DOWN20','MEDIAN_DV20')},
         'capability_basis':'basis','clock_assurance':'modeled','observed_clocks':
             {'published_at':None,'available_at':None,'ingested_at':None},
         'historical_D_feature_information_check':'PUBLICATION_ONLY',
         'Ghist_W_fold_S_transform_solver_fit_score_masks':'UNBOUND_NOT_SELECTED',
         'source_row_ref':ref,'history_metadata_ref':ref,'opportunity_metadata_ref':ref}
    result=adapt_metadata_row(row,binding)
    assert result.nominal_date=='2022-01-10'
    assert json.loads(result.source_metadata_json)['observed_clocks']==row['observed_clocks']
    row['X']['RET1']['numeric_status']='UNAVAILABLE_AS_STORED'
    row['X']['RET1']['represented_source_payload']=None
    # Unavailable slot reference is preserved without opening any child path.
    result=adapt_metadata_row(row,binding)
    assert result.X[0].status=='UNAVAILABLE'
