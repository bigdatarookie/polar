"""Partitioned source-record/date projection over the existing HYP003 checker.

This is availability of supplied source evidence, never an economic universe,
market calendar, feature/label set, causal clock or financial experiment.
"""
from collections import Counter, defaultdict
from datetime import date
import hashlib
import os
from pathlib import Path

from .codec import canonical, digest
from .hyp003_source import (Sources, object_value, decode, check, RAW, JSON_LIMIT,
                            NDJSON_LIMIT, LINE_LIMIT, safe_root, relative, MULTIYEAR)
from .hyp003_preparation import quality
from .history_store import fsync_directory
from .import_contract import ImportError as RawImportError

R0_SHA='71f3f93bc59dd3e716011e7bcbcf6ab269cc2cb5e6b8283c4b74eab493cf55c0'
GRID_SHA='b12d848020e0844a418842b9953a7818e2f8ec3cee3c37fa578ac7e532f115d0'
PART_LIMIT=16*1024**2
TOTAL_LIMIT=20*1024**3


def reference(ref, limit):
    check(type(ref) is dict and set(ref)=={'path','sha256'},'HYP003_AVAILABILITY_REFERENCE')
    path=Path(ref['path']);check(path.is_absolute(),'HYP003_ABSOLUTE_ROOT_REQUIRED')
    value,verified=Sources().read(path.parent,path.name,limit,{'sha256':ref['sha256']})
    return value,verified


def packets(entry):
    """A collection is an index of unchanged RAW-compatible input packets."""
    check(type(entry) is dict and set(entry)=={'directory','manifest','manifest_sha256','links_ref'},
          'HYP003_AVAILABILITY_INPUT')
    root=Path(entry['directory']);check(root.is_absolute(),'HYP003_ABSOLUTE_ROOT_REQUIRED')
    name=relative(entry['manifest'])
    raw,_=Sources().read(root,name,JSON_LIMIT,{'sha256':entry['manifest_sha256']})
    manifest=decode(raw)
    if manifest.get('schema') in (RAW,MULTIYEAR):
        yield {'adapter':manifest['schema'],'directory':str(root),'manifest':name,
               'manifest_sha256':entry['manifest_sha256']},None
        return
    check(manifest.get('schema')=='polar.raw-sip-source-collection/1'
          and type(manifest.get('packets')) is list and 1<=len(manifest['packets'])<=10000,
          'HYP003_AVAILABILITY_COLLECTION')
    parent=Path(name).parent;objects=manifest['objects'];seen=set();used={'job-status-index.ndjson'}
    # Retain and verify the global job/status index even when individual source
    # packets have no bars. Packet jobs never stand in for economic identities.
    job_name=str(parent/'job-status-index.ndjson')
    job_rows,_=Sources().read(root,job_name,NDJSON_LIMIT,objects['job-status-index.ndjson'])
    check(len(job_rows)==manifest['jobs'],'HYP003_AVAILABILITY_JOB_INDEX')
    check([r['global_job_ordinal'] for r in job_rows]==list(range(len(job_rows))),
          'HYP003_AVAILABILITY_JOB_INDEX')
    by_job={r['canonical_job_id']:r for r in job_rows};progress=Counter();appearances=defaultdict(list)
    check(len(by_job)==len(job_rows),'HYP003_AVAILABILITY_JOB_INDEX')
    for part_number,packet in enumerate(manifest['packets']):
        key=relative(packet['manifest']);check(key not in seen,'HYP003_AVAILABILITY_DUPLICATE_PACKET');seen.add(key)
        used.add(key)
        check(objects[key]=={k:packet[k] for k in ('bytes','sha256')},'HYP003_AVAILABILITY_COLLECTION')
        packet_name=str(parent/key)
        body,_=Sources().read(root,packet_name,JSON_LIMIT,objects[key]);part=decode(body)
        for member,ref in part['objects'].items():
            full=str(Path(key).parent/relative(member))
            check(objects.get(full)==ref,'HYP003_AVAILABILITY_COLLECTION')
            used.add(full)
        bars,_=Sources().read(root,str(Path(packet_name).parent/'bars.ndjson'),PART_LIMIT,
                             part['objects']['bars.ndjson'])
        check(len(bars)==sum(s['rows'] for s in packet['job_segments'].values()),
              'HYP003_AVAILABILITY_ROW_CONSERVATION')
        for jid,segment in packet['job_segments'].items():
            check(jid in by_job and segment['first_job_row']==progress[jid]
                  and type(segment['rows']) is int and segment['rows']>=0,
                  'HYP003_AVAILABILITY_ROW_CONSERVATION')
            progress[jid]+=segment['rows'];appearances[jid].append(part_number)
        yield {'adapter':RAW,'directory':str(root),'manifest':packet_name,
               'manifest_sha256':packet['sha256']},entry['manifest_sha256']
    check(used==set(objects) and sum(progress.values())==manifest['normalized_rows'],
          'HYP003_AVAILABILITY_ROW_CONSERVATION')
    for jid,row in by_job.items():
        check(appearances[jid] and progress[jid]==row['rows']
              and appearances[jid][0]==row['first_partition'] and appearances[jid][-1]==row['last_partition'],
              'HYP003_AVAILABILITY_ROW_CONSERVATION')


