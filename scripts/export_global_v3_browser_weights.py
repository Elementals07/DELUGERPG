"""Export the DelugeRPG global DQN V3 checkpoint for OrangeMonkey inference."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import random
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np
import torch

import sys

sys.path.insert(0, os.path.abspath("."))
from scripts.train_global_49maps import (
    ACTION_NAMES,
    DuelingDQN,
    Global49MapDQNv2,
    GlobalWorldGraph,
    ImprovedGlobal49MapEnv,
)


EXPECTED_SHAPES = {
    "feature_net.0.weight": (256, 190),
    "feature_net.0.bias": (256,),
    "feature_net.2.weight": (128, 256),
    "feature_net.2.bias": (128,),
    "value_stream.0.weight": (64, 128),
    "value_stream.0.bias": (64,),
    "value_stream.2.weight": (1, 64),
    "value_stream.2.bias": (1,),
    "advantage_stream.0.weight": (64, 128),
    "advantage_stream.0.bias": (64,),
    "advantage_stream.2.weight": (11, 64),
    "advantage_stream.2.bias": (11,),
}


def validate_and_export(
    checkpoint_path: str,
    output_path: str,
) -> Dict[str, object]:
    if not os.path.isfile(checkpoint_path):
        raise FileNotFoundError(
            f"Checkpoint not found: {checkpoint_path}"
        )

    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    state = checkpoint.get("policy_net_state")
    if not isinstance(state, dict):
        raise ValueError("Checkpoint does not contain policy_net_state")
    if int(checkpoint.get("obs_dim", -1)) != 190:
        raise ValueError("Checkpoint obs_dim is not 190")
    if int(checkpoint.get("num_actions", -1)) != 11:
        raise ValueError("Checkpoint num_actions is not 11")

    for key, expected_shape in EXPECTED_SHAPES.items():
        tensor = state.get(key)
        if tensor is None:
            raise ValueError(f"Missing parameter: {key}")
        actual_shape = tuple(tensor.shape)
        if actual_shape != expected_shape:
            raise ValueError(
                f"Unexpected shape for {key}: {actual_shape}; "
                f"expected {expected_shape}"
            )

    world = GlobalWorldGraph()
    map_names = sorted(world.grids.keys())
    if len(map_names) != 49:
        raise ValueError(f"Expected 49 maps, found {len(map_names)}")

    net = DuelingDQN(190, 11)
    net.load_state_dict(state)
    net.eval()

    observations = [
        [0.0] * 190,
        [1.0 if i < 49 else 0.0 for i in range(190)],
    ]
    rng = random.Random(12345)
    observations.append([rng.uniform(-0.01, 1.01) for _ in range(190)])

    walkgrids = {
        name: base64.b64encode(world.grids[name].raw_bytes).decode("ascii")
        for name in map_names
    }
    with open("data/processed/transition_registry_v1.json", "r", encoding="utf-8") as handle:
        registry_payload = json.load(handle)

    sector_centers = [(8, 8), (24, 8), (16, 16), (8, 24), (24, 24)]
    sector_waypoints: Dict[str, List[List[int]]] = {}
    for name in map_names:
        grid = world.grids[name]
        walkable = [
            (x, y)
            for y in range(33)
            for x in range(33)
            if grid.get_tile(x, y) and grid.get_tile(x, y).walkable
        ]
        waypoints = []
        for cx, cy in sector_centers:
            best = min(walkable, key=lambda tile: (tile[0] - cx) ** 2 + (tile[1] - cy) ** 2)
            waypoints.append([int(best[0]), int(best[1])])
        sector_waypoints[name] = waypoints

    planner_env = ImprovedGlobal49MapEnv(world, max_macro_steps=30, seed=42)
    map_indices = {name: index for index, name in enumerate(map_names)}
    macro_edges = []
    for source, destinations in planner_env.oracle._macro_transition_adj.items():
        source_map, source_coord = source
        source_index = map_indices[source_map] * 1089 + source_coord[0] * 33 + source_coord[1]
        for destination, _cost in destinations:
            destination_map, destination_coord = destination
            destination_index = (
                map_indices[destination_map] * 1089 +
                destination_coord[0] * 33 +
                destination_coord[1]
            )
            macro_edges.append([source_index, destination_index])

    python_qvalues: List[List[float]] = []
    selected_actions: List[int] = []
    with torch.no_grad():
        for observation in observations:
            tensor = torch.tensor([observation], dtype=torch.float32)
            qvalues = net(tensor).squeeze(0).tolist()
            python_qvalues.append(qvalues)
            selected_actions.append(int(np.argmax(qvalues)))

    parameters = {
        key: tensor.detach().cpu().numpy().astype("<f4").tolist()
        for key, tensor in state.items()
    }

    payload = {
        "model_version": "Global49MapDQN-v3",
        "checkpoint": os.path.basename(checkpoint_path),
        "checkpoint_episode": int(checkpoint.get("episode", 0)),
        "checkpoint_format": checkpoint.get("format"),
        "input_dim": 190,
        "output_dim": 11,
        "activation": "relu",
        "output_calculation": "value + (advantage - mean(advantage))",
        "architecture": [
            {"name": "feature_net.0", "type": "Linear", "in": 190, "out": 256, "activation": "ReLU"},
            {"name": "feature_net.2", "type": "Linear", "in": 256, "out": 128, "activation": "ReLU"},
            {"name": "value_stream.0", "type": "Linear", "in": 128, "out": 64, "activation": "ReLU"},
            {"name": "value_stream.2", "type": "Linear", "in": 64, "out": 1, "activation": None},
            {"name": "advantage_stream.0", "type": "Linear", "in": 128, "out": 64, "activation": "ReLU"},
            {"name": "advantage_stream.2", "type": "Linear", "in": 64, "out": 11, "activation": None},
        ],
        "action_names": list(ACTION_NAMES),
        "map_names": map_names,
        "map_count": len(map_names),
        "sector_targets": [
            [8, 8],
            [24, 8],
            [16, 16],
            [8, 24],
            [24, 24],
        ],
        "sector_waypoints": sector_waypoints,
        "macro_edges": macro_edges,
        "walkgrids": walkgrids,
        "transition_registry": registry_payload,
        "observation_layout": [
            {"name": "current_map_one_hot", "start": 0, "size": 49},
            {"name": "target_map_one_hot", "start": 49, "size": 49},
            {"name": "current_x", "start": 98, "size": 1, "divisor": 32},
            {"name": "current_y", "start": 99, "size": 1, "divisor": 32},
            {"name": "target_x", "start": 100, "size": 1, "divisor": 32},
            {"name": "target_y", "start": 101, "size": 1, "divisor": 32},
            {"name": "same_map", "start": 102, "size": 1},
            {"name": "remaining_macro_cost", "start": 103, "size": 1, "divisor": 30},
            {"name": "map_hops", "start": 104, "size": 1, "divisor": 10},
            {"name": "local_target_distance", "start": 105, "size": 1, "divisor": 64},
            {"name": "visited_map_one_hot", "start": 106, "size": 49},
            {"name": "current_map_visit_count", "start": 155, "size": 1, "divisor": 5},
            {"name": "recent_map_history", "start": 156, "size": 5, "map_divisor": 49},
            {"name": "recent_actions", "start": 161, "size": 4, "action_divisor": 10},
            {"name": "action_mask", "start": 165, "size": 11},
            {"name": "warp_costs", "start": 176, "size": 4},
            {"name": "allowed_directions", "start": 180, "size": 8},
            {"name": "transition_source_present", "start": 188, "size": 1},
            {"name": "local_coverage", "start": 189, "size": 1},
        ],
        "parameters": parameters,
        "test_vectors": [
            {
                "observation": observation,
                "python_qvalues": qvalues,
                "python_selected_action": selected,
            }
            for observation, qvalues, selected in zip(
                observations,
                python_qvalues,
                selected_actions,
            )
        ],
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    return payload


def compare_python_and_javascript(payload: Dict[str, object], output_path: str) -> Dict[str, object]:
    js_code = r"""
