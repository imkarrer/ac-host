"""Minimal KN5 reader: textures, materials, and mesh UVs.

Used to answer two questions automatically, with no CM/AC load:

1. Which texture file does a body/door mesh actually sample? (skin override name)
2. Where on that texture does the door live? (UV triangles → placement mask)

Format reference: AcTools Kn5Reader. Node classes: 1 dummy, 2 mesh, 3 skinned mesh.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"sc6969"
VERTEX_SIZE = 44  # pos 3f, normal 3f, uv 2f, tangent 3f
SKINNED_VERTEX_SIZE = VERTEX_SIZE + 32  # + weights 4f + bone ids 4f

NODE_DUMMY = 1
NODE_MESH = 2
NODE_SKINNED_MESH = 3


@dataclass
class Material:
    name: str
    shader: str
    props: dict[str, float] = field(default_factory=dict)
    slots: dict[str, str] = field(default_factory=dict)

    def diffuse_texture(self) -> str:
        for key in ("txDiffuse", "txDiffuseMap", "txDetail", "txVariation"):
            if self.slots.get(key):
                return self.slots[key]
        for value in self.slots.values():
            if value:
                return value
        return ""


@dataclass
class Mesh:
    name: str
    material_id: int
    uvs: list[tuple[float, float]]
    indices: list[int]
    visible: bool
    transparent: bool
    path: str = ""
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        return len(self.indices) // 3

    def uv_triangles(self) -> list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]]:
        tris = []
        n = len(self.uvs)
        for i in range(0, len(self.indices) - 2, 3):
            a, b, c = self.indices[i], self.indices[i + 1], self.indices[i + 2]
            if a < n and b < n and c < n:
                tris.append((self.uvs[a], self.uvs[b], self.uvs[c]))
        return tris

    def uv_bbox(self) -> tuple[float, float, float, float] | None:
        if not self.uvs:
            return None
        us = [u for u, _ in self.uvs]
        vs = [v for _, v in self.uvs]
        return (min(us), min(vs), max(us), max(vs))


@dataclass
class Model:
    version: int
    textures: dict[str, bytes]
    materials: list[Material]
    meshes: list[Mesh]
    trailing_bytes: int = 0

    def material_for(self, mesh: Mesh) -> Material | None:
        if 0 <= mesh.material_id < len(self.materials):
            return self.materials[mesh.material_id]
        return None

    def texture_for(self, mesh: Mesh) -> str:
        mat = self.material_for(mesh)
        return mat.diffuse_texture() if mat else ""


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def read(self, n: int) -> bytes:
        chunk = self.data[self.pos : self.pos + n]
        if len(chunk) != n:
            raise EOFError(f"kn5 truncated at {self.pos} (+{n})")
        self.pos += n
        return chunk

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.read(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.read(4))[0]

    def string(self) -> str:
        n = self.u32()
        return self.read(n).decode("utf-8", "replace")

    def skip(self, n: int) -> None:
        self.read(n)

    @property
    def remaining(self) -> int:
        return len(self.data) - self.pos


def read_kn5(path: Path, *, want_uvs: bool = True) -> Model:
    r = _Reader(Path(path).read_bytes())
    if r.read(6) != MAGIC:
        raise ValueError(f"not a kn5: {path}")
    version = r.u32()
    if version > 5:
        r.u32()  # extra version

    textures: dict[str, bytes] = {}
    for _ in range(r.u32()):
        r.u32()  # active flag
        name = r.string()
        size = r.u32()
        textures[name] = r.read(size)

    materials: list[Material] = []
    for _ in range(r.u32()):
        name = r.string()
        shader = r.string()
        r.u8()  # blend mode
        r.u8()  # alpha tested
        if version > 4:
            r.u32()  # depth mode
        props: dict[str, float] = {}
        for _ in range(r.u32()):
            pname = r.string()
            values = struct.unpack("<10f", r.read(40))
            props[pname] = values[0]
        slots: dict[str, str] = {}
        for _ in range(r.u32()):
            sname = r.string()
            r.u32()  # slot index
            slots[sname] = r.string()
        materials.append(Material(name=name, shader=shader, props=props, slots=slots))

    meshes: list[Mesh] = []
    _read_node(r, meshes, want_uvs=want_uvs, parents=())
    return Model(
        version=version,
        textures=textures,
        materials=materials,
        meshes=meshes,
        trailing_bytes=r.remaining,
    )


def _read_node(r: _Reader, out: list[Mesh], *, want_uvs: bool, parents: tuple[str, ...]) -> None:
    node_class = r.u32()
    name = r.string()
    children = r.u32()
    r.u8()  # active

    if node_class == NODE_DUMMY:
        r.skip(64)  # transform matrix
    elif node_class in (NODE_MESH, NODE_SKINNED_MESH):
        r.u8()  # cast shadows
        visible = bool(r.u8())
        transparent = bool(r.u8())

        if node_class == NODE_SKINNED_MESH:
            for _ in range(r.u32()):
                r.string()
                r.skip(64)
            stride = SKINNED_VERTEX_SIZE
        else:
            stride = VERTEX_SIZE

        vcount = r.u32()
        uvs: list[tuple[float, float]] = []
        positions: list[tuple[float, float, float]] = []
        normals: list[tuple[float, float, float]] = []
        if want_uvs:
            blob = r.read(vcount * stride)
            for i in range(vcount):
                base = i * stride
                positions.append(struct.unpack_from("<3f", blob, base))
                normals.append(struct.unpack_from("<3f", blob, base + 12))
                uvs.append(struct.unpack_from("<2f", blob, base + 24))
        else:
            r.skip(vcount * stride)

        icount = r.u32()
        idx_blob = r.read(icount * 2)
        indices = list(struct.unpack_from(f"<{icount}H", idx_blob, 0)) if icount else []

        material_id = r.u32()
        r.u32()  # layer
        r.f32()  # lod in
        r.f32()  # lod out
        if node_class == NODE_MESH:
            r.skip(12)  # bounding sphere center
            r.f32()  # bounding sphere radius
            r.u8()  # is renderable

        out.append(
            Mesh(
                name=name,
                material_id=material_id,
                uvs=uvs,
                indices=indices,
                visible=visible,
                transparent=transparent,
                path="/".join(parents + (name,)),
                positions=positions,
                normals=normals,
            )
        )
    else:
        raise ValueError(f"unknown kn5 node class {node_class} at {r.pos}")

    for _ in range(children):
        _read_node(r, out, want_uvs=want_uvs, parents=parents + (name,))
