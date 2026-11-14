"""Bounded private pair graph: one full account, verified candidate receipt, refs.

No retained admission here. Service owns debit, resources and durable observer.
Legacy all-account APIs remain available; this is an explicit streaming path.
"""
from copy import deepcopy
from .signed_pair_input import CONTROLS,CASES
from .signed_pair_producer import produce_account
from .signed_pair_saved import (publish_account,verify_stored_account,candidate_receipt,
    member_census,chunk_rows,read_chunk_rows,exact_members)
from .signed_pair_metrics import metrics,evaluate_reports
from .signed_event_saved import encode,restore
from .signed_pair_wire import wire_bytes,wire_read
from .gym_contract import canonical,decode,sha,MAX_BYTES
from .history_bundle import read_file
from .signed_native_bridge import require


def criterion_view(report):
    """Only operands used by unchanged study clauses; full reports stay saved."""
    return {k:deepcopy(report[k]) for k in ('terminal_cents','mean','variance','drawdown','ES','survival')}


def put_object(store,parent,prefix,value):
    raw=wire_bytes(value);require(len(raw)<=MAX_BYTES,'PAIR_STREAM_OBJECT_LIMIT')
    name=prefix+sha(raw)
    with store.locked():store._publish(parent,name,{'record.json':raw},file_limit=MAX_BYTES)
    return {'parent':parent,'id':name,'sha256':sha(raw),'bytes':len(raw)}


def read_object(root,ref):
    raw=read_file(root,ref['parent']+'/'+ref['id']+'/record.json',MAX_BYTES)
    require(sha(raw)==ref['sha256'] and len(raw)==ref['bytes'] and ref['id'].endswith(sha(raw)),
        'PAIR_STREAM_OBJECT_PIN')
    return wire_read(raw)


def stream_members(data,emit,observer):
    """Emit before next producer. No list of accounts or retained candidate tape."""
    members=[];activations={};proof=None
    for case in CASES:
        proof=None
        for control in CONTROLS:
            observer('ACCOUNT_ENTRY',{'control':control,'case':case})
            account=produce_account(data,control,case,activation=activations.get(case),observer=observer)
            observer('ACCOUNT_COMPLETED',{'control':control,'case':case})
            member,new_proof=emit(account,proof)
            members.append(member)
            if control=='DYNAMIC_SPREAD':
                proof=new_proof;activations[case]=deepcopy(account['activation'])
            observer('ACCOUNT_PERSISTED',{'control':control,'case':case,'member':member})
            del account,new_proof
    member_census([(v['control'],v['case']) for v in members])
    return members,activations


def produce_stream(data,store,binding,observer):
    def emit(account,proof):
        ref=publish_account(store,account,binding,_candidate_receipt=proof)
        report=metrics(account)
        report_ref=put_object(store,'pair-stream-reports','pair-metrics-',report)
        member={'control':account['control'],'case':account['case'],'account':ref,'metrics':report_ref,
            'criteria':criterion_view(report)}
        receipt=candidate_receipt(account,binding,ref) if account['control']=='DYNAMIC_SPREAD' else None
        return member,receipt
    members,activations=stream_members(data,emit,observer)
    return publish_graph(store,members,activations,binding)


def publish_graph(store,members,activations,binding):
    member_census([(v['control'],v['case']) for v in members])
    require([(v['control'],v['case']) for v in members]==[(c,p) for p in CASES for c in CONTROLS],
        'PAIR_STREAM_ORDERED_MEMBERSHIP')
    require(set(activations)==set(CASES),'PAIR_STREAM_ACTIVATION_CENSUS')
    report={v['control']+'/'+v['case']:v['criteria'] for v in members}
    evaluation=evaluate_reports(report,activations)
    graph={'schema':'polar.private-fixed-pair-stream-graph/1','binding':binding,'members':members,
        'activations':activations,'evaluation':evaluation,'metric_projection':'CRITERION_OPERANDS_ONLY_FULL_REPORT_REFS',
        'actual_native_completed':48,'financial_assessment':'NOT_ISSUED'}
    return put_object(store,'pair-study-components','pair-stream-study-',graph)


