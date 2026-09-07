"""Race numbers on AC car skins, derived from the car model instead of guesswork.

Why this exists in this shape: ``livery.png`` is only the 64x64 icon Content
Manager shows in the skin picker — painting it changes nothing on the car. The
texture that shows up on the bodywork is the body material's ``txDiffuse``
(``Skin_00.dds`` on the Kunos Miata), which is exactly what Kunos' own race
liveries override. So the pipeline is:

1. Read the car KN5, pick the bodywork material, take its diffuse name.
2. Select outward-facing door triangles and rasterize their UVs to find the
   door island in texture space — no hand-calibrated pixel coordinates.
3. Composite the badge into the largest circle that fits inside that island.
4. Save the result under the exact texture name so the skin overrides it.
5. Prove it offline: rasterize the body from the side with the old and the new
   texture and require the badge to appear on the rendered car.

Step 5 is the part that replaces loading the game to check.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import kn5
import skin_uv

SAFE_SKIN_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
REPORT_DIR_NAME = "_number_report"
DEFAULT_PIXEL_FORMAT = "DXT5"

DEFAULT_STYLE = {
    "circle_fill": [255, 255, 255, 255],
    "text_fill": [20, 20, 20, 255],
    "outline": [20, 20, 20, 255],
    "outline_width": 6,
    "diameter_scale": 1.0,
    "max_diameter": 0,
}


@dataclass
class BodyTarget:
    """The bodywork texture a skin must override, plus the meshes that use it."""

    car: str
    kn5_path: Path
    material: str
    texture: str
    texture_size: tuple[int, int]
    model: kn5.Model
    meshes: list[kn5.Mesh]

    @property
    def triangle_count(self) -> int:
        return sum(m.triangle_count for m in self.meshes)


@dataclass
class Placement:
    side: str
    center: tuple[int, int]
    diameter: int
    inside_ratio: float
    axes: "skin_uv.IslandAxes | None" = None


@dataclass
class Check:
    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        return f"[{'PASS' if self.ok else 'FAIL'}] {self.name}: {self.detail}"


@dataclass
class ValidationReport:
    car: str
    skin: str
    number: str
    checks: list[Check] = field(default_factory=list)
    report_dir: Path | None = None

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name=name, ok=ok, detail=detail))

    def text(self) -> str:
        head = f"{self.car} / {self.skin} / #{self.number} — {'PASS' if self.ok else 'FAIL'}"
        return "\n".join([head, *(c.line() for c in self.checks)])

    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


# --------------------------------------------------------------------------- #
# Car model / texture discovery
# --------------------------------------------------------------------------- #


def car_dir(content: Path, car: str) -> Path:
    return Path(content) / "cars" / car


def skin_dir(content: Path, car: str, skin: str) -> Path:
    return car_dir(content, car) / "skins" / skin


def find_car_kn5(content: Path, car: str) -> Path:
    """Main body model: largest non-LOD, non-collider KN5."""
    directory = car_dir(content, car)
    candidates = [
        p
        for p in directory.glob("*.kn5")
        if p.name.lower() != "collider.kn5" and not re.search(r"_lod_?[a-d]\.kn5$", p.name, re.I)
    ]
    if not candidates:
        raise FileNotFoundError(f"no body kn5 in {directory}")
    return max(candidates, key=lambda p: p.stat().st_size)


def load_body_target(content: Path, car: str) -> BodyTarget:
    path = find_car_kn5(content, car)
    model = kn5.read_kn5(path)
    if model.trailing_bytes:
        raise ValueError(
            f"{path.name}: parser left {model.trailing_bytes} trailing bytes — refusing to trust UVs"
        )
    body = skin_uv.pick_body(model)
    blob = model.textures.get(body.texture)
    if blob is None:
        raise ValueError(f"{path.name}: body texture {body.texture} not embedded in kn5")
    with Image.open(io.BytesIO(blob)) as img:
        size = img.size
    return BodyTarget(
        car=car,
        kn5_path=path,
        material=body.material.name,
        texture=body.texture,
        texture_size=size,
        model=model,
        meshes=body.meshes,
    )


def load_skin_texture(content: Path, car: str, skin: str, target: BodyTarget, name: str) -> Image.Image | None:
    """A texture as the game would resolve it: skin override first, then KN5."""
    override = skin_dir(content, car, skin) / name
    if override.is_file():
        with Image.open(override) as img:
            return img.convert("RGBA")
    blob = target.model.textures.get(name)
    if blob is None:
        return None
    with Image.open(io.BytesIO(blob)) as img:
        return img.convert("RGBA")


def load_base_texture(content: Path, car: str, skin: str, target: BodyTarget) -> Image.Image:
    img = load_skin_texture(content, car, skin, target, target.texture)
    if img is None:
        raise ValueError(f"{car}: cannot resolve body texture {target.texture}")
    return img


# --------------------------------------------------------------------------- #
# Factory paint tint
#
# Kunos colours factory skins through the body material's tiled txDetail
# texture, not the diffuse: the Miata's diffuse is a near-white template and
# 05_sunburst_yellow just ships a yellow metal_detail.dds. The detail is
# multiplied in, so a white badge painted into the diffuse would come out
# yellow. Kunos' own race livery (ks_toyota_gt86/rsrnurburg) solves this by
# shipping a neutral white detail and putting the full paint in the diffuse, so
# that is what we do: bake the factory colour into the diffuse, then neutralise
# the detail so the badge keeps its own colours.
# --------------------------------------------------------------------------- #

NEUTRAL_TINT_MIN = 246


def detail_texture_name(target: BodyTarget) -> str:
    material = next((m for m in target.model.materials if m.name == target.material), None)
    return (material.slots.get("txDetail") if material else "") or ""


def texture_tint(img: Image.Image) -> tuple[int, int, int]:
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    return tuple(int(round(float(arr[..., i].mean()))) for i in range(3))  # type: ignore[return-value]


def is_neutral_tint(tint: tuple[int, int, int]) -> bool:
    return min(tint) >= NEUTRAL_TINT_MIN


BAKE_TINT_FLOOR = 24


def bakeable_tint(tint: tuple[int, int, int]) -> tuple[int, int, int]:
    """Lift near-black paint so the multiply keeps the body template's shading.

    Baking replaces the carPaint shader with a plain diffuse. In game a black
    car is still shaped by the shader's specular and reflections, but a diffuse
    multiplied by 0 is a flat silhouette with no ambient occlusion or panel
    lines, and the badge is the only thing left on it. Scale the darkest paints
    up to a floor, keeping their hue.
    """
    top = max(tint)
    if top >= BAKE_TINT_FLOOR:
        return tint
    if top <= 0:
        return (BAKE_TINT_FLOOR, BAKE_TINT_FLOOR, BAKE_TINT_FLOOR)
    scale = BAKE_TINT_FLOOR / top
    return tuple(min(255, int(round(c * scale))) for c in tint)  # type: ignore[return-value]


def bake_tint(diffuse: Image.Image, tint: tuple[int, int, int]) -> Image.Image:
    """Multiply the diffuse template by the factory paint colour."""
    src = diffuse.convert("RGBA")
    alpha = src.getchannel("A")
    arr = np.asarray(src.convert("RGB")).astype(np.float32)
    scale = np.array(tint, dtype=np.float32) / 255.0
    out = np.clip(arr * scale, 0, 255).astype(np.uint8)
    baked = Image.fromarray(out).convert("RGBA")
    baked.putalpha(alpha)
    return baked


def _tint_match(tint: tuple[int, int, int], baked: tuple[int, int, int]) -> tuple[float, float]:
    """Compare colours ignoring overall brightness.

    Baking multiplies the paint colour by the diffuse template, which is darker
    than white on cars whose template carries ambient occlusion. That darkening
    is expected; a hue shift is not.
    """
    tint_mean = max(sum(tint) / 3.0, 1e-6)
    brightness = (sum(baked) / 3.0) / tint_mean
    hue_error = max(abs(b - brightness * t) for t, b in zip(tint, baked))
    return hue_error, brightness


def neutral_detail(img: Image.Image) -> Image.Image:
    """Flat white RGB, original alpha — the flake pattern lives in alpha."""
    src = img.convert("RGBA")
    white = Image.new("RGB", src.size, (255, 255, 255)).convert("RGBA")
    white.putalpha(src.getchannel("A"))
    return white


MIN_LIVERY_TEXTURE = 512
V_ANCHOR_MIN_STRENGTH = 0.3
HAND_ANCHOR_MIN_CONFIDENCE = 0.5


def _door_geometry_check(target: BodyTarget, placement: Placement) -> tuple[str, bool, str]:
    """Name the panel the badge lands on, working back from texture to model.

    The mask that chose the spot and the render that previewed it share the same
    UV assumptions, so both stay happy if those assumptions are wrong. This walks
    the other direction — from the painted texels to the geometry sampling them —
    and insists the answer is an outward-facing side panel rather than the hood
    or a bumper.
    """
    footprint = skin_uv.sample_geometry(
        target.meshes, placement.center, placement.diameter, target.texture_size
    )
    name = f"badge_on_door_geometry[{placement.side}]"
    if not footprint.triangles:
        return name, False, "no geometry samples these texels — the badge would be invisible"

    lo, hi = skin_uv.body_bbox(target.meshes)
    half_width = max(abs(float(lo[0])), abs(float(hi[0])), 1e-6)
    z_span = float(hi[2] - lo[2])
    (x_lo, x_hi), (_, _), (z_lo, z_hi) = footprint.bounds

    outboard = min(abs(x_lo), abs(x_hi)) / half_width
    side_facing = abs(footprint.normal[0])
    upward = abs(footprint.normal[1])
    off_front = (float(hi[2]) - z_hi) / z_span
    off_rear = (z_lo - float(lo[2])) / z_span

    ok = outboard >= 0.7 and side_facing >= 0.6 and upward <= 0.5 and off_front >= 0.1 and off_rear >= 0.1
    return (
        name,
        ok,
        f"panel={footprint.panel_names()} outboard={outboard:.2f} "
        f"normal=({footprint.normal[0]:+.2f},{footprint.normal[1]:+.2f},{footprint.normal[2]:+.2f}) "
        f"z=[{z_lo:+.2f},{z_hi:+.2f}]",
    )


def assert_paintable(target: BodyTarget) -> None:
    """Reject cars whose bodywork has no UV-mapped livery texture.

    Some ports (the Abarth 124) paint the body from a small tiling swatch —
    ``bodyCoat.txDiffuse`` is 128x128 — so there is nowhere on the texture that
    corresponds to a door. Those cars need a decal mesh, not a texture edit.
    """
    if max(target.texture_size) < MIN_LIVERY_TEXTURE:
        raise ValueError(
            f"{target.car}: body material {target.material} paints from "
            f"{target.texture} at {target.texture_size[0]}x{target.texture_size[1]} — "
            "a tiling paint swatch, not a UV livery texture. Race numbers cannot be "
            "baked into this car's skin."
        )


def parse_cm_colour(raw: object) -> tuple[int, int, int] | None:
    """CM writes #AARRGGBB (or #RRGGBB) in cm_skin.json."""
    if not isinstance(raw, str):
        return None
    text = raw.strip().lstrip("#")
    if len(text) == 8:
        text = text[2:]
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def load_cm_paint(content: Path, car: str, skin: str) -> tuple[dict, tuple[int, int, int] | None]:
    """CM paint config for a skin, plus its body colour if paint is enabled."""
    data = load_json(skin_dir(content, car, skin) / "cm_skin.json")
    paint = data.get("carPaint") or {}
    if not paint.get("enabled", False):
        return data, None
    return data, parse_cm_colour(paint.get("color"))


