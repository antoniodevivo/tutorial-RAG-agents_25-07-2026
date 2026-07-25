# Chunking dei Markdown in docs/md. Due strategie, entrambe eseguibili.
# Solo libreria standard: nessuna dipendenza esterna.

import json
import re
from datetime import date
from pathlib import Path
from typing import List
from ..models.validators.chunks import Chunk

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PDF_DIR = BASE_DIR / "docs" / "pdf"
MD_DIR = BASE_DIR / "docs" / "md"
CHUNK_DIR = BASE_DIR / "docs" / "chunks"

MAX_TOKENS = 1200

# Marcatore di pagina inserito da pdf2md prima di ogni pagina convertita.
PAGE_RE = re.compile(r"^<!--\s*pagina:\s*(\d+)\s*-->")
# Version nel nome del file: `..._v5.0.3` -> `5.0.3`.
VERSION_RE = re.compile(r"[_-]v(\d+(?:\.\d+)*)", re.IGNORECASE)


def doc_version(md_path):
    # Il Markdown non contiene la version: l'unica traccia è il nome del file.
    match = VERSION_RE.search(md_path.stem)
    return match.group(1) if match else "1.0"


def words_with_pages(text):
    # Scorre il testo parola per parola portandosi dietro la pagina di origine.
    # I marcatori vengono consumati qui, così non finiscono dentro i chunk.
    page = None
    for line in text.splitlines():
        marker = PAGE_RE.match(line)
        if marker:
            page = int(marker.group(1))
            continue
        for word in line.split():
            yield word, page


def fixed_size_chunking(text, metadata=None) -> List[Chunk]:
    chunks = []
    current_chunk = []
    current_tokens = 0
    today = str(date.today())
    last_section = ""
    chunk_page = None  # pagina in cui inizia il chunk in corso

    for word, page in words_with_pages(text):
        if not current_chunk:
            chunk_page = page

        current_tokens += 1
        if current_tokens <= MAX_TOKENS:
            current_chunk.append(word)
        else:
            chunks.append({
                "text": ' '.join(current_chunk),
                "metadata": {
                    "date": today,
                    "section": last_section,
                    "page": chunk_page,
                    **(metadata or {})
                },
            })
            current_chunk = [word]
            current_tokens = 1
            chunk_page = page

    # Append the last chunk
    if current_chunk:
        chunks.append({
            "text": ' '.join(current_chunk),
            "metadata": {
                "date": today,
                "section": last_section,
                "page": chunk_page,
                **(metadata or {})
            },
        })

    return chunks


def cut_from_structure(text, metadata=None) -> List[Chunk]:
    # Split the text into lines
    lines = text.splitlines()
    chunks = []
    current_chunk = []
    current_tokens = 0
    today = str(date.today())
    last_section = ""
    current_page = None  # pagina aperta dall'ultimo marcatore letto
    chunk_page = None  # pagina in cui inizia il chunk in corso

    for line in lines:
        # Il marcatore aggiorna la pagina e non entra nel testo
        marker = PAGE_RE.match(line)
        if marker:
            current_page = int(marker.group(1))
            continue

        # Check for headings to update the last_section
        heading_match = re.match(r'^(#{1,6})\s+(.+)', line)
        if heading_match:
            last_section = heading_match.group(2)

        if not current_chunk:
            # Le righe vuote non aprono un chunk: aspettando la prima riga di
            # testo la pagina è quella giusta anche se il marcatore viene dopo.
            if not line.strip():
                continue
            chunk_page = current_page

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
                    "page": chunk_page,
                    **(metadata or {})
                },
            })
            current_chunk = [line]
            current_tokens = line_tokens
            chunk_page = current_page

    # Append the last chunk
    if current_chunk:
        chunks.append({
            "text": '\n'.join(current_chunk),
            "metadata": {
                "date": today,
                "section": last_section,
                "page": chunk_page,
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

    md_name = md_path.name
    print(f"Generazione chunk per {md_name}...")

    for name, strategy in CHUNKING_STRATEGIES.items():
        out_path = CHUNK_DIR / f"md_{md_name}_chunks-{name}.jsonl"
        total = 0

        # first delete the file if it already exists to avoid appending to old data
        if out_path.exists():
            out_path.unlink()

        text = md_path.read_text(encoding="utf-8")
        with out_path.open("w", encoding="utf-8") as f:
            # Solo i metadati comuni a tutto il document: `page` varia da
            # chunk a chunk, la calcola la strategia leggendo i marcatori.
            metadata = {
                "document": md_path.stem,
                "version": doc_version(md_path),
                "visibility": "public",
            }
            for chunk in strategy(text, metadata):
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                total += 1
        print(
            f"Strategia {name}: {total} chunk -> docs/chunks/{out_path.name}")


def generate_chunks_for_all_md() -> None:
    for md_path in MD_DIR.glob("*.md"):
        generate_chunks(md_path)
