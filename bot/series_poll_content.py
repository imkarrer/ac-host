"""Series #1 poll copy — no discord.py dependency."""

from __future__ import annotations

PM_ROLE_DEFAULT = "product manager"
POLL_DURATION_HOURS = 168

INTRO = """🏁 **Series #1 — PM review (not public yet)**

We're shaping our first championship. **Please vote in every poll below** and reply to the freeform prompt at the end.

After PM review we'll revise, then post publicly for all `@ac-practice` members. Winning options drive a **single non-points pilot race** (Round 0) to test signup → quali → grid → results.

**Fixed rules (not voted on):**
• `/intake` first (Steam + unique number 1–999), then `/ac-practice signup` — list locks when **qualifying closes**
• **Miss quali → back of grid**
• **Quali:** server cut detection — invalid lap, no quali time
• **Race:** track limits via **stewarding**, not auto-DQ
• **Driver aids:** your choice in-car
• **Race length:** one **time** per round; we set laps per track internally"""

FREEFORM = """📝 **Anything we missed?**

Reply here with:
• Format ideas we didn't cover
• Hard **can't race** dates in the next ~6 weeks
• Car/track combos for a future season
• Quali or signup pain points

When you're done, react ✅ on this message or say "looks good" so we know you're finished."""

POLLS: list[tuple[str, list[str]]] = [
    (
        "Series #1 — which ONE car?",
        [
            "Toyota GR86 Premium (mod, CSP)",
            "Abarth 124 Spider (mod)",
            "Honda Civic (mod)",
            "Mazda Miata (base game)",
            "Lotus Elise SC (base game)",
            "BMW M3 E30 (base game)",
            "Other — reply in thread (free public link; paid DLC needs unanimous ac-practice)",
        ],
    ),
    (
        "How should we set the starting grid?",
        [
            "Live quali on race night (~12 min Qualify → Race)",
            "Async hotlap week (quali server days ahead; race night = race only)",
        ],
    ),
    (
        "If the pilot works, how long should the championship be?",
        [
            "3 rounds — each track once",
            "6 rounds — each track twice",
            "8–10 rounds — repeats + optional wildcard",
            "Drop-in rounds — run when turnout looks good",
        ],
    ),
    (
        "Race length each round? (time-based; laps set per track)",
        ["15 minutes", "20 minutes", "25 minutes", "30 minutes"],
    ),
    (
        "Damage & wear?",
        [
            "Full sim — damage, tyre wear, fuel on",
            "Cosmetic damage only",
            "No damage, tyres wear",
            "Arcade — no damage, wear, or fuel",
        ],
    ),
    (
        "Tyre rules for the series?",
        [
            "One compound all season (same for everyone)",
            "Organizer picks per round",
            "Open compound — strategy allowed",
        ],
    ),
    (
        "Best regular race slot? (Central Time)",
        [
            "Sunday 2:00 PM CT",
            "Sunday 7:00 PM CT",
            "Saturday 2:00 PM CT",
            "Saturday 7:00 PM CT",
            "Friday 8:00 PM CT",
            "Thursday 8:00 PM CT",
            "Wednesday 8:00 PM CT",
            "Biweekly at winning time",
            "Monthly — one round per month",
        ],
    ),
    (
        "Championship points? (pilot is non-points)",
        [
            "Top 5 — 10 / 8 / 6 / 4 / 2",
            "Podium only — 10 / 6 / 4",
            "Top 3 — 15 / 10 / 7",
            "No points — bragging rights only",
            "Top 5 + fastest lap bonus (+1 if in points)",
        ],
    ),
    (
        "Where should Round 0 (pilot) be?",
        [
            "Blackhawk Farms",
            "Gingerman — full forward",
            "Road America",
        ],
    ),
]
