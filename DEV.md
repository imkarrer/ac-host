# Dev / test environment

Isolated stack on the same NixOS box (slot **8** → `9608` / `8089` / `8189`). See `compose/env.dev.example`.

```bash
cp compose/env.dev.example /var/lib/ac-host-dev/.env
# set AC_PUBLIC_IP, AC_GITHUB_*, GITHUB_STATUS_TOKEN; keep GITHUB_STATUS_PATH=dev/leaderboard.json
python3 scripts/acctl.py --env dev up-static
```

Dev Pages path: `$AC_PAGES_URL` (usually `…/ac-practice/dev/`). Status file: `dev/leaderboard.json`.

Leave `UNIFI_PF` off for LAN-only DEV.
