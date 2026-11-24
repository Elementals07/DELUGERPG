# DelugeRPG Roaming AI - Phase 0 Baseline Audit

Generated: 2026-11-24T17:58:46

Command: `python scripts/audit_navigation_baseline.py`

This is a read-only audit. No navigation algorithm, reward value or checkpoint was changed. The audit script writes only this report and `logs/phase0_audit.json`.

## 1. Executive summary

- All 49 walkgrids decode to 33x33 tiles / 2178 bytes.
- The base `WorldGraph` has 49 nodes and 112 edges and is **not** strongly connected (8 SCCs).
- `GlobalWorldGraph` adds 7 hardcoded dungeon entrances -> 126 edges and becomes strongly connected topologically, with diameter 14 map hops.
- Seam portals: 78 seam edges, 78 classified as axis mismatch under the documented x=row / y=column convention. Graph connectivity is therefore **topological only**.
- Overworld 21 has two dungeon entrances but both share action 9; the handler selects `pkmnmansion1` first. `pkmnmansion1` and `volcano1` landings at (16,16) are not walkable.
- Reward decomposition reconciles with the real environment reward: True (max abs diff 3.552713678800501e-15).
- The training log shows success falling from ~10.5% (first 4000 episodes) to ~5.7% (last 4000) while mean reward and water-tile encounter counts rise. This is consistent with local reward farming.

## 2. Map grid audit (all 49 maps)

Decoded maps: 49 (25 overworld + 24 dungeon). All 33x33: True. All 2178 bytes: True. Total walkable tiles: 34117. Total water tiles: 9604.

| Map | Walkable | Water | Blocked | dirmask==0 tiles |
|---|---:|---:|---:|---:|
| overworld1 | 532 | 78 | 557 | 557 |
| overworld10 | 659 | 15 | 430 | 430 |
| overworld11 | 584 | 376 | 505 | 505 |
| overworld12 | 815 | 535 | 274 | 274 |
| overworld13 | 792 | 373 | 297 | 297 |
| overworld14 | 778 | 290 | 311 | 311 |
| overworld15 | 783 | 259 | 306 | 306 |
| overworld16 | 747 | 609 | 342 | 342 |
| overworld17 | 744 | 222 | 345 | 345 |
| overworld18 | 746 | 341 | 343 | 343 |
| overworld19 | 759 | 343 | 330 | 330 |
| overworld2 | 596 | 64 | 493 | 493 |
| overworld20 | 862 | 430 | 227 | 227 |
| overworld21 | 956 | 783 | 133 | 133 |
| overworld22 | 948 | 659 | 141 | 141 |
| overworld23 | 944 | 557 | 145 | 145 |
| overworld24 | 862 | 367 | 227 | 227 |
| overworld25 | 762 | 358 | 327 | 327 |
| overworld3 | 888 | 631 | 201 | 201 |
| overworld4 | 738 | 0 | 351 | 351 |
| overworld5 | 576 | 0 | 513 | 513 |
| overworld6 | 741 | 45 | 348 | 348 |
| overworld7 | 705 | 174 | 384 | 384 |
| overworld8 | 930 | 542 | 159 | 159 |
| overworld9 | 739 | 38 | 350 | 350 |
| pkmnmansion1 | 676 | 0 | 413 | 413 |
| pkmnmansion2 | 553 | 0 | 536 | 536 |
| pkmnmansion3 | 548 | 0 | 541 | 541 |
| pkmnmansion4 | 571 | 0 | 518 | 518 |
| pkmntower1 | 416 | 0 | 673 | 673 |
| pkmntower2 | 450 | 0 | 639 | 639 |
| pkmntower3 | 477 | 0 | 612 | 612 |
| powerplant1 | 537 | 0 | 552 | 552 |
| powerplant2 | 494 | 0 | 595 | 595 |
| powerplant3 | 456 | 0 | 633 | 633 |
| rockcave1 | 833 | 171 | 256 | 256 |
| rockcave2 | 766 | 18 | 323 | 323 |
| rockcave3 | 817 | 126 | 272 | 272 |
| rockcave4 | 858 | 711 | 231 | 231 |
| snowcave1 | 717 | 0 | 372 | 372 |
| snowcave2 | 733 | 0 | 356 | 356 |
| snowcave3 | 877 | 353 | 212 | 212 |
| snowcave4 | 855 | 136 | 234 | 234 |
| unownruins1 | 621 | 0 | 468 | 468 |
| unownruins2 | 652 | 0 | 437 | 437 |
| volcano1 | 535 | 0 | 554 | 554 |
| volcano2 | 520 | 0 | 569 | 569 |
| volcano3 | 458 | 0 | 631 | 631 |
| volcano4 | 511 | 0 | 578 | 578 |

