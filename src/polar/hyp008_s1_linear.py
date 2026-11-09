"""One fixed sparse LP route and bounded exact secondary/certificate."""
from dataclasses import asdict
from fractions import Fraction as F
import math
import struct
from .hyp008_s1_numeric import dyadic,round_binary64
from .exact_certificate import ExactCertificateRequest,ExactCertificateLimits,verify_exact_certificate

OPTIONS={'presolve':True,'maxiter':1000,'time_limit':10.0,
         'dual_feasibility_tolerance':1e-7,'primal_feasibility_tolerance':1e-7}
VERIFIER_LIMITS=ExactCertificateLimits(10000,2048,4096,65536,2000000,16777216)


class LinearUnavailable(ValueError):pass


def require(ok,reason):
    if not ok:raise LinearUnavailable(reason)


class Arithmetic:
    """Conservative raw-intermediate4096-bit guard before arithmetic."""
    def __init__(self):self.operations=0
    def charge(self):
        require(self.operations<2000000,'GENERATION_OPERATION_LIMIT');self.operations+=1
    def guard(self,size):require(size<=4096,'GENERATION_INTEGER_GROWTH')
    def value(self,x):
        require(type(x) is F,'GENERATION_RATIONAL_TYPE')
        self.guard(max(x.numerator.bit_length(),x.denominator.bit_length()));return x
    def mul(self,a,b):
        self.charge();self.value(a);self.value(b)
        self.guard(a.numerator.bit_length()+b.numerator.bit_length())
        self.guard(a.denominator.bit_length()+b.denominator.bit_length())
        return self.value(a*b)
    def add(self,a,b):
        self.charge();self.value(a);self.value(b)
        self.guard(max(a.numerator.bit_length()+b.denominator.bit_length(),
                       b.numerator.bit_length()+a.denominator.bit_length())+1)
        self.guard(a.denominator.bit_length()+b.denominator.bit_length())
        return self.value(a+b)
    def sub(self,a,b):return self.add(a,-b)
    def div(self,a,b):
        require(b!=0,'DEPENDENT_WORKING_SET');return self.mul(a,F(b.denominator,b.numerator))
    def dot(self,a,b):
        total=F(0)
        for x,y in zip(a,b):total=self.add(total,self.mul(x,y))
        return total
    def solve(self,matrix,rhs):
        n=len(rhs);require(n<=6,'UNSUPPORTED_WORKING_SET')
        rows=[list(row)+[value] for row,value in zip(matrix,rhs)]
        for k in range(n):
            pivot=next((i for i in range(k,n) if rows[i][k]),None)
            require(pivot is not None,'DEPENDENT_WORKING_SET');rows[k],rows[pivot]=rows[pivot],rows[k]
            scale=rows[k][k];rows[k]=[self.div(v,scale) for v in rows[k]]
            for i in range(n):
                if i!=k:
                    scale=rows[i][k]
                    rows[i]=[self.sub(a,self.mul(scale,b)) for a,b in zip(rows[i],rows[k])]
        return [row[-1] for row in rows]


def admitted(row_ids,z_bits,y_bits):
    require(type(row_ids) is tuple and type(z_bits) is tuple and type(y_bits) is tuple
            and 1<=len(row_ids)<=10000 and len(row_ids)==len(z_bits)==len(y_bits),'LINEAR_INPUT_SHAPE')
    require(all(type(r) is str and r.isascii() and 1<=len(r)<=128 for r in row_ids)
            and len(set(row_ids))==len(row_ids),'LINEAR_ROW_IDS')
    require(all(type(row) is tuple and len(row)==5 for row in z_bits),'LINEAR_INPUT_SHAPE')
    m=Arithmetic();A=[tuple([F(1)]+[m.value(dyadic(b)) for b in row]) for row in z_bits]
    y=[m.value(dyadic(b)) for b in y_bits]
    return m,A,y


def sparse_equations(A,csr_matrix):
    """Column convention(theta6,residual+n,residual-n), <=8n nonzeros."""
    n=len(A);require(type(A) in (list,tuple) and 1<=n<=10000
            and all(type(row) is tuple and len(row)==6 and all(type(v) is F for v in row) for row in A),
            'LINEAR_ROW_BOUND')
    data=[];indices=[];indptr=[0]
    for i,row in enumerate(A):
        for j,value in enumerate(row):
            if value:data.append(float(value));indices.append(j)
        data.extend((1.0,-1.0));indices.extend((6+i,6+n+i));indptr.append(len(data))
    require(len(data)<=8*n,'SPARSE_ALLOCATION_BOUND')
    return csr_matrix((data,indices,indptr),shape=(n,6+2*n),dtype='float64')


