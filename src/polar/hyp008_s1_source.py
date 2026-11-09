"""Closed, value-free S1 metadata facade. Masks never inspect numeric/model results.

A producer adapter must bind source status/basis/version/reference fields to this
facade; accepting it does not certify a dataset's fitness or grant execution.
"""
from dataclasses import dataclass,asdict
from datetime import datetime,timedelta,timezone
import re
from bisect import bisect_right
from .hyp008_s1_numeric import SLOTS

PROTOCOL='HYP008_STANDARD_SOURCE_COHORT_FORECAST_S1'
OWNER_PINS=('d53346a65e26aaa910fd629c2bf9fe6093519f45ce4292df08bf2a613d46c997',
 'fcae770d1a42560b27f49956c954bd765d7d92fd8e68fa2c97236c7b9cc60e65',
 '52b42d943eb03273fa5469d6f60dc9f159ec9901c5f04f9f717b0dad2d216603')
F='2022-01-01T00:00:00Z'
S='2026-11-09T09:37:23Z'


class S1SourceError(ValueError):pass


def require(ok,reason):
    if not ok:raise S1SourceError(reason)


def clock(value):
    require(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.[0-9]{1,6})?(?:Z|[+-]\d\d:\d\d)',value),'UTC_CLOCK')
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        require(result.tzinfo is not None,'UTC_CLOCK')
        return result.astimezone(timezone.utc)
    except ValueError:raise S1SourceError('UTC_CLOCK') from None


def text(value):return type(value) is str and 0<len(value)<=512


@dataclass(frozen=True)
class Eligibility:
    status: str
    reasons: tuple
    known_by: str | None
    basis: str
    version: str
    units: str
    reference: str

    def validate(self):
        require(self.status in ('OK','UNAVAILABLE') and type(self.reasons) is tuple
                and all(text(r) for r in self.reasons) and len(set(self.reasons))==len(self.reasons)
                and (self.status!='OK' or not self.reasons),'ELIGIBILITY_STATUS')
        require(all(text(v) for v in (self.basis,self.version,self.units,self.reference)),
                'ELIGIBILITY_PROVENANCE')
        if self.known_by is not None:clock(self.known_by)

    def at(self,cutoff,basis,version,units):
        self.validate();reasons=list(self.reasons)
        if self.status!='OK':reasons.append('UNAVAILABLE')
        if (self.basis,self.version,self.units)!=(basis,version,units):reasons.append('BASIS_VERSION_UNITS')
        if self.known_by is None:reasons.append('KNOWN_BY_UNKNOWN')
        elif clock(self.known_by)>cutoff:reasons.append('KNOWN_BY_AFTER_CUTOFF')
        return tuple(dict.fromkeys(reasons))


@dataclass(frozen=True)
class Opportunity:
    opportunity_id: str
    decision: str
    scheduled_end: str
    label_end: str | None
    common_A: Eligibility
    X: tuple
    B: Eligibility
    source_reference: str
    nominal_date: str
    source_metadata_json: str | None = None

    def validate(self):
        require(text(self.opportunity_id) and text(self.source_reference),'OPPORTUNITY_ID_REFERENCE')
        require(type(self.nominal_date) is str and re.fullmatch(r'\d{4}-\d\d-\d\d',self.nominal_date),'NOMINAL_DATE')
        try:datetime.strptime(self.nominal_date,'%Y-%m-%d')
        except ValueError:raise S1SourceError('NOMINAL_DATE') from None
        clock(self.decision);clock(self.scheduled_end)
        if self.label_end is not None:clock(self.label_end)
        require(type(self.common_A) is Eligibility and type(self.B) is Eligibility
                and type(self.X) is tuple and len(self.X)==5
                and all(type(x) is Eligibility for x in self.X),'OPPORTUNITY_SHAPE')
        self.common_A.validate();self.B.validate()
        for x in self.X:x.validate()


@dataclass(frozen=True)
class SourceBinding:
    source_class: str
    dataset_revision: str
    content_sha256: str
    delivery_sha256: str
    x_basis: str
    x_version: str
    x_units: tuple
    b_basis: str
    b_version: str
    b_units: str
    census_count: int

    def validate(self):
        require(self.source_class in ('INVENTED','RETAINED') and text(self.dataset_revision)
                and all(type(h) is str and re.fullmatch('[a-f0-9]{64}',h)
                        for h in (self.content_sha256,self.delivery_sha256)),'SOURCE_BINDING')
        require(all(text(v) for v in (self.x_basis,self.x_version,self.b_basis,self.b_version,self.b_units))
                and type(self.x_units) is tuple and len(self.x_units)==5 and all(text(v) for v in self.x_units)
                and type(self.census_count) is int and 1<=self.census_count<=10000,'SOURCE_DOMAIN')
        if self.source_class=='RETAINED':
            require(self.dataset_revision=='hyp008capability-c4783e17c03acfabe2a8c5a93d5bf04687ba1620995af7da56c3ea5ebbcecc95'
                    and self.content_sha256=='3fc65eadbf23c96c181b1381f0764aa1e5d0b235653ffc1560f69d2b3792e63f'
                    and self.delivery_sha256=='624e8ac0fb4309e3f16807bbcb53178eb0715da5c31600ba8e40468603cec421'
                    and self.census_count==403,'RETAINED_SOURCE_IDENTITY')


