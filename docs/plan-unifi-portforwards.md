# Plan: UniFi slot-scoped port forwards (locked-down WAN)

## Why

Wide open ranges (`9600–9615`, `8081–8096`, `8181–8196`) invite scanners/bots. That burns Dream Router NAT state and may have contributed to a crash. Only ports for **running** lobbies should be forwarded.

## Goal

`acctl.py` opens three UniFi port-forward rules per lobby slot on start, and deletes them on stop. No broad “always open” race range on the WAN.

| Slot N | Rules | Proto |
| --- | --- | --- |
| Game | `9600+N` | TCP+UDP |
| HTTP | `8081+N` | TCP |
| Details | `8181+N` | TCP |

Names: `ac-{env}-s{N}-game|http|details` (idempotent).

## Already sketched in tree

- [`scripts/unifi_pf.py`](scripts/unifi_pf.py) — login + ensure/delete
- [`scripts/acctl.py`](scripts/acctl.py) — hooks on `up-static` / `down-static` / `start-race` / `stop-race`
- [`compose/env.example`](compose/env.example) — `UNIFI_PF`, `UNIFI_*` vars
- Off by default until `UNIFI_PF=1` + credentials

## Remaining work

1. Put UniFi local admin (or API) creds in `/var/lib/ac-host/.env` only (never commit).
2. Smoke-test from the box: `UNIFI_PF=1 … python3 scripts/unifi_pf.py list`
3. In UniFi UI: delete the wide port-forward ranges.
4. Run `acctl.py --env prod up-static` once so practice slots 0–2 get named rules.
5. Dev: leave `UNIFI_PF` off on `/var/lib/ac-host-dev/.env` unless you need WAN join to slot 8.
6. Optional later: schedule/`down-static` when nobody is playing so even practice ports close; UniFi IPS / country filters for residual scan noise on always-on practice.

## Out of scope (for now)

- Official UniFi Integration API (port forwards still classic cookie API)
- Geo-IP allowlists for friends (possible later)
- Auto-heal if UniFi rejects a rule mid-race

## Git note

Port-forward helpers ship in the public `ac-host` repo. Keep `UNIFI_*` credentials in `.env` only; leave `UNIFI_PF=0` until you are ready to drive the Dream Router from the box.
