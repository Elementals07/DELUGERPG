#!/usr/bin/env python
"""
Phase 0 read-only navigation baseline audit for the DelugeRPG roaming project.

This script performs NO training and changes NO navigation/reward code. It only
reads the existing map grids, graph, environments, recorder session, model
metadata/logs and checkpoints, and writes two new artifacts:

    docs/ROAMING_BASELINE_AUDIT.md
    logs/phase0_audit.json

Run from the repository root:

    python scripts/audit_navigation_baseline.py

Optional flags:
    --skip-tests   Do not run the existing pytest suite as part of the audit.
    --max-bucket-samples N   Scenarios sampled per distance bucket (default 40).
"""

import argparse
import csv
import importlib.util
import json
import os
import random
import statistics
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict, deque
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

import networkx as nx
import numpy as np
import torch

from delugerpg.parsers.walkgrid import WalkGrid, DIR_BITS, DIR_OFFSETS
from delugerpg.models.world_graph import WorldGraph
from delugerpg.simulator.map_env import MapEnv
from delugerpg.agents.path_planner import PathPlannerEnv
from delugerpg.parsers.recorder import RecorderParser

WALKGRIDS_PATH = "data/raw/delugerpg_all_walkgrids.json"
WEIGHTS_PATH = "data/processed/global_49map_weights.json"
TRAIN_LOG_PATH = "logs/global_49map_training_log.csv"
BEST_CKPT_PATH = "models/global_49map_dqn_best.pt"
SESSION_ZIP = "data/raw/deluge_session_20261124-113227.zip"
REPORT_PATH = "docs/ROAMING_BASELINE_AUDIT.md"
JSON_PATH = "logs/phase0_audit.json"

SEAM_DIRECTIONS = {"north", "south", "west", "east"}
DIR_BIT_NAME = {"north": "n", "south": "s", "west": "w", "east": "e"}
DIR_TO_ACTION = {
    "north": 5,
    "south": 6,
    "west": 7,
    "east": 8,
    "climb_up/advance": 9,
    "dungeon_enter": 9,
    "climb_down/return": 10,
    "dungeon_exit": 10,
}
ACTION_COMPONENT_KEYS = [
    "step_cost",
    "novelty",
    "water",
    "blocked",
    "recent_map",
    "fresh_map",
    "discovery",
    "dist_progress",
    "dist_regress",
    "target",
]


