"""Inert fixed-profile admission. Called only after an authoritative START."""
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import json
import re

from .history_bundle import read_file, safe_root
from .capability_contract import (require, exact, decode, sha, canonical, validate, ns, microtime,
    MAX_BYTES, METHODS, SYMBOLS, TOKENS, D, I, MAPPING, OPEN_DATES, CLOSE_DATES, NumberToken, money)
from .capability_profile import identity, decimal_fraction


def source_clock(value):
    require(type(value) is str and len(value)<=40
            and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)',value),
            'CLOCK_ORDER')
    try: instant=datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)
    except ValueError:
        require(False,'CLOCK_ORDER')
    return instant.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def checked_ref(ref):
    exact(ref,('path','record_token','sha256'),'BINDING_MISMATCH')
    validate({'record_token':ref['record_token'],'sha256':ref['sha256']},'hash_ref')
    path=Path(ref['path'])
    require(path.is_absolute() and path==path.resolve(),'INPUT_INTEGRITY')
    return path


def read_ref(ref):
    path=checked_ref(ref)
    body=read_file(safe_root(path.parent),path.name,MAX_BYTES)
    require(sha(body)==ref['sha256'],'INPUT_INTEGRITY')
    return body


def semantic_ref(ref):
    return {k:ref[k] for k in ('record_token','sha256')}


def source_json(value):
    """Exact source JSON preimage; numeric lexemes are emitted as numbers."""
    if type(value) is NumberToken:
        decimal_fraction(value)  # lexical finite/domain bound; no binary conversion
        return str(value)
    if type(value) is dict:
        return '{'+','.join(json.dumps(k,ensure_ascii=True)+':'+source_json(v)
                            for k,v in sorted(value.items()))+'}'
    if type(value) is list:
        return '['+','.join(source_json(v) for v in value)+']'
    require(type(value) in (str,int,bool,type(None)),'INPUT_INTEGRITY')
    return json.dumps(value,separators=(',',':'),ensure_ascii=True,allow_nan=False)