## 3. Graph topology (topological only)

| Graph | Nodes | Edges | Strongly connected | SCC sizes | Diameter | Mean hops | Unreachable ordered pairs |
|---|---:|---:|---|---|---:|---:|---:|
| WorldGraph (overworld seams + dungeon floor chains) | 49 | 112 | False | [25, 4, 4, 4, 4, 3, 3, 2] | None | 3.2054 | 1690 |
| GlobalWorldGraph (+ 7 hardcoded overworld->dungeon entrances) | 49 | 126 | True | [49] | 14 | 5.818 | 0 |

> All connectivity here is TOPOLOGICAL (map-name graph). It is not evidence that a player can physically walk to a portal or that a landing coordinate is valid.

## 4. Portal / transition audit

- Edges audited: 126 (seam 78, dungeon entrance 14, dungeon floor 34).
- Portal records checked: 1646. Source walkable: 1644. Destination walkable: 1644. Direction-bit OK: 1632/1632. Correct-boundary OK: 0/1632. Reverse portal OK: 1584.
- Seam edges verified under documented axes: 0. Axis-mismatch seam edges: 78. Partial: 0.
- Dungeon-entrance edges with walkable coordinates: 10. Invalid coordinates: 4.
- Edges without portal coordinates (floor transitions): 34; of those, default (16,16) landing is invalid: 5.

Status legend: `verified_under_documented_axes`, `axis_mismatch`, `unverified_no_coordinates`, `unverified_no_coordinates_default_landing_invalid`, `coordinates_walkable_mechanic_unverified`, `invalid_coordinates`.

Every individual portal record (1646 rows) with source/destination, walkability, direction-bit, boundary, reverse and failure reasons is stored in `logs/phase0_audit.json` under `portals.portal_records`.

