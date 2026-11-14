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
from .gym_contract import canonical,decode,sha,MAX_BYTES
from .history_bundle import read_file
from .signed_native_bridge import require


def criterion_view(report):
    """Only operands used by unchanged study clauses; full reports stay saved."""
    return {k:deepcopy(report[k]) for k in ('terminal_cents','mean','variance','drawdown','ES','survival')}


def put_object(store,parent,prefix,value):
    raw=canonical(encode(value));require(len(raw)<=MAX_BYTES,'PAIR_STREAM_OBJECT_LIMIT')
    name=prefix+sha(raw)
    with store.locked():store._publish(parent,name,{'record.json':raw},file_limit=MAX_BYTES)
    return {'parent':parent,'id':name,'sha256':sha(raw),'bytes':len(raw)}


def read_object(root,ref):
    raw=read_file(root,ref['parent']+'/'+ref['id']+'/record.json',MAX_BYTES)
    require(sha(raw)==ref['sha256'] and len(raw)==ref['bytes'] and ref['id'].endswith(sha(raw)),
        'PAIR_STREAM_OBJECT_PIN')
    return restore(decode(raw))


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


def save_prefix(store,parent,value,*,max_bytes=None):
    """Chunk actual active record/bridge prefixes with the existing8MiB codec."""
    native=value.get('native') or {};header={k:v for k,v in native.items() if k not in ('records','bridge_events')}
    files,records=chunk_rows(native.get('records',[]),'records')
    bridge_files,bridge=chunk_rows(native.get('bridge_events',[]),'bridge');files.update(bridge_files)
    other={k:v for k,v in value.items() if k!='native'}
    # NAV/D receipts can also grow; keep every supplied operand in bounded chunks.
    nav_files,nav=chunk_rows(other.pop('NAV',[]),'nav');files.update(nav_files)
    d_files,decisions=chunk_rows(other.pop('D_receipts',[]),'decisions');files.update(d_files)
    raw=canonical(encode({'schema':'polar.pair-stream-active-prefix/1','native_header':header,'other':other,
        'records':records,'bridge':bridge,'NAV':nav,'D_receipts':decisions,'completed_account':False}))
    require(len(raw)<=MAX_BYTES,'PAIR_STREAM_PARTIAL_HEADER');files['record.json']=raw;name='prefix-'+sha(raw)
    require(max_bytes is None or sum(len(v) for v in files.values())<=max_bytes,'PAIR_OPERATION_PARTIAL_AGGREGATE_LIMIT')
    with store.locked():store._publish(parent,name,files,file_limit=MAX_BYTES)
    return {'parent':parent,'id':name,'sha256':sha(raw),'bytes':len(raw),'aggregate_bytes':sum(len(v) for v in files.values())}
