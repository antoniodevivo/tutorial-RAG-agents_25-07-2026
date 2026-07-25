"""Entrypoint del modulo.

Uso (dalla radice del repo, non da src/):
    python -m src.main --pdf2md

`src` deve essere il pacchetto radice: i moduli sotto src/ si importano tra
loro con percorsi relativi (`from ..clients.ollama import oclient`), che
risalgono fino a `src` e non oltre. Lanciando da src/ quei percorsi escono
dal pacchetto e Python solleva `attempted relative import beyond top-level`.
"""

import argparse
from src.scripts.chunking_simple import generate_chunks_for_all_md
from src.scripts.pdf2md import convert_all_pdfs
from src.scripts.qdrant.ingestion import ingest_all_chunks


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
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Ingestisce i chunk in Qdrant.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.pdf2md:
        convert_all_pdfs()

    if args.gchunks:
        generate_chunks_for_all_md()

    if args.ingest:
        ingest_all_chunks()


if __name__ == "__main__":
    main()
