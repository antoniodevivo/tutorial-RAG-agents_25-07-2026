"""Entrypoint del modulo.

Uso:
    python -m src.main --pdf2md
"""

import argparse
from scripts.chunking_simple import generate_chunks_for_all_md
from scripts.pdf2md import convert_all_pdfs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Utility del modulo.")
    parser.add_argument(
        "--pdf2md",
        action="store_true",
        help="Converte tutti i PDF in docs/pdf in file Markdown in docs/md.",
    )
    parser.add_argument(
        "--gchunks",
        action="store_true",
        help="Applica le due strategie di chunking e scrive i JSONL in docs/chunks.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.pdf2md:
        convert_all_pdfs()

    if args.gchunks:
        generate_chunks_for_all_md()


if __name__ == "__main__":
    main()
