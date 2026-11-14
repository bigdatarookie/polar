"""PRIVATE exact consumed pair graph verification. No policy/native/source calls."""
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction as F
from pathlib import Path
import gzip,zlib
from .signed_event_saved import verify_packet,encode,restore,packet_bytes,publish_packet,verify_stored
from .signed_pair_input import NAMES,CONTROLS,CASES,MERGED,price
from .signed_pair_metrics import evaluate
from .signed_account_core import mark
from .signed_native_bridge import require
from .gym_contract import canonical,decode,sha,MAX_BYTES
from .history_bundle import read_file


def binding_for(data):
    return {'input_id':data.input_id,'protocol_sha256':data.protocol_sha256,'namespace':data.namespace,
        'nav_closes':data.nav_closes,'formations':tuple((f.id,f.g_index,f.decision_ns,f.execution_ns,
            f.endpoint21_index,f.endpoint252_index) for f in data.formations),
        'source_pins':data.source_pins,'source_rows':tuple((n,i,q.date,q.close_ns,q.modeled_available_ns,q.local_id,sha(canonical(encode(asdict(q)))))
            for n in NAMES for i,q in enumerate(q for q in data.quotes if q.name==n)),
        'input_content_sha256':sha(canonical(encode(asdict(data)))),'terminal_D':data.terminal_decision_ns,'terminal_Q':data.terminal_execution_ns}