@dataclass
class BasePaint:
    """How a base skin actually looks, with its detail tint folded in."""

    template: Image.Image
    baked: Image.Image
    detail_name: str
    detail: Image.Image | None
    tint: tuple[int, int, int]
    needs_bake: bool
    cm_skin: dict
    cm_colour: tuple[int, int, int] | None

    @property
    def cm_paint_active(self) -> bool:
        return self.cm_colour is not None


def resolve_base_paint(content: Path, car: str, skin: str, target: BodyTarget) -> BasePaint:
    template = load_base_texture(content, car, skin, target)
    detail_name = detail_texture_name(target)
    detail = load_skin_texture(content, car, skin, target, detail_name) if detail_name else None
    cm_skin, cm_colour = load_cm_paint(content, car, skin)

    # CSP repaints the body from cm_skin.json at runtime, so its colour is the
    # authoritative tint — and it has to be switched off in the generated skin
    # or it will paint straight over the badge.
    if cm_colour is not None:
        tint = cm_colour
    elif detail is not None:
        tint = texture_tint(detail)
    else:
        tint = (255, 255, 255)
    needs_bake = cm_colour is not None or (detail is not None and not is_neutral_tint(tint))
    tint = bakeable_tint(tint)

    return BasePaint(
        template=template,
        baked=bake_tint(template, tint) if needs_bake else template,
        detail_name=detail_name,
        detail=detail,
        tint=tint,
        needs_bake=needs_bake,
        cm_skin=cm_skin,
        cm_colour=cm_colour,
    )