def verify_stream(root,ref,binding):
    graph=read_object(root,ref)
    require(graph['schema']=='polar.private-fixed-pair-stream-graph/1' and graph['binding']==binding and
        graph['actual_native_completed']==48 and graph['metric_projection']=='CRITERION_OPERANDS_ONLY_FULL_REPORT_REFS',
        'PAIR_STREAM_GRAPH_BINDING')
    pairs=[(v['control'],v['case']) for v in graph['members']];member_census(pairs)
    require(pairs==[(c,p) for p in CASES for c in CONTROLS],'PAIR_STREAM_ORDERED_MEMBERSHIP')
    reports={};activations={};proof=None
    for member in graph['members']:
        candidate=member['control']=='DYNAMIC_SPREAD'
        if candidate:proof=None
        account=verify_stored_account(root,member['account'],binding,_candidate_receipt=proof)
        require((account['control'],account['case'])==(member['control'],member['case']),
            'PAIR_STREAM_MEMBER_CONTEXT')
        if candidate:
            proof=candidate_receipt(account,binding,member['account'])
            activations[member['case']]=deepcopy(account['activation'])
        require(account['activation']==activations[member['case']],'PAIR_STREAM_ACTUAL_ACTIVATION_JOIN')
        report=metrics(account);saved=read_object(root,member['metrics'])
        require(encode(report)==encode(saved) and criterion_view(report)==member['criteria'],
            'PAIR_STREAM_RECOMPUTED_METRICS')
        reports[member['control']+'/'+member['case']]=criterion_view(report)
        del account,report,saved
    evaluation=evaluate_reports(reports,activations)
    require(activations==graph['activations'] and encode(evaluation)==encode(graph['evaluation']),
        'PAIR_STREAM_COMPLETE_EVALUATION_JOIN')
    return {'status':'VERIFIED_PRIVATE_STREAM_STUDY','graph':ref,'evaluation':evaluation,
        'verified_members':48,'native_calls':0,'source_reads':0,'feature_calls':0,'writes':0,
        'financial_assessment':'NOT_ISSUED','full_tapes_retained_in_reader':False}


def save_prefix(store,parent,value,*,max_bytes=None,max_logical_bytes=None):
    """Content-share immutable prefix chunks; no cumulative copy of old prefixes."""
    native=value.get('native') or {};header={k:v for k,v in native.items() if k not in ('records','bridge_events')}
    other={k:v for k,v in value.items() if k!='native'}
    series={'records':native.get('records',[]),'bridge':native.get('bridge_events',[]),
        'NAV':other.pop('NAV',[]),'D_receipts':other.pop('D_receipts',[])}
    shared={};groups={};logical=0
    for label,rows in series.items():
        files,refs=chunk_rows(rows,label.lower())
        groups[label]=[]
        for r in refs:
            compressed=files[r['name']];name='prefix-chunk-'+sha(compressed)
            shared[name]=compressed
            groups[label].append({**r,'storage_parent':'pair-stream-prefix-chunks/'+name})
            logical+=len(compressed)
    raw=wire_bytes({'schema':'polar.pair-stream-active-prefix/2','native_header':header,'other':other,
        'chunks':groups,'completed_account':False})
    require(len(raw)<=MAX_BYTES,'PAIR_STREAM_PARTIAL_HEADER');name='prefix-'+sha(raw);logical+=len(raw)
    require(max_logical_bytes is None or logical<=max_logical_bytes,'PAIR_OPERATION_PARTIAL_LOGICAL_LIMIT')
    with store.locked():
        new=sum(len(raw) for key,raw in shared.items() if not (store.root/'pair-stream-prefix-chunks'/key).exists())
        if not (store.root/parent/name).exists():new+=len(raw)
        require(max_bytes is None or new<=max_bytes,'PAIR_OPERATION_PARTIAL_AGGREGATE_LIMIT')
        for key,compressed in shared.items():
            store._publish('pair-stream-prefix-chunks',key,{'chunk-00000.json.gz':compressed},file_limit=MAX_BYTES//4)
        store._publish(parent,name,{'record.json':raw},file_limit=MAX_BYTES)
    return {'parent':parent,'id':name,'sha256':sha(raw),'bytes':len(raw),'aggregate_bytes':logical,'new_bytes':new}


def verify_prefix(root,ref):
    header=read_object(root,ref);require(header['schema']=='polar.pair-stream-active-prefix/2' and
        header['completed_account'] is False,'PAIR_STREAM_PREFIX_SCHEMA')
    restored={};aggregate=ref['bytes']
    for label,refs in header['chunks'].items():
        rows=[]
        for i,r in enumerate(refs):
            require(r['name']==label.lower()+'-'+str(i).zfill(5)+'.json.gz' and r['first']==len(rows) and
                r['storage_parent']=='pair-stream-prefix-chunks/prefix-chunk-'+r['sha256'],
                'PAIR_STREAM_PREFIX_CHUNK_JOIN')
            single={k:v for k,v in r.items() if k not in ('name','first','storage_parent')}
            single.update(name='chunk-00000.json.gz',first=0)
            value,total=read_chunk_rows(root,r['storage_parent'],[single],'chunk')
            rows.extend(value);aggregate+=total
        restored[label]=rows
    require(aggregate==ref['aggregate_bytes'],'PAIR_STREAM_PREFIX_COMPLETE_BYTES')
    return {'schema':'polar.private-pair-active-prefix/1','native':{**header['native_header'],
        'records':restored['records'],'bridge_events':restored['bridge']},**header['other'],
        'NAV':restored['NAV'],'D_receipts':restored['D_receipts'],'completed_account':False}