def verify_account(account,binding,candidate_account=None):
    require(type(account) is dict and account['schema']=='polar.private-fixed-pair-account/1' and
        account['control'] in CONTROLS and account['case'] in CASES and account['input_id']==binding['input_id'] and
        account['protocol_sha256']==binding['protocol_sha256']==MERGED and account['execution_authority'] is False,
        'PAIR_SAVED_ACCOUNT_BINDING')
    ctx=account['context'];prefix='INVENTED/' if binding['namespace']=='INVENTED' else ''
    require(ctx.account==prefix+binding['input_id']+'/'+account['case']+'/'+account['control'] and
        ctx.path==account['case'] and ctx.source==binding['input_id'] and ctx.config==MERGED and ctx.names==NAMES,
        'PAIR_SAVED_EXTERNAL_CONTEXT')
    verify_packet(account['packet'],ctx)
    from .signed_pair_activation import verify_candidate,account_effect,scenario_factor
    if account['control']=='DYNAMIC_SPREAD':verify_candidate(account,binding)
    elif account['case'] not in CASES[:2]:
        require(candidate_account is not None and candidate_account['control']=='DYNAMIC_SPREAD' and
            candidate_account['case']==account['case'],'PAIR_STANDALONE_CONTROL_REQUIRES_CANDIDATE')
        verify_account(candidate_account,binding)
        require(account['activation']==candidate_account['activation'],'PAIR_CONTROL_ACTUAL_CANDIDATE_ACTIVATION_JOIN')
    require(account['intervention_effect']==account_effect(account['packet'],binding,account['activation']), 'PAIR_ACCOUNT_INTERVENTION_EFFECT_JOIN')
    external_rows={(r[0],r[1]):r for r in binding['source_rows']}
    records=account['packet']['records'];begins={r['event'].id:r['event'] for r in records if r['kind']=='BEGIN'}
    ends={r['event']:r for r in records if r['kind']=='END'}
    nav=account['NAV'];require(tuple(v['nominal_ns'] for v in nav)==binding['nav_closes'],'PAIR_SAVED_NAV_CENSUS')
    for row in nav:
        e=begins[row['event_id']];end=ends[e.id]
        require(e.kind=='CLOSE' and e.at_ns==row['nominal_ns'] and end['state']==row['state'] and
            row['report']==mark(end['state'],dict(e.marks)) and row['nav_cents']==row['report']['equity_cents'] and
            row['default_ever']==end['default_ever'] and row['overdue_ever']==end['overdue_ever'] and
            row['pending_flatten']==end['pending_flatten'],'PAIR_SAVED_ACTUAL_NAV_JOIN')
    require(tuple(d['formation']['id'] for d in account['D_receipts'])==tuple(f[0] for f in binding['formations']),
        'PAIR_SAVED_D_RECEIPT_CENSUS')
    for d,f in zip(account['D_receipts'],binding['formations']):
        require(tuple(d['formation'][k] for k in ('id','g_index','decision_ns','execution_ns','endpoint21_index','endpoint252_index'))==f,
            'PAIR_SAVED_FORMATION_ROLE')
        e=begins[d['actual_D_event']];end=ends[e.id]
        require(e.kind=='OBSERVATION' and e.at_ns==f[2] and e.mark_event==d['actual_D_mark'] and
            records[d['actual_D_END_sequence']]==end and end['state']==d['actual_D_state'] and
            d['own_D_report']==mark(end['state'],dict(e.marks)),'PAIR_SAVED_ACTUAL_D_BOOK')
        if d['status']!='SIZED':
            require(d['status']=='UNAVAILABLE_DEFAULT_OR_NONPOSITIVE_D_NAV' and
                    (end['default_ever'] or d['own_D_report']['equity_cents']<=0),'PAIR_SAVED_D_UNAVAILABLE')
            continue
        s=d['sizing'];tokens=d['consumed_tokens'];members=d['source_members']
        raw={n:price(tokens['raw_g'][n],raw=False) for n in NAMES}
        scores={n:price(tokens['signal21'][n],raw=False)/price(tokens['signal252'][n],raw=False)-1 for n in NAMES}
        require(dict(e.marks)==raw and s['raw_g_prices']==raw and s['scores']==scores and
            s['own_D_equity_cents']==d['own_D_report']['equity_cents']>0 and s['control']==account['control'] and
            s['Q_price_consumed'] is False,'PAIR_SAVED_CONSUMED_D_OPERANDS')
        for n in NAMES:
            selected=(f[1],f[4],f[5])
            require(len(members[n])==3 and tuple(v['local_id'] for v in members[n])==d['source_ids'][n], 'PAIR_SAVED_SOURCE_ENDPOINT_CENSUS')
            for m,index in zip(members[n],selected):
                expected=external_rows[n,index]
                require((m['name'],index,m['date'],m['close_ns'],m['modeled_available_ns'],m['local_id'])==expected[:6] and
                    sha(canonical(encode(m)))==expected[6], 'PAIR_EXPECTED_SOURCE_ENDPOINT_COMMITMENT')
                require(m['modeled_available_ns']<=f[2] and m['observed_known_ns'] is None,'PAIR_SOURCE_ENDPOINT_ELIGIBILITY')
            g,p21,p252=members[n]
            expected_raw=price(g['raw_usd_token'],raw=True)*scenario_factor(account['case'],n,g['close_ns'],account['activation'])
            expected21=price(p21['adjusted_signal_token'],raw=False)*scenario_factor(account['case'],n,p21['close_ns'],account['activation'])
            expected252=price(p252['adjusted_signal_token'],raw=False)*scenario_factor(account['case'],n,p252['close_ns'],account['activation'])
            require((raw[n],price(tokens['signal21'][n],raw=False),price(tokens['signal252'][n],raw=False))==
                    (expected_raw,expected21,expected252),'PAIR_ORIGINAL_CONSUMED_TOKEN_FACTOR_JOIN')
        # Check saved ranking/weight arithmetic without invoking policy/ranking
        # code or searching any source history. Claimed long must dominate both
        # declared exact endpoint scores, with fixed lexical tie handling.
        long=s['long'];short=s['short'];require({long,short}==set(NAMES),'PAIR_SAVED_NAMES')
        if account['control']!='STATIC_SPREAD':
            require(scores[long]>=scores[short] and (scores[long]!=scores[short] or long=='AAPL'),'PAIR_SAVED_RANK_OPERAND_RELATION')
        else:require((long,short)==NAMES,'PAIR_SAVED_STATIC_NAMES')
        expected={n:F() for n in NAMES}
        if account['control']!='RF0_CASH':expected[long]=F(1,2)
        if account['control'] in ('DYNAMIC_SPREAD','STATIC_SPREAD'):expected[short]=-F(1,2)
        require(s['weights']==expected and s['targets']=={n:(1 if expected[n]>0 else -1)*int(abs(expected[n])*s['own_D_equity_cents']/(100*raw[n])) if expected[n] else 0 for n in NAMES},
                'PAIR_SAVED_FLOOR_ARITHMETIC')
        routed=next((v for v in begins.values() if v.at_ns==f[3]),None)
        require(routed is not None and routed.decision_ns==f[2] and routed.formation==f[0] and
                dict(routed.targets)==s['targets'],'PAIR_SAVED_FROZEN_D_TO_Q_TARGETS')
    return {'status':'VERIFIED_PRIVATE_PAIR_ACCOUNT','activation_join_scope':'SELF_CANDIDATE' if account['control']=='DYNAMIC_SPREAD' else 'BASELINE_NOT_REQUIRED' if account['case'] in CASES[:2] else 'VERIFIED_SUPPLIED_CANDIDATE','source_reads':0,'native_calls':0,'rank_policy_calls':0,'writes':0}


