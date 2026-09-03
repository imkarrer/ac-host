# Plan: Public `ac-host` repo + Flox where it fits

## Intent

**`ac-host` is the public GitHub repo** for this NixOS + Docker practice-host stack. Use **Flox** as the low-friction entry for contributors who should not need a full NixOS box to run scripts and tests.

Keep the **NixOS module + flake** as the production host story. Flox does not replace that.

Related: Pages stay in a separate repo (`AC_GITHUB_REPO`, often `ac-practice`). UniFi lockdown: [`docs/plan-unifi-portforwards.md`](plan-unifi-portforwards.md).

## Done / baseline

- Config lives in `.env` (`compose/env.example`); `scripts/settings.py` + `render_site.py`.
- Secrets / machine hardware / SSH local keys gitignored.
- MIT `LICENSE`; no game zips in tree.

## Remaining (Flox)

1. Add `.flox/env/manifest.toml` (`python312`, `gh`, `rsync`, `git`).
2. README: “Install [Flox](https://flox.dev), then `flox activate`.”
3. Optional Actions CI with `flox activate -- python -m unittest …`.

Do **not** move NixOS module logic into Flox services.

## Success criteria

- Clone → copy `compose/env.example` → `.env` → run unit tests.
- Spare x86_64 box can follow the flake for lobbies.
- No secrets or zip assets in the public tree.
