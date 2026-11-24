"""
Unit tests for the Hierarchical Path Planner Agent.
"""

import os
import sqlite3
import pytest
import numpy as np
import torch

from delugerpg.parsers.walkgrid import WalkGrid
from delugerpg.agents.path_planner import (
    PathPlannerEnv,
    PathPlannerDQN,
    WAYPOINTS_OW1,
)


@pytest.fixture
def ow1_walkgrid():
    db_path = os.path.join("data", "processed", "delugerpg_kb.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    row = cur.execute("SELECT walkgrid_b64 FROM map_walkgrids WHERE map_name = ?", ("overworld1",)).fetchone()
    conn.close()
    assert row is not None, "overworld1 walkgrid missing from database"
    return WalkGrid.from_base64(row[0], "overworld1")


def test_waypoint_definitions(ow1_walkgrid):
    assert len(WAYPOINTS_OW1) == 16
    for wp in WAYPOINTS_OW1:
        tile = ow1_walkgrid.get_tile(wp.x, wp.y)
        assert tile is not None and tile.walkable, f"Waypoint {wp.name} at ({wp.x}, {wp.y}) must be walkable"


def test_path_planner_env_step(ow1_walkgrid):
    env = PathPlannerEnv(ow1_walkgrid, max_macro_steps=5)
    obs = env.reset(start_pos=(8, 29))

    assert obs.shape == (67,)
    assert obs[0] == pytest.approx(8 / 32.0, 1e-4)
    assert obs[1] == pytest.approx(29 / 32.0, 1e-4)

    mask = env.get_action_mask()
    assert len(mask) == 16
    # Waypoint 2 is (8, 29), so mask[2] should be 0.0
    assert mask[2] == 0.0

    # Step to Waypoint 0: (4, 28)
    next_obs, reward, done, info = env.step(0)
    assert next_obs.shape == (67,)
    assert reward > 0
    assert info["path_length"] > 0
    assert env.curr_x == 4
    assert env.curr_y == 28

    # Next mask should prevent immediate backtracking to 0
    next_mask = env.get_action_mask()
    assert next_mask[0] == 0.0


def test_path_planner_dqn_action_selection(ow1_walkgrid):
    env = PathPlannerEnv(ow1_walkgrid, max_macro_steps=5)
    obs = env.reset(start_pos=(8, 29))
    mask = env.get_action_mask()

    agent = PathPlannerDQN(input_dim=67, num_actions=16)
    action = agent.select_action(obs, mask, epsilon=0.0)

    assert 0 <= action < 16
    assert mask[action] > 0.5, "Selected action must be valid according to mask"


def test_path_planner_export_weights(ow1_walkgrid):
    agent = PathPlannerDQN(input_dim=67, num_actions=16)
    weights = agent.export_weights_dict()

    assert weights["model_type"] == "PathPlannerDQN"
    assert weights["input_dim"] == 67
    assert weights["output_dim"] == 16
    assert len(weights["layers"]) == 4
    assert len(weights["waypoints"]) == 16
