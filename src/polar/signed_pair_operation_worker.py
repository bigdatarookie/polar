"""Trusted finite B11 child: actual producer entry, durable counters and prefix.

The outer existing process supervisor owns kill/accounting. No dispatch/retry.
"""
from pathlib import Path
from dataclasses import asdict
import sys,json,time,os
from .gym_contract import canonical,decode,sha,read_ref,MAX_BYTES
from .signed_event_saved import encode,restore
from .signed_pair_input import PairInput,Quote,Formation,CONTROLS,CASES
from .signed_event_driver import Action
from .signed_pair_saved import binding_for
from .signed_pair_stream import produce_stream,save_prefix,verify_stream
from .signed_pair_operation import binding,family,read_index,SEMANTIC
from .gym_service import code_binding
from .gym_store import GymStore
from .history_bundle import read_file
from .signed_native_bridge import require

COUNTERS={'source_load_entries':0,'scientific_entries':0,'saved_entries':0,'account_entries':0,
 'native_call_entries':0,'native_accounts_observed':0,'native_completed':0,'account_completed':0,
 'account_persisted':0,'decision_entries':0,'feature_entries':0,'fill_callbacks':0,'event_checkpoints':0}
KIND={'ACCOUNT_ENTRY':'account_entries','NATIVE_CALL_ENTRY':'native_call_entries',
 'NATIVE_ACCOUNT_OBSERVED':'native_accounts_observed','NATIVE_COMPLETED':'native_completed',
 'ACCOUNT_COMPLETED':'account_completed','ACCOUNT_PERSISTED':'account_persisted','DECISION_ENTRY':'decision_entries',
 'FEATURE_ENTRY':'feature_entries','FILL_CALLBACK':'fill_callbacks','EVENT_CHECKPOINT':'event_checkpoints',
 'SOURCE_LOAD_ENTRY':'source_load_entries','SCIENTIFIC_ENTRY':'scientific_entries','SAVED_ENTRY':'saved_entries'}


class LimitedStore(GymStore):
    def __init__(self,root,limit,object_bytes):
        super().__init__(root,limit);self.object_bytes=object_bytes
    def _publish(self,parent,name,files,*,file_limit=MAX_BYTES):
        require(all(len(v)<=self.object_bytes for v in files.values()),'PAIR_OPERATION_OBJECT_LIMIT')
        return super()._publish(parent,name,files,file_limit=min(file_limit,self.object_bytes))


class Collector:
    def __init__(self,store,path,limits):
        self.store=store;self.path=path;self.limits=limits;self.counts=dict(COUNTERS);self.seq=0
        self.counter_bytes=0;self.partial_bytes=0;self.latest=None;self.current=None;self.since=0;self.observed=dict(COUNTERS)
    def __call__(self,kind,payload):
        require(kind in KIND or kind=='NATIVE_PARTIAL','PAIR_OPERATION_UNKNOWN_ENTRY')
        next_counts=dict(self.observed)
        if kind in KIND:next_counts[KIND[kind]]+=1
        if kind=='ACCOUNT_ENTRY':
            i=next_counts['account_entries']-1
            require(i<48 and (payload['control'],payload['case'])==[(c,p) for p in CASES for c in CONTROLS][i],
                'PAIR_OPERATION_ORDERED_ACCOUNT_ENTRY')
            self.current={'control':payload['control'],'case':payload['case']};self.latest=None;self.since=0
        require(next_counts['native_call_entries']<=48 and next_counts['account_entries']<=48 and
            next_counts['scientific_entries']<=1 and next_counts['saved_entries']<=1,'PAIR_OPERATION_ENTRY_BOUND')
        detail=payload.get('details',payload)
        detail={k:v for k,v in detail.items() if k not in ('snapshot','member')}
        self.since+=1;self.observed=next_counts
        snapshot=payload.get('snapshot')
        # Native/feature/decision/account boundaries are always synchronous.
        # Routine already-completed event/fill callbacks are checkpointed in
        # bounded batches rather than fsyncing a second tape one row at a time.
        if kind in ('EVENT_CHECKPOINT','FILL_CALLBACK') and self.since<self.limits['checkpoint_interval_events']:
            return
        if snapshot is not None and (kind in ('NATIVE_PARTIAL','NATIVE_ACCOUNT_OBSERVED') or self.since>=self.limits['checkpoint_interval_events']):
            before=self.store.used();ref=save_prefix(self.store,self.path+'/checkpoints',snapshot(),max_bytes=self.limits['partial_bytes']-self.partial_bytes)
            added=self.store.used()-before;self.partial_bytes+=added
            require(self.partial_bytes<=self.limits['partial_bytes'],'PAIR_OPERATION_PARTIAL_AGGREGATE_LIMIT')
            self.latest=ref;self.since=0
        record={'schema':'polar.private-pair-durable-counter/1','sequence':self.seq,'kind':kind,'details':detail,
            'account':self.current,'increments':{k:next_counts[k]-self.counts[k] for k in COUNTERS},'counters':next_counts,'latest_prefix':self.latest,'recorded_ns':time.time_ns(),
            'frontier':'EXACT_OBSERVED_PREFIX_NOT_UNOBSERVED_TOTAL'}
        if kind=='ACCOUNT_PERSISTED':record['member']=payload['member']
        raw=canonical(encode(record));require(self.counter_bytes+len(raw)<=self.limits['counter_bytes'],
            'PAIR_OPERATION_COUNTER_OUTPUT_LIMIT')
        with self.store.locked():self.store._publish(self.path+'/counters',str(self.seq).zfill(8),{'record.json':raw})
        self.counter_bytes+=len(raw);self.seq+=1;self.counts=next_counts


