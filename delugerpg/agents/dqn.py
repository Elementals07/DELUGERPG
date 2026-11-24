"""
DQN Agent for DelugeRPG — works for both MapEnv and BattleEnv.

Architecture (small, CPU-friendly, <50k params):
  Input → Linear(128) → ReLU → Linear(64) → ReLU → Linear(n_actions)

Uses:
  - Experience Replay Buffer (stores up to 10k transitions)
  - Epsilon-greedy exploration (starts random, becomes more confident over time)
  - Action masking (illegal moves get Q = -1e9 so agent never picks them)
  - Target network (a copy of Q-net updated every N steps for stable training)
"""

import random
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from collections import deque
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────
# Neural Network
# ─────────────────────────────────────────────

class QNetwork(nn.Module):
    """
    Small fully-connected Q-network.
    Input:  state vector (102 for MapEnv, 64 for BattleEnv)
    Output: Q-value for every possible action
    """
    def __init__(self, obs_dim: int, n_actions: int, hidden: int = 128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 64),
            nn.ReLU(),
            nn.Linear(64, n_actions)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())


# ─────────────────────────────────────────────
# Replay Buffer
# ─────────────────────────────────────────────

class ReplayBuffer:
    """
    Circular buffer that stores past (state, action, reward, next_state, done) tuples.
    Training samples random batches from here — this breaks correlation between steps.
    """
    def __init__(self, capacity: int = 10_000):
        self.buffer = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        self.buffer.append((
            np.array(state, dtype=np.float32),
            int(action),
            float(reward),
            np.array(next_state, dtype=np.float32),
            float(done)
        ))

    def sample(self, batch_size: int):
        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            torch.tensor(np.stack(states), dtype=torch.float32),
            torch.tensor(actions, dtype=torch.long),
            torch.tensor(rewards, dtype=torch.float32),
            torch.tensor(np.stack(next_states), dtype=torch.float32),
            torch.tensor(dones, dtype=torch.float32),
        )

    def __len__(self):
        return len(self.buffer)


# ─────────────────────────────────────────────
# DQN Agent
# ─────────────────────────────────────────────

class DQNAgent:
    """
    DQN Agent with:
    - Epsilon-greedy exploration (epsilon decays from 1.0 → 0.05)
    - Action masking (illegal moves blocked)
    - Target network (synced every target_update_freq steps)
    - Huber loss for stable training
    """

    def __init__(
        self,
        obs_dim: int,
        n_actions: int,
        lr: float = 1e-3,
        gamma: float = 0.99,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: int = 2000,       # steps until epsilon reaches minimum
        batch_size: int = 64,
        buffer_capacity: int = 10_000,
        target_update_freq: int = 200,   # steps between target network syncs
        hidden: int = 128,
    ):
        self.obs_dim = obs_dim
        self.n_actions = n_actions
        self.gamma = gamma
        self.epsilon_start = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        self.target_update_freq = target_update_freq

        # Q-network and target network (target is a stable copy, updated less often)
        self.q_net = QNetwork(obs_dim, n_actions, hidden)
        self.target_net = QNetwork(obs_dim, n_actions, hidden)
        self.target_net.load_state_dict(self.q_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.q_net.parameters(), lr=lr)
        self.loss_fn = nn.SmoothL1Loss()  # Huber loss — more stable than MSE
        self.replay = ReplayBuffer(buffer_capacity)

        self.total_steps = 0
        self.losses: List[float] = []

        print(f"DQNAgent ready: obs={obs_dim} actions={n_actions} params={self.q_net.param_count():,}")

    @property
    def epsilon(self) -> float:
        """Current exploration rate — decays linearly from start to end."""
        progress = min(self.total_steps / self.epsilon_decay, 1.0)
        return self.epsilon_start + progress * (self.epsilon_end - self.epsilon_start)

    def choose_action(self, obs: np.ndarray, action_mask: Optional[np.ndarray] = None) -> int:
        """
        Epsilon-greedy action selection with optional action masking.
        - With probability epsilon: pick a random LEGAL action
        - Otherwise: pick the action with the highest Q-value among LEGAL actions
        """
        # Determine legal actions from mask
        if action_mask is not None:
            legal = [i for i, m in enumerate(action_mask) if m > 0]
        else:
            legal = list(range(self.n_actions))

        if not legal:
            return 0  # fallback — should not happen

        if random.random() < self.epsilon:
            return random.choice(legal)
        else:
            with torch.no_grad():
                obs_t = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)
                q_vals = self.q_net(obs_t).squeeze(0).numpy()

            # Mask illegal actions with very negative value
            if action_mask is not None:
                for i in range(self.n_actions):
                    if action_mask[i] == 0:
                        q_vals[i] = -1e9

            return int(np.argmax(q_vals))

    def remember(self, state, action, reward, next_state, done):
        """Store one transition in replay buffer."""
        self.replay.push(state, action, reward, next_state, done)

    def learn(self) -> Optional[float]:
        """
        Sample a batch from replay buffer and update Q-network weights.
        Returns the loss value (or None if buffer not yet full enough).
        """
        if len(self.replay) < self.batch_size:
            return None

        self.total_steps += 1
        states, actions, rewards, next_states, dones = self.replay.sample(self.batch_size)

        # Current Q-values for the actions taken
        q_pred = self.q_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)

        # Target Q-values (Bellman equation):
        # Q_target = reward + gamma * max(Q_target_net(next_state)) * (1 - done)
        with torch.no_grad():
            q_next = self.target_net(next_states).max(1)[0]
            q_target = rewards + self.gamma * q_next * (1 - dones)

        loss = self.loss_fn(q_pred, q_target)

        self.optimizer.zero_grad()
        loss.backward()
        # Gradient clipping — prevents exploding gradients on CPU
        nn.utils.clip_grad_norm_(self.q_net.parameters(), max_norm=10.0)
        self.optimizer.step()

        # Sync target network periodically
        if self.total_steps % self.target_update_freq == 0:
            self.target_net.load_state_dict(self.q_net.state_dict())

        loss_val = loss.item()
        self.losses.append(loss_val)
        return loss_val

    def save(self, path: str):
        torch.save({
            "q_net_state": self.q_net.state_dict(),
            "optimizer_state": self.optimizer.state_dict(),
            "total_steps": self.total_steps,
            "losses": self.losses,
        }, path)
        print(f"Saved model to {path}")

    def load(self, path: str):
        ckpt = torch.load(path, map_location="cpu")
        self.q_net.load_state_dict(ckpt["q_net_state"])
        self.target_net.load_state_dict(ckpt["q_net_state"])
        self.optimizer.load_state_dict(ckpt["optimizer_state"])
        self.total_steps = ckpt.get("total_steps", 0)
        self.losses = ckpt.get("losses", [])
        print(f"Loaded model from {path} (step={self.total_steps})")
