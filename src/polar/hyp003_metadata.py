"""Offline metadata response-position projection; no cache, retry or acquisition engine."""
from .codec import canonical,digest
from .hyp003_source import check,object_value,METADATA,SAMPLE,valid_clock


def kind(value):
    if type(value) is not dict:return 'UNRESOLVED_RESPONSE'
    if type(value.get('data')) is list and value['data']:return 'CANDIDATES'
    if value.get('warning')=='No identifier found.':return 'WARNING_NO_MATCH'
    if 'error' in value:return 'PER_JOB_ERROR'
    return 'UNRESOLVED_RESPONSE'


def metadata_tables(infos):
    roots={info['directory']:info for info in infos if info['manifest']['schema'] in (METADATA,SAMPLE)}
    batches=[];jobs={};receipts={};contexts={}
    def job(req,context):
        identity={'schema':'polar.hyp003-metadata-job/1','producer_schema':METADATA,'request_context':context,'request':req}
        jid=digest(identity);return jid,jobs.setdefault(jid,{'job_id':jid,'identity':identity,'versions':{},'requested_by':[]})
    for root,info in roots.items():
        sample=info['manifest']['schema']==SAMPLE;prefix=info['prefix']
        if sample:
            request=object_value(info,'request.json');receipt=object_value(info,'receipt.json')
            rows=[(str(prefix/'response.json'),request,receipt)]
            context={k:v for k,v in request[0].items() if k!='idValue'} if request else {}
        else:
            plan=object_value(info,'plan.json');check(type(plan) is dict and type(plan.get('request_context')) is dict,'HYP003_METADATA_PLAN_SCHEMA')
            context=plan['request_context'];rs=object_value(info,'receipts.json');check(type(rs) is list,'HYP003_RECEIPT_SCHEMA')
            rows=[(str(prefix/f"responses/batch-{r['batch_ordinal']:04d}.json"),r['request_body'],r) for r in rs]
        contexts[root]=context;receipts[root]={}
        for source,requests,receipt in rows:
            check(type(requests) is list and all(type(r) is dict and type(r.get('idValue')) is str for r in requests),'HYP003_ORIGINAL_REQUEST_SCHEMA')
            check(digest_bytes(canonical(requests)+b'\n')==receipt['request_sha256'],'HYP003_ORIGINAL_WIRE_HASH')
            check(source in info['files'] and isinstance(info['files'][source],bytes),'HYP003_RESPONSE_NOT_MANIFEST_MEMBER')
            body=info['files'][source];check(digest_bytes(body)==receipt['response_sha256'] and len(body)==receipt['response_bytes'],'HYP003_ORIGINAL_RESPONSE_HASH')
            from .hyp003_source import decode
            values=decode(body)
            aligned=receipt['http_status']==200 and type(values) is list and len(values)==len(requests)
            captured=receipt.get('completed_at',receipt.get('actual_completed_at'))
            check(valid_clock(captured),'HYP003_RECEIPT_CLOCK')
            ref={'manifest_sha256':info['ref']['sha256'],'member':source,'response_sha256':digest_bytes(body),
                 'request_sha256':receipt['request_sha256'],'actual_capture_at':captured}
            receipts[root][source]=(requests,values,receipt,ref,aligned)
            batches.append({'source':ref,'assigned_by_length':aligned,'status':'ALIGNED' if aligned else 'FAILED_UNASSIGNED_BATCH',
                            'request_count':len(requests),'response_count':len(values) if type(values) is list else None,
                            'receipt':receipt,'body':values})
        if info['primary'] and not sample:
            selected=object_value(info,'selected-symbols.json');check(type(selected) is list and all(type(s) is str for s in selected),'HYP003_SELECTED_SYMBOLS_SCHEMA')
            for symbol in selected:
                _,item=job({**context,'idValue':symbol},context)
                item['requested_by'].append(info['ref']['sha256'])
    # Inspect every explicitly supplied primary snapshot; ancestors support validation, not silent latest overlay.
    for info in infos:
        if not info['primary'] or info['manifest']['schema']!=METADATA:continue
        entries=object_value(info,'job-results.json');check(type(entries) is dict,'HYP003_JOB_RESULTS_SCHEMA')
        for symbol,entry in entries.items():
            check(type(entry) is dict and type(entry.get('job_ordinal')) is int,'HYP003_JOB_REFERENCE_SCHEMA')
            source=entry['source'];position=entry['job_ordinal'];capture_root=entry.get('capture_root')
            possible=[]
            for root,capture in roots.items():
                if capture_root is not None and root!=capture_root:continue
                hit=receipts[root].get(source)
                if hit is None:continue
                requests,values,receipt,ref,aligned=hit
                expected={**contexts[root],'idValue':symbol}
                if aligned and ref['response_sha256']==entry['source_sha256'] and 0<=position<len(requests) and requests[position]==expected and values[position]==entry['response']:
                    possible.append((root,hit))
            check(len(possible)==1,'HYP003_CAPTURE_POSITION_UNVERIFIED_OR_AMBIGUOUS')
            root,(requests,values,receipt,ref,aligned)=possible[0]
            req=requests[position];jid,item=job(req,contexts[root]);response=values[position];response_hash=digest(response)
            version=item['versions'].setdefault(response_hash,{'response_sha256':response_hash,'kind':kind(response),'response':response,'sources':{}})
            provenance={**ref,'position':position,'source_snapshot_sha256':info['ref']['sha256'],'reused_from_prior_capture':root!=info['directory'],'producer_job_record':entry}
            version['sources'][digest(provenance)]=provenance
    result=[]
    for jid,item in sorted(jobs.items()):
        versions=[]
        for h,v in sorted(item['versions'].items()):versions.append({**v,'sources':[v['sources'][k] for k in sorted(v['sources'])]})
        successes=[v for v in versions if v['kind'] in ('CANDIDATES','WARNING_NO_MATCH')]
        state='UNRECEIVED' if not versions else 'CONFLICTING_SUCCESS' if len(successes)>1 else 'RECEIVED' if successes else 'ERROR_OR_UNRESOLVED'
        result.append({**item,'versions':versions,'requested_by':sorted(set(item['requested_by'])),'state':state,
                       'candidate_count':sum(len(v['response']['data']) for v in versions if type(v['response'].get('data')) is list),
                       'economic_id_selection':None})
    return result,batches


def digest_bytes(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()
