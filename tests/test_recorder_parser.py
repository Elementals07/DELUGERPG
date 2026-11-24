import json
import pytest
from delugerpg.parsers.recorder import RecorderParser

def test_page_reconstruction_and_diffs():
    parser = RecorderParser()

    # 1. Baseline Page event P
    baseline_html = "<html><body><div id='container'><p id='msg'>Hello</p></div></body></html>"
    parser.process_raw_event({
        "t": "P",
        "ts": 1700000000,
        "d": {"url": "https://www.delugerpg.com/map/overworld12", "html": baseline_html}
    })
    assert parser.current_dom is not None
    assert parser.current_dom.find(id="msg").get_text() == "Hello"

    # 2. Text changed event x
    parser.process_raw_event({
        "t": "x",
        "ts": 1700000001,
        "d": {"target": "#msg", "text": "Walking on map..."}
    })
    assert parser.current_dom.find(id="msg").get_text() == "Walking on map..."

    # 3. Attribute change event a
    parser.process_raw_event({
        "t": "a",
        "ts": 1700000002,
        "d": {"target": "#msg", "name": "class", "value": "active-status"}
    })
    assert parser.current_dom.find(id="msg")["class"] == "active-status"

    # 4. Element added event +
    parser.process_raw_event({
        "t": "+",
        "ts": 1700000003,
        "d": {"parent": "#container", "html": "<span id='poke-encounter'>A wild Pikachu appeared!</span>"}
    })
    assert parser.current_dom.find(id="poke-encounter") is not None
    assert "Pikachu" in parser.current_dom.find(id="poke-encounter").get_text()

    # 5. Element removed event -
    parser.process_raw_event({
        "t": "-",
        "ts": 1700000004,
        "d": {"target": "#poke-encounter"}
    })
    assert parser.current_dom.find(id="poke-encounter") is None

def test_map_graph_building():
    parser = RecorderParser()

    # Initial map event
    parser.process_raw_event({
        "t": "m",
        "ts": 1700000010,
        "d": {"map": "overworld12", "x": 31, "y": 15}
    })

    # Transition to overworld13
    parser.process_raw_event({
        "t": "m",
        "ts": 1700000015,
        "d": {"map": "overworld13", "x": 1, "y": 15}
    })

    assert "overworld12" in parser.map_graph
    assert "overworld13" in parser.map_graph
    exits = parser.map_graph["overworld12"]["exits"]
    assert len(exits) == 1
    assert exits[0]["to_map"] == "overworld13"
    assert exits[0]["from_coord"] == (31, 15)
    assert exits[0]["to_coord"] == (1, 15)

def test_battle_log_extraction():
    parser = RecorderParser()

    # Simulated battle baseline
    battle_html = """
    <div id='battle'>
        <div id='opp'>Negative Lairon HP: 400/400</div>
        <div id='me'>Ledyba HP: 44/44</div>
    </div>
    """
    parser.process_raw_event({
        "t": "P",
        "ts": 1700000020,
        "d": {"url": "https://www.delugerpg.com/battle/user/u/S-Normal", "html": battle_html}
    })

    # Simulated turn message
    turn_text = "Jigglypuff used Pound and dealt 25HP Damage. Croagunk fainted."
    parser.process_raw_event({
        "t": "+",
        "ts": 1700000021,
        "d": {"parent": "#battle", "html": f"<div class='log'>{turn_text}</div>"}
    })

    assert len(parser.battle_logs) >= 1
    log = parser.battle_logs[-1]
    assert len(log.actions) == 1
    action = log.actions[0]
    assert action["attacker"] == "Jigglypuff"
    assert action["move"] == "Pound"
    assert action["damage"] == 25
    assert action["fainted"] is True
