"""
Pokemon Type Chart parser and damage multiplier calculator for DelugeRPG.
Supports:
- 18x18 standard type effectiveness matrix
- Dual-type defender multiplier calculation
- Same Type Attack Bonus (STAB = 1.5x)
- Normal vs Inverse battle mode & class interactions (Negative class parity inversion)
"""

from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup

TYPE_ABBREV_MAP = {
    "nor": "normal",
    "fir": "fire",
    "wat": "water",
    "ele": "electric",
    "gra": "grass",
    "ice": "ice",
    "fig": "fighting",
    "poi": "poison",
    "gro": "ground",
    "fly": "flying",
    "psy": "psychic",
    "bug": "bug",
    "roc": "rock",
    "gho": "ghost",
    "dra": "dragon",
    "dar": "dark",
    "ste": "steel",
    "fai": "fairy"
}

STANDARD_TYPES = [
    "normal", "fire", "water", "electric", "grass", "ice",
    "fighting", "poison", "ground", "flying", "psychic", "bug",
    "rock", "ghost", "dragon", "dark", "steel", "fairy"
]

# Classes that flip the typechart in DelugeRPG
# Verified from 23_pages_type_chart.html / mobile/pages.js: Negative class has value -1, all others +1.
CLASS_PARITY = {
    "normal": 1,
    "shiny": 1,
    "metallic": 1,
    "ghostly": 1,
    "dark": 1,
    "shadow": 1,
    "mirage": 1,
    "chrome": 1,
    "negative": -1,
    "retro": 1
}


class TypeChart:
    def __init__(self, matrix: Optional[Dict[str, Dict[str, float]]] = None):
        """
        matrix[defense_type][attack_type] = float multiplier
        """
        self.matrix: Dict[str, Dict[str, float]] = matrix or {}

    @classmethod
    def from_html(cls, html_content: str) -> "TypeChart":
        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.find("table", id="typechart")
        if not table:
            # Fallback to any table
            table = soup.find("table")
        if not table:
            raise ValueError("No typechart table found in HTML")

        matrix: Dict[str, Dict[str, float]] = {}
        rows = table.find_all("tr")

        # Row 1 contains attack types (abbreviated in DelugeRPG: nor, fir, wat...)
        header_row = rows[1]
        attack_types: List[str] = []
        for th in header_row.find_all(["th", "td"]):
            text = th.get_text(strip=True).lower()
            full_type = TYPE_ABBREV_MAP.get(text, text)
            if full_type in STANDARD_TYPES:
                attack_types.append(full_type)

        # Subsequent rows are defense types and their row values
        for r in rows[2:]:
            cells = r.find_all(["th", "td"])
            if not cells:
                continue
            def_type_raw = cells[0].get_text(strip=True).lower()
            def_type = TYPE_ABBREV_MAP.get(def_type_raw, def_type_raw)
            if def_type not in STANDARD_TYPES:
                continue

            matrix[def_type] = {}
            col_vals = cells[1:]
            for i, cell in enumerate(col_vals):
                if i >= len(attack_types):
                    break
                atk_type = attack_types[i]
                val_text = cell.get_text(strip=True)
                val = cls._parse_multiplier(val_text)
                matrix[def_type][atk_type] = val

        return cls(matrix)

    @staticmethod
    def _parse_multiplier(text: str) -> float:
        text = text.strip()
        if text in ("0", "0.0"):
            return 0.0
        elif text in ("½", "1/2", "0.5", "\xbd", ""):
            # Notice in corrupted/sanitized text '' represents 1/2 (0xBD in latin-1)
            return 0.5
        elif text in ("1", "1.0", ""):
            return 1.0
        elif text in ("2", "2.0"):
            return 2.0
        try:
            return float(text)
        except ValueError:
            return 1.0

    def get_single_multiplier(self, def_type: str, atk_type: str, inverse: bool = False) -> float:
        d = def_type.lower()
        a = atk_type.lower()
        base_mult = self.matrix.get(d, {}).get(a, 1.0)
        if not inverse:
            return base_mult

        # Inverse type effectiveness rule:
        # 2x -> 0.5x, 0.5x -> 2x, 0x -> 2x, 1x -> 1x
        if base_mult == 2.0:
            return 0.5
        elif base_mult == 0.5:
            return 2.0
        elif base_mult == 0.0:
            return 2.0
        return 1.0

    def get_defender_multiplier(
        self,
        def_type1: str,
        def_type2: Optional[str],
        atk_type: str,
        inverse: bool = False
    ) -> float:
        """
        Calculates cumulative type multiplier against defender type(s).
        Dual-type multiplier is product of both individual multipliers.
        """
        m1 = self.get_single_multiplier(def_type1, atk_type, inverse=inverse)
        if def_type2 and def_type2.lower() not in ("none", "", "0"):
            m2 = self.get_single_multiplier(def_type2, atk_type, inverse=inverse)
            return m1 * m2
        return m1

    def calculate_attack_multiplier(
        self,
        attacker_type1: str,
        attacker_type2: Optional[str],
        attacker_class: str,
        defender_type1: str,
        defender_type2: Optional[str],
        defender_class: str,
        attack_type: str,
        is_inverse_battle: bool = False
    ) -> Tuple[float, bool]:
        """
        Computes total attack multiplier and whether Inverse chart is active.
        DelugeRPG Formula:
        is_inverse = (battle_factor * attacker_class_factor * defender_class_factor) < 0
        """
        battle_factor = -1 if is_inverse_battle else 1
        atk_class_factor = CLASS_PARITY.get(attacker_class.lower(), 1)
        def_class_factor = CLASS_PARITY.get(defender_class.lower(), 1)

        is_chart_inverted = (battle_factor * atk_class_factor * def_class_factor) < 0

        type_mult = self.get_defender_multiplier(
            defender_type1,
            defender_type2,
            attack_type,
            inverse=is_chart_inverted
        )

        # STAB (Same Type Attack Bonus): 1.5x if attack type matches attacker's types
        has_stab = False
        atk_t = attack_type.lower()
        if atk_t == attacker_type1.lower():
            has_stab = True
        elif attacker_type2 and attacker_type2.lower() not in ("none", "", "0") and atk_t == attacker_type2.lower():
            has_stab = True

        total_multiplier = type_mult * (1.5 if has_stab else 1.0)
        return total_multiplier, is_chart_inverted
