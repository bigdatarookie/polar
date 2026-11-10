"""Bounded invented mature-library training and fixed-trace native reconciliation."""
from datetime import date,timedelta,timezone
import numpy as np
from polar.reference_ppo import train_seed,deterministic_episode,native_test_plan,reconcile_selected
from polar.ci_research_native import simulate


def test_actual_ppo_rollout_true_terminals_and_final_native_trace():
    days=[(date(2020,1,1)+timedelta(days=i)).isoformat() for i in range(100)]
    symbols=['AAPL','AMZN','TSLA','VTI']
    market={'dataset_revision':'INVENTED-PPO-ROLLOUT','dates':days,'symbols':symbols,
        'prices_micro':{d:{s:10000000+i*(j+1)*10000+(i%7)*1000 for j,s in enumerate(symbols)}
                        for i,d in enumerate(days)}}
    model,audit=train_seed(market,days[60],days[70],timezone.utc,0,invented_steps=256)
    assert audit['actual_timesteps']==256 and audit['actual_rollouts']==1
    assert audit['actual_epoch_updates']==10 and audit['actual_optimizer_steps']==40
    assert len(audit['resets'])==26 and not audit['budget_stop_is_episode_terminal']
    assert audit['rows'] if 'rows' in audit else audit['transitions']
    terminal=[r for r in audit['transitions'] if r['terminated']]
    assert len(terminal)==25
    assert all(r['next_observation'][-1]==0 and r['info']['terminal_action_ignored'] for r in terminal)
    assert all(not any(r['ledger']['positions'].values()) for r in terminal)
    assert audit['last_environment_state']['date']==days[66] # no invented budget-end liquidation
    episode=deterministic_episode(model,market,days[70],days[80],timezone.utc)
    assert len(episode['rows'])==10 and len(episode['nav'])==11
    assert all(row['action']==int(np.argmax(row['probabilities'])) for row in episode['rows'])
    plan=native_test_plan(market,episode,timezone.utc)
    native=simulate(plan)
    assert reconcile_selected(episode,native)['status']=='MATCHED'
    assert len(native['legs'])==5
    assert all(not any(leg['nav'][-1]['positions'].values()) for leg in native['legs'])