| From | To | Direction | Portals | src OK | dst OK | dirbit OK | boundary OK | reverse OK | Status |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| overworld1 | overworld2 | east | 16 | 16 | 16 | 16 | 0 | 15 | axis_mismatch |
| overworld1 | overworld6 | south | 5 | 5 | 5 | 5 | 0 | 3 | axis_mismatch |
| overworld1 | snowcave1 | dungeon_enter | 1 | 1 | 1 | 0 | 0 | 1 | coordinates_walkable_mechanic_unverified |
| overworld10 | overworld15 | south | 10 | 10 | 10 | 10 | 0 | 10 | axis_mismatch |
| overworld10 | overworld5 | north | 13 | 13 | 13 | 13 | 0 | 10 | axis_mismatch |
| overworld10 | overworld9 | west | 8 | 8 | 8 | 8 | 0 | 8 | axis_mismatch |
| overworld10 | powerplant1 | dungeon_enter | 1 | 1 | 1 | 0 | 0 | 1 | coordinates_walkable_mechanic_unverified |
| overworld11 | overworld12 | east | 24 | 24 | 24 | 24 | 0 | 24 | axis_mismatch |
| overworld11 | overworld16 | south | 16 | 16 | 16 | 16 | 0 | 15 | axis_mismatch |
| overworld12 | overworld11 | west | 25 | 25 | 25 | 25 | 0 | 24 | axis_mismatch |
| overworld12 | overworld13 | east | 25 | 25 | 25 | 25 | 0 | 25 | axis_mismatch |
| overworld12 | overworld17 | south | 19 | 19 | 19 | 19 | 0 | 17 | axis_mismatch |
| overworld12 | overworld7 | north | 28 | 28 | 28 | 28 | 0 | 28 | axis_mismatch |
| overworld13 | overworld12 | west | 25 | 25 | 25 | 25 | 0 | 25 | axis_mismatch |
| overworld13 | overworld14 | east | 26 | 26 | 26 | 26 | 0 | 26 | axis_mismatch |
| overworld13 | overworld18 | south | 25 | 25 | 25 | 25 | 0 | 24 | axis_mismatch |
| overworld13 | overworld8 | north | 29 | 29 | 29 | 29 | 0 | 27 | axis_mismatch |
| overworld14 | overworld13 | west | 26 | 26 | 26 | 26 | 0 | 26 | axis_mismatch |
| overworld14 | overworld15 | east | 14 | 14 | 14 | 14 | 0 | 13 | axis_mismatch |
| overworld14 | overworld19 | south | 21 | 21 | 21 | 21 | 0 | 20 | axis_mismatch |
| overworld14 | overworld9 | north | 24 | 24 | 24 | 24 | 0 | 23 | axis_mismatch |
| overworld15 | overworld10 | north | 12 | 12 | 12 | 12 | 0 | 10 | axis_mismatch |
| overworld15 | overworld14 | west | 15 | 15 | 15 | 15 | 0 | 13 | axis_mismatch |
| overworld15 | overworld20 | south | 20 | 20 | 20 | 20 | 0 | 19 | axis_mismatch |
| overworld15 | unownruins1 | dungeon_enter | 1 | 1 | 1 | 0 | 0 | 1 | coordinates_walkable_mechanic_unverified |
| overworld16 | overworld11 | north | 15 | 15 | 15 | 15 | 0 | 15 | axis_mismatch |
| overworld16 | overworld17 | east | 25 | 25 | 25 | 25 | 0 | 24 | axis_mismatch |
| overworld16 | overworld21 | south | 25 | 25 | 25 | 25 | 0 | 25 | axis_mismatch |
| overworld17 | overworld12 | north | 17 | 17 | 17 | 17 | 0 | 17 | axis_mismatch |
| overworld17 | overworld16 | west | 24 | 24 | 24 | 24 | 0 | 24 | axis_mismatch |
| overworld17 | overworld18 | east | 29 | 29 | 29 | 29 | 0 | 28 | axis_mismatch |
| overworld17 | overworld22 | south | 24 | 24 | 24 | 24 | 0 | 24 | axis_mismatch |
| overworld18 | overworld13 | north | 24 | 24 | 24 | 24 | 0 | 24 | axis_mismatch |
| overworld18 | overworld17 | west | 28 | 28 | 28 | 28 | 0 | 28 | axis_mismatch |
| overworld18 | overworld19 | east | 20 | 20 | 20 | 20 | 0 | 18 | axis_mismatch |
| overworld18 | overworld23 | south | 22 | 22 | 22 | 22 | 0 | 22 | axis_mismatch |
| overworld19 | overworld14 | north | 21 | 21 | 21 | 21 | 0 | 20 | axis_mismatch |
| overworld19 | overworld18 | west | 18 | 18 | 18 | 18 | 0 | 18 | axis_mismatch |
| overworld19 | overworld20 | east | 8 | 8 | 8 | 8 | 0 | 7 | axis_mismatch |
| overworld19 | overworld24 | south | 27 | 27 | 27 | 27 | 0 | 27 | axis_mismatch |
| overworld2 | overworld1 | west | 16 | 16 | 16 | 16 | 0 | 15 | axis_mismatch |
| overworld2 | overworld3 | east | 16 | 16 | 16 | 16 | 0 | 15 | axis_mismatch |
| overworld2 | overworld7 | south | 19 | 19 | 19 | 19 | 0 | 17 | axis_mismatch |
| overworld20 | overworld15 | north | 19 | 19 | 19 | 19 | 0 | 19 | axis_mismatch |
| overworld20 | overworld19 | west | 9 | 9 | 9 | 9 | 0 | 7 | axis_mismatch |
| overworld20 | overworld25 | south | 24 | 24 | 24 | 24 | 0 | 23 | axis_mismatch |
| overworld21 | overworld16 | north | 26 | 26 | 26 | 26 | 0 | 25 | axis_mismatch |
| overworld21 | overworld22 | east | 31 | 31 | 31 | 31 | 0 | 31 | axis_mismatch |
| overworld21 | pkmnmansion1 | dungeon_enter | 1 | 1 | 0 | 0 | 0 | 1 | invalid_coordinates |
| overworld21 | volcano1 | dungeon_enter | 1 | 1 | 0 | 0 | 0 | 1 | invalid_coordinates |
| overworld22 | overworld17 | north | 25 | 25 | 25 | 25 | 0 | 24 | axis_mismatch |
| overworld22 | overworld21 | west | 31 | 31 | 31 | 31 | 0 | 31 | axis_mismatch |
| overworld22 | overworld23 | east | 31 | 31 | 31 | 31 | 0 | 31 | axis_mismatch |
| overworld23 | overworld18 | north | 23 | 23 | 23 | 23 | 0 | 22 | axis_mismatch |
| overworld23 | overworld22 | west | 31 | 31 | 31 | 31 | 0 | 31 | axis_mismatch |
| overworld23 | overworld24 | east | 19 | 19 | 19 | 19 | 0 | 18 | axis_mismatch |
| overworld24 | overworld19 | north | 28 | 28 | 28 | 28 | 0 | 27 | axis_mismatch |
| overworld24 | overworld23 | west | 18 | 18 | 18 | 18 | 0 | 18 | axis_mismatch |
| overworld24 | overworld25 | east | 31 | 31 | 31 | 31 | 0 | 31 | axis_mismatch |
| overworld25 | overworld20 | north | 23 | 23 | 23 | 23 | 0 | 23 | axis_mismatch |
| overworld25 | overworld24 | west | 31 | 31 | 31 | 31 | 0 | 31 | axis_mismatch |
| overworld3 | overworld2 | west | 16 | 16 | 16 | 16 | 0 | 15 | axis_mismatch |
| overworld3 | overworld4 | east | 26 | 26 | 26 | 26 | 0 | 22 | axis_mismatch |
| overworld3 | overworld8 | south | 29 | 29 | 29 | 29 | 0 | 29 | axis_mismatch |
| overworld3 | pkmntower1 | dungeon_enter | 1 | 1 | 1 | 0 | 0 | 1 | coordinates_walkable_mechanic_unverified |
| overworld4 | overworld3 | west | 22 | 22 | 22 | 22 | 0 | 22 | axis_mismatch |
| overworld4 | overworld5 | east | 16 | 16 | 16 | 16 | 0 | 15 | axis_mismatch |
| overworld4 | overworld9 | south | 20 | 20 | 20 | 20 | 0 | 19 | axis_mismatch |
| overworld5 | overworld10 | south | 12 | 12 | 12 | 12 | 0 | 10 | axis_mismatch |
| overworld5 | overworld4 | west | 17 | 17 | 17 | 17 | 0 | 15 | axis_mismatch |
| overworld6 | overworld1 | north | 4 | 4 | 4 | 4 | 0 | 3 | axis_mismatch |
| overworld6 | overworld7 | east | 8 | 8 | 8 | 8 | 0 | 7 | axis_mismatch |
| overworld7 | overworld12 | south | 29 | 29 | 29 | 29 | 0 | 28 | axis_mismatch |
| overworld7 | overworld2 | north | 17 | 17 | 17 | 17 | 0 | 17 | axis_mismatch |
| overworld7 | overworld6 | west | 8 | 8 | 8 | 8 | 0 | 7 | axis_mismatch |
| overworld7 | overworld8 | east | 25 | 25 | 25 | 25 | 0 | 24 | axis_mismatch |
| overworld8 | overworld13 | south | 27 | 27 | 27 | 27 | 0 | 27 | axis_mismatch |
| overworld8 | overworld3 | north | 29 | 29 | 29 | 29 | 0 | 29 | axis_mismatch |
| overworld8 | overworld7 | west | 24 | 24 | 24 | 24 | 0 | 24 | axis_mismatch |
| overworld8 | overworld9 | east | 23 | 23 | 23 | 23 | 0 | 21 | axis_mismatch |
| overworld9 | overworld10 | east | 10 | 10 | 10 | 10 | 0 | 8 | axis_mismatch |
| overworld9 | overworld14 | south | 23 | 23 | 23 | 23 | 0 | 23 | axis_mismatch |
| overworld9 | overworld4 | north | 22 | 22 | 22 | 22 | 0 | 19 | axis_mismatch |
| overworld9 | overworld8 | west | 21 | 21 | 21 | 21 | 0 | 21 | axis_mismatch |
| overworld9 | rockcave1 | dungeon_enter | 1 | 1 | 1 | 0 | 0 | 1 | coordinates_walkable_mechanic_unverified |
| pkmnmansion1 | overworld21 | dungeon_exit | 1 | 0 | 1 | 0 | 0 | 1 | invalid_coordinates |
| pkmnmansion1 | pkmnmansion2 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| pkmnmansion2 | pkmnmansion1 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates_default_landing_invalid |
| pkmnmansion2 | pkmnmansion3 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| pkmnmansion3 | pkmnmansion2 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| pkmnmansion3 | pkmnmansion4 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| pkmnmansion4 | pkmnmansion3 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| pkmntower1 | overworld3 | dungeon_exit | 1 | 1 | 1 | 0 | 0 | 1 | coordinates_walkable_mechanic_unverified |
| pkmntower1 | pkmntower2 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| pkmntower2 | pkmntower1 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| pkmntower2 | pkmntower3 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| pkmntower3 | pkmntower2 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| powerplant1 | overworld10 | dungeon_exit | 1 | 1 | 1 | 0 | 0 | 1 | coordinates_walkable_mechanic_unverified |
| powerplant1 | powerplant2 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| powerplant2 | powerplant1 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| powerplant2 | powerplant3 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates_default_landing_invalid |
| powerplant3 | powerplant2 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| rockcave1 | overworld9 | dungeon_exit | 1 | 1 | 1 | 0 | 0 | 1 | coordinates_walkable_mechanic_unverified |
| rockcave1 | rockcave2 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| rockcave2 | rockcave1 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| rockcave2 | rockcave3 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| rockcave3 | rockcave2 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| rockcave3 | rockcave4 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| rockcave4 | rockcave3 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| snowcave1 | overworld1 | dungeon_exit | 1 | 1 | 1 | 0 | 0 | 1 | coordinates_walkable_mechanic_unverified |
| snowcave1 | snowcave2 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| snowcave2 | snowcave1 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| snowcave2 | snowcave3 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| snowcave3 | snowcave2 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| snowcave3 | snowcave4 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| snowcave4 | snowcave3 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| unownruins1 | overworld15 | dungeon_exit | 1 | 1 | 1 | 0 | 0 | 1 | coordinates_walkable_mechanic_unverified |
| unownruins1 | unownruins2 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| unownruins2 | unownruins1 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| volcano1 | overworld21 | dungeon_exit | 1 | 0 | 1 | 0 | 0 | 1 | invalid_coordinates |
| volcano1 | volcano2 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| volcano2 | volcano1 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates_default_landing_invalid |
| volcano2 | volcano3 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates_default_landing_invalid |
| volcano3 | volcano2 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| volcano3 | volcano4 | climb_up/advance | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates |
| volcano4 | volcano3 | climb_down/return | 0 | 0 | 0 | 0 | 0 | 0 | unverified_no_coordinates_default_landing_invalid |

