import os
import pytest
from delugerpg.parsers.typechart import TypeChart

TYPECHART_HTML_PATH = "DELUGERPG_Consolidated_Reference/pages/23_pages_type_chart.html"

@pytest.fixture
def typechart():
    assert os.path.exists(TYPECHART_HTML_PATH)
    with open(TYPECHART_HTML_PATH, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()
    return TypeChart.from_html(html)

def test_typechart_parsed_dimensions(typechart):
    assert len(typechart.matrix) == 18
    for d_type, atks in typechart.matrix.items():
        assert len(atks) == 18

def test_standard_effectiveness(typechart):
    # Water vs Fire = 2.0
    assert typechart.get_single_multiplier("fire", "water") == 2.0
    # Grass vs Water = 2.0
    assert typechart.get_single_multiplier("water", "grass") == 2.0
    # Fire vs Water = 0.5
    assert typechart.get_single_multiplier("water", "fire") == 0.5
    # Ghost vs Normal = 0.0 (Ghost attack vs Normal defender)
    assert typechart.get_single_multiplier("normal", "ghost") == 0.0

def test_dual_type_calculation(typechart):
    # Grass/Poison defender (Bulbasaur) vs Psychic attack:
    # Poison is weak to Psychic (2.0), Grass is neutral to Psychic (1.0) -> 2.0
    assert typechart.get_defender_multiplier("grass", "poison", "psychic") == 2.0

    # Water/Ground defender (Swampert) vs Grass attack:
    # Water is weak to Grass (2.0), Ground is weak to Grass (2.0) -> 4.0
    assert typechart.get_defender_multiplier("water", "ground", "grass") == 4.0

    # Normal/Flying defender (Pidgeot) vs Ghost attack:
    # Normal is immune to Ghost (0.0) -> 0.0
    assert typechart.get_defender_multiplier("normal", "flying", "ghost") == 0.0

def test_stab_and_negative_class_inversion(typechart):
    # Normal battle, Normal class vs Negative class:
    # 1 * 1 * (-1) = -1 -> Inverted typechart!
    mult, inverted = typechart.calculate_attack_multiplier(
        attacker_type1="water",
        attacker_type2=None,
        attacker_class="Normal",
        defender_type1="fire",
        defender_type2=None,
        defender_class="Negative",
        attack_type="water",
        is_inverse_battle=False
    )
    assert inverted is True
    # Water vs Fire normally 2.0, but inverted becomes 0.5!
    # STAB applies because attacker is Water: 0.5 * 1.5 = 0.75
    assert mult == pytest.approx(0.75)
