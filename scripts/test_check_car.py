import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_car import check_folder, kn5_has_node


def _kn5(textures: list[tuple[bytes, bytes]], nodes: list[bytes]) -> bytes:
    buf = bytearray(b"sc6969")
    buf += struct.pack("<I", 5)
    buf += struct.pack("<I", len(textures))
    for name, blob in textures:
        buf += struct.pack("<I", 1)
        buf += struct.pack("<I", len(name)) + name
        buf += struct.pack("<I", len(blob)) + blob
    buf += struct.pack("<I", 0)  # materials
    for name in nodes:
        buf += struct.pack("<I", len(name)) + name
    return bytes(buf)


def _dds(fourcc: bytes, width: int, height: int) -> bytes:
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<I", header, 12, height)
    struct.pack_into("<I", header, 16, width)
    struct.pack_into("<I", header, 80, 4)
    header[84:88] = fourcc
    return bytes(header) + b"\x00" * 16


class CheckCarTests(unittest.TestCase):
    def test_kn5_has_node_uses_length_prefix(self):
        data = struct.pack("<I", 6) + b"RIM_LF"
        self.assertTrue(kn5_has_node(data, "RIM_LF"))
        self.assertFalse(kn5_has_node(b"RIM_LF", "RIM_LF"))

    def test_dx10_texture_is_an_error(self):
        with tempfile.TemporaryDirectory() as raw:
            car = Path(raw)
            (car / "body.kn5").write_bytes(_kn5([(b"btn.dds", _dds(b"DX10", 64, 64))], [b"WHEEL_LF"]))
            issues = check_folder(car)
        self.assertTrue(any("DX10" in i.message for i in issues if i.level == "error"))

    def test_blurred_object_must_exist_in_kn5(self):
        with tempfile.TemporaryDirectory() as raw:
            car = Path(raw)
            (car / "data").mkdir()
            (car / "data" / "blurred_objects.ini").write_text(
                "[OBJECT_0]\nNAME=RIM_LF\n", encoding="ascii"
            )
            (car / "body.kn5").write_bytes(_kn5([], [b"WHEEL_LF"]))
            issues = check_folder(car)
        self.assertTrue(any("RIM_LF" in i.message for i in issues if i.level == "error"))


if __name__ == "__main__":
    unittest.main()
