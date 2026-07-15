"""AEC raw-binary disassembler."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct
import sys

from .isa import PROFILES, TRACK_B_V1, bytes_to_words, decode_instruction, words_to_msb_hex


AECI_MAGIC = 0x49434541


def disassemble(blob: bytes, profile_name: str = TRACK_B_V1.name) -> list[str]:
    profile = PROFILES[profile_name]
    offset = 0
    if len(blob) >= 64:
        magic = struct.unpack_from("<I", blob, 0)[0]
        if magic == AECI_MAGIC:
            header_bytes = struct.unpack_from("<I", blob, 12)[0]
            offset = header_bytes
    words = bytes_to_words(blob[offset:])
    lines: list[str] = []
    for pc, inst_words in enumerate(words):
        lines.append(f"{pc:04d}: {words_to_msb_hex(inst_words)}    {decode_instruction(inst_words, profile)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aec-objdump")
    parser.add_argument("input", type=Path)
    parser.add_argument("--profile", choices=sorted(PROFILES), default=TRACK_B_V1.name)
    args = parser.parse_args(argv)

    try:
        for line in disassemble(args.input.read_bytes(), args.profile):
            print(line)
    except (OSError, ValueError) as exc:
        print(f"aec-objdump: error: {exc}", file=sys.stderr)
        return 1
    return 0
