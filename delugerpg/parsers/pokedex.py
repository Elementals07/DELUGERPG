"""
PokeDex Parser for DelugeRPG.
Parses pokedex table rows, extracts dex ID, name, types, mega/gmax flags,
and variant/class ownership status across the 10 DelugeRPG classes:
Normal, Shiny, Metallic, Ghostly, Dark, Shadow, Mirage, Chrome, Negative, Retro.
"""

from typing import List, Optional, Dict
from bs4 import BeautifulSoup
from ..core.types import PokemonSpecies

POKEDEX_CLASSES = [
    "Normal",
    "Shiny",
    "Metallic",
    "Ghostly",
    "Dark",
    "Shadow",
    "Mirage",
    "Chrome",
    "Negative",
    "Retro"
]

class PokeDexParser:
    @staticmethod
    def parse_html(html_content: str) -> List[PokemonSpecies]:
        soup = BeautifulSoup(html_content, "html.parser")
        rows = soup.find_all("tr", class_=lambda c: c and "dexrow" in c)

        species_list: List[PokemonSpecies] = []
        for r in rows:
            cells = r.find_all("td")
            if len(cells) < 4:
                continue

            # Col 0: Dex Number
            raw_no = cells[0].get_text(strip=True)
            dex_no = int(raw_no) if raw_no.isdigit() else 0

            # Col 2: Name
            name_elem = cells[2].find("a")
            name = name_elem.get_text(strip=True) if name_elem else cells[2].get_text(strip=True)
            if not name:
                continue

            is_mega = "mega " in name.lower()
            is_gmax = "g-max " in name.lower() or "gigantamax" in name.lower()

            # Col 3: Types
            type_icons = cells[3].find_all("i", class_=lambda c: c and "tbtn-" in c)
            types: List[str] = []
            for icon in type_icons:
                for cls in icon.get("class", []):
                    if cls.startswith("tbtn-") and cls != "tbtn-mini":
                        types.append(cls.replace("tbtn-", "").strip().lower())
                        break

            type1 = types[0] if len(types) > 0 else "normal"
            type2 = types[1] if len(types) > 1 else None

            # Cols 4-13: Variant ownership flags
            classes_owned: Dict[str, bool] = {}
            for idx, class_name in enumerate(POKEDEX_CLASSES):
                cell_idx = 4 + idx
                if cell_idx < len(cells):
                    img = cells[cell_idx].find("img")
                    is_owned = False
                    if img and img.get("alt") == "y":
                        is_owned = True
                    classes_owned[class_name] = is_owned

            species_list.append(PokemonSpecies(
                dex_no=dex_no,
                name=name,
                type1=type1,
                type2=type2,
                is_mega=is_mega,
                is_gmax=is_gmax,
                classes_owned=classes_owned
            ))

        return species_list