def load_input(source,expected):
    # Only called after immutable FIRST_START and durable SOURCE_LOAD_ENTRY.
    x=restore(decode(read_ref(source['encoded_input'])))
    value=PairInput(**{**x,'quotes':tuple(Quote(**r) for r in x['quotes']),
        'formations':tuple(Formation(**r) for r in x['formations']),'actions':tuple(Action(**r) for r in x['actions'])})
    require(binding_for(value)==expected,'PAIR_OPERATION_LOADED_INPUT_CONTENT_BINDING')
    return value


def context(root,path,limit):
    raw=read_file(root,path+'/start/config.json',MAX_BYTES);config=decode(raw)
    start=restore(decode(read_file(root,path+'/start/record.json',MAX_BYTES)))
    require(start['binding']==binding(config) and config['code']==code_binding(), 'PAIR_OPERATION_CHILD_CURRENT_BINDING')
    resources=decode(read_ref(config['resources_ref']))['limits']
    # Root quota already certified before admission; worker cannot increase it.
    store=LimitedStore(root,min(limit,start['store_used_before']+resources['operation_store_bytes']),resources['object_bytes'])
    return store,config,start,resources


def work(root,path,limit):
    store,config,start,resources=context(root,path,limit);observer=Collector(store,path,resources)
    try:
        if config['stage']=='ORIGINAL':
            observer('SCIENTIFIC_ENTRY',{});source=decode(read_ref(config['source_manifest_ref']))
            observer('SOURCE_LOAD_ENTRY',{});data=load_input(source,start['input_binding'])
            graph=produce_stream(data,store,start['input_binding'],observer)
            require(observer.counts['account_persisted']==observer.counts['native_completed']==
                observer.counts['native_call_entries']==48,'PAIR_OPERATION_COMPLETE_ACTUAL_ENTRY_CENSUS')
            index={'schema':'polar.private-pair-stream-operation/1','candidate_id':config['candidate_id'],
                'experiment_id':config['experiment_id'],'code':config['code'],'runtime_image_id':config['runtime_image_id'],
                'input_binding':start['input_binding'],'graph':graph,'attempt_id':start['attempt_id'],'attempt_path':path}
            raw=canonical(encode(index));sid=SEMANTIC+sha(raw)
            with store.locked():store._publish('reference-research-experiments',sid,{'manifest.json':raw})
            result={'status':'SUCCESS','semantic_id':sid,'graph':graph,'financial_assessment':'NOT_ISSUED'}
        else:
            observer('SAVED_ENTRY',{});index=read_index(root,config['semantic_id'])
            verification=verify_stream(root,index['graph'],index['input_binding'])
            result={'status':'REPRODUCED','semantic_id':config['semantic_id'],'graph':index['graph'],
                'verification':verification,'financial_assessment':'NOT_ISSUED'}
    except BaseException as exc:
        result={'status':'FAILED_UNFINALIZED','error':str(exc)[:240],'exception_type':type(exc).__name__,
            'frontier':'UNKNOWN_AFTER_LAST_DURABLE_COUNTER_OR_PREFIX','collection_error':getattr(exc,'pair_collection_error',None),
            'automatic_retry':False,'refund':False}
    result.update(counters=dict(observer.counts),last_durable_sequence=observer.seq-1,latest_prefix=observer.latest,
        counter_bytes=observer.counter_bytes,partial_bytes=observer.partial_bytes,
        counter_scope='DURABLE_PREFIX_MINIMUM_ON_FAILURE_EXACT_ON_COMPLETE')
    with store.locked():store._publish(path,'work-result',{'record.json':canonical(encode(result))},file_limit=MAX_BYTES)
    return result


