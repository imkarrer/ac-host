# Livery picker experiment log (dev-blackhawk)

Run on `[DEV] Practice — Blackhawk Farmsℹ8189` (HTTP `8089`, details `8189`).

## Server-side verification (2026-09-03)

| Check | Result |
| --- | --- |
| Dev stack isolated from prod | Prod `8081` stays up; dev on `8089` |
| Prod plugin binds slots 0–2 only | Confirmed |
| Dev plugin binds slot 8 only | Confirmed |
| `/api/details` session + pickup | `session: 0`, `pickup: true` |

## Experiments (CM join)

| Id | `RENDER_SKIN_MODE` | Result |
| --- | --- | --- |
| A | `pinned` | Not required after B |
| **B** | `empty` | **FAIL spawn.** Clicked Nero → `race.ini` has `SKIN=01_nero` (CM OK). Spawned **red** (`00_Rosso`, first folder). Pickup ignores client skin when `SKIN=` is blank. |
| C | `empty` | Skipped — same handshake as B; race.ini already proved CM sends the pick. |
| D | `cycle` | Optional variety only; not a picker. |

### Experiment B detail (fugazy, 192.168.1.146)

- `entry_list` CAR_0: `MODEL=abarth_124_2016`, `SKIN=` empty
- `Documents/.../race.ini`: `SKIN=01_nero`
- Server: `DRIVER ACCEPTED FOR CAR 0` → red in-game

**Verdict:** Pickup cannot honor the Online thumbnail strip. Empty `SKIN=` collapses to the car’s first skin folder (Rosso), not the client selection.

## Production decision

Do **not** set `RENDER_SKIN_MODE=empty` on prod.

Keep **`pinned`** (`PREFERRED_SKIN`, 124 → `02_Bianco`) so empty pits do not default to Rosso. The Online skin row remains visible (Booking advertise) but is **cosmetic** for spawn color.

Optional later: `cycle` for visual variety (first free pit’s color), still not a true picker. Real Kunos booking mode is out of scope for 24h practice.
