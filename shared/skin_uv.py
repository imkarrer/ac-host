"""Locate a car's body texture and door UV island, and render offline proof.

Everything here is derived from the KN5 itself, so no per-car pixel guessing:

* ``pick_body`` finds the bodywork material (damage/dust slots + triangle mass)
  and the meshes that use it. Its ``txDiffuse`` is the texture a skin must
  override — the same file Kunos' own race liveries replace.
* ``door_triangles`` selects outward-facing triangles inside a door zone
  expressed as fractions of the body bounding box, so it transfers between cars.
* ``uv_mask`` rasterizes those triangles into texture space; ``best_spot``
  returns the largest circle that fits inside that island.
* ``render_side`` rasterizes the body orthographically with the new texture so
  a badge can be verified without launching AC.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import ndimage

import kn5

# Slots that only bodywork materials carry on Kunos-style shaders.
BODY_SLOT_HINTS = ("txDamage", "txDust", "txDamageMask")
BODY_NAME_HINTS = ("body", "chassis", "carpaint", "paint", "coat")
INTERIOR_HINTS = ("int_", "interior", "cockpit", "dash", "seat", "carpet", "leather")

# Door zone as fractions of the body bounding box (y = height, z = length).
DEFAULT_ZONE = {
    "y_min": 0.35,
    "y_max": 0.72,
    "z_min": 0.42,
    "z_max": 0.73,
    "normal_x_min": 0.5,
    "x_frac_min": 0.35,
}


@dataclass
class BodySelection:
    material: kn5.Material
    meshes: list[kn5.Mesh]
    texture: str

    @property
    def triangle_count(self) -> int:
        return sum(m.triangle_count for m in self.meshes)


@dataclass
class Spot:
    center: tuple[int, int]
    diameter: int
    inside_ratio: float


@dataclass
class Footprint3D:
    """Where a patch of texture actually sits on the car."""

    triangles: int
    meshes: dict[str, int]
    centre: tuple[float, float, float]
    normal: tuple[float, float, float]
    bounds: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]

    def panel_names(self) -> str:
        return ", ".join(
            name for name, _ in sorted(self.meshes.items(), key=lambda kv: -kv[1])
        ) or "nothing"


def sample_geometry(
    meshes: list[kn5.Mesh],
    center: tuple[int, int],
    diameter: int,
    size: tuple[int, int],
) -> Footprint3D:
    """Find the geometry that samples a circular patch of the texture.

    Runs from texture space back to the model, so it answers "what panel did we
    just paint on" without reusing the mask that chose the spot.
    """
    w, h = size
    cx, cy = center
    radius = diameter / 2.0
    positions: list[np.ndarray] = []
    normals: list[np.ndarray] = []
    counts: dict[str, int] = {}

    for mesh in meshes:
        uv = np.asarray(mesh.uvs, dtype=np.float32)
        pos = np.asarray(mesh.positions, dtype=np.float32)
        nrm = np.asarray(mesh.normals, dtype=np.float32)
        idx = np.asarray(mesh.indices, dtype=np.int64)
        if idx.size < 3 or pos.size == 0:
            continue
        idx = idx[: (idx.size // 3) * 3].reshape(-1, 3)
        if idx.max() >= len(uv) or idx.max() >= len(pos):
            continue
        u = uv[idx][..., 0].mean(axis=1) * w
        v = _flip_v(uv[idx][..., 1]).mean(axis=1) * h
        hit = ((u - cx) ** 2 + (v - cy) ** 2) <= radius * radius
        if not hit.any():
            continue
        counts[mesh.name] = int(hit.sum())
        positions.append(pos[idx[hit]].reshape(-1, 3))
        normals.append(nrm[idx[hit]].mean(axis=1))

    if not positions:
        return Footprint3D(0, {}, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), ((0, 0), (0, 0), (0, 0)))

    pts = np.concatenate(positions)
    nrms = np.concatenate(normals)
    return Footprint3D(
        triangles=int(sum(counts.values())),
        meshes=counts,
        centre=tuple(float(x) for x in pts.mean(axis=0)),  # type: ignore[arg-type]
        normal=tuple(float(x) for x in nrms.mean(axis=0)),  # type: ignore[arg-type]
        bounds=tuple(  # type: ignore[arg-type]
            (float(pts[:, i].min()), float(pts[:, i].max())) for i in range(3)
        ),
    )


def pick_body(model: kn5.Model) -> BodySelection:
    """Choose the exterior bodywork material whose diffuse a skin must override."""
    tris_by_mat: dict[int, int] = {}
    for mesh in model.meshes:
        tris_by_mat[mesh.material_id] = tris_by_mat.get(mesh.material_id, 0) + mesh.triangle_count

    best: tuple[float, int] | None = None
    for mat_id, tris in tris_by_mat.items():
        if not 0 <= mat_id < len(model.materials):
            continue
        mat = model.materials[mat_id]
        name = mat.name.lower()
        if any(hint in name for hint in INTERIOR_HINTS):
            continue
        if not mat.diffuse_texture():
            continue
        score = float(tris)
        if all(slot in mat.slots for slot in BODY_SLOT_HINTS):
            score *= 4.0
        if any(hint in name for hint in BODY_NAME_HINTS):
            score *= 2.0
        if best is None or score > best[0]:
            best = (score, mat_id)

    if best is None:
        raise ValueError("no bodywork material found")

    mat_id = best[1]
    mat = model.materials[mat_id]
    meshes = [m for m in model.meshes if m.material_id == mat_id and m.uvs]
    return BodySelection(material=mat, meshes=meshes, texture=mat.diffuse_texture())


# AC stores V shifted rather than mirrored: a stored v of -0.669 samples texture
# row 0.331, i.e. the raw value under ordinary texture wrapping. Negating it
# instead (row 0.669) mirrors the whole layout vertically, which still produces
# a self-consistent mask and render — the badge looks right in an offline
# preview while the game paints it on the panel occupying the mirrored slot. On
# the Miata that mirror maps the doors onto the hood and rear bumper, which is
# exactly the failure this constant exists to prevent. Anchored by license plate
# textures, which are authored upright: see detect_v_convention.
V_CONVENTION = "wrap"

# AC's world basis is right-handed, so the direction that appears to the right
# of a viewer is cross(view_direction, up). Standing outside the +X flank the
# view direction is -X, giving cross(-X, +Y) = -Z: the car's tail is on the
# right. Assuming the opposite mirrors every flank render, which makes a
# backwards number look correct in an offline preview. Anchored by number plate
# textures, whose text runs left-to-right for a viewer at that end of the car:
# see detect_handedness.
HANDEDNESS = "right"


def screen_right(sign: float) -> np.ndarray:
    """World direction that appears rightwards when viewing a flank outside-in.

    ``sign`` is the X side being viewed, as returned by :func:`side_sign`.
    """
    return np.array([0.0, 0.0, -1.0], dtype=np.float64) * sign


def _texture_axis_in_world(mesh: kn5.Mesh, axis: int = 0) -> np.ndarray | None:
    """World direction that a texture axis (+u or +v) points along."""
    pos = np.asarray(mesh.positions, dtype=np.float64)
    uv = np.asarray(mesh.uvs, dtype=np.float64)
    idx = np.asarray(mesh.indices, dtype=np.int64)
    if idx.size < 3 or pos.size == 0:
        return None
    idx = idx[: (idx.size // 3) * 3].reshape(-1, 3)
    if idx.max() >= len(uv) or idx.max() >= len(pos):
        return None

    want = np.array([1.0, 0.0]) if axis == 0 else np.array([0.0, 1.0])
    acc = np.zeros(3)
    weight = 0.0
    for tri in idx:
        p0, p1, p2 = pos[tri]
        t0, t1, t2 = uv[tri]
        duv = np.stack([t1 - t0, t2 - t0], axis=1)
        det = float(np.linalg.det(duv))
        if abs(det) < 1e-12:
            continue
        direction = np.stack([p1 - p0, p2 - p0], axis=1) @ np.linalg.solve(duv, want)
        n = float(np.linalg.norm(direction))
        if n < 1e-12:
            continue
        acc += (direction / n) * abs(det)
        weight += abs(det)

    if weight <= 0:
        return None
    out = acc / weight
    n = float(np.linalg.norm(out))
    return out / n if n > 1e-9 else None


def nose_direction(model: kn5.Model, meshes: list[kn5.Mesh]) -> float:
    """Which Z direction the car's nose points, from its headlights."""
    lights = [
        m
        for m in model.meshes
        if m.positions
        and any(k in m.name.lower() for k in ("headlight", "light_front", "lights_front"))
    ]
    if not lights:
        return 1.0
    lo, hi = body_bbox(meshes)
    zs = np.concatenate([np.asarray(m.positions, dtype=np.float64)[:, 2] for m in lights])
    return 1.0 if zs.mean() > (float(lo[2]) + float(hi[2])) / 2.0 else -1.0