def write_cm_paint_disabled(dst: Path, cm_skin: dict) -> None:
    data = dict(cm_skin)
    paint = dict(data.get("carPaint") or {})
    paint["enabled"] = False
    data["carPaint"] = paint
    (dst / "cm_skin.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Per-car profile (optional zone tuning only)
# --------------------------------------------------------------------------- #


def load_json(path: Path) -> dict:
    if not Path(path).is_file():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_reference(catalog: Path, car: str) -> dict:
    """Recorded known-good placement for a car, if we have proven one."""
    return load_json(Path(catalog) / "race_numbers" / f"{car}.json").get("reference") or {}


def check_against_reference(
    report: ValidationReport,
    catalog: Path,
    car: str,
    placements: list[Placement],
    *,
    tolerance: int = 24,
) -> None:
    """Compare derived placement with the recorded one for cars we have proven.

    Placement is recomputed from the model every run, so this is not how the
    badge gets positioned — it is a tripwire for a change in the UV maths
    silently moving numbers onto a different panel.
    """
    reference = load_reference(catalog, car)
    recorded = {p["side"]: p for p in reference.get("placements") or []}
    if not recorded:
        return
    for placement in placements:
        want = recorded.get(placement.side)
        if not want:
            continue
        wx, wy = want["center"]
        cx, cy = placement.center
        drift = max(abs(cx - wx), abs(cy - wy))
        report.add(
            f"matches_recorded_placement[{placement.side}]",
            drift <= tolerance,
            f"derived {placement.center} vs recorded {(wx, wy)} on {want.get('panel', '?')} "
            f"(drift {drift}px, tolerance {tolerance})",
        )


def load_style(catalog: Path, car: str) -> tuple[dict, dict]:
    """Return (style, zone) merged from _default.json and <car>.json."""
    style = dict(DEFAULT_STYLE)
    style.update(load_json(Path(catalog) / "race_numbers" / "_default.json").get("style") or {})
    car_cfg = load_json(Path(catalog) / "race_numbers" / f"{car}.json")
    style.update(car_cfg.get("style") or {})
    return style, dict(car_cfg.get("zone") or {})


# --------------------------------------------------------------------------- #
# Placement
# --------------------------------------------------------------------------- #


def plan_placements(
    target: BodyTarget,
    *,
    zone: dict | None = None,
    style: dict | None = None,
    sides: tuple[str, ...] = ("left", "right"),
) -> tuple[list[Placement], dict[str, np.ndarray]]:
    style = {**DEFAULT_STYLE, **(style or {})}
    scale = float(style.get("diameter_scale") or 1.0)
    cap = int(style.get("max_diameter") or 0) or None

    placements: list[Placement] = []
    masks: dict[str, np.ndarray] = {}
    for side in sides:
        tris, centres = skin_uv.door_faces(target.meshes, side=side, zone=zone)
        if not len(tris):
            raise ValueError(
                f"{target.car}: no door triangles on the {side} side — "
                f"widen 'zone' in catalog/race_numbers/{target.car}.json"
            )
        mask = skin_uv.select_door_island(
            skin_uv.uv_mask(tris, target.texture_size),
            tris,
            centres,
            target.texture_size,
            target.meshes,
        )
        spot = skin_uv.best_spot(
            mask, downscale=4, max_diameter=cap, prefer=skin_uv.mask_centroid(mask)
        )
        diameter = max(16, int(spot.diameter * scale))
        ratio = skin_uv._circle_inside_ratio(mask, spot.center, diameter)
        masks[side] = mask
        placements.append(
            Placement(
                side=side,
                center=spot.center,
                diameter=diameter,
                inside_ratio=ratio,
                axes=skin_uv.island_axes(
                    target.meshes,
                    spot.center,
                    diameter,
                    target.texture_size,
                    sign=skin_uv.side_sign(target.meshes, side),
                ),
            )
        )
    return placements, masks


def orient_badge(badge: Image.Image, axes: "skin_uv.IslandAxes | None") -> Image.Image:
    """Rotate/mirror a badge so it reads upright on the car.

    Without this the number comes out backwards or upside down wherever the UV
    island happens to be packed at a different rotation, which is per-side and
    per-car.
    """
    if axes is None or not axes.usable:
        return badge
    size = badge.width
    half = size / 2.0
    rx, ry = axes.right
    ux, uy = axes.up
    # Inverse map: texture-space offset -> badge pixel, so image right follows
    # the car's screen-right and image up follows the car's up.
    matrix = (
        rx,
        ry,
        half - (rx + ry) * half,
        -ux,
        -uy,
        half + (ux + uy) * half,
    )
    return badge.transform(
        (size, size), Image.AFFINE, matrix, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0)
    )


# --------------------------------------------------------------------------- #
# Badge rendering
# --------------------------------------------------------------------------- #


FONT_PATHS = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)

FONT_ENV = "AC_NUMBER_FONT"

