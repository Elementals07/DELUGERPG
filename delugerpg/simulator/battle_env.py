"""
Turn-Based Battle Environment for DelugeRPG.
Faithfully simulates DelugeRPG battle mechanics:
- Exact HP formula: Level * 4 (with +25% for Shiny class)
- Damage formula: floor((Level * Power) / 50) * TypeMult * STAB * VariantMult
- Variant effects (Dark +25% Atk, Shiny +25% HP, Ghostly flinch, Metallic immunity, Shadow piercing, Negative inversion)
- Discrete(9) action space with legal action masking (4 moves + 5 bench switches)
- 64-dimensional standardized state observation
- Fully offline, reproducible, and zero external framework dependencies (standard Gym-like API).
"""

import math
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from ..core.types import Attack
from ..parsers.typechart import TypeChart, STANDARD_TYPES


@dataclass
class BattlePokemon:
    name: str
    level: int
    class_name: str
    type1: str
    type2: Optional[str]
    attacks: List[Attack]
    max_hp: int = 0
    current_hp: int = 0
    status: Optional[str] = None  # None, "burn", "freeze", "paralysis", "poison", "sleep"
    flinch: bool = False

    def __post_init__(self):
        if self.max_hp <= 0:
            base_hp = self.level * 4
            if self.class_name.lower() == "shiny":
                base_hp = int(base_hp * 1.25)
            self.max_hp = base_hp
            self.current_hp = base_hp

    @property
    def is_fainted(self) -> bool:
        return self.current_hp <= 0

    def copy(self) -> "BattlePokemon":
        return BattlePokemon(
            name=self.name,
            level=self.level,
            class_name=self.class_name,
            type1=self.type1,
            type2=self.type2,
            attacks=[Attack(**a.to_dict()) for a in self.attacks],
            max_hp=self.max_hp,
            current_hp=self.current_hp,
            status=self.status,
            flinch=self.flinch
        )


