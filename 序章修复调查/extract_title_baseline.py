"""Read the pinned game archives and save diagnostic copies only; no installation."""
from pathlib import Path
import hashlib
import json
import struct
import zlib

GAME = Path("D:/STEAM__/steamapps/common/Marvel's Spider-Man Remastered")
OUTPUT = Path(__file__).resolve().parent / "原始UI基线"
TOC_HASH = "58e571cf1e54e08b18db4e8effb3f964eded1ddaa3e4feebd72f88fbbc066da1"
HUD_HASH = "b230d7b810680030cf24a3265e25ed43e099183f13ad5805243ecc6722782feb"


def asset_hash(path):
    table = []
    for number in range(256):
        value = number
        for _ in range(8):
            value = (value >> 1) ^ (0xC96C5795D7870F42 if value & 1 else 0)
        table.append(value)
    value = 0xC96C5795D7870F42
    for byte in path.replace("\\", "/").lower().encode("utf8"):
        value = (value >> 8) ^ table[(value ^ byte) & 255]
    return (value >> 2) | 0x8000000000000000


def lz4(data, expected):
    result = bytearray()
    pos = 0
    while pos < len(data):
        token = data[pos]
        pos += 1
        literals = token >> 4
        if literals == 15:
            while True:
                extra = data[pos]
                pos += 1
                literals += extra
                if extra != 255:
                    break
        if pos + literals > len(data):
            raise ValueError("Truncated LZ4 literals")
        result.extend(data[pos:pos + literals])
        pos += literals
        if pos == len(data):
            break
        distance = int.from_bytes(data[pos:pos + 2], "little")
        pos += 2
        if not distance or distance > len(result):
            raise ValueError("Invalid LZ4 distance")
        count = token & 15
        if count == 15:
            while True:
                extra = data[pos]
                pos += 1
                count += extra
                if extra != 255:
                    break
        count += 4
        if len(result) + count > expected:
            raise ValueError("LZ4 output exceeds block size")
        for _ in range(count):
            result.append(result[-distance])
    if len(result) != expected:
        raise ValueError("LZ4 output length mismatch")
    return bytes(result)


def read_range(archive, offset, size):
    with archive.open("rb") as stream:
        header = stream.read(32)
        if header[:4] != b"DSAR":
            stream.seek(offset)
            data = stream.read(size)
            if len(data) != size:
                raise ValueError("Truncated archive")
            return data
        table_end = struct.unpack_from("<I", header, 12)[0]
        if table_end < 32 or (table_end - 32) % 32:
            raise ValueError("Invalid DSAR block table")
        table = stream.read(table_end - 32)
        result = bytearray()
        for pos in range(0, len(table), 32):
            real, compressed, real_size, compressed_size, kind = struct.unpack_from("<QQIIB", table, pos)
            if real >= offset + size or real + real_size <= offset:
                continue
            stream.seek(compressed)
            raw = stream.read(compressed_size)
            if kind != 3:
                raise ValueError(f"Unsupported compression type {kind}; no external decoder installed")
            block = lz4(raw, real_size)
            result.extend(block[max(0, offset - real):min(real_size, offset + size - real)])
        if len(result) != size:
            raise ValueError("Extracted asset length mismatch")
        return bytes(result)


def main():
    toc_path = GAME / "asset_archive" / "toc"
    packed = toc_path.read_bytes()
    if hashlib.sha256(packed).hexdigest() != TOC_HASH:
        raise ValueError("Game TOC changed from the audited baseline")
    toc = zlib.decompressobj().decompress(packed[8:])
    if toc[:4] != b"1TAD" or len(toc) != struct.unpack_from("<I", packed, 4)[0]:
        raise ValueError("Invalid TOC header/size")
    count = struct.unpack_from("<I", toc, 12)[0]
    sections = {tag: (offset, size) for tag, offset, size in
                (struct.unpack_from("<III", toc, 16 + index * 12) for index in range(count))}
    ids_offset, ids_size = sections[0x506D7B8A]
    records_offset, _ = sections[0x65BCF461]
    locations_offset, _ = sections[0xDCD720B5]
    entries = []
    for path, expected in (("ui/export/HUD.gfx", HUD_HASH), ("ui/export/lobby/Title.gfx", None)):
        key = asset_hash(path)
        pos = toc.find(struct.pack("<Q", key), ids_offset, ids_offset + ids_size)
        if pos < 0 or (pos - ids_offset) % 8:
            raise ValueError(f"Asset ID not found/aligned: {path}")
        index = (pos - ids_offset) // 8
        _, size, location = struct.unpack_from("<III", toc, records_offset + index * 12)
        archive_id, offset = struct.unpack_from("<II", toc, locations_offset + location * 8)
        archive = GAME / "asset_archive" / f"g00s{archive_id:03d}"
        data = read_range(archive, offset, size)
        digest = hashlib.sha256(data).hexdigest()
        if expected and digest != expected:
            raise ValueError("Independent HUD baseline verification failed")
        target = OUTPUT / Path(path).name
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError("Diagnostic output already exists with different contents; refusing overwrite")
        else:
            with target.open("xb") as stream:
                stream.write(data)
        entries.append({"asset_path": path, "asset_id": f"{key:016X}", "toc_index": index,
                        "archive": archive.name, "offset": offset, "size": size,
                        "sha256": digest, "output_path": str(target)})
    if toc_path.read_bytes() != packed:
        raise ValueError("TOC changed during extraction")
    record = {"toc_sha256": TOC_HASH, "decompressed_toc_length": len(toc), "assets": entries,
              "format_reference": "https://github.com/Tkachov/Overstrike/tree/main/DAT1",
              "operation": "read-only archive extraction to diagnostic directory; no deployment"}
    target = OUTPUT / "Title提取来源.json"
    with target.open("w", encoding="utf8", newline="\n") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
