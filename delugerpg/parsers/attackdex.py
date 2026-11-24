"""
AttackDex Parser for DelugeRPG.
Extracts attacks with move name, type, power, accuracy, effect, and effect accuracy.
"""

from typing import List, Optional
from bs4 import BeautifulSoup
from ..core.types import Attack

class AttackDexParser:
    @staticmethod
    def parse_html(html_content: str) -> List[Attack]:
        soup = BeautifulSoup(html_content, "html.parser")
        tbody = soup.find("tbody")
        if not tbody:
            raise ValueError("No tbody found in AttackDex HTML")

        attacks: List[Attack] = []
        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            name = cells[0].get_text(strip=True)
            if not name:
                continue

            # Move type from icon class "tbtn tbtn-{type}"
            atk_type = "normal"
            icon = cells[1].find("i", class_=lambda c: c and "tbtn-" in c)
            if icon:
                for cls in icon.get("class", []):
                    if cls.startswith("tbtn-") and cls != "tbtn-mini":
                        atk_type = cls.replace("tbtn-", "").strip().lower()
                        break

            # Power
            raw_power = cells[2].get_text(strip=True)
            power: Optional[int] = None
            if raw_power.isdigit():
                power = int(raw_power)

            # Accuracy
            raw_acc = cells[3].get_text(strip=True)
            accuracy: Optional[int] = None
            if raw_acc.isdigit():
                accuracy = int(raw_acc)

            # Effect and Effect Accuracy
            effect: Optional[str] = None
            effect_acc: Optional[int] = None
            if len(cells) >= 5:
                raw_eff = cells[4].get_text(strip=True)
                if raw_eff and raw_eff != "-":
                    effect = raw_eff

            if len(cells) >= 6:
                raw_eff_acc = cells[5].get_text(strip=True)
                if raw_eff_acc.isdigit():
                    effect_acc = int(raw_eff_acc)

            attacks.append(Attack(
                name=name,
                type=atk_type,
                power=power,
                accuracy=accuracy,
                effect=effect,
                effect_accuracy=effect_acc
            ))

        return attacks
