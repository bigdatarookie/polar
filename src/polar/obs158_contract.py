"""Closed OBS158 result projection; execution receipts are outside semantic identity."""
from pathlib import Path
from .gym_contract import canonical,decode,sha,COMPOSITION_SHA
from .obs158_data import PUBLIC_SHA,METRIC_SHA,REVISION,QUALIFICATION
from .obs158_math import require

PROTOCOL='OBS158_PRICE_LEDGER_20190830_20200831_V1'
MAX_BYTES=128*1024**2
FILES=('converted.json','preflight.json','source-context.json','simulation.json','evaluation.json')
ENGINEERING_CHECKS=('NATIVE_CENT_UNIT_EQUIVALENCE','INDEPENDENT_CONTROLS',
                    'RUNNER_OUTPUT_SCHEMA','ACTUAL_RUNTIME_BINDING')


def source_code():
    root=Path(__file__).parent
    return {str(p.relative_to(root)):{'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())}
            for p in sorted(root.rglob('*')) if p.is_file() and p.suffix in ('.py','.json','.sql')}


def input_inventory(bindings):
    # Preserve multiplicity and content roles; paths to mounted source roots are
    # execution provenance. Immutable source-row provenance remains data content.
    return sorted(({'role':Path(name).name if Path(name).is_absolute() else name,
                    'sha256':value['sha256'],'bytes':value['bytes']}
                   for name,value in bindings.items()),
                  key=lambda r:(r['role'],r['sha256'],r['bytes']))


def semantic_bindings(code,inputs):
    return {'schema':'polar.obs158-semantic-bindings/1','protocol':PROTOCOL,
            'public_sha256':PUBLIC_SHA,'metric_sha256':METRIC_SHA,
            'dataset_revision':REVISION if inputs.source_class=='RETAINED' else 'INVENTED',
            'source_qualification_sha256':QUALIFICATION if inputs.source_class=='RETAINED' else None,
            'source_class':inputs.source_class,'source_code':code,
            'input_inventory':input_inventory(decode(inputs.bindings)),
            'engine':'nautilus_trader/1.231.0','composition_sha256':COMPOSITION_SHA,
            'numeric_policy':'EXACT_FRACTION_DECIMAL50_HALF_EVEN',
            'output_contract_sha256':code['obs158_output_schema.json']['sha256']}


def source_context(inputs,aliases):
    context=decode(inputs.context);q=context.get('qualification',{})
    coverage=q.get('instrument-coverage.json',[])
    require(type(coverage) is list,'INVALID_COVERAGE_CONTEXT')
    zero=[]
    for raw in inputs.rows:
        row=decode(raw)
        if int(row['raw_fields_exact_tokens']['v'])==0:
            zero.append({'alias':row['source_symbol'],'date':row['reference_date'],
                         'source_row_sha256':sha(raw)})
    require(len(zero)==960,'FIXED_ZERO_VOLUME_COUNT')
    return {'schema':'polar.obs158-source-context/1','source_class':inputs.source_class,
            'coverage':sorted(coverage,key=lambda r:r['source_symbol']),
            'excluded_sources':sorted((r for r in coverage if r['source_symbol'] not in aliases),
                                      key=lambda r:r['source_symbol']),
            'zero_volume_flags':sorted(zero,key=lambda r:(r['date'],r['alias'])),
            'producer_zero_volume_flags':context.get('observed_zero_rows',[]),
            'pointer_scope':context.get('pointer_scope','INVENTED'),
            'financial_status':'INSUFFICIENT_EVIDENCE',
            'limits':['PRICE_ONLY_DIVIDENDS_EXCLUDED','PARTIAL_ACTION_COVERAGE',
                      'SOURCE_ALIASES_NOT_ECONOMIC_SECURITY_IDS','MODELED_CLOCKS_AND_EXECUTION',
                      'ZERO_VOLUME_RETAINED_NOT_LIQUIDITY_PROOF']}
