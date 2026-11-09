"""S1 byte/ref/pointer closure. Numerical payload interpretation is deferred.

Locators are a trusted read-only mount allowlist, not caller-supplied paths in
Config. Only declared graph references may be followed; no transport/rebuild.
"""
from pathlib import Path
import re

from .hyp003_source import member_stream
from .hyp008_s1_contract import (canonical,sha,ref,decode,require,validate,closed,
                                NumberToken,MAX_FILE,MAX_LINE)
from .hyp008_s1_source import SourceBinding,adapt_metadata_row,prepare_metadata
from .hyp008_s1_numeric import SLOTS


def domain_int(value):
    if type(value) is NumberToken:
        require(re.fullmatch('0|[1-9][0-9]*',value.token) is not None and len(value.token)<=12,'METADATA_INTEGER')
        return int(value.token)
    require(type(value) is int and value>=0,'METADATA_INTEGER');return value


def metadata(value,key=None):
    """Convert only declared integer metadata; leave numeric payloads opaque."""
    if key in ('represented_source_payload','represented_fraction'):return value
    if key in ('index','bytes','line_1based'):return domain_int(value)
    if key=='A_action_indices':
        require(type(value) is list,'ACTION_INDICES');return [domain_int(x) for x in value]
    if type(value) is dict:return {k:metadata(v,k) for k,v in value.items()}
    if type(value) is list:return [metadata(v) for v in value]
    require(type(value) is not NumberToken,'UNDECLARED_NUMERIC_METADATA');return value


