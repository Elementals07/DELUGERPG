import os
import pytest
from delugerpg.db.database import DatabaseManager

DB_PATH = "data/processed/delugerpg_kb.db"

@pytest.fixture
def db():
    assert os.path.exists(DB_PATH)
    manager = DatabaseManager(DB_PATH)
    yield manager
    manager.close()

def test_attacks_in_database(db):
    tackle = db.get_attack("Tackle")
    assert tackle is not None
    assert tackle["type"] == "normal"
    assert tackle["power"] == 50
    assert tackle["accuracy"] == 100

    surf = db.get_attack("Surf")
    assert surf is not None
    assert surf["type"] == "water"
    assert surf["power"] == 90

    # Test status attack with effect
    hypnosis = db.get_attack("Hypnosis")
    assert hypnosis is not None
    assert hypnosis["effect"] == "Sleep"

def test_pokemon_in_database(db):
    bulba = db.get_pokemon("Bulbasaur")
    assert bulba is not None
    assert bulba["dex_no"] == 1
    assert bulba["type1"] == "grass"
    assert bulba["type2"] == "poison"

    charizard = db.get_pokemon("Charizard")
    assert charizard is not None
    assert charizard["dex_no"] == 6
    assert charizard["type1"] == "fire"
    assert charizard["type2"] == "flying"

def test_user_collection_query(db):
    collection = db.get_user_collection("Bulbasaur")
    assert len(collection) == 10
    assert "Normal" in collection
    assert "Shiny" in collection
    assert "Negative" in collection

def test_walkgrid_in_database(db):
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM map_walkgrids WHERE map_name = 'overworld12'")
    row = cursor.fetchone()
    assert row is not None
    assert row["total_walkable"] == 815
    assert row["total_water"] == 535