# NixOS keeps fonts in the store rather than /usr/share, so fall back to a search
# that includes XDG_DATA_DIRS — which is how nix-shell exposes a font package.
FONT_SEARCH_ROOTS = (
    "/run/current-system/sw/share/X11/fonts",
    "/run/current-system/sw/share/fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
)
FONT_PREFERENCE = (
    "dejavusans-bold",
    "liberationsans-bold",
    "arialbd",
    "dejavusans",
    "liberationsans",
    "arial",
)


def find_font() -> Path:
    """A scalable font for the digits, or an error saying how to install one.

    Deliberately does not fall back to ``ImageFont.load_default()``: that is a
    small bitmap face, so the badge would come out with unreadable digits and
    fail its own proof for a reason that looks nothing like a missing font.
    """
    override = os.environ.get(FONT_ENV, "").strip()
    if override:
        if not Path(override).is_file():
            raise RuntimeError(f"{FONT_ENV}={override!r} is not a file")
        return Path(override)

    for path in FONT_PATHS:
        if Path(path).is_file():
            return Path(path)

    roots = [*FONT_SEARCH_ROOTS]
    for entry in os.environ.get("XDG_DATA_DIRS", "").split(os.pathsep):
        if entry.strip():
            roots.append(str(Path(entry.strip()) / "fonts"))

    found: dict[str, Path] = {}
    for root in roots:
        base = Path(root)
        if not base.is_dir():
            continue
        for path in base.rglob("*.ttf"):
            found.setdefault(path.stem.lower(), path)
    for stem in FONT_PREFERENCE:
        if stem in found:
            return found[stem]
    if found:
        return sorted(found.values())[0]

    raise RuntimeError(
        "no scalable font found for the race number; install one "
        "(e.g. dejavu_fonts on NixOS, fonts-dejavu on Debian), or point "
        f"{FONT_ENV} at a .ttf"
    )


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(find_font()), size=size)


def render_number_badge(diameter: int, number: str, *, style: dict | None = None) -> Image.Image:
    """White disc with the number, sized so the digits always fit the circle."""
    style = {**DEFAULT_STYLE, **(style or {})}
    fill = _rgba(style.get("circle_fill"), (255, 255, 255, 255))
    text_fill = _rgba(style.get("text_fill"), (20, 20, 20, 255))
    outline = _rgba(style.get("outline"), (20, 20, 20, 255))
    outline_width = max(1, int(style.get("outline_width") or 1))

    pad = outline_width + 2
    size = diameter + pad * 2
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    draw.ellipse(
        (pad, pad, pad + diameter - 1, pad + diameter - 1),
        fill=fill,
        outline=outline,
        width=outline_width,
    )

    text = str(number)
    max_w = diameter * 0.74
    max_h = diameter * 0.62
    font_size = max(8, int(diameter * 0.7))
    while font_size > 8:
        font = _load_font(font_size)
        box = draw.textbbox((0, 0), text, font=font)
        if (box[2] - box[0]) <= max_w and (box[3] - box[1]) <= max_h:
            break
        font_size = int(font_size * 0.92)
    font = _load_font(font_size)
    box = draw.textbbox((0, 0), text, font=font)
    tx = pad + (diameter - (box[2] - box[0])) / 2 - box[0]
    ty = pad + (diameter - (box[3] - box[1])) / 2 - box[1]
    draw.text((tx, ty), text, fill=text_fill, font=font)
    return badge


def apply_numbers(
    base: Image.Image,
    placements: list[Placement],
    number: str | int,
    *,
    style: dict | None = None,
) -> Image.Image:
    """Composite badges into the body texture, leaving its alpha channel alone.

    The body diffuse ships with alpha 0 on Kunos cars and the shader does not
    treat it as opacity; overwriting it risks changing how the paint reads.
    """
    source = base.convert("RGBA")
    alpha = source.getchannel("A")
    rgb = source.convert("RGB")
    for placement in placements:
        badge = orient_badge(
            render_number_badge(placement.diameter, str(number), style=style), placement.axes
        )
        cx, cy = placement.center
        pos = (int(cx - badge.width / 2), int(cy - badge.height / 2))
        # paste-with-mask, not alpha_composite: the body diffuse ships alpha 0,
        # and compositing against a transparent destination zeroes its RGB.
        rgb.paste(badge.convert("RGB"), pos, badge.getchannel("A"))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def badge_probe_texture(
    base: Image.Image,
    placements: list[Placement],
    *,
    colour: tuple[int, int, int] = (255, 0, 255),
) -> Image.Image:
    """Base texture with flat-coloured discs where badges go.

    Rendering this tells us which screen pixels the badge occupies, which is how
    we check the badge is on visible exterior bodywork rather than measuring a
    colour difference that a white base paint would hide.
    """
    rgb = base.convert("RGB").copy()
    draw = ImageDraw.Draw(rgb)
    for placement in placements:
        cx, cy = placement.center
        r = placement.diameter / 2
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour)
    return rgb.convert("RGBA")


def _rgba(raw: object, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        values = [int(v) for v in raw[:4]]
        while len(values) < 4:
            values.append(255)
        return tuple(values)  # type: ignore[return-value]
    return default


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #


def save_body_texture(
    img: Image.Image,
    path: Path,
    *,
    pixel_format: str = DEFAULT_PIXEL_FORMAT,
    max_size: int = 0,
) -> Path:
    out = img.convert("RGBA")
    if max_size and max(out.size) > max_size:
        ratio = max_size / max(out.size)
        out = out.resize((int(out.width * ratio), int(out.height * ratio)), Image.LANCZOS)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, format="DDS", pixel_format=pixel_format)
    return path


# --------------------------------------------------------------------------- #
# Offline proof
# --------------------------------------------------------------------------- #


def render_proof(
    target: BodyTarget,
    texture: Image.Image,
    *,
    side: str = "left",
    width: int = 900,
) -> Image.Image:
    return skin_uv.render_side(target.model, target.meshes, texture, side=side, width=width)


def badge_footprint(render: Image.Image, colour: tuple[int, int, int] = (255, 0, 255)) -> np.ndarray:
    """Screen pixels covered by the probe colour in a side render."""
    arr = np.asarray(render.convert("RGB")).astype(np.int16)
    target = np.array(colour, dtype=np.int16)
    return np.abs(arr - target).max(axis=2) <= 60


