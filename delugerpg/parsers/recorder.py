"""
Deluge Recorder ZIP / JSON Parser (Schema 1).
Reconstructs page DOM state from baseline snapshots (P) and diffs (+, T, -, a, x),
builds spatial map graphs from m and g events, and extracts structured battle turn logs.
"""

import json
import zipfile
import re
from typing import Dict, List, Optional, Tuple, Any, Union
from bs4 import BeautifulSoup, Tag, NavigableString
from .walkgrid import WalkGrid
from ..core.types import RecorderEvent, BattleTurnLog

class RecorderParser:
    def __init__(self):
        self.events: List[RecorderEvent] = []
        self.current_dom: Optional[BeautifulSoup] = None
        self.current_url: str = ""
        self.map_graph: Dict[str, Dict[str, Any]] = {}  # map_name -> {"walkgrid": WalkGrid, "exits": []}
        self.battle_logs: List[BattleTurnLog] = []
        self._last_map: Optional[Tuple[str, int, int]] = None
        self.captured_pokedex_pages: Dict[str, str] = {}  # url -> html snippet

    def load_from_zip(self, zip_path: str):
        """
        Loads and parses compressed JSON chunk streams from a recorder ZIP file.
        """
        with zipfile.ZipFile(zip_path, "r") as z:
            chunk_files = sorted([f for f in z.namelist() if f.startswith("chunks/") and f.endswith(".json")])
            for fname in chunk_files:
                content = z.read(fname).decode("utf-8")
                self.load_from_json_string(content)

    def load_from_json_string(self, json_str: str):
        data = json.loads(json_str)
        if isinstance(data, list):
            for item in data:
                self.process_raw_event(item)
        elif isinstance(data, dict):
            if "events" in data and isinstance(data["events"], list):
                for item in data["events"]:
                    self.process_raw_event(item)
            else:
                self.process_raw_event(data)

    def process_raw_event(self, raw: Union[Dict[str, Any], List[Any]]):
        """
        Normalizes Schema 1 event formats (both dict and array variants):
        ['P', t, url, title, bodyHtml]
        ['+', t, parentPath, childIndex, html]
        ['T', t, parentPath, text]
        ['-', t, parentPath, descriptor]
        ['a', t, path, attr, value]
        ['x', t, path, text]
        ['c', t, kind, path, label, value, ...]
        ['n', t, xhr|fetch, path, ms]
        ['m', t, mapFile, mapNum, mapName]
        ['g', t, mapFile, base64]
        """
        if isinstance(raw, dict):
            etype = raw.get("t") or raw.get("type", "")
            ts = raw.get("ts") or raw.get("timestamp", 0)
            data = raw.get("d") or raw.get("data", {})
        elif isinstance(raw, list) and len(raw) >= 2:
            etype = raw[0]
            ts = raw[1]
            data = raw[2:]
        else:
            return

        ev = RecorderEvent(event_type=etype, timestamp=int(ts), data=data)
        self.events.append(ev)
        self._apply_event(ev)

    def _apply_event(self, ev: RecorderEvent):
        etype = ev.event_type
        d = ev.data

        if etype == "P":
            if isinstance(d, dict):
                html = d.get("html", "")
                self.current_url = d.get("url", "")
            elif isinstance(d, list) and len(d) >= 3:
                self.current_url = d[0]
                html = d[2]
            else:
                html = str(d)
                self.current_url = ""

            self.current_dom = BeautifulSoup(html, "html.parser")
            self._check_for_battle_state(html)

            if "/pokedex" in self.current_url:
                self.captured_pokedex_pages[self.current_url] = html

        elif etype == "+":
            if isinstance(d, dict):
                target_sel = d.get("target") or d.get("parent")
                html_snippet = d.get("html") or d.get("content", "")
            elif isinstance(d, list) and len(d) >= 3:
                target_sel = d[0]
                html_snippet = d[2]
            else:
                return

            if self.current_dom:
                parent = self._find_target(target_sel)
                if parent:
                    try:
                        new_soup = BeautifulSoup(html_snippet, "html.parser")
                        for child in new_soup.contents:
                            parent.append(child)
                    except Exception:
                        pass
                    self._check_for_battle_state(html_snippet)

        elif etype == "T":
            if isinstance(d, dict):
                target_sel = d.get("target")
                text = d.get("text", "")
            elif isinstance(d, list) and len(d) >= 2:
                target_sel = d[0]
                text = d[1]
            else:
                return

            if self.current_dom:
                target = self._find_target(target_sel)
                if target:
                    target.append(NavigableString(text))
                    self._check_for_battle_state(text)

        elif etype == "-":
            if isinstance(d, dict):
                target_sel = d.get("target")
            elif isinstance(d, list) and len(d) >= 1:
                target_sel = d[0]
            else:
                return

            if self.current_dom:
                target = self._find_target(target_sel)
                if target:
                    target.decompose()

        elif etype == "a":
            if isinstance(d, dict):
                target_sel = d.get("target")
                attr = d.get("name")
                val = d.get("value")
            elif isinstance(d, list) and len(d) >= 3:
                target_sel = d[0]
                attr = d[1]
                val = d[2]
            else:
                return

            if self.current_dom:
                target = self._find_target(target_sel)
                if target and isinstance(target, Tag) and attr:
                    if val is None:
                        if attr in target.attrs:
                            del target.attrs[attr]
                    else:
                        target[attr] = val

        elif etype == "x":
            if isinstance(d, dict):
                target_sel = d.get("target")
                new_text = d.get("text", "")
            elif isinstance(d, list) and len(d) >= 2:
                target_sel = d[0]
                new_text = d[1]
            else:
                return

            if self.current_dom:
                target = self._find_target(target_sel)
                if target:
                    target.string = new_text
                    self._check_for_battle_state(new_text)

        elif etype == "m":
            if isinstance(d, dict):
                map_file = d.get("map", "")
                map_num = d.get("num", "0")
                map_name = d.get("name", "")
                x = int(d.get("x", 0))
                y = int(d.get("y", 0))
            elif isinstance(d, list) and len(d) >= 1:
                map_file = str(d[0])
                map_num = str(d[1]) if len(d) > 1 else "0"
                map_name = str(d[2]) if len(d) > 2 else ""
                x = 0
                y = 0
            else:
                return

            self._record_map_transition(map_file, map_num, map_name, x, y)

        elif etype == "g":
            if isinstance(d, dict):
                map_name = d.get("map", "unknown")
                b64 = d.get("walkgrid", "")
            elif isinstance(d, list) and len(d) >= 2:
                map_name = str(d[0])
                b64 = str(d[1])
            else:
                return

            if b64:
                try:
                    wg = WalkGrid.from_base64(b64, map_name=map_name)
                    if map_name not in self.map_graph:
                        self.map_graph[map_name] = {"walkgrid": wg, "exits": []}
                    else:
                        self.map_graph[map_name]["walkgrid"] = wg
                except Exception:
                    pass

    def _find_target(self, sel: Optional[str]) -> Optional[Tag]:
        if not self.current_dom or not sel:
            return None
        clean_sel = re.sub(r':\d+', '', sel)
        if clean_sel.startswith("#") and " " not in clean_sel and ">" not in clean_sel:
            return self.current_dom.find(id=clean_sel[1:])
        try:
            return self.current_dom.select_one(clean_sel)
        except Exception:
            return None

    def _record_map_transition(self, map_file: str, map_num: str = "0", map_name: str = "", x: int = 0, y: int = 0):
        if not map_file:
            return
        if map_file not in self.map_graph:
            self.map_graph[map_file] = {
                "num": map_num,
                "name": map_name,
                "walkgrid": None,
                "exits": []
            }

        if self._last_map:
            prev_map, prev_x, prev_y = self._last_map
            if prev_map != map_file:
                transition = {
                    "from_map": prev_map,
                    "from_coord": (prev_x, prev_y),
                    "to_map": map_file,
                    "to_coord": (x, y)
                }
                existing = self.map_graph[prev_map].setdefault("exits", [])
                if transition not in existing:
                    existing.append(transition)

        self._last_map = (map_file, x, y)

    def _check_for_battle_state(self, text_or_html: str):
        if not text_or_html:
            return

        if "used" not in text_or_html or "HP" not in text_or_html:
            return

        pattern = re.compile(
            r'([A-Za-z0-9\- ]+?)\s+used\s+([A-Za-z0-9\- ]+?)\s+and\s+dealt\s+(\d+)HP\s+Damage\.(.*?)(?=(?:[A-Za-z0-9\- ]+?\s+used|\Z))',
            re.DOTALL
        )

        matches = pattern.findall(text_or_html)
        if matches:
            actions = []
            for attacker, move, dmg_str, extra in matches:
                extra_clean = extra.strip()
                fainted = "fainted" in extra_clean
                critical = "critical hit" in extra_clean
                action_info = {
                    "attacker": attacker.strip(),
                    "move": move.strip(),
                    "damage": int(dmg_str),
                    "fainted": fainted,
                    "critical": critical,
                    "extra": extra_clean
                }
                actions.append(action_info)

            player_hp = None
            opp_hp = None
            if self.current_dom:
                hp_matches = re.findall(r'HP:\s*(\d+)/(\d+)', self.current_dom.get_text())
                if len(hp_matches) >= 2:
                    opp_hp = (int(hp_matches[0][0]), int(hp_matches[0][1]))
                    player_hp = (int(hp_matches[1][0]), int(hp_matches[1][1]))

            turn_log = BattleTurnLog(
                turn_num=len(self.battle_logs) + 1,
                raw_text=text_or_html.strip(),
                actions=actions,
                player_hp=player_hp,
                opponent_hp=opp_hp
            )
            self.battle_logs.append(turn_log)
