# Livery picker experiment log (dev-blackhawk)

Run on `[DEV] Practice — Blackhawk Farmsℹ8189` (HTTP `8089`, details `8189`).

## Server-side verification (2026-09-03)

| Check | Result |
| --- | --- |
| Dev stack isolated from prod | Prod `8081` still up with 2 clients; dev on `8089` |
| Prod plugin binds slots 0–2 only | `ac-host-plugin-1` logs slots 0,1,2 |
| Dev plugin binds slot 8 only | `ac-host-dev-plugin-1` logs slot 8 |
| `/api/details` session + pickup | `session: 0`, `pickup: true` |
| GitHub 124 in content payload | `content.cars.abarth_124_2016` present |

## Experiments (CM join required)

| Id | `RENDER_SKIN_MODE` | entry_list `SKIN=` | Expected | User result |
| --- | --- | --- | --- | --- |
| A | `pinned` | `02_Bianco` on all 124 pits | Always Bianco | _pending CM join_ |
| B | `empty` | blank | Click Nero in row → `race.ini` + spawn Nero | _pending CM join_ |
| C | `empty` | blank | Cars page livery → Join | _pending CM join_ |
| D | `cycle` | Rosso, Nero, Bianco, … | First joiner = pit 0 color | _pending CM join_ |

Run: `python3 scripts/skin_experiment.py B` on the box (re-renders dev lobby only).

## Promotion gate (production)

Do **not** change prod until experiment **B** passes on dev:

```bash
# After B passes and Blackhawk is empty (green on player page):
echo 'RENDER_SKIN_MODE=empty' | sudo tee -a /var/lib/ac-host/.env
python3 /var/lib/ac-host/src/scripts/acctl.py --env prod up-static --only blackhawk
```

Until then, production stays `pinned` (default `render_cfg` behavior).
