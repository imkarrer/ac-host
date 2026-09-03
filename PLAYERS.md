# Join the practice lobbies

Configure the public page URL and join IP in `.env` (`AC_PAGES_URL`, `AC_PUBLIC_IP`), then run `python scripts/render_site.py`.

Player-facing HTML lives in `site/` (GitHub Pages). This file is maintainer notes.

1. Copy `compose/env.example` → `.env` and set `AC_PUBLIC_IP`, `AC_GITHUB_*`, tokens.
2. `python scripts/render_site.py`
3. Publish `site/` to your Pages repo (`AC_GITHUB_REPO`).
4. Friends: whitelist Steam ID → Content Manager → Join → Download missing content.
