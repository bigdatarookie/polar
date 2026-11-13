"""Invented source correspondence only; no retained source is opened."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from polar.history_bundle import canonical,sha,verify_files,HistoryError
from polar.history_retained import assemble,RAW,ADJUSTED
from polar.history_store import HistoryStore


def fixture(adjusted=False):
    body=b'{"bars":{"AAA":[{"t":"2024-01-02T05:00:00Z","o":10.00,"h":12.0,"l":9.0,"c":11.00,"v":2.5},{"t":"2024-01-03T05:00:00Z","o":11.0,"h":13.0,"l":10.0,"c":12.0,"v":4}]}}'
    bh=sha(body);ih='a'*64;basis=ADJUSTED if adjusted else RAW;rows=[];claims=[]
    for i,(day,o,h,l,c,v) in enumerate([('2024-01-02','10.00','12.0','9.0','11.00','2.5'),('2024-01-03','11.0','13.0','10.0','12.0','4')]):
        rows.append({'source_symbol':'AAA','session_date':day,'aggregation_label':day+'T05:00:00Z','open':o,'high':h,'low':l,'close':c,'volume':v,'source_body_sha256':bh,'source_array_pointer':'/bars/AAA/'+str(i),'source_row_index':i,'event_at':None,'published_at':None,'historical_available_at':None,'source_revision':None,'source_status':'OBSERVED'})
        claims.append({'date':day,'source_body_sha256':bh,'source_row_index':i,'normalized_line_1based':i+1,'normalized_line_sha256':'d'*64})
    row_raw=b''.join(canonical(r)+b'\n' for r in rows);rh=sha(row_raw)
    s={'research_input_sha256':ih,'source_symbol':'AAA','rows':2,'first_date':'2024-01-02','last_date':'2024-01-03','row_bindings':claims,'row_member':{'sha256':rh,'bytes':len(row_raw)},'ohlc_basis':basis['ohlc_basis'],'adjusted_close_basis':None,'volume_basis':basis['volume_basis']}
    metadata={}
    def pin_meta(raw):
        metadata[sha(raw)]=raw;return {'sha256':sha(raw),'bytes':len(raw)}
    if adjusted:
        request={'adjustment':'all','feed':'sip','symbols':'AAA','timeframe':'1Day','currency':'USD','endpoint':'https://data.alpaca.markets/v2/stocks/bars'}
        parent=canonical({'canonical_job_id':'invented-job','request':request})+b'\n'
        collection=canonical({'objects':{'parts/00000/parent-coverage-ledger.ndjson':pin_meta(parent),
                                        'parts/00000/objects/'+bh+'.json':{'sha256':bh,'bytes':len(body)}}})
        s.update(source_collection=pin_meta(collection),canonical_job_id='invented-job',request=request)
    else:
        receipt=canonical([{'sha256':bh,'symbol':'AAA','bytes':len(body),'http_status':200,
             'request_url':'https://data.alpaca.markets/v2/stocks/bars?adjustment=raw&feed=sip&symbols=AAA&timeframe=1Day&currency=USD'}])
        s['source_receipts']=pin_meta(receipt)
    candidate={'schema':'polar.retained-orders-history-source-candidate/1','series':[s],'source_objects':[{'sha256':bh,'bytes':len(body)}],'limits':['Invented test-only private display data; no financial use']}
    raw=canonical(candidate);evidence={'schema':'polar.saved-orders-history-correspondence/1','candidate':{'sha256':sha(raw),'bytes':len(raw)},'series':[s]}
    return raw,canonical(evidence),{rh:row_raw},{bh:body},ih,metadata


def built(adjusted=False):
    args=fixture(adjusted);files,summary=assemble(*args[:5],metadata=args[5]);return files,summary,args


@pytest.mark.parametrize('adjusted',[False,True])
def test_exact_source_tokens_null_adjusted_close_basis_and_store_replay(tmp_path,adjusted):
    files,s,args=built(adjusted);bundle=verify_files(files,s['manifest_sha256'])
    assert s['basis']==(ADJUSTED if adjusted else RAW) and s['row_count']==2
    assert bundle.summary==s and s['calendar_status']=='UNVERIFIED'
    row=json.loads(files['bars/hist-sip-AAA.ndjson'].splitlines()[0])
    assert row['open']=='10.00' and row['close']=='11.00' and row['volume']=='2.5' and row['adjusted_close'] is None
    assert s['research_bindings'][0]['input_sha256']==args[4] and s['research_bindings'][0]['native_symbol']=='AAA'
    assert s['import_started_at'] is s['import_completed_at'] is None
    store=HistoryStore(tmp_path,128*1024**2)
    with store.locked():pub=store.publish_locked(bundle)
    assert store.verify(bundle.revision,bundle.receipt_id,pub).summary==s
    before={str(p):sha(p.read_bytes()) for p in tmp_path.rglob('*') if p.is_file()}
    with store.locked():assert store.publish_locked(bundle)==pub
    assert before=={str(p):sha(p.read_bytes()) for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mutation',['token','model100','date','pointer','row_index_bool','duplicate','clock','adjusted_close','symbol','negative','nan','source_hash','selection','evidence','basis','row_count_bool'])
def test_rehashed_staging_cannot_forge_source_correspondence(mutation):
    candidate,evidence,rows,bodies,ih,metadata=fixture(True);c=json.loads(candidate);e=json.loads(evidence);rh=next(iter(rows));rs=[json.loads(v) for v in rows[rh].splitlines()]
    if mutation=='token':rs[0]['open']='10.0'
    elif mutation=='model100':rs[0]['close']='1100'
    elif mutation=='date':rs[0]['session_date']='2024-01-01'
    elif mutation=='pointer':rs[0]['source_array_pointer']='/bars/OTHER/0'
    elif mutation=='row_index_bool':rs[0]['source_row_index']=False
    elif mutation=='duplicate':rs[1]=deepcopy(rs[0])
    elif mutation=='clock':rs[0]['historical_available_at']='2024-01-02T06:00:00Z'
    elif mutation=='adjusted_close':rs[0]['adjusted_close']=rs[0]['close']
    elif mutation=='symbol':rs[0]['source_symbol']='OTHER'
    elif mutation=='negative':rs[0]['volume']='-1'
    elif mutation=='nan':rs[0]['open']='NaN'
    elif mutation=='source_hash':rs[0]['source_body_sha256']='b'*64
    elif mutation=='selection':c['series'][0]['row_bindings'][0]['source_row_index']=1
    elif mutation=='evidence':e['candidate']['sha256']='b'*64
    elif mutation=='basis':c['series'][0]['ohlc_basis']='VENDOR_RAW_UNADJUSTED'
    else:c['series'][0]['rows']=True
    raw=b''.join(canonical(r)+b'\n' for r in rs);newrh=sha(raw);c['series'][0]['row_member']={'sha256':newrh,'bytes':len(raw)};newc=canonical(c)
    if mutation!='evidence':e['candidate']={'sha256':sha(newc),'bytes':len(newc)}
    e['series']=c['series']
    with pytest.raises(HistoryError):assemble(newc,canonical(e),{newrh:raw},bodies,ih,metadata=metadata)


@pytest.mark.parametrize('mutation',['bar','extra','manifest','receipt','source'])
def test_publication_rejects_changed_or_extra_material(mutation):
    files,s,_=built()
    if mutation=='bar':files['bars/hist-sip-AAA.ndjson']=files['bars/hist-sip-AAA.ndjson'].replace(b'10.00',b'10.01')
    elif mutation=='extra':files['unexpected.json']=b'{}'
    elif mutation=='manifest':files['bundle-manifest.json']+=b' '
    elif mutation=='receipt':files['import-receipt.json']+=b' '
    else:
        p=next(p for p in files if p.startswith('sources/'));files[p]+=b' '
    with pytest.raises(HistoryError):verify_files(files,s['manifest_sha256'])


def test_registered_navigation_requires_exact_input_alias_and_unique_verified_revision(monkeypatch):
    from polar.history_registry import HistoryRegistry
    from polar.config import Settings
    files,s,_=built();bundle=verify_files(files,s['manifest_sha256'])
    class DB:
        rows=[]
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def execute(self,query,params):return self
        def fetchall(self):return self.rows
    db=DB();r=HistoryRegistry(Settings('unused',Path('/unused')))
    monkeypatch.setattr(r.legacy,'check',lambda:None);monkeypatch.setattr(r.legacy,'connect',lambda:db);monkeypatch.setattr(r,'_check',lambda _:None)
    monkeypatch.setattr(r,'load_revision',lambda dataset,rev:(s,bundle))
    assert r.research_navigation('a'*64,'AAA') is None
    db.rows=[{'dataset_id':s['dataset_id'],'revision':s['dataset_revision']}]
    n=r.research_navigation('a'*64,'AAA');assert n['instrument_id']=='hist-sip-AAA' and n['dataset_revision']==s['dataset_revision']
    with pytest.raises(HistoryError):r.research_navigation('b'*64,'AAA')
    db.rows*=2;assert r.research_navigation('a'*64,'AAA') is None


@pytest.mark.parametrize('adjusted',[False,True])
def test_basis_label_must_match_original_capture_metadata(adjusted):
    c,e,rows,bodies,ih,metadata=fixture(adjusted)
    data=json.loads(c);proof=json.loads(e)
    s=data['series'][0]
    if adjusted:
        # Keep original collection-parent request intact; fake caller label only.
        s['request']['adjustment']='raw'
    else:
        pin=s['source_receipts'];old=json.loads(metadata[pin['sha256']]);old[0]['request_url']=old[0]['request_url'].replace('adjustment=raw','adjustment=all')
        raw=canonical(old);metadata={sha(raw):raw};s['source_receipts']={'sha256':sha(raw),'bytes':len(raw)}
    raw=canonical(data);proof['candidate']={'sha256':sha(raw),'bytes':len(raw)};proof['series']=data['series']
    with pytest.raises(HistoryError):assemble(raw,canonical(proof),rows,bodies,ih,metadata=metadata)


@pytest.mark.parametrize('kind',['missing_source','bad_metadata_hash','bad_source_type'])
def test_malformed_source_fails_with_stable_history_error(kind):
    c,e,rows,bodies,ih,metadata=fixture(True)
    if kind=='missing_source':bodies={}
    elif kind=='bad_metadata_hash':metadata={k:v+b' ' for k,v in metadata.items()}
    else:bodies={k:None for k in bodies}
    with pytest.raises(HistoryError):assemble(c,e,rows,bodies,ih,metadata=metadata)


@pytest.mark.parametrize('adjusted',[False,True])
def test_existing_history_bars_api_preserves_source_basis_and_missing_adjusted_close(tmp_path,adjusted):
    from types import SimpleNamespace
    from polar.history_queries import HistoryQueries
    from polar.history_cursor import CursorCodec
    files,s,_=built(adjusted);bundle=verify_files(files,s['manifest_sha256'])
    registry=SimpleNamespace(store=SimpleNamespace(root=tmp_path),load_revision=lambda *a:(s,bundle))
    q=HistoryQueries(registry,None);q._codec=CursorCodec(b'invented-cursor-key-32-bytes......'[:32])
    first=q.bars(s['dataset_id'],s['dataset_revision'],'hist-sip-AAA','2024-01-02','2024-01-04',limit='1')
    assert first['basis']==s['basis'] and first['rows'][0]['close']=='11.00' and first['rows'][0]['adjusted_close'] is None
    assert first['next_cursor'] and not first['window_complete']
    second=q.bars(s['dataset_id'],s['dataset_revision'],'hist-sip-AAA','2024-01-02','2024-01-04',limit='1',cursor=first['next_cursor'])
    assert second['rows'][0]['session_date']=='2024-01-03' and second['window_complete'] and second['basis']==first['basis']
    assert second['coverage']['calendar_status']=='UNVERIFIED'