def member_census(identities):
    require(type(identities) in (tuple,list) and all(type(v) is tuple and len(v)==2 for v in identities) and
        len(set(identities))==len(identities) and set(identities)=={(c,p) for p in CASES for c in CONTROLS},
        'PAIR_COMPLETE_48_MEMBER_CENSUS')
    return {'status':'DECLARED_48_MEMBERS','native_acceptance_inferred':False}


def verify_study(study,binding,*,complete=True):
    require(study['schema']=='polar.private-fixed-pair-study/1' and study['input_id']==binding['input_id'] and
        study['protocol_sha256']==binding['protocol_sha256'] and study['retained_dispatch_authority'] is False,'PAIR_STUDY_BINDING')
    require(study['actual_native_completed']==len(study['accounts']),'PAIR_COMPLETED_ACCOUNT_COUNTER')
    pairs=[(a['control'],a['case']) for a in study['accounts']]
    if complete:member_census(pairs)
    else:require(len(set(pairs))==len(pairs),'PAIR_DUPLICATE_ACCOUNT')
    from .signed_pair_activation import verify_candidate
    candidates={a['case']:a for a in study['accounts'] if a['control']=='DYNAMIC_SPREAD'}
    for case,candidate in candidates.items():
        require(study['activations'][case]==verify_candidate(candidate,binding),'PAIR_STUDY_ACTUAL_CANDIDATE_ACTIVATION')
    for a in study['accounts']:
        require(a['case'] in candidates,'PAIR_MISSING_ACTUAL_CANDIDATE_WITNESS')
        verify_account(a,binding,candidates[a['case']])
        require(a['activation']==study['activations'][a['case']],'PAIR_CROSS_CONTROL_ACTIVATION_JOIN')
    result=evaluate(study['accounts'])
    if 'evaluation' in study:require(encode(study['evaluation'])==encode(result),'PAIR_SAVED_EVALUATION_MISMATCH')
    return result


def publish_account(store,account,binding,candidate_account=None):
    verify_account(account,binding,candidate_account)
    candidate_ref=(publish_account(store,candidate_account,binding) if account['control']!='DYNAMIC_SPREAD' and account['case'] not in CASES[:2] else None)
    ref=publish_tape(store,account['packet'])
    sidecar={k:v for k,v in account.items() if k not in ('packet','NAV')}
    payload=canonical(encode({'binding':binding,'account':sidecar,'packet':ref,'candidate_ref':candidate_ref}))
    require(len(payload)<=MAX_BYTES,'PAIR_ACCOUNT_SIDECAR_SIZE')
    files,refs=chunk_rows(account['NAV'],'nav');files['account.json']=payload
    manifest=canonical({'schema':'polar.private-pair-account-manifest/1','sha256':sha(payload),'bytes':len(payload),
        'NAV':refs,'NAV_count':len(account['NAV'])})
    require(len(manifest)<=MAX_BYTES,'PAIR_ACCOUNT_MANIFEST_SIZE')
    name='pair-account-'+sha(manifest);files['manifest.json']=manifest
    with store.locked():store._publish('pair-account-components',name,files,file_limit=MAX_BYTES)
    return {'id':name,'manifest_sha256':sha(manifest),'account_sha256':sha(payload),'bytes':len(payload),
        'aggregate_bytes':sum(len(v) for v in files.values()),'NAV_chunks':len(refs)}