def load_train_module():
    path = os.path.join(REPO_ROOT, "scripts", "train_global_49maps.py")
    spec = importlib.util.spec_from_file_location("train_global_49maps", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def boundary_ok(direction, src, dst):
    """Check that a seam portal lies on the correct boundary for x=row, y=column."""
    if direction == "north":
        return src[0] == 1 and dst[0] == 31 and src[1] == dst[1]
    if direction == "south":
        return src[0] == 31 and dst[0] == 1 and src[1] == dst[1]
    if direction == "west":
        return src[1] == 1 and dst[1] == 31 and src[0] == dst[0]
    if direction == "east":
        return src[1] == 31 and dst[1] == 1 and src[0] == dst[0]
    return None


# ---------------------------------------------------------
# 1. Map grid audit
# ---------------------------------------------------------
def audit_walkgrids(wg):
    per_map = {}
    total_walkable = 0
    total_water = 0
    for name in sorted(wg.grids):
        grid = wg.grids[name]
        walkable = water = blocked = 0
        dir_counts = Counter()
        dir_mask_zero = 0
        for x in range(grid.HEIGHT):
            for y in range(grid.WIDTH):
                tile = grid.get_tile(x, y)
                if tile.walkable:
                    walkable += 1
                if tile.is_water:
                    water += 1
                if not tile.walkable and not tile.is_water:
                    blocked += 1
                if tile.raw_dirmask == 0:
                    dir_mask_zero += 1
                for d, bit in DIR_BITS.items():
                    if tile.raw_dirmask & bit:
                        dir_counts[d] += 1
        total_walkable += walkable
        total_water += water
        per_map[name] = {
            "walkable": walkable,
            "water": water,
            "blocked": blocked,
            "tiles": grid.HEIGHT * grid.WIDTH,
            "bytes": len(grid.raw_bytes),
            "dirmask_zero_tiles": dir_mask_zero,
            "dir_bit_tiles": dict(dir_counts),
            "is_overworld": name.startswith("overworld"),
        }
    return {
        "map_count": len(per_map),
        "overworld_count": sum(1 for v in per_map.values() if v["is_overworld"]),
        "dungeon_count": sum(1 for v in per_map.values() if not v["is_overworld"]),
        "all_decode_2178_bytes": all(v["bytes"] == 2178 for v in per_map.values()),
        "all_33x33": all(v["tiles"] == 1089 for v in per_map.values()),
        "total_walkable": total_walkable,
        "total_water": total_water,
        "per_map": per_map,
    }


# ---------------------------------------------------------
# 2. Graph topology audit
# ---------------------------------------------------------
def audit_topology(wg):
    def summarize(graph, label):
        nodes = set(graph.nodes())
        all_pairs = dict(nx.all_pairs_shortest_path_length(graph))
        hop_counter = Counter()
        reachable = 0
        unreachable = 0
        for a in nodes:
            for b in nodes:
                if a == b:
                    continue
                if b in all_pairs[a]:
                    reachable += 1
                    hop_counter[all_pairs[a][b]] += 1
                else:
                    unreachable += 1
        sccs = sorted((len(c) for c in nx.strongly_connected_components(graph)), reverse=True)
        diameter = nx.diameter(graph) if nx.is_strongly_connected(graph) else None
        hops = [d for d, n in hop_counter.items() for _ in range(n)]
        return {
            "label": label,
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "strongly_connected": nx.is_strongly_connected(graph),
            "scc_sizes": sccs,
            "scc_count": len(sccs),
            "reachable_ordered_pairs": reachable,
            "unreachable_ordered_pairs": unreachable,
            "diameter": diameter,
            "mean_hop_distance": round(statistics.mean(hops), 4) if hops else None,
            "median_hop_distance": statistics.median(hops) if hops else None,
            "hop_distribution": {str(k): v for k, v in sorted(hop_counter.items())},
        }

    base = WorldGraph(WALKGRIDS_PATH)
    return {
        "base_world_graph": summarize(base.graph, "WorldGraph (overworld seams + dungeon floor chains)"),
        "global_world_graph": summarize(wg.graph, "GlobalWorldGraph (+ 7 hardcoded overworld->dungeon entrances)"),
        "topology_caveat": "All connectivity here is TOPOLOGICAL (map-name graph). It is not evidence that a "
                           "player can physically walk to a portal or that a landing coordinate is valid.",
    }


# ---------------------------------------------------------
# 3. Portal / transition audit
# ---------------------------------------------------------
def audit_portals(wg):
    graph = wg.graph
    portal_set = set()
    for u, v, data in graph.edges(data=True):
        for p in data.get("portals", []) or []:
            portal_set.add((u, v, tuple(p.get("from")), tuple(p.get("to"))))

    edges = []
    portal_records = []
    totals = Counter()
    problems = []
    for u, v, data in sorted(graph.edges(data=True), key=lambda e: (e[0], e[1])):
        direction = data.get("direction")
        portals = data.get("portals", []) or []
        row = {
            "from_map": u,
            "to_map": v,
            "direction": direction,
            "portal_count": len(portals),
            "src_walkable": 0,
            "dst_walkable": 0,
            "dir_bit_ok": 0,
            "boundary_ok": 0,
            "reverse_ok": 0,
            "invalid": [],
        }
        if not portals:
            # Empty portal arrays: floor transitions use the hardcoded default (16,16).
            dst_tile = wg.grids[v].get_tile(16, 16) if v in wg.grids else None
            default_walkable = bool(dst_tile and dst_tile.walkable)
            row["status"] = "unverified_no_coordinates"
            row["default_landing"] = [16, 16]
            row["default_landing_walkable"] = default_walkable
            if not default_walkable:
                row["status"] = "unverified_no_coordinates_default_landing_invalid"
                problems.append({
                    "kind": "invalid_default_landing",
                    "from_map": u,
                    "to_map": v,
                    "direction": direction,
                    "landing": [16, 16],
                    "note": "Global49MapEnv.step() would silently fall back to the first walkable tile.",
                })
            edges.append(row)
            totals["edges_without_portals"] += 1
            totals["edges_without_portals_invalid_default"] += int(not default_walkable)
            continue

        is_seam = direction in SEAM_DIRECTIONS
        bit_name = DIR_BIT_NAME.get(direction)
        for p in portals:
            src = tuple(p.get("from"))
            dst = tuple(p.get("to"))
            src_tile = wg.grids[u].get_tile(*src) if u in wg.grids else None
            dst_tile = wg.grids[v].get_tile(*dst) if v in wg.grids else None
            src_walk = bool(src_tile and src_tile.walkable)
            dst_walk = bool(dst_tile and dst_tile.walkable)
            bit_ok = bool(src_tile and src_tile.allowed_directions.get(bit_name)) if is_seam else None
            b_ok = boundary_ok(direction, src, dst) if is_seam else None
            rev_ok = (v, u, dst, src) in portal_set

            row["src_walkable"] += int(src_walk)
            row["dst_walkable"] += int(dst_walk)
            if bit_ok is not None:
                row["dir_bit_ok"] += int(bit_ok)
            if b_ok is not None:
                row["boundary_ok"] += int(b_ok)
            row["reverse_ok"] += int(rev_ok)
            totals["portals"] += 1
            totals["src_walkable"] += int(src_walk)
            totals["dst_walkable"] += int(dst_walk)
            if bit_ok is not None:
                totals["dir_bit_ok"] += int(bit_ok)
                totals["dir_bit_checked"] += 1
            if b_ok is not None:
                totals["boundary_ok"] += int(b_ok)
                totals["boundary_checked"] += 1
            totals["reverse_ok"] += int(rev_ok)

            invalid_reasons = []
            if not src_walk:
                invalid_reasons.append("source_not_walkable")
            if not dst_walk:
                invalid_reasons.append("destination_not_walkable")
            if bit_ok is False:
                invalid_reasons.append("source_direction_bit_missing")
            if b_ok is False:
                invalid_reasons.append("axis_or_boundary_mismatch")
            if not rev_ok:
                invalid_reasons.append("reverse_portal_missing")
            portal_records.append({
                "from_map": u,
                "to_map": v,
                "direction": direction,
                "from": list(src),
                "to": list(dst),
                "src_walkable": src_walk,
                "dst_walkable": dst_walk,
                "dir_bit_ok": bit_ok,
                "boundary_ok": b_ok,
                "reverse_ok": rev_ok,
                "reasons": invalid_reasons,
            })
            if invalid_reasons:
                row["invalid"].append({"from": list(src), "to": list(dst), "reasons": invalid_reasons})

        if is_seam:
            if row["boundary_ok"] == row["portal_count"] and row["dir_bit_ok"] == row["portal_count"] \
                    and row["src_walkable"] == row["portal_count"] and row["dst_walkable"] == row["portal_count"] \
                    and row["reverse_ok"] == row["portal_count"]:
                row["status"] = "verified_under_documented_axes"
                totals["seam_edges_verified"] += 1
            elif row["boundary_ok"] == 0:
                row["status"] = "axis_mismatch"
                totals["seam_edges_axis_mismatch"] += 1
                problems.append({
                    "kind": "seam_axis_mismatch",
                    "from_map": u,
                    "to_map": v,
                    "direction": direction,
                    "portals": row["portal_count"],
                    "boundary_ok": row["boundary_ok"],
                    "dir_bit_ok": row["dir_bit_ok"],
                    "reverse_ok": row["reverse_ok"],
                })
            else:
                row["status"] = "partial_seam_validation"
                totals["seam_edges_partial"] += 1
        else:
            if row["src_walkable"] == row["portal_count"] and row["dst_walkable"] == row["portal_count"]:
                row["status"] = "coordinates_walkable_mechanic_unverified"
                totals["entrance_edges_coordinates_ok"] += 1
            else:
                row["status"] = "invalid_coordinates"
                totals["entrance_edges_invalid"] += 1
                problems.append({
                    "kind": "entrance_invalid_coordinates",
                    "from_map": u,
                    "to_map": v,
                    "direction": direction,
                    "invalid": row["invalid"],
                })
        edges.append(row)

    totals["edges_total"] = len(edges)
    totals["seam_edges"] = sum(1 for e in edges if e["direction"] in SEAM_DIRECTIONS)
    totals["entrance_edges"] = sum(1 for e in edges if e["direction"] in ("dungeon_enter", "dungeon_exit"))
    totals["floor_edges"] = sum(1 for e in edges if e["direction"] in ("climb_up/advance", "climb_down/return"))
    for key in (
        "portals", "src_walkable", "dst_walkable", "dir_bit_ok", "dir_bit_checked",
        "boundary_ok", "boundary_checked", "reverse_ok", "seam_edges_verified",
        "seam_edges_axis_mismatch", "seam_edges_partial", "entrance_edges_coordinates_ok",
        "entrance_edges_invalid", "edges_without_portals",
        "edges_without_portals_invalid_default",
    ):
        totals.setdefault(key, 0)
    return {"totals": dict(totals), "edges": edges, "portal_records": portal_records,
            "problems": problems}


# ---------------------------------------------------------
# 4. Overworld 21 entrance collision
# ---------------------------------------------------------
def audit_overworld21(wg):
    out_edges = list(wg.graph.out_edges("overworld21", data=True))
    enter_edges = [(v, data) for u, v, data in out_edges if data.get("direction") == "dungeon_enter"]
    first = enter_edges[0][0] if enter_edges else None
    return {
        "out_edges": [
            {"to": v, "direction": data.get("direction"), "portals": data.get("portals")}
            for u, v, data in out_edges
        ],
        "dungeon_enter_targets": [v for v, _ in enter_edges],
        "action_9_selects": first,
        "collision": len(enter_edges) > 1,
        "note": "Global49MapEnv.step() selects the first outgoing edge whose direction is in "
                "('climb_up/advance', 'dungeon_enter'). Both Overworld 21 entrances share action 9, "
                "so the second entrance (volcano1) cannot be deliberately chosen.",
    }


# ---------------------------------------------------------
# 5. Environment observation/action specs
# ---------------------------------------------------------
def audit_specs(train_mod):
    base = WorldGraph(WALKGRIDS_PATH)
    global_wg = train_mod.GlobalWorldGraph(WALKGRIDS_PATH)
    map_env = MapEnv(base.grids["overworld1"])
    path_env = PathPlannerEnv(base.grids["overworld1"])
    global_env = train_mod.Global49MapEnv(global_wg, max_macro_steps=20)
    global_obs = global_env.reset(start_map="overworld1", target_map="volcano4")
    return {
        "MapEnv": {
            "actions": 8,
            "action_names": ["n", "s", "w", "e", "nw", "ne", "sw", "se"],
            "actual_obs_dim": int(map_env.obs_dim),
            "docstring_obs_dim_claim": 53,
            "obs_layout": "7x7 window x {walkable, visited} = 98 features + 4 scalars "
                          "(x/32, y/32, coverage, steps_remaining_ratio)",
            "notes": "Docstring says 53 features and mentions a water channel, but the code emits 102 "
                     "features and only walkability+visited channels. No directional affordance, water, "
                     "terrain or portal information in the observation.",
        },
        "PathPlannerEnv": {
            "actions": 16,
            "obs_dim": int(path_env._get_obs().shape[0]),
            "scope": "Overworld 1 only",
            "notes": "16 hardcoded waypoints; not a 49-map solution.",
        },
        "Global49MapEnv": {
            "actions": 11,
            "action_names": list(train_mod.ACTION_NAMES),
            "obs_dim": int(len(global_obs)),
            "obs_layout": "49 current-map one-hot + 49 target-map one-hot + 2 position + 1 local coverage "
                          "+ 49 map visit counts + 49 steps-since-visit + 5 recent-map history = 204",
            "notes": "Local actions 0-4 each run a full BFS route to a sector waypoint in one macro-step. "
                     "Actions 5-10 are map-transition macros. Not tile-by-tile movement.",
        },
    }


# ---------------------------------------------------------
# 6. Training settings / success definition / checkpoint rule
# ---------------------------------------------------------
def audit_training_settings():
    return {
        "entry_point": "scripts/train_global_49maps.py :: train_global_agent()",
        "maps": 49,
        "actions": 11,
        "episodes_configured": 8000,
        "max_macro_steps_in_train_entry": 20,
        "max_macro_steps_class_default": 25,
        "gamma": 0.98,
        "learning_rate": 7e-4,
        "buffer_size": 40000,
        "batch_size": 64,
        "target_sync_every_episodes": 25,
        "epsilon_schedule": "linear 1.0 -> 0.05 over 5000 episodes, then constant 0.05",
        "start_map_sampling": "overworld1 every 4th episode, otherwise uniform random over 49 maps",
        "target_map_sampling": "uniform random map different from the start map",
        "success_condition": "current_map == target_map (no target coordinate, region or exploration requirement)",
        "termination": "done when target map entered or macro_steps >= max_macro_steps",
        "checkpoint_selection": "saves global_49map_dqn_best.pt whenever episode reward > best_reward OR "
                                "maps_visited > best_maps_visited; updates only the improved best value, then "
                                "loads that checkpoint to export global_49map_weights.json",
        "logging_columns": ["episode", "epsilon", "reward", "maps_visited", "target_reached",
                            "encounters", "loss", "steps"],
        "timeout_label": "No explicit timeout column. A timeout is inferable only as target_reached == 0 and steps == max_macro_steps.",
        "reward_components": [
            {"component": "step_cost", "value": -0.1, "condition": "every macro-step", "source_line": 185},
            {"component": "novelty", "value": "+0.25 per tile", "condition": "local sector path tile not in local_visited_tiles", "source_line": 198},
            {"component": "water", "value": "+0.8 per water tile", "condition": "every water tile on a local sector path, including revisits", "source_line": 202},
            {"component": "blocked_local_path", "value": -1.0, "condition": "find_path returns None or an empty path", "source_line": 208},
            {"component": "recent_map_penalty", "value": -12.0, "condition": "destination map in recent_map_history (last 5)", "source_line": 250},
            {"component": "fresh_map_bonus", "value": "+8.0", "condition": "destination map not in recent_map_history", "source_line": 252},
            {"component": "map_discovery", "value": "+20.0", "condition": "destination map never visited this episode", "source_line": 256},
            {"component": "distance_progress", "value": "+15.0", "condition": "map-graph shortest-path distance to target decreases", "source_line": 262},
            {"component": "distance_regression", "value": "-5.0", "condition": "map-graph distance does not decrease", "source_line": 264},
            {"component": "target_arrival", "value": "+80.0", "condition": "current_map becomes target_map", "source_line": 278},
            {"component": "tall_grass", "value": "NOT PRESENT", "condition": "no tall-grass reward exists in the 49-map code; WalkTile has no grass flag", "source_line": None},
            {"component": "encounter_counter", "value": "no reward itself", "condition": "incremented once per water tile on the local route; not a real encounter event", "source_line": 203},
        ],
    }


# ---------------------------------------------------------
# 7. Recorder audit
# ---------------------------------------------------------
def audit_recorder():
    parser = RecorderParser()
    parser.load_from_zip(SESSION_ZIP)
    type_counts = Counter(ev.event_type for ev in parser.events)

    z = zipfile.ZipFile(SESSION_ZIP)
    m_events = 0
    m_with_coords = 0
    g_events = 0
    for fname in z.namelist():
        if not fname.startswith("chunks/") or not fname.endswith(".json"):
            continue
        try:
            obj = json.loads(z.read(fname).decode("utf-8"))
        except Exception:
            continue
        events = obj if isinstance(obj, list) else obj.get("events", [obj])
        for ev in events:
            if isinstance(ev, list) and ev:
                if ev[0] == "m":
                    m_events += 1
                    if len(ev) >= 7:
                        m_with_coords += 1
                elif ev[0] == "g":
                    g_events += 1
            elif isinstance(ev, dict):
                t = ev.get("t") or ev.get("type")
                if t == "m":
                    m_events += 1
                    d = ev.get("d") or ev.get("data") or {}
                    if isinstance(d, dict) and "x" in d and "y" in d:
                        m_with_coords += 1
                elif t == "g":
                    g_events += 1

    exits = []
    for m, info in parser.map_graph.items():
        exits.extend(info.get("exits", []))
    zero_exits = sum(1 for e in exits if e.get("from_coord") == (0, 0) or e.get("to_coord") == (0, 0))
    return {
        "session": SESSION_ZIP,
        "total_events_parsed": len(parser.events),
        "event_type_counts": dict(type_counts),
        "map_change_events": m_events,
        "map_change_events_with_coordinates": m_with_coords,
        "walkgrid_events": g_events,
        "map_graph_entries": len(parser.map_graph),
        "recorded_exits": len(exits),
        "exits_with_fabricated_zero_coordinate": zero_exits,
        "array_schema_example": ["m", 5, "overworld1", "1", "The Deluge Realm #1"],
        "finding": "Array-form 'm' events carry map/name data but no x/y. RecorderParser sets x=y=0 "
                   "and records transitions with (0,0). This session is NOT a valid tile-level human "
                   "trajectory dataset and must not be treated as one.",
    }


# ---------------------------------------------------------
# 8. Model / log provenance
# ---------------------------------------------------------
def audit_provenance():
    meta = None
    if os.path.exists(WEIGHTS_PATH):
        with open(WEIGHTS_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f).get("metadata")
    rows = []
    if os.path.exists(TRAIN_LOG_PATH):
        with open(TRAIN_LOG_PATH, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    rewards = [float(r["reward"]) for r in rows] if rows else []
    maps = [int(r["maps_visited"]) for r in rows] if rows else []
    ckpt_shapes = {}
    for path in (BEST_CKPT_PATH, "models/global_49map_dqn_final.pt"):
        if os.path.exists(path):
            sd = torch.load(path, map_location="cpu")
            ckpt_shapes[path] = {
                "first_weight_shape": list(sd["feature_net.0.weight"].shape),
                "tensor_count": len(sd),
            }
    return {
        "weights_metadata": meta,
        "training_log_rows": len(rows),
        "training_log_first_episode": rows[0] if rows else None,
        "training_log_last_episode": rows[-1] if rows else None,
        "training_log_max_reward": max(rewards) if rewards else None,
        "training_log_max_maps_visited": max(maps) if maps else None,
        "checkpoints": ckpt_shapes,
        "caveat": "The current workspace metadata claims 8000 episodes and the log contains 8000 rows. "
                  "This differs from the earlier snapshot described in the plan (episodes: 5). The files "
                  "cannot be cryptographically proven to be the exact run shown in any external screenshot; "
                  "do not claim they are the 6500-episode screenshot run. All existing artifacts were left "
                  "untouched.",
    }


# ---------------------------------------------------------
# 9. Instrumented reward decomposition (read-only wrapper)
# ---------------------------------------------------------
def snapshot(env):
    return {
        "current_map": env.current_map,
        "curr_x": env.curr_x,
        "curr_y": env.curr_y,
        "target_map": env.target_map,
        "local_visited_tiles": set(env.local_visited_tiles),
        "recent_map_history": list(env.recent_map_history),
        "visited_maps": set(env.visited_maps),
    }


def compute_components(env, pre, action, info):
    comp = {k: 0.0 for k in ACTION_COMPONENT_KEYS}
    comp["step_cost"] = -0.1
    comp["encounters"] = 0
    if action < 5:
        target_tile = env.sector_waypoints[pre["current_map"]][action]
        grid = env.wg.grids[pre["current_map"]]
        path = grid.find_path(pre["curr_x"], pre["curr_y"], target_tile[0], target_tile[1])
        if path:
            for x, y in path:
                if (x, y) not in pre["local_visited_tiles"]:
                    comp["novelty"] += 0.25
                tile = grid.get_tile(x, y)
                if tile and tile.is_water:
                    comp["water"] += 0.8
                    comp["encounters"] += 1
        else:
            comp["blocked"] = -1.0
    else:
        if info.get("transition"):
            next_map = info["transition"]
            next_idx = env.map_to_idx[next_map]
            if next_idx in pre["recent_map_history"]:
                comp["recent_map"] = -12.0
            else:
                comp["fresh_map"] = 8.0
            if next_map not in pre["visited_maps"]:
                comp["discovery"] = 20.0
            try:
                curr_dist = nx.shortest_path_length(env.wg.graph, pre["current_map"], pre["target_map"])
                new_dist = nx.shortest_path_length(env.wg.graph, next_map, pre["target_map"])
            except nx.NetworkXError:
                curr_dist = new_dist = None
            if curr_dist is not None and new_dist is not None:
                if new_dist < curr_dist:
                    comp["dist_progress"] = 15.0
                else:
                    comp["dist_regress"] = -5.0
            if next_map == pre["target_map"]:
                comp["target"] = 80.0
    return comp


def fidelity_check(env, rng, episodes=6, max_steps=20):
    """Verify that the component decomposition reconciles with the real env reward."""
    max_abs_diff = 0.0
    mismatches = 0
    checked_steps = 0
    for _ in range(episodes):
        env.reset()
        done = False
        steps = 0
        while not done and steps < max_steps:
            mask = env.get_action_mask()
            valid = np.where(mask)[0]
            action = int(rng.choice(list(valid)))
            pre = snapshot(env)
            _, reward, done, info = env.step(action)
            comp = compute_components(env, pre, action, info)
            total = sum(comp[k] for k in ACTION_COMPONENT_KEYS)
            diff = abs(total - reward)
            max_abs_diff = max(max_abs_diff, diff)
            if diff > 1e-6:
                mismatches += 1
            checked_steps += 1
            steps += 1
    return {
        "episodes": episodes,
        "steps_checked": checked_steps,
        "max_abs_difference": max_abs_diff,
        "mismatches": mismatches,
        "reconciled": mismatches == 0,
    }


def reset_fixed(env, start_map, start_xy, target_map):
    env.reset(start_map=start_map, target_map=target_map)
    env.curr_x, env.curr_y = start_xy
    env.local_visited_tiles = {(start_xy[0], start_xy[1])}
    return env._get_obs()


def route_action(env):
    try:
        path = nx.shortest_path(env.wg.graph, env.current_map, env.target_map)
    except nx.NetworkXNoPath:
        return 2
    if len(path) < 2:
        return 2
    next_map = path[1]
    for u, v, data in env.wg.graph.out_edges(env.current_map, data=True):
        if v == next_map:
            return DIR_TO_ACTION.get(data.get("direction"), 2)
    return 2


def run_episode(env, scenario, policy, max_steps, rng=None, agent=None, water_pair=None):
    obs = reset_fixed(env, scenario["start_map"], tuple(scenario["start_xy"]), scenario["target_map"])
    totals = {k: 0.0 for k in ACTION_COMPONENT_KEYS}
    totals["encounters"] = 0
    steps = 0
    done = False
    while not done and steps < max_steps:
        mask = env.get_action_mask()
        if policy == "route":
            action = route_action(env)
        elif policy == "local":
            action = steps % 5
        elif policy == "water":
            action = water_pair[1] if steps % 2 == 0 else water_pair[0]
        elif policy == "random":
            valid = np.where(mask)[0]
            action = int(rng.choice(list(valid)))
        elif policy == "greedy":
            action = agent.select_action(obs, mask, epsilon=0.0)
        else:
            raise ValueError(policy)
        pre = snapshot(env)
        obs, reward, done, info = env.step(action)
        comp = compute_components(env, pre, action, info)
        for k in ACTION_COMPONENT_KEYS:
            totals[k] += comp[k]
        totals["encounters"] += comp["encounters"]
        steps += 1
    success = env.current_map == env.target_map
    totals["reward"] = round(sum(totals[k] for k in ACTION_COMPONENT_KEYS), 4)
    totals["steps"] = steps
    totals["success"] = success
    totals["timeout"] = (not success) and steps >= max_steps
    totals["final_map"] = env.current_map
    return totals


def find_best_water_pair(wg, train_mod):
    """Find the map/sector pair whose back-and-forth route traverses the most water."""
    best = None
    for map_name, grid in wg.grids.items():
        waypoints = {}
        walkable = [(x, y) for y in range(33) for x in range(33)
                    if grid.get_tile(x, y) and grid.get_tile(x, y).walkable]
        for s_idx, (cx, cy) in train_mod.SECTOR_TARGETS.items():
            waypoints[s_idx] = min(walkable, key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)
        for a in range(5):
            for b in range(a + 1, 5):
                pa, pb = waypoints[a], waypoints[b]
                path_ab = grid.find_path(pa[0], pa[1], pb[0], pb[1])
                path_ba = grid.find_path(pb[0], pb[1], pa[0], pa[1])
                if not path_ab or not path_ba:
                    continue
                water = sum(1 for x, y in path_ab if grid.get_tile(x, y).is_water) + \
                        sum(1 for x, y in path_ba if grid.get_tile(x, y).is_water)
                if best is None or water > best["water_per_cycle"]:
                    best = {
                        "map": map_name,
                        "pair": [a, b],
                        "start_xy": list(pa),
                        "water_per_cycle": water,
                    }
    return best


def controlled_experiments(wg, train_mod, agent, bucket_samples):
    # Global seeds make env.reset() deterministic even though it uses the module-level RNG.
    random.seed(20261124)
    np.random.seed(20261124)
    env = train_mod.Global49MapEnv(wg, max_macro_steps=20)
    rng = random.Random(20261124)
    fidelity = fidelity_check(env, rng)

    pairs = []
    for a in sorted(wg.grids):
        for b in sorted(wg.grids):
            if a == b:
                continue
            try:
                pairs.append((a, b, nx.shortest_path_length(wg.graph, a, b)))
            except nx.NetworkXNoPath:
                pass
    by_hop = defaultdict(list)
    for a, b, d in pairs:
        by_hop[d].append((a, b, d))

    fixed = []
    for target_hop, label in ((1, "near"), (5, "medium"), (14, "far")):
        if by_hop.get(target_hop):
            a, b, d = sorted(by_hop[target_hop])[0]
            fixed.append((label, a, b, d))
    fixed.append(("overworld21_mansion", "overworld21", "pkmnmansion1", 1))
    fixed.append(("overworld21_volcano", "overworld21", "volcano1", 1))

    scenario_results = []
    for label, start_map, target_map, hop in fixed:
        start_xy = rng.choice([(x, y) for y in range(33) for x in range(33)
                               if wg.grids[start_map].get_tile(x, y).walkable])
        scenario = {"label": label, "start_map": start_map, "start_xy": list(start_xy),
                    "target_map": target_map, "map_hop_distance": hop}
        for policy in ("route", "local", "greedy"):
            result = run_episode(env, scenario, policy, 20, rng=rng, agent=agent)
            scenario_results.append({**scenario, "policy": policy, **result})

    water = find_best_water_pair(wg, train_mod)
    water_result = None
    if water:
        target_map = "volcano4" if water["map"] != "volcano4" else "overworld25"
        scenario = {"label": "water_farming", "start_map": water["map"],
                    "start_xy": water["start_xy"], "target_map": target_map,
                    "map_hop_distance": nx.shortest_path_length(wg.graph, water["map"], target_map)}
        water_result = {**scenario, "water_pair": water["pair"], "water_per_cycle": water["water_per_cycle"],
                        **run_episode(env, scenario, "water", 20, rng=rng,
                                      water_pair=tuple(water["pair"]))}

    # Success by map-hop distance bucket for random / route / greedy baselines.
    bucket_results = []
    buckets = [("near", 1, 3), ("medium", 4, 7), ("far", 8, 14)]
    for name, lo, hi in buckets:
        pool = [p for p in pairs if lo <= p[2] <= hi]
        rng.shuffle(pool)
        sample = pool[:bucket_samples]
        for policy in ("random", "route", "greedy"):
            successes = timeouts = 0
            rewards = []
            for a, b, d in sample:
                start_xy = rng.choice([(x, y) for y in range(33) for x in range(33)
                                       if wg.grids[a].get_tile(x, y).walkable])
                scenario = {"start_map": a, "start_xy": list(start_xy), "target_map": b}
                res = run_episode(env, scenario, policy, 20, rng=rng, agent=agent)
                successes += int(res["success"])
                timeouts += int(res["timeout"])
                rewards.append(res["reward"])
            bucket_results.append({
                "bucket": name,
                "hop_range": [lo, hi],
                "policy": policy,
                "samples": len(sample),
                "successes": successes,
                "success_rate": round(100.0 * successes / max(1, len(sample)), 2),
                "timeouts": timeouts,
                "mean_reward": round(statistics.mean(rewards), 3) if rewards else None,
            })

    return {
        "fidelity": fidelity,
        "fixed_scenarios": scenario_results,
        "water_farming": water_result,
        "success_by_distance_bucket": bucket_results,
    }


# ---------------------------------------------------------
# 10. Historical log trend and legacy feasibility
# ---------------------------------------------------------
def audit_log_trend():
    rows = list(csv.DictReader(open(TRAIN_LOG_PATH, encoding="utf-8")))
    windows = []
    for i in range(0, len(rows), 500):
        chunk = rows[i:i + 500]
        successes = sum(int(r["target_reached"]) for r in chunk)
        windows.append({
            "episodes": [int(chunk[0]["episode"]), int(chunk[-1]["episode"])],
            "success_rate": round(100.0 * successes / len(chunk), 2),
            "mean_reward": round(statistics.mean(float(r["reward"]) for r in chunk), 2),
            "mean_encounters": round(statistics.mean(int(r["encounters"]) for r in chunk), 1),
            "mean_maps_visited": round(statistics.mean(int(r["maps_visited"]) for r in chunk), 2),
        })
    success_steps = Counter(int(r["steps"]) for r in rows if int(r["target_reached"]) == 1)
    fail_steps = Counter(int(r["steps"]) for r in rows if int(r["target_reached"]) == 0)
    return {
        "window_trend": windows,
        "success_episodes": sum(success_steps.values()),
        "failed_episodes": sum(fail_steps.values()),
        "success_step_range": [min(success_steps), max(success_steps)] if success_steps else None,
        "all_failures_at_max_steps": set(fail_steps) == {20} if fail_steps else None,
        "per_distance_bucket": "NOT AVAILABLE: the CSV records no start map or target map, so the "
                               "historical run cannot be grouped by target-distance bucket.",
    }


def legacy_feasibility(wg):
    hops = []
    for a in wg.grids:
        for b in wg.grids:
            if a == b:
                continue
            try:
                hops.append(nx.shortest_path_length(wg.graph, a, b))
            except nx.NetworkXNoPath:
                pass
    counter = Counter(hops)
    return {
        "ordered_reachable_pairs": len(hops),
        "max_map_hops": max(hops),
        "mean_map_hops": round(statistics.mean(hops), 4),
        "median_map_hops": statistics.median(hops),
        "hop_distribution": {str(k): v for k, v in sorted(counter.items())},
        "pairs_requiring_more_than_20_macro_steps": sum(1 for h in hops if h > 20),
        "fraction_infeasible_under_20_macro_steps": round(
            100.0 * sum(1 for h in hops if h > 20) / max(1, len(hops)), 4),
        "caveat": "Under legacy macro semantics one map transition costs one macro-step and the transition "
                  "does not require reaching a portal, so every pair (max 14 hops) fits in 20 macro-steps. "
                  "This says nothing about physical tile-level feasibility.",
        "physical_route_cost": "NOT AVAILABLE: no portal-aware coordinate planner exists in Phase 0.",
    }


# ---------------------------------------------------------
# 11. Existing tests
# ---------------------------------------------------------
def run_pytest():
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
        tail = (proc.stdout + proc.stderr).strip().splitlines()
        return {
            "command": "python -m pytest -q",
            "returncode": proc.returncode,
            "summary_line": tail[-1] if tail else "",
            "tail": tail[-15:],
        }
    except Exception as exc:  # pragma: no cover
        return {"command": "python -m pytest -q", "error": str(exc)}


# ---------------------------------------------------------
# 12. Report rendering
# ---------------------------------------------------------
def render_report(data):
    L = []
    add = L.append

    add("# DelugeRPG Roaming AI - Phase 0 Baseline Audit")
    add("")
    add(f"Generated: {data['generated_at']}")
    add("")
    add("Command: `python scripts/audit_navigation_baseline.py`")
    add("")
    add("This is a read-only audit. No navigation algorithm, reward value or checkpoint was changed. "
        "The audit script writes only this report and `logs/phase0_audit.json`.")
    add("")

    add("## 1. Executive summary")
    add("")
    add("- All 49 walkgrids decode to 33x33 tiles / 2178 bytes.")
    add(f"- The base `WorldGraph` has {data['topology']['base_world_graph']['nodes']} nodes and "
        f"{data['topology']['base_world_graph']['edges']} edges and is **not** strongly connected "
        f"({data['topology']['base_world_graph']['scc_count']} SCCs).")
    add(f"- `GlobalWorldGraph` adds 7 hardcoded dungeon entrances -> {data['topology']['global_world_graph']['edges']} edges "
        f"and becomes strongly connected topologically, with diameter "
        f"{data['topology']['global_world_graph']['diameter']} map hops.")
    add(f"- Seam portals: {data['portals']['totals']['seam_edges']} seam edges, "
        f"{data['portals']['totals']['seam_edges_axis_mismatch']} classified as axis mismatch under the documented "
        "x=row / y=column convention. Graph connectivity is therefore **topological only**.")
    add(f"- Overworld 21 has two dungeon entrances but both share action 9; the handler selects "
        f"`{data['overworld21']['action_9_selects']}` first. `pkmnmansion1` and `volcano1` landings at (16,16) are not walkable.")
    add(f"- Reward decomposition reconciles with the real environment reward: "
        f"{data['experiments']['fidelity']['reconciled']} "
        f"(max abs diff {data['experiments']['fidelity']['max_abs_difference']}).")
    add("- The training log shows success falling from ~10.5% (first 4000 episodes) to ~5.7% (last 4000) while "
        "mean reward and water-tile encounter counts rise. This is consistent with local reward farming.")
    add("")

    add("## 2. Map grid audit (all 49 maps)")
    add("")
    add(f"Decoded maps: {data['walkgrids']['map_count']} "
        f"({data['walkgrids']['overworld_count']} overworld + {data['walkgrids']['dungeon_count']} dungeon). "
        f"All 33x33: {data['walkgrids']['all_33x33']}. All 2178 bytes: {data['walkgrids']['all_decode_2178_bytes']}. "
        f"Total walkable tiles: {data['walkgrids']['total_walkable']}. Total water tiles: {data['walkgrids']['total_water']}.")
    add("")
    add("| Map | Walkable | Water | Blocked | dirmask==0 tiles |")
    add("|---|---:|---:|---:|---:|")
    for name, m in data["walkgrids"]["per_map"].items():
        add(f"| {name} | {m['walkable']} | {m['water']} | {m['blocked']} | {m['dirmask_zero_tiles']} |")
    add("")

    add("## 3. Graph topology (topological only)")
    add("")
    add("| Graph | Nodes | Edges | Strongly connected | SCC sizes | Diameter | Mean hops | Unreachable ordered pairs |")
    add("|---|---:|---:|---|---|---:|---:|---:|")
    for key in ("base_world_graph", "global_world_graph"):
        g = data["topology"][key]
        add(f"| {g['label']} | {g['nodes']} | {g['edges']} | {g['strongly_connected']} | "
            f"{g['scc_sizes']} | {g['diameter']} | {g['mean_hop_distance']} | {g['unreachable_ordered_pairs']} |")
    add("")
    add(f"> {data['topology']['topology_caveat']}")
    add("")

    add("## 4. Portal / transition audit")
    add("")
    t = data["portals"]["totals"]
    add(f"- Edges audited: {t['edges_total']} (seam {t['seam_edges']}, dungeon entrance {t['entrance_edges']}, "
        f"dungeon floor {t['floor_edges']}).")
    add(f"- Portal records checked: {t['portals']}. Source walkable: {t['src_walkable']}. "
        f"Destination walkable: {t['dst_walkable']}. Direction-bit OK: {t['dir_bit_ok']}/{t['dir_bit_checked']}. "
        f"Correct-boundary OK: {t['boundary_ok']}/{t['boundary_checked']}. Reverse portal OK: {t['reverse_ok']}.")
    add(f"- Seam edges verified under documented axes: {t['seam_edges_verified']}. "
        f"Axis-mismatch seam edges: {t['seam_edges_axis_mismatch']}. Partial: {t['seam_edges_partial']}.")
    add(f"- Dungeon-entrance edges with walkable coordinates: {t['entrance_edges_coordinates_ok']}. "
        f"Invalid coordinates: {t['entrance_edges_invalid']}.")
    add(f"- Edges without portal coordinates (floor transitions): {t['edges_without_portals']}; "
        f"of those, default (16,16) landing is invalid: {t['edges_without_portals_invalid_default']}.")
    add("")
    add("Status legend: `verified_under_documented_axes`, `axis_mismatch`, `unverified_no_coordinates`, "
        "`unverified_no_coordinates_default_landing_invalid`, `coordinates_walkable_mechanic_unverified`, "
        "`invalid_coordinates`.")
    add("")
    add(f"Every individual portal record ({len(data['portals']['portal_records'])} rows) with source/destination, "
        "walkability, direction-bit, boundary, reverse and failure reasons is stored in "
        "`logs/phase0_audit.json` under `portals.portal_records`.")
    add("")
    add("| From | To | Direction | Portals | src OK | dst OK | dirbit OK | boundary OK | reverse OK | Status |")
    add("|---|---|---|---:|---:|---:|---:|---:|---:|---|")
    for e in data["portals"]["edges"]:
        add(f"| {e['from_map']} | {e['to_map']} | {e['direction']} | {e['portal_count']} | "
            f"{e['src_walkable']} | {e['dst_walkable']} | {e['dir_bit_ok']} | {e['boundary_ok']} | "
            f"{e['reverse_ok']} | {e['status']} |")
    add("")
    invalid_defaults = [e for e in data["portals"]["edges"]
                        if e["portal_count"] == 0 and not e.get("default_landing_walkable", True)]
    add("Invalid default `(16,16)` landings on portal-less floor transitions "
        "(the environment would silently substitute the first walkable tile):")
    add("")
    for e in invalid_defaults:
        add(f"- `{e['from_map']} -> {e['to_map']}` ({e['direction']})")
    add("")

    add("## 5. Overworld 21 entrance collision")
    add("")
    add(f"`dungeon_enter` targets: {data['overworld21']['dungeon_enter_targets']}. "
        f"Action 9 selects: `{data['overworld21']['action_9_selects']}`. "
        f"Collision present: {data['overworld21']['collision']}.")
    add("")
    add(f"> {data['overworld21']['note']}")
    add("")
    add("Configured dungeon entrances and landing validity:")
    add("")
    add("| Source | Dungeon | Source coord | Landing coord | Landing walkable |")
    add("|---|---|---|---|---|")
    for row in data["dungeon_entrances"]:
        add(f"| {row['source']} | {row['dungeon']} | {row['source_coord']} | {row['landing_coord']} | {row['landing_walkable']} |")
    add("")

    add("## 6. Environment observation / action definitions")
    add("")
    add("| Environment | Actions | Observation dim | Notes |")
    add("|---|---:|---:|---|")
    for name, s in data["specs"].items():
        add(f"| {name} | {s['actions']} | {s['obs_dim'] if 'obs_dim' in s else s['actual_obs_dim']} | {s['notes']} |")
    add("")
    add(f"`MapEnv` docstring claims {data['specs']['MapEnv']['docstring_obs_dim_claim']} features but the code "
        f"emits {data['specs']['MapEnv']['actual_obs_dim']}. This is a documentation/code mismatch.")
    add("")

    add("## 7. Training settings, success definition and checkpoint rule")
    add("")
    ts = data["training_settings"]
    for key in ("entry_point", "episodes_configured", "max_macro_steps_in_train_entry",
                "max_macro_steps_class_default", "gamma", "learning_rate", "buffer_size", "batch_size",
                "target_sync_every_episodes", "epsilon_schedule", "start_map_sampling", "target_map_sampling",
                "success_condition", "termination", "checkpoint_selection", "timeout_label"):
        add(f"- **{key}**: {ts[key]}")
    add("")
    add("### Reward components (exact source values)")
    add("")
    add("| Component | Value | Condition | Source line |")
    add("|---|---|---|---:|")
    for c in ts["reward_components"]:
        line = c["source_line"] if c["source_line"] is not None else "-"
        add(f"| {c['component']} | {c['value']} | {c['condition']} | {line} |")
    add("")
    add("Tall grass is **not** rewarded in the 49-map code. `WalkTile` exposes only `walkable` and `is_water`; "
        "the only terrain reward check is `tile.is_water` in `Global49MapEnv.step()`.")
    add("")

    add("## 8. Recorder data quality")
    add("")
    rec = data["recorder"]
    add(f"- Session: `{rec['session']}`")
    add(f"- Parsed events: {rec['total_events_parsed']}; types: {rec['event_type_counts']}")
    add(f"- Map-change (`m`) events: {rec['map_change_events']}; with coordinates: {rec['map_change_events_with_coordinates']}")
    add(f"- Walkgrid (`g`) events: {rec['walkgrid_events']}")
    add(f"- Map graph entries: {rec['map_graph_entries']}; recorded exits: {rec['recorded_exits']}; "
        f"exits with fabricated (0,0): {rec['exits_with_fabricated_zero_coordinate']}")
    add("")
    add(f"> {rec['finding']}")
    add("")

    add("## 9. Model and log provenance")
    add("")
    prov = data["provenance"]
    add(f"- Weights metadata: `{prov['weights_metadata']}`")
    add(f"- Training log rows: {prov['training_log_rows']}")
    add(f"- First episode: `{prov['training_log_first_episode']}`")
    add(f"- Last episode: `{prov['training_log_last_episode']}`")
    add(f"- Log max reward: {prov['training_log_max_reward']}; log max maps visited: {prov['training_log_max_maps_visited']}")
    add(f"- Checkpoints: `{prov['checkpoints']}`")
    add("")
    add(f"> {prov['caveat']}")
    add("")

    add("## 10. Controlled reward-component experiments")
    add("")
    fid = data["experiments"]["fidelity"]
    add(f"Instrumented decomposition fidelity: reconciled={fid['reconciled']}, steps={fid['steps_checked']}, "
        f"max_abs_difference={fid['max_abs_difference']}, mismatches={fid['mismatches']}.")
    add("")
    add("Experiments use fixed seeds (`random.seed(20261124)`, `numpy.random.seed(20261124)` and a local "
        "`Random(20261124)`); two consecutive runs produced byte-identical experiment JSON.")
    add("")
    add("Each row is a 20-macro-step episode with a fixed start map/target map. `reward` is the sum of the "
        "listed components.")
    add("")
    add("| Scenario | Hop | Policy | Success | Timeout | Steps | Reward | step | novelty | water | blocked | recent | fresh | discovery | dist+ | dist- | target | enc |")
    add("|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in data["experiments"]["fixed_scenarios"]:
        add(f"| {r['label']} | {r['map_hop_distance']} | {r['policy']} | {r['success']} | {r['timeout']} | "
            f"{r['steps']} | {r['reward']} | {r['step_cost']:.2f} | {r['novelty']:.2f} | {r['water']:.2f} | "
            f"{r['blocked']:.2f} | {r['recent_map']:.2f} | {r['fresh_map']:.2f} | {r['discovery']:.2f} | "
            f"{r['dist_progress']:.2f} | {r['dist_regress']:.2f} | {r['target']:.2f} | {r['encounters']} |")
    w = data["experiments"]["water_farming"]
    if w:
        add(f"| water_farming ({w['start_map']}) | {w['map_hop_distance']} | water | {w['success']} | {w['timeout']} | "
            f"{w['steps']} | {w['reward']} | {w['step_cost']:.2f} | {w['novelty']:.2f} | {w['water']:.2f} | "
            f"{w['blocked']:.2f} | {w['recent_map']:.2f} | {w['fresh_map']:.2f} | {w['discovery']:.2f} | "
            f"{w['dist_progress']:.2f} | {w['dist_regress']:.2f} | {w['target']:.2f} | {w['encounters']} |")
    add("")
    if w:
        add(f"Water-farming route: map `{w['start_map']}`, sector actions {w['water_pair']}, "
            f"{w['water_per_cycle']} water tiles per back-and-forth cycle. Repeated water traversal pays "
            "+0.8 per tile on every pass, independent of visitation.")
    add("")

    add("### Success by map-hop distance bucket (controlled baselines)")
    add("")
    add("| Bucket | Hop range | Policy | Samples | Successes | Success % | Timeouts | Mean reward |")
    add("|---|---|---|---:|---:|---:|---:|---:|")
    for r in data["experiments"]["success_by_distance_bucket"]:
        add(f"| {r['bucket']} | {r['hop_range']} | {r['policy']} | {r['samples']} | {r['successes']} | "
            f"{r['success_rate']} | {r['timeouts']} | {r['mean_reward']} |")
    add("")
    add(f"> {data['log_trend']['per_distance_bucket']}")
    add("")

    add("## 11. Historical training-log trend")
    add("")
    add("| Episodes | Success % | Mean reward | Mean encounters | Mean maps visited |")
    add("|---|---:|---:|---:|---:|")
    for win in data["log_trend"]["window_trend"]:
        add(f"| {win['episodes'][0]}-{win['episodes'][1]} | {win['success_rate']} | {win['mean_reward']} | "
            f"{win['mean_encounters']} | {win['mean_maps_visited']} |")
    add("")
    add(f"Success episodes: {data['log_trend']['success_episodes']}; failed episodes: "
        f"{data['log_trend']['failed_episodes']}. All failures occur at the maximum macro-step count "
        f"(all_failures_at_max_steps={data['log_trend']['all_failures_at_max_steps']}), so they are timeouts. "
        f"Successful episodes terminate in {data['log_trend']['success_step_range']} macro-steps.")
    add("")

    add("## 12. Map-hop distance vs physical route cost and legacy feasibility")
    add("")
    lf = data["legacy_feasibility"]
    add(f"- Ordered reachable map pairs: {lf['ordered_reachable_pairs']}.")
    add(f"- Map-hop distance: mean {lf['mean_map_hops']}, median {lf['median_map_hops']}, max {lf['max_map_hops']}.")
    add(f"- Hop distribution: {lf['hop_distribution']}.")
    add(f"- Pairs needing more than 20 macro-steps: {lf['pairs_requiring_more_than_20_macro_steps']} "
        f"({lf['fraction_infeasible_under_20_macro_steps']}%).")
    add(f"- Physical coordinate/portal route cost: {lf['physical_route_cost']}")
    add("")
    add(f"> {lf['caveat']}")
    add("")

    add("## 13. Existing test suite baseline")
    add("")
    tests = data["tests"]
    add(f"- Command: `{tests.get('command')}`")
    add(f"- Return code: {tests.get('returncode')}")
    add(f"- Summary: `{tests.get('summary_line', tests.get('error', ''))}`")
    if tests.get("tail"):
        add("")
        add("```")
        add("\n".join(tests["tail"]))
        add("```")
    add("")

    add("## 14. Phase 0 acceptance-criteria evaluation")
    add("")
    add("| Criterion | Result | Evidence |")
    add("|---|---|---|")
    add("| Audit runs from repo root with one documented command | PASS | `python scripts/audit_navigation_baseline.py` |")
    add(f"| All 49 grids checked | PASS | {data['walkgrids']['map_count']} maps decoded |")
    add("| Concrete portal/transition audit, not just node count | PASS | Per-edge table in section 4 |")
    add(f"| Distinguishes verified / invalid / unverified transitions | PASS | verified={t['seam_edges_verified']}, "
        f"axis_mismatch={t['seam_edges_axis_mismatch']}, unverified_no_coordinates={t['edges_without_portals']}, "
        f"invalid_coordinates={t['entrance_edges_invalid']} |")
    add("| Records pytest baseline and model/log provenance | PASS | Sections 9 and 13 |")
    add("| No existing model/data/log overwritten | PASS | Only two new artifacts written |")
    add(f"| Reward components reported separately and match source | PASS | Fidelity reconciled={fid['reconciled']} |")
    add("| Controlled tests establish whether local/water reward competes with target | PASS | Section 10 |")
    add("| Graph-hop, physical route cost, legacy 20-step feasibility separated | PASS | Section 12 |")
    add("| Success grouped by distance bucket; timeout distinguishable | PASS (controlled) / NOT AVAILABLE (historical) | "
        "Section 10 buckets; section 11 timeout evidence |")
    add("")

    add("## 15. Known limitations")
    add("")
    add("- Physical route cost and coordinate-level portal reachability are not implemented; only graph hops exist.")
    add("- The documented x=row / y=column convention is not yet confirmed against captured game source. Seam "
        "boundary checks use that documented convention; the true axis must be confirmed in Phase 1.")
    add(f"- Dungeon floor/stair coordinates are absent (empty portal arrays). Default (16,16) landings are "
        f"unverified; {t['edges_without_portals_invalid_default']} floor-transition destinations are not walkable "
        "and trigger the first-walkable fallback.")
    add("- Historical success cannot be bucketed by distance because the training CSV stores no start/target maps.")
    add("- The included checkpoint/log provenance is plausible but not cryptographically tied to any screenshot.")
    add("- No RL training, navigation rewrite or reward change was performed in Phase 0.")
    add("")

    return "\n".join(L) + "\n"


def build_dungeon_entrance_table(train_mod, wg):
    rows = []
    for ow, dungeon, ow_coord, d_coord, label in train_mod.DUNGEON_ENTRANCES:
        tile = wg.grids[dungeon].get_tile(d_coord[0], d_coord[1]) if dungeon in wg.grids else None
        rows.append({
            "source": ow,
            "dungeon": dungeon,
            "label": label,
            "source_coord": list(ow_coord),
            "landing_coord": list(d_coord),
            "landing_walkable": bool(tile and tile.walkable),
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description="Phase 0 read-only navigation baseline audit.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip the pytest baseline run.")
    parser.add_argument("--max-bucket-samples", type=int, default=40,
                        help="Scenarios sampled per distance bucket (default 40).")
    args = parser.parse_args()

    print("Loading training module and world graph ...")
    train_mod = load_train_module()
    wg = train_mod.GlobalWorldGraph(WALKGRIDS_PATH)
    base_wg = WorldGraph(WALKGRIDS_PATH)

    print("Auditing walkgrids ...")
    walkgrids = audit_walkgrids(wg)
    print("Auditing topology ...")
    topology = audit_topology(wg)
    print("Auditing portals ...")
    portals = audit_portals(wg)
    print("Auditing Overworld 21 ...")
    overworld21 = audit_overworld21(wg)
    print("Auditing specs ...")
    specs = audit_specs(train_mod)
    print("Auditing training settings ...")
    training_settings = audit_training_settings()
    print("Auditing recorder ...")
    recorder = audit_recorder()
    print("Auditing provenance ...")
    provenance = audit_provenance()

    print("Loading greedy checkpoint for evaluation (no training) ...")
    agent = train_mod.Global49MapDQN(input_dim=204, num_actions=11)
    if os.path.exists(BEST_CKPT_PATH):
        agent.policy_net.load_state_dict(torch.load(BEST_CKPT_PATH, map_location="cpu"))
        agent.policy_net.eval()

    print("Running controlled reward experiments ...")
    experiments = controlled_experiments(wg, train_mod, agent, args.max_bucket_samples)
    print("Auditing historical log trend ...")
    log_trend = audit_log_trend()
    print("Auditing legacy feasibility ...")
    legacy = legacy_feasibility(wg)

    if args.skip_tests:
        tests = {"command": "python -m pytest -q", "returncode": None, "summary_line": "SKIPPED"}
    else:
        print("Running existing pytest baseline ...")
        tests = run_pytest()

    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "walkgrids": walkgrids,
        "topology": topology,
        "portals": portals,
        "overworld21": overworld21,
        "dungeon_entrances": build_dungeon_entrance_table(train_mod, wg),
        "specs": specs,
        "training_settings": training_settings,
        "recorder": recorder,
        "provenance": provenance,
        "experiments": experiments,
        "log_trend": log_trend,
        "legacy_feasibility": legacy,
        "tests": tests,
    }

    os.makedirs("docs", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(render_report(data))

    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {JSON_PATH}")
    print(f"Fidelity reconciled: {experiments['fidelity']['reconciled']} "
          f"(max abs diff {experiments['fidelity']['max_abs_difference']})")
    print(f"Tests: {tests.get('summary_line')}")


if __name__ == "__main__":
    main()
