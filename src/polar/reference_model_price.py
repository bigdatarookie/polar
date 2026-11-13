"""Closed coarse100 model denomination after unchanged source validation.

Source prices/tokens remain source evidence. This changes the attainable lot1
model grid; it is not a split, physical-share mapping or invariant coordinate
change. No source reads or financial work on import.
"""
from .ci_research import require
from .gym_contract import canonical,sha


def validate(mapping,profile):
    require(type(mapping) is dict and set(mapping)=={'schema','source_input_sha256','multipliers','lot_size','active_unit'} and
        mapping['schema']=='polar.reference-model-price-mapping/1' and
        mapping['source_input_sha256']==profile['input_sha256'] and type(mapping['lot_size']) is int and
        mapping['lot_size']==1 and mapping['active_unit']=='COARSE100_SYNTHETIC_REFERENCE_UNIT_NOT_PHYSICAL_SHARE',
        'MODEL_PRICE_MAPPING_SCHEMA')
    pairs=mapping['multipliers'];require(type(pairs) is dict and set(pairs)==set(profile['symbols']),
        'MODEL_PRICE_MAPPING_SYMBOLS')
    require(any(v==[100,1] for v in pairs.values()),'MODEL_PRICE_MAPPING_COARSE100')
    for symbol,pair in pairs.items():
        require(type(pair) is list and len(pair)==2 and all(type(x) is int for x in pair) and
            pair in ([1,1],[100,1]),'MODEL_PRICE_MAPPING_FACTOR')
        if pair==[1,1]:
            require(all(leg['weights'][symbol][0]==0 for leg in profile['legs']),
                'MODEL_PRICE_IDENTITY_ALIAS_MUST_BE_INACTIVE')
        else:
            require(any(leg['weights'][symbol][0]>0 for leg in profile['legs']),
                'MODEL_PRICE_COARSE_ALIAS_MUST_BE_ACTIVE')
    return mapping


def view(source,mapping):
    """Called only after source equality validation inside the debited original."""
    require(set(source['symbols'])==set(mapping['multipliers']),'MODEL_PRICE_VIEW_SYMBOLS')
    require(mapping['source_input_sha256']==source['manifest_ref']['sha256'] and
        all(type(v) is list and len(v)==2 and all(type(x) is int for x in v) and v in ([1,1],[100,1])
            for v in mapping['multipliers'].values()),'MODEL_PRICE_VIEW_SOURCE_FACTOR')
    original=source['prices_micro'];prices={}
    for day,row in original.items():
        prices[day]={}
        for symbol in source['symbols']:
            p=row[symbol];require(type(p) is int and p>0,'MODEL_SOURCE_PRICE_DOMAIN')
            q=p*mapping['multipliers'][symbol][0]
            # Preserve exact integers. Do not clamp/round to salvage a native quote.
            require(0<q<=10**24,'MODEL_PRICE_DOMAIN')
            prices[day][symbol]=q
    return {**source,'prices_micro':prices,'source_prices_micro':original,'model_price_mapping':mapping}


def bind_plan(plan,market):
    # Instrument the existing sizing call, never a later reconstructed state.
    clocks={row['date']:row['nominal_ns'] for row in plan['grid']}
    plan={**plan,'decisions':[{**d,'formation_close_ns':clocks[d['formation']]} for d in plan['decisions']],
        'capture_consumed_sizing':True,'consumed_witness_schema':'polar.model-price-consumed-operands/1',
        'price_evidence':{d:{'source_input_sha256':market['model_price_mapping']['source_input_sha256'],
            'model_mapping_sha256':sha(canonical(market['model_price_mapping'])),'source_date':d}
            for d in plan['prices']}}
    return {**plan,'model_price_mapping':market['model_price_mapping'],
        'source_prices_micro':{d:market['source_prices_micro'][d] for d in plan['prices']},
        'quantity_unit':'COARSE100_SYNTHETIC_REFERENCE_UNIT_NOT_PHYSICAL_SHARE'}


def verify_plan(plan,profile):
    mapping=validate(profile['model_price_mapping'],profile)
    require(plan.get('model_price_mapping')==mapping and
        plan.get('quantity_unit')==mapping['active_unit'] and
        set(plan['source_prices_micro'])==set(plan['prices']),'MODEL_SAVED_MAPPING_BINDING')
    for day,row in plan['prices'].items():
        original=plan['source_prices_micro'][day]
        require(set(original)==set(row)==set(mapping['multipliers']),'MODEL_SAVED_SYMBOLS')
        for symbol in row:
            p=original[symbol];q=row[symbol]['close_micro']
            require(type(p) is int and p>0 and type(q) is int and 0<q<=10**24 and
                q==p*mapping['multipliers'][symbol][0],'MODEL_SAVED_PRICE_CORRESPONDENCE')
    return {'status':'VERIFIED_SAVED_MODEL_MAPPING','mapping_sha256':sha(canonical(mapping)),
        'source_reads':0,'policy_calls':0,'native_calls':0}
