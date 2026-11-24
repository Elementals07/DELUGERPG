"""
Collection and Evolution Advisor for DelugeRPG.
Provides real-time O(1) decision support:
1. Encounter Advisor: Whether to capture a wild Pokémon (prioritizing missing Normal species and unowned evolution family lines).
2. Evolution Advisor: Which owned Pokémon should be evolved to unlock missing Pokédex entries.
3. Collection Statistics: Exact completion rates by generation, category (starters, legendaries, regular), and forms.
"""

import sqlite3
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass
from ..parsers.evolution_dex import EvolutionRegistry


@dataclass
class EncounterAdvice:
    species_name: str
    class_name: str
    action: str  # "CAPTURE", "SKIP", "OPTIONAL"
    priority: str  # "HIGH", "MEDIUM", "LOW", "NONE"
    reason: str
    missing_family_members: List[str]


@dataclass
class EvolutionAdvice:
    current_species: str
    target_species: str
    base_species: str
    evolution_stage: int
    reason: str


class CollectionAdvisor:
    def __init__(self, db_path: str = "data/processed/delugerpg_kb.db"):
        self.db_path = db_path
        self.registry = EvolutionRegistry()
        self.normal_owned: Set[str] = set()
        self.all_owned_classes: Dict[str, Set[str]] = {}  # species -> set(class_names)
        self.total_species_count = 0
        self.reload_from_db()

    def reload_from_db(self):
        """
        Reloads ownership and species data from SQLite into fast O(1) in-memory sets.
        """
        self.normal_owned.clear()
        self.all_owned_classes.clear()

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Load species count
        cur.execute("SELECT count(*) FROM pokemon_species")
        self.total_species_count = cur.fetchone()[0]

        # Load user ownership
        cur.execute("SELECT pokemon_name, class_name, owned FROM user_collection WHERE owned = 1")
        for name, cls_name, owned in cur.fetchall():
            if name not in self.all_owned_classes:
                self.all_owned_classes[name] = set()
            self.all_owned_classes[name].add(cls_name)

            if cls_name.lower() == "normal":
                self.normal_owned.add(name)

        conn.close()

    def evaluate_encounter(self, species_name: str, class_name: str = "Normal") -> EncounterAdvice:
        """
        Evaluates a wild encounter when roaming in MapEnv or live gameplay.
        Rule: Priority is on completing all Normal Pokédex entries and base/evolution forms.
        """
        c_name = class_name.capitalize()
        is_normal = (c_name.lower() == "normal")

        # 1. Non-normal variant check
        if not is_normal:
            already_has_variant = (species_name in self.all_owned_classes and c_name in self.all_owned_classes[species_name])
            if not already_has_variant:
                return EncounterAdvice(
                    species_name=species_name,
                    class_name=c_name,
                    action="CAPTURE",
                    priority="MEDIUM",
                    reason=f"New {c_name} variant! Not yet owned in your collection.",
                    missing_family_members=[]
                )
            else:
                return EncounterAdvice(
                    species_name=species_name,
                    class_name=c_name,
                    action="SKIP",
                    priority="NONE",
                    reason=f"Duplicate {c_name} variant already owned.",
                    missing_family_members=[]
                )

        # 2. Check if this exact Normal species is missing
        if species_name not in self.normal_owned:
            return EncounterAdvice(
                species_name=species_name,
                class_name="Normal",
                action="CAPTURE",
                priority="HIGH",
                reason=f"{species_name} is NOT yet owned in your Normal Pokédex! Immediate capture recommended.",
                missing_family_members=[]
            )

        # 3. Check evolution family relatives
        family = self.registry.get_family(species_name)
        missing_relatives = [p for p in family if p not in self.normal_owned]

        if missing_relatives:
            return EncounterAdvice(
                species_name=species_name,
                class_name="Normal",
                action="CAPTURE",
                priority="MEDIUM",
                reason=f"You own {species_name}, but its family is missing: {', '.join(missing_relatives)}. Capture to evolve!",
                missing_family_members=missing_relatives
            )

        # 4. Family is 100% complete in Normal class!
        return EncounterAdvice(
            species_name=species_name,
            class_name="Normal",
            action="SKIP",
            priority="NONE",
            reason=f"Entire {species_name} family is already fully registered in Normal Pokédex. Skip to save Pokéballs.",
            missing_family_members=[]
        )

    def get_evolution_recommendations(self) -> List[EvolutionAdvice]:
        """
        Finds all owned Pokémon that can be evolved to register new missing Normal Pokédex entries.
        """
        recommendations: List[EvolutionAdvice] = []

        for owned_species in sorted(self.normal_owned):
            info = self.registry.get_info(owned_species)
            if not info or not info.evolves_to:
                continue

            for target in info.evolves_to:
                if target not in self.normal_owned:
                    recommendations.append(EvolutionAdvice(
                        current_species=owned_species,
                        target_species=target,
                        base_species=info.base_species,
                        evolution_stage=info.evolution_stage + 1,
                        reason=f"Evolve {owned_species} -> {target} to register new entry in Normal Pokédex!"
                    ))

        return recommendations

    def get_completion_summary(self) -> Dict[str, Any]:
        """
        Returns statistical completion summary of the Normal collection.
        """
        normal_count = len(self.normal_owned)
        total = max(1, self.total_species_count)
        pct = (normal_count / total) * 100.0

        # Category breakdown
        starters_owned = 0
        starters_total = 0
        legendaries_owned = 0
        legendaries_total = 0

        for name, info in self.registry.species_info.items():
            if info.category == "starter":
                starters_total += 1
                if name in self.normal_owned:
                    starters_owned += 1
            elif info.category == "legendary":
                legendaries_total += 1
                if name in self.normal_owned:
                    legendaries_owned += 1

        evo_recs = self.get_evolution_recommendations()

        return {
            "total_species": total,
            "normal_owned": normal_count,
            "completion_percentage": round(pct, 2),
            "missing_normal_count": total - normal_count,
            "starters": {
                "owned": starters_owned,
                "total": starters_total,
                "pct": round((starters_owned / max(1, starters_total)) * 100.0, 1)
            },
            "legendaries": {
                "owned": legendaries_owned,
                "total": legendaries_total,
                "pct": round((legendaries_owned / max(1, legendaries_total)) * 100.0, 1)
            },
            "pending_evolutions_available": len(evo_recs),
            "pending_evolution_targets": [r.target_species for r in evo_recs[:10]]
        }
