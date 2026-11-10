"""Selected Gymnasium contract: no retained data, PPO training or financial result."""
from datetime import date,timedelta,timezone
import copy
import numpy as np
from stable_baselines3.common.env_checker import check_env
from polar.reference_env import ReferenceAllocationEnv


def market():
    days=[(date(2020,1,1)+timedelta(days=i)).isoformat() for i in range(70)]
    symbols=['AAA','BBB','CCC','DDD']
    return {'dates':days,'symbols':symbols,'prices_micro':{
        d:{s:10000000+10000*i+100*j for j,s in enumerate(symbols)} for i,d in enumerate(days)}}


def test_gym_contract_causal_observation_and_true_terminal():
    m=market();env=ReferenceAllocationEnv(m,m['dates'][60],m['dates'][65],timezone.utc)
    check_env(env,warn=True)
    obs,_=env.reset(seed=0);assert obs.dtype==np.float32 and obs.shape==(23,)
    future=copy.deepcopy(m)
    for d in m['dates'][61:]:future['prices_micro'][d]['AAA']=1000000000000000
    other=ReferenceAllocationEnv(future,m['dates'][60],m['dates'][65],timezone.utc)
    alt,_=other.reset(seed=0);np.testing.assert_array_equal(obs,alt)
    for i in range(5):
        obs,reward,done,truncated,info=env.step(1 if i<4 else 2)
        assert done==(i==4) and truncated is False and np.isfinite(reward)
    assert env.ledger.previous_target==0 and not any(env.ledger.held.values())
    assert info['terminal_action_ignored'] is True
    assert obs[-1]==0 and obs[17]==1 # terminal previous requested target is CASH


def test_zero_fill_keeps_requested_target_in_observation_and_same_action_holds():
    m=market()
    for day in m['dates']:m['prices_micro'][day]['AAA']=10**18
    m['prices_micro'][m['dates'][62]]['AAA']=1000000
    env=ReferenceAllocationEnv(m,m['dates'][60],m['dates'][65],timezone.utc);env.reset()
    obs,_,_,_,_=env.step(1)
    assert env.ledger.held['AAA']==0 and env.ledger.previous_target==1 and obs[18]==1
    env.step(1)
    assert env.ledger.held['AAA']==0 and not env.ledger.fills
