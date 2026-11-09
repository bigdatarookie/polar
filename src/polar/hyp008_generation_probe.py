"""Invented two-control feasibility probe; not a supported generator or forecast API."""
from fractions import Fraction as F
from pathlib import Path
import dataclasses
import hashlib
import json
import math
import os
import struct
import sys

VERIFIER_SHA='be0b3a2af15b6e3e4d545c92807601a8c4d61108d021549c1f16cfb5ad1fe779'
OPTIONS={'presolve':True,'maxiter':1000,'time_limit':10.0,
         'dual_feasibility_tolerance':1e-7,'primal_feasibility_tolerance':1e-7}
CONTROLS=(
    {'id':'constant-interval','z':[[1,1,1,1,1]]*10,'y':[1,3,4,5,6,7,8,9,10,11],
     'theta':[['1','6']]*6,'objective':['27','5']},
    {'id':'full-six','z':[[0,0,0,0,0],[1,0,0,0,0],[0,1,0,0,0],
                         [0,0,1,0,0],[0,0,0,1,0],[0,0,0,0,1]],
     'y':[1,3,4,5,6,7],'theta':[[str(i),'1'] for i in range(1,7)],'objective':['0','1']})


def encoded(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def digest(body):return hashlib.sha256(body).hexdigest()


def require(ok,reason):
    if not ok:raise ValueError(reason)


def publish(name,value):
    path=Path('/polar-output')/name
    with path.open('xb') as out:out.write(encoded(value));out.flush();os.fsync(out.fileno())


def bounded(value):
    require(value.numerator.bit_length()<=4096 and value.denominator.bit_length()<=4096,'EXACT_DOMAIN')
    return value


def dot(a,b):return bounded(sum((bounded(x*y) for x,y in zip(a,b)),F()))


def solve(matrix,rhs):
    """At most six independent equations; no row/basis enumeration."""
    n=len(rhs);require(n<=6,'TOY_DOMAIN')
    rows=[list(row)+[value] for row,value in zip(matrix,rhs)]
    for k in range(n):
        pivot=next((i for i in range(k,n) if rows[i][k]),None)
        require(pivot is not None,'DEPENDENT_WORKING_SET')
        rows[k],rows[pivot]=rows[pivot],rows[k]
        scale=rows[k][k];rows[k]=[bounded(v/scale) for v in rows[k]]
        for i in range(n):
            if i!=k:
                scale=rows[i][k]
                rows[i]=[bounded(a-bounded(scale*b)) for a,b in zip(rows[i],rows[k])]
    return [row[-1] for row in rows]


def secondary(A,y,dual):
    constraints=[]
    for row,target,d in zip(A,y,dual):
        equality=d not in (F(1,10),F(-9,10))
        sign=-1 if d==F(-9,10) else 1
        constraints.append(([sign*a for a in row],sign*target,equality))
    active=[i for i,c in enumerate(constraints) if c[2]]
    seen=set()
    for _ in range(32):
        key=tuple(active);require(key not in seen,'WORKING_SET_CYCLE');seen.add(key)
        rows=[constraints[i][0] for i in active]
        gram=[[dot(a,b) for b in rows] for a in rows]
        u=solve(gram,[constraints[i][1] for i in active])
        theta=[dot([row[j] for row in rows],u) for j in range(6)]
        wrong=next((i for i,v in zip(active,u) if not constraints[i][2] and -v<0),None)
        if wrong is not None:active.remove(wrong);continue
        violated=next((i for i,(row,rhs,equality) in enumerate(constraints)
                       if (dot(row,theta)!=rhs if equality else dot(row,theta)>rhs)),None)
        if violated is not None:
            require(violated not in active and len(active)<6,'UNSUPPORTED_WORKING_SET')
            active.append(violated);continue
        multipliers=[F() for _ in A]
        for i,v in zip(active,u):multipliers[i]=-v
        return theta,multipliers
    raise ValueError('WORKING_SET_LIMIT')


def candidate(control,linprog):
    A=[[F(1)]+[F(v) for v in row] for row in control['z']];y=[F(v) for v in control['y']]
    n=len(y);require(n<=10,'TOY_DOMAIN')
    equations=[[float(v) for v in row]+[float(i==j) for j in range(n)]+
               [-float(i==j) for j in range(n)] for i,row in enumerate(A)]
    result=linprog([0.0]*6+[0.1]*n+[0.9]*n,A_eq=equations,b_eq=[float(v) for v in y],
                   bounds=[(None,None)]*6+[(0,None)]*(2*n),method='highs-ds',options=OPTIONS)
    require(result.status==0 and result.success,'LP_CANDIDATE_UNAVAILABLE')
    require(len(result.eqlin.marginals)==n and all(math.isfinite(float(v)) for v in result.eqlin.marginals),'LP_DUAL_UNAVAILABLE')
    dual=[F(float(v)).limit_denominator(1000000) for v in result.eqlin.marginals]
    require(all(F(-9,10)<=d<=F(1,10) for d in dual),'DUAL_RECONSTRUCTION')
    require(all(dot([row[j] for row in A],dual)==0 for j in range(6)),'DUAL_RECONSTRUCTION')
    theta,multipliers=secondary(A,y,dual)
    return theta,dual,multipliers,{'status':int(result.status),'iterations':int(result.nit),
                                 'dual_binary64':[struct.pack('>d',float(v)).hex() for v in result.eqlin.marginals]}


def preflight():
    prep=json.loads(Path('/polar-launch/preparation.json').read_bytes())
    require(prep['preparation']=='PREPARED' and prep['scenario_started'] is False,'AUTOMATIC_RECEIPT_REQUIRED')
    observed=prep['observed'];expected=prep['expected']
    require(observed['image_id']==expected['image_id'] and observed['os']=='linux'
            and observed['architecture']=='arm64','RUNTIME_IDENTITY')
    require(os.getuid()==10001 and sys.version_info[:3]==(3,13,18),'RUNTIME_IDENTITY')
    binding=prep['source_binding'];require(binding['packaged_source_independently_observed'] is True,'SOURCE_OBSERVATION')
    require(binding['observed_container_id']==observed['container_id'],'SAME_CONTAINER')
    for name in ('hyp008_generation_probe.py','exact_certificate.py'):
        path=Path('/app/src/polar')/name;body=path.read_bytes()
        require(binding['observed_files'][str(path)]=={'bytes':len(body),'sha256':digest(body)},'SOURCE_BYTES')
        if name=='exact_certificate.py':require(digest(body)==VERIFIER_SHA,'ACCEPTED_VERIFIER_BYTES')
    require(Path(__file__).resolve()==Path('/app/src/polar/hyp008_generation_probe.py'),'SOURCE_ORIGIN')
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS',
                 'NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
        require(os.environ.get(name)=='1','THREAD_CONFIGURATION')
    return prep


def main():
    prep=preflight()
    import scipy
    import numpy
    from scipy.optimize import linprog
    from polar import exact_certificate as verifier
    require(scipy.__version__=='1.15.3' and numpy.__version__=='2.2.6','PINNED_NUMERICAL_BUILD')
    require(Path(verifier.__file__).resolve()==Path('/app/src/polar/exact_certificate.py'),'VERIFIER_ORIGIN')
    publish('generation-preflight.json',{'image':prep['observed']['image_id'],
            'container':prep['observed']['container_id'],'source':prep['source_binding'],
            'controls_sha256':digest(encoded(CONTROLS)),'method':'highs-ds','options':OPTIONS,
            'scipy':scipy.__version__,'numpy':numpy.__version__,'scenario_calls':0})
    results=[]
    for control in CONTROLS:
        try:
            theta,dual,secondary_values,lp=candidate(control,linprog)
            wire=lambda values:tuple((str(v.numerator),str(v.denominator)) for v in values)
            bits=lambda v:struct.pack('>d',float(v)).hex()
            request=verifier.ExactCertificateRequest(tuple(control['id']+'/'+str(i) for i in range(len(dual))),
                tuple(tuple(bits(v) for v in row) for row in control['z']),tuple(bits(v) for v in control['y']),
                wire(theta),wire(dual),wire(secondary_values))
            proof=verifier.verify_exact_certificate(request,limits=verifier.ExactCertificateLimits(10,128,4096,65536,2000000,1048576))
            expected=proof.theta==tuple(tuple(v) for v in control['theta']) and proof.primary_objective==tuple(control['objective'])
            results.append({'control':control['id'],'status':'CERTIFIED_TOY' if
                proof.status=='EXACT_REPRESENTED_INPUT_CERTIFIED' and expected else 'NUMERICAL_UNVERIFIED',
                'lp':lp,'request':dataclasses.asdict(request),'proof':dataclasses.asdict(proof),'expected_match':expected})
        except (ValueError,ArithmeticError) as exc:
            results.append({'control':control['id'],'status':'NUMERICAL_UNVERIFIED',
                            'reason':str(exc)[:128]})
    publish('generation-result.json',{'scope':'INVENTED_TECHNICAL_ONLY','controls':results,
            'production_generator':'NOT_IMPLEMENTED','financial_status':'NOT_ASSESSED'})


if __name__=='__main__':main()