Invalid default `(16,16)` landings on portal-less floor transitions (the environment would silently substitute the first walkable tile):

- `pkmnmansion2 -> pkmnmansion1` (climb_down/return)
- `powerplant2 -> powerplant3` (climb_up/advance)
- `volcano2 -> volcano1` (climb_down/return)
- `volcano2 -> volcano3` (climb_up/advance)
- `volcano4 -> volcano3` (climb_down/return)

## 5. Overworld 21 entrance collision

`dungeon_enter` targets: ['pkmnmansion1', 'volcano1']. Action 9 selects: `pkmnmansion1`. Collision present: True.

> Global49MapEnv.step() selects the first outgoing edge whose direction is in ('climb_up/advance', 'dungeon_enter'). Both Overworld 21 entrances share action 9, so the second entrance (volcano1) cannot be deliberately chosen.

Configured dungeon entrances and landing validity:

| Source | Dungeon | Source coord | Landing coord | Landing walkable |
|---|---|---|---|---|
| overworld1 | snowcave1 | [14, 2] | [16, 16] | True |
| overworld3 | pkmntower1 | [16, 16] | [16, 16] | True |
| overworld9 | rockcave1 | [16, 16] | [16, 16] | True |
| overworld10 | powerplant1 | [16, 16] | [16, 16] | True |
| overworld15 | unownruins1 | [16, 16] | [16, 16] | True |
| overworld21 | pkmnmansion1 | [10, 10] | [16, 16] | False |
| overworld21 | volcano1 | [22, 22] | [16, 16] | False |

