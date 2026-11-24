"""Plan and print one deterministic local/global route."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from delugerpg.agents.multi_map_planner import GlobalNavigator, load_navigation_data


def parse_coord(value: str):
    parts = value.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("Coordinate must be row,column")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Coordinate values must be integers") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-map", required=True)
    parser.add_argument("--start", required=True, type=parse_coord)
    parser.add_argument("--goal-map", required=True)
    parser.add_argument("--goal", required=True, type=parse_coord)
    parser.add_argument("--registry", default="data/processed/transition_registry_v1.json")
    parser.add_argument("--walkgrids", default="data/raw/delugerpg_all_walkgrids.json")
    parser.add_argument("--require-verified", action="store_true")
    parser.add_argument("--ascii", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    registry, grids = load_navigation_data(args.registry, args.walkgrids)
    navigator = GlobalNavigator(
        registry,
        grids,
        allow_unverified=not args.require_verified,
    )
    route = navigator.plan(args.start_map, args.start, args.goal_map, args.goal)
    if args.json:
        print(json.dumps(route.to_dict(), indent=2, sort_keys=True))
    else:
        print(navigator.describe_route(route, include_ascii=args.ascii))
    return 0 if route.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