def footprint_stats(render: Image.Image, footprint: np.ndarray) -> dict:
    """How the badge reads on screen: is it bright with dark digits inside it?"""
    arr = np.asarray(render.convert("RGB")).astype(np.float32)
    if not footprint.any():
        return {"count": 0, "bbox": None, "aspect": 0.0, "white": 0.0, "dark": 0.0}
    px = arr[footprint]
    lum = 0.299 * px[:, 0] + 0.587 * px[:, 1] + 0.114 * px[:, 2]
    ys, xs = np.nonzero(footprint)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    bw = bbox[2] - bbox[0] + 1
    bh = bbox[3] - bbox[1] + 1
    return {
        "count": int(footprint.sum()),
        "bbox": bbox,
        "aspect": float(bw) / float(bh),
        "white": float((lum >= 150).mean()),
        "dark": float((lum <= 100).mean()),
    }


def _changed_within(before: Image.Image, after: Image.Image, footprint: np.ndarray, *, threshold: int = 40) -> float:
    if not footprint.any():
        return 0.0
    a = np.asarray(before.convert("RGB")).astype(np.int16)
    b = np.asarray(after.convert("RGB")).astype(np.int16)
    delta = np.abs(a - b).max(axis=2)
    return float((delta[footprint] >= threshold).mean())


def render_diff(before: Image.Image, after: Image.Image, *, threshold: int = 40) -> dict:
    """Compare two side renders and describe where the picture changed."""
    a = np.asarray(before.convert("RGB")).astype(np.int16)
    b = np.asarray(after.convert("RGB")).astype(np.int16)
    if a.shape != b.shape:
        raise ValueError("render size mismatch")
    delta = np.abs(a - b).max(axis=2)
    mask = delta >= threshold
    count = int(mask.sum())
    if not count:
        return {"count": 0, "bbox": None, "aspect": 0.0, "white": 0.0, "dark": 0.0}

    ys, xs = np.nonzero(mask)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    bw = bbox[2] - bbox[0] + 1
    bh = bbox[3] - bbox[1] + 1
    after_px = np.asarray(after.convert("RGB")).astype(np.float32)[mask]
    lum = 0.299 * after_px[:, 0] + 0.587 * after_px[:, 1] + 0.114 * after_px[:, 2]
    return {
        "count": count,
        "bbox": bbox,
        "aspect": float(bw) / float(bh),
        "white": float((lum >= 170).mean()),
        "dark": float((lum <= 90).mean()),
    }


def annotate_diff(after: Image.Image, info: dict) -> Image.Image:
    """Outline where the badge landed on the rendered car."""
    out = after.convert("RGB").copy()
    bbox = info.get("footprint_bbox") or info.get("bbox")
    if bbox:
        draw = ImageDraw.Draw(out)
        x0, y0, x1, y1 = bbox
        draw.rectangle((x0 - 3, y0 - 3, x1 + 3, y1 + 3), outline=(255, 60, 60), width=2)
    return out


def reads_upright(
    render: Image.Image,
    bbox: tuple[int, int, int, int] | None,
    number: str,
    style: dict | None = None,
    *,
    span: int = 160,
) -> tuple[bool, str]:
    """Does the badge on the rendered car match the badge, or a flip of it?

    Compares the rendered badge against the intended artwork and its mirror,
    vertical flip and 180 rotation. The intended one has to win, which catches a
    UV island packed backwards even though the badge is in the right place.
    """
    if not bbox:
        return False, "no badge footprint to read"

    crop = _digit_shape(render.crop(bbox), span)
    reference = _digit_shape(render_number_badge(span, str(number), style=style), span)
    if crop is None or reference is None:
        return False, "could not isolate the digits to compare"

    variants = {
        "upright": reference,
        "mirrored": reference[:, ::-1],
        "upside down": reference[::-1, :],
        "rotated 180": reference[::-1, ::-1],
    }
    scores = {
        label: float((crop & ref).sum()) / float(max((crop | ref).sum(), 1))
        for label, ref in variants.items()
    }
    best = max(scores, key=lambda k: scores[k])
    detail = " ".join(f"{k}={scores[k]:.2f}" for k in variants)
    margin = scores[best] - max(v for k, v in scores.items() if k != best)
    if best == "upright":
        return True, f"reads upright (overlap {detail})"
    if margin < 0.03:
        return True, f"digits too symmetric to call, no clear flip (overlap {detail})"
    return False, f"reads {best} (overlap {detail})"


def _digit_shape(badge: Image.Image, span: int) -> np.ndarray | None:
    """Binary mask of just the digits, normalised for size and contrast.

    Comparing brightness directly is dominated by disc size, outline weight and
    the paint showing at the corners, none of which say anything about whether
    the number is the right way round.
    """
    grey = np.asarray(badge.convert("L").resize((span, span), Image.LANCZOS)).astype(np.float32)
    # Drop the outline ring and any bodywork in the corners.
    ys, xs = np.mgrid[0:span, 0:span]
    half = (span - 1) / 2.0
    inner = ((xs - half) ** 2 + (ys - half) ** 2) <= (half * 0.78) ** 2
    field = grey[inner]
    if field.size < 64:
        return None

    ink = np.zeros_like(inner)
    ink[inner] = field < (float(field.min()) + float(field.max())) / 2.0
    rows, cols = np.nonzero(ink)
    if len(rows) < span // 4:
        return None

    box = (int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1)
    tight = Image.fromarray((ink * 255).astype(np.uint8)).crop(box).resize((64, 64), Image.BILINEAR)
    return np.asarray(tight) > 127


def badge_crop(texture: Image.Image, placement: Placement, *, pad: float = 0.35) -> Image.Image:
    cx, cy = placement.center
    r = placement.diameter / 2 * (1 + pad)
    box = (int(cx - r), int(cy - r), int(cx + r), int(cy + r))
    return texture.convert("RGB").crop(box)