## 6. Environment observation / action definitions

| Environment | Actions | Observation dim | Notes |
|---|---:|---:|---|
| MapEnv | 8 | 102 | Docstring says 53 features and mentions a water channel, but the code emits 102 features and only walkability+visited channels. No directional affordance, water, terrain or portal information in the observation. |
| PathPlannerEnv | 16 | 67 | 16 hardcoded waypoints; not a 49-map solution. |
| Global49MapEnv | 11 | 204 | Local actions 0-4 each run a full BFS route to a sector waypoint in one macro-step. Actions 5-10 are map-transition macros. Not tile-by-tile movement. |

`MapEnv` docstring claims 53 features but the code emits 102. This is a documentation/code mismatch.

## 7. Training settings, success definition and checkpoint rule

- **entry_point**: scripts/train_global_49maps.py :: train_global_agent()
- **episodes_configured**: 8000
- **max_macro_steps_in_train_entry**: 20
- **max_macro_steps_class_default**: 25
- **gamma**: 0.98
- **learning_rate**: 0.0007
- **buffer_size**: 40000
- **batch_size**: 64
- **target_sync_every_episodes**: 25
- **epsilon_schedule**: linear 1.0 -> 0.05 over 5000 episodes, then constant 0.05
- **start_map_sampling**: overworld1 every 4th episode, otherwise uniform random over 49 maps
- **target_map_sampling**: uniform random map different from the start map
- **success_condition**: current_map == target_map (no target coordinate, region or exploration requirement)
- **termination**: done when target map entered or macro_steps >= max_macro_steps
- **checkpoint_selection**: saves global_49map_dqn_best.pt whenever episode reward > best_reward OR maps_visited > best_maps_visited; updates only the improved best value, then loads that checkpoint to export global_49map_weights.json
- **timeout_label**: No explicit timeout column. A timeout is inferable only as target_reached == 0 and steps == max_macro_steps.

