"""Executable invented one-fit/two-phase service and stored-only/API wire controls."""
from datetime import date,timedelta
import calendar as calendar_module
import hashlib
import json
from pathlib import Path
import subprocess
from zoneinfo import TZPATH
import pytest

from polar.reference_service import ReferenceResearchService,A,INVENTED_A,config_from_seed
from polar.research_results import ResearchResults


def write(path,value):
    path.write_bytes((json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode())
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}


def fixture(tmp_path, monkeypatch):
    root=tmp_path.resolve();store=root/'store';store.mkdir();monkeypatch.setenv('POLAR_ARTIFACT_ROOT',str(store))
    symbols=['AAA','BBB','CCC','DDD'];days=[(date(2018,1,1)+timedelta(days=i)).isoformat() for i in range(400)]
    schedule=[];quotes=[]
    for i,d in enumerate(days):
        schedule.append({'date':d,'reference_open_utc':d+'T14:30:00+00:00','reference_close_utc':d+'T21:00:00+00:00',
            'next_reference_date':days[i+1] if i+1<len(days) else None,
            'month_end_in_reference_range':(days[i+1][:7]!=d[:7]) if i+1<len(days) else None})
        for j,s in enumerate(symbols):
            token=f'{10+i//100}.{i%100:02d}{j}0'
            quotes.append({'symbol':s,'date':d,'reference_quote':token+'00','source_adjusted_close_token':token,
                'source_ref':{'normalized_member_sha256':'a'*64,'line_1based':i+1,'line_sha256':'b'*64,
                              'raw_object_sha256':'c'*64,'source_row_index':i},
                'observed_published_at':None,'observed_historical_available_at':None})
    sp=write(root/'schedule.json',{'schema':'polar.xnys-reference-schedule/1','rows':schedule})
    qpath=root/'quotes.ndjson';qpath.write_bytes(b''.join((json.dumps(q,sort_keys=True,separators=(',',':'))+'\n').encode() for q in quotes))
    qp={'path':str(qpath),'sha256':hashlib.sha256(qpath.read_bytes()).hexdigest(),'bytes':qpath.stat().st_size}
    manifest={'schema':'polar.synthetic-reference-source-input/1','quote_basis':'VENDOR_SPLIT_AND_DIVIDEND_ADJUSTED_REFERENCE_CLOSE',
        'unit_type':'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE','double_action_policy':'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL',
        'symbols':symbols,'dates':{'count':400,'start':days[0],'end':days[-1]},'rows':1600,'schedule':sp,'quotes':qp,
        'source_members':[{'sha256':'a'*64}],'parent_dataset_revision':'INVENTED-PUBLIC-FIXTURE','rights':'INVENTED_PUBLIC_TEST',
        'provenance':{'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'}}
    mp=write(root/'manifest.json',manifest)
    cycles=[{'signal':days[i],'signal_index':i,'entry':days[i+1],'label_exit':days[i+22]} for i in [252,274]]
    def grid(lo,hi):
        monthly=sum(schedule[i]['month_end_in_reference_range'] is True and days[i+1]<days[hi] for i in range(lo,hi))
        return {'initial':days[lo],'terminal':days[hi],'first_execution':days[lo+1],
                'nav_points':hi-lo+1,'returns':hi-lo,'monthly_decisions':monthly}
    cp=write(root/'calendar.json',{'source_schedule':sp,'training_cycles':cycles,'training_rows':8,
        'validation_financial_grid':grid(320,350),'final_financial_grid':grid(351,399),
        'validation_complete_label_cycles':[{'signal':days[333],'signal_index':333,'entry':days[334],'label_exit':days[340]}],
        'final_complete_label_cycles':[{'signal':days[364],'signal_index':364,'entry':days[365],'label_exit':days[395]}]})
    timezone_path=next((Path(p)/'America/New_York' for p in TZPATH if (Path(p)/'America/New_York').is_file()),None)
    if timezone_path is None:
        from importlib.resources import files
        raw=files('tzdata').joinpath('zoneinfo/America/New_York').read_bytes()
    else:raw=timezone_path.read_bytes()
    tz=root/'New_York';tz.write_bytes(raw)
    pp=write(root/'protocol.json',{'schema':'polar.invented-reference-protocol/1','profile_id':INVENTED_A,
        'fit_event':days[310]+'T00:00:30+00:00','classification':'INVENTED','calendar_sha256':cp['sha256'],
        'timezone_sha256':hashlib.sha256(raw).hexdigest(),'input_sha256':mp['sha256']})
    revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    cfg=config_from_seed({'namespace':'INVENTED','profile_id':INVENTED_A,'protocol_path':pp['path'],'input_path':mp['path'],
        'calendar_path':cp['path'],'timezone_path':str(tz),'code_revision':revision,'runtime_image_id':'sha256:'+'f'*64,
        'candidate_id':'INVENTED-A','experiment_id':'INVENTED-A-ONE-FIT'})
    return store,cfg

