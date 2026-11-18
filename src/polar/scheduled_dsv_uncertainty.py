"""DSV arithmetic verification of captured bootstrap draws; never draws samples."""
from collections import Counter
from hashlib import sha256

from .ci_research import require
from .history_bundle import canonical,sha
from . import scheduled_uncertainty as math

IDS=('DSV','EW','INV')


def return_binding(simulation):
    require([l['id'] for l in simulation['legs']]==list(IDS),'DSV_BOOTSTRAP_BASE_LEGS')
    result={}
    for leg in simulation['legs']:
        vector,n,reason=math._vector(leg)
        result[leg['id']]={'intervals':n,'reason':reason,
            'return_literals_sha256':sha(canonical([[str(v.numerator),str(v.denominator)] for v in vector]))}
    return result


def verify_saved(simulation,saved):
    """Check saved indices/statistics, no RNG/bootstrap/source/native/writes.

    Original index generation is bound to the original immutable code/run and
    seed. This path checks the captured draw operands, circular-block geometry,
    return binding, exact conditional statistics and summaries; it does not
    generate an independent sample stream or claim new statistical evidence.
    """
    require(saved.get('schema')=='polar.scheduled-paired-bootstrap/1' and
        saved.get('saved_draw_schema')=='polar.dsv-saved-bootstrap-operands/1' and
        saved.get('primary_id')=='DSV' and saved.get('benchmark_ids')==['EW','INV'] and
        saved.get('seed')==37006 and saved.get('samples')==1000 and saved.get('block_length')==63 and
        saved.get('integer_bit_limit')==math.BIT_LIMIT and
        saved.get('base_return_binding')==return_binding(simulation),'DSV_SAVED_BOOTSTRAP_BINDING')
    parsed={leg['id']:math._vector(leg) for leg in simulation['legs']}
    n=parsed['DSV'][1]
    require(type(saved.get('n')) is int and saved['n']==n and
            saved.get('actual_work')==dict(invocations=1,replicates_started=1000,indices_produced=1000,
                                          replicates_completed=1000),'DSV_SAVED_BOOTSTRAP_WORK')
    vectors,errors,tables={},{},{}
    for leg in IDS:
        vector,count,reason=parsed[leg]
        if count!=n:reason='RETURN_VECTOR_LENGTH_MISMATCH'
        vectors[leg],errors[leg]=vector,reason
        tables[leg]=math._moment_table(vector) if not reason and n>=2 else None
    valid={b:{s:[] for s in math.STATISTICS} for b in ('EW','INV')}
    reasons={b:{s:Counter() for s in math.STATISTICS} for b in ('EW','INV')}
    sequence=sha256()
    require(type(saved.get('replicates')) is list and len(saved['replicates'])==1000,'DSV_SAVED_BOOTSTRAP_DRAWS')
    keys={'sr_delta':'sr','growth_delta':'growth','drawdown_delta':'drawdown'}
    for draw,replicate in enumerate(saved['replicates']):
        require(set(replicate)=={'draw','indices_sha256','comparisons','saved_indices'} and
                type(replicate['draw']) is int and replicate['draw']==draw,'DSV_SAVED_DRAW_ORDER')
        indices=replicate['saved_indices']
        require(type(indices) is list and len(indices)==n and
                all(type(i) is int and 0<=i<n for i in indices) and
                all(indices[j]==(indices[j-1]+1)%n for j in range(1,n) if j%63),
                'DSV_SAVED_CIRCULAR_BLOCKS')
        raw=math._canonical_indices(indices);sequence.update(raw)
        require(sha256(raw).hexdigest()==replicate['indices_sha256'],'DSV_SAVED_DRAW_HASH')
        counts=Counter(indices)
        stats={leg:math._leg_statistics(vectors[leg],indices,tables[leg],counts,errors[leg]) for leg in IDS}
        comparisons=[]
        for benchmark in ('EW','INV'):
            record={'benchmark_id':benchmark}
            for name,key in keys.items():
                value,stat=math._difference(stats['DSV'][key],stats[benchmark][key])
                record[name]=stat
                if stat['status']=='OK':valid[benchmark][name].append(value)
                else:reasons[benchmark][name][stat['reason']]+=1
            comparisons.append(record)
        require(canonical(comparisons)==canonical(replicate['comparisons']),'DSV_SAVED_DRAW_STATISTICS')
    comparisons=[{'benchmark_id':b,**{s:math._temporal_interval(valid[b][s],reasons[b][s],1000)
                                      for s in math.STATISTICS}} for b in ('EW','INV')]
    all_valid=all(c[s]['valid_count']==1000 for c in comparisons for s in math.STATISTICS)
    require(sequence.hexdigest()==saved['index_sequence_sha256'] and
            canonical(comparisons)==canonical(saved['comparisons']) and saved['all_components_valid']==all_valid and
            saved['status']==('COMPLETE' if all_valid else 'INSUFFICIENT') and
            saved['reason']==(None if all_valid else 'REQUIRED_COMPONENT_REPLICATES_INVALID'),
            'DSV_SAVED_BOOTSTRAP_SUMMARY')
    return dict(saved)