def secondary(A,y,dual,m):
    constraints=[]
    for row,target,d in zip(A,y,dual):
        equality=d not in (F(1,10),F(-9,10));sign=-1 if d==F(-9,10) else 1
        constraints.append((tuple(-a if sign==-1 else a for a in row),-target if sign==-1 else target,equality))
    active=[i for i,c in enumerate(constraints) if c[2]]
    require(len(active)<=6,'UNSUPPORTED_WORKING_SET');seen=set()
    for iteration in range(32):
        key=tuple(active);require(key not in seen,'WORKING_SET_CYCLE');seen.add(key)
        rows=[constraints[i][0] for i in active]
        gram=[[m.dot(a,b) for b in rows] for a in rows]
        u=m.solve(gram,[constraints[i][1] for i in active])
        theta=[m.dot([row[j] for row in rows],u) for j in range(6)]
        wrong=next((i for i,v in zip(active,u) if not constraints[i][2] and v>0),None)
        if wrong is not None:active.remove(wrong);continue
        violated=next((i for i,(row,rhs,equality) in enumerate(constraints)
            if (m.sub(m.dot(row,theta),rhs)!=0 if equality else m.sub(m.dot(row,theta),rhs)>0)),None)
        if violated is not None:
            require(violated not in active and len(active)<6,'UNSUPPORTED_WORKING_SET')
            active.append(violated);continue
        multipliers=[F(0) for _ in A]
        for i,v in zip(active,u):multipliers[i]=-v
        return theta,multipliers,iteration+1
    raise LinearUnavailable('WORKING_SET_LIMIT')


def generate(row_ids,z_bits,y_bits,linprog,csr_matrix):
    """Injected functions are the locked SciPy route or pure test doubles."""
    m,A,y=admitted(row_ids,z_bits,y_bits);n=len(y)
    equations=sparse_equations(A,csr_matrix)
    result=linprog([0.0]*6+[0.1]*n+[0.9]*n,A_eq=equations,b_eq=[float(v) for v in y],
                   bounds=[(None,None)]*6+[(0,None)]*(2*n),method='highs-ds',options=dict(OPTIONS))
    require(result.status==0 and result.success,'LP_CANDIDATE_UNAVAILABLE')
    values=result.eqlin.marginals
    require(len(values)==n and all(math.isfinite(float(v)) for v in values),'LP_DUAL_UNAVAILABLE')
    raw_bits=[struct.pack('>d',float(v)).hex() for v in values]
    dual=[m.value(dyadic(b).limit_denominator(1000000)) for b in raw_bits]
    require(all(m.sub(d,F(-9,10))>=0 and m.sub(F(1,10),d)>=0 for d in dual),'DUAL_RECONSTRUCTION')
    require(all(m.dot([row[j] for row in A],dual)==0 for j in range(6)),'DUAL_RECONSTRUCTION')
    theta,multipliers,iterations=secondary(A,y,dual,m)
    pairs=lambda values:tuple((str(v.numerator),str(v.denominator)) for v in values)
    request=ExactCertificateRequest(row_ids,z_bits,y_bits,pairs(theta),pairs(dual),pairs(multipliers))
    proof=verify_exact_certificate(request,limits=VERIFIER_LIMITS)
    require(proof.status=='EXACT_REPRESENTED_INPUT_CERTIFIED','CERTIFICATE_NOT_VERIFIED')
    return {'schema':'polar.hyp008-s1-linear/1','theta':list(proof.theta),
            'certificate_request':asdict(request),'proof':asdict(proof),
            'solver':{'method':'highs-ds','options':dict(OPTIONS),'status':int(result.status),
                      'iterations':int(result.nit),'dual_binary64':raw_bits,
                      'secondary_iterations':iterations,'generation_operations':m.operations},
            'limits':asdict(VERIFIER_LIMITS),'representation':'CSR_THETA6_POSITIVE_N_NEGATIVE_N'}


def predict_linear(theta,z_bits):
    require(type(z_bits) is tuple and len(z_bits)==5 and len(theta)==6,'LINEAR_PREDICTION_SHAPE')
    m=Arithmetic();coefficients=[]
    for pair in theta:
        require(type(pair) in (tuple,list) and len(pair)==2
                and all(type(t) is str and len(t)<=2048 for t in pair),'LINEAR_THETA_TOKEN')
        numerator,denominator=int(pair[0]),int(pair[1])
        m.guard(max(numerator.bit_length(),denominator.bit_length()))
        require(denominator>0,'LINEAR_THETA_DENOMINATOR')
        value=m.value(F(numerator,denominator))
        require((str(value.numerator),str(value.denominator))==tuple(pair),'LINEAR_THETA_CANONICAL')
        coefficients.append(value)
    result=round_binary64(m.dot(coefficients,(F(1),)+tuple(m.value(dyadic(b)) for b in z_bits)))
    return {'schema':'polar.hyp008-s1-linear-prediction/1',**result}


def verify_saved_linear(value):
    """Read-only certificate reproduction: never invokes LP or generation."""
    require(type(value) is dict and value.get('schema')=='polar.hyp008-s1-linear/1'
            and value.get('limits')==asdict(VERIFIER_LIMITS),'STORED_LINEAR_SCHEMA')
    r=value['certificate_request']
    require(type(r) is dict and set(r)=={'row_ids','z_bits','y_bits','theta','dual','secondary'}
            and type(r['row_ids']) in (tuple,list) and 1<=len(r['row_ids'])<=10000,
            'STORED_CERTIFICATE_SHAPE')
    request=ExactCertificateRequest(tuple(r['row_ids']),tuple(tuple(row) for row in r['z_bits']),
        tuple(r['y_bits']),tuple(tuple(p) for p in r['theta']),tuple(tuple(p) for p in r['dual']),
        tuple(tuple(p) for p in r['secondary']))
    result=verify_exact_certificate(request,limits=VERIFIER_LIMITS)
    require(result.status=='EXACT_REPRESENTED_INPUT_CERTIFIED'
            and result.proof_id==value['proof']['proof_id']
            and tuple(tuple(p) for p in value['theta'])==result.theta,'STORED_CERTIFICATE_MISMATCH')
    return asdict(result)
