"""Read-only, content-bound execution projection. Never infer trades from NAV.

Only the requested saved simulation member is read; training/model/private input
members are not opened. No service runner/evaluator/predictor is imported.
"""
import re
from fractions import Fraction
from pathlib import Path
from datetime import datetime, timezone
from .history_bundle import read_file, decode, sha, canonical
from .research_results import ResearchError

LIMIT = 32 * 1024**2
MAX_ORDERS = 100000


def require(ok, code="RESEARCH_EXECUTION_BINDING"):
    if not ok:
        raise ResearchError(code, 409)


def integer(v, minimum=0):
    require(type(v) is int and minimum <= v <= 10**30)
    return v


def money(cents):
    n=integer(cents)
    return f"{n//100}.{n%100:02d}"


def matches_money(cents, token):
    return Fraction(integer(cents),100)==Fraction(token)


def utc(ns):
    integer(ns)
    seconds, nano=divmod(ns,10**9)
    return datetime.fromtimestamp(seconds,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + (f'.{nano:09d}' if nano else '') + 'Z'


def navigation(record, symbol):
    # Versioned metadata relation keyed by input content, never by strategy name
    # or ticker equality alone. No source quote file is opened.
    mapping=decode(Path(__file__).with_name('research_navigation.json').read_bytes())
    rows=[x for x in mapping['mapping'] if x['native_symbol']==symbol] if record['bindings']['data_sha256']==mapping['input_sha256'] else []
    if len(rows)!=1:
        return {'status':'UNRESOLVED','reason':'SOURCE_INSTRUMENT_MAPPING_NOT_BOUND',
                'dataset_id':None,'dataset_revision':None,'instrument_id':None}
    row=rows[0]
    return {'status':'BOUND','reason':None,**{k:v for k,v in row.items() if k!='native_symbol'},
            'evidence_sha256':mapping['evidence_sha256'],'input_sha256':mapping['input_sha256']}


def project(results, result_id, series_id=None, limit=100, offset=0):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= MAX_ORDERS:
        raise ResearchError('RESEARCH_EXECUTION_PAGE',422)
    detail=results.read(result_id);r=detail['record']
    if series_id is None:
        selected=[s for s in r['series'] if s['role']=='STRATEGY']
    else:
        selected=[s for s in r['series'] if s['id']==series_id]
    if len(selected)!=1:
        raise ResearchError('RESEARCH_EXECUTION_SERIES',422)
    series=selected[0]
    base={'schema_version':'polar.research-executions/1','result_id':result_id,
          'content_sha256':detail['content_sha256'],'series_id':series['id'],
          'basis':r['basis'],'limit':limit,'offset':offset}
    refs=[x for x in r['provenance'] if x['role']=='semantic_manifest']
    require(len(refs)==1)
    ref=refs[0];sid=ref['id'];h=ref['sha256']
    if re.fullmatch(r'ci-experiment-[a-f0-9]{64}',sid):
        parent='ci-research-experiments/'+sid
    elif re.fullmatch(r'(?:scheduled-reference|reference)-experiment-[a-f0-9]{64}',sid):
        parent='reference-research-experiments/'+sid
    else:
        return {**base,'status':'UNAVAILABLE','reason':'SAVED_EXECUTION_TAPE_NOT_BOUND','phase':None,
                'total':None,'next_offset':None,'items':[]}
    require(sid.endswith(h))
    raw=read_file(results.root,parent+'/manifest.json',LIMIT)
    require(sha(raw)==h,'RESEARCH_EXECUTION_MANIFEST_HASH')
    manifest=decode(raw);schema=manifest.get('schema');members=manifest.get('files')
    require(type(members) is dict and len(members)<=1000)
    phase=None
    def member(name):
        require(name in members)
        pin=members[name]
        require(type(pin) is dict and set(pin)=={'sha256','bytes'} and
                type(pin['sha256']) is str and re.fullmatch('[a-f0-9]{64}',pin['sha256']) and
                type(pin['bytes']) is int and 0 <= pin['bytes'] <= LIMIT)
        body=read_file(results.root,parent+'/'+name,LIMIT)
        require(len(body)==pin['bytes'] and sha(body)==pin['sha256'],'RESEARCH_EXECUTION_MEMBER_HASH')
        return decode(body),pin['sha256']
    if schema=='polar.ci-research-semantic-manifest/1':
        require(sid.startswith('ci-experiment-'))
        simulation,member_hash=member('simulation.json');member_name='simulation.json'
        require(r['question']['id']==r['bindings']['protocol_id'])
    elif schema in {'polar.reference-semantic-manifest/1','polar.scheduled-reference-semantic-manifest/1'}:
        require(sid.startswith('scheduled-reference-experiment-') if schema.startswith('polar.scheduled') else sid.startswith('reference-experiment-'))
        phases,member_hash=member('phases.json');member_name='phases.json'
        prefix=r['bindings']['protocol_id']+'.'
        require(r['question']['id'].startswith(prefix))
        phase=r['question']['id'][len(prefix):]
        require(phase in phases and re.fullmatch('[A-Z][A-Z0-9_]{0,63}',phase))
        simulation=phases[phase]['simulation']
    elif schema=='polar.reference-ppo-semantic-manifest/1':
        require(sid.startswith('reference-experiment-') and r['question']['id']==r['bindings']['protocol_id']+'.FINAL')
        final,member_hash=member('final.json');member_name='final.json';simulation=final['simulation'];phase='FINAL'
    else:
        return {**base,'status':'UNAVAILABLE','reason':'SAVED_EXECUTION_SCHEMA_UNSUPPORTED','phase':None,
                'total':None,'next_offset':None,'items':[]}
    binding,binding_hash=member('bindings.json')
    public_binding=r['bindings']
    require(binding['code_revision']==public_binding['code_revision'] and binding['runtime_image_id']==public_binding['runtime_id'])
    if schema=='polar.ci-research-semantic-manifest/1':
        require(binding['pins']['input_sha256']==public_binding['data_sha256'] and binding['pins']['protocol_sha256']==public_binding['protocol_sha256'])
    else:
        require(binding['input_ref']['sha256']==public_binding['data_sha256'] and binding['protocol_ref']['sha256']==public_binding['protocol_sha256'] and
                binding['candidate_id']==public_binding['candidate_id'] and binding['experiment_id']==public_binding['experiment_id'])
    require(simulation.get('schema')=='polar.ci-research-simulation/1')
    legs=simulation.get('legs');require(type(legs) is list and len(legs)==len(r['series']))
    require(len({x['id'] for x in legs})==len(legs) and {x['id'] for x in legs}=={x['id'] for x in r['series']})
    # Bind the exact phase and every account to immutable public grid/NAV/ledger.
    for public in r['series']:
        leg=next(x for x in legs if x['id']==public['id']);nav=leg['nav']
        require(len(nav)==len(r['grid'])==len(public['values'])==len(public['ledger']))
        for row,clock,value,ledger in zip(nav,r['grid'],public['values'],public['ledger']):
            require(utc(row['nominal_ns'])==clock and value['status']=='OK' and matches_money(row['nav_cents'],value['value']))
            require(row['positions']==ledger['positions'] and matches_money(row['cash_cents'],ledger['cash']) and
                    matches_money(row['exposure_cents'],ledger['exposure']) and matches_money(row['flat_cents'],ledger['cumulative_flat_fees']) and
                    matches_money(row['bps_cents'],ledger['cumulative_bps_fees']))
    synthetic=r['basis']['wealth_basis']=='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT'
    require((simulation.get('quote_basis')=='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT')==synthetic)
    # Profile10 records consumed zero-delta decisions as well as actual fills.
    # Bind that opt-in to the saved profile/plan and public mapping provenance;
    # a zero quantity in another legacy tape is still rejected.
    consumed_model = simulation.get('quantity_unit')=='COARSE100_SYNTHETIC_REFERENCE_UNIT_NOT_PHYSICAL_SHARE'
    if consumed_model:
        require(schema=='polar.scheduled-reference-semantic-manifest/1')
        profile,_=member('profile.json');plan=phases[phase].get('plan',{})
        require(profile.get('schema')=='polar.scheduled-reference-profile/10')
        from .reference_model_price import validate
        from .gym_contract import canonical as model_canonical
        mapping=profile.get('model_price_mapping')
        try:
            validate(mapping,profile)
        except (ValueError,KeyError,TypeError) as exc:
            raise ResearchError('RESEARCH_EXECUTION_MODEL_MAPPING',409) from exc
        mapping_refs=[p for p in r['provenance'] if p['role']=='model_price_mapping']
        require(len(mapping_refs)==1 and mapping_refs[0]['sha256']==sha(model_canonical(mapping)) and
                mapping['source_input_sha256']==public_binding['data_sha256'] and
                canonical(plan.get('model_price_mapping'))==canonical(mapping) and
                plan.get('quantity_unit')==mapping['active_unit'] and
                plan.get('capture_consumed_sizing') is True and
                plan.get('consumed_witness_schema')=='polar.model-price-consumed-operands/1')
    leg=next(x for x in legs if x['id']==series['id']);orders=leg['orders'];fills=leg['fills']
    require(type(orders) is list and type(fills) is list and len(orders)<=MAX_ORDERS and len(fills)<=len(orders))
    require(len({x['id'] for x in orders})==len(orders) and len({x['id'] for x in fills})==len(fills))
    fill_map={x['id']:x for x in fills};require(set(fill_map)<={x['id'] for x in orders})
    events=[]
    for order in orders:
        oid=order['id'];symbol=order['symbol'];side=order['side'];at=integer(order['at_ns'])
        require(type(oid) is str and len(oid)<=256 and type(symbol) is str and re.fullmatch('[A-Za-z0-9_.:-]{1,64}',symbol) and side in ('BUY','SELL'))
        parts=oid.split('/')
        require(len(parts)==4 and parts[0]==series['id'] and parts[2]==side and parts[3]==symbol and re.fullmatch(r'\d{4}-\d{2}-\d{2}',parts[1]))
        datetime.strptime(parts[1],'%Y-%m-%d')
        desired=integer(order['intended_quantity']);q=integer(order['routed_quantity']);require(q<=desired)
        if desired==0:
            witness=order.get('consumed_operands');require(consumed_model and q==0 and
                order.get('reason')=='ZERO_DELTA_NO_ORDER' and type(witness) is dict)
            require(type(witness.get('desired_delta')) is int and witness['desired_delta']==0 and
                witness.get('decision_id')==series['id']+'/'+parts[1])
            target=integer(witness.get('target'));held=witness.get('holdings_before')
            require(type(held) is dict and symbol in held)
            current=integer(held[symbol])
            require(max(current-target,0)==0 if side=='SELL' else max(target-current,0)==0)
        fill=fill_map.get(oid);require((fill is not None)==(q>0))
        if fill is not None:
            require(fill['symbol']==symbol and fill['side']==side and fill['at_ns']==at and fill['q']==q)
            price=integer(fill['price_micro'],1);fee=integer(fill['fee_cents']);settled=integer(fill['settled_cents'])
        else:price=fee=settled=None
        events.append({'order_id':oid,'symbol':symbol,'side':side,'timestamp_ns':str(at),'timestamp':utc(at),
            'intended_quantity':str(desired),'routed_quantity':str(q),'filled_quantity':str(q) if fill else '0',
            'status':'FILLED' if fill else 'NOT_ROUTED','reason':order.get('reason'),
            'session_date':parts[1],'timestamp_semantics':'NATIVE_ORDER_SUBMISSION_AND_MATCHED_FILL',
            'instrument':navigation(r,symbol),
            'price_micro':str(price) if fill else None,'fee_cents':str(fee) if fill else None,
            'settled_notional_cents':str(settled) if fill else None})
    events.sort(key=lambda x:(int(x['timestamp_ns']),x['order_id']))
    end=offset+limit
    return {**base,'status':'OK','reason':None,'phase':phase,'semantic_id':sid,
        'semantic_manifest_sha256':h,'member':member_name,'member_sha256':member_hash,'binding_sha256':binding_hash,
        'quote_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT' if synthetic else 'MODELED_RAW_SHARE_PRICE',
        'quantity_unit':simulation.get('quantity_unit','WHOLE_SHARE'),
        'price_unit':'USD_PER_SYNTHETIC_REFERENCE_UNIT' if synthetic else 'USD_PER_MODELED_SHARE',
        'raw_ohlc_overlay_compatible':False,
        'compatibility_reason':'EXACT_PRICE_BASIS_MATCH_REQUIRED_NO_TICKER_ONLY_ATTRIBUTION',
        'total':len(events),'next_offset':end if end<len(events) else None,'items':events[offset:end]}