def detect_handedness(model: kn5.Model) -> tuple[str, float]:
    """Independent check of the world basis, using plate textures as ground truth.

    A plate's text runs left-to-right for someone standing at that end of the
    car, so the world direction of the texture's +u axis is a direct reading of
    which way 'right' points for that viewer.
    """
    body = pick_body(model)
    nose = nose_direction(model, body.meshes)
    lo, hi = body_bbox(body.meshes)
    mid_z = (float(lo[2]) + float(hi[2])) / 2.0
    up = np.array([0.0, 1.0, 0.0])

    votes: list[float] = []
    for mesh in model.meshes:
        texture = model.texture_for(mesh).lower()
        if "plate" not in texture or "_nm" in texture or "norm" in texture:
            continue
        if len(mesh.uvs) < 4:
            continue
        u_axis = _texture_axis_in_world(mesh, axis=0)
        if u_axis is None or abs(u_axis[0]) < 0.5:
            continue
        z_mean = float(np.asarray(mesh.positions, dtype=np.float64)[:, 2].mean())
        # Outward normal of the end this plate sits on, then the viewer's gaze.
        outward = nose if (z_mean - mid_z) * nose > 0 else -nose
        view = np.array([0.0, 0.0, -outward])
        right_handed = np.cross(view, up)
        votes.append(float(np.dot(u_axis, right_handed)))

    if not votes:
        return "unknown", 0.0
    mean = float(np.mean(votes))
    return ("right" if mean > 0 else "left"), abs(mean)


