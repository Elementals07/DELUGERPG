# DelugeRPG Transition Registry Audit (Phase 1)

Generated: 2026-11-24T13:18:30.659301+00:00

## 1. Phase 0 artifact integrity

| Artifact | Bytes | Modified (UTC) | SHA-256 |
|---|---:|---|---|
| `scripts\audit_navigation_baseline.py` | 60303 | 2026-11-24T12:27:55.550816+00:00 | `d3712346d33e2a9a3e3c6d9379d23144e92e26b06dbcd65b6025b45a36ab9c0b` |
| `docs\ROAMING_BASELINE_AUDIT.md` | 31823 | 2026-11-24T12:28:46.309161+00:00 | `1106173cce2204fb5df690eea4936d6f1830ae7de2dca7a1940820111f7a9ed0` |
| `logs\phase0_audit.json` | 1321039 | 2026-11-24T12:28:46.308159+00:00 | `fe04f09913e5941acaca576b4ed24f2767c650a2d86eca3f1dbd73d61a326a7f` |

The Phase 0 artifacts are present and unchanged. The legacy data is preserved in `data\processed\transition_registry_v1_legacy_baseline.json`.

## 2. Proven coordinate convention

Captured source: `DELUGERPG_Consolidated_Reference/source/javascript/game/assets.delugerpg.com/js10402/map.js`.

- `gridTile(b,c)` returns bytes at `(b*33+c)*2`, so the first argument is the row.
- `PEEP_DIRS` maps north to `(-1,0)`, south to `(1,0)`, west to `(0,-1)`, east to `(0,1)`.
- `playerRow(top) = round((top + 17)/16) + 1`; sprite `left` converts with `round((left + 7)/16) + 1` for the column.
- The recorded session contains 78 other-player sprites with both `data-tx`/`data-ty` and pixel `top`/`left`; all 78 agree with row,column.

| Sprite top,left | Computed row,column | Recorded data-tx,data-ty |
|---|---|---|
| (191.0, 105.0) | (14, 8) | (14, 8) |
| (255.0, 105.0) | (18, 8) | (18, 8) |
| (-1.0, 297.0) | (2, 20) | (2, 20) |
| (463.0, 217.0) | (31, 15) | (31, 15) |
| (319.0, 361.0) | (22, 24) | (22, 24) |

Cross-checks: 78 passed, 0 failed. Reproducible mapping: `grid_byte_index(row, col) == (row * 33 + col) * 2`.

## 3. WorldGraph vs GlobalWorldGraph edge-by-edge

| View | Edges | SCC count | SCC sizes |
|---|---:|---:|---|
| Legacy base `WorldGraph` | 112 | 8 | [25, 4, 4, 4, 4, 3, 3, 2] |
| Legacy `GlobalWorldGraph` | 126 | 1 | [49] |
| Canonical base (seams + floors) | 114 | 8 | [25, 4, 4, 4, 4, 3, 3, 2] |
| Canonical global (all records) | 128 | 1 | [49] |
| Canonical usable (non-invalid, known landing) | 90 | 1 | [30] |
| Canonical VERIFIED only | 0 | 0 | [] |

Legacy base = 78 seams + 34 floor chains = 112. Legacy global adds 7 entrance pairs x 2 directions = 14, giving 126. The corrected registry has 80 seams + 34 floor chains = 114 and 128 including the same 14 entrance records. The two additional seams are the missing overworld6<->overworld11 north/south adjacency. The legacy 8 SCCs are the 25-node overworld plus the seven dungeon chains; the 1-SCC global view depends on the entrance edges and is topological only.

The 14-edge difference is exactly the seven entrance pairs in both directions:

