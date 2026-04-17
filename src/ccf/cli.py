"""CCF v1 CLI — entry point for `python -m ccf` and the `ccf` script."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ccf import _structural_diff, compress, compress_file, restore, restore_file


def _ratio_str(original_len: int, compressed_len: int) -> str:
    ratio = original_len / compressed_len if compressed_len else 0
    return f"original {original_len}ch → compressed {compressed_len}ch ({ratio:.1f}×)"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ccf",
        description="CCF v1 — Causal Compact Format tool",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # compress
    cp = sub.add_parser("compress", help="Compress a .causal.json file to CCF v1")
    cp.add_argument("input", type=Path, metavar="input.causal.json")
    cp.add_argument("--out", type=Path, default=None, metavar="file.ccf")

    # restore
    rp = sub.add_parser("restore", help="Restore a .ccf file to .causal.json")
    rp.add_argument("input", type=Path, metavar="input.ccf")
    rp.add_argument("--out", type=Path, default=None, metavar="file.causal.json")

    # roundtrip
    rt = sub.add_parser(
        "roundtrip",
        help="Compress then restore and check structural equivalence (exits 0 if lossless)",
    )
    rt.add_argument("input", type=Path, metavar="input.causal.json")

    # ratio
    ra = sub.add_parser("ratio", help="Print compression ratio")
    ra.add_argument("input", type=Path, metavar="input.causal.json")

    args = parser.parse_args()

    if args.cmd == "compress":
        original_text = args.input.read_text(encoding="utf-8")
        result = compress(json.loads(original_text))
        if args.out:
            args.out.write_text(result, encoding="utf-8")
        else:
            print(result)
        print(_ratio_str(len(original_text), len(result)), file=sys.stderr)

    elif args.cmd == "restore":
        result_dict = restore_file(args.input)
        output = json.dumps(result_dict, indent=2, ensure_ascii=False)
        if args.out:
            args.out.write_text(output, encoding="utf-8")
        else:
            print(output)

    elif args.cmd == "roundtrip":
        original = json.loads(args.input.read_text(encoding="utf-8"))
        compressed = compress(original)
        restored = restore(compressed)
        diffs = _structural_diff(original, restored)
        if diffs:
            for d in diffs:
                print(d)
            sys.exit(1)
        else:
            print("Lossless roundtrip: OK")

    elif args.cmd == "ratio":
        original_text = args.input.read_text(encoding="utf-8")
        compressed = compress_file(args.input)
        print(_ratio_str(len(original_text), len(compressed)))


if __name__ == "__main__":
    main()