def prepare_metadata(rows,binding):
    require(type(binding) is SourceBinding,'SOURCE_BINDING_TYPE');binding.validate()
    require(type(rows) is tuple and len(rows)==binding.census_count
            and all(type(row) is Opportunity for row in rows),'SOURCE_CENSUS')
    for row in rows:row.validate()
    require(len({row.opportunity_id for row in rows})==len(rows),'DUPLICATE_OPPORTUNITY')
    require(all(clock(a.decision)<clock(b.decision) for a,b in zip(rows,rows[1:])),
            'OPPORTUNITY_ORDER')
    cutoff=clock(F);assessment=clock(S);ready=cutoff+timedelta(seconds=900)

    def x_reasons(row):
        d=clock(row.decision)
        reasons=['A:'+r for r in row.common_A.at(d,binding.x_basis,binding.x_version,'A_PACKET')]
        for slot,x,unit in zip(SLOTS,row.X,binding.x_units):
            reasons.extend(slot+':'+r for r in x.at(d,binding.x_basis,binding.x_version,unit))
        return reasons

    def b_reasons(row,d):
        reasons=['B:'+r for r in row.B.at(d,binding.b_basis,binding.b_version,binding.b_units)]
        if row.label_end is None:reasons.append('B:END_UNKNOWN')
        elif clock(row.label_end)>d:reasons.append('B:END_AFTER_CUTOFF')
        if clock(row.scheduled_end)>d:reasons.append('B:SCHEDULED_END_AFTER_CUTOFF')
        return reasons

    ordered_ends=sorted((clock(row.scheduled_end),i) for i,row in enumerate(rows))
    end_clocks=[v[0] for v in ordered_ends];last_indices=[];latest=-1
    for _,index in ordered_ends:
        latest=max(latest,index);last_indices.append(latest)
    training=[];census=[]
    for row in rows:
        date=row.nominal_date;xr=x_reasons(row)
        if '2017-01-03'<=date<='2021-12-31':
            reasons=xr+b_reasons(row,cutoff)
            training.append({'opportunity_id':row.opportunity_id,'admitted':not reasons,'reasons':reasons})
        if date[:4]!='2022':continue
        d=clock(row.decision);position=bisect_right(end_clocks,d)-1
        j=last_indices[position] if position>=0 else None
        window=tuple(range(j-51,j+1)) if j is not None and j>=51 else ()
        issue_reasons=list(xr)
        if ready>d:issue_reasons.append('EXPECTED_READY_AFTER_D')
        if not window:issue_reasons.append('HISTORY_52_CONSECUTIVE_SLOTS_UNAVAILABLE')
        for index in window:
            issue_reasons.extend('HISTORY:'+rows[index].opportunity_id+':'+r for r in b_reasons(rows[index],d))
        er=b_reasons(row,assessment);issue=not issue_reasons;evaluable=not er
        census.append({'opportunity_id':row.opportunity_id,'I':issue,'E':evaluable,'P':issue and evaluable,
                       'I_reasons':issue_reasons,'E_reasons':er,
                       'history_anchor':None if j is None else rows[j].opportunity_id,
                       'history_window':[rows[i].opportunity_id for i in window]})
    ids=lambda key:[r['opportunity_id'] for r in census if r[key]]
    return {'schema':'polar.hyp008-s1-masks/1','protocol':PROTOCOL,'owner_pins':list(OWNER_PINS),
            'dataset_revision':binding.dataset_revision,'source_class':binding.source_class,
            'source_binding':asdict(binding),'metadata_census':[asdict(row) for row in rows],
            'F':F,'expected_ready':'2022-01-01T00:15:00Z','S':S,
            'full_census':[row.opportunity_id for row in rows],'training':training,'C':census,
            'I':ids('I'),'E':ids('E'),'P':ids('P'),
            'lineage_status':'NOT_STARTED','reason':'NO_ISSUE_COMPARISON' if not ids('I') else 'EXECUTION_NOT_AUTHORIZED',
            'scientific_starts':0,'numeric_work_performed':False}


