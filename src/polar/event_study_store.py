"""Private graph references existing immutable native witnesses, never duplicates tapes."""
from dataclasses import asdict
from pathlib import Path
import re

from .event_study import (StudyBinding,binding_from_plain,evaluate_study,plain,LEGS,COSTS)
from .event_native_witness import (publish_witnesses,verify_stored_witnesses,encode,restore)
from .gym_contract import canonical,decode,sha,MAX_BYTES
from .history_bundle import read_file
from .ci_research import require


def _check_study(study,expected_binding):
    require(type(study) is dict and set(study)=={'schema','binding','calendar','roles','accounts','evaluation','execution_authority'}
            and study['schema']=='polar.private-calendar-study/1' and type(expected_binding) is StudyBinding and
            study['binding']==expected_binding and study['execution_authority'] is False,'STUDY_GRAPH_BINDING')
    require(len(study['accounts'])==len(LEGS)*len(COSTS),'STUDY_COMPLETE_TEN_ACCOUNT_GRAPH')
    evaluation=evaluate_study(study['accounts'],study['calendar'],study['roles'],expected_binding)
    require(canonical(encode(evaluation))==canonical(encode(study['evaluation'])),'STUDY_SAVED_EVALUATION_MISMATCH')
    return evaluation


def publish_study(store,study):
    """Existing store only, PRIVATE graph publication, no begin/budget/registry.

    Existing witness objects may survive a later graph publication error. They
    are immutable useful account evidence, never successful scientific finish.
    """
    evaluation=_check_study(study,study['binding']);refs=[]
    for a in study['accounts']:refs.append(publish_witnesses(store,a))
    graph={'schema':'polar.private-calendar-study-index/1','binding':plain(asdict(study['binding'])),
           'calendar':study['calendar'],'roles':study['roles'],'accounts':encode(refs),
           'evaluation':encode(evaluation),'execution_authority':False}
    raw=canonical(graph);require(len(raw)<=MAX_BYTES,'STUDY_GRAPH_SIZE')
    manifest={'schema':'polar.private-calendar-study-manifest/1','binding':graph['binding'],
              'file':{'name':'graph.json','sha256':sha(raw),'bytes':len(raw)}}
    m=canonical(manifest);name='calendar-study-'+sha(m)
    with store.locked():store._publish('calendar-study-components',name,{'manifest.json':m,'graph.json':raw},file_limit=MAX_BYTES)
    return {'id':name,'manifest_sha256':sha(m),'graph_sha256':sha(raw),'bytes':len(raw),
            'account_witness_ids':[v['id'] for v in refs],'execution_authority':False}


def verify_stored_study(root,name,expected_binding):
    require(type(name) is str and re.fullmatch(r'calendar-study-[a-f0-9]{64}',name),'STUDY_GRAPH_ID')
    parent='calendar-study-components/'+name;m=read_file(root,parent+'/manifest.json',65536);manifest=decode(m)
    require(canonical(manifest)==m and name=='calendar-study-'+sha(m) and
            set(manifest)=={'schema','binding','file'} and manifest['schema']=='polar.private-calendar-study-manifest/1' and
            binding_from_plain(manifest['binding'])==expected_binding,'STUDY_GRAPH_MANIFEST_BINDING')
    directory=Path(root)/parent
    require({p.name for p in directory.iterdir()}=={'manifest.json','graph.json'} and
            not any(p.is_symlink() for p in directory.iterdir()),'STUDY_GRAPH_MEMBER_SET')
    ref=manifest['file'];require(set(ref)=={'name','sha256','bytes'} and ref['name']=='graph.json','STUDY_GRAPH_FILE')
    raw=read_file(root,parent+'/graph.json',MAX_BYTES)
    require(sha(raw)==ref['sha256'] and len(raw)==ref['bytes'],'STUDY_GRAPH_FILE_HASH')
    graph=decode(raw)
    require(canonical(graph)==raw and set(graph)=={'schema','binding','calendar','roles','accounts','evaluation','execution_authority'}
            and graph['schema']=='polar.private-calendar-study-index/1' and graph['execution_authority'] is False and
            binding_from_plain(graph['binding'])==expected_binding,'STUDY_GRAPH_INDEX')
    refs=restore(graph['accounts']);require(type(refs) is list and len(refs)==10,'STUDY_COMPLETE_TEN_ACCOUNT_GRAPH')
    accounts=[]
    for ref in refs:
        require(set(ref)=={'id','manifest_sha256','context','payload_sha256','bytes'} and
                ref['id']=='event-witness-'+ref['manifest_sha256'],'STUDY_ACCOUNT_WITNESS_REFERENCE')
        result=verify_stored_witnesses(root,ref['id'],ref['context'])
        require(result['immutable_payload_sha256']==ref['payload_sha256'] and type(ref['bytes']) is int and
                len(canonical({'schema':'polar.event-native-component-witnesses/1','account':encode(result['account'])}))==ref['bytes'],
                'STUDY_ACCOUNT_PAYLOAD_HASH')
        accounts.append(result['account'])
    study={'schema':'polar.private-calendar-study/1','binding':expected_binding,'calendar':graph['calendar'],
           'roles':graph['roles'],'accounts':accounts,'evaluation':restore(graph['evaluation']),'execution_authority':False}
    evaluation=_check_study(study,expected_binding)
    return {'status':'VERIFIED_PRIVATE_SAVED_CALENDAR_STUDY','study':study,'evaluation':evaluation,
            'id':name,'account_count':len(accounts),'saved_member_reads':2+2*len(accounts),
            'source_reads':0,'native_calls':0,'feature_calls':0,'Service_calls':0,'writes':0,
            'financial_assessment':'NOT_ISSUED','execution_authority':False}