def pointer_state(info,row):
    """Verify both historical marker encodings literally, never split an alias."""
    from .import_raw_sip import page
    ref=row.get('source_reference');symbol=row.get('source_symbol')
    if not isinstance(ref,dict):return 'REFERENCED_ONLY'
    marker=ref.get('source_array')
    if marker not in ('bars/'+str(symbol),'bars.'+str(symbol)):return 'INVALID_SOURCE_POINTER'
    ordinal=ref.get('source_row_ordinal');body_sha=ref.get('source_body_sha256')
    if type(ordinal) is not int or ordinal<0:return 'INVALID_SOURCE_POINTER'
    candidates=[name for name,r in info['inventory'].items() if r['sha256']==body_sha]
    if not candidates:return 'REFERENCED_ONLY'
    body=info['files'][str(info['prefix']/candidates[0])]
    if not isinstance(body,bytes):return 'INVALID_SOURCE_POINTER'
    try:
        parsed=info.setdefault('_pointer_cache',{})
        if body_sha not in parsed:parsed[body_sha]=page(body,limit=JSON_LIMIT)
        rows=parsed[body_sha]['bars'].get(symbol,[])
        if ordinal>=len(rows) or rows[ordinal]!=row.get('raw_fields_exact_tokens'):
            return 'INVALID_SOURCE_POINTER'
    except (RawImportError,ValueError,KeyError,TypeError,IndexError):return 'INVALID_SOURCE_POINTER'
    return 'VERIFIED_EXACT_BODY_POSITION'


def producer_links(jobs,parents):
    """Only a complete job/parent identity pair can verify a supplied link."""
    from .import_raw_sip import job_id
    entries=[]
    for job in jobs:
        if not isinstance(job,dict) or not isinstance(job.get('request'),dict):continue
        request=job['request'];rid=job.get('population_record_id');source_id=job.get('job_id')
        if type(rid) is not str or type(source_id) is not str:continue
        try:canonical_id=job_id(request)
        except RawImportError:continue  # Legacy/unbound declarations are not producer verification.
        for parent in parents:
            if (parent.get('population_record_id')==rid and parent.get('request')==request
                    and parent.get('job_id')==source_id
                    and parent.get('canonical_job_id',parent.get('raw_coverage_ref'))==canonical_id):
                identity={'population_record_id':rid,'source_symbol':request['symbols'],
                          'request':request,'canonical_job_id':canonical_id,'source_plan_job_id':source_id}
                entries.append((identity,parent))
    return entries