def reference(ref):
    require(type(ref) is dict and {'path','bytes','sha256'}<=set(ref)
            <={'path','bytes','sha256','json_pointer','line_1based'}
            and text(ref['path']) and ref['path'].startswith('/')
            and type(ref['bytes']) is int and ref['bytes']>=0
            and type(ref['sha256']) is str and re.fullmatch('[a-f0-9]{64}',ref['sha256']),
            'SOURCE_REFERENCE')
    if 'json_pointer' in ref:
        require(type(ref['json_pointer']) is str and (not ref['json_pointer'] or ref['json_pointer'].startswith('/')),
                'SOURCE_REFERENCE_POINTER')
    if 'line_1based' in ref:require(type(ref['line_1based']) is int and ref['line_1based']>0,'SOURCE_REFERENCE_LINE')
    import json
    return json.dumps(ref,sort_keys=True,separators=(',',':'),allow_nan=False)


def adapt_metadata_row(row,binding):
    """Map DE's published row fields without parsing any numeric payload.

    File/hash/JSON-pointer verification belongs the bound input loader; this
    function validates references' shape, not their external bytes or rights.
    """
    binding.validate()
    fields={'A','B','D','Ghist_W_fold_S_transform_solver_fit_score_masks','X','capability_basis',
            'clock_assurance','decision_date','historical_D_feature_information_check',
            'history_metadata_ref','index','observed_clocks','opportunity_id',
            'opportunity_metadata_ref','source_row_ref'}
    require(type(row) is dict and set(row)==fields,'SOURCE_ROW_SCHEMA')
    require(type(row['index']) is int and row['index']>=0 and row['capability_basis']==binding.x_basis
            and binding.x_version==binding.dataset_revision and binding.b_version==binding.dataset_revision,
            'SOURCE_ROW_BASIS_VERSION')
    require(type(row['X']) is dict and set(row['X'])==set(SLOTS),'SOURCE_SLOT_ORDER')
    a=row['A'];b=row['B']
    require(type(a) is dict and a.get('A_status') in ('READY_CONDITIONAL','UNAVAILABLE')
            and type(a.get('A_reasons')) is list and type(b) is dict
            and b.get('status') in ('DEFINED_CONDITIONAL','UNDEFINED')
            and type(b.get('reasons')) is list,'SOURCE_STATUS')
    for key in ('history_metadata_ref','opportunity_metadata_ref','source_row_ref'):reference(row[key])
    common=Eligibility('OK' if a['A_status']=='READY_CONDITIONAL' else 'UNAVAILABLE',
        tuple(a['A_reasons']),a['A_required_K'],row['capability_basis'],binding.dataset_revision,
        'A_PACKET',reference(row['source_row_ref']))
    xs=[]
    for slot in SLOTS:
        x=row['X'][slot]
        require(type(x) is dict and set(x)=={'numeric_status','represented_source_payload','unit','source_ref','source_field'}
                and x['numeric_status'] in ('AVAILABLE_AS_STORED','UNAVAILABLE_AS_STORED')
                and x['source_field']==('LIQUIDITY' if slot=='MEDIAN_DV20' else slot),'SOURCE_X_SCHEMA')
        available=x['numeric_status']=='AVAILABLE_AS_STORED'
        require((x['represented_source_payload'] is not None)==available,'SOURCE_X_STATUS_VALUE')
        xs.append(Eligibility('OK' if available else 'UNAVAILABLE',() if available else ('SOURCE_X_UNAVAILABLE',),
            a['A_required_K'],row['capability_basis'],binding.dataset_revision,x['unit'],reference(x['source_ref'])))
    available=b['status']=='DEFINED_CONDITIONAL'
    require((b['represented_fraction'] is not None)==available,'SOURCE_B_STATUS_VALUE')
    target=Eligibility('OK' if available else 'UNAVAILABLE',tuple(b['reasons']),b['required_K'],
        binding.b_basis,binding.dataset_revision,b['unit'],reference(b['numeric_source_ref']))
    import json
    # Retain all nonnumeric source provenance, including null observed clocks.
    metadata={**row,'X':{slot:{k:v for k,v in row['X'][slot].items()
                             if k!='represented_source_payload'} for slot in SLOTS},
              'B':{k:v for k,v in b.items() if k!='represented_fraction'}}
    original=json.dumps(metadata,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    return Opportunity(row['opportunity_id'],row['D'],b['scheduled_end'],b['scheduled_end'],
                       common,tuple(xs),target,reference(row['source_row_ref']),row['decision_date'],original)
