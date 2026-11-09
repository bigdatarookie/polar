"""Closed first-unit raw GET adapter for ImportService; no provider access on import."""
from datetime import datetime
from pathlib import Path
import json
import os
import re
import uuid

from .import_contract import (require, exact, canonical, decode, sha, digest, hash_value,
                              timestamp, seconds, ImportError)

ADAPTER='alpaca-raw-sip-first-unit/1'
UNIT_SHA='aded6413f66d7b2f2857de50df99cd75b6911325de34793bee9450dba58636ef'
REUSE_SHA='1d6c7fcb7362cac1186bab53583c28c1e23339dcedf1ac6bfcc64af606964b3a'
ENDPOINT='https://data.alpaca.markets/v2/stocks/bars'
POLICY={'schema':'polar.raw-sip-policy/1','basis':'INTERNAL_FIRST_UNIT',
        'jobs':20,'gets':40,'pages':2,'body_bytes':1048576,'total_bytes':41943040,
        'wall_seconds':900,'spacing_seconds':1,'request_seconds':45,'retries':0,'redirects':False}


def request(value):
    exact(value,('endpoint','symbols','adjustment','feed','currency','timeframe','asof',
                 'limit','sort','start','end'))
    require(value['endpoint']==ENDPOINT and value['adjustment']=='raw' and value['feed']=='sip'
            and value['currency']=='USD' and value['timeframe']=='1Day' and value['sort']=='asc'
            and value['asof']=='2020-09-02' and type(value['limit']) is int and value['limit']==10000,
            'IMPORT_REQUEST_SEMANTICS')
    require(type(value['symbols']) is str and re.fullmatch(r'[A-Za-z0-9._-]{1,40}',value['symbols']),
            'IMPORT_REQUEST_SEMANTICS')
    require(seconds(value['start'])<seconds(value['end']),'IMPORT_REQUEST_SEMANTICS')
    return value


def job_id(value):
    return digest({'adapter':ADAPTER,'request':request(value)})


def page(raw, *, limit=None):
    """All numeric JSON tokens remain source lexemes, including integers and extras."""
    require(len(raw)<=(POLICY['body_bytes'] if limit is None else limit),'IMPORT_RESPONSE_LIMIT')
    def pairs(items):
        out={}
        for k,v in items:
            require(k not in out,'IMPORT_DUPLICATE_FIELD');out[k]=v
        return out
    try:
        value=json.loads(raw,parse_int=str,parse_float=str,object_pairs_hook=pairs,
                         parse_constant=lambda _:require(False,'IMPORT_NONFINITE'))
    except (ValueError,UnicodeError,RecursionError):raise ImportError('IMPORT_INVALID_JSON') from None
    require(type(value) is dict and type(value.get('bars')) is dict,'IMPORT_RAW_PAGE_SCHEMA')
    for symbol,rows in value['bars'].items():
        require(type(symbol) is str and symbol and type(rows) is list,'IMPORT_RAW_PAGE_SCHEMA')
        for row in rows:
            require(type(row) is dict,'IMPORT_RAW_PAGE_SCHEMA')
    cursor=value.get('next_page_token')
    require(cursor is None or type(cursor) is str and 0<len(cursor)<=4096
            and all(ord(c)>=32 for c in cursor),'IMPORT_RAW_CURSOR')
    return value


def records(service):
    if getattr(service.store,'_raw_execution_rows',None) is not None:return service.store._raw_execution_rows
    rows=[]
    for name in service.store.list('requests'):
        start=service.store.read(name)
        require(start['schema']=='polar.raw-sip-request-start/1'
                and Path(name).stem==start['request_id'] and start['job_id']==job_id(start['request'])
                and start['page'] in (0,1),'IMPORT_REQUEST_INTEGRITY')
        require(start['request_cursor'] is None if start['page']==0 else
                type(start['request_cursor']) is str and 0<len(start['request_cursor'])<=4096,
                'IMPORT_REQUEST_INTEGRITY')
        other='responses/'+start['request_id']+'.json'
        response=service.store.read(other) if service.store.exists(other) else None
        if response:
            require(response['request_start_sha256']==digest(start),'IMPORT_RESPONSE_IDENTITY')
            service.store.object_read(response['body'])
        rows.append((start,response))
    ordered=sorted(rows,key=lambda r:(r[0]['sequence'],r[0]['request_id']))
    require([s['sequence'] for s,_ in ordered]==list(range(len(ordered))),
            'IMPORT_REQUEST_INTEGRITY')
    return ordered


