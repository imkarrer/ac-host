# Join the practice lobbies

Always-on practice. Pickup, no server password. **Content Manager only** — the stock launcher cannot download mods.

**Player page (leaderboard + join links):** https://imkarrer.github.io/ac-practice/

**Whitelist:** send the server admin your Steam ID (Steam64, the 17-digit number on your Steam profile) before you try to join. You will be refused until you are on the list.

**Install content before you join.** Content Manager can auto-download only the **124 Spider** from this server. Install Custom Shaders Patch, the GR86, the Civic FK8, and your lobby’s track from the player page first. The NA Miata, Elise SC, and BMW M3 E30 are in the base game.

| Lobby | Join |
| --- | --- |
| Practice — Blackhawk Farms | [Join](https://acstuff.ru/s/q:race/online/join?ip=167.237.13.200&httpPort=8081) |
| Practice — Brainerd Competition | [Join](https://acstuff.ru/s/q:race/online/join?ip=167.237.13.200&httpPort=8082) |
| Practice — Brainerd Donnybrooke | [Join](https://acstuff.ru/s/q:race/online/join?ip=167.237.13.200&httpPort=8083) |

Need Content Manager? [Content Manager Lite](https://github.com/gro-ove/actools/releases/latest) (~8 MB). Extract somewhere permanent, run it, point it at your Steam `assettocorsa` folder.

**Custom Shaders Patch is required** for the GR86 and Civic FK8. Install [Custom Shaders Patch](https://acstuff.club/patch/) (0.2.11) via Content Manager **before** you join. Stock AC will crash on those cars.

## Steps

1. Send the server admin your Steam ID, then install Assetto Corsa and Content Manager.
2. Install Custom Shaders Patch. Restart CM.
3. Install the cars and track you need from the player page (OverTake / AssettoWorld login may be required).
4. Click a Join link (or Drive → Online and search `Practice —`).
5. On the lobby page, click **Download missing content** if the 124 is still missing. Do not join until installs finish.
6. **Livery (color):** Use **Content Manager Full** (not Lite). On the Online lobby page, pick a thumbnail in the row under the car **or** set the livery on **Content → Cars** first — the big car preview must match before you Join. On the 124, use **Bianco** for white, not Owner White. Civic default is Championship White.
7. Back on the lobby page, Join.

**Dev test lobby** (config experiments only): search `[DEV] Practice` in Online — port `8089`. Production lobbies are unchanged.

## If Join fails

- **Connection refused / kicked immediately:** you are not on the whitelist. Send the admin your Steam ID.
- **Checksum failed:** delete that car folder under `content\cars\` (124, GR86, or Civic), reinstall from the player page or Download missing content for the 124.
- **GR86 / Civic crash on load:** you do not have CSP. Install it from the player page, restart CM, try again.
- **Missing track:** install Gray Ghost (Blackhawk) or Brainerd from OverTake before joining that lobby.
- Restart Content Manager after a download if the car or track does not show up.

## Required downloads

Install these in Content Manager before joining. Tracks are large; one Brainerd download covers both layouts.

| Content | Source |
| --- | --- |
| Custom Shaders Patch | [acstuff.club/patch](https://acstuff.club/patch/) |
| 124 Spider (server build) | [GitHub Release](https://github.com/imkarrer/ac-practice/releases/download/content/abarth_124_2016.zip) |
| GR86 Premium | [AssettoWorld](https://www.assettoworld.com/car/toyota-gr86-premium) |
| Civic Type-R FK8 | [AssettoWorld](https://www.assettoworld.com/car/honda-civic-type-r-fk8-5) |
| Gray Ghost (Blackhawk) | [OverTake](https://www.overtake.gg/downloads/gray-ghost-trail.80813/) |
| Brainerd (both layouts) | [OverTake](https://www.overtake.gg/downloads/brainerd-international-raceway.42674/) |

## Rules

- 124 Spider EC P1, Toyota GR86 Premium, Honda Civic Type-R FK8, Mazda Miata NA, Lotus Elise SC, or BMW M3 E30
- Practice, 24-hour loop, pickup
- ABS and TC on; stability off; autoclutch off; no tyre blankets