def _flip_v(v: np.ndarray) -> np.ndarray:
    """Stored V -> top-left texture space."""
    return np.mod(v, 1.0)


def detect_v_convention(model: kn5.Model) -> tuple[str, float]:
    """Independent check of the V rule, using plate textures as ground truth.

    Number plates are authored upright, so the top of the plate in 3D must map
    to the top of its texture. Returns the winning convention and how strong the
    evidence is, so a car with no usable plate can be skipped rather than
    guessed at.
    """
    best: tuple[str, float] = ("unknown", 0.0)
    for mesh in model.meshes:
        texture = model.texture_for(mesh).lower()
        if "plate" not in texture or len(mesh.uvs) < 4:
            continue
        if "_nm" in texture or "norm" in texture:
            continue
        pos = np.asarray(mesh.positions, dtype=np.float32)
        uv = np.asarray(mesh.uvs, dtype=np.float32)
        height = pos[:, 1]
        v = uv[:, 1]
        if height.std() < 1e-4 or v.std() < 1e-6:
            continue
        # Upright means higher in 3D maps to a lower texture row.
        corr_wrap = float(np.corrcoef(height, np.mod(v, 1.0))[0, 1])
        corr_negate = float(np.corrcoef(height, -v)[0, 1])
        winner = "wrap" if corr_wrap < corr_negate else "negate"
        strength = abs(corr_wrap - corr_negate) / 2.0
        if strength > best[1]:
            best = (winner, strength)
    return best