def commits(store):
    if getattr(store,'_raw_execution_commits',None) is not None:return store._raw_execution_commits
    result={}
    for name in store.list('successes')+store.list('cache-imports'):
        row=store.read(name)
        require(row['schema']=='polar.raw-sip-cache-commit/1' and Path(name).stem==digest(row),
                'IMPORT_CACHE_SCHEMA')
        jid=job_id(row['request'])
        require(row['job_id']==jid and row['kind'] in ('RAW_COMPLETE','RAW_NO_ROWS'),
                'IMPORT_CACHE_INTEGRITY')
        previous=None;count=0
        require(0<len(row['pages'])<=2,'IMPORT_CACHE_INTEGRITY')
        for i,entry in enumerate(row['pages']):
            require(entry['page']==i and entry['request_cursor']==previous,'IMPORT_CACHE_INTEGRITY')
            body=page(store.object_read(entry['body']))
            require(not (set(body['bars'])-{row['request']['symbols']}),'IMPORT_CACHE_INTEGRITY')
            previous=body.get('next_page_token')
            count+=sum(len(v) for v in body['bars'].values())
        require(previous is None and row['kind']==('RAW_COMPLETE' if count else 'RAW_NO_ROWS'),
                'IMPORT_CACHE_INTEGRITY')
        wrapped={**row,'response':{'pages':row['pages']},'response_sha256':digest(row['pages']),
                 'sources':row['sources']}
        result.setdefault(jid,[]).append(wrapped)
    return result


def save_commit(store,commit):
    store.write('successes/'+digest(commit)+'.json',commit)
    cache=getattr(store,'_raw_execution_commits',None)
    if cache is not None:
        wrapped={**commit,'response':{'pages':commit['pages']},
                 'response_sha256':digest(commit['pages']),'sources':commit['sources']}
        versions=cache.setdefault(commit['job_id'],[])
        if not any(digest(v['pages'])==digest(commit['pages']) for v in versions):versions.append(wrapped)


def status(service,pid):
    plan=service.load(pid);saved=commits(service.store);rows=records(service)
    states={j['job_id']:{'state':'pending','kind':None,'reason':None,'retry_eligible':False,
                          'pages':[]} for j in plan['jobs']}
    for start,response in rows:
        if start['job_id'] not in states:continue
        state=states[start['job_id']]
        name='outcomes/'+start['request_id']+'.json'
        outcome=service.store.read(name) if service.store.exists(name) else None
        if outcome:
            require(outcome['request_start_sha256']==digest(start),'IMPORT_OUTCOME_IDENTITY')
        state.update(state='permanent_error',reason='UNKNOWN_IN_FLIGHT')
        if outcome:state.update(state=outcome['state'],reason=outcome['reason'])
        state['pages'].append({'start':start,'response':response,'outcome':outcome})
    for jid,versions in saved.items():
        if jid not in states:continue
        unique={v['response_sha256'] for v in versions}
        states[jid].update(state='success' if len(unique)==1 else 'permanent_error',
                           kind=versions[0]['kind'] if len(unique)==1 else 'CONFLICTING_RESPONSE_VERSIONS',
                           reason=None if len(unique)==1 else 'CONFLICTING_RESPONSE_VERSIONS')
    counts={k:sum(v['state']==k for v in states.values())
            for k in ('pending','success','partial','permanent_error')}
    counts['no_rows']=sum(v['kind']=='RAW_NO_ROWS' for v in states.values())
    return {'schema':'polar.raw-sip-status/1','plan_id':pid,'states':states,'counts':counts,
            'scope_physical_gets':len(rows),'scientific_fitness':'NOT_ASSESSED'}