def mask_overlay(texture: Image.Image, masks: dict[str, np.ndarray]) -> Image.Image:
    out = texture.convert("RGB").copy()
    arr = np.asarray(out).copy()
    for mask in masks.values():
        arr[mask, 0] = np.minimum(255, arr[mask, 0].astype(np.int16) + 90).astype(np.uint8)
    return Image.fromarray(arr)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _disc_stats(texture: Image.Image, placement: Placement) -> dict:
    arr = np.asarray(texture.convert("RGB")).astype(np.float32)
    ys, xs = skin_uv.circle_pixels(placement.center, placement.diameter, arr.shape[:2])
    px = arr[ys, xs]
    lum = 0.299 * px[:, 0] + 0.587 * px[:, 1] + 0.114 * px[:, 2]
    inner_ys, inner_xs = skin_uv.circle_pixels(
        placement.center, max(4, int(placement.diameter * 0.7)), arr.shape[:2]
    )
    inner = arr[inner_ys, inner_xs]
    inner_lum = 0.299 * inner[:, 0] + 0.587 * inner[:, 1] + 0.114 * inner[:, 2]
    return {
        "white": float((lum >= 200).mean()),
        "dark_inner": float((inner_lum <= 90).mean()),
    }


@dataclass
class ProofCache:
    """Proof renders that depend on the car and its paint, but not the number.

    Validating one skin renders the car three times per side: the base skin, the
    numbered skin, and a probe that locates the badge on screen. Only the
    numbered render changes between drivers, so a grid of 20 cars sharing a
    colour can reuse the other two instead of rendering 120 times.
    """

    base_render: dict[str, Image.Image]
    footprint: dict[str, np.ndarray]
    render_width: int


def build_proof_cache(
    target: BodyTarget,
    base: Image.Image,
    placements: list[Placement],
    *,
    render_width: int = 900,
) -> ProofCache:
    base_render: dict[str, Image.Image] = {}
    footprint: dict[str, np.ndarray] = {}
    for side in sorted({p.side for p in placements}):
        side_placements = [p for p in placements if p.side == side]
        base_render[side] = render_proof(target, base, side=side, width=render_width)
        probe = render_proof(
            target, badge_probe_texture(base, side_placements), side=side, width=render_width
        )
        footprint[side] = badge_footprint(probe)
    return ProofCache(base_render=base_render, footprint=footprint, render_width=render_width)


def validate_numbered_texture(
    *,
    target: BodyTarget,
    base: Image.Image,
    numbered: Image.Image,
    placements: list[Placement],
    number: str,
    skin: str,
    style: dict | None = None,
    report_dir: Path | None = None,
    render_width: int = 900,
    cache: ProofCache | None = None,
) -> ValidationReport:
    report = ValidationReport(car=target.car, skin=skin, number=str(number), report_dir=report_dir)

    report.add(
        "body_texture_identified",
        True,
        f"{target.material}.txDiffuse = {target.texture} "
        f"({target.texture_size[0]}x{target.texture_size[1]}, {target.triangle_count} tris)",
    )

    convention, strength = skin_uv.detect_v_convention(target.model)
    if strength >= V_ANCHOR_MIN_STRENGTH:
        report.add(
            "v_convention_verified",
            convention == skin_uv.V_CONVENTION,
            f"plate texture says '{convention}' (confidence {strength:.2f}), "
            f"code uses '{skin_uv.V_CONVENTION}'",
        )
    else:
        report.add(
            "v_convention_verified",
            True,
            f"no usable plate anchor on this car (confidence {strength:.2f}); "
            f"'{skin_uv.V_CONVENTION}' is locked by tests against cars that have one",
        )

    handedness, confidence = skin_uv.detect_handedness(target.model)
    if confidence >= HAND_ANCHOR_MIN_CONFIDENCE:
        report.add(
            "handedness_verified",
            handedness == skin_uv.HANDEDNESS,
            f"plate text says '{handedness}-handed' (confidence {confidence:.2f}), "
            f"code uses '{skin_uv.HANDEDNESS}-handed'",
        )
    else:
        report.add(
            "handedness_verified",
            True,
            f"no usable plate anchor on this car (confidence {confidence:.2f}); "
            f"'{skin_uv.HANDEDNESS}-handed' is locked by tests against cars that have one",
        )

    for placement in placements:
        report.add(*_door_geometry_check(target, placement))

    for placement in placements:
        report.add(
            f"badge_inside_door_uv[{placement.side}]",
            placement.inside_ratio >= 0.999,
            f"center={placement.center} d={placement.diameter} "
            f"inside_door_island={placement.inside_ratio * 100:.1f}%",
        )
        stats = _disc_stats(numbered, placement)
        report.add(
            f"badge_pixels[{placement.side}]",
            stats["white"] >= 0.55 and stats["dark_inner"] >= 0.05,
            f"white={stats['white'] * 100:.0f}% dark_digits={stats['dark_inner'] * 100:.0f}%",
        )
        base_stats = _disc_stats(base, placement)
        report.add(
            f"changed_from_base[{placement.side}]",
            abs(stats["white"] - base_stats["white"]) >= 0.15
            or abs(stats["dark_inner"] - base_stats["dark_inner"]) >= 0.03,
            f"base white={base_stats['white'] * 100:.0f}% dark={base_stats['dark_inner'] * 100:.0f}%",
        )

    if cache is None or cache.render_width != render_width:
        cache = build_proof_cache(target, base, placements, render_width=render_width)

    renders: dict[str, tuple[Image.Image, Image.Image, dict]] = {}
    for side in sorted({p.side for p in placements}):
        before = cache.base_render[side]
        footprint = cache.footprint[side]
        after = render_proof(target, numbered, side=side, width=render_width)
        stats = footprint_stats(after, footprint)
        min_px = max(60, int(render_width * render_width * 0.0002))

        report.add(
            f"badge_on_visible_bodywork[{side}]",
            stats["count"] >= min_px and 0.4 <= stats["aspect"] <= 2.6,
            f"screen_pixels={stats['count']} (min {min_px}) bbox={stats['bbox']} "
            f"aspect={stats['aspect']:.2f}",
        )
        report.add(
            f"badge_reads_on_render[{side}]",
            stats["white"] >= 0.35 and stats["dark"] >= 0.04,
            f"disc_bright={stats['white'] * 100:.0f}% digits_dark={stats['dark'] * 100:.0f}%",
        )
        upright, detail = reads_upright(after, stats["bbox"], str(number), style)
        report.add(f"number_reads_upright[{side}]", upright, detail)
        # Compare inside the footprint only: DXT compression perturbs the whole
        # texture slightly, so a whole-image diff proves nothing.
        changed = _changed_within(before, after, footprint)
        renders[side] = (before, after, {"footprint_bbox": stats["bbox"], "changed": changed})
        report.add(
            f"badge_changed_the_car[{side}]",
            changed >= 0.5,
            f"{changed * 100:.0f}% of the badge footprint differs from the base skin render",
        )

    if report_dir is not None:
        _write_report(report, report_dir, numbered, placements, renders)
    return report