def side_sign(meshes: list[kn5.Mesh], side: str) -> float:
    """Which X direction this car's own mesh names call ``side``.

    Kunos is not consistent about which sign is left, so take the model's word
    for it when it names its panels, and fall back to left = -X.
    """
    votes: dict[str, list[float]] = {"left": [], "right": []}
    for mesh in meshes:
        lowered = mesh.name.lower()
        if not mesh.positions:
            continue
        for key in ("left", "right"):
            if key in lowered:
                votes[key].append(float(np.asarray(mesh.positions, dtype=np.float32)[:, 0].mean()))

    left_x = float(np.mean(votes["left"])) if votes["left"] else None
    right_x = float(np.mean(votes["right"])) if votes["right"] else None
    if left_x is not None and right_x is not None and abs(left_x - right_x) > 1e-3:
        left_is_positive = left_x > right_x
    elif left_x is not None and abs(left_x) > 1e-3:
        left_is_positive = left_x > 0
    else:
        left_is_positive = False

    if side == "left":
        return 1.0 if left_is_positive else -1.0
    return -1.0 if left_is_positive else 1.0


def door_meshes(meshes: list[kn5.Mesh], side: str) -> list[kn5.Mesh]:
    """Body meshes the car itself calls doors, on one side."""
    sign = side_sign(meshes, side)
    found = []
    for mesh in meshes:
        if "door" not in mesh.name.lower() or not mesh.positions:
            continue
        x = float(np.asarray(mesh.positions, dtype=np.float32)[:, 0].mean())
        if x * sign > 0:
            found.append(mesh)
    return found


def body_bbox(meshes: list[kn5.Mesh]) -> tuple[np.ndarray, np.ndarray]:
    pts = np.concatenate([np.asarray(m.positions, dtype=np.float32) for m in meshes])
    return pts.min(axis=0), pts.max(axis=0)


def door_triangles(
    meshes: list[kn5.Mesh],
    *,
    side: str,
    zone: dict | None = None,
) -> np.ndarray:
    """Return UV triangles (N,3,2) for outward door faces on one side."""
    return door_faces(meshes, side=side, zone=zone)[0]