const fs = require('fs');
const model = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
function linear(input, weight, bias) {
  const output = new Array(weight.length).fill(0);
  for (let r = 0; r < weight.length; r++) {
    let sum = bias[r];
    const row = weight[r];
    for (let c = 0; c < row.length; c++) sum += input[c] * row[c];
    output[r] = sum;
  }
  return output;
}
function relu(input) { return input.map(v => v > 0 ? v : 0); }
function forward(input) {
  const p = model.parameters;
  let x = relu(linear(input, p['feature_net.0.weight'], p['feature_net.0.bias']));
  x = relu(linear(x, p['feature_net.2.weight'], p['feature_net.2.bias']));
  const value = linear(x, p['value_stream.0.weight'], p['value_stream.0.bias']);
  let valueOut = linear(relu(value), p['value_stream.2.weight'], p['value_stream.2.bias']);
  let adv = relu(linear(x, p['advantage_stream.0.weight'], p['advantage_stream.0.bias']));
  adv = linear(adv, p['advantage_stream.2.weight'], p['advantage_stream.2.bias']);
  const mean = adv.reduce((s, v) => s + v, 0) / adv.length;
  return adv.map((v, i) => valueOut[0] + (v - mean));
}
const results = model.test_vectors.map(v => {
  const q = forward(v.observation);
  let selected = 0;
  for (let i = 1; i < q.length; i++) if (q[i] > q[selected]) selected = i;
  return {qvalues: q, selected};
});
process.stdout.write(JSON.stringify(results));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(js_code)
        js_path = handle.name
    try:
        absolute_output_path = os.path.abspath(output_path)
        try:
            result = subprocess.run(
                ["node", js_path, absolute_output_path],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"JavaScript inference comparison failed: {exc.stderr}"
            ) from exc
        js_results = json.loads(result.stdout)
    finally:
        os.unlink(js_path)

    comparisons = []
    max_q_error = 0.0
    selected_match = True
    for test, js_result in zip(payload["test_vectors"], js_results):
        q_error = max(
            abs(float(a) - float(b))
            for a, b in zip(test["python_qvalues"], js_result["qvalues"])
        )
        max_q_error = max(max_q_error, q_error)
        action_match = int(test["python_selected_action"]) == int(js_result["selected"])
        selected_match = selected_match and action_match
        comparisons.append({
            "max_q_error": q_error,
            "python_action": test["python_selected_action"],
            "javascript_action": js_result["selected"],
            "selected_match": action_match,
        })
    report = {
        "tolerance": 2e-5,
        "selected_actions_match": selected_match,
        "max_q_error": max_q_error,
        "pass": selected_match and max_q_error <= 2e-5,
        "comparisons": comparisons,
    }
    if not report["pass"]:
        raise RuntimeError(f"Python/JavaScript inference mismatch: {report}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint",
        default="models/global_49map_dqn_v3_best.pt",
    )
    parser.add_argument(
        "--output",
        default="data/processed/global_49map_v3_browser_weights.json",
    )
    parser.add_argument("--skip-js-compare", action="store_true")
    args = parser.parse_args()

    payload = validate_and_export(args.checkpoint, args.output)
    print(
        f"Exported V3 browser weights: {args.output} "
        f"({os.path.getsize(args.output)} bytes)"
    )
    print(
        f"Checkpoint: {payload['checkpoint']} "
        f"episode {payload['checkpoint_episode']}"
    )
    print(
        f"Architecture: 190 -> 256 -> 128 -> "
        f"(value 64 -> 1; advantage 64 -> 11)"
    )
    if not args.skip_js_compare:
        report = compare_python_and_javascript(payload, args.output)
        print(
            "Python/JavaScript compare: "
            f"pass={report['pass']} max_q_error={report['max_q_error']:.8f}"
        )


if __name__ == "__main__":
    main()
