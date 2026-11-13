"""Retained SIP display-source extension of the existing history bundle contract.

No fetch, model-price rescale, research execution or inferred adjusted close.
Registration still uses HistoryRegistry/HistoryStore and immutable publications.
"""
from decimal import Decimal
import re
from urllib.parse import urlsplit, parse_qs
from .history_bundle import (canonical, decode, sha, require, hex_hash, identifier,
                             label, numeric, Token, VerifiedBundle, MAX_FILE, MAX_BUNDLE, HistoryError)

FORMAT = 'polar.retained-sip-history-bundle/1'
RAW = {'ohlc_basis':'VENDOR_RAW_UNADJUSTED','adjusted_close_basis':'NOT_SUPPLIED',
       'volume_basis':'VENDOR_RAW_RESPONSE_UNITS','price_unit':'USD/vendor raw reference unit',
       'volume_unit':'vendor raw response units'}
ADJUSTED = {'ohlc_basis':'VENDOR_ALL_ADJUSTED_REFERENCE','adjusted_close_basis':'NOT_SUPPLIED',
       'volume_basis':'VENDOR_RESPONSE_UNITS_ADJUSTMENT_ALL_NOT_RAW_SHARES',
       'price_unit':'USD/vendor all-adjusted reference unit','volume_unit':'vendor all-adjusted response units'}
SOURCE_FIELDS = {'aggregation_label','close','event_at','high','historical_available_at','low','open',
                 'published_at','session_date','source_array_pointer','source_body_sha256','source_revision',
                 'source_row_index','source_status','source_symbol','volume'}


def input_hash(series):
    return hex_hash(series.get('research_input_sha256') or series['research_input']['sha256'])