def verify_stored_account(root,ref,binding,*,_candidate_depth=0):
    require(_candidate_depth<=1,'PAIR_CANDIDATE_REFERENCE_DEPTH')
    parent='pair-account-components/'+ref['id'];manifest=read_file(root,parent+'/manifest.json',MAX_BYTES)
    require(ref['id']=='pair-account-'+sha(manifest)== 'pair-account-'+ref['manifest_sha256'],'PAIR_ACCOUNT_MANIFEST_PIN')
    obj=decode(manifest);payload=read_file(root,parent+'/account.json',MAX_BYTES)
    require(obj['schema']=='polar.private-pair-account-manifest/1' and obj['sha256']==sha(payload)==ref['account_sha256'] and
            obj['bytes']==len(payload)==ref['bytes'] and len(obj['NAV'])==ref['NAV_chunks'],'PAIR_ACCOUNT_PAYLOAD_PIN')
    exact_members(root,parent,[v['name'] for v in obj['NAV']]+['manifest.json','account.json'])
    d=restore(decode(payload));require(d['binding']==binding,'PAIR_ACCOUNT_EXPECTED_BINDING')
    nav,total=read_chunk_rows(root,parent,obj['NAV'],'nav')
    require(len(nav)==obj['NAV_count'] and total+len(payload)+len(manifest)==ref['aggregate_bytes'],'PAIR_NAV_FULL_CENSUS')
    packet=verify_tape(root,d['packet'],d['account']['context'])
    account={**d['account'],'packet':packet,'NAV':nav}
    candidate=None
    if d['candidate_ref'] is not None:
        require(_candidate_depth==0,'PAIR_CANDIDATE_MUST_NOT_REFERENCE_CANDIDATE')
        candidate=verify_stored_account(root,d['candidate_ref'],binding,_candidate_depth=1)
    verify_account(account,binding,candidate)
    return account


def publish_study(store,study,binding):
    evaluation=verify_study(study,binding);refs=[]
    candidates={a['case']:a for a in study['accounts'] if a['control']=='DYNAMIC_SPREAD'}
    for a in study['accounts']:refs.append(publish_account(store,a,binding,candidates.get(a['case'])))
    payload=canonical(encode({'schema':'polar.private-fixed-pair-graph/1','binding':binding,
        'members':refs,'activations':study['activations'],'evaluation':evaluation}))
    require(len(payload)<=MAX_BYTES,'PAIR_STUDY_GRAPH_SIZE')
    manifest=canonical({'schema':'polar.private-fixed-pair-graph-manifest/1','sha256':sha(payload),'bytes':len(payload)})
    name='pair-study-'+sha(manifest)
    with store.locked():store._publish('pair-study-components',name,{'manifest.json':manifest,'graph.json':payload},file_limit=MAX_BYTES)
    return {'id':name,'manifest_sha256':sha(manifest),'graph_sha256':sha(payload),'bytes':len(payload)}


def verify_stored_study(root,ref,binding):
    parent='pair-study-components/'+ref['id'];m=read_file(root,parent+'/manifest.json',65536)
    raw=read_file(root,parent+'/graph.json',MAX_BYTES);manifest=decode(m)
    require(ref['id']=='pair-study-'+sha(m) and sha(m)==ref['manifest_sha256'] and
            sha(raw)==manifest['sha256']==ref['graph_sha256'] and len(raw)==manifest['bytes']==ref['bytes'],'PAIR_STUDY_MANIFEST_PIN')
    graph=restore(decode(raw));require(graph['binding']==binding,'PAIR_STUDY_EXPECTED_BINDING')
    accounts=[verify_stored_account(root,v,binding) for v in graph['members']]
    study={'schema':'polar.private-fixed-pair-study/1','input_id':binding['input_id'],'protocol_sha256':binding['protocol_sha256'],
        'accounts':accounts,'actual_native_completed':len(accounts),'activations':graph['activations'],'evaluation':graph['evaluation'],'retained_dispatch_authority':False}
    return {'status':'VERIFIED_PRIVATE_FIXED_PAIR_STUDY','study':study,'evaluation':verify_study(study,binding),
            'native_calls':0,'source_reads':0,'writes':0,'financial_assessment':'NOT_ISSUED'}



