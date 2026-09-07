# Deploy pipeline audit: silent-destruction bug class (homelab-bqo.22)

Follow-up to commit `a05a908` ("Stop content deploys deleting machine-local
host files"), which fixed two files that `sync_tree()`'s `rsync -a --delete`
silently erased on every content deploy (`hosts/ac-box/hardware-configuration.nix`,
`hosts/ac-box/ssh-keys.local.nix`). This audit looked for every other instance
of the same shape of bug: an operation that "succeeds" today and only shows
its damage later (next reboot, next login, next 404, next corrupted read).

Method: read `shared/pending_deploy.py`, `scripts/ci_downtime.py`,
`ci_apply_now.py`, `ci_queue_prod.py`, `acctl.py` in full; grepped the whole
tree for every delete/truncate/rmtree/docker-rm; and did a file-by-file diff
of the live `/var/lib/ac-host/src` tree on ac-box against this git checkout
at HEAD (read-only `ssh ac-box`, no writes made to the box).

Each finding below is tagged **FIXED**, **WRITE-UP** (judgement call, not
touched), or **INFO** (no action implied).

---

## 1. WRITE-UP — an entire feature (and a newer `bot.py`) exists only on the
   box and has never been committed to git

**Severity: highest. Blast radius: largest. Not yet triggered.**

Diffing `/var/lib/ac-host/src` against `git ls-files` at HEAD turns up ~150
files that exist live on the box and have **never existed in this repo's git
history, on any branch** (`git log --all --diff-filter=D` finds nothing —
they were never added and then deleted, they were simply never committed).
This is not gitignored-by-design state; it is ordinary application source
that should be tracked. Notably:

- `bot/bot.py` on the box is **not the same file** as the one in git: 52136
  bytes vs. 47072 bytes, different MD5. The box's copy wires up Discord
  "series" commands; git's copy does not.
- Box-only, never-committed modules that this newer `bot.py` and
  `sidecar/plugin.py` actively import: `shared/series_lib.py` (26.6 KB,
  imported by `sidecar/plugin.py:369` via `import series_lib`),
  `shared/kn5.py`, `shared/skin_livery.py`, `shared/skin_uv.py`,
  `bot/series_cmds.py` (40.6 KB), `bot/series_poll.py`,
  `bot/series_poll_content.py`, `bot/send_series_poll_rest.py`.
- Box-only scripts referenced by the *tracked* `scripts/ci_series_pack.sh`:
  it calls `python scripts/generate_series_liveries.py` and
  `python scripts/publish_series_race_pack.py` — **neither file exists in
  git**. A fresh git checkout cannot run this pipeline step at all today.
- More box-only, uncommitted scripts in the same family:
  `scripts/push_standings.py`, `scripts/generate_race_number.py`,
  `scripts/kn5_inspect.py`, `scripts/github_release.py`,
  `scripts/publish_cars.py`, `scripts/sync_series_models.py`,
  `scripts/validate_race_number.py`, plus their `test_*.py` files, and
  content: `catalog/series/series-1.json`, `catalog/race_numbers/*.json`,
  `catalog/cars/some1_honda_nsx_1997_s1.json`, `compose/docker-compose.series.yml`,
  `compose/series.env.example`, `compose/.env.buildkite`,
  `compose/content-www/{index.html,content.json}`.

**Why this is not currently visible as broken:** I checked the persistent
Buildkite checkout that CI actually builds from
(`/var/lib/docker/volumes/ac-host-ci_buildkite-builds/_data/.../ac-host` on
ac-box). `git status --porcelain --untracked-files=all` there is **completely
clean** at HEAD `a05a908`. So the CI pipeline's own working copy has never
seen these files — they must have been placed directly onto
`/var/lib/ac-host/src` by hand (or by some process outside this git/Buildkite
pipeline) before the current rsync-based apply mechanism existed.

**Why this is dangerous now:** there is no `last-applied.json` in
`/var/lib/ac-host/` — the new `ci_downtime.py`/`sync_tree` apply path has
**never actually run for real yet** (the current `pending-deploy.json` shows
sha `a05a908` queued today, not yet applied). The very first time the 03:00
downtime job (or `ci_apply_now.py`'s emergency path) runs `sync_tree(pending-src,
/var/lib/ac-host/src)`, `rsync -a --delete` will delete every file above (none
of it is in `PRESERVE_LOCAL` or any other exclude) and overwrite `bot/bot.py`
with git's older, series-less version. Because `bot/` and `compose/docker-compose.yml`
are in `SIDECAR_PATHS`, essentially any real content deploy will also trigger
`_rebuild_sidecars()`, which does `docker compose ... up -d --build ... bot`
— rebuilding and restarting the bot container from the now-regressed tree
immediately. Net effect: Discord series commands vanish, `sidecar/plugin.py`'s
`import series_lib` starts throwing (caught and logged, but quali-lap sync
silently stops working), and none of it produces a failed exit code anywhere.

**Why I did not fix this myself:** committing ~150 unreviewed files
(including third-party-adjacent tooling like `kn5.py`/`skin_livery.py` and a
bot cog implementing live Discord commands) into the user's history is
exactly the kind of judgement call the task asked me to leave alone. A human
needs to decide: is the box's `bot.py`/series feature set the one that should
win, or does git's leaner version win with the series feature deliberately
staged elsewhere? Either way, the fix is "make the deploy source of truth
match what's actually running," not another rsync exclude.

**Concrete recommended next step for a human:** before the next real
downtime apply runs, either (a) `rsync -n` (dry run) `/var/lib/ac-host/src`
against a fresh clone at `a05a908` to get the full list of what would be
deleted/overwritten and reconcile it into git, or (b) temporarily add these
paths to `PRESERVE_LOCAL` as a stopgap *only* until they're committed
properly — but a stopgap here just hides the divergence, it doesn't fix it.

---

## 2. WRITE-UP — `_extract/` scratch directory is gitignored and unprotected

`.gitignore` excludes `_extract/` entirely. On the box it currently holds
one-off content-repackaging archives: `asw-honda-civic-type-r-fk8-5.7z`,
`asw-toyota-gr86-premium.zip`, `csp-civic-deploy.tar`, `e30-cars.tar`,
`e30-src.tar`, `gr86-deploy.tar`, `gr86-slim.tar`, `na-elise-cars.tar`,
`na-elise-src.tar`, plus the scripts that operate on them
(`fix_gr86_kn5.py`, `patch_gr86_zip.py`, `verify_checksums.py`,
`up_e30.sh`, `up_na_elise.sh`, `list_slow.py`). None of these are read by any
service at runtime (only invoked by hand), but the archives themselves may be
hard to reproduce (some look like manually-sourced or purchased mod content,
not build output). `_extract/` is not in `RSYNC_EXCLUDES`/`PRESERVE_LOCAL`,
so the next real apply deletes it silently.

**Judgement call, not fixed:** whether this is disposable scratch or
irreplaceable source material depends on where the archives actually came
from, which I can't determine from the box alone. Flagging for a human: if
any of these archives can't be re-downloaded/re-extracted trivially, add
`_extract/` to `PRESERVE_LOCAL` (or move the archives somewhere outside the
deployed tree entirely, which is the better fix — nothing under
`/var/lib/ac-host/src` should be a required, non-regenerable artifact store).

---

## 3. FIXED — `dist/*.zip` and `dist/content.json` were the same class of bug
   as the two already fixed

`.gitignore` excludes `dist/*.zip` and `dist/content.json`. These are the car
content zips (e.g. `abarth_124_2016.zip`, `Content.Manager.zip`,
`CustomShadersPatch.zip`, `gb_brainerd.zip`, `pc_civic.zip`, and others) and
the manifest that the player page and Content Manager read to fetch them —
served straight out of the deployed tree, gitignored by design, and rebuilt
by no deploy step. They were **not** in `PRESERVE_LOCAL`, so the next real
apply would have deleted them exactly like the hardware-config/ssh-keys bug:
`nixos-rebuild`/the compose apply succeeds, and the damage (broken download
links, players unable to install content) only appears when someone actually
tries to join.

**Fix applied** (`shared/pending_deploy.py`): added `"dist/*.zip"` and
`"dist/content.json"` to `PRESERVE_LOCAL`, with a comment explaining why,
mirroring the existing two entries. Added a regression test,
`test_sync_tree_preserves_local_dist_artifacts`, to
`shared/test_pending_deploy.py`. Full `shared/` test suite passes (20/20).

`dist/site/` (the rendered player page itself) was deliberately **not**
added — it's fully regenerated by `ci_publish_pages.py` on every run, so
losing it is not silent or permanent.

---

## 4. WRITE-UP — unlocked, non-atomic read-modify-write race on `leaderboard.json`

`scripts/acctl.py:publish_health()` reads `STATE / "leaderboard.json"` with a
plain `json.loads`, falls back to `payload = {}` on any `OSError` or
`JSONDecodeError`, and then **unconditionally writes that payload back** with
a plain `path.write_text(...)` (no atomic tmp+rename, no lock):

```python
path = STATE / "leaderboard.json"
payload: dict = {}
if path.is_file():
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded
    except (OSError, json.JSONDecodeError):
        payload = {}                      # <- silently empty on any corruption
server_health.apply_to_payload(payload, STATE)
text = json.dumps(payload, indent=2) + "\n"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(text, encoding="utf-8")   # <- writes the emptied payload back
```

Meanwhile `sidecar/plugin.py`'s `Leaderboard.save()` writes the *same file*
via `atomic_write()` (tmp file + `Path.replace`), on its own schedule
(heartbeats, lap completions, session resets) — with no coordination between
the two writers. `Leaderboard._load()` has the identical
silently-return-default-on-parse-error pattern.

Two related risks, same root cause:

- **Lost-update race:** if `acctl.py`'s read happens, then `plugin.py`
  atomically replaces the file with new lap data, then `acctl.py`'s write
  lands — the plugin's update is clobbered by `acctl.py`'s now-stale copy.
  `publish_health()` runs from `up-static` (`ExecStart` at every boot per
  `modules/ac-host.nix:146`) and from `drain`/`maintenance`, so this is not a
  rare code path — it runs on every reboot and every apply-now drain/resume.
- **Corruption-to-total-loss:** if `leaderboard.json` is ever unreadable for
  any reason (disk hiccup, an interrupted non-atomic write, manual edit
  typo), the *very next* boot's `publish_health()` call silently treats the
  whole board as empty and immediately persists that empty board over the
  real one — permanently losing every lobby's all-time best laps, with
  nothing printed to indicate it happened. This is the same "looks fine,
  discovered days later" shape as the original bug, just triggered by
  corruption instead of git.

The same swallow-and-default pattern (`except (OSError, json.JSONDecodeError):
return default`, no logging) also exists in `bot/bot.py:load_json` (protects
`whitelist.json`, `steam_requests.json`) and `shared/server_health.py:read_flag`.
`bot.py` and `plugin.py`'s own writers *are* atomic (tmp + `.replace()`), so
those two are lower-risk than `acctl.py`'s `leaderboard.json` writer
specifically — but the "corrupt read silently becomes an empty write" shape
is systemic across all four load_json-style helpers, not just one file.

**Not fixed:** this needs an actual design decision (lock file? merge instead
of replace? at least log+refuse-to-write on parse failure instead of
silently emptying?) rather than a one-line exclude, so it's written up for a
human rather than patched here.

---

## 5. INFO — stale top-level `arcade-hub.nix`, already resolved by today's commits

The box's `/var/lib/ac-host/src/arcade-hub.nix` (top level, never tracked in
git) is a **dead, orphaned copy**. Commits `3852489` ("Add canonical
arcade-hub module from home-arcade") and `e8590f4` ("Enable arcade-hub on
ac-box"), both from earlier today, moved the real module to
`modules/arcade-hub.nix` and wired it in via `flake.nix`
(`nixosModules.arcade-hub = import ./modules/arcade-hub.nix`) and
`hosts/ac-box/configuration.nix` (`services.arcade-hub = { ... }`). I
confirmed nothing in the current tracked config imports the old top-level
path anymore — `configuration.nix` only references `services.arcade-hub`,
which now resolves through the flake module. Diffing the two copies shows
the top-level one is the "vendored, mojibake-corrupted copy with hardcoded
lanAddress/gameInterface defaults" the `3852489` commit message describes.

**Verdict: junk, safe to sweep.** No action needed — the next real deploy's
`rsync --delete` removing this file (it's not git-tracked and not excluded)
is the *correct* outcome now that its replacement is properly homed and
wired. This is the exact example named in the task; today's commits already
fixed the underlying problem, so it just needs to actually get deployed.

---

## 6. INFO — stale duplicate `state/` directory nested inside the deployed tree

`/var/lib/ac-host/src/state/` (gitignored via the top-level `state/` rule)
holds `whitelist.json`, `whitelist.json.example`, and
`static/{blackhawk,brainerd-competition,brainerd-donnybrooke}/cfg/*.ini`.
This is distinct from the real prod state at `/var/lib/ac-host/whitelist.json`
and `/var/lib/ac-host/static/` (one directory level up, outside `src/`) —
`acctl.py`'s `apply_env()` only falls back to `REPO / "state"` when
`/var/lib/ac-host` doesn't exist, which it does, so prod doesn't use this
nested copy today. It looks like a leftover from early bootstrapping/testing
run directly inside the checkout before `/var/lib/ac-host` existed.

**Not fixed, low priority:** gitignored and unprotected like the others, so
a real apply will delete it — but since the authoritative copies live
elsewhere and are unaffected, this looks like safe-to-lose junk rather than a
landmine. Worth a quick human diff against the real `whitelist.json` before
assuming that, since I did not compare file contents byte-for-byte.

---

## 7. INFO — the `_local_wipe_backup/` mechanism referenced in excludes does
   not exist (task item 3)

`RSYNC_EXCLUDES` in `shared/pending_deploy.py` includes `"_local_wipe_backup/"`,
which strongly implies there is (or was meant to be) a wipe/rollback
operation that stages a backup under that name before doing something
destructive. I searched the entire repo (all file types, not just `.py`) and
the entire box for any reference to `_local_wipe_backup` or a `wipe` script:

- No file in `~/src/ac-host` (any extension) creates, reads, or restores from
  `_local_wipe_backup/` — the only occurrence anywhere in git history is the
  exclude-pattern string itself.
- No `_local_wipe_backup` directory exists anywhere under `/var/lib/ac-host`
  on the box.
- `docs/` has no mention of a wipe procedure.

**Conclusion: this is a vestigial or planned-but-never-implemented safety
net.** Practically, this means `sync_tree()`'s `rsync -a --delete` currently
has **no backup-and-restore capability at all** despite the naming
convention suggesting one should exist — if a bad apply deletes something
important, there is no automated undo; recovery would have to come from
whatever's still in `pending-src`, a machine snapshot, or git. Given finding
#1 above (a real, untested first apply is imminent), a human should decide
whether to build this properly before the first live apply, or to at least
snapshot `/var/lib/ac-host` out-of-band before it runs.

---

## 8. INFO — stray duplicate `bot/downtime.py` shadows the tracked module

The box has `downtime.py` in **both** `bot/` and `shared/`, byte-identical,
both dated the same minute. Git only tracks `shared/downtime.py`. `bot.py`'s
own sys.path search (`_HERE` before `_HERE.parent / "shared"`) means the
box's stray `bot/downtime.py` currently shadows the real one — harmless
today since they're identical, but any future edit to `shared/downtime.py`
would silently not take effect for the bot until this stray copy is gone.

**No action needed:** `bot/downtime.py` is untracked and not excluded, so
the next real `rsync --delete` removes it on its own, which is the correct
outcome (matches git's expectation that only `shared/downtime.py` should
exist). Noted for awareness only — someone reading `git status` after a
real deploy might otherwise wonder why a file "disappeared."

---

## 9. INFO — `arcade/metadata/crops/*.yaml`: unclear provenance, flagged for
   human triage

Four box-only files under `/var/lib/ac-host/src/arcade/metadata/crops/`
(`_layouts.yaml`, `goldeneye_007.yaml`, `mario_kart_64.yaml`,
`super_mario_kart.yaml`) don't correspond to anything in this repo's git
history and aren't obviously related to `modules/arcade-hub.nix` (whose own
header says "game files stay on `/srv/arcade`, not in git" — a different
path). Given the "arcade" tenant's actual code lives in a separate
`home-arcade` repository per the homelab README, this may be leftover
content from before that split, or content deployed by a different pipeline
entirely that happens to share this directory. Not enough information from
ac-box alone to say whether this is safe-to-sweep junk or another sibling
system's live output sitting unprotected in ac-host's blast radius (the same
shape as finding #1, just smaller). Flagging rather than guessing.

---

## Other destructive operations audited: no additional issues found

Full grep for `rmtree`, `--delete`, `.unlink(`, `shutil.move`, `docker rm`,
`docker volume rm`, `compose down`, `system prune`, and truncating writes
across `shared/`, `scripts/`, `sidecar/`, `bot/`:

- **`acctl.py` container churn** (`docker rm -f` in `run_server_container`,
  `cmd_down_static`, `cmd_stop_race`): only ever removes containers by name
  before recreating them; all game/steam state lives in **named** Docker
  volumes (`ac-host_ac-server`, `ac-host_steam`, via `docker_volume()`),
  which are never targeted by `docker volume rm` anywhere in the codebase.
  No blast radius beyond the intended container recycle.
- **`scripts/sync_content.py`**: `shutil.rmtree(dest)` before
  `copytree` — but `dest` is always a specific `content/cars/<car>/...` or
  `content/tracks/<folder>` subpath, and this is a manually-invoked authoring
  tool (`--ac-root` points at a local AC install), not part of the
  automated deploy path. Bounded, human-driven, not a landmine.
- **`scripts/render_site.py`**: `shutil.rmtree(out)` only when `--out` is the
  default gitignored `dist/site` (never `--in-place`); fully regenerated
  immediately after. No state loss.
- **`scripts/bootstrap_ssh.py`**: writes `ssh-keys.local.nix` and fetches
  `hardware-configuration.nix` — this is the (human-run, one-time) tool that
  *populates* the two files the original bug deleted, not a risk to them.
  Worth noting for a human: `write_keys_nix()` replaces the file's contents
  wholesale from whatever keys are on the *current* workstation
  (`ensure_key()` + `extra_pubkeys()`), so re-running it from a different
  machine than usual would silently drop any key manually added by someone
  else. Not part of the automated pipeline, so left as a note rather than a
  fix.
- **`sidecar/auth.py`**: only writes `whitelist.json` with `{"players": []}`
  when the file **does not already exist** (`if not whitelist.is_file()`) —
  cannot clobber an existing whitelist.
- **`ci_apply_now.py`**, **`ci_queue_prod.py`**: no deletes beyond the
  already-covered `sync_tree` calls.
- No `docker compose down`, `docker volume rm`, or `docker system/volume
  prune` anywhere in the tree.

`SIDECAR_PATHS = ("sidecar/", "bot/", "compose/docker-compose.yml")` and
`rebuild_sidecars_from_diff()` only *trigger a rebuild*
(`docker compose up -d --build`) — they don't delete anything themselves.
The risk they carry is entirely downstream of finding #1: a rebuild pulls
whatever `sync_tree` just placed in `/var/lib/ac-host/src`, so once #1 is
resolved this path is safe.

---

## Summary

| # | Finding | Category | Status |
|---|---|---|---|
| 1 | ~150 files incl. a newer `bot.py` and the whole "series" feature live only on the box, never in git | Judgement call — largest blast radius | **Written up**, not fixed |
| 2 | `_extract/` scratch archives gitignored, unprotected | Judgement call | Written up |
| 3 | `dist/*.zip`, `dist/content.json` unprotected (same class as original bug) | Unambiguous, low-risk | **Fixed** (`PRESERVE_LOCAL` + test) |
| 4 | Unlocked, non-atomic race on `leaderboard.json`; systemic silent-default-on-corrupt-read pattern | Judgement call | Written up |
| 5 | Stale top-level `arcade-hub.nix` | Resolved by prior commits today | No action needed |
| 6 | Nested stale `src/state/` duplicate | Low priority | Written up |
| 7 | `_local_wipe_backup/` has no implementation anywhere | Informational (task item 3) | Written up |
| 8 | Stray duplicate `bot/downtime.py` | Self-correcting | No action needed |
| 9 | `arcade/metadata/crops/*.yaml` provenance unclear | Judgement call | Written up |
| — | All other destructive ops (`docker rm`, `rmtree`, etc.) | Audited | No issues found |

**What was actually changed:** `shared/pending_deploy.py` (`PRESERVE_LOCAL`
extended with `dist/*.zip` and `dist/content.json`, with a comment) and
`shared/test_pending_deploy.py` (one new regression test). Full `shared/`
suite passes: 20/20. Everything else above is a write-up for a human to
decide, per the instruction to fix only unambiguous, low-risk items.