### Reward components (exact source values)

| Component | Value | Condition | Source line |
|---|---|---|---:|
| step_cost | -0.1 | every macro-step | 185 |
| novelty | +0.25 per tile | local sector path tile not in local_visited_tiles | 198 |
| water | +0.8 per water tile | every water tile on a local sector path, including revisits | 202 |
| blocked_local_path | -1.0 | find_path returns None or an empty path | 208 |
| recent_map_penalty | -12.0 | destination map in recent_map_history (last 5) | 250 |
| fresh_map_bonus | +8.0 | destination map not in recent_map_history | 252 |
| map_discovery | +20.0 | destination map never visited this episode | 256 |
| distance_progress | +15.0 | map-graph shortest-path distance to target decreases | 262 |
| distance_regression | -5.0 | map-graph distance does not decrease | 264 |
| target_arrival | +80.0 | current_map becomes target_map | 278 |
| tall_grass | NOT PRESENT | no tall-grass reward exists in the 49-map code; WalkTile has no grass flag | - |
| encounter_counter | no reward itself | incremented once per water tile on the local route; not a real encounter event | 203 |

Tall grass is **not** rewarded in the 49-map code. `WalkTile` exposes only `walkable` and `is_water`; the only terrain reward check is `tile.is_water` in `Global49MapEnv.step()`.

## 8. Recorder data quality

- Session: `data/raw/deluge_session_20261124-113227.zip`
- Parsed events: 8733; types: {'P': 92, 'a': 3941, '+': 1219, '-': 2795, 'c': 228, 'm': 53, 'n': 243, 'T': 162}
- Map-change (`m`) events: 53; with coordinates: 0
- Walkgrid (`g`) events: 0
- Map graph entries: 49; recorded exits: 50; exits with fabricated (0,0): 50

> Array-form 'm' events carry map/name data but no x/y. RecorderParser sets x=y=0 and records transitions with (0,0). This session is NOT a valid tile-level human trajectory dataset and must not be treated as one.

## 9. Model and log provenance

- Weights metadata: `{'episodes': 8000, 'maps_count': 49, 'best_reward': 583.8, 'best_maps_visited': 15, 'training_time_seconds': 2752.71, 'timestamp': '2026-11-24 17:00:21'}`
- Training log rows: 8000
- First episode: `{'episode': '1', 'epsilon': '0.9998', 'reward': '54.50', 'maps_visited': '4', 'target_reached': '0', 'encounters': '0', 'loss': '0.0000', 'steps': '20'}`
- Last episode: `{'episode': '8000', 'epsilon': '0.0500', 'reward': '307.95', 'maps_visited': '4', 'target_reached': '0', 'encounters': '214', 'loss': '22.3158', 'steps': '20'}`
- Log max reward: 583.8; log max maps visited: 15
- Checkpoints: `{'models/global_49map_dqn_best.pt': {'first_weight_shape': [256, 204], 'tensor_count': 12}, 'models/global_49map_dqn_final.pt': {'first_weight_shape': [256, 204], 'tensor_count': 12}}`

> The current workspace metadata claims 8000 episodes and the log contains 8000 rows. This differs from the earlier snapshot described in the plan (episodes: 5). The files cannot be cryptographically proven to be the exact run shown in any external screenshot; do not claim they are the 6500-episode screenshot run. All existing artifacts were left untouched.

## 10. Controlled reward-component experiments

Instrumented decomposition fidelity: reconciled=True, steps=120, max_abs_difference=3.552713678800501e-15, mismatches=0.

Experiments use fixed seeds (`random.seed(20261124)`, `numpy.random.seed(20261124)` and a local `Random(20261124)`); two consecutive runs produced byte-identical experiment JSON.

Each row is a 20-macro-step episode with a fixed start map/target map. `reward` is the sum of the listed components.

