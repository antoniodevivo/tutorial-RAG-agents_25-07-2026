"""Entrypoint del modulo.

Uso:
    python -m src.main --pdf2md
"""

import argparse
from scripts.pdf2md import convert_all_pdfs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Utility del modulo.")
    parser.add_argument(
        "--pdf2md",
        action="store_true",
        help="Converte tutti i PDF in docs/pdf in file Markdown in docs/md.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.pdf2md:
        convert_all_pdfs()


if __name__ == "__main__":
    main()