def typed_equal(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return set(a)==set(b) and all(typed_equal(a[k],b[k]) for k in a)
    if type(a) is list:return len(a)==len(b) and all(typed_equal(x,y) for x,y in zip(a,b))
    return a==b


def pointer(value,path):
    require(type(path) is str and (path=='' or path.startswith('/')),'JSON_POINTER')
    if path=='':return value
    for encoded in path[1:].split('/'):
        require(re.search(r'~(?![01])',encoded) is None,'JSON_POINTER_ESCAPE')
        key=encoded.replace('~1','/').replace('~0','~')
        if type(value) is dict:require(key in value,'JSON_POINTER_MISSING');value=value[key]
        elif type(value) is list:
            require(re.fullmatch('0|[1-9][0-9]*',key) is not None and len(key)<=8,'JSON_POINTER_INDEX')
            index=int(key);require(index<len(value),'JSON_POINTER_INDEX');value=value[index]
        else:require(False,'JSON_POINTER_PARENT')
    return value


class SourceGraph:
    def __init__(self,locators):
        require(type(locators) is dict,'TRUSTED_LOCATORS');self.locators=dict(locators)
        self.cache={};self.total=0;self.declared={};self.checks={}

    def raw(self,pin,coordinate=None):
        validate('Ref',pin);key=(coordinate,pin['sha256'])
        require((coordinate if coordinate is not None else pin['sha256']) in self.locators,'UNBOUND_SOURCE_LOCATOR')
        if key in self.cache:
            require(ref(self.cache[key])==pin,'REFERENCE_LENGTH');return self.cache[key]
        locator=self.locators.get(coordinate if coordinate is not None else pin['sha256'])
        require(isinstance(locator,(str,Path)),'UNBOUND_SOURCE_LOCATOR')
        path=Path(locator);require(path.is_absolute(),'SOURCE_LOCATOR_ABSOLUTE')
        with member_stream(path.parent,path.name,MAX_FILE) as stream:raw=stream.read(MAX_FILE+1)
        require(len(raw)<=MAX_FILE and self.total+len(raw)<=512*1024**2,'SOURCE_BYTE_BOUND')
        require(ref(raw)==pin,'SOURCE_BYTE_HASH');self.cache[key]=raw;self.total+=len(raw)
        return raw

    def declare(self,table):
        closed(table,('schema','closure_scope','references'),'polar.private-consumer-source-refs/1')
        require(type(table['references']) is dict and len(table['references'])<=10000,'SOURCE_GRAPH_BOUND')
        for coordinate,item in table['references'].items():
            require(type(item) is dict and set(item)=={'path','sha256','bytes','roles'} and
                item['path']==coordinate and type(coordinate) is str and coordinate.startswith('/')
                and type(item['roles']) is list and item['roles'] and all(type(s) is str for s in item['roles']), 'SOURCE_GRAPH_MEMBER')
            require(not any(part.lower() in ('models','predictions','losses','credentials') for part in Path(coordinate).parts),'FORBIDDEN_SOURCE_ROLE')
            pin={'sha256':item['sha256'],'bytes':domain_int(item['bytes'])};validate('Ref',pin)
            self.declared[coordinate]=pin

    def resolve(self,reference):
        require(type(reference) is dict and {'path','bytes','sha256'}<=set(reference)
            <={'path','bytes','sha256','json_pointer','line_1based'},'SOURCE_REFERENCE')
        coordinate=reference['path'];pin={k:reference[k] for k in ('sha256','bytes')}
        require(coordinate in self.declared and self.declared[coordinate]==pin,'UNDECLARED_SOURCE_REFERENCE')
        raw=self.raw(pin,coordinate)
        if 'line_1based' in reference:
            line=domain_int(reference['line_1based']);require(line>0,'SOURCE_LINE')
            lines=raw.splitlines(keepends=True);require(line<=len(lines),'SOURCE_LINE')
            raw=lines[line-1];require(len(raw)<=MAX_LINE,'SOURCE_LINE_BOUND')
        value=decode(raw,opaque=True)
        value=pointer(value,reference.get('json_pointer',''))
        key=sha(canonical(reference))
        self.checks[key]={'reference':reference,'status':'MATCHED_BYTES_POINTER','raw_line_sha256':sha(raw) if 'line_1based' in reference else None}
        return value


def prepare_source(config,locators):
    validate('Config',config)
    binding_raw=config['source_binding'];binding=SourceBinding(**{**binding_raw,'x_units':tuple(binding_raw['x_units'])})
    binding.validate();graph=SourceGraph(locators);inputs=config['inputs']
    require(binding.content_sha256==inputs['content_manifest']['sha256'] and
            binding.delivery_sha256==inputs['delivery_manifest']['sha256'],'SOURCE_BINDING_INPUTS')
    manifest=decode(graph.raw(inputs['content_manifest']),opaque=True)
    require(type(manifest) is dict and manifest.get('schema')=='polar.hyp008-private-consumer-content/1'
        and manifest.get('revision')==binding.dataset_revision and manifest.get('feature_order')==list(SLOTS)
        and domain_int(manifest['rows'])==binding.census_count,'SOURCE_CONTENT_MANIFEST')
    require(metadata(manifest['objects']['rows.ndjson'])==inputs['rows'] and
        metadata(manifest['objects']['references.json'])==inputs['references'],'SOURCE_CONTENT_MEMBERS')
    delivery=decode(graph.raw(inputs['delivery_manifest']),opaque=True)
    require(type(delivery) is dict and delivery.get('schema')=='polar.private-dataset-delivery-package/1'
        and delivery.get('revision')==binding.dataset_revision and
        all(metadata(delivery['files'][name])==inputs[role] for name,role in
            [('content-manifest.json','content_manifest'),('rows.ndjson','rows'),('references.json','references')]),'SOURCE_DELIVERY')
    graph.raw(inputs['descriptor'])  # Value-free schema description, exact pin retained.
    table=metadata(decode(graph.raw(inputs['references']),opaque=True));graph.declare(table)
    raw=graph.raw(inputs['rows']);lines=raw.splitlines(keepends=True)
    require(len(lines)==binding.census_count and all(len(line)<=MAX_LINE for line in lines),'SOURCE_ROW_COUNT_BOUND')
    roster_paths=[coordinate for coordinate in graph.declared
                  if Path(coordinate).name=='roster.ndjson' and
                  'DECLARED_PRIMITIVE_OR_OPERATOR_ANCESTRY' in table['references'][coordinate]['roles']]
    require(len(roster_paths)==1,'SOURCE_ROSTER_GRAPH')
    roster_path=roster_paths[0];roster_raw=graph.raw(graph.declared[roster_path],roster_path)
    roster_lines=roster_raw.splitlines(keepends=True)
    roster_keys=[decode(line,opaque=True).get('key') for line in roster_lines]
    require(all(type(key) is str for key in roster_keys) and len(set(roster_keys))==len(roster_keys),'SOURCE_ROSTER_DUPLICATE_KEY')
    rows=[];opportunities=[]
    for index,line in enumerate(lines):
        row=metadata(decode(line,opaque=True));require(row['index']==index,'SOURCE_ROW_ORDINAL')
        opportunities.append(adapt_metadata_row(row,binding))
        for name in ('history_metadata_ref','opportunity_metadata_ref'):
            require(row[name].get('line_1based')==index+1,'SOURCE_METADATA_LINE');graph.resolve(row[name])
        require(set(row['source_row_ref'])=={'path','bytes','sha256'},'SOURCE_PER_DATE_ROOT_REF')
        original=graph.resolve(row['source_row_ref'])
        require(type(original) is dict and original.get('D_date')==row['decision_date']
                and original.get('D')==row['D'],'SOURCE_ORIGINAL_ROW')
        require(all(typed_equal(original.get(key),row['A'][key]) for key in
                    ('A_status','A_reasons','A_required_K')),'SOURCE_A_METADATA')
        opportunity=graph.resolve(row['opportunity_metadata_ref'])
        require(typed_equal(original.get('B_open_dates'),row['B']['open_dates']) and
                typed_equal(original.get('B_required_K'),row['B']['required_K']) and
                typed_equal(opportunity.get('end'),row['B']['scheduled_end']),'SOURCE_B_METADATA')
        components=original.get('B_constituents')
        require(type(components) is list and len(components)==4,'SOURCE_CONSTITUENTS')
        projected=[{k:v[k] for k in ('key','stored_K','reason','mark_kind')} for v in components]
        require(typed_equal(projected,row['B']['component_metadata']) and
                typed_equal(projected,opportunity.get('component_metadata')),'SOURCE_COMPONENT_METADATA')
        require(opportunity.get('decision_date')==row['decision_date'] and opportunity.get('D')==row['D'],'SOURCE_OPPORTUNITY_ID')
        roster_refs=metadata(opportunity.get('roster_pointers'))
        require(roster_refs==row['B']['original_source_roster_refs'] and len(roster_refs)==4
                and [r['key'] for r in roster_refs]==[row['decision_date']+':'+symbol for symbol in ('AAPL','AMZN','TSLA','TWTR')],'SOURCE_ROSTER_POINTERS')
        for item in roster_refs:
            require(type(item) is dict and set(item)=={'key','line_1based','raw_line_sha256'},'SOURCE_ROSTER_REF')
            line1=domain_int(item['line_1based']);require(1<=line1<=len(roster_lines),'SOURCE_ROSTER_LINE')
            raw_line=roster_lines[line1-1];require(len(raw_line)<=MAX_LINE and sha(raw_line)==item['raw_line_sha256'],'SOURCE_ROSTER_RAW_LINE_HASH')
            require(roster_keys[line1-1]==item['key'],'SOURCE_ROSTER_KEY')
            graph.checks[sha(canonical(item))]={'reference':item,'status':'MATCHED_ROSTER_RAW_LINE_KEY','roster_ref':graph.declared[roster_path]}

        for slot in SLOTS:
            field='LIQUIDITY' if slot=='MEDIAN_DV20' else slot
            reference=row['X'][slot]['source_ref']
            require({k:v for k,v in reference.items() if k!='json_pointer'}==row['source_row_ref'],'SOURCE_X_PARENT_REF')
            require(reference.get('json_pointer')=='/A_values/'+field,'SOURCE_SLOT_POINTER')
            if row['A']['A_status']=='UNAVAILABLE':
                require(row['X'][slot]['represented_source_payload'] is None and original.get('A_values') is None,'SOURCE_UNAVAILABLE_PARENT')
                require(reference['path']==row['source_row_ref']['path'] and reference['sha256']==row['source_row_ref']['sha256']
                        and reference['bytes']==row['source_row_ref']['bytes'],'SOURCE_UNAVAILABLE_PARENT')
            else:
                require(typed_equal(graph.resolve(reference),row['X'][slot]['represented_source_payload']),'SOURCE_X_POINTER_VALUE')
        for name in ('numeric_source_ref','binary64_projection_ref','source_constituents_ref'):
            require({k:v for k,v in row['B'][name].items() if k!='json_pointer'}==row['source_row_ref'],'SOURCE_B_PARENT_REF')
        require(row['B']['numeric_source_ref'].get('json_pointer')=='/B_value_represented_fraction','SOURCE_B_POINTER')
        require(typed_equal(graph.resolve(row['B']['numeric_source_ref']),row['B']['represented_fraction']),'SOURCE_B_POINTER_VALUE')
        for name in ('binary64_projection_ref','source_constituents_ref'):graph.resolve(row['B'][name])
        rows.append(row)
    masks=prepare_metadata(tuple(opportunities),binding)
    source={'schema':'polar.hyp008-s1-source/1','inputs':inputs,'graph':table,
        'metadata_refs':[{'opportunity_id':row['opportunity_id'],'source_row_ref':row['source_row_ref'],
            'history_metadata_ref':row['history_metadata_ref'],'opportunity_metadata_ref':row['opportunity_metadata_ref'],
            'source_line_sha256':sha(line)} for row,line in zip(rows,lines)],
        'closure_checks':[graph.checks[k] for k in sorted(graph.checks)],
        'assurance':{'source_class':binding.source_class,'capability':'SOURCE_COHORT_CAPABILITY_ONLY',
                     'historical_observed_clocks':'NOT_UPGRADED','original_HYP':'UNTESTED','financial':'NOT_ASSESSED'}}
    return masks,source,tuple(rows)
