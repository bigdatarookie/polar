"""Producer projection for modeled reference units; no UI finance or raw-price labels."""
from .ci_research import cents_text, utc_text
from .research_results import validate_result

ALIASES = {'net_total_return':'adjusted_reference_return_after_costs',
           'net_cagr_act36525':'adjusted_reference_cagr_after_costs'}
MONEY = {'terminal_nav_usd','flat_fee_usd','bps_cost_usd','total_cost_usd',
         'gross_exact_notional_usd','gross_settled_notional_usd'}


def public_reference(config, simulation, evaluation, *, semantic_id, semantic_hash, phase):
    primary, benchmark = config['primary_strategy'], config['primary_benchmark']
    evaluated = {v['id']:v for v in evaluation['legs']}
    series=[]
    for leg in simulation['legs']:
        returns=evaluated[leg['id']]['returns'];ledger=[]
        for i,row in enumerate(leg['nav']):
            ledger.append({'cash':cents_text(row['cash_cents']),'exposure':cents_text(row['exposure_cents']),
                'cumulative_flat_fees':cents_text(row['flat_cents']),'cumulative_bps_fees':cents_text(row['bps_cents']),
                'positions':row['positions'],'net_return':{'value':returns[i-1]['decimal'] if i else None,
                     'status':'OK' if i else 'NOT_APPLICABLE','reason':None if i else 'INITIAL_POINT'}})
        series.append({'id':leg['id'],'label':leg['id'],'role':'STRATEGY' if leg['id']==primary else 'BENCHMARK' if leg['id']==benchmark else 'CONTROL',
            'unit':'USD','values':[{'value':cents_text(r['nav_cents']),'status':'OK','reason':None} for r in leg['nav']], 'ledger':ledger})
    metrics=[];units={}
    for name in evaluation['legs'][0]['metrics']:
        key=ALIASES.get(name,name);unit='USD' if name in MONEY else 'count' if name=='positive_fill_count' else 'ratio' if name=='sharpe_252_rf0' else 'fraction'
        units[name]=unit
        label={'net_total_return':'Synthetic vendor-adjusted reference-unit return after modeled costs',
               'net_cagr_act36525':'Synthetic vendor-adjusted reference-unit CAGR after modeled costs'}.get(name,name.replace('_',' '))
        metrics.append({'id':key,'label':label,'unit':unit,'values':{leg['id']:leg['metrics'][name] for leg in evaluation['legs']}})
    costs=[{'id':name,'label':label,'kind':'CHARGED_FEES','unit':'USD',
            'values':{leg['id']:leg['metrics'][metric] for leg in evaluation['legs']},'description':description}
           for name,label,metric,description in [
            ('FLAT_ORDER_FEE','Modeled flat order fee','flat_fee_usd','Model USD1 per positive fill, charged once.'),
            ('BPS_COMMISSION','Modeled 10bps commission','bps_cost_usd','Ceiling-cent 10bps exact notional, charged once; no additional spread or slippage debit.')]]
    limits=[('SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT','Current-vintage vendor-adjusted close is a modeled quote per synthetic whole reference unit. This is not a raw share, observed auction fill, or certified investor total return.'),
            ('NO_DOUBLE_ACTION_CREDIT','Vendor source already incorporates adjustment. No additional split units, dividend cash, or rebasing is credited.'),
            ('COUNTERFACTUAL_TIMING','Observed source availability remains unknown. Protocol K and D are counterfactual clock assumptions.'),
            ('MODEL_CLOSE_TIMING',config['clock_description']),
            ('SURVIVOR_CONDITIONED_FOUR_ASSETS','Four fixed known survivors/ETF; distinct from the mission broad-data target, no full-universe claim.'),
            ('EXPOSED_RETROSPECTIVE_INTERVAL','Chronological evaluation does not establish pristine process holdout or unseen history.'),
            ('MODELED_EXECUTION_COSTS','Whole reference units, exact-cent modeled costs, frozen decision quantities and next-close cash clipping; no calibrated capacity proof.'),
            ('UNMODELED_MARKET_EFFECTS','Spread, additional slippage, market impact, tax and financing are not estimated, not evidenced zero.'),
            ('TRAIN_DEVELOPMENT_TEST',config['partition_description']),
            ('PHASE_AND_FRESH_CAPITAL',phase+' uses a separate fresh model USD100000 portfolio; phases do not roll wealth forward.'),
            ('RISK_AND_POLICY_CLASS','Exposure and concentration may differ across controls. Point differences do not isolate causal alpha or risk-matched utility.'),
            ('NO_INFERENTIAL_ADOPTION','No calibrated significance, general alpha, prospective profit, original-hypothesis validation or adoption claim.')]
    record={'schema_version':'polar.research-result/1','question':{'id':config['protocol_id']+'.'+phase,
        'label':config['question_label']+' — '+phase,'summary':config['question_summary']},
        'bindings':config['bindings'],'basis':{'currency':'USD','frequency':'DAILY','timezone':'UTC',
        'wealth_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT','cost_basis':'NET',
        'cash_basis':'MODEL_USD_ZERO_CASH_CREDIT','risk_free_basis':'MODELED_RF_ZERO'},
        'grid':[utc_text(r['nominal_ns']) for r in simulation['legs'][0]['nav']], 'series':series,
        'primary_benchmark_id':benchmark,'metrics':metrics,
        'comparisons':[{**c,'metric_id':ALIASES.get(c['metric_id'],c['metric_id']),'unit':units[c['metric_id']],
                       'interpretation':'Producer-computed descriptive point difference, not significance or adoption.'} for c in evaluation['comparisons']],
        'costs':costs,'limitations':[{'code':code,'text':text,'scope':'Entire modeled comparison'} for code,text in limits],
        'provenance':config['provenance']+[{'role':'semantic_manifest','id':semantic_id,'sha256':semantic_hash}],
        'evidence_level':config['evidence_level'],'financial_claim':'Limited synthetic adjusted-reference-unit comparison after modeled costs; no raw-share, investor-total-return or adoption claim.',
        'criteria':evaluation['criteria'],'point_interpretation':evaluation['point_interpretation']}
    return validate_result(record)
