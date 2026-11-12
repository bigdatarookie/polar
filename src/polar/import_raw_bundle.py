"""Bounded immutable envelopes over the existing raw-SIP evidence graph."""
from .import_contract import canonical, decode, digest, sha, require, ImportError
from .import_raw_sip import page, records, commits, status, adjusted, kind


def normalized_partitions(service, plan, prefix, *, deadline):
    """Partition by encoded bytes; keep job identity even across a row boundary."""
    limit=plan['policy']['partition_bytes'];store=service.store
    all_adjusted=adjusted(store)
    states=status(service,plan['plan_id'])['states']
    grouped={}
    for start,response in records(service):
        if response:grouped.setdefault(start['job_id'],[]).append((start,response))
    saved=commits(store);objects={};packets=[];job_index=[]
    buffer=bytearray();parents={};body_refs={};segments={};part=0

    def emit(relative,raw):
        require(service.clock.monotonic()<deadline,'IMPORT_SOURCE_ENVELOPE_DEADLINE')
        store.write_raw(prefix+'/source/'+relative,raw)
        objects[relative]={'bytes':len(raw),'sha256':sha(raw)}
        return objects[relative]

    def flush():
        nonlocal buffer,parents,body_refs,segments,part
        if not parents:return
        base=f'parts/{part:05d}/';members={}
        def member(name,raw):members[name]=emit(base+name,raw)
        member('bars.ndjson',bytes(buffer))
        member('parent-coverage-ledger.ndjson',b''.join(canonical(r)+b'\n' for r in parents.values()))
        member('coverage.json',canonical([{
            'job_id':jid,'transport_state':r['raw_data_state'],
            'expected_reference_positions':r.get('expected_reference_labels'),
            'calendar_validated_positions':None,'coverage_fraction':None,
            'economic_eligible_N_contribution':None} for jid,r in parents.items()])+b'\n')
        member('source-plan.json',canonical({
            'schema':'polar.adjusted-sip-source-plan/1' if all_adjusted else 'polar.raw-sip-source-plan/1','source_plan_id':plan['plan_id'],
            'selected_symbols':[r['request']['symbols'] for r in parents.values()],
            'unit':{'jobs':[plan_job['relation'] for plan_job in plan['jobs']
                            if plan_job['job_id'] in parents]},
            'policy':plan['policy'],'scope_sha256':plan['unit']['scope_sha256'],
            'source_job_segments':segments,'fitness':'NOT_ASSESSED'})+b'\n')
        for name,ref in sorted(body_refs.items()):member(name,store.object_read(ref))
        manifest={'schema':'polar.vendor-all-adjusted-source-content/1' if all_adjusted else 'polar.partial-raw-pv-source-content/1','objects':members,
                  'recipe_sha256':digest(plan['source_projection']),'source_plan_id':plan['plan_id'],
                  'receipt_clocks':'ACTUAL_CAPTURE_ONLY_HISTORICAL_CLOCKS_UNKNOWN',
                  'scientific_fitness':'NOT_ASSESSED'}
        ref=emit(base+'content-manifest.json',canonical(manifest)+b'\n')
        packets.append({'manifest':base+'content-manifest.json',**ref,
                        'job_segments':segments,'bars':members['bars.ndjson']})
        buffer=bytearray();parents={};body_refs={};segments={};part+=1

    for ordinal,job in enumerate(plan['jobs']):
        jid=job['job_id'];state=states[jid]
        raw_state=('RECEIVED_EMPTY' if state['kind']==kind(store,False) else 'RECEIVED_COMPLETE'
            if state['state']=='success' else 'RECEIVED_PARTIAL' if state['state']=='partial'
            else 'UNRECEIVED_OUTCOME_UNKNOWN' if state['reason']=='UNKNOWN_IN_FLIGHT'
            else 'REQUEST_FAILED' if state['state']=='permanent_error' else 'UNRECEIVED')
        parent={**job['relation'],'canonical_job_id':jid,'global_job_ordinal':ordinal,
                'this_batch':state['state'],'this_batch_reason':state['reason'],
                'raw_data_state':raw_state,'raw_coverage_ref':jid}
        related=grouped.get(jid,[])
        if not related:
            versions=saved.get(jid,[])
            if len({v['response_sha256'] for v in versions})==1 and versions:
                related=[({'request_id':None,'page':e['page']},{'body':e['body']})
                         for e in versions[0]['pages']]
        emitted=0;first_part=part
        # Empty, failed and unreceived jobs also occupy an explicit global slot.
        # Limit parent-only packets to keep the existing consumer bounded.
        if len(parents)>=32:flush();first_part=part
        parents[jid]=parent;segments.setdefault(jid,{'first_job_row':0,'rows':0})
        for start,response in related:
            raw=store.object_read(response['body'])
            try:body=page(raw)
            except ImportError:continue  # outer terminal graph retains malformed bodies
            for symbol,rows in body['bars'].items():
                for row_ordinal,original in enumerate(rows):
                    require(service.clock.monotonic()<deadline,'IMPORT_SOURCE_ENVELOPE_DEADLINE')
                    label=original.get('t');date=label[:10] if type(label) is str else None
                    in_window=type(date) is str and job['request']['start'][:10]<=date<job['request']['end'][:10]
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
                           'source_body_sha256':response['body']['sha256'],'source_array':'bars/'+symbol,
                           'source_row_ordinal':row_ordinal,'job_id':jid,
                           'request_id':start['request_id'],'page':start['page']}}
                    for field,key in [('raw_open','o'),('raw_high','h'),('raw_low','l'),
                                      ('raw_close','c'),('raw_volume','v')]:row[field]=original.get(key)
                    if all_adjusted:
                        from .import_adjusted_sip import source_row
                        row=source_row(row)
                    encoded=canonical(row)+b'\n'
                    require(len(encoded)<=limit,'IMPORT_SOURCE_ROW_SIZE')
                    if len(buffer)+len(encoded)>limit:
                        flush();parents[jid]=parent
                        segments[jid]={'first_job_row':emitted,'rows':0}
                    buffer.extend(encoded);body_refs[response['body']['path']]=response['body']
                    segments[jid]['rows']+=1;emitted+=1
        # Retain parseable empty response bodies too; malformed bytes remain in
        # the outer terminal graph and must not be disguised as empty success.
        for _,response in related:
            try:page(store.object_read(response['body']))
            except ImportError:continue
            body_refs[response['body']['path']]=response['body']
        job_index.append({'global_job_ordinal':ordinal,'canonical_job_id':jid,
                          'source_plan_job_id':job['relation']['job_id'],
                          'population_record_id':job['relation']['population_record_id'],
                          **({'source_record_ids':job['relation']['source_record_ids']} if all_adjusted else {}),
                          **({'source_target_id':job['relation']['source_target_id']}
                             if store.raw_profile=='all-adjusted-selected' else {}),
                          'request':job['request'],'transport_state':raw_state,'reason':state['reason'],
                          'first_partition':first_part,'last_partition':part,'rows':emitted})
    flush()
    emit('job-status-index.ndjson',b''.join(canonical(r)+b'\n' for r in job_index))
    index={'schema':'polar.vendor-all-adjusted-source-collection/1' if all_adjusted else 'polar.raw-sip-source-collection/1','objects':objects,'packets':packets,
           'source_plan_id':plan['plan_id'],'scope_sha256':plan['unit']['scope_sha256'],
           'prior_counter_lineage':plan['unit']['lineage'],'normalized_rows':sum(r['rows'] for r in job_index),
           'jobs':len(job_index),'source_reference_encoding':'bars/<literalAlias>',
           'fitness':'NOT_ASSESSED'}
    store.write_raw(prefix+'/source/content-manifest.json',canonical(index)+b'\n')
    return prefix+'/source/content-manifest.json'