def _write_report(
    report: ValidationReport,
    report_dir: Path,
    numbered: Image.Image,
    placements: list[Placement],
    renders: dict[str, tuple[Image.Image, Image.Image, dict]],
) -> None:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.txt").write_text(report.text() + "\n", encoding="utf-8")
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "car": report.car,
                "skin": report.skin,
                "number": report.number,
                "ok": report.ok,
                "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in report.checks],
                "placements": [
                    {
                        "side": p.side,
                        "center": list(p.center),
                        "diameter": p.diameter,
                        "inside_ratio": p.inside_ratio,
                    }
                    for p in placements
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for placement in placements:
        badge_crop(numbered, placement).save(report_dir / f"badge_{placement.side}.png")
    for side, (before, after, info) in renders.items():
        before.save(report_dir / f"render_{side}_base.png")
        annotate_diff(after, info).save(report_dir / f"render_{side}_number.png")


# --------------------------------------------------------------------------- #
# Generate / validate entry points
# --------------------------------------------------------------------------- #


def validate_output_name(name: str) -> str:
    cleaned = str(name).strip()
    if not cleaned or not SAFE_SKIN_RE.match(cleaned):
        raise ValueError(f"unsafe output skin name: {name!r}")
    return cleaned


def copy_skin_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(REPORT_DIR_NAME))


@dataclass
class CarPlan:
    """Everything about a car and one of its factory colours that the number does not change.

    Reading the KN5, rasterizing the door UV island and baking the factory paint
    cost the same whether one driver or a whole grid shares the colour, so a
    batch run does that work once and only re-composites the digits per driver.
    """

    car: str
    base_skin: str
    target: BodyTarget
    style: dict
    zone: dict
    placements: list[Placement]
    masks: dict[str, np.ndarray]
    paint: BasePaint
    proof: ProofCache


def prepare_car(
    *,
    content: Path,
    catalog: Path,
    car: str,
    base_skin: str,
    render_width: int = 900,
) -> CarPlan:
    """Do the per-car half of skin generation so a grid can share it."""
    content = Path(content)
    if not skin_dir(content, car, base_skin).is_dir():
        raise FileNotFoundError(skin_dir(content, car, base_skin))

    target = load_body_target(content, car)
    assert_paintable(target)
    style, zone = load_style(Path(catalog), car)
    placements, masks = plan_placements(target, zone=zone, style=style)
    paint = resolve_base_paint(content, car, base_skin, target)
    proof = build_proof_cache(target, paint.baked, placements, render_width=render_width)
    return CarPlan(
        car=car,
        base_skin=base_skin,
        target=target,
        style=style,
        zone=zone,
        placements=placements,
        masks=masks,
        paint=paint,
        proof=proof,
    )


def generate_numbered_skin(
    *,
    content: Path,
    catalog: Path,
    car: str,
    base_skin: str,
    number: str | int,
    output_skin: str,
    out_content: Path | None = None,
    pixel_format: str = DEFAULT_PIXEL_FORMAT,
    max_texture_size: int = 0,
    render_width: int = 900,
    write_report: bool = True,
    force: bool = False,
    plan: CarPlan | None = None,
) -> tuple[Path, ValidationReport]:
    """Build a numbered skin and refuse to ship it unless the proof passes."""
    output_skin = validate_output_name(output_skin)
    content = Path(content)
    src = skin_dir(content, car, base_skin)
    if not src.is_dir():
        raise FileNotFoundError(src)

    if plan is not None and (plan.car != car or plan.base_skin != base_skin):
        raise ValueError(
            f"prepared plan is for {plan.car}/{plan.base_skin}, not {car}/{base_skin}"
        )
    if plan is None:
        plan = prepare_car(
            content=content,
            catalog=catalog,
            car=car,
            base_skin=base_skin,
            render_width=render_width,
        )

    target, style, placements, masks = plan.target, plan.style, plan.placements, plan.masks
    paint = plan.paint
    detail_name, tint, needs_bake = paint.detail_name, paint.tint, paint.needs_bake
    base = paint.baked
    numbered = apply_numbers(base, placements, number, style=style)

    dst = skin_dir(Path(out_content) if out_content else content, car, output_skin)
    copy_skin_tree(src, dst)
    save_body_texture(
        numbered, dst / target.texture, pixel_format=pixel_format, max_size=max_texture_size
    )
    if needs_bake and paint.detail is not None:
        save_body_texture(neutral_detail(paint.detail), dst / detail_name, pixel_format=pixel_format)
    if paint.cm_paint_active:
        # A baked full livery (e.g. 07_hks_hypermax) ships ext_body_Mixed_AO.dds and
        # no cm_skin.json at all. Leaving a disabled carPaint block can still engage
        # CSP's paint path on some cars, which repaints over the badge at runtime.
        cm_path = dst / "cm_skin.json"
        if cm_path.is_file():
            cm_path.unlink()
    _update_ui_skin(dst, number)
    _update_livery_icon(dst, number, style)

    with Image.open(dst / target.texture) as saved:
        saved_rgba = saved.convert("RGBA")

    report_dir = (dst / REPORT_DIR_NAME) if write_report else None
    report = validate_numbered_texture(
        target=target,
        base=base,
        numbered=saved_rgba,
        placements=placements,
        number=str(number),
        skin=output_skin,
        style=style,
        report_dir=report_dir,
        render_width=render_width,
        cache=plan.proof,
    )
    report.add(
        "texture_override_name",
        (dst / target.texture).is_file(),
        f"skin ships {target.texture} (kn5 body diffuse) — {(dst / target.texture).stat().st_size // 1024} KB",
    )
    if needs_bake:
        baked_tint = texture_tint(base)
        hue_error, brightness = _tint_match(tint, baked_tint)
        report.add(
            "paint_colour_preserved",
            hue_error <= 24 and 0.2 <= brightness <= 1.4,
            f"factory colour {tint} baked into {target.texture}, result {baked_tint} "
            f"(hue error {hue_error:.0f}, brightness x{brightness:.2f})",
        )
        if detail_name and (dst / detail_name).is_file():
            with Image.open(dst / detail_name) as saved_detail:
                shipped = texture_tint(saved_detail)
            report.add(
                "detail_neutralised",
                is_neutral_tint(shipped),
                f"{detail_name} shipped at {shipped} so the badge is not tinted by the paint",
            )
    else:
        report.add(
            "paint_colour_preserved",
            True,
            f"{base_skin} paint already lives in {target.texture} (detail tint {tint} is neutral)",
        )

    _check_cm_paint(report, content, car, output_skin, base_skin)
    check_against_reference(report, Path(catalog), car, placements)
    if report_dir is not None:
        _write_report(report, report_dir, saved_rgba, placements, {})
    if masks and report_dir is not None:
        mask_overlay(base, masks).resize((1024, 1024)).save(report_dir / "door_uv_mask.png")

    if not report.ok and not force:
        shutil.rmtree(dst, ignore_errors=True)
        raise RuntimeError(
            "race number validation failed, skin discarded:\n"
            + "\n".join(c.line() for c in report.failures())
        )
    return dst, report