- `entrance:overworld1->snowcave1`: overworld1 -> snowcave1 (entrance, UNVERIFIED)
- `exit:snowcave1->overworld1`: snowcave1 -> overworld1 (exit, UNVERIFIED)
- `entrance:overworld3->pkmntower1`: overworld3 -> pkmntower1 (entrance, UNVERIFIED)
- `exit:pkmntower1->overworld3`: pkmntower1 -> overworld3 (exit, UNVERIFIED)
- `entrance:overworld9->rockcave1`: overworld9 -> rockcave1 (entrance, UNVERIFIED)
- `exit:rockcave1->overworld9`: rockcave1 -> overworld9 (exit, UNVERIFIED)
- `entrance:overworld10->powerplant1`: overworld10 -> powerplant1 (entrance, UNVERIFIED)
- `exit:powerplant1->overworld10`: powerplant1 -> overworld10 (exit, UNVERIFIED)
- `entrance:overworld15->unownruins1`: overworld15 -> unownruins1 (entrance, UNVERIFIED)
- `exit:unownruins1->overworld15`: unownruins1 -> overworld15 (exit, UNVERIFIED)
- `entrance:overworld21->pkmnmansion1`: overworld21 -> pkmnmansion1 (entrance, INVALID)
- `exit:pkmnmansion1->overworld21`: pkmnmansion1 -> overworld21 (exit, INVALID)
- `entrance:overworld21->volcano1`: overworld21 -> volcano1 (entrance, INVALID)
- `exit:volcano1->overworld21`: volcano1 -> overworld21 (exit, INVALID)

The legacy base graph was missing two seam edges: `('overworld6', 'overworld11', 'north')` and `('overworld11', 'overworld6', 'south')`. The corrected scan finds 10 portal records in each direction.

## 4. Legacy 1,646 portal records

| Metric | Count |
|---|---:|
| Legacy portal records | 1646 |
| Legacy seam records | 1632 |
| Legacy entrance records | 14 |
| disposition: `rejected_no_legal_canonical_trigger` | 335 |
| disposition: `superseded_by_canonical` | 1311 |
| legacy status: `INVALID` | 1636 |
| legacy status: `UNVERIFIED` | 10 |
| legacy records whose old target map differs from the canonical target | 1297 |
| canonical records carrying legacy references | 1311 |

Every legacy seam record is invalid as labeled. Many are invalid because the source coordinate is not on the boundary implied by the declared direction; the rest are on a boundary but the destination is not the declared mirror. Of the 1632 legacy seam records, 1297 coincide with a legal canonical seam under a boundary-implied direction and 1297 of those used the wrong target map; the remaining 335 have no legal canonical trigger (direction bit missing or the correct destination is not walkable). All 14 legacy entrance records map to canonical entrance/exit records (10 UNVERIFIED, 4 INVALID). All 1,646 records are accounted for; the full list is in the legacy baseline file.

## 5. Canonical transition status

| Class | Total | VERIFIED | INVALID | UNVERIFIED | Geometry verified | Coordinates missing | Reverse OK | Legacy default INVALID |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `overworld_seam` | 2010 | 0 | 0 | 2010 | 2010 | 0 | 2010 | 0 |
| `overworld_to_dungeon` | 14 | 0 | 4 | 10 | 10 | 0 | 14 | 0 |
| `dungeon_floor` | 34 | 0 | 0 | 34 | 0 | 34 | 34 | 5 |

No seam landing was observed in the recorded session; therefore every seam is UNVERIFIED even though its source trigger, boundary geometry, walkability and reverse record are verified. The five invalid legacy (16,16) floor defaults are recorded as INVALID default landings while the floor transition itself remains UNVERIFIED because the stair coordinates are unknown. No first-walkable fallback is used.

### Overworld seams

- Canonical seam records: 2010 across 80 directed edges (20 north, 20 south, 20 west, 20 east).
- Geometry-verified records: 2010; reverse records: 2010.
- The corrected scan finds 2,010 seam records versus 1,632 legacy records; the legacy builder used the wrong boundary and the wrong direction bit.

### Overworld-to-dungeon entrances

- Records: 14 (7 pairs, entrance and exit).
- INVALID: 4. The Pokemon Mansion and Volcano entrance/exit pairs use the non-walkable (16,16) landing on pkmnmansion1 and volcano1.
- UNVERIFIED: 10. Their source/landing coordinates are walkable legacy seeds, but no entrance trigger or landing was observed.
- Overworld 21 has two distinct portal IDs: `entrance:overworld21->pkmnmansion1` and `entrance:overworld21->volcano1`, with different source coordinates (10,10) and (22,22).

### Dungeon-floor transitions

- Records: 34 (17 floor pairs, ascend and descend).
- UNVERIFIED: 34 because no stair/ladder coordinates were observed.
- Legacy default (16,16) invalid landings: 5 (pkmnmansion2->pkmnmansion1, powerplant2->powerplant3, volcano2->volcano1, volcano2->volcano3, volcano4->volcano3).
- Observed map-entry spawns from the session are recorded as evidence only; they are not used as stair coordinates.

## 6. Recorded-session evidence and its limits

