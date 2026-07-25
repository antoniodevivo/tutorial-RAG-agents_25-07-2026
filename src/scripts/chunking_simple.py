# Chunking dei Markdown in docs/md. Due strategie, entrambe eseguibili.
# Solo libreria standard: nessuna dipendenza esterna.

import json
import re
from datetime import date
from itertools import groupby
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PDF_DIR = BASE_DIR / "docs" / "pdf"
MD_DIR = BASE_DIR / "docs" / "md"
CHUNK_DIR = BASE_DIR / "docs" / "chunks"

MAX_TOKENS = 1200


def fixed_size_chunking(text, metadata=None):
    words = text.split()
    chunks = []
    current_chunk = []
    current_tokens = 0
    today = str(date.today())
    last_section = ""

    for word in words:
        current_tokens += len(word.split())
        if current_tokens <= MAX_TOKENS:
            current_chunk.append(word)
        else:
            chunks.append({
                "text": ' '.join(current_chunk),
                "metadata": {
                    "date": today,
                    "section": last_section,
                    **(metadata or {})
                },
            })
            current_chunk = [word]
            current_tokens = len(word.split())

    # Append the last chunk
    if current_chunk:
        chunks.append({
            "text": ' '.join(current_chunk),
            "metadata": {
                "date": today,
                "section": last_section,
                **(metadata or {})
            },
        })

    return chunks


def cut_from_structure(text, metadata=None):
    # Split the text into lines
    lines = text.splitlines()
    chunks = []
    current_chunk = []
    current_tokens = 0
    today = str(date.today())
    last_section = ""

    for line in lines:
        # Check for headings to update the last_section
        heading_match = re.match(r'^(#{1,6})\s+(.+)', line)
        if heading_match:
            last_section = heading_match.group(2)

        # Count tokens in the line
        line_tokens = len(line.split())
        if current_tokens + line_tokens <= MAX_TOKENS:
            current_chunk.append(line)
            current_tokens += line_tokens
        else:
            chunks.append({
                "text": '\n'.join(current_chunk),
                "metadata": {
                    "date": today,
                    "section": last_section,
                    **(metadata or {})
                },
            })
            current_chunk = [line]
            current_tokens = line_tokens

    # Append the last chunk
    if current_chunk:
        chunks.append({
            "text": '\n'.join(current_chunk),
            "metadata": {
                "date": today,
                "section": last_section,
                **(metadata or {})
            },
        })

    return chunks


CHUNKING_STRATEGIES = {"A": fixed_size_chunking, "B": cut_from_structure}


def generate_chunks(md_path) -> None:
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)

    if not md_path.exists():
        print(f"Nessun Markdown trovato in {md_path}")
        return

    for name, strategy in CHUNKING_STRATEGIES.items():
        out_path = CHUNK_DIR / f"chunks_{name}.jsonl"
        total = 0

        text = md_path.read_text(encoding="utf-8")
        with out_path.open("w", encoding="utf-8") as f:
            metadata = {
                "document": md_path.stem,
                "version": "???",
                "visibility": "public",
                "page": "???"
            }
            for chunk in strategy(text, metadata):
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                total += 1
        print(
            f"Strategia {name}: {total} chunk -> docs/chunks/{out_path.name}")
