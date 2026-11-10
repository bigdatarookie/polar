"""The selected 23-input causal allocation environment, not a generic RL engine."""
from fractions import Fraction
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from .ci_research import require, instant
from .research_allocation import ReferenceLedger


class ReferenceAllocationEnv(gym.Env):
    metadata = {'render_modes': []}

    def __init__(self, market, anchor, terminal, tz):
        super().__init__()
        require(len(market['symbols']) == 4 and market['symbols'] == sorted(market['symbols']), 'PPO_SYMBOL_ORDER')
        self.symbols=list(market['symbols']);self.days=list(market['dates']);self.tz=tz
        self.prices={d:dict(market['prices_micro'][d]) for d in self.days}
        self.anchor=self.days.index(anchor);self.terminal=self.days.index(terminal)
        require(60<=self.anchor<self.terminal,'PPO_WINDOW')
        # Parse exact decimal quote text to float64 once. These features never feed accounting.
        self.quotes=np.asarray([[np.float64(f'{self.prices[d][s]//1000000}.{self.prices[d][s]%1000000:06d}')
                                 for s in self.symbols] for d in self.days],dtype=np.float64)
        require(np.isfinite(self.quotes).all() and (self.quotes>0).all(),'PPO_FEATURE_QUOTES')
        self.action_space=spaces.Discrete(5)
        self.observation_space=spaces.Box(low=-1.,high=1.,shape=(23,),dtype=np.float32)
        self.total_transitions=0;self.current=None

    def _prices(self,index):return self.prices[self.days[index]]

    def _observation(self):
        i=self.current;values=[]
        for j in range(4):
            p=self.quotes[:,j]
            r20=np.log(np.float64(p[i]/p[i-20]));r60=np.log(np.float64(p[i]/p[i-60]))
            daily=np.log(np.asarray(p[i-19:i+1]/p[i-20:i],dtype=np.float64))
            mean=np.sum(daily,dtype=np.float64)/np.float64(20)
            var=np.sum(np.square(daily-mean),dtype=np.float64)/np.float64(19)
            vol=np.sqrt(var)*np.sqrt(np.float64(252))
            values.extend([np.clip(r20,-1.,1.),np.clip(r60,-1.,1.),min(np.float64(2),vol)/np.float64(2)])
        mark=self.ledger.mark(self._prices(i));nav=np.float64(mark['nav_cents'])
        values.extend(np.float64(mark['position_cents'][s])/nav for s in self.symbols)
        values.append(np.float64(mark['cash_cents'])/nav)
        values.extend(int(self.ledger.previous_target==a) for a in range(5))
        values.append(np.float64(self.terminal-i)/np.float64(self.terminal-self.anchor))
        result=np.asarray(values,dtype=np.float32)
        require(result.shape==(23,) and np.isfinite(result).all() and self.observation_space.contains(result), 'PPO_OBSERVATION_DOMAIN')
        return result

    def _record(self,mark):
        ns=instant(self.days[self.current],16,0,self.tz)
        return {'date':self.days[self.current],'nominal_ns':ns,'sample_ns':ns+1000,**mark}

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:self.action_space.seed(seed)
        self.current=self.anchor;self.ledger=ReferenceLedger(self.symbols);self.done=False
        self.episode_transitions=0;self.intents=[]
        self.nav=[self._record(self.ledger.mark(self._prices(self.current)))]
        return self._observation(), {'date':self.days[self.current],'previous_target':0}

    def step(self, action):
        require(self.current is not None and not self.done,'PPO_EPISODE_TERMINATED')
        require(isinstance(action,(int,np.integer)) and not isinstance(action,(bool,np.bool_)) and 0<=int(action)<=4,'PPO_ACTION_DOMAIN')
        action=int(action);old=self.nav[-1]['nav_cents'];next_index=self.current+1
        intent=self.ledger.action_intent(action,self._prices(self.current),terminal=next_index==self.terminal)
        self.intents.append({'formation':self.days[self.current],'execution_date':self.days[next_index],
                             'requested_action':action,'previous_target':self.ledger.previous_target,**intent})
        mark=self.ledger.execute(intent,self._prices(next_index),date=self.days[next_index])
        self.current=next_index;self.episode_transitions+=1;self.total_transitions+=1
        self.nav.append(self._record(mark));self.done=self.current==self.terminal
        reward=np.log(np.float64(mark['nav_cents'])/np.float64(old))
        require(np.isfinite(reward),'PPO_REWARD_NONFINITE')
        ratio=Fraction(mark['nav_cents'],old)
        info={'date':self.days[self.current],'nav_cents':mark['nav_cents'],
              'reward_repr':repr(float(reward)),'exact_nav_ratio':[ratio.numerator,ratio.denominator],
              'previous_target':self.ledger.previous_target,'episode_transitions':self.episode_transitions,
              'total_transitions':self.total_transitions,'terminal_action_ignored':self.done}
        return self._observation(),float(reward),self.done,False,info
