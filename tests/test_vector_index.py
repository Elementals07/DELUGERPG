import pytest
from delugerpg.models.vector_index import SpeciesVectorIndex

def test_vector_index_build():
    index = SpeciesVectorIndex()
    assert len(index.species_names) == 1107
    assert index.embeddings.shape == (1107, 48)

def test_similarity_search():
    index = SpeciesVectorIndex()
    results = index.search_by_name("Charizard", top_k=3)
    assert len(results) == 3
    # Top matches should be fire/flying
    assert any(r["type1"] == "fire" or r["type2"] == "flying" for r in results)
    # Cosine similarity between 0 and 1
    for r in results:
        assert 0.0 <= r["similarity_score"] <= 1.0

def test_counter_search():
    index = SpeciesVectorIndex()
    counters = index.search_counters_for_types("water", "ground", top_k=3)
    assert len(counters) == 3
    # Grass is 4x super-effective against water/ground
    assert any(c["type1"] == "grass" or c["type2"] == "grass" for c in counters)