| Scenario | Hop | Policy | Success | Timeout | Steps | Reward | step | novelty | water | blocked | recent | fresh | discovery | dist+ | dist- | target | enc |
|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| near | 1 | route | True | False | 1 | 122.9 | -0.10 | 0.00 | 0.00 | 0.00 | 0.00 | 8.00 | 20.00 | 15.00 | 0.00 | 80.00 | 0 |
| near | 1 | local | False | True | 20 | 55.45 | -2.00 | 22.25 | 35.20 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 44 |
| near | 1 | greedy | True | False | 1 | 122.9 | -0.10 | 0.00 | 0.00 | 0.00 | 0.00 | 8.00 | 20.00 | 15.00 | 0.00 | 80.00 | 0 |
| medium | 5 | route | True | False | 5 | 294.5 | -0.50 | 0.00 | 0.00 | 0.00 | 0.00 | 40.00 | 100.00 | 75.00 | 0.00 | 80.00 | 0 |
| medium | 5 | local | False | True | 20 | 53.2 | -2.00 | 20.00 | 35.20 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 44 |
| medium | 5 | greedy | False | True | 20 | 364.55 | -2.00 | 5.75 | 208.80 | 0.00 | 0.00 | 32.00 | 80.00 | 45.00 | -5.00 | 0.00 | 261 |
| far | 14 | route | True | False | 14 | 680.6 | -1.40 | 0.00 | 0.00 | 0.00 | 0.00 | 112.00 | 280.00 | 210.00 | 0.00 | 80.00 | 0 |
| far | 14 | local | False | True | 20 | 20.5 | -2.00 | 22.50 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0 |
| far | 14 | greedy | False | True | 20 | 369.4 | -2.00 | 11.00 | 102.40 | 0.00 | 0.00 | 48.00 | 120.00 | 90.00 | 0.00 | 0.00 | 128 |
| overworld21_mansion | 1 | route | True | False | 1 | 122.9 | -0.10 | 0.00 | 0.00 | 0.00 | 0.00 | 8.00 | 20.00 | 15.00 | 0.00 | 80.00 | 0 |
| overworld21_mansion | 1 | local | False | True | 20 | 183.05 | -2.00 | 16.25 | 168.80 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 211 |
| overworld21_mansion | 1 | greedy | False | True | 20 | 201.95 | -2.00 | 4.75 | 199.20 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 249 |
| overworld21_volcano | 1 | route | False | True | 20 | -102.0 | -2.00 | 0.00 | 0.00 | 0.00 | -228.00 | 8.00 | 20.00 | 150.00 | -50.00 | 0.00 | 0 |
| overworld21_volcano | 1 | local | False | True | 20 | 186.55 | -2.00 | 15.75 | 172.80 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 216 |
| overworld21_volcano | 1 | greedy | False | True | 20 | 136.95 | -2.00 | 9.75 | 83.20 | 0.00 | 0.00 | 16.00 | 40.00 | 0.00 | -10.00 | 0.00 | 104 |
| water_farming (rockcave4) | 14 | water | False | True | 20 | 277.75 | -2.00 | 7.75 | 272.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 340 |

Water-farming route: map `rockcave4`, sector actions [0, 4], 34 water tiles per back-and-forth cycle. Repeated water traversal pays +0.8 per tile on every pass, independent of visitation.

### Success by map-hop distance bucket (controlled baselines)

| Bucket | Hop range | Policy | Samples | Successes | Success % | Timeouts | Mean reward |
|---|---|---|---:|---:|---:|---:|---:|
| near | [1, 3] | random | 40 | 11 | 27.5 | 29 | 189.544 |
| near | [1, 3] | route | 40 | 38 | 95.0 | 2 | 168.78 |
| near | [1, 3] | greedy | 40 | 9 | 22.5 | 31 | 297.015 |
| medium | [4, 7] | random | 40 | 0 | 0.0 | 40 | 153.805 |
| medium | [4, 7] | route | 40 | 39 | 97.5 | 1 | 295.668 |
| medium | [4, 7] | greedy | 40 | 1 | 2.5 | 39 | 356.96 |
| far | [8, 14] | random | 40 | 0 | 0.0 | 40 | 153.403 |
| far | [8, 14] | route | 40 | 32 | 80.0 | 8 | 446.495 |
| far | [8, 14] | greedy | 40 | 0 | 0.0 | 40 | 372.988 |

> NOT AVAILABLE: the CSV records no start map or target map, so the historical run cannot be grouped by target-distance bucket.

## 11. Historical training-log trend