def multiyear_bindings(info,explicit,by_id,profiles,coverage,links_sha):
    """Declared alias/revision evidence; no synthesized producer job or transport."""
    version=info['ref']['sha256'];aliases=defaultdict(list)
    check(type(explicit) is list and explicit,'HYP003_MULTIYEAR_LINKS_REQUIRED')
    linked={}
    for link in explicit:
        check(type(link) is dict and set(link)=={'population_record_id','source_symbol','source_manifest_sha256'},
              'HYP003_AVAILABILITY_LINKS')
        rid=link['population_record_id'];symbol=link['source_symbol']
        check(type(rid) is str and type(symbol) is str and rid in by_id and symbol==by_id[rid]['literal_symbol']
              and sum(row['literal_symbol']==symbol for row in by_id.values())==1
              and symbol not in linked,'HYP003_AVAILABILITY_RECORD_JOIN')
        check(link['source_manifest_sha256']==version,'HYP003_MULTIYEAR_REVISION_LINK')
        linked[symbol]=rid
    declarations=object_value(info,'source-profiles.json');quality_report=object_value(info,'quality.json')
    objects=info['manifest'].get('source_objects')
    check(type(declarations) is list and 1<=len(declarations)<=10000 and type(objects) is list and len(objects)<=10000 and isinstance(quality_report,dict)
          and type(quality_report.get('chunks')) is list,
          'HYP003_MULTIYEAR_PROFILE')
    body_by_request={}
    for ref in objects:
        check(type(ref) is dict and set(ref)=={'request_ordinal','bytes','sha256'}
              and type(ref['request_ordinal']) is int and ref['request_ordinal']>=0
              and type(ref['bytes']) is int and 0<=ref['bytes']<=JSON_LIMIT
              and ref['request_ordinal'] not in body_by_request,'HYP003_MULTIYEAR_PROFILE')
        # hash spelling checked without admitting any unlisted body path.
        from .hyp003_source import hash_value
        hash_value(ref['sha256']);body_by_request[ref['request_ordinal']]=ref
    chunks=quality_report.get('chunks',[]) if isinstance(quality_report,dict) else []
    seen=set();declared={}
    for profile in declarations:
        check(type(profile) is dict,'HYP003_MULTIYEAR_PROFILE')
        ordinal=profile.get('request_ordinal');symbol=profile.get('symbol');request=profile.get('parameters')
        check(type(ordinal) is int and ordinal>=0 and ordinal not in seen
              and type(symbol) is str and type(request) is dict
              and type(profile.get('chunk_index')) is int and profile['chunk_index']>=0
              and request.get('symbols')==symbol and type(request.get('start')) is str
              and type(request.get('end')) is str,'HYP003_MULTIYEAR_PROFILE')
        seen.add(ordinal)
        start=profile.get('start');end=profile.get('end')
        check(type(start) is str and type(end) is str and start<=end
              and date.fromisoformat(start).isoformat()==start and date.fromisoformat(end).isoformat()==end
              and request['start']==start+'T00:00:00Z' and request['end']==end+'T23:59:59Z',
              'HYP003_MULTIYEAR_PROFILE')
        declared[ordinal]=profile
        if symbol not in linked:continue
        rid=linked[symbol];pid=digest({'request':request,'source_revision':version,'request_ordinal':ordinal})
        basis={k:v for k,v in request.items() if k not in ('start','end')}
        profiles[pid]={'request':request,'compatibility_basis_sha256':digest(basis),
                       'source_profile':profile,'interval_end_inclusive':True}
        states=[chunk.get('source_coverage_status') for chunk in chunks
                if isinstance(chunk,dict) and chunk.get('request_ordinal')==ordinal]
        fact={'source_manifest_sha256':version,'collection_sha256':None,'profile_id':pid,
              'profile_binding':'DECLARED_NOT_VERIFIED','canonical_job_id':None,'source_plan_job_id':None,
              'transport_state':'UNKNOWN','links_sha256':links_sha,
              'source_link_basis':'EXPLICIT_LITERAL_ALIAS_AND_SOURCE_REVISION',
              'source_request_ordinal':ordinal,'source_body_ref':body_by_request.get(ordinal),
              'producer_coverage_states':states}
        coverage[rid].append(fact);aliases[symbol].append((rid,fact))
    check(set(body_by_request)<=seen and set(linked)<=set(p['symbol'] for p in declarations),
          'HYP003_MULTIYEAR_PROFILE')
    info['_multiyear_profiles']=declared;info['_multiyear_bodies']=body_by_request
    return aliases


