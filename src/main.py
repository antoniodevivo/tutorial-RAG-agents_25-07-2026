"""Entrypoint del modulo.

Uso:
    python -m src.main --pdf2md
"""

import argparse
from scripts.chunking import generate_chunks, lonely_chunk_test
from scripts.pdf2md import convert_all_pdfs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Utility del modulo.")
    parser.add_argument(
        "--pdf2md",
        action="store_true",
        help="Converte tutti i PDF in docs/pdf in file Markdown in docs/md.",
    )
    parser.add_argument(
        "--chunk",
        action="store_true",
        help="Applica le due strategie di chunking e scrive i JSONL in docs/chunks.",
    )
    parser.add_argument(
        "--test-solitario",
        action="store_true",
        help="Estrae 10 chunk a caso per strategia per il test del chunk solitario.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.pdf2md:
        convert_all_pdfs()

    if args.chunk:
        generate_chunks()

    if args.test_solitario:
        lonely_chunk_test()


if __name__ == "__main__":
    main()