def door_faces(
    meshes: list[kn5.Mesh],
    *,
    side: str,
    zone: dict | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """UV triangles and their 3D centres for outward door faces on one side.

    When the car names its door meshes we use them and drop the along-the-car
    limits, because a fraction of the body's length is a guess that clips the
    front of a short door and drags the number backwards. The limits still apply
    to cars that model the body as one mesh.
    """
    cfg = dict(DEFAULT_ZONE)
    cfg.update(zone or {})
    sign = side_sign(meshes, side)
    lo, hi = body_bbox(meshes)
    span = np.maximum(hi - lo, 1e-6)

    named = door_meshes(meshes, side)
    if named:
        cfg["z_min"], cfg["z_max"] = 0.0, 1.0

    out: list[np.ndarray] = []
    centres: list[np.ndarray] = []
    for mesh in named or meshes:
        pos = np.asarray(mesh.positions, dtype=np.float32)
        nrm = np.asarray(mesh.normals, dtype=np.float32)
        uv = np.asarray(mesh.uvs, dtype=np.float32)
        idx = np.asarray(mesh.indices, dtype=np.int64)
        if idx.size < 3 or pos.size == 0:
            continue
        idx = idx[: (idx.size // 3) * 3].reshape(-1, 3)
        if idx.max() >= len(pos) or idx.max() >= len(uv):
            continue

        centre = pos[idx].mean(axis=1)
        normal = nrm[idx].mean(axis=1)
        y_frac = (centre[:, 1] - lo[1]) / span[1]
        z_frac = (centre[:, 2] - lo[2]) / span[2]
        x_frac = (centre[:, 0] * sign) / max(abs(lo[0]), abs(hi[0]), 1e-6)

        keep = (
            (normal[:, 0] * sign >= cfg["normal_x_min"])
            & (x_frac >= cfg["x_frac_min"])
            & (y_frac >= cfg["y_min"])
            & (y_frac <= cfg["y_max"])
            & (z_frac >= cfg["z_min"])
            & (z_frac <= cfg["z_max"])
        )
        if not keep.any():
            continue
        out.append(uv[idx[keep]])
        centres.append(centre[keep])

    if not out:
        return np.zeros((0, 3, 2), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)
    return np.concatenate(out), np.concatenate(centres)


def select_door_island(
    mask: np.ndarray,
    tris: np.ndarray,
    centres: np.ndarray,
    size: tuple[int, int],
    meshes: list[kn5.Mesh],
    *,
    min_relative_area: float = 0.25,
) -> np.ndarray:
    """Narrow a side mask to the single UV island that is the door.

    The side of a car reaches the texture as several islands — door, front
    fender, rear quarter, sill — and treating them as one region gives a badge
    wherever the union happens to be widest, which is usually neither centred
    nor large. Doors sit at the middle of the wheelbase, so among the islands
    big enough to matter we take the one nearest the car's mid-length.
    """
    labels, count = ndimage.label(mask)
    if count <= 1 or not len(tris):
        return mask

    areas = ndimage.sum(mask, labels, range(1, count + 1))
    threshold = float(areas.max()) * min_relative_area

    w, h = size
    u = np.clip((tris[..., 0].mean(axis=1) * w).astype(int), 0, w - 1)
    v = np.clip((_flip_v(tris[..., 1]).mean(axis=1) * h).astype(int), 0, h - 1)
    tri_label = labels[v, u]

    lo, hi = body_bbox(meshes)
    mid_z = (float(lo[2]) + float(hi[2])) / 2.0

    best: tuple[float, int] | None = None
    for index in range(1, count + 1):
        if areas[index - 1] < threshold:
            continue
        owned = tri_label == index
        if not owned.any():
            continue
        offset = abs(float(centres[owned][:, 2].mean()) - mid_z)
        if best is None or offset < best[0]:
            best = (offset, index)

    return mask if best is None else (labels == best[1])


def uv_to_pixels(tris: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    w, h = size
    px = tris[..., 0] * w
    py = _flip_v(tris[..., 1]) * h
    return np.stack([px, py], axis=-1)


def uv_mask(tris: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Rasterize UV triangles into a boolean mask of the texture."""
    from PIL import Image, ImageDraw

    w, h = size
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)
    if tris.size:
        pix = uv_to_pixels(tris, size)
        for tri in pix:
            draw.polygon([tuple(p) for p in tri], fill=255)
    return np.asarray(img) > 0


def distance_inside(mask: np.ndarray) -> np.ndarray:
    """Chebyshev-ish distance to the nearest outside pixel (2-pass chamfer)."""
    big = float(mask.size)
    dist = np.where(mask, big, 0.0).astype(np.float32)
    h, w = dist.shape
    for y in range(h):
        row = dist[y]
        prev = dist[y - 1] if y > 0 else None
        for x in range(w):
            if row[x] == 0.0:
                continue
            best = row[x]
            if x > 0:
                best = min(best, row[x - 1] + 1.0)
            if prev is not None:
                best = min(best, prev[x] + 1.0)
                if x > 0:
                    best = min(best, prev[x - 1] + 1.4)
                if x + 1 < w:
                    best = min(best, prev[x + 1] + 1.4)
            row[x] = best
    for y in range(h - 1, -1, -1):
        row = dist[y]
        nxt = dist[y + 1] if y + 1 < h else None
        for x in range(w - 1, -1, -1):
            if row[x] == 0.0:
                continue
            best = row[x]
            if x + 1 < w:
                best = min(best, row[x + 1] + 1.0)
            if nxt is not None:
                best = min(best, nxt[x] + 1.0)
                if x + 1 < w:
                    best = min(best, nxt[x + 1] + 1.4)
                if x > 0:
                    best = min(best, nxt[x - 1] + 1.4)
            row[x] = best
    return dist


def mask_centroid(mask: np.ndarray) -> tuple[float, float]:
    """Centre of a UV island, in pixels."""
    ys, xs = np.nonzero(mask)
    if not len(ys):
        raise ValueError("empty mask")
    return float(xs.mean()), float(ys.mean())


def best_spot(
    mask: np.ndarray,
    *,
    downscale: int = 4,
    max_diameter: int | None = None,
    prefer: tuple[float, float] | None = None,
    clearance: float = 0.85,
) -> Spot:
    """Largest circle that fits inside the mask, biased toward ``prefer``.

    The single roomiest point on a door island sits wherever the outline happens
    to bulge, which on the Miata is toward the front of the door. Race numbers
    belong in the middle of the door, so among the spots that still take most of
    the available diameter, take the one nearest the island's centre.
    """
    if not mask.any():
        raise ValueError("empty door mask — widen the zone in the car profile")

    small = mask[::downscale, ::downscale]
    dist = distance_inside(small)
    peak = float(dist.max())

    if prefer is not None and peak > 0:
        roomy = np.argwhere(dist >= peak * clearance)
        target = np.array([prefer[1] / downscale, prefer[0] / downscale])
        cy_s, cx_s = (int(v) for v in roomy[np.argmin(((roomy - target) ** 2).sum(axis=1))])
    else:
        cy_s, cx_s = divmod(int(dist.argmax()), dist.shape[1])
    radius_s = float(dist[cy_s, cx_s])

    cx = int(cx_s * downscale + downscale // 2)
    cy = int(cy_s * downscale + downscale // 2)
    diameter = max(8, int(radius_s * downscale * 1.6))
    if max_diameter:
        diameter = min(diameter, max_diameter)

    inside = _circle_inside_ratio(mask, (cx, cy), diameter)
    return Spot(center=(cx, cy), diameter=diameter, inside_ratio=inside)


def circle_pixels(center: tuple[int, int], diameter: int, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    h, w = shape
    cx, cy = center
    r = diameter / 2.0
    y0, y1 = max(0, int(cy - r) - 1), min(h, int(cy + r) + 2)
    x0, x1 = max(0, int(cx - r) - 1), min(w, int(cx + r) + 2)
    ys, xs = np.mgrid[y0:y1, x0:x1]
    inside = (xs - cx) ** 2 + (ys - cy) ** 2 <= r * r
    return ys[inside], xs[inside]


def _circle_inside_ratio(mask: np.ndarray, center: tuple[int, int], diameter: int) -> float:
    ys, xs = circle_pixels(center, diameter, mask.shape)
    if ys.size == 0:
        return 0.0
    return float(mask[ys, xs].mean())


@dataclass
class IslandAxes:
    """Texture-space directions for 'along the car' and 'up', at one spot.

    UV islands are packed at whatever rotation fits, and the two doors are often
    packed differently from each other, so a badge drawn axis-aligned can come
    out mirrored or upside down on the car. These axes say how to orient it.
    """

    right: tuple[float, float]
    up: tuple[float, float]
    quality: float

    @property
    def usable(self) -> bool:
        return self.quality >= 0.5


def island_axes(
    meshes: list[kn5.Mesh],
    center: tuple[int, int],
    diameter: int,
    size: tuple[int, int],
    *,
    sign: float,
) -> IslandAxes:
    """Fit texture-space axes for the car's screen-right and up at a spot.

    Viewed from outside, screen-right is +Z on the +X flank and -Z on the -X
    flank, so ``sign`` orients the fit to the side being painted.
    """
    w, h = size
    cx, cy = center
    reach = max(diameter, 32) * 1.2

    world_right = screen_right(sign)
    world_up = np.array([0.0, 1.0, 0.0], dtype=np.float64)

    right_acc = np.zeros(2)
    up_acc = np.zeros(2)
    weight = 0.0

    for mesh in meshes:
        uv = np.asarray(mesh.uvs, dtype=np.float64)
        pos = np.asarray(mesh.positions, dtype=np.float64)
        idx = np.asarray(mesh.indices, dtype=np.int64)
        if idx.size < 3 or pos.size == 0:
            continue
        idx = idx[: (idx.size // 3) * 3].reshape(-1, 3)
        if idx.max() >= len(uv) or idx.max() >= len(pos):
            continue
        u = uv[idx][..., 0] * w
        v = _flip_v(uv[idx][..., 1]) * h
        hit = ((u.mean(axis=1) - cx) ** 2 + (v.mean(axis=1) - cy) ** 2) <= reach * reach
        if not hit.any():
            continue

        tri_pos = pos[idx[hit]]
        tri_tex = np.stack([u[hit], v[hit]], axis=-1)
        for p3, t2 in zip(tri_pos, tri_tex):
            # Within a triangle the surface-to-texture map is exactly affine, so
            # solve for the texture direction of each world direction instead of
            # regressing over a curved patch (which shears the result).
            edges = np.stack([p3[1] - p3[0], p3[2] - p3[0]], axis=1)  # 3x2
            tex_edges = np.stack([t2[1] - t2[0], t2[2] - t2[0]], axis=1)  # 2x2
            area = abs(float(np.linalg.det(tex_edges)))
            if area < 1e-9:
                continue
            try:
                coeffs, *_ = np.linalg.lstsq(
                    edges, np.stack([world_right, world_up], axis=1), rcond=None
                )
            except np.linalg.LinAlgError:
                continue
            mapped = tex_edges @ coeffs  # 2x2: columns are right, up in texture px
            r_vec, u_vec = mapped[:, 0], mapped[:, 1]
            r_n, u_n = float(np.hypot(*r_vec)), float(np.hypot(*u_vec))
            if r_n < 1e-9 or u_n < 1e-9:
                continue
            right_acc += (r_vec / r_n) * area
            up_acc += (u_vec / u_n) * area
            weight += area

    if weight <= 0.0:
        return IslandAxes((1.0, 0.0), (0.0, -1.0), 0.0)

    right_hat = right_acc / weight
    up_hat = up_acc / weight
    quality = min(float(np.hypot(*right_hat)), float(np.hypot(*up_hat)))
    r_n, u_n = float(np.hypot(*right_hat)), float(np.hypot(*up_hat))
    if r_n < 1e-6 or u_n < 1e-6:
        return IslandAxes((1.0, 0.0), (0.0, -1.0), 0.0)
    right_hat = right_hat / r_n
    up_hat = up_hat / u_n

    # Keep the badge square: orthogonalise 'up' against 'right' rather than
    # shearing the artwork to match an anisotropic island.
    up_hat = up_hat - right_hat * float(np.dot(up_hat, right_hat))
    n = float(np.hypot(*up_hat))
    if n < 1e-6:
        return IslandAxes((1.0, 0.0), (0.0, -1.0), 0.0)
    up_hat = up_hat / n

    return IslandAxes(
        right=(float(right_hat[0]), float(right_hat[1])),
        up=(float(up_hat[0]), float(up_hat[1])),
        quality=quality,
    )


def render_side(
    model: kn5.Model,
    meshes: list[kn5.Mesh],
    texture,
    *,
    side: str = "left",
    width: int = 900,
    background: tuple[int, int, int] = (28, 30, 34),
):
    """Orthographic side render of the body sampling the given texture."""
    from PIL import Image

    tex = texture.convert("RGB")
    tex_arr = np.asarray(tex).astype(np.uint8)
    th, tw = tex_arr.shape[:2]

    lo, hi = body_bbox(meshes)
    z_span = max(hi[2] - lo[2], 1e-6)
    y_span = max(hi[1] - lo[1], 1e-6)
    height = max(64, int(width * y_span / z_span))
    scale = width / z_span

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[:, :] = background
    depth = np.full((height, width), -np.inf, dtype=np.float32)
    sign = side_sign(meshes, side)

    for mesh in meshes:
        pos = np.asarray(mesh.positions, dtype=np.float32)
        nrm = np.asarray(mesh.normals, dtype=np.float32)
        uv = np.asarray(mesh.uvs, dtype=np.float32)
        idx = np.asarray(mesh.indices, dtype=np.int64)
        if idx.size < 3 or pos.size == 0:
            continue
        idx = idx[: (idx.size // 3) * 3].reshape(-1, 3)
        if idx.max() >= len(pos) or idx.max() >= len(uv):
            continue
        facing = nrm[idx].mean(axis=1)[:, 0] * sign > 0
        idx = idx[facing]
        if not len(idx):
            continue

        tri_pos = pos[idx]
        tri_uv = uv[idx]
        # Screen: x from -z (front right for left side), y from -height
        # Screen right is -Z on the +X flank and +Z on the -X flank.
        sx = (hi[2] - tri_pos[..., 2]) * scale
        sy = (hi[1] - tri_pos[..., 1]) * scale
        if sign < 0:
            sx = width - sx
        tri_depth = tri_pos[..., 0].mean(axis=1) * sign

        for tri_i in range(len(idx)):
            _raster_tri(
                canvas,
                depth,
                sx[tri_i],
                sy[tri_i],
                tri_uv[tri_i],
                float(tri_depth[tri_i]),
                tex_arr,
                tw,
                th,
            )

    return Image.fromarray(canvas)


def _raster_tri(canvas, depth, sx, sy, uv, tri_depth, tex_arr, tw, th) -> None:
    h, w = depth.shape
    x0 = max(0, int(np.floor(sx.min())))
    x1 = min(w, int(np.ceil(sx.max())) + 1)
    y0 = max(0, int(np.floor(sy.min())))
    y1 = min(h, int(np.ceil(sy.max())) + 1)
    if x1 <= x0 or y1 <= y0:
        return

    ax, ay = sx[0], sy[0]
    bx, by = sx[1], sy[1]
    cx, cy = sx[2], sy[2]
    det = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
    if abs(det) < 1e-9:
        return

    ys, xs = np.mgrid[y0:y1, x0:x1]
    px = xs + 0.5
    py = ys + 0.5
    w1 = ((px - ax) * (cy - ay) - (cx - ax) * (py - ay)) / det
    w2 = ((bx - ax) * (py - ay) - (px - ax) * (by - ay)) / det
    w0 = 1.0 - w1 - w2
    inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
    if not inside.any():
        return

    closer = inside & (tri_depth > depth[y0:y1, x0:x1])
    if not closer.any():
        return

    u = w0 * uv[0, 0] + w1 * uv[1, 0] + w2 * uv[2, 0]
    v = w0 * uv[0, 1] + w1 * uv[1, 1] + w2 * uv[2, 1]
    tx = np.clip((u * tw).astype(np.int32), 0, tw - 1)
    ty = np.clip((_flip_v(v) * th).astype(np.int32), 0, th - 1)

    sub_canvas = canvas[y0:y1, x0:x1]
    sub_depth = depth[y0:y1, x0:x1]
    sub_canvas[closer] = tex_arr[ty[closer], tx[closer]]
    sub_depth[closer] = tri_depth