def plan(service,value):
    from .import_service import bound_file,code_projection
    from .import_raw_profile import aggregate_unit,AGGREGATE_POLICY,AGGREGATE_ADAPTER
    aggregate=service.store.raw_profile=='remaining3490'
    require(value.get('mode') in ('fixture','provider'),'IMPORT_POLICY_MISMATCH')
    fixture=value['mode']=='fixture'
    expected_fixture_prefix='imports-rawsip-aggregate-fixture-v1/' if aggregate else 'imports-rawsip-fixture-v1/'
    require(fixture==service.store.base.startswith(expected_fixture_prefix),'IMPORT_MODE_MISMATCH')
    if aggregate:
        unit=aggregate_unit(value,fixture);policy=AGGREGATE_POLICY
    else:
        exact(value,('schema','adapter','mode','unit_ref','reuse_ref','seed_refs'))
        require(value['schema']=='polar.raw-sip-import-config/1' and value['adapter']==ADAPTER,
                'IMPORT_POLICY_MISMATCH')
        raw=bound_file(value['unit_ref']);unit=decode(raw);reuse=bound_file(value['reuse_ref'])
        if not fixture:require(sha(raw)==UNIT_SHA and sha(reuse)==REUSE_SHA,'IMPORT_SCOPE_MISMATCH')
        require(type(unit.get('jobs')) is list and 0<len(unit['jobs'])<=20,'IMPORT_SCOPE_MISMATCH')
        policy=POLICY
    jobs=[{'job_id':job_id(j['request']),'request':j['request'],'relation':j} for j in unit['jobs']]
    require(len({j['job_id'] for j in jobs})==len(jobs),'IMPORT_DUPLICATE_JOB')
    data={'schema':'polar.import-plan/1','config':value,'scope':service.store.base,'jobs':jobs,
          'source_projection':code_projection(),'unit':unit,'policy':policy}
    prefix=('rawsipaggregatefixture-' if fixture else 'rawsipaggregate-') if aggregate else (
            'rawsipfixture-' if fixture else 'rawsip-')
    pid=prefix+digest(data);data['plan_id']=pid
    require(type(value['seed_refs']) is list and len(value['seed_refs'])<=policy['jobs']*2,'IMPORT_CACHE_SCHEMA')
    with service.store.locked():
        service.store.admit_storage()
        service.store.write('policy.json',policy)
        service.store.write('plans/'+pid+'.json',data)
        # Explicit legacy migration: exact request, complete cursor chain, bound raw bodies.
        for ref in value['seed_refs']:
            seed=decode(bound_file(ref))
            exact(seed,('schema','request','pages','completeness','provenance'))
            require(seed['schema']=='polar.raw-sip-seed/1' and seed['completeness']=='COMPLETE'
                    and seed['provenance'] and type(seed['pages']) is list
                    and 0<len(seed['pages'])<=2,'IMPORT_CACHE_SCHEMA')
            jid=job_id(seed['request']);require(jid in {j['job_id'] for j in jobs},'IMPORT_JOB_NOT_IN_PLAN')
            entries=[];cursor=None;count=0
            for i,entry in enumerate(seed['pages']):
                exact(entry,('body_ref','request_cursor'))
                require(entry['request_cursor']==cursor,'IMPORT_CACHE_INTEGRITY')
                body=bound_file(entry['body_ref']);parsed=page(body)
                require(not (set(parsed['bars'])-{seed['request']['symbols']}),'IMPORT_CACHE_INTEGRITY')
                entries.append({'page':i,'request_cursor':cursor,'body':service.store.object(body)})
                cursor=parsed.get('next_page_token');count+=sum(len(r) for r in parsed['bars'].values())
            require(cursor is None,'IMPORT_CACHE_INTEGRITY')
            commit={'schema':'polar.raw-sip-cache-commit/1','job_id':jid,'request':seed['request'],
                    'kind':'RAW_COMPLETE' if count else 'RAW_NO_ROWS','pages':entries,
                    'sources':[{'seed_ref':ref,'provenance':seed['provenance']}]}
            service.store.write('cache-imports/'+digest(commit)+'.json',commit)
        commits(service.store)
    return {'schema':'polar.import-plan-result/1','plan_id':pid,'planned':len(jobs),
            'counts':status(service,pid)['counts'],'mode':value['mode'],'provider_requests':0}


