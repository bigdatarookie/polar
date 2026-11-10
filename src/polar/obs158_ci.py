"""Explicit PUBLIC invented CI admission; retained/source-host admission unchanged.

The job owns resources. This path observes checkout/runtime directly instead of
fabricating a host launcher receipt. It cannot admit RETAINED inputs.
"""
from importlib.metadata import version
import os
from pathlib import Path
import subprocess
import sys
from .obs158_contract import canonical, decode, sha
from .obs158_data import Inputs, MEMBERS, PUBLIC_SHA, METRIC_SHA, read_bound
from .obs158_math import require

CALENDAR_SHA='803aaef74549c4887ce7838a1667b7c5e3068e5d6ea661b421baa7331b2de1bb'
TIMEZONE_SHA='d7f2206b3a45989fc9ad63d558922532fa7352280d5f87176bf1db79cb1d1fa9'


def runtime(config, code):
    require(config['source_class']=='INVENTED' and
            config['input_config']['schema']=='polar.obs158-ci-input-config/1' and
            os.environ.get('POLAR_CI_SCENARIO')=='obs158' and sys.platform=='linux',
            'OBS158_CI_PUBLIC_ONLY')
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],text=True).strip()
    require(config['candidate']=={'commit':head,'tree':tree},'OBS158_CI_CHECKOUT_BINDING')
    require(os.environ.get('POLAR_CI_RUNTIME_IMAGE_ID')==config['image_id'],
            'OBS158_CI_IMAGE_BINDING')
    require(version('nautilus-trader')=='1.231.0','OBS158_CI_NATIVE_VERSION')
    return {'schema':'polar.obs158-ci-observed-runtime/1','lifecycle':'SHARED_CI_JOB',
            'candidate':config['candidate'],'image_id':config['image_id'],
            'actual_uid':os.geteuid(),'platform':sys.platform,'native':'nautilus_trader/1.231.0',
            'source_code_sha256':sha(canonical(code)),
            'external_host_guard':'NOT_REQUIRED_FOR_PUBLIC_CI', 'financial':'NOT_ASSESSED'}


def inputs(config):
    c=config['input_config']
    require(config['source_class']=='INVENTED' and set(c)=={'schema','profile_ref','fixture_ref','calendar_ref','timezone_ref'}
            and c['schema']=='polar.obs158-ci-input-config/1','OBS158_CI_INPUT_SCHEMA')
    profile=read_bound(c['profile_ref'],1024**2);p=decode(profile)
    require(set(p)=={'public_sha256','metric_sha256','members','projection'} and
            p['public_sha256']==PUBLIC_SHA and p['metric_sha256']==METRIC_SHA and
            p['projection']=='EXACT_PUBLIC_COHORT_CALENDAR_ACTION_MEMBERS_NO_PRIVATE_PATHS',
            'OBS158_CI_PROFILE_BINDING')
    expected={'cohort-order-v1.json': 'cf08cb1196fce104bc41806d038d6fb44a159e7803dc69ef234d2a5507262ed4', 'calendar-profile-v1.json': '030354eacee6b3d358ca921e48164c5c48b5d0a94ee7d9494e53b97652d39377', 'action-profile-v1.json': '56f3e7ec1682f397ddf0fcd92589baf37ffab0f3c9dd0ad9bf0076a1b4b2c44f'}
    require(set(p['members'])==set(expected) and all(sha(canonical(p['members'][n]))==expected[n] for n in expected),
            'OBS158_CI_PUBLIC_MEMBER_BINDING')
    cal=read_bound(c['calendar_ref'],1024**2);tz=read_bound(c['timezone_ref'],1024**2)
    require(sha(cal)==CALENDAR_SHA and sha(tz)==TIMEZONE_SHA,'OBS158_CI_CALENDAR_TIMEZONE_BINDING')
    raw=read_bound(c['fixture_ref']);f=decode(raw)
    require(set(f)=={'schema','rows','context'} and f['schema']=='polar.obs158-invented-input/1'
            and f['context']=={'pointer_scope':'PUBLIC_DETERMINISTIC_SYNTHETIC_NO_PROVIDER'},
            'OBS158_CI_INVENTED_FIXTURE')
    aliases=p['members']['cohort-order-v1.json']['symbols_in_route_order']
    dates=p['members']['calendar-profile-v1.json']['reference_dates']
    expected_keys={'source_symbol','reference_date','adjustment','feed','currency','asof',
        'raw_fields_exact_tokens','aggregation_label','estimated_K','raw_open','raw_high',
        'raw_low','raw_close','raw_volume','event_open_at','event_close_at',
        'observed_published_at','observed_historical_available_at','economic_security_id'}
    require(len(f['rows'])==len(aliases)*len(dates)==39974,'OBS158_CI_FULL_PUBLIC_GRID')
    for index,row in enumerate(f['rows']):
        expected_tokens={'o':'31.5000','h':'31.500250','l':'31.500000','c':'31.500250',
                         'v':'0' if index<960 else '1000000'}
        require(set(row)==expected_keys and row['raw_fields_exact_tokens']==expected_tokens and
                row['source_symbol']==aliases[index%158] and row['reference_date']==dates[index//158],
                'OBS158_CI_DETERMINISTIC_PUBLIC_ONLY')
    refs={'profile':{'sha256':sha(profile),'bytes':len(profile)},
          'fixture':{'sha256':sha(raw),'bytes':len(raw)},'calendar':{'sha256':sha(cal),'bytes':len(cal)},
          'timezone':{'sha256':sha(tz),'bytes':len(tz)}}
    return Inputs(profile,tuple(canonical(row) for row in f['rows']),tuple(decode(cal)['sessions']),
                  tz,canonical(f['context']),canonical(refs),'INVENTED')