def multiyear_row(info,row):
    ordinal=row.get('request_ordinal');profile=info['_multiyear_profiles'].get(ordinal)
    ref=info['_multiyear_bodies'].get(ordinal)
    check(type(ordinal) is int and profile is not None and ref is not None
          and row.get('source_symbol')==profile['symbol']
          and row.get('chunk_index')==profile.get('chunk_index')
          and row.get('source_body_sha256')==ref['sha256'],'HYP003_MULTIYEAR_ROW_PROFILE')
    metadata={key:row.get(key) for key in ('request_ordinal','chunk_index','aggregation_label',
              'quality_reasons','mapping_status','economic_security_id','causal_K',
              'source_array','source_row_ordinal','source_body_sha256')}
    pointer={'source_array':row.get('source_array'),'source_row_ordinal':row.get('source_row_ordinal'),
             'source_body_sha256':row.get('source_body_sha256')}
    return {**row,'source_reference':pointer},metadata


def write_availability(config, output_dir):
    check(len(canonical(config))<=64*1024,'HYP003_CONFIG_LIMIT')
    check(type(config) is dict and set(config)=={'schema','mode','population_ref','grid_ref','inputs'}
          and config['schema']=='polar.hyp003-availability-config/1'
          and config['mode'] in ('INVENTED','RETAINED'),'HYP003_AVAILABILITY_CONFIG')
    population,popref=reference(config['population_ref'],NDJSON_LIMIT)
    grid_raw,gridref=reference(config['grid_ref'],JSON_LIMIT);grid=decode(grid_raw)
    if config['mode']=='RETAINED':
        check(popref['sha256']==R0_SHA and gridref['sha256']==GRID_SHA,'HYP003_AVAILABILITY_FIXED_SCOPE')
    check(type(population) is list and 1<=len(population)<=3514,'HYP003_AVAILABILITY_POPULATION')
    by_id={}
    for row in population:
        rid=row.get('population_record_id');alias=row.get('literal_symbol')
        check(type(rid) is str and rid not in by_id and type(alias) is str and alias,
              'HYP003_AVAILABILITY_POPULATION')
        by_id[rid]=row
    dates=grid.get('all');check(type(dates) is list and 1<=len(dates)<=1008
                              and len(set(dates))==len(dates),'HYP003_AVAILABILITY_GRID')
    for day in dates:
        check(type(day) is str and date.fromisoformat(day).isoformat()==day,'HYP003_AVAILABILITY_GRID')
    check(type(config['inputs']) is list and len(config['inputs'])<=64,'HYP003_AVAILABILITY_INPUTS')
    root=Path(output_dir);check(root.is_absolute(),'HYP003_ABSOLUTE_OUTPUT_REQUIRED')
    check(all(not (p/'.git').exists() for p in (root,*root.parents)),'HYP003_OUTPUT_INSIDE_REPOSITORY')
    safe_root(root.parent);check(not root.exists(),'HYP003_AVAILABILITY_OUTPUT_EXISTS')
    root.mkdir(mode=0o700);scratch=root/'.working';scratch.mkdir(mode=0o700)
    members={};total=0;input_bytes=0;source_versions=[];profiles={};coverage=defaultdict(list)
    ordinal_of={rid:i for i,rid in enumerate(by_id)};unlinked=[];row_count=0;seen_versions=set()

    def emit(name,raw):
        nonlocal total
        check(len(raw)<=PART_LIMIT and total+len(raw)<=TOTAL_LIMIT,'HYP003_AVAILABILITY_OUTPUT_LIMIT')
        target=root/relative(name);target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with target.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        target.chmod(0o400)
        for parent in (target.parent,*target.parent.parents):
            fsync_directory(parent)
            if parent==root:break
        total+=len(raw)
        members[name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

    def spool(rid,observations):
        nonlocal total
        path=scratch/(str(ordinal_of[rid])+'.ndjson')
        raw=b''.join(canonical(r)+b'\n' for r in observations)
        check(total+len(raw)<=TOTAL_LIMIT,'HYP003_AVAILABILITY_OUTPUT_LIMIT')
        with path.open('ab') as f:f.write(raw)
        total+=len(raw)

    for entry in config['inputs']:
        explicit=[];links_sha=None;links_schema=None
        if entry.get('links_ref') is not None:
            value,links=reference(entry['links_ref'],JSON_LIMIT);value=decode(value)
            check(value.get('schema') in ('polar.hyp003-source-record-links/1','polar.hyp003-multiyear-source-record-links/1')
                  and type(value.get('links')) is list,'HYP003_AVAILABILITY_LINKS')
            explicit=value['links'];links_sha=links['sha256'];links_schema=value['schema']
        for source,collection_sha in packets(entry):
            admitted=Sources();info=admitted.add(source,True,allow_multiyear=True);input_bytes+=admitted.total
            check(input_bytes<=TOTAL_LIMIT,'HYP003_AVAILABILITY_INPUT_LIMIT')
            version=info['ref']['sha256']
            check(version not in seen_versions,'HYP003_DUPLICATE_PRIMARY_INPUT');seen_versions.add(version)
            multiyear=info['manifest']['schema']==MULTIYEAR
            if multiyear:
                check(links_schema=='polar.hyp003-multiyear-source-record-links/1','HYP003_MULTIYEAR_LINKS_REQUIRED')
                aliases=multiyear_bindings(info,explicit,by_id,profiles,coverage,links_sha)
            else:
                check(links_schema in (None,'polar.hyp003-source-record-links/1'),'HYP003_AVAILABILITY_LINKS')
                plan=object_value(info,'source-plan.json')
                jobs=plan.get('unit',{}).get('jobs',[])
                parents=object_value(info,'parent-coverage-ledger.ndjson')
                producer=producer_links(jobs,parents)
                auto=[identity for identity,_ in producer if identity['population_record_id'] in by_id
                      and sum(other==identity for other,_ in producer)==1]
                links=explicit or auto;aliases=defaultdict(list)
                for link in links:
                    check(type(link) is dict and set(link)=={'population_record_id','source_symbol','request',
                            'canonical_job_id','source_plan_job_id'},'HYP003_AVAILABILITY_LINKS')
                    rid=link['population_record_id'];check(rid in by_id
                        and link['source_symbol']==by_id[rid]['literal_symbol'],'HYP003_AVAILABILITY_RECORD_JOIN')
                    request=link['request'];check(request is None or isinstance(request,dict),'HYP003_AVAILABILITY_PROFILE')
                    if request is not None:
                        check(type(request.get('start')) is str and type(request.get('end')) is str
                              and request.get('symbols')==link['source_symbol']
                              and request['start']<request['end'],'HYP003_AVAILABILITY_PROFILE')
                    # Both ID namespaces, literal alias, record and exact request
                    # must resolve to ONE producer job/parent entry. Never replace
                    # a caller's mismatched ID with a convenient parent value.
                    matched=[parent for identity,parent in producer if identity==link]
                    related=[identity for identity,_ in producer
                             if identity['population_record_id']==rid
                             and identity['source_symbol']==link['source_symbol']]
                    check(not related or len(matched)==1,'HYP003_AVAILABILITY_PRODUCER_LINK_MISMATCH')
                    verified=len(matched)==1
                    basis={k:v for k,v in request.items() if k not in ('start','end')} if request else None
                    profile_id=digest({'request':request,'unbound_source':None if request else version})
                    profiles[profile_id]={'request':request,'compatibility_basis_sha256':digest(basis) if basis else None}
                    # A record alone proves no request-specific transport outcome.
                    # Unresolved legacy declarations must not borrow completion.
                    parent=matched[0] if verified else {}
                    fact={'source_manifest_sha256':version,'collection_sha256':collection_sha,
                          'profile_id':profile_id,'profile_binding':'VERIFIED_PRODUCER_JOB' if verified else 'DECLARED_NOT_VERIFIED',
                          'canonical_job_id':link['canonical_job_id'],
                          'source_plan_job_id':link['source_plan_job_id'],
                          'transport_state':parent.get('raw_data_state','UNKNOWN'),
                          'links_sha256':links_sha}
                    coverage[rid].append(fact);aliases[link['source_symbol']].append((rid,fact))
            grouped=defaultdict(list)
            for position,row in enumerate(object_value(info,'bars.ndjson')):
                metadata=None
                if multiyear:row,metadata=multiyear_row(info,row)
                row_count+=1;pointer=pointer_state(info,row);validation=quality(row)
                tokens=row.get('raw_fields_exact_tokens',{})
                if not isinstance(tokens,dict):tokens={}
                fields={}
                for long,key in [('open','o'),('high','h'),('low','l'),('close','c'),('volume','v')]:
                    direct=row.get('raw_'+long);token=tokens.get(key)
                    agrees=None if direct is None or token is None else direct==token
                    fields[long]={'normalized_field':'raw_'+long,'body_field':key,
                                  'normalized_supplied':direct is not None,'body_token_supplied':token is not None,
                                  'exact_token_agreement':agrees}
                    if agrees is False:
                        validation['status']='FIELDS_PARTIAL_OR_INVALID'
                        validation['reasons'].append('SOURCE_FIELD_TOKEN_MISMATCH:'+long)
                observation={'source_manifest_sha256':version,'source_member':'bars.ndjson',
                    'source_row_ordinal':position,'reference_date':row.get('reference_date'),
                    'source_symbol':row.get('source_symbol'),
                    'raw_value_sha256':digest({k:row[k] for k in ('raw_open','raw_high','raw_low','raw_close','raw_volume',
                        'raw_fields_exact_tokens') if k in row}),
                    'source_reference':row.get('source_reference'),'pointer_status':pointer,
                    'validation':validation,'field_positions':fields,
                    'clocks':{k:row.get(k) for k in ('event_open_at','event_close_at','observed_published_at',
                                                   'observed_historical_available_at','estimated_K')}}
                if multiyear:observation['source_metadata']=metadata
                targets=aliases.get(row.get('source_symbol'),[])
                if multiyear:targets=[t for t in targets if t[1]['source_request_ordinal']==row['request_ordinal']]
                if not targets:unlinked.append(observation)
                for rid,fact in targets:grouped[rid].append({**observation,'profile_id':fact['profile_id']})
            for rid,observations in grouped.items():spool(rid,observations)
            # Never hold an unbounded unlinked corpus in memory.
            if unlinked:
                for offset in range(0,len(unlinked),100):
                    name=f'unlinked/{len(members):08d}.ndjson'
                    emit(name,b''.join(canonical(r)+b'\n' for r in unlinked[offset:offset+100]))
                unlinked=[]
            source_versions.append({'manifest_sha256':version,'collection_sha256':collection_sha,
                                    'members':info['inventory'],'linked_records':len(grouped),
                                    'source_rows':len(object_value(info,'bars.ndjson'))})
    counts=Counter();population_index=[]
    for rid,original in by_id.items():
        cells=defaultdict(list);spool_path=scratch/(str(ordinal_of[rid])+'.ndjson')
        observations=[]
        if spool_path.exists():
            check(spool_path.stat().st_size<=NDJSON_LIMIT,'HYP003_AVAILABILITY_RECORD_LIMIT')
            with spool_path.open('rb') as f:
                for line in f:
                    check(len(line)<=LINE_LIMIT,'HYP003_LINE_LIMIT');row=decode(line)
                    observations.append(row)
                    if type(row['reference_date']) is str:cells[row['reference_date']].append(row)
        # Preserve ALL observations, including dates outside the supplied grid.
        for offset in range(0,len(observations),100):
            emit(f'rows/{ordinal_of[rid]:05d}/{offset//100:05d}.ndjson',
                 b''.join(canonical(r)+b'\n' for r in observations[offset:offset+100]))
        indexed=[]
        for day in dates:
            versions=cells.get(day,[]);by_basis=defaultdict(set);profile_states=[]
            for row in versions:
                basis=profiles[row['profile_id']]['compatibility_basis_sha256']
                by_basis[basis or 'UNBOUND:'+row['profile_id']].add(row['raw_value_sha256'])
            for fact in coverage[rid]:
                req=profiles[fact['profile_id']]['request']
                state=('PROFILE_INTERVAL_UNKNOWN' if req is None else
                       'OUTSIDE_REQUEST_INTERVAL' if not (req['start'][:10]<=day and
                           (day<=req['end'][:10] if profiles[fact['profile_id']].get('interval_end_inclusive') else day<req['end'][:10])) else
                       fact['transport_state'])
                profile_states.append({'profile_id':fact['profile_id'],
                    'source_manifest_sha256':fact['source_manifest_sha256'],'state':state})
            if versions:state='CONFLICTING' if any(len(v)>1 for v in by_basis.values()) else 'OBSERVED_SOURCE_ROWS'
            else:
                applicable=[f['state'] for f in profile_states if f['state']!='OUTSIDE_REQUEST_INTERVAL']
                if not applicable or all(s=='UNRECEIVED' for s in applicable):state='UNREQUESTED'
                elif all(s=='RECEIVED_EMPTY' for s in applicable):state='COMPLETE_EMPTY'
                elif all(s in ('RECEIVED_EMPTY','RECEIVED_COMPLETE') for s in applicable):
                    state='MISSING_WITHIN_COMPLETE_REQUEST'
                else:state='PARTIAL_OR_UNKNOWN'
            counts[state]+=1
            indexed.append({'population_record_id':rid,'reference_date':day,'state':state,
                            'profile_states':profile_states,'observations':[
                                {k:r[k] for k in ('source_manifest_sha256','source_member','source_row_ordinal',
                                     'profile_id','raw_value_sha256','pointer_status')} for r in versions]})
        name=f'availability/{ordinal_of[rid]:05d}.ndjson'
        emit(name,b''.join(canonical(r)+b'\n' for r in indexed))
        population_index.append({'ordinal':ordinal_of[rid],'source_record':original,
                                 'availability_member':name,'coverage':coverage[rid]})
        if spool_path.exists():
            total-=spool_path.stat().st_size;spool_path.unlink()
    scratch.rmdir()
    emit('population-index.ndjson',b''.join(canonical(r)+b'\n' for r in population_index))
    emit('profiles.json',canonical(profiles))
    emit('reference-dates.json',canonical(grid))
    code={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
          for n in ('hyp003_availability.py','hyp003_availability_schema.json','hyp003_source.py',
                    'hyp003_preparation.py','import_raw_sip.py')}
    manifest={'schema':'polar.hyp003-source-availability-content/1','objects':dict(members),
              'population':popref,'grid':gridref,'records':len(by_id),'reference_dates':len(dates),
              'source_record_date_slots':len(by_id)*len(dates),'states':dict(counts),
              'source_rows':row_count,'sources':source_versions,'code':code,
              'scope':'SOURCE_RECORD_DATE_EVIDENCE_ONLY','economic_universe':'UNRESOLVED',
              'calendar':'REFERENCE_DATES_ONLY','causal_availability':'NOT_QUALIFIED',
              'features':'NOT_RUN','financial':'NOT_RUN'}
    manifest['revision']='hyp003availability-'+digest(manifest)
    # Terminal content marker is last; an interrupted directory without it is
    # incomplete and cannot be consumed as a dataset revision.
    emit('content-manifest.json',canonical(manifest))
    return {'schema':'polar.hyp003-availability-result/1','revision':manifest['revision'],
            'manifest_sha256':members['content-manifest.json']['sha256'],
            'manifest_path':str(root/'content-manifest.json'),'counts':dict(counts),'financial':'NOT_RUN'}


def read_availability(output_dir):
    from .hyp003_source import member_stream
    root=safe_root(output_dir)
    raw,_=Sources().read(root,'content-manifest.json',PART_LIMIT)
    report=decode(raw);revision=report.pop('revision',None)
    check(report.get('schema')=='polar.hyp003-source-availability-content/1'
          and revision=='hyp003availability-'+digest(report),'HYP003_AVAILABILITY_IDENTITY')
    total=0
    for name,expected in report['objects'].items():
        size=0;hasher=hashlib.sha256()
        with member_stream(root,relative(name),PART_LIMIT) as stream:
            while chunk:=stream.read(1024**2):size+=len(chunk);hasher.update(chunk)
        total+=size
        check(total<=TOTAL_LIMIT and size==expected['bytes'] and hasher.hexdigest()==expected['sha256'],
              'HYP003_AVAILABILITY_OBJECT_HASH')
    report['revision']=revision
    return report