def chunk_rows(rows,prefix):
    files={};refs=[];pending=[];size=2;first=0
    def flush():
        nonlocal pending,size,first
        if not pending:return
        name=prefix+'-'+str(len(refs)).zfill(5)+'.json.gz';raw=b'['+b','.join(pending)+b']'
        compressed=gzip.compress(raw,compresslevel=6,mtime=0)
        require(len(compressed)<=MAX_BYTES//4,'PAIR_COMPRESSED_CHUNK_SIZE')
        files[name]=compressed;refs.append({'name':name,'sha256':sha(compressed),'bytes':len(compressed),
            'unpacked_sha256':sha(raw),'unpacked_bytes':len(raw),'first':first,'count':len(pending)})
        first+=len(pending);pending=[];size=2
    for row in rows:
        raw=canonical(encode(row));require(len(raw)+2<=MAX_BYTES//4,'PAIR_RECORD_EXCEEDS_CHUNK')
        if size+len(raw)+1>MAX_BYTES//4:flush()
        pending.append(raw);size+=len(raw)+1
    flush();return files,refs


def read_chunk_rows(root,parent,refs,prefix):
    result=[];aggregate=0;strings={}
    def intern_values(value):
        if type(value) is str:return strings.setdefault(value,value)
        if type(value) is list:return [intern_values(v) for v in value]
        if type(value) is dict:return {strings.setdefault(k,k):intern_values(v) for k,v in value.items()}
        return value
    for index,c in enumerate(refs):
        require(c['name']==prefix+'-'+str(index).zfill(5)+'.json.gz' and c['first']==len(result),'PAIR_CHUNK_ORDER')
        raw=read_file(root,parent+'/'+c['name'],MAX_BYTES//4)
        require(sha(raw)==c['sha256'] and len(raw)==c['bytes'],'PAIR_CHUNK_PIN')
        require(type(c['unpacked_bytes']) is int and 0<c['unpacked_bytes']<=MAX_BYTES//4,'PAIR_UNPACKED_BOUND')
        decompressor=zlib.decompressobj(31);unpacked=decompressor.decompress(raw,MAX_BYTES//4+1)
        require(decompressor.eof and not decompressor.unused_data and not decompressor.unconsumed_tail and
            len(unpacked)==c['unpacked_bytes'] and sha(unpacked)==c['unpacked_sha256'],'PAIR_UNPACKED_PIN')
        rows=restore(intern_values(decode(unpacked)));require(type(rows) is list and len(rows)==c['count'],'PAIR_CHUNK_COUNT')
        result.extend(rows);aggregate+=len(raw)
    return result,aggregate


def exact_members(root,parent,names):
    directory=Path(root)/parent
    require({p.name for p in directory.iterdir()}==set(names) and not any(p.is_symlink() for p in directory.iterdir()),'PAIR_EXACT_MEMBERS')


def publish_tape(store,packet):
    """Lossless ordered chunks in the existing store, unchanged per-file cap."""
    verify_packet(packet,packet['context'])
    header=canonical(encode({k:v for k,v in packet.items() if k!='records'}))
    require(len(header)<=MAX_BYTES,'PAIR_TAPE_HEADER_SIZE')
    files,refs=chunk_rows(packet['records'],'records');files['header.json']=header
    manifest=canonical({'schema':'polar.private-pair-tape-manifest/1',
        'context':encode(packet['context']),'header':{'name':'header.json','sha256':sha(header),'bytes':len(header)},
        'record_count':len(packet['records']),'chunks':refs})
    require(len(manifest)<=MAX_BYTES,'PAIR_TAPE_MANIFEST_SIZE')
    name='pair-tape-'+sha(manifest);files['manifest.json']=manifest
    with store.locked():store._publish('pair-tape-components',name,files,file_limit=MAX_BYTES)
    return {'id':name,'manifest_sha256':sha(manifest),'chunks':len(refs),
        'aggregate_bytes':sum(len(v) for v in files.values()),'records':len(packet['records'])}


def verify_tape(root,ref,context):
    parent='pair-tape-components/'+ref['id'];raw=read_file(root,parent+'/manifest.json',MAX_BYTES);m=decode(raw)
    require(ref['id']=='pair-tape-'+sha(raw) and ref['manifest_sha256']==sha(raw) and canonical(m)==raw and
        m['schema']=='polar.private-pair-tape-manifest/1' and restore(m['context'])==context and
        len(m['chunks'])==ref['chunks'],'PAIR_TAPE_MANIFEST_PIN')
    exact_members(root,parent,[v['name'] for v in m['chunks']]+['header.json','manifest.json'])
    h=m['header'];header=read_file(root,parent+'/'+h['name'],MAX_BYTES)
    require(h['name']=='header.json' and sha(header)==h['sha256'] and len(header)==h['bytes'],'PAIR_TAPE_HEADER_PIN')
    packet=restore(decode(header));records,total=read_chunk_rows(root,parent,m['chunks'],'records')
    require(len(records)==m['record_count']==ref['records'] and total+len(raw)+len(header)==ref['aggregate_bytes'],'PAIR_TAPE_FULL_CENSUS')
    packet['records']=records;verify_packet(packet,context);return packet