def disposition(service,start,response):
    name='outcomes/'+start['request_id']+'.json'
    if service.store.exists(name):return service.store.read(name)
    reason=response['error'];state='permanent_error';cursor=None
    if response['status'] in (401,403):
        reason='AUTH_OR_RIGHTS_REFUSAL';service.store.write('auth-pause.json',{'reason':reason})
    elif response['truncated']:reason='RESPONSE_BODY_LIMIT'
    elif not reason and response['status']!=200:reason='HTTP_FAILURE_NO_RETRY'
    elif not reason:
        try:
            require(response['headers'].get('content-type','').split(';',1)[0].strip().lower()
                    =='application/json','IMPORT_CONTENT_TYPE')
            body=page(service.store.object_read(response['body']));cursor=body.get('next_page_token')
            preceding=[(s,r) for s,r in records(service) if s['job_id']==start['job_id']
                       and s['sequence']<start['sequence']]
            require(len(preceding)==start['page'],'IMPORT_PAGE_SEQUENCE')
            if preceding:
                prior_start,prior_response=preceding[-1]
                require(prior_response is not None and
                        page(service.store.object_read(prior_response['body'])).get('next_page_token')
                        ==start['request_cursor'],'IMPORT_PAGE_SEQUENCE')
            cursors={s['request_cursor'] for s,_ in preceding}|{start['request_cursor']}
            unexpected=set(body['bars'])-{start['request']['symbols']}
            if unexpected:reason='UNEXPECTED_RETURNED_SYMBOL'
            elif cursor is not None and cursor in cursors:reason='REPEATED_CURSOR'
            elif cursor is not None and start['page']==1:reason='PAGE_LIMIT_PARTIAL'
            else:reason=None
            state='permanent_error' if unexpected else 'partial' if cursor is not None else 'success'
            if cursor is None and not unexpected:
                entries=[{'page':s['page'],'request_cursor':s['request_cursor'],'body':r['body']}
                         for s,r in preceding if r]
                entries.append({'page':start['page'],'request_cursor':start['request_cursor'],'body':response['body']})
                count=sum(sum(len(rows) for rows in page(service.store.object_read(e['body']))['bars'].values())
                          for e in entries)
                commit={'schema':'polar.raw-sip-cache-commit/1','job_id':start['job_id'],
                        'request':start['request'],'kind':'RAW_COMPLETE' if count else 'RAW_NO_ROWS',
                        'pages':entries,'sources':[{'request_id':start['request_id'],
                                                   'request_start_sha256':digest(start)}]}
                save_commit(service.store,commit)
        except ImportError as exc:reason=exc.code;state='permanent_error'
    outcome={'schema':'polar.raw-sip-outcome/1','request_start_sha256':digest(start),
             'state':state,'reason':reason,'next_cursor':cursor}
    service.store.write(name,outcome)
    return outcome


