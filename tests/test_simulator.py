"""
Unit tests for DelugeRPG MapEnv and BattleEnv.
"""

import pytest
import numpy as np
from delugerpg.simulator.map_env import MapEnv
from delugerpg.simulator.battle_env import BattleEnv, BattlePokemon
from delugerpg.parsers.walkgrid import WalkGrid
from delugerpg.parsers.typechart import TypeChart
from delugerpg.core.types import Attack


@pytest.fixture
def sample_walkgrid():
    # 33x33 * 2 = 2178 bytes
    # Make tile (10, 10) walkable with all 8 directions allowed (mask 255)
    # and neighbor (10, 11) walkable with mask 255
    data = bytearray(2178)
    for x in range(33):
        for y in range(33):
            idx = (x * 33 + y) * 2
            # Byte 0: 1 (walkable)
            data[idx] = 1
            # Byte 1: 255 (all directions allowed)
            data[idx + 1] = 255
    return WalkGrid(bytes(data), map_name="test_map")


@pytest.fixture
def sample_typechart():
    # Build minimal type chart
    matrix = {
        "water": {"electric": 2.0, "grass": 2.0, "fire": 0.5, "water": 0.5, "normal": 1.0},
        "fire": {"water": 2.0, "ground": 2.0, "fire": 0.5, "grass": 0.5, "normal": 1.0},
        "grass": {"fire": 2.0, "ice": 2.0, "water": 0.5, "grass": 0.5, "normal": 1.0},
        "ghost": {"normal": 0.0, "fighting": 0.0, "dark": 2.0, "ghost": 2.0}
    }
    return TypeChart(matrix)


class TestMapEnv:
    def test_map_env_reset(self, sample_walkgrid):
        env = MapEnv(sample_walkgrid, max_steps=50)
        obs, info = env.reset(seed=42)

        assert obs.shape == (env.obs_dim,)
        assert 0 <= info["pos"][0] < 33
        assert 0 <= info["pos"][1] < 33
        assert info["visited_count"] == 1
        assert info["total_walkable"] == 33 * 33

    def test_map_env_step(self, sample_walkgrid):
        env = MapEnv(sample_walkgrid, max_steps=50)
        env.reset(seed=42, start_pos=(10, 10))

        # Action 3 is 'e' (0, 1) -> moves to (10, 11)
        obs, reward, terminated, truncated, info = env.step(3)

        assert info["pos"] == (10, 11)
        assert info["visited_count"] == 2
        assert not info["collided"]
        assert reward > 0  # Got unvisited tile exploration reward

    def test_map_env_action_mask(self, sample_walkgrid):
        env = MapEnv(sample_walkgrid, max_steps=50)
        env.reset(start_pos=(10, 10))

        mask = env.get_action_mask()
        assert mask.shape == (8,)
        assert np.all(mask == 1.0)  # In center with 255 mask, all 8 directions legal


class TestBattleEnv:
    def test_pokemon_stat_formulas(self):
        # DelugeRPG HP = Level * 4 (Shiny = +25%)
        charizard = BattlePokemon(
            name="Charizard",
            level=100,
            class_name="normal",
            type1="fire",
            type2="flying",
            attacks=[]
        )
        assert charizard.max_hp == 400
        assert charizard.current_hp == 400

        shiny_charizard = BattlePokemon(
            name="Charizard",
            level=100,
            class_name="shiny",
            type1="fire",
            type2="flying",
            attacks=[]
        )
        assert shiny_charizard.max_hp == 500
        assert shiny_charizard.current_hp == 500

    def test_damage_calculation(self, sample_typechart):
        env = BattleEnv(sample_typechart)

        # Attacker: Jolteon (Electric, Level 100), Attack: Thunderbolt (Power 90, Electric)
        # Defender: Blastoise (Water, Level 100)
        # Base = floor(100 * 90 / 50) = 180
        # STAB = 1.5x (Electric on Electric) -> 270
        # Type effectiveness = 2.0x (Electric on Water) -> 540
        jolteon = BattlePokemon("Jolteon", 100, "normal", "electric", None, [])
        blastoise = BattlePokemon("Blastoise", 100, "normal", "water", None, [])
        thunderbolt = Attack("Thunderbolt", "electric", 90, 100)

        dmg = env.calculate_damage(jolteon, blastoise, thunderbolt)
        assert dmg == 540

    def test_dark_variant_multiplier(self, sample_typechart):
        env = BattleEnv(sample_typechart)

        # Dark variant gets +25% attack damage (1.25x)
        normal_poke = BattlePokemon("Houndoom", 100, "normal", "fire", "dark", [])
        dark_poke = BattlePokemon("Houndoom", 100, "dark", "fire", "dark", [])
        defender = BattlePokemon("Tangela", 100, "normal", "grass", None, [])
        flamethrower = Attack("Flamethrower", "fire", 90, 100)

        # Base = 180, STAB = 1.5 -> 270, Type = 2.0 -> 540
        dmg_normal = env.calculate_damage(normal_poke, defender, flamethrower)
        assert dmg_normal == 540

        # With Dark class: 540 * 1.25 = 675
        dmg_dark = env.calculate_damage(dark_poke, defender, flamethrower)
        assert dmg_dark == 675

    def test_negative_class_type_inversion(self, sample_typechart):
        env = BattleEnv(sample_typechart)

        # In standard battle: Electric vs Water is 2.0x
        # With Negative class defender: 2.0x becomes 0.5x
        jolteon = BattlePokemon("Jolteon", 100, "normal", "electric", None, [])
        neg_blastoise = BattlePokemon("Blastoise", 100, "negative", "water", None, [])
        thunderbolt = Attack("Thunderbolt", "electric", 90, 100)

        # Base = 180, STAB = 1.5 -> 270. Type effectiveness inverted: 2.0 -> 0.5. Total = 135
        dmg = env.calculate_damage(jolteon, neg_blastoise, thunderbolt)
        assert dmg == 135

    def test_battle_step_win_resolution(self, sample_typechart):
        env = BattleEnv(sample_typechart)

        p1 = BattlePokemon(
            name="Pikachu",
            level=100,
            class_name="normal",
            type1="electric",
            type2=None,
            attacks=[Attack("Thunderbolt", "electric", 90, 100)]
        )
        opp = BattlePokemon(
            name="Squirtle",
            level=10,  # Max HP = 40
            class_name="normal",
            type1="water",
            type2=None,
            attacks=[Attack("Tackle", "normal", 40, 100)]
        )

        obs, info = env.reset([p1], [opp])
        assert obs.shape == (64,)

        # Use Move 0 (Thunderbolt). Deals > 500 dmg to 40 HP Squirtle -> KO -> Win!
        obs, reward, terminated, truncated, info = env.step(0)

        assert terminated is True
        assert reward > 1.0  # KO + Win reward
        assert info["result"] == "win"
