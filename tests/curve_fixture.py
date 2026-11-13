"""Entirely invented B8-shaped source, including a fictional holiday schedule."""
from datetime import date,timedelta,datetime,timezone
from pathlib import Path
import json,hashlib,subprocess
from reference_fixture import write
from polar.gym_contract import canonical,sha
from polar.scheduled_service import config_from_seed


def fixture(tmp_path,monkeypatch,*,raw_ref=None):
    root=tmp_path/'store';root.mkdir();monkeypatch.setenv('POLAR_ARTIFACT_ROOT',str(root))
    first,last=date(2022,12,30),date(2026,11,6)
    candidates=[first+timedelta(days=i) for i in range((last-first).days+1) if (first+timedelta(days=i)).weekday()<5]
    monthlast={d for d in candidates if d==last or (d+timedelta(days=1)).month!=d.month or
               next((x for x in candidates if x>d),last).month!=d.month}
    # Deterministic fictional closures: date metadata only, no actual market file.
    removable=[d for d in candidates[1:-1] if d not in monthlast]
    needed=len(candidates)-967;remove=set(removable[::max(1,len(removable)//needed)][:needed]);nav=[d.isoformat() for d in candidates if d not in remove]
    days=['2022-12-26','2022-12-27','2022-12-28','2022-12-29']+nav
    rows=[];quotes=[]
    for i,day in enumerate(days):
        rows.append({'date':day,'reference_open_utc':day+'T14:30:00+00:00','reference_close_utc':day+'T21:00:00+00:00',
            'next_reference_date':days[i+1] if i+1<len(days) else None,
            'month_end_in_reference_range':days[i+1][:7]!=day[:7] if i+1<len(days) else None})
        for symbol in ['AAA','VTI']:
            token=str(100000000+1000*i+(i%13-6)*10000)
            price=str(int(token)//1000000)+'.'+str(int(token)%1000000).zfill(6)
            quotes.append({'symbol':symbol,'date':day,'reference_quote':price,'source_adjusted_close_token':price,
                'source_ref':{'normalized_member_sha256':'a'*64,'line_1based':i+1,'line_sha256':'b'*64,
                    'raw_object_sha256':'c'*64,'source_row_index':i},'observed_published_at':None,'observed_historical_available_at':None})
    schedule=write(tmp_path/'schedule.json',{'schema':'polar.xnys-reference-schedule/1','rows':rows})
    qp=tmp_path/'quotes.ndjson';qp.write_bytes(b''.join(canonical(q) for q in quotes));qref={'path':str(qp),'sha256':sha(qp.read_bytes()),'bytes':qp.stat().st_size}
    equity=write(tmp_path/'equity.json',{'schema':'polar.synthetic-reference-source-input/1',
        'quote_basis':'VENDOR_SPLIT_AND_DIVIDEND_ADJUSTED_REFERENCE_CLOSE','unit_type':'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
        'double_action_policy':'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL','symbols':['AAA','VTI'],
        'dates':{'count':len(days),'start':days[0],'end':days[-1]},'rows':2*len(days),'schedule':schedule,'quotes':qref,
        'source_members':[{'sha256':'a'*64}],'parent_dataset_revision':'INVENTED-PUBLIC-CURVE',
        'rights':'INVENTED_PUBLIC_TEST','provenance':{'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'}})
    decisions=[{'signal_date':d,'signal_index':i,'execution_date':days[i+1],
        'execution_reference_close_utc':rows[i+1]['reference_close_utc']} for i,d in enumerate(days[:-1])
        if d>=nav[0] and rows[i]['month_end_in_reference_range'] and days[i+1]<nav[-1]]
    assert len(decisions)==47 and len(nav)==967
    grid={'initial':nav[0],'terminal':nav[-1],'nav_dates':nav,'nav_points':967,'return_count':966,'decisions':decisions,'decision_count':47}
    calendar={'schema':'polar.scheduled-policy-calendar/1','source_schedule':schedule,'phases':{'FINAL':grid}}
    cp=write(tmp_path/'calendar.json',calendar)
    macro=[];index=[];offset=0
    start=date(2022,12,1)
    for i in range((last-start).days+1):
        current=start+timedelta(days=i)
        if current.weekday()==0:continue  # Fictional source-only Sunday may be the latest eligible row.
        d=current.isoformat()
        two,ten=[('2.0000000000000000000000000000000000001','2.0000000000000000000000000000000000002'),
                 ('0.00','0.00'),('-1.01','-1.02')][i%3]
        row={'source_date':d,'tokens':{'NEW_DATE':d+'T00:00:00','BC_2YEAR':two,'BC_10YEAR':ten},
             'raw_ref':dict(raw_ref) if raw_ref is not None else {'path':'/INVENTED-NOT-READ.xml','sha256':'e'*64,'bytes':10000,'complete':True},
             'raw_pointers':{f:{'field':f,'byte_start':10*j,'byte_end_exclusive':10*j+5,'xml_entry_ordinal_zero_based':i} for j,f in enumerate(['NEW_DATE','BC_2YEAR','BC_10YEAR'])},
             'captured_at':'2030-01-01T00:00:00Z','entry_updated':None,'feed_updated':None,
             'historical_K':None,'historical_available_at':None,'method_context':'MONOTONE_CONVEX_CONTEXT'}
        raw=canonical(row);macro.append(raw);index.append({'date':d,'line_1based':len(macro),'byte_start':offset,'byte_end_exclusive':offset+len(raw),
            'fields':['BC_2YEAR','BC_10YEAR'],'conflict':False,'historical_K':None});offset+=len(raw)
    mp=tmp_path/'macro.ndjson';mp.write_bytes(b''.join(macro));macroref={'path':str(mp),'sha256':sha(mp.read_bytes()),'bytes':mp.stat().st_size}
    ip=write(tmp_path/'index.json',{'schema':'polar.scheduled-curve-index/1','macro_records_sha256':macroref['sha256'],'records':index})
    joins=[]
    for e in decisions:
        i=days.index(e['signal_date']);cutoff=days[i-2];selected=max(d['date'] for d in index if d['date']<=cutoff)
        joins.append({'formation_date':e['signal_date'],'execution_date':e['execution_date'],'cutoff_date':cutoff,
            'selected_treasury_date':selected,'civil_age_days':(date.fromisoformat(e['signal_date'])-date.fromisoformat(selected)).days})
    proof=write(tmp_path/'dateproof.json',{'joins':joins,'scope':'INVENTED DATE-ONLY'})
    purpose=write(tmp_path/'purpose.json',{'scope':'INVENTED PUBLIC FIXTURE; NO SOURCE PAYLOADS'})
    descriptor={'schema':'polar.scheduled-curve-input/1','reference_input_ref':equity,'macro_records_ref':macroref,
        'macro_index_ref':ip,'source_date_join_ref':proof,'purpose_ref':purpose,'source_delivery_ref':purpose,
        'rights':'INVENTED_PUBLIC_TEST','provenance':{'kind':'DETERMINISTIC_INVENTED_FIXTURE','source_payloads':'NONE'},
        'historical_K':None,'limitations':['INVENTED ONLY']}
    dp=write(tmp_path/'input.json',descriptor);protocol=write(tmp_path/'protocol.json',{'id':'INVENTED-CURVE','source_payloads':'NONE'})
    tz=tmp_path/'UTC';tz.write_bytes(Path('/usr/share/zoneinfo/UTC').read_bytes())
    criteria=[{'id':k,'description':k,'kind':k,'left_id':'CURVE_VTI',**({} if k=='POSITIVE_GROWTH' else {'right_id':'HALF_VTI'}),
        **({'threshold':'0.10'} if k=='SR_DELTA_GE' else {'lower':'0.8','upper':'1.25'} if k=='VOL_RATIO_BETWEEN' else {})}
        for k in ['TERMINAL_GT','SR_DELTA_GE','DRAWDOWN_LE','VOL_RATIO_BETWEEN','POSITIVE_GROWTH']]
    profile={'schema':'polar.scheduled-reference-profile/11','protocol_id':'INVENTED-CURVE',
        'protocol_sha256':protocol['sha256'],'input_sha256':dp['sha256'],'calendar_sha256':cp['sha256'],
        'timezone_sha256':sha(tz.read_bytes()),'symbols':['VTI'],
        'policy':{'kind':'TREASURY_2Y10Y_SIGN','lag_sessions':2,'max_age_days':10,'symbol':'VTI','drawdown_peak':'EARLIEST_EQUAL_PEAK'},
        'legs':[{'id':i,'label':i,'rule':r,'scale':s} for i,r,s in [('CURVE_VTI','CURVE',[1,1]),('HALF_VTI','FIXED',[1,2]),('FULL_VTI','FIXED',[1,1]),('CASH','CASH',[0,1])]],
        'primary_strategy':'CURVE_VTI','primary_benchmark':'HALF_VTI','decision_delay_seconds':60,'criteria':criteria,
        'cost_scenarios':[{'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},{'id':'COST_STRESS','cost_profile':{'flat_cents':200,'bps':20}}],
        'question_label':'Invented curve fixture','question_summary':'Fictional literal signed rate tokens and prices only.',
        'clock_description':'Modeled UTCmidnight D60; observed availability unknown.',
        'partition_description':'FINAL only; no fit, uncertainty or bootstrap.',
        'additional_limitations':[['INVENTED_ONLY','Not a research result.']],
        'subperiods':[[nav[0],'2024-12-31'],['2024-12-31',nav[-1]]]}
    assert '2024-12-31' in nav
    pp=write(tmp_path/'profile.json',profile)
    cfg=config_from_seed({'schema':'polar.scheduled-reference-seed/1','namespace':'INVENTED','profile_path':pp['path'],
        'protocol_path':protocol['path'],'input_path':dp['path'],'calendar_path':cp['path'],'timezone_path':str(tz),
        'code_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'runtime_image_id':'sha256:'+'f'*64,'candidate_id':'INVENTED-CURVE','experiment_id':'INVENTED-CURVE-ORIGINAL'})
    return root,cfg,profile,calendar,descriptor