def normalized(service,plan,prefix):
    """Lossless source envelope, not prices/features or a fitness verdict."""
    bars=[];parents=[];coverage=[]
    rows=records(service)
    states=status(service,plan['plan_id'])['states']
    for job in plan['jobs']:
        related=[(s,r) for s,r in rows if s['job_id']==job['job_id'] and r]
        # Imported completed bodies have the same typed page interface.
        if not related:
            versions=commits(service.store).get(job['job_id'],[])
            if len(versions)==1:
                related=[({'request':job['request'],'job_id':job['job_id'],
                           'page':e['page'],'request_id':None},
                          {'body':e['body']}) for e in versions[0]['pages']]
        for start,response in related:
            try:body=page(service.store.object_read(response['body']))
            except ImportError:continue
            for symbol,values in body['bars'].items():
                for ordinal,original in enumerate(values):
                    label=original.get('t');date=label[:10] if type(label) is str else None
                    in_window=(type(date) is str and job['request']['start'][:10]<=date<job['request']['end'][:10])
                    row={'source_symbol':symbol,'query_symbol':job['request']['symbols'],
                         'reference_date':date,'aggregation_label':label,
                         'raw_fields_exact_tokens':original,'capture_origin':'RAW_SIP_IMPORT_ADAPTER_V1',
                         'adjustment':'raw','feed':'sip','currency':'USD_REQUEST_CONTRACT',
                         'asof':job['request']['asof'],'volume_basis':'RAW_SHARES',
                         'economic_security_id':None,'event_open_at':None,'event_close_at':None,
                         'observed_published_at':None,'observed_historical_available_at':None,
                         'estimated_K':None,'K_label':'UNKNOWN_NO_CAUSAL_USE',
                         'parent_relation':job['relation'],'quality_reasons':[],
                         'supplemental_reasons':['SOURCE_FITNESS_UNRESOLVED'],
                         'window_classification':'IN_REQUEST_WINDOW' if in_window else 'OUTSIDE_OR_UNKNOWN_WINDOW',
                         'source_reference':{'raw_file':response['body']['path'],
                             'source_body_sha256':response['body']['sha256'],
                             'source_array':'bars/'+symbol,'source_row_ordinal':ordinal,
                             'job_id':job['job_id'],'request_id':start['request_id'],'page':start['page']}}
                    for field,key in (('raw_open','o'),('raw_high','h'),('raw_low','l'),
                                      ('raw_close','c'),('raw_volume','v')):
                        row[field]=original.get(key)
                    bars.append(row)
        state=states[job['job_id']]
        raw_state=('RECEIVED_EMPTY' if state['kind']=='RAW_NO_ROWS' else 'RECEIVED_COMPLETE'
                   if state['state']=='success' else 'RECEIVED_PARTIAL' if state['state']=='partial'
                   else 'UNRECEIVED_OUTCOME_UNKNOWN' if state['reason']=='UNKNOWN_IN_FLIGHT'
                   else 'REQUEST_FAILED' if state['state']=='permanent_error' else 'UNRECEIVED')
        parents.append({**job['relation'],'this_batch':state['state'],'this_batch_reason':state['reason'],
                        'raw_data_state':raw_state,'raw_coverage_ref':job['job_id']})
        coverage.append({'job_id':job['job_id'],'source_symbol':job['request']['symbols'],
                         'expected_reference_positions':job['relation'].get('expected_reference_labels'),
                         'transport_state':raw_state,'reason':state['reason'],
                         'calendar_validated_positions':None,'coverage_fraction':None,
                         'economic_eligible_N_contribution':None})
    members={}
    def emit(name,raw):
        path=prefix+'/source/'+name;service.store.write_raw(path,raw)
        members[name]={'bytes':len(raw),'sha256':sha(raw)}
    emit('bars.ndjson',b''.join(canonical(r)+b'\n' for r in bars))
    emit('parent-coverage-ledger.ndjson',b''.join(canonical(r)+b'\n' for r in parents))
    emit('coverage.json',canonical(coverage)+b'\n')
    emit('source-plan.json',canonical({'schema':'polar.raw-sip-source-plan/1',
         'selected_symbols':[j['request']['symbols'] for j in plan['jobs']],
         'unit':plan['unit'],'policy':POLICY,'fitness':'NOT_ASSESSED'})+b'\n')
    # Raw bodies are copied with exact bytes under their referenced relative names.
    for _,response in rows:
        if response:
            ref=response['body'];raw=service.store.object_read(ref)
            try:page(raw)
            except ImportError:continue  # malformed body remains in the terminal capture graph.
            emit(ref['path'],raw)
    for versions in commits(service.store).values():
        for version in versions:
            for entry in version['pages']:
                ref=entry['body'];emit(ref['path'],service.store.object_read(ref))
    manifest={'schema':'polar.partial-raw-pv-source-content/1','objects':members,
              'recipe_sha256':digest(plan['source_projection']),
              'source_plan_id':plan['plan_id'],'receipt_clocks':'ACTUAL_CAPTURE_ONLY_HISTORICAL_CLOCKS_UNKNOWN',
              'scientific_fitness':'NOT_ASSESSED'}
    service.store.write_raw(prefix+'/source/content-manifest.json',canonical(manifest)+b'\n')
    return prefix+'/source/content-manifest.json'