def validate_numbered_skin(
    *,
    content: Path,
    catalog: Path,
    car: str,
    skin: str,
    number: str | int,
    base_skin: str | None = None,
    render_width: int = 900,
    write_report: bool = True,
) -> ValidationReport:
    """Re-check an already generated skin folder without rebuilding it."""
    content = Path(content)
    target = load_body_target(content, car)
    try:
        assert_paintable(target)
    except ValueError as exc:
        report = ValidationReport(car=car, skin=skin, number=str(number))
        report.add("car_supports_baked_numbers", False, str(exc))
        return report

    style, zone = load_style(Path(catalog), car)
    placements, _ = plan_placements(target, zone=zone, style=style)

    path = skin_dir(content, car, skin) / target.texture
    if not path.is_file():
        report = ValidationReport(car=car, skin=skin, number=str(number))
        report.add(
            "texture_override_name",
            False,
            f"{skin} does not ship {target.texture}; a race number in any other file "
            f"(livery.png, cm_skin.json) will not appear on the car",
        )
        return report

    with Image.open(path) as img:
        numbered = img.convert("RGBA")
    # Compare against how the base skin really looks in game (detail tint folded
    # in), otherwise a white template would hide the badge in the render diff.
    paint = resolve_base_paint(content, car, base_skin or skin, target)

    report_dir = (skin_dir(content, car, skin) / REPORT_DIR_NAME) if write_report else None
    report = validate_numbered_texture(
        target=target,
        base=paint.baked,
        numbered=numbered,
        placements=placements,
        number=str(number),
        skin=skin,
        style=style,
        report_dir=report_dir,
        render_width=render_width,
    )
    report.add("texture_override_name", True, f"skin ships {target.texture}")
    _check_cm_paint(report, content, car, skin, base_skin)
    check_against_reference(report, Path(catalog), car, placements)
    if paint.detail_name:
        shipped = load_skin_texture(content, car, skin, target, paint.detail_name)
        shipped_tint = texture_tint(shipped) if shipped is not None else (255, 255, 255)
        report.add(
            "detail_neutralised",
            is_neutral_tint(shipped_tint),
            f"{paint.detail_name} tint {shipped_tint} "
            f"({'neutral' if is_neutral_tint(shipped_tint) else 'would tint the badge'})",
        )
    return report


def _check_cm_paint(
    report: ValidationReport, content: Path, car: str, skin: str, base_skin: str | None = None
) -> None:
    """CSP's carPaint repaints the bodywork and would hide a baked-in badge."""
    _, shipped_colour = load_cm_paint(content, car, skin)
    source = base_skin or skin
    _, base_colour = load_cm_paint(content, car, source)
    if base_colour is None and shipped_colour is None:
        return
    if shipped_colour is None:
        cm_path = skin_dir(content, car, skin) / "cm_skin.json"
        detail = (
            "cm_skin.json removed after baking"
            if not cm_path.is_file()
            else "carPaint disabled in cm_skin.json"
        )
        report.add(
            "cm_paint_disabled",
            True,
            f"carPaint from {source} ({base_colour}) baked into the texture; "
            f"{detail}, so CSP cannot paint over the badge",
        )
    else:
        report.add(
            "cm_paint_disabled",
            False,
            f"{skin}/cm_skin.json still has carPaint enabled ({shipped_colour}); "
            "CSP repaints the body at runtime and the badge will not be visible",
        )


def _update_ui_skin(dst: Path, number: str | int) -> None:
    path = dst / "ui_skin.json"
    data = load_json(path) if path.is_file() else {}
    name = str(data.get("name") or dst.name)
    data["name"] = re.sub(r"\s*#\d+$", "", name) + f" #{number}"
    data["number"] = str(number)
    data["skinname"] = f"#{number}"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _update_livery_icon(dst: Path, number: str | int, style: dict) -> None:
    """The 64x64 CM picker icon — cosmetic only, but keeps the list readable."""
    path = dst / "livery.png"
    if not path.is_file():
        return
    with Image.open(path) as img:
        icon = img.convert("RGBA")
    badge = render_number_badge(
        max(16, int(min(icon.size) * 0.8)),
        str(number),
        style={**style, "outline_width": 1},
    )
    icon.alpha_composite(
        badge,
        ((icon.width - badge.width) // 2, (icon.height - badge.height) // 2),
    )
    icon.save(path)