- Map-change events: 53; followed by UI navigation: 53.
- Every recorded map change followed a minimap or 'Return to Map' click. No physical seam or dungeon-portal landing was observed. The spawn coordinates are map-entry spawns after UI navigation, not proof of a portal landing coordinate.
- Observed map-entry spawns (row,column):

  - `overworld1`: [[22, 15], [24, 16]]
  - `overworld10`: [[18, 14]]
  - `overworld11`: [[17, 13]]
  - `overworld12`: [[18, 8]]
  - `overworld13`: [[22, 25]]
  - `overworld14`: [[17, 13]]
  - `overworld15`: [[16, 18]]
  - `overworld16`: [[21, 15]]
  - `overworld17`: [[20, 14]]
  - `overworld18`: [[23, 14]]
  - `overworld19`: [[17, 13]]
  - `overworld2`: [[19, 9]]
  - `overworld20`: [[16, 14]]
  - `overworld21`: [[14, 14]]
  - `overworld22`: [[14, 17]]
  - `overworld23`: [[13, 18]]
  - `overworld24`: [[12, 14]]
  - `overworld25`: [[20, 17]]
  - `overworld3`: [[15, 15]]
  - `overworld4`: [[13, 13]]
  - `overworld5`: [[16, 10]]
  - `overworld6`: [[4, 10], [5, 10], [8, 18], [11, 12]]
  - `overworld7`: [[14, 15]]
  - `overworld8`: [[20, 11]]
  - `overworld9`: [[18, 14]]
  - `pkmnmansion1`: [[20, 21]]
  - `pkmnmansion2`: [[16, 16]]
  - `pkmnmansion3`: [[12, 19]]
  - `pkmnmansion4`: [[20, 14]]
  - `pkmntower1`: [[15, 17]]
  - `pkmntower2`: [[15, 16]]
  - `pkmntower3`: [[26, 17]]
  - `powerplant1`: [[15, 21]]
  - `powerplant2`: [[18, 14]]
  - `powerplant3`: [[21, 12]]
  - `rockcave1`: [[15, 13]]
  - `rockcave2`: [[19, 14]]
  - `rockcave3`: [[7, 23]]
  - `rockcave4`: [[7, 22]]
  - `snowcave1`: [[11, 11]]
  - `snowcave2`: [[19, 20]]
  - `snowcave3`: [[7, 12]]
  - `snowcave4`: [[13, 17]]
  - `unownruins1`: [[17, 17]]
  - `unownruins2`: [[15, 15]]
  - `volcano1`: [[20, 15]]
  - `volcano2`: [[12, 12]]
  - `volcano3`: [[21, 18]]
  - `volcano4`: [[20, 17]]

## 7. Removed silent relocation

The legacy `(16,16)` and first-walkable fallback in `Global49MapEnv.step()` is removed. Transition selection now goes through the registry. A transition with no destination coordinate raises `UnverifiedTransitionError`; an INVALID transition raises `InvalidTransitionError`; ambiguous portals raise `AmbiguousTransitionError`. Unverified but walkable candidate landings are used only when explicitly allowed, and the result is flagged in `info` with `verification_status` and `portal_id`.

## 8. Tests

Focused tests: `python -m pytest -q tests/test_transition_registry.py`

Latest focused run: 15 passed, 1 warning.

Full suite: `python -m pytest -q`

Latest full run: 56 passed, 1 warning.

## 9. Changed files and remaining blockers

- Added `delugerpg/models/transition_registry.py`.
- Added `scripts/build_transition_registry.py`.
- Added `data/processed/transition_registry_v1.json`.
- Added `data/processed/transition_registry_v1_legacy_baseline.json`.
- Added `docs/TRANSITION_REGISTRY_AUDIT.md`.
- Updated `scripts/train_global_49maps.py` to consume the registry and remove the first-walkable fallback.
- The legacy `DUNGEON_ENTRANCES` constant remains only as the read-only Phase 0 audit seed; `GlobalWorldGraph` no longer reads it.
- Added `tests/test_transition_registry.py`.

Remaining blockers:

- No physical seam or dungeon-portal landing was observed; seam and entrance landings remain UNVERIFIED.
- All 34 dungeon-floor stair/ladder coordinates remain unknown.
- The Pokemon Mansion and Volcano entrance/exit pairs are INVALID at the legacy (16,16) landing and must be re-derived before physical navigation can use them.
- The registry does not claim that all 49 maps are physically connected. Only the map-level graph is connected, and that view is topological.
