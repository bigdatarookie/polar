"""Saved-only verification of newly captured coarse-model call-site witnesses.

Never reconstructs absent witnesses or reads source/store files. The saved fill
ledger is an independent check on the *captured* D/pre-order state, not a
replacement for that state. Does not run a policy, native account or evaluator.
"""
from fractions import Fraction
from .ci_research import require, fee_cents
from .obs158_math import cent_round_micro
from .gym_contract import canonical, sha


def same(a,b):
    return canonical(a)==canonical(b)  # JSON bool is not an integer operand.


def verify(plan,simulation,profile,calendar=None):
    from .reference_model_price import verify_plan
    verify_plan(plan,profile)
    if calendar is not None:
        from .saved_report_projection import report_calendar,fixed_plan_metadata
        grid,closes=report_calendar(calendar)
        require(closes is not None,'MODEL_CONSUMED_FIXED_CALENDAR')
        fixed_plan_metadata({'plan':plan,'simulation':simulation},profile,grid,closes)
    clocks={g['date']:g['nominal_ns'] for g in plan['grid']}
    require(all(same(d['formation_close_ns'],clocks[d['formation']]) and
                d['formation_close_ns']<d['known_ns']<d['decision_ns']<d['open_ns']
                for d in plan['decisions']),'MODEL_CONSUMED_CLOCK')
    symbols=profile['symbols'];zero={s:0 for s in symbols}
    mapping=profile['model_price_mapping'];mapping_hash=sha(canonical(mapping))
    require(plan.get('capture_consumed_sizing') is True and
            plan.get('consumed_witness_schema')=='polar.model-price-consumed-operands/1', 'MODEL_CONSUMED_REQUIRED')
    require([x['id'] for x in simulation['legs']]==[x['id'] for x in profile['legs']] and
            simulation.get('quantity_unit')==mapping['active_unit'], 'MODEL_CONSUMED_LEGS_UNIT')
    cost=plan.get('cost_profile',{'flat_cents':100,'bps':10})
    events=plan['decisions'];days=[d['day'] for d in events]
    require(len(days)==len(set(days)) and days==sorted(days),'MODEL_CONSUMED_EVENT_ORDER')
    for leg,definition in zip(simulation['legs'],profile['legs']):
        fills=leg['fills'];orders=leg['orders'];intents=leg['intents']
        require(fills==sorted(fills,key=lambda f:f['at_ns']) and
                len({f['id'] for f in fills})==len(fills),'MODEL_CONSUMED_FILL_ORDER')
        require(len(intents)==len(events) and [i['day'] for i in intents]==days,'MODEL_CONSUMED_INTENT_COUNT')
        require(len(orders)==2*len(symbols)*len(events) and len({o['id'] for o in orders})==len(orders),
                'MODEL_CONSUMED_ROUTE_COUNT')
        by_order={o['id']:o for o in orders};by_fill={f['id']:f for f in fills}
        cash=10000000;held=dict(zero);states=[]
        for f in fills:
            s=f['symbol'];q=f['q'];p=f['price_micro'];side=f['side'];o=by_order.get(f['id'])
            require(s in symbols and side in ('BUY','SELL') and type(q) is int and q>0 and type(p) is int and p>0 and
                    o is not None and o['symbol']==s and o['side']==side and o['routed_quantity']==q and o['at_ns']==f['at_ns'],
                    'MODEL_CONSUMED_FILL_LINK')
            require(f['fee_cents']==fee_cents(q,p,cost_profile=cost) and
                    f['settled_cents']==cent_round_micro(q*p),'MODEL_CONSUMED_FILL_MONEY')
            sign=1 if side=='BUY' else -1
            cash-=sign*f['settled_cents']+f['fee_cents'];held[s]+=sign*q
            require(cash>=0 and min(held.values())>=0 and same(cash,f['cash_after_cents']), 'MODEL_CONSUMED_FILL_STATE')
            states.append((f['at_ns'],cash,dict(held)))
        def before(ns):
            prior=[x for x in states if x[0]<ns]
            return (prior[-1][1],prior[-1][2]) if prior else (10000000,dict(zero))
        for d,i in zip(events,intents):
            kind='EXIT' if d is events[-1] else 'HOLD' if definition['rule']=='CASH' else 'TARGET'
            instruction={'kind':kind} if kind!='TARGET' else {'kind':'TARGET','weights':definition['weights'],'signal':{'kind':'FIXED_DECLARED_WEIGHTS'}}
            require(same(d['instructions'][leg['id']],instruction),'MODEL_CONSUMED_INSTRUCTION')
            decision_id=leg['id']+'/'+d['day'];cash,held=before(d['decision_ns'])
            require(i['decision_id']==decision_id and same(i['decision_ns'],d['decision_ns']) and i['instruction_kind']==kind and
                    i['formation']==d['formation'] and same(i['known_ns'],d['known_ns']) and i['spending_budgets_cents']=={},
                    'MODEL_CONSUMED_DECISION_LINK')
            marks={s:plan['prices'][d['formation']][s]['close_micro'] for s in symbols}
            if kind=='TARGET':
                nav=cash+sum(cent_round_micro(held[s]*marks[s]) for s in symbols)
                weights={s:Fraction(*p) for s,p in definition['weights'].items()}
                target={s:nav*10000*w.numerator//(marks[s]*w.denominator) for s,w in weights.items()}
                expected={'schema':'polar.target-sizing-witness/1','cash_cents':cash,'holdings':held,
                    'eligible_prices_micro':marks,'nav_cents':nav,'weights':{s:[w.numerator,w.denominator] for s,w in weights.items()},
                    'targets':target,'lot_size':1,'quantity_unit':mapping['active_unit'],'model_mapping_sha256':mapping_hash,
                    'eligible_quote':{'date':d['formation'],'at_ns':d['formation_close_ns'],
                        'source_identity':{'source_input_sha256':mapping['source_input_sha256'],
                            'model_mapping_sha256':mapping_hash,'source_date':d['formation']}}}
                require(same(i['sizing_witness'],expected) and i['sizing_status']=='CONSUMED_TARGET_OPERANDS', 'MODEL_CONSUMED_D_OPERANDS_FLOOR')
            else:
                target=dict(zero) if kind=='EXIT' else held
                require(i['sizing_witness'] is None and i['sizing_status']=='NOT_APPLICABLE_'+kind,'MODEL_CONSUMED_NO_FAKE_SIZING')
            require(same(i['targets'],target),'MODEL_CONSUMED_TARGET')
            for side,offset in [('SELL',100),('BUY',200)]:
                for j,s in enumerate(symbols):
                    oid=decision_id+'/'+side+'/'+s;o=by_order[oid];at=d['open_ns']+offset+j
                    cash,held=before(at);p=plan['prices'][d['day']][s]['close_micro']
                    desired=max(held[s]-target[s],0) if side=='SELL' else max(target[s]-held[s],0)
                    w=o['consumed_operands'];q=o['routed_quantity']
                    require(type(q) is int and 0<=q<=desired and o['id']==oid and o['symbol']==s and o['side']==side and
                            same(o['at_ns'],at) and same(o['intended_quantity'],desired),'MODEL_CONSUMED_ROUTE_ID')
                    expected={'decision_id':decision_id,'target':target[s],'holdings_before':held,'cash_before_cents':cash,
                        'price_micro':p,'quote_at_ns':d['open_ns']+j,'quote_day':d['day'],'desired_delta':desired,
                        'affordability':w['affordability'],'cost_profile':cost}
                    require(same(w,expected),'MODEL_CONSUMED_ROUTE_STATE')
                    if side=='SELL':
                        require(q==min(desired,held[s]) and w['affordability'] is None,'MODEL_CONSUMED_SELL')
                    else:
                        expected={'schema':'polar.affordability-witness/1','desired':desired,'price_micro':p,
                            'cash_cents':cash,'effective_spend_cap_cents':cash,'budget_cents_input':None,'cost_profile':cost,
                            'returned_quantity':q,'settlement':'HALF_EVEN_CENT','commission':'FLAT_PLUS_CEILING_BPS_EXACT_MICRO'}
                        require(same(w['affordability'],expected) and
                                cent_round_micro(q*p)+fee_cents(q,p,cost_profile=cost)<=cash and
                                (q==desired or cent_round_micro((q+1)*p)+fee_cents(q+1,p,cost_profile=cost)>cash),
                                'MODEL_CONSUMED_BUY_MAXIMAL')
                    require(o['reason']==('ZERO_DELTA_NO_ORDER' if desired==0 else 'FEE_AWARE_BUDGET_CAP' if q<desired else None) and
                            (oid in by_fill)==(q>0),'MODEL_CONSUMED_ZERO_FILL_LINK')
                    if q:require(by_fill[oid]['price_micro']==p,'MODEL_CONSUMED_EXECUTION_MODEL_PRICE')
        # Captured native marks must agree with the independently joined saved fills.
        require(len(leg['nav'])==len(plan['grid']),'MODEL_CONSUMED_NAV_COUNT')
        for n,g in zip(leg['nav'],plan['grid']):
            cash,held=before(g['sample_ns']);prices={s:plan['prices'][g['date']][s]['close_micro'] for s in symbols}
            require(same(n['nominal_ns'],g['nominal_ns']) and same(n['sample_ns'],g['sample_ns']) and
                    same(n['cash_cents'],cash) and same(n['positions'],held) and
                    same(n['nav_cents'],cash+sum(cent_round_micro(held[s]*prices[s]) for s in symbols)), 'MODEL_CONSUMED_NATIVE_MARK')
    return {'status':'VERIFIED_NEW_MODEL_CONSUMED_OPERANDS','source_reads':0,'policy_calls':0,'native_calls':0,'store_writes':0,
            'old_missing_witnesses':'UNAVAILABLE_NOT_BACKFILLED'}


def verify_saved(service,semantic_id):
    """Manifest-checked source-absent RO witness validation, not financial recompute."""
    import re
    from .gym_contract import decode
    from .history_bundle import read_file
    from .gym_service import code_binding
    from .scheduled_policy import profile_value
    require(type(semantic_id) is str and re.fullmatch('scheduled-reference-experiment-[a-f0-9]{64}',semantic_id),
            'MODEL_CONSUMED_SEMANTIC_ID')
    parent='reference-research-experiments/'+semantic_id
    raw=read_file(service.store.root,parent+'/manifest.json',32*1024**2)
    require(semantic_id=='scheduled-reference-experiment-'+sha(raw),'MODEL_CONSUMED_MANIFEST_HASH')
    manifest=decode(raw);names={'profile.json','calendar.json','phases.json','diagnostics.json','bindings.json'}
    require(type(manifest) is dict and manifest.get('schema')=='polar.scheduled-reference-semantic-manifest/1' and
            set(manifest['files'])==names,'MODEL_CONSUMED_MEMBER_SET')
    files={}
    for name,pin in manifest['files'].items():
        b=read_file(service.store.root,parent+'/'+name,32*1024**2)
        require(type(pin) is dict and set(pin)=={'sha256','bytes'} and type(pin['bytes']) is int and
                len(b)==pin['bytes'] and sha(b)==pin['sha256'],'MODEL_CONSUMED_MEMBER_HASH')
        files[name]=decode(b)
    p=profile_value(files['profile.json'])
    require(p['schema']=='polar.scheduled-reference-profile/10' and
            same(files['bindings.json']['code'],code_binding()) and set(files['phases.json'])=={'FINAL'},
            'MODEL_CONSUMED_CODE_PROFILE')
    data=files['phases.json']['FINAL']
    result=verify(data['plan'],data['simulation'],p,files['calendar.json'])
    return {**result,'semantic_id':semantic_id,'manifest_sha256':sha(raw),
            'financial_evaluations':0,'diagnostic_recomputations':0,'publications':0}