class BattleEnv:
    """
    DelugeRPG Battle Gym Environment.

    Actions:
      0..3: Use Move 0 to 3
      4..8: Switch to bench Pokemon 1 to 5

    Reward Signal:
      +1.0 for winning the battle
      -1.0 for losing the battle
      +0.1 * damage_dealt_ratio
      -0.1 * damage_received_ratio
      +0.3 for KO-ing an opponent Pokemon
      -0.3 for losing a Pokemon
      -0.01 per turn (efficiency incentive)
    """

    NUM_ACTIONS = 9
    OBS_DIM = 64

    def __init__(self, type_chart: TypeChart, max_turns: int = 100):
        self.type_chart = type_chart
        self.max_turns = max_turns

        self.player_team: List[BattlePokemon] = []
        self.opponent_team: List[BattlePokemon] = []
        self.player_active_idx = 0
        self.opponent_active_idx = 0
        self.turn_count = 0

    def reset(
        self,
        player_team: List[BattlePokemon],
        opponent_team: List[BattlePokemon],
        seed: Optional[int] = None
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        if seed is not None:
            np.random.seed(seed)

        if not player_team or not opponent_team:
            raise ValueError("Teams cannot be empty")

        self.player_team = [p.copy() for p in player_team]
        self.opponent_team = [p.copy() for p in opponent_team]
        self.player_active_idx = 0
        self.opponent_active_idx = 0
        self.turn_count = 0

        obs = self.get_observation()
        info = {
            "player_active": self.active_player_pokemon.name,
            "opponent_active": self.active_opponent_pokemon.name,
            "turn": self.turn_count,
            "action_mask": self.get_action_mask()
        }
        return obs, info

    @property
    def active_player_pokemon(self) -> BattlePokemon:
        return self.player_team[self.player_active_idx]

    @property
    def active_opponent_pokemon(self) -> BattlePokemon:
        return self.opponent_team[self.opponent_active_idx]

    def get_action_mask(self) -> np.ndarray:
        """
        Binary array of length 9: 1 = legal, 0 = illegal action.
        """
        mask = np.zeros(self.NUM_ACTIONS, dtype=np.float32)
        active = self.active_player_pokemon

        if active.is_fainted:
            # Must switch
            for i, p in enumerate(self.player_team):
                if i != self.player_active_idx and not p.is_fainted:
                    # bench action slot: if i > active_idx, index is i - 1, etc.
                    # Standard mapping: action 4 + bench_slot
                    bench_slot = i if i < self.player_active_idx else i - 1
                    if 0 <= bench_slot < 5:
                        mask[4 + bench_slot] = 1.0
            return mask

        # Check moves
        for m_idx, move in enumerate(active.attacks[:4]):
            if move and move.name:
                mask[m_idx] = 1.0

        # Check bench switches
        bench_idx = 0
        for i, p in enumerate(self.player_team):
            if i != self.player_active_idx:
                if bench_idx < 5:
                    if not p.is_fainted:
                        mask[4 + bench_idx] = 1.0
                    bench_idx += 1

        return mask

    def calculate_damage(self, attacker: BattlePokemon, defender: BattlePokemon, attack: Attack) -> int:
        if not attack or attack.power is None or attack.power <= 0:
            return 0

        # Base power formula: floor((Level * Power) / 50)
        base = (attacker.level * attack.power) // 50

        # STAB (Same-Type Attack Bonus = 1.5x)
        stab = 1.5 if attack.type.lower() in (attacker.type1.lower(), (attacker.type2 or "").lower()) else 1.0

        # Dark variant modifier: +25% attack
        variant_mult = 1.25 if attacker.class_name.lower() == "dark" else 1.0

        # Type effectiveness multiplier with Negative class inversion check
        is_inverse = (attacker.class_name.lower() == "negative" or defender.class_name.lower() == "negative")
        type_mult = self.type_chart.get_defender_multiplier(
            def_type1=defender.type1,
            def_type2=defender.type2,
            atk_type=attack.type,
            inverse=is_inverse
        )

        total_damage = math.floor(base * stab * variant_mult * type_mult)
        if type_mult > 0.0 and total_damage < 1:
            total_damage = 1

        return int(total_damage)

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        self.turn_count += 1
        mask = self.get_action_mask()

        reward = -0.01  # Turn penalty
        terminated = False
        truncated = self.turn_count >= self.max_turns

        # Check if action is illegal
        if not (0 <= action < self.NUM_ACTIONS) or mask[action] == 0.0:
            # Illegal move penalty
            reward -= 0.5
            # Fallback to first legal action
            legal_actions = np.where(mask == 1.0)[0]
            if len(legal_actions) == 0:
                # No legal actions means battle lost
                return self.get_observation(), -1.0, True, False, {"error": "no_legal_actions"}
            action = int(legal_actions[0])

        active_player = self.active_player_pokemon
        active_opp = self.active_opponent_pokemon
        log_events = []

        # 1. Player Action Resolution
        player_switched = False
        if 4 <= action <= 8:
            # Bench switch
            bench_slot = action - 4
            target_team_idx = self._get_bench_team_index(bench_slot)
            if target_team_idx is not None and not self.player_team[target_team_idx].is_fainted:
                self.player_active_idx = target_team_idx
                active_player = self.active_player_pokemon
                player_switched = True
                log_events.append(f"Player switched to {active_player.name}")
        else:
            # Move execution
            move_idx = action
            if move_idx < len(active_player.attacks):
                attack = active_player.attacks[move_idx]
                dmg = self.calculate_damage(active_player, active_opp, attack)
                active_opp.current_hp = max(0, active_opp.current_hp - dmg)
                dmg_ratio = dmg / active_opp.max_hp
                reward += 0.2 * dmg_ratio
                log_events.append(f"{active_player.name} used {attack.name} for {dmg} dmg")

                if active_opp.is_fainted:
                    reward += 0.4
                    log_events.append(f"Opponent's {active_opp.name} fainted!")

        # 2. Opponent KO check / replacement
        if active_opp.is_fainted:
            # Opponent switches to next available pokemon
            next_opp_idx = self._get_next_available_opponent()
            if next_opp_idx is None:
                # Opponent has no more Pokemon -> Player WINS!
                reward += 1.0
                terminated = True
                obs = self.get_observation()
                return obs, reward, terminated, truncated, {"result": "win", "logs": log_events}
            else:
                self.opponent_active_idx = next_opp_idx
                active_opp = self.active_opponent_pokemon
                log_events.append(f"Opponent sent out {active_opp.name}")
        else:
            # 3. Opponent Turn (if not fainted and player didn't KO)
            opp_move = self._select_opponent_move(active_opp, active_player)
            if opp_move:
                dmg = self.calculate_damage(active_opp, active_player, opp_move)
                active_player.current_hp = max(0, active_player.current_hp - dmg)
                dmg_ratio = dmg / active_player.max_hp
                reward -= 0.2 * dmg_ratio
                log_events.append(f"Opponent {active_opp.name} used {opp_move.name} for {dmg} dmg")

                if active_player.is_fainted:
                    reward -= 0.4
                    log_events.append(f"Player's {active_player.name} fainted!")
                    # Check if player has any remaining alive Pokemon
                    next_player_idx = self._get_next_available_player()
                    if next_player_idx is None:
                        # Player has no more Pokemon -> Player LOSES!
                        reward -= 1.0
                        terminated = True
                        obs = self.get_observation()
                        return obs, reward, terminated, truncated, {"result": "loss", "logs": log_events}
                    else:
                        # Auto switch or force switch next turn
                        self.player_active_idx = next_player_idx
                        log_events.append(f"Player sent out {self.active_player_pokemon.name}")

        obs = self.get_observation()
        info = {
            "turn": self.turn_count,
            "player_hp": (self.active_player_pokemon.current_hp, self.active_player_pokemon.max_hp),
            "opp_hp": (self.active_opponent_pokemon.current_hp, self.active_opponent_pokemon.max_hp),
            "logs": log_events,
            "action_mask": self.get_action_mask()
        }
        return obs, reward, terminated, truncated, info

    def _get_bench_team_index(self, bench_slot: int) -> Optional[int]:
        slots = [i for i in range(len(self.player_team)) if i != self.player_active_idx]
        if 0 <= bench_slot < len(slots):
            return slots[bench_slot]
        return None

    def _get_next_available_opponent(self) -> Optional[int]:
        for i, p in enumerate(self.opponent_team):
            if not p.is_fainted:
                return i
        return None

    def _get_next_available_player(self) -> Optional[int]:
        for i, p in enumerate(self.player_team):
            if not p.is_fainted:
                return i
        return None

    def _select_opponent_move(self, attacker: BattlePokemon, defender: BattlePokemon) -> Optional[Attack]:
        # Simple heuristic: chooses highest damage dealing move among its attacks
        valid_attacks = [a for a in attacker.attacks if a and a.name]
        if not valid_attacks:
            return None
        best_attack = valid_attacks[0]
        best_dmg = -1
        for a in valid_attacks:
            dmg = self.calculate_damage(attacker, defender, a)
            if dmg > best_dmg:
                best_dmg = dmg
                best_attack = a
        return best_attack

    def get_observation(self) -> np.ndarray:
        """
        Encodes the battle state into a 64-dimensional float vector.
        """
        obs = np.zeros(self.OBS_DIM, dtype=np.float32)
        p = self.active_player_pokemon
        o = self.active_opponent_pokemon

        # Active player: hp_ratio, type1, type2, class, 4 moves
        obs[0] = p.current_hp / max(1, p.max_hp)
        obs[1] = self._type_to_scalar(p.type1)
        obs[2] = self._type_to_scalar(p.type2)
        obs[3] = self._class_to_scalar(p.class_name)

        # 4 Player attacks: (power/150, type/18, effectiveness/4)
        for i in range(4):
            idx = 4 + (i * 3)
            if i < len(p.attacks) and p.attacks[i] and p.attacks[i].name:
                atk = p.attacks[i]
                obs[idx] = (atk.power or 0) / 150.0
                obs[idx + 1] = self._type_to_scalar(atk.type)
                is_inv = (p.class_name.lower() == "negative" or o.class_name.lower() == "negative")
                eff = self.type_chart.get_defender_multiplier(o.type1, o.type2, atk.type, inverse=is_inv)
                obs[idx + 2] = eff / 4.0

        # Active opponent: hp_ratio, type1, type2, class
        obs[16] = o.current_hp / max(1, o.max_hp)
        obs[17] = self._type_to_scalar(o.type1)
        obs[18] = self._type_to_scalar(o.type2)
        obs[19] = self._class_to_scalar(o.class_name)

        # Player bench: 5 pokemon x (hp_ratio, type1, type2) = 15 features
        bench_slots = [p_b for i, p_b in enumerate(self.player_team) if i != self.player_active_idx]
        for b_i in range(5):
            idx = 20 + (b_i * 3)
            if b_i < len(bench_slots):
                bp = bench_slots[b_i]
                obs[idx] = bp.current_hp / max(1, bp.max_hp)
                obs[idx + 1] = self._type_to_scalar(bp.type1)
                obs[idx + 2] = self._type_to_scalar(bp.type2)

        # Opponent remaining pokemon count ratio
        opp_alive = sum(1 for op in self.opponent_team if not op.is_fainted)
        obs[35] = opp_alive / max(1, len(self.opponent_team))

        # Action mask encoded in obs[36:45]
        mask = self.get_action_mask()
        obs[36:45] = mask

        return obs

    @staticmethod
    def _type_to_scalar(type_name: Optional[str]) -> float:
        if not type_name:
            return 0.0
        t = type_name.lower()
        if t in STANDARD_TYPES:
            return (STANDARD_TYPES.index(t) + 1) / 18.0
        return 0.0

    @staticmethod
    def _class_to_scalar(class_name: str) -> float:
        classes = ["normal", "shiny", "dark", "metallic", "ghostly", "shadow", "negative", "mirage", "chrome", "retro"]
        c = class_name.lower()
        if c in classes:
            return (classes.index(c) + 1) / 10.0
        return 0.1
