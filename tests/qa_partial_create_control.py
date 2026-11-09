"""Affected-only actual partial-create control; independent review required before use."""
from pathlib import Path
import hashlib
import json
import os
import re
import sys

BASE='09b2df96bbaaa6ceba24ac448fed27f002a291e7'
TREE='75ab142ddd8ad6704b8c2c3fcce9cbc49028975a'
SOURCE_SHA='df5bae9b28d89324ed3199ead184c60216c16626b20587ced8d70be2018d0fe9'


def main():
    # Import only exact accepted helper bytes, never an ambient installation.
    source=Path(__file__).resolve().parents[1]/'src'
    module=source/'polar/qa_environment.py'
    if hashlib.sha256(module.read_bytes()).hexdigest()!=SOURCE_SHA:
        raise ValueError('ACCEPTED_SOURCE_REQUIRED')
    if len(sys.argv)!=3 or sys.version_info[:2]!=(3,13):raise ValueError('BOUND_ARGUMENTS_RUNTIME')
    sys.path.insert(0,str(source))
    from polar.qa_environment import Environment,Docker,Commands,Gap,config,decode,read,write
    if Path(sys.modules['polar.qa_environment'].__file__).resolve()!=module:
        raise ValueError('SOURCE_ORIGIN')
    cfg=config(decode(read(Path(sys.argv[1]).resolve(),65536)))
    if cfg['commit']!=BASE or cfg['tree']!=TREE:raise ValueError('MERGED_BASE_REQUIRED')
    root=Path(sys.argv[2]);report=root.parent/'partial-create-result.json'
    if report.exists() or root.exists():raise ValueError('FRESH_TASK_PATH_REQUIRED')
    commands=Commands();docker=None;env=None;before=None;prepared=None;cleanup=None
    outcome={'schema':'polar.qa-partial-create-control/1','base':BASE,'tree':TREE,
             'source_sha256':SOURCE_SHA,'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'injection':'BEFORE_API_CREATE_AFTER_BACKEND_CREATED','status':'NOT_RUN',
             'container_starts':0,'http_calls':0,'partial_resume':'NOT_RUN','prior_results':'UNCHANGED'}

    class Interrupted(Docker):
        creates=0;blocked_api=0
        def create_network(self,name,labels,*,internal=True):
            if not internal or self.creates:raise Gap('COMMAND_FAILED')
            self.creates+=1
            return super().create_network(name,labels,internal=internal)
        def create_api(self,*args):
            self.blocked_api+=1
            raise Gap('COMMAND_FAILED')  # Deliberate failure BEFORE any container create.
        def create_proxy(self,*args):raise Gap('COMMAND_FAILED')
        def start(self,*args):raise Gap('COMMAND_FAILED')

    def ids(docker):
        result={}
        for kind,args in [('containers',('container','ls','-a','--no-trunc')),
                          ('networks',('network','ls','--no-trunc')),('volumes',('volume','ls'))]:
            values=docker.run(*args,'--format','{{.ID}}' if kind!='volumes' else '{{.Name}}').decode().splitlines()
            if len(values)!=len(set(values)):raise ValueError('AMBIGUOUS_RESOURCE_LIST')
            result[kind]=sorted(values)
        return result

    try:
        docker=Interrupted(commands);before=ids(docker)
        outcome['before']=before
        env=Environment(root,commands,docker)
        prepared=env.prepare(cfg)
        outcome['prepare']=prepared
        if not (prepared['status']=='NOT_PREPARED' and prepared['reason']=='COMMAND_FAILED'
                and set(prepared['resources'])=={'net'} and docker.blocked_api==1 and docker.creates==1):
            raise ValueError('INJECTION_BOUNDARY')
        net_id=prepared['resources']['net']
        if not re.fullmatch('[a-f0-9]{64}',net_id):raise ValueError('FULL_ID_REQUIRED')
        owner,state,bound=env.state()
        _,net=env.resource(owner,state,bound,'net')
        if net['Id']!=net_id or not net['Internal'] or net['Containers']:
            raise ValueError('BACKEND_NOT_EXACT_EMPTY_INTERNAL')
        for role in ('api','proxy','front'):
            if env.resource(owner,state,bound,role)[1] is not None:raise ValueError('NOT_PARTIAL_SUBSET')
        outcome['observed_owned_subset']={'net':net_id}
        outcome['phase']=state['phase']
        if state['phase']!='CONTAINER_INTENT':raise ValueError('PHASE_MISMATCH')
        outcome['status']='PARTIAL_BOUNDARY_OBSERVED'
    except Exception as exc:
        outcome['status']='FAIL';outcome['reason']=type(exc).__name__+':'+str(exc)[:128]
    finally:
        # The accepted helper verifies complete ownership before exact-ID removal.
        # No prune, daemon-wide cleanup, repeat prepare, container start or HTTP.
        if env is not None and (root/'state.json').is_file():
            try:
                owner,_,_=env.state()
                cleanup=env.cleanup(owner['operation'],owner['config_sha256'])
                outcome['cleanup']=cleanup
            except Exception as exc:
                outcome['cleanup_error']=type(exc).__name__
        if docker is not None and before is not None:
            try:
                outcome['after']=ids(docker)
                if cleanup and cleanup['status']=='CLEANED' and outcome['after']==before:
                    if outcome['status']=='PARTIAL_BOUNDARY_OBSERVED':outcome['status']='PASS'
                else:outcome['status']='FAIL'
            except Exception as exc:
                outcome['status']='FAIL';outcome['final_observation_error']=type(exc).__name__
        write(report,outcome,True)
    return 0 if outcome['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