class AdmittedInputs:
    def __init__(self,config):
        self.config=config
        self.refs=list(config['input_refs'].values())+config['auxiliary_refs']
        self.by_path={}
        self.cache={}
        self.lineage={}
        for ref in self.refs:
            path=str(checked_ref(ref))
            require(path not in self.by_path,'INPUT_INTEGRITY')
            self.by_path[path]=ref

    def member(self,path):
        require(type(path) is str and path in self.by_path,'INPUT_INTEGRITY')
        if path not in self.cache:
            self.cache[path]=read_ref(self.by_path[path])
        return self.cache[path]

    def reference(self,role,path,expected=None):
        body=self.member(path);ref=self.by_path[path]
        require(expected is None or sha(body)==expected,'INPUT_INTEGRITY')
        row={'role':role,**semantic_ref(ref)}
        validate(row,'lineage_ref')
        self.lineage[(role,row['record_token'],row['sha256'])]=row
        return row

    def line(self,path,ordinal,expected,role):
        body=self.member(path)
        require(type(ordinal) is int and 1<=ordinal<=1000000,'INPUT_INTEGRITY')
        lines=body.splitlines(keepends=True)
        require(ordinal<=len(lines) and sha(lines[ordinal-1])==expected,'INPUT_INTEGRITY')
        base=self.reference(role,path)
        result={'role':role,'record_token':base['record_token']+'/line/'+str(ordinal),'sha256':expected}
        validate(result,'lineage_ref')
        self.lineage[(role,result['record_token'],expected)]=result
        return decode(lines[ordinal-1],inert_numbers=True),result

    def pointer(self,pointer,members,role):
        require(type(pointer) is dict and pointer.get('member') in members,'INPUT_INTEGRITY')
        source=members[pointer['member']]
        self.reference(role,source['path'],source['sha256'])
        return self.line(source['path'],pointer['line_1based'],pointer['raw_line_sha256'],role)

    def subobject(self,ref,members,role):
        require(ref['member'] in members,'INPUT_INTEGRITY')
        file=members[ref['member']]
        self.reference(role.replace('_subobject','_file'),file['path'],file['sha256'])
        obj=decode(self.member(file['path']),inert_numbers=True)
        require(type(obj) is dict and ref['json_key'] in obj,'INPUT_INTEGRITY')
        body=source_json(obj[ref['json_key']]).encode()
        require(sha(body)==ref['canonical_subobject_sha256'],'INPUT_INTEGRITY')
        result={'role':role,'record_token':self.by_path[file['path']]['record_token']+'/'+ref['json_key'],
                'sha256':sha(body)}
        validate(result,'lineage_ref')
        self.lineage[(role,result['record_token'],result['sha256'])]=result
        return result

    def load(self):
        refs=self.config['input_refs']
        seal=decode(read_ref(refs['score_seal']),inert_numbers=True)
        readiness=decode(read_ref(refs['capsule_readiness']),inert_numbers=True)
        require(seal.get('schema')=='polar.hyp007-five-method-score-capability/1'
                and readiness.get('schema')=='polar.hyp007-fixed-retained-input-capsule-inventory/1',
                'INPUT_INTEGRITY')
        require(source_clock(readiness['D'])==D and source_clock(readiness['I_D'])==I
                and source_clock(seal['fixed_D'])==D,'CLOCK_ORDER')
        # Manifest exact bytes are pinned independently of source member decoding.
        for key,member_key in (('score_manifest','score_seal'),('capsule_manifest','capsule_readiness')):
            manifest=decode(read_ref(refs[key]),inert_numbers=True)
            require(type(manifest.get('files')) is dict,'INPUT_INTEGRITY')
            wanted=refs[member_key]
            matches=[r for name,r in manifest['files'].items()
                     if name==Path(wanted['path']).name and r.get('sha256')==wanted['sha256']]
            require(len(matches)==1 and matches[0]['bytes']==len(read_ref(wanted)),'INPUT_INTEGRITY')
        rows=seal['rows']
        require(type(rows) is list and len(rows)==4 and {r['key'] for r in rows}==set(TOKENS),
                'SCORE_COHORT_MISMATCH')
        members=seal['source_members']
        require(type(members) is dict and len(members)<=128,'INPUT_INTEGRITY')
        semantic_rows=[];ordered=[]
        for symbol,token in zip(SYMBOLS,TOKENS):
            found=[r for r in rows if r['key']==token]
            require(len(found)==1,'SCORE_COHORT_MISMATCH')
            row=found[0]
            require(row['source_witness']==symbol and set(row['scores'])==set(METHODS),'SCORE_COHORT_MISMATCH')
            require(source_clock(row['D'])==D and source_clock(row['I_D'])==I
                    and ns(source_clock(row['K']))<=ns(D),'CLOCK_ORDER')
            row=dict(row,D=D,I_D=I,K=source_clock(row['K']))
            raw_pointer=row['scores'][METHODS[0]]['source_pointer']
            self.reference('source_record',raw_pointer['path'],raw_pointer['sha256'])
            raw_packet=decode(self.member(raw_pointer['path']),inert_numbers=True)
            feature_members=raw_packet['source_members']
            require(type(feature_members) is dict and len(feature_members)<=128,'INPUT_INTEGRITY')
            feature,feature_ref=self.pointer(row['feature_source_pointer'],feature_members,'feature_anchor')
            require(feature['key']==token and source_clock(feature['D'])==D
                    and source_clock(feature['packet']['K'])==row['K'],'CLOCK_ORDER')
            roster,_=self.pointer(row['roster_pointer'],members,'qualification')
            require(roster['key']==token and source_clock(roster['D'])==D
                    and source_clock(roster['I_D'])==I
                    and ns(source_clock(row['A_close_proxy']))<=ns(D)
                    and ns(I)<ns(source_clock(row['O1'])),'CLOCK_ORDER')
            self.reference('feature_anchor',row['feature_ancestry_pins'],row['feature_ancestry_sha256'])
            score_refs=[];readiness_refs=[]
            for method in METHODS:
                entry=row['scores'][method]
                lineage=[]
                if method in METHODS[:2]:
                    p=entry['source_pointer']
                    require(p['key']==token,'INPUT_INTEGRITY')
                    lineage.append(self.reference('source_record',p['path'],p['sha256']))
                    packet=decode(self.member(p['path']),inert_numbers=True)
                    selected=[r for r in packet['rows'] if r['key']==token]
                    require(len(selected)==1 and p['score_identity']==method,'INPUT_INTEGRITY')
                    original=selected[0]['scores'][method]
                    require(all(original[k]==entry[k] for k in ('value','binary64_bits_be','binary64_hex')),
                            'SCORE_REPRESENTATION')
                else:
                    p=entry['source_pointer']
                    require(p['key']==token and p['model']==method,'INPUT_INTEGRITY')
                    prediction,prediction_ref=self.pointer(p,members,'source_record')
                    require(prediction['key']==token and prediction['fold']==p['fold']
                            and prediction['model']==method
                            and str(prediction['prediction'])==entry['original_json_numeric_token'],
                            'SCORE_REPRESENTATION')
                    lineage.append(prediction_ref)
                    version=entry['model_transform_version']
                    lineage.append(self.subobject(version['model_ref'],members,'model_subobject'))
                    lineage.append(self.subobject(version['transform_ref'],members,'transform_subobject'))
                    fit_ref=version['fit_slot_ref']
                    require(fit_ref['member'] in members and type(fit_ref['ordinal']) is int
                            and fit_ref['ordinal']>=0,'INPUT_INTEGRITY')
                    fit_file=members[fit_ref['member']]
                    lineage.append(self.reference('fit_receipt',fit_file['path'],fit_file['sha256']))
                    slots=decode(self.member(fit_file['path']),inert_numbers=True)
                    found=[slot for slot in slots if slot['ordinal']==fit_ref['ordinal']]
                    require(len(found)==1 and found[0]['model']==method
                            and found[0]['fold']==p['fold'] and found[0]['status']=='SUCCESS'
                            and found[0]['finish']['status']=='SUCCESS'
                            and found[0]['finish']['model_sha256']==version['model_ref']['canonical_subobject_sha256'],
                            'INPUT_INTEGRITY')
                    availability=version['modeled_availability']
                    F=source_clock(availability['F']);ready=source_clock(availability['ready'])
                    require(availability['delay_seconds']==900 and ns(ready)==ns(F)+900*10**9
                            and ns(ready)<=ns(D),'CLOCK_ORDER')
                    readiness_refs.extend(lineage)
                score_refs.append({'method_id':method,'binary64_bits_be':entry['binary64_bits_be'],
                    'binary64_hex':entry['binary64_hex'],'lineage_refs':sorted(lineage,
                        key=lambda r:(r['role'],r['record_token'],r['sha256']))})
            # The readiness metadata itself is immutable in the complete seal.
            ready_ref=semantic_ref(refs['score_seal'])
            semantic_rows.append({**identity(symbol),'feature_anchor_ref':semantic_ref(feature_ref),
                'feature_K':row['K'],'model_readiness_ref':ready_ref,'scores':score_refs})
            ordered.append(row)
        inventory_path=str(Path(refs['capsule_readiness']['path']).parent/'raw-operand-inventory.json')
        require(inventory_path in self.by_path,'INPUT_INTEGRITY')
        inventory=decode(self.member(inventory_path),inert_numbers=True)
        require(type(inventory) is list and len(inventory)<=128,'INPUT_INTEGRITY')
        index={}
        for row in inventory:
            key=(row['source_witness'],row['reference_date'])
            require(key not in index,'INPUT_INTEGRITY');index[key]=row
        observations=[]
        for field,dates in (('o',OPEN_DATES),('c',CLOSE_DATES)):
            for day in dates:
                Q=ns(day+('T14:30:00.000000Z' if field=='o' else 'T21:00:00.000000Z'))
                for i,symbol in enumerate(SYMBOLS):
                    require((symbol,day) in index,'INPUT_INTEGRITY')
                    row=index[symbol,day]
                    basis=row['source_basis'];clocks=row['observed_clocks']
                    require(basis['adjustment']=='raw' and basis['feed']=='sip'
                            and basis['currency']=='USD' and basis['requested_asof']=='2020-09-02',
                            'FORBIDDEN_INPUT')
                    require(type(clocks) is dict and all(v is None for v in clocks.values()),'CLOCK_ORDER')
                    point=row['source_normalized_line']
                    source_line,source_ref=self.line(point['path'],point['line_1based'],point['sha256'],'source_record')
                    source_body=row['source_body'];body=self.member(source_body['path'])
                    require(sha(body)==source_body['sha256'] and len(body)==source_body['bytes'],'INPUT_INTEGRITY')
                    values=decode(body,inert_numbers=True)
                    require(type(source_body['ordinal_0based']) is int and source_body['ordinal_0based']>=0,'INPUT_INTEGRITY')
                    values=values[source_body['array']]
                    # Some provider bodies key bars by symbol; no ticker remapping is inferred.
                    if type(values) is dict:values=values[symbol]
                    require(type(values) is list and source_body['ordinal_0based']<len(values),'INPUT_INTEGRITY')
                    source_value=values[source_body['ordinal_0based']][field]
                    token=row['raw_open_token' if field=='o' else 'raw_close_token']
                    require(source_line['source_symbol']==symbol and source_line['reference_date']==day
                            and source_line['raw_fields_exact_tokens'][field]==token
                            and source_line['source_body_sha256']==source_body['sha256']
                            and source_line['source_row_ordinal']==source_body['ordinal_0based'],
                            'INPUT_INTEGRITY')
                    require(type(source_value) in (NumberToken,int) and str(source_value)==token
                            and str(values[source_body['ordinal_0based']]['t'])==row['source_daily_timestamp_token'],
                            'INPUT_INTEGRITY')
                    amount=decimal_fraction(token)*100
                    require(amount.denominator==1 and amount>0,'NATIVE_REPRESENTATION')
                    source={'record_token':source_ref['record_token'],'source_record_sha256':source_ref['sha256'],
                        'field':field,'estimated_fullbar_K':source_clock(row['estimated_full_bar_K_inherited_method']),
                        'observed_event_at':None,'observed_historical_available_at':None,
                        'role':'EXECUTOR_MODELED_OPEN' if field=='o' else 'EX_POST_REFERENCE_CLOSE'}
                    validate(source,'event_source')
                    observations.append({**identity(symbol),'kind':'OPEN' if field=='o' else 'CLOSE',
                        'day':day,'quote_event_ns':str(Q+i),'snapshot_as_of':microtime(Q+1000),
                        'price':money(amount.numerator),'source':source})
        payload={'required_methods':list(METHODS),'D':D,'I':I,'rows':semantic_rows}
        validate(payload,'scores_payload')
        return {'score_rows':ordered,'scores_payload':payload,'observations':observations,
                'lineage_refs':sorted(self.lineage.values(),key=lambda r:(r['role'],r['record_token'],r['sha256']))}
