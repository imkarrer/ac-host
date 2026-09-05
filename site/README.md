# Player status page (GitHub Pages)

Templates use `__AC_*__` placeholders. Configure **ac-host `.env`**, then:

```bash
python scripts/render_site.py
# push dist/site/ to your Pages repo (AC_GITHUB_REPO)
```

| Path | Role |
| --- | --- |
| `/` | Production |
| `/dev/` | Test lobby |

Status push from the game box uses `GITHUB_STATUS_*` in `.env`. After each
successful JSON PUT the plugin also POSTs a ping to `STATUS_EVENT_URL` (default
`https://ntfy.sh/ac-<owner>-<repo>-status`). The page listens on that topic and
refetches `leaderboard.json` immediately, then retries a few seconds for Pages CDN
lag. A 15s poll stays as fallback.

The header light is the box, not lobby occupancy. `leaderboard.json` `status` is
`maintenance` / `down` / `up`. The plugin heartbeats `aliveAt` over ntfy every
60s so an empty lobby stays green. Flip it with `python scripts/acctl.py
maintenance --on --message "…"` (and `--off` when you're back).
