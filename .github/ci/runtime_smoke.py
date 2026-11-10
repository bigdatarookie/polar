"""Public synthetic API smoke; no market ledger, private data or economic verdict."""
import json
import importlib.metadata
import numpy as np
import torch
import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env

assert torch.version.cuda is None, "CPU_WHEEL_REQUIRED"
assert not torch.cuda.is_available(), "CPU_ONLY_RUNTIME_REQUIRED"
torch.set_num_threads(1)
torch.set_num_interop_threads(1)

class SyntheticAPIEnv(gym.Env):
    observation_space = gym.spaces.Box(-1.0, 1.0, shape=(23,), dtype=np.float32)
    action_space = gym.spaces.Discrete(5)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.tick = 0
        return np.zeros(23, dtype=np.float32), {}

    def step(self, action):
        assert self.action_space.contains(action)
        self.tick += 1
        return np.full(23, self.tick / 8, dtype=np.float32), float(action == 2), self.tick == 8, False, {}

# Exercise the accepted caller kernel, not a replacement or a scientific fit.
from polar.hyp007_numeric import numpy as guarded_numpy, ridge_fit, ridge_predict
assert guarded_numpy().__version__ == "2.2.6"
toy = guarded_numpy().array([[0., 0., 0., 0.], [1., 0., 1., 0.], [0., 1., 0., 1.]])
synthetic_ridge = ridge_fit(toy, [0., 1., -1.])
assert all(np.isfinite(ridge_predict(synthetic_ridge, toy)))

env = SyntheticAPIEnv()
check_env(env)
model = PPO("MlpPolicy", env, n_steps=16, batch_size=16, n_epochs=1,
            policy_kwargs={"net_arch": [8]}, seed=7, device="cpu", verbose=0)
model.learn(total_timesteps=32)
observation, _ = env.reset(seed=7)
action, _ = model.predict(observation, deterministic=True)
assert env.action_space.contains(action)
assert model.num_timesteps == 32
print(json.dumps({"schema": "polar.cpu-rl-runtime-smoke/1", "status": "PASS",
    "dependencies": {n: importlib.metadata.version(n) for n in ["numpy", "stable-baselines3", "gymnasium", "torch", "threadpoolctl"]},
    "device": str(model.device), "threads": torch.get_num_threads(), "cuda": torch.version.cuda,
    "synthetic_train_steps": model.num_timesteps,
    "scope": "Synthetic API/import/CPU-training smoke only; no financial data, ledger qualification or economic result"}))
