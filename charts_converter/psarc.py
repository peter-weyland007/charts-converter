from __future__ import annotations

import fnmatch
import struct
import zlib
from pathlib import Path

try:
    from Crypto.Cipher import AES
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("pycryptodome is required for PSARC decryption") from exc

MAGIC = b"PSAR"
ARC_KEY = bytes.fromhex(
    "C53DB23870A1A2F71CAE64061FDD0E1157309DC85204D4C5BFDF25090DF2572C"
)
ARC_IV = bytes.fromhex("E915AA018FEF71FC508132E4BB4CEB42")


def _decrypt_toc(data: bytes) -> bytes:
    aes = AES.new(ARC_KEY, AES.MODE_CFB, iv=ARC_IV, segment_size=128)
    return aes.decrypt(data)


def _extract_entry(handle, entry: dict, block_sizes: list[int], block_size: int) -> bytes:
    handle.seek(entry["offset"])
    if entry["length"] == 0:
        return b""

    num_blocks = (entry["length"] + block_size - 1) // block_size
    result = b""
    for i in range(num_blocks):
        bi = entry["z_index"] + i
        compressed_size = block_sizes[bi] if bi < len(block_sizes) else 0
        if compressed_size == 0:
            remaining = entry["length"] - len(result)
            result += handle.read(min(block_size, remaining))
        else:
            block_data = handle.read(compressed_size)
            try:
                result += zlib.decompress(block_data)
            except zlib.error:
                result += block_data
    return result[: entry["length"]]


def parse_toc(handle):
    magic = handle.read(4)
    if magic != MAGIC:
        raise ValueError("Not a PSARC file")

    handle.read(4)  # version
    handle.read(4)  # compression
    toc_length = struct.unpack(">I", handle.read(4))[0]
    toc_entry_size = struct.unpack(">I", handle.read(4))[0]
    toc_entries = struct.unpack(">I", handle.read(4))[0]
    block_size = struct.unpack(">I", handle.read(4))[0]
    archive_flags = struct.unpack(">I", handle.read(4))[0]

    toc_region_size = toc_length - 32
    toc_region_raw = handle.read(toc_region_size)
    toc_region = _decrypt_toc(toc_region_raw) if archive_flags == 4 else toc_region_raw

    toc_data_size = toc_entry_size * toc_entries
    toc_data = toc_region[:toc_data_size]
    bt_data = toc_region[toc_data_size:]

    entries = []
    for i in range(toc_entries):
        off = i * toc_entry_size
        ed = toc_data[off : off + toc_entry_size]
        entries.append(
            {
                "z_index": struct.unpack(">I", ed[16:20])[0],
                "length": int.from_bytes(ed[20:25], "big"),
                "offset": int.from_bytes(ed[25:30], "big"),
            }
        )

    block_sizes = [int.from_bytes(bt_data[i * 2 : i * 2 + 2], "big") for i in range(len(bt_data) // 2)]
    file_list_data = _extract_entry(handle, entries[0], block_sizes, block_size)
    filenames = (
        file_list_data.decode("utf-8", errors="ignore")
        .replace("\r\n", "\n")
        .strip()
        .split("\n")
    )
    return entries, filenames, block_sizes, block_size


def list_entries(filepath: str | Path) -> list[str]:
    with open(filepath, "rb") as handle:
        entries, filenames, _block_sizes, _block_size = parse_toc(handle)
        return [name.strip() for _entry, name in zip(entries[1:], filenames) if name.strip()]


def read_entries(filepath: str | Path, patterns: list[str] | None = None) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    with open(filepath, "rb") as handle:
        entries, filenames, block_sizes, block_size = parse_toc(handle)
        for entry, filename in zip(entries[1:], filenames):
            filename = filename.strip()
            if not filename:
                continue
            if patterns and not any(fnmatch.fnmatch(filename.lower(), p.lower()) for p in patterns):
                continue
            result[filename] = _extract_entry(handle, entry, block_sizes, block_size)
    return result


def unpack_psarc(filepath: str | Path, output_dir: str | Path) -> list[str]:
    extracted: list[str] = []
    out = Path(output_dir)
    with open(filepath, "rb") as handle:
        entries, filenames, block_sizes, block_size = parse_toc(handle)
        for entry, filename in zip(entries[1:], filenames):
            filename = filename.strip()
            if not filename:
                continue
            outpath = out / filename
            outpath.parent.mkdir(parents=True, exist_ok=True)
            outpath.write_bytes(_extract_entry(handle, entry, block_sizes, block_size))
            extracted.append(str(outpath))
    return extracted