def execute(service,pid,*,fixture=None,network=False,attempt_id=None,scope=None):
    from .import_service import attempt_name,bound_file,code_projection
    from .import_transport import FixtureClock
    from .import_raw_transport import RawFixtureTransport,RawHttpTransport
    plan=service.load(pid);mode=plan['config']['mode'];is_fixture=mode=='fixture'
    aggregate=service.store.raw_profile=='remaining3490'
    policy=plan['policy']
    from .import_raw_profile import AGGREGATE_POLICY
    require(policy==(AGGREGATE_POLICY if aggregate else POLICY),'IMPORT_POLICY_MISMATCH')
    require(plan['source_projection']==code_projection(),'IMPORT_SOURCE_CHANGED')
    require(is_fixture==(fixture is not None) and network==(not is_fixture),'IMPORT_NETWORK_NOT_AUTHORIZED')
    if is_fixture:
        require(scope is None,'IMPORT_SCOPE_MISMATCH')
        if not getattr(service.clock,'synthetic',False):service.clock=FixtureClock(fixture['start_seconds'])
        transport=RawFixtureTransport(fixture,service.clock)
    else:
        require(scope is not None,'IMPORT_SCOPE_MISMATCH')
        authority=decode(bound_file(scope))
        exact(authority,('schema','unit_sha256','source_projection','python_sha256','binding_refs',
                         'attempt_id','credential_reference','terminal_owner'))
        expected_scope=plan['unit']['scope_sha256'] if aggregate else UNIT_SHA
        require(authority['schema']=='polar.raw-sip-execution-authority/1'
                and authority['unit_sha256']==expected_scope and authority['source_projection']==code_projection()
                and authority['attempt_id']==attempt_id and authority['terminal_owner'],
                'IMPORT_SCOPE_MISMATCH')
        require(type(authority['binding_refs']) is list and authority['binding_refs'],'IMPORT_SCOPE_MISMATCH')
        for ref in authority['binding_refs']:bound_file(ref)
        import sys
        require(sha(Path(sys.executable).read_bytes())==authority['python_sha256'],'IMPORT_RUNTIME_MISMATCH')
        if aggregate:
            completed_ref={k:plan['unit']['aggregate']['completed_unit'][k] for k in ('path','sha256')}
            completed_raw=bound_file(completed_ref);completed=decode(completed_raw)
            require(sha(completed_raw)==UNIT_SHA,
                    'IMPORT_SCOPE_MISMATCH')
            credential=completed['credentials']['reference']
        else:credential=plan['unit']['credentials']['reference']
        require(authority['credential_reference']==credential,'IMPORT_SCOPE_MISMATCH')
        transport=RawHttpTransport(authority['credential_reference'])
    aid=attempt_name(attempt_id or str(uuid.uuid4()));prefix='attempts/'+aid
    with service.store.locked():
        service.store.admit_storage()
        require(not service.store.exists(prefix+'/started.json'),'IMPORT_ATTEMPT_EXISTS')
        # Immutable metadata/body graphs are validated once at executor entry;
        # append updates below keep the same evidence-first order. No persistent
        # cache or checkpoint can substitute for validation on the next resume.
        service.store._raw_execution_rows=None;service.store._raw_execution_commits=None
        service.store._read_cache={}
        service.store._raw_execution_rows=records(service)
        service.store._raw_execution_commits=commits(service.store)
        for start,response in records(service):
            if response:disposition(service,start,response)  # saved-body crash recovery, no refetch
        if service.store.exists('budget.json'):
            budget=service.store.read('budget.json')
            require(budget['policy_sha256']==digest(policy),'IMPORT_POLICY_MISMATCH')
        else:
            budget={'schema':'polar.raw-sip-budget/1','policy_sha256':digest(policy),
                    'started_at':timestamp(service.clock.now()),
                    'deadline':timestamp(service.clock.now()+policy['wall_seconds'])}
            service.store.write('budget.json',budget)
        if getattr(service.clock,'synthetic',False) and service.store.exists('clock.json'):
            service.clock.sleep(max(0,seconds(service.store.read('clock.json')['at'])-service.clock.now()))
        deadline=service.clock.monotonic()+max(0,seconds(budget['deadline'])-service.clock.now())
        started={'schema':'polar.import-attempt-start/1','plan_id':pid,'attempt_id':aid,
                 'started_at':timestamp(service.clock.now()),'scope_ref':scope,
                 'mode':mode,'source_projection':plan['source_projection']}
        service.store.write(prefix+'/started.json',started)
        reason=None;interrupted=False
        try:
            for job in plan['jobs']:
                while True:
                    current=status(service,pid)['states'][job['job_id']]
                    if current['state'] not in ('pending','partial') or current['reason']:break
                    if service.store.exists('auth-pause.json'):reason='AUTH_OR_RIGHTS_REFUSAL';break
                    if aggregate and service.store.exists('provider-pause.json'):
                        reason='PROVIDER_RATE_LIMIT_PAUSED';break
                    control=service.store.read('control.json') if service.store.exists('control.json') else {}
                    if control.get('action') in ('pause','stop'):reason='CONTROL_'+control['action'].upper();break
                    previous=records(service)
                    # Unknown bytes reserve the full body envelope; never treated as free.
                    charged=sum(r['body']['bytes'] if r else policy['body_bytes'] for _,r in previous)
                    if len(previous)>=policy['gets'] or charged+policy['body_bytes']>policy['total_bytes']:
                        reason='OPERATION_REQUEST_OR_BYTE_LIMIT';break
                    wait=max(0,seconds(previous[-1][0]['started_at'])+policy['spacing_seconds']-service.clock.now()) if previous else 0
                    reserve=policy.get('materialization_reserve_seconds',4)
                    if wait:service.clock.sleep(min(wait,max(0,deadline-service.clock.monotonic()-reserve)))
                    timeout=min(policy['request_seconds'],deadline-service.clock.monotonic()-reserve)
                    if timeout<=0 or service.clock.now()>=seconds(budget['deadline']):
                        reason='OPERATION_DEADLINE';break
                    pages=current['pages'];cursor=pages[-1]['outcome']['next_cursor'] if pages else None
                    start={'schema':'polar.raw-sip-request-start/1','request_id':str(uuid.uuid4()),
                           'attempt_id':aid,'sequence':len(previous),'job_id':job['job_id'],
                           'request':job['request'],'page':len(pages),'request_cursor':cursor,
                           'started_at':timestamp(service.clock.now()),'timeout_seconds':timeout}
                    service.store.write('requests/'+start['request_id']+'.json',start)
                    service.store._raw_execution_rows.append((start,None))
                    result=transport.get(start,len(previous),timeout)
                    require(type(result['body']) is bytes and len(result['body'])<=POLICY['body_bytes']+1,
                            'IMPORT_TRANSPORT_LIMIT')
                    body_ref=service.store.object(result.pop('body'))  # body is durable FIRST
                    response={**result,'body':body_ref,'request_start_sha256':digest(start),
                              'completed_at':timestamp(service.clock.now())}
                    service.store.write('responses/'+start['request_id']+'.json',response)
                    service.store._raw_execution_rows[-1]=(start,response)
                    disposition(service,start,response)
                    if aggregate and response['status']==429:
                        service.store.write('provider-pause.json',{
                            'reason':'PROVIDER_RATE_LIMIT_PAUSED','request_id':start['request_id'],
                            'headers':response['headers'],'automatic_retry':False})
                    service.store.write('clock.json',{'at':timestamp(service.clock.now())},replace=True)
                    service.store.checkpoint(pid,{'plan_id':pid,'attempt_id':aid,'status':status(service,pid)})
                if reason:break
        except BaseException as exc:
            interrupted=isinstance(exc,(KeyboardInterrupt,SystemExit))
            reason=exc.code if isinstance(exc,ImportError) else 'IMPORT_EXECUTION_ERROR'
        finally:
            state=status(service,pid);counts=state['counts']
            terminal_status=('interrupted' if interrupted else 'complete' if counts['success']==len(plan['jobs'])
                             else 'partial' if counts['success'] or counts['partial'] else 'failed')
            source_manifest=None
            try:
                if aggregate:
                    from .import_raw_bundle import normalized_partitions
                    source_manifest=normalized_partitions(service,plan,prefix,deadline=deadline-4)
                else:source_manifest=normalized(service,plan,prefix)
            except (ImportError,OSError) as exc:
                service.store._terminal_finalization=True
                terminal_status='partial' if counts['success'] or counts['partial'] else 'failed'
                reason='SOURCE_ENVELOPE_NOT_MATERIALIZED'
                service.store.write(prefix+'/source-gap.json',{'reason':reason,
                    'detail':exc.code if isinstance(exc,ImportError) else 'LOCAL_IO_FAILURE',
                    'raw_evidence_retained':True,'next_action':'Review exact envelope/storage bound before retry; no refetch'})
            service.store._terminal_finalization=True
            if service.clock.now()>seconds(budget['deadline']):
                terminal_status='partial' if counts['success'] or counts['partial'] else 'failed'
                reason='OPERATION_DEADLINE_EXCEEDED'
            summary={'schema':'polar.import-terminal-state/1','plan_id':pid,'attempt_id':aid,
                     'status':terminal_status,'reason':reason,'counts':counts,'states':state['states'],
                     'physical_gets':state['scope_physical_gets'],'budget':budget,
                     'scientific_fitness':'NOT_ASSESSED'}
            service.store.write(prefix+'/terminal-state.json',summary)
            service.store.write('clock.json',{'at':timestamp(service.clock.now())},replace=True)
            service.store.checkpoint(pid,summary)
            members=[prefix+'/started.json',prefix+'/terminal-state.json','plans/'+pid+'.json',
                     'policy.json','budget.json']
            if source_manifest:
                members.append(source_manifest)
                source=decode(service.store.raw(source_manifest))
                members += [prefix+'/source/'+n for n in source['objects']]
            else:members.append(prefix+'/source-gap.json')
            for directory in ('requests','responses','outcomes','objects','successes','cache-imports'):
                members+=service.store.list(directory)
            objects={n:{'sha256':sha(service.store.raw(n)),'bytes':len(service.store.raw(n))} for n in members}
            manifest={'schema':'polar.import-terminal-manifest/1','plan_id':pid,'attempt_id':aid,
                      'status':terminal_status,'started_at':started['started_at'],
                      'completed_at':timestamp(service.clock.now()),'scope':service.store.base,
                      'objects':objects,'terminal_state':prefix+'/terminal-state.json',
                      'source_manifest':source_manifest}
            service.store.write(prefix+'/content-manifest.json',manifest)  # terminal marker LAST
            service.store._raw_execution_rows=None;service.store._raw_execution_commits=None
            service.store._read_cache=None
        return {'schema':'polar.import-execution/1','plan_id':pid,'attempt_id':aid,'status':terminal_status,
                'manifest_path':str(service.store.root/service.store.path(prefix+'/content-manifest.json')),
                'manifest_sha256':digest(manifest),'counts':counts,'reason':reason}