def _assemble(candidate_raw, evidence_raw, rows, bodies, research_input_sha256, metadata):
    """Pure deterministic assembly over explicitly supplied, pinned retained bytes.

    rows/bodies are maps keyed by content SHA. Original source qualification is
    attributed to the selected DE evidence, not inferred from ticker equality.
    No file/provider/store reads or writes occur in this function.
    """
    require(type(candidate_raw) is bytes and type(evidence_raw) is bytes and
            len(candidate_raw)<=MAX_FILE and len(evidence_raw)<=MAX_FILE)
    candidate=decode(candidate_raw);evidence=decode(evidence_raw);ih=hex_hash(research_input_sha256)
    require(candidate['schema']=='polar.retained-orders-history-source-candidate/1' and
            evidence['schema']=='polar.saved-orders-history-correspondence/1')
    require(type(evidence['candidate']['bytes']) is int and evidence['candidate']['bytes']==len(candidate_raw) and
            evidence['candidate']['sha256']==sha(candidate_raw),'HISTORY_RETAINED_EVIDENCE_HASH')
    selected=[s for s in candidate['series'] if input_hash(s)==ih]
    require(1<=len(selected)<=4 and len({s['source_symbol'] for s in selected})==len(selected),
            'HISTORY_RETAINED_SELECTION')
    selected.sort(key=lambda s:s['source_symbol'])
    basis=RAW if selected[0]['ohlc_basis']==RAW['ohlc_basis'] else ADJUSTED
    require(all(s['ohlc_basis']==basis['ohlc_basis'] and s['volume_basis']==basis['volume_basis'] and
                s['adjusted_close_basis'] is None for s in selected),'HISTORY_RETAINED_BASIS')
    dataset=identifier('history-sip-'+ih[:24]);assets=[];links=[]
    files={'source-candidate.json':candidate_raw,'source-evidence.json':evidence_raw}
    evidence_series={s['source_symbol']:s for s in evidence['series'] if input_hash(s)==ih}
    source_pins={v['sha256']:v for v in candidate['source_objects']}
    source_cache={}
    def meta(pin):
        mh=hex_hash(pin['sha256']);raw=metadata[mh]
        require(type(raw) is bytes and type(pin['bytes']) is int and len(raw)==pin['bytes'] and sha(raw)==mh and len(raw)<=MAX_FILE,
                'HISTORY_RETAINED_METADATA_HASH')
        files['metadata/'+mh+'.json']=raw
        return raw
    for s in selected:
        symbol=s['source_symbol'];require(type(symbol) is str and re.fullmatch('[A-Z][A-Z0-9.]{0,15}',symbol))
        iid=identifier('hist-sip-'+symbol);pin=s['row_member'];rh=hex_hash(pin['sha256'])
        require(symbol in evidence_series and canonical(s['row_member'])==canonical(evidence_series[symbol]['row_member']),
                'HISTORY_RETAINED_EVIDENCE_SELECTION')
        if basis==ADJUSTED:
            collection=decode(meta(s['source_collection']));objects=collection['objects']
            parents=[]
            for path,mp in objects.items():
                if path.endswith('/parent-coverage-ledger.ndjson'):
                    parents.extend(decode(v) for v in meta(mp).splitlines())
            parent=[v for v in parents if v['canonical_job_id']==s['canonical_job_id']]
            require(len(parent)==1 and canonical(parent[0]['request'])==canonical(s['request']),
                    'HISTORY_RETAINED_REQUEST_BINDING')
            req=s['request'];require(req['adjustment']=='all' and req['feed']=='sip' and req['timeframe']=='1Day' and req['symbols']==symbol and req.get('currency')=='USD' and
                                     req.get('endpoint')=='https://data.alpaca.markets/v2/stocks/bars',
                                     'HISTORY_RETAINED_REQUEST_BASIS')
            source_receipts=None
        else:
            source_receipts=decode(meta(s['source_receipts']));require(type(source_receipts) is list)
            objects=None
        raw=rows[rh];require(type(raw) is bytes and type(pin['bytes']) is int and len(raw)==pin['bytes'] and sha(raw)==rh,
                             'HISTORY_RETAINED_ROWS_HASH')
        files['selected/'+rh+'.ndjson']=raw
        lines=raw.splitlines();require(type(s['rows']) is int and 1<=len(lines)==s['rows']<=5000)
        census=s['row_bindings'];require(len(census)==len(lines),'HISTORY_RETAINED_SELECTION_COUNT')
        admitted=[];previous=None
        for line,claim in zip(lines,census):
            row=decode(line);require(type(row) is dict and set(row)==SOURCE_FIELDS,'HISTORY_RETAINED_ROW_SCHEMA')
            day=label(row['session_date']).isoformat();idx=row['source_row_index'];bh=hex_hash(row['source_body_sha256'])
            require(previous is None or previous<day,'HISTORY_RETAINED_DATE_ORDER');previous=day
            require(row['source_symbol']==symbol and type(idx) is int and idx>=0 and row['source_status']=='OBSERVED' and
                    all(row[k] is None for k in ['event_at','published_at','historical_available_at','source_revision']))
            require(claim['date']==day and claim['source_body_sha256']==bh and
                    type(claim['source_row_index']) is int and claim['source_row_index']==idx,
                    'HISTORY_RETAINED_SELECTED_POINTER')
            require(row['source_array_pointer']=='/bars/'+symbol+'/'+str(idx),'HISTORY_RETAINED_POINTER')
            if bh not in source_cache:
                body=bodies[bh];bp=source_pins[bh]
                require(type(body) is bytes and type(bp['bytes']) is int and len(body)==bp['bytes'] and
                        sha(body)==bh and len(body)<=MAX_FILE,'HISTORY_RETAINED_BODY_HASH')
                source_cache[bh]=decode(body,source=True);files['sources/'+bh+'.json']=body
            if objects is not None:
                refs=[v for p,v in objects.items() if p.endswith('/objects/'+bh+'.json')]
                require(len(refs)==1 and refs[0]['sha256']==bh and refs[0]['bytes']==len(bodies[bh]),
                        'HISTORY_RETAINED_COLLECTION_BODY')
            else:
                matches=[v for v in source_receipts if v['sha256']==bh and v['symbol']==symbol]
                require(len(matches)==1 and matches[0]['http_status']==200 and matches[0]['bytes']==len(bodies[bh]),
                        'HISTORY_RETAINED_RAW_RECEIPT')
                url=urlsplit(matches[0]['request_url']);query=parse_qs(url.query)
                require(url.scheme=='https' and url.hostname=='data.alpaca.markets' and url.path=='/v2/stocks/bars' and
                        all(query.get(k)==[v] for k,v in [('adjustment','raw'),('feed','sip'),('symbols',symbol),('timeframe','1Day'),('currency','USD')]),
                        'HISTORY_RETAINED_REQUEST_BASIS')
            original=source_cache[bh]['bars'][symbol][idx]
            require(original['t']==row['aggregation_label'] and row['aggregation_label'][:10]==day,
                    'HISTORY_RETAINED_SOURCE_DATE')
            values={}
            for target,key in [('open','o'),('high','h'),('low','l'),('close','c'),('volume','v')]:
                require(type(original[key]) is Token and type(row[target]) is str and row[target]==str(original[key]),
                        'HISTORY_RETAINED_SOURCE_TOKEN')
                if target!='volume':values[target]=numeric(row[target],target)
                else:
                    # Adjustment-all vendor response volume can be fractional.
                    require(len(row[target])<=40 and re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?',row[target]))
                    v=Decimal(row[target]);require(v.is_finite() and 0<=v<=Decimal('1e18') and v.as_tuple().exponent>=-18)
            require(values['low']<=min(values['open'],values['close'])<=max(values['open'],values['close'])<=values['high'],
                    'HISTORY_RETAINED_OHLC_RANGE')
            admitted.append({**row,'instrument_id':iid,'adjusted_close':None,
                             'source_snapshot_id':'raw-'+bh,'raw_object_sha256':bh})
        require(admitted[0]['session_date']==s['first_date'] and admitted[-1]['session_date']==s['last_date'])
        files['bars/'+iid+'.ndjson']=b''.join(canonical(v)+b'\n' for v in admitted)
        asset={'instrument_id':iid,'source_symbol':symbol,'instrument_type':'DECLARED_SOURCE_SYMBOL',
               'currency':'USD','effective_from':None,'effective_until':None,'mapping_status':'DECLARED_CURRENT_ONLY',
               'evidence_sha256':sha(evidence_raw),'row_count':len(admitted),'raw_rows':len(admitted),
               'quarantined_rows':0,'duplicate_keys':0,'duplicate_rows':0,'quarantine_reason_counts':{},
               'chart_fitness':'READY_WITH_LIMITS','first_date':s['first_date'],'last_date':s['last_date'],
               'expected_sessions':None,'calendar_status':'UNVERIFIED','qualified_ten_year_continuity':'UNVERIFIED'}
        assets.append(asset)
        links.append({'input_sha256':ih,'native_symbol':symbol,'instrument_id':iid,'source_symbol':symbol,
                      'source_member_sha256':rh,'evidence_sha256':sha(evidence_raw),
                      'basis_relation':basis['ohlc_basis']+' source candles; saved model fills use their own declared units. '
                                       'Dates only; no price/share equivalence, permanent security identity or PIT claim.'})
    content={'format':FORMAT,'dataset_id':dataset,'research_input_sha256':ih,'basis':basis,
             'source_candidate_sha256':sha(candidate_raw),'source_evidence_sha256':sha(evidence_raw),
             'objects':{k:{'sha256':sha(v),'bytes':len(v)} for k,v in sorted(files.items())}}
    revision='histrev-'+sha(canonical(content))
    receipt={'schema':'polar.retained-history-import-receipt/1','dataset_revision':revision,
             'origin':'RETAINED_CONTENT_PROJECTION_NOT_NEW_CAPTURE','source_evidence_sha256':sha(evidence_raw)}
    receipt_raw=canonical(receipt);receipt_id=sha(receipt_raw)
    files['import-receipt.json']=receipt_raw
    files['bundle-manifest.json']=canonical({'dataset_id':dataset,'dataset_revision':revision,'content':content,
                                            'import_receipt_sha256':receipt_id})
    require(len(files)<=64 and all(len(v)<=MAX_FILE for v in files.values()) and sum(map(len,files.values()))<=MAX_BUNDLE,
            'HISTORY_BUNDLE_LIMIT')
    summary={'schema_version':'polar.history-revision/1','dataset_id':dataset,'dataset_revision':revision,
             'import_receipt_id':receipt_id,'manifest_sha256':sha(files['bundle-manifest.json']),'basis':basis,
             'instruments':assets,'row_count':sum(a['row_count'] for a in assets),
             'raw_rows':sum(a['raw_rows'] for a in assets),'quarantined_rows':0,'calendar_status':'UNVERIFIED',
             'fitness':{'rights_status':'ADMITTED','structural_status':'VALID','chart_fitness':'READY_WITH_LIMITS',
                        'retrospective_analysis_fitness':'NOT_ASSESSED','causal_PIT_fitness':'INSUFFICIENT_EVIDENCE',
                        'financial_evaluation':'NOT_RUN'},'rights_scope':'OWNER_ONLY_PRIVATE_NONCOMMERCIAL',
             'import_started_at':None,'import_completed_at':None,'research_bindings':links,
             'limitations':['Retained source display projection, not a new capture or research result.',
                             'Declared current symbol only; historical availability and permanent security/PIT identity unverified.',
                             'No separate adjusted-close series is supplied; source and saved execution unit bases remain distinct.'],
             'source_staging_limits':candidate['limits']}
    return files,summary


def assemble(candidate_raw, evidence_raw, rows, bodies, research_input_sha256, *, metadata=None):
    try:
        return _assemble(candidate_raw,evidence_raw,rows,bodies,research_input_sha256,metadata or {})
    except HistoryError:
        raise
    except (KeyError,TypeError,IndexError,AttributeError,OverflowError,ValueError,ArithmeticError):
        raise HistoryError('HISTORY_INVALID_RETAINED_SOURCE') from None


def verify(files,expected_manifest_hash):
    manifest=decode(files['bundle-manifest.json']);ih=manifest['content']['research_input_sha256']
    rows={p.split('/')[1][:-7]:v for p,v in files.items() if re.fullmatch('selected/[a-f0-9]{64}\.ndjson',p)}
    bodies={p.split('/')[1][:-5]:v for p,v in files.items() if re.fullmatch('sources/[a-f0-9]{64}\.json',p)}
    metadata={p.split('/')[1][:-5]:v for p,v in files.items() if re.fullmatch('metadata/[a-f0-9]{64}\.json',p)}
    expected,summary=assemble(files['source-candidate.json'],files['source-evidence.json'],rows,bodies,ih,metadata=metadata)
    require(set(files)==set(expected) and all(files[p]==raw for p,raw in expected.items()),'HISTORY_RETAINED_CONTENT_MISMATCH')
    require(summary['manifest_sha256']==expected_manifest_hash,'HISTORY_MANIFEST_HASH')
    content=set(files)-{'bundle-manifest.json','import-receipt.json'}
    return VerifiedBundle(summary['dataset_id'],summary['dataset_revision'],summary['import_receipt_id'],
                          expected_manifest_hash,files,frozenset(content),summary)
