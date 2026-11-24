"""
Core data types and structures for the DelugeRPG simulator, knowledge base, and parsers.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

@dataclass
class Attack:
    name: str
    type: str
    power: Optional[int]
    accuracy: Optional[int]
    effect: Optional[str] = None
    effect_accuracy: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "power": self.power,
            "accuracy": self.accuracy,
            "effect": self.effect,
            "effect_accuracy": self.effect_accuracy
        }


@dataclass
class PokemonSpecies:
    dex_no: int
    name: str
    type1: str
    type2: Optional[str] = None
    is_mega: bool = False
    is_gmax: bool = False
    classes_owned: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dex_no": self.dex_no,
            "name": self.name,
            "type1": self.type1,
            "type2": self.type2,
            "is_mega": self.is_mega,
            "is_gmax": self.is_gmax,
            "classes_owned": self.classes_owned
        }


@dataclass
class WalkTile:
    x: int  # row 0..32
    y: int  # col 0..32
    walkable: bool  # bit 0 of byte 0
    is_water: bool  # bit 1 of byte 0
    raw_byte0: int
    raw_dirmask: int  # byte 1
    allowed_directions: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "walkable": self.walkable,
            "is_water": self.is_water,
            "raw_byte0": self.raw_byte0,
            "raw_dirmask": self.raw_dirmask,
            "allowed_directions": self.allowed_directions
        }


@dataclass
class RecorderEvent:
    event_type: str  # 'P', '+', 'T', '-', 'a', 'x', 'c', 'n', 'm', 'g'
    timestamp: int  # whole seconds unix or relative
    data: Any

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.event_type,
            "timestamp": self.timestamp,
            "data": self.data
        }


@dataclass
class BattleTurnLog:
    turn_num: int
    raw_text: str
    actions: List[Dict[str, Any]] = field(default_factory=list)
    player_hp: Optional[Tuple[int, int]] = None  # current, max
    opponent_hp: Optional[Tuple[int, int]] = None  # current, max
    player_pokemon: Optional[str] = None
    opponent_pokemon: Optional[str] = None
    winner: Optional[str] = None  # 'player', 'opponent', or None if ongoing

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_num": self.turn_num,
            "raw_text": self.raw_text,
            "actions": self.actions,
            "player_hp": self.player_hp,
            "opponent_hp": self.opponent_hp,
            "player_pokemon": self.player_pokemon,
            "opponent_pokemon": self.opponent_pokemon,
            "winner": self.winner
        }