| Episodes | Success % | Mean reward | Mean encounters | Mean maps visited |
|---|---:|---:|---:|---:|
| 1-500 | 9.8 | 189.75 | 32.0 | 5.29 |
| 501-1000 | 11.2 | 217.67 | 29.3 | 6.04 |
| 1001-1500 | 10.8 | 209.99 | 36.8 | 5.67 |
| 1501-2000 | 10.6 | 215.92 | 44.8 | 5.73 |
| 2001-2500 | 12.4 | 235.79 | 58.7 | 5.8 |
| 2501-3000 | 9.8 | 257.57 | 66.6 | 6.22 |
| 3001-3500 | 9.6 | 265.97 | 85.5 | 6.02 |
| 3501-4000 | 10.0 | 300.7 | 116.9 | 6.31 |
| 4001-4500 | 11.8 | 326.4 | 172.3 | 5.69 |
| 4501-5000 | 6.6 | 339.0 | 198.6 | 5.57 |
| 5001-5500 | 5.2 | 343.13 | 220.0 | 5.27 |
| 5501-6000 | 4.8 | 336.72 | 220.0 | 5.08 |
| 6001-6500 | 5.2 | 326.32 | 227.3 | 4.54 |
| 6501-7000 | 5.8 | 316.96 | 226.8 | 4.31 |
| 7001-7500 | 3.8 | 304.95 | 226.4 | 3.99 |
| 7501-8000 | 2.0 | 311.11 | 239.0 | 3.94 |

Success episodes: 647; failed episodes: 7353. All failures occur at the maximum macro-step count (all_failures_at_max_steps=True), so they are timeouts. Successful episodes terminate in [1, 20] macro-steps.

## 12. Map-hop distance vs physical route cost and legacy feasibility

- Ordered reachable map pairs: 2352.
- Map-hop distance: mean 5.818, median 5.0, max 14.
- Hop distribution: {'1': 126, '2': 194, '3': 256, '4': 298, '5': 308, '6': 282, '7': 238, '8': 192, '9': 150, '10': 114, '11': 94, '12': 60, '13': 28, '14': 12}.
- Pairs needing more than 20 macro-steps: 0 (0.0%).
- Physical coordinate/portal route cost: NOT AVAILABLE: no portal-aware coordinate planner exists in Phase 0.

> Under legacy macro semantics one map transition costs one macro-step and the transition does not require reaching a portal, so every pair (max 14 hops) fits in 20 macro-steps. This says nothing about physical tile-level feasibility.

## 13. Existing test suite baseline

- Command: `python -m pytest -q`
- Return code: 0
- Summary: `41 passed, 1 warning in 6.10s`

```
.........................................                                [100%]
============================== warnings summary ===============================
..\..\..\..\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\site-packages\anyio\pytest_plugin.py:14
  C:\Users\dugge\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\site-packages\anyio\pytest_plugin.py:14: PytestRemovedIn10Warning: _pytest.python.CallSpec2 has been renamed to CallSpec.
  The CallSpec2 alias will be removed in pytest 10.
  Update imports to use CallSpec instead.
  See https://docs.pytest.org/en/stable/deprecations.html#callspec2-renamed
    from _pytest.python import CallSpec2

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
41 passed, 1 warning in 6.10s
```

## 14. Phase 0 acceptance-criteria evaluation

| Criterion | Result | Evidence |
|---|---|---|
| Audit runs from repo root with one documented command | PASS | `python scripts/audit_navigation_baseline.py` |
| All 49 grids checked | PASS | 49 maps decoded |
| Concrete portal/transition audit, not just node count | PASS | Per-edge table in section 4 |
| Distinguishes verified / invalid / unverified transitions | PASS | verified=0, axis_mismatch=78, unverified_no_coordinates=34, invalid_coordinates=4 |
| Records pytest baseline and model/log provenance | PASS | Sections 9 and 13 |
| No existing model/data/log overwritten | PASS | Only two new artifacts written |
| Reward components reported separately and match source | PASS | Fidelity reconciled=True |
| Controlled tests establish whether local/water reward competes with target | PASS | Section 10 |
| Graph-hop, physical route cost, legacy 20-step feasibility separated | PASS | Section 12 |
| Success grouped by distance bucket; timeout distinguishable | PASS (controlled) / NOT AVAILABLE (historical) | Section 10 buckets; section 11 timeout evidence |

## 15. Known limitations

- Physical route cost and coordinate-level portal reachability are not implemented; only graph hops exist.
- The documented x=row / y=column convention is not yet confirmed against captured game source. Seam boundary checks use that documented convention; the true axis must be confirmed in Phase 1.
- Dungeon floor/stair coordinates are absent (empty portal arrays). Default (16,16) landings are unverified; 5 floor-transition destinations are not walkable and trigger the first-walkable fallback.
- Historical success cannot be bucketed by distance because the training CSV stores no start/target maps.
- The included checkpoint/log provenance is plausible but not cryptographically tied to any screenshot.
- No RL training, navigation rewrite or reward change was performed in Phase 0.

