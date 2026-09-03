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

Status push from the game box uses `GITHUB_STATUS_*` in `.env`.
