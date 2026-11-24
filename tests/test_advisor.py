"""
Unit tests for CollectionAdvisor and EvolutionRegistry.
"""

import pytest
from delugerpg.models.advisor import CollectionAdvisor
from delugerpg.parsers.evolution_dex import EvolutionRegistry


class TestEvolutionRegistry:
    def test_evolution_family_resolution(self):
        reg = EvolutionRegistry()
        info = reg.get_info("Charmander")
        assert info is not None
        assert info.base_species == "Charmander"
        assert info.evolution_stage == 1
        assert "Charmeleon" in info.evolves_to
        assert info.category == "starter"

        charizard_info = reg.get_info("Charizard")
        assert charizard_info.evolution_stage == 3
        assert charizard_info.evolves_from == "Charmeleon"

    def test_branching_evolutions(self):
        reg = EvolutionRegistry()
        eevee_info = reg.get_info("Eevee")
        assert eevee_info is not None
        assert len(eevee_info.evolves_to) >= 8
        assert "Vaporeon" in eevee_info.evolves_to
        assert "Umbreon" in eevee_info.evolves_to


class TestCollectionAdvisor:
    def test_advisor_encounter_evaluation(self):
        adv = CollectionAdvisor()
        # Ekans is owned in test DB, but Arbok is not
        advice = adv.evaluate_encounter("Ekans", "Normal")
        assert advice.action == "CAPTURE"
        assert "Arbok" in advice.missing_family_members

    def test_advisor_evolution_recommendations(self):
        adv = CollectionAdvisor()
        recs = adv.get_evolution_recommendations()
        assert len(recs) > 0
        target_names = [r.target_species for r in recs]
        assert "Arbok" in target_names