def collect(root,path,limit):
    store,config,start,resources=context(root,path,limit)
    process=json.loads(read_file(root,path+'/process-work/record.json',MAX_BYTES))
    require(process['cleanup']=='COMPLETE','PAIR_OPERATION_CHILD_CLEANUP_INCOMPLETE')
    directory=Path(root)/path/'counters';counts=dict(COUNTERS);latest=None;members=[];actual_events=0
    if directory.exists():
        for seq,p in enumerate(sorted(directory.iterdir())):
            record=restore(decode(read_file(root,str((p/'record.json').relative_to(root)),MAX_BYTES)))
            require(p.name==str(seq).zfill(8) and record['sequence']==seq,'PAIR_OPERATION_COUNTER_SEQUENCE')
            increments=record['increments']
            require(set(increments)==set(COUNTERS) and all(type(v) is int and v>=0 for v in increments.values()),
                'PAIR_OPERATION_COUNTER_INCREMENT_TYPES')
            for k in COUNTERS:
                if k not in ('fill_callbacks','event_checkpoints'):
                    require(increments[k]==int(KIND.get(record['kind'])==k),'PAIR_OPERATION_MANDATORY_ENTRY_CENSUS')
                counts[k]+=increments[k]
            require(record['counters']==counts,'PAIR_OPERATION_COUNTER_RECONCILIATION')
            latest=record['latest_prefix'];actual_events+=1
            if record['kind']=='ACCOUNT_PERSISTED':members.append(record['member'])
    result_path=Path(root)/path/'work-result/record.json'
    if process['failure'] is None and process['exit_code']==0 and result_path.exists():
        result=restore(decode(read_file(root,str(result_path.relative_to(root)),MAX_BYTES)))
        require(result['counters']==counts,'PAIR_OPERATION_WORK_RESULT_COUNTERS')
        if result['status']=='SUCCESS':
            require(config['stage']=='ORIGINAL' and len(members)==counts['account_persisted']==counts['native_completed']==48,
                'PAIR_OPERATION_SUCCESS_MEMBERS')
        elif result['status']=='REPRODUCED':
            require(config['stage']=='SAVED' and counts['saved_entries']==1 and counts['scientific_entries']==
                counts['source_load_entries']==counts['native_call_entries']==counts['feature_entries']==0,
                'PAIR_OPERATION_SAVED_ZERO_CALLS')
    else:result={'status':'FAILED_UNFINALIZED','error':process['failure'] or 'PAIR_OPERATION_CHILD_NO_RESULT',
        'counter_scope':'LAST_DURABLE_PREFIX_ONLY_TOTAL_FRONTIER_UNKNOWN','frontier':'UNKNOWN_AFTER_LAST_DURABLE_COUNTER_OR_PREFIX'}
    result.update(durable_counters=counts,actual_counter_records=actual_events,completed_member_refs=members,
        latest_prefix=latest,automatic_retry=False,refund=False)
    with store.locked():store._publish(path,'collected',{'record.json':canonical(encode(result))},file_limit=MAX_BYTES)
    return result


def main():
    root,path,mode,limit=sys.argv[1:];limit=int(limit)
    result=work(Path(root),path,limit) if mode=='work' else collect(Path(root),path,limit)
    print(json.dumps({'status':result['status'],'private':True}))

if __name__=='__main__':main()
