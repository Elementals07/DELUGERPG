# Unresolved Transition Dependencies

Generated: 2026-11-24T14:07:39.233990+00:00

Registry: `data/processed/transition_registry_v1.json` version `1.0.0` with `2058` records.

## Hard blockers

### INVALID transitions (4)

| Portal | Source | Destination | Reasons |
| --- | --- | --- | --- |
| entrance:overworld21->pkmnmansion1 | overworld21 (10, 10) | pkmnmansion1 (16, 16) | destination_not_walkable |
| exit:pkmnmansion1->overworld21 | pkmnmansion1 (16, 16) | overworld21 (10, 10) | source_not_walkable |
| entrance:overworld21->volcano1 | overworld21 (22, 22) | volcano1 (16, 16) | destination_not_walkable |
| exit:volcano1->overworld21 | volcano1 (16, 16) | overworld21 (22, 22) | source_not_walkable |

These transitions are excluded from every route. In particular, both `overworld21` dungeon
entrances are blocked by non-walkable `(16,16)` destination tiles. The observed dungeon entry
spawns are not portal landings and are not used as substitutes.

### Missing coordinates (34)

| Portal | Source map | Destination map |
| --- | --- | --- |
| floor:pkmnmansion1->pkmnmansion2 | pkmnmansion1 | pkmnmansion2 |
| floor:pkmnmansion2->pkmnmansion1 | pkmnmansion2 | pkmnmansion1 |
| floor:pkmnmansion2->pkmnmansion3 | pkmnmansion2 | pkmnmansion3 |
| floor:pkmnmansion3->pkmnmansion2 | pkmnmansion3 | pkmnmansion2 |
| floor:pkmnmansion3->pkmnmansion4 | pkmnmansion3 | pkmnmansion4 |
| floor:pkmnmansion4->pkmnmansion3 | pkmnmansion4 | pkmnmansion3 |
| floor:pkmntower1->pkmntower2 | pkmntower1 | pkmntower2 |
| floor:pkmntower2->pkmntower1 | pkmntower2 | pkmntower1 |
| floor:pkmntower2->pkmntower3 | pkmntower2 | pkmntower3 |
| floor:pkmntower3->pkmntower2 | pkmntower3 | pkmntower2 |
| floor:powerplant1->powerplant2 | powerplant1 | powerplant2 |
| floor:powerplant2->powerplant1 | powerplant2 | powerplant1 |
| floor:powerplant2->powerplant3 | powerplant2 | powerplant3 |
| floor:powerplant3->powerplant2 | powerplant3 | powerplant2 |
| floor:rockcave1->rockcave2 | rockcave1 | rockcave2 |
| floor:rockcave2->rockcave1 | rockcave2 | rockcave1 |
| floor:rockcave2->rockcave3 | rockcave2 | rockcave3 |
| floor:rockcave3->rockcave2 | rockcave3 | rockcave2 |
| floor:rockcave3->rockcave4 | rockcave3 | rockcave4 |
| floor:rockcave4->rockcave3 | rockcave4 | rockcave3 |
| floor:snowcave1->snowcave2 | snowcave1 | snowcave2 |
| floor:snowcave2->snowcave1 | snowcave2 | snowcave1 |
| floor:snowcave2->snowcave3 | snowcave2 | snowcave3 |
| floor:snowcave3->snowcave2 | snowcave3 | snowcave2 |
| floor:snowcave3->snowcave4 | snowcave3 | snowcave4 |
| floor:snowcave4->snowcave3 | snowcave4 | snowcave3 |
| floor:unownruins1->unownruins2 | unownruins1 | unownruins2 |
| floor:unownruins2->unownruins1 | unownruins2 | unownruins1 |
| floor:volcano1->volcano2 | volcano1 | volcano2 |
| floor:volcano2->volcano1 | volcano2 | volcano1 |
| floor:volcano2->volcano3 | volcano2 | volcano3 |
| floor:volcano3->volcano2 | volcano3 | volcano2 |
| floor:volcano3->volcano4 | volcano3 | volcano4 |
| floor:volcano4->volcano3 | volcano4 | volcano3 |

All 34 are dungeon-floor transitions. They have no recorded stair/ladder source or landing
coordinates, so no route through them can be planned.

## Physical verification gaps

- `VERIFIED` transitions: **0**
- `UNVERIFIED` overworld seams: **2010**
  (directions: {"east": 526, "north": 479, "south": 479, "west": 526})
- `UNVERIFIED` overworld-to-dungeon entrances: **10**

The seam records have verified boundary geometry, source direction bits, walkable endpoints,
and reverse records. Their server-side landing coordinates were not observed, so they remain
UNVERIFIED. The entrance records have known coordinates but their physical landings were not
observed either.

## OW21 parallel entrances

`overworld21` has two physically distinct entrance source coordinates:

- Mansion: source `(10,10)` to `pkmnmansion1`, currently INVALID because `(16,16)` is not walkable.
- Volcano: source `(22,22)` to `volcano1`, currently INVALID because `(16,16)` is not walkable.

The planner treats these as independent transitions. It never substitutes the observed dungeon
entry spawn for the missing portal landing. The Phase 2 tests use a clearly labeled simulated
registry to exercise independent Mansion/Volcano selection.

## Full data

- `data/processed/unresolved_transition_dependencies.json` contains the full invalid list, missing-coordinate list, unverified
  entrance list, and all 2,010 unverified seam portal IDs.
- `data/processed/route_feasibility_report.json` contains the scenario results and coverage metrics.
