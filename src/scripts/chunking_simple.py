# Chunking dei Markdown in docs/md. Due strategie, entrambe eseguibili.
# Il chunker produce il chunk *completo*: identità (chunk_id) ed embedding.
# Richiede quindi Ollama attivo: non è più un passaggio offline.

import re
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import List

from ..clients.ollama import oclient
from ..models.validators.chunks import ChunkMetadata, ChunkWithEmbedding

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PDF_DIR = BASE_DIR / "docs" / "pdf"
MD_DIR = BASE_DIR / "docs" / "md"
CHUNK_DIR = BASE_DIR / "docs" / "chunks"

MAX_TOKENS = 1200
EMBED_MODEL = "qwen3-embedding"

# Marcatore di pagina inserito da pdf2md prima di ogni pagina convertita.
PAGE_RE = re.compile(r"^<!--\s*pagina:\s*(\d+)\s*-->")
# Version nel nome del file: `..._v5.0.3` -> `5.0.3`.
VERSION_RE = re.compile(r"[_-]v(\d+(?:\.\d+)*)", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)")

# Namespace fisso: cambiarlo rigenera *tutti* gli id.
CHUNK_NAMESPACE = uuid.UUID("6f9b1d2e-5c4a-4f3b-8a71-0d5e7c9a2b64")


def doc_version(md_path):
    # Il Markdown non contiene la version: l'unica traccia è il nome del file.
    match = VERSION_RE.search(md_path.stem)
    return match.group(1) if match else "1.0"


def chunk_uuid(document: str, config: str, section: str, ordinal: int) -> str:
    """Identità stabile del chunk: documento, configurazione, posizione.

    Deterministica (stessa chiave -> stesso id) e in forma UUID, l'unico
    formato stringa che Qdrant accetta come id di un punto.

    La posizione è l'ordinale *dentro la sezione*: aggiungere un paragrafo a
    metà documento sposta gli id della sola sezione toccata, non di tutti i
    chunk che seguono.
    """

    return str(uuid.uuid5(CHUNK_NAMESPACE, f"{document}|{config}|{section}|{ordinal}"))


def embed(text: str) -> list[float]:
    return oclient.embeddings(model=EMBED_MODEL, prompt=text)["embedding"]


def build_chunk(text, metadata, section, page, ordinal, config) -> ChunkWithEmbedding:
    """Chiude un chunk: metadati, identità ed embedding."""
    metadata = metadata or {}
    return ChunkWithEmbedding(
        chunk_id=chunk_uuid(metadata.get("document", ""), config, section, ordinal),
        text=text,
        metadata=ChunkMetadata(
            document=metadata.get("document", ""),
            version=metadata.get("version", "1.0"),
            visibility=metadata.get("visibility", "public"),
            date=metadata.get("date", str(date.today())),
            page="" if page is None else str(page),
            section=section,
            ordinal=ordinal,
            config=config,
        ),
        embedding=embed(text),
    )


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


def fixed_size_chunking(text, metadata=None, config="A") -> List[ChunkWithEmbedding]:
    chunks = []
    current_chunk = []
    current_tokens = 0
    chunk_page = None  # pagina in cui inizia il chunk in corso
    # Senza sezioni l'ordinale è per forza globale: una modifica in testa al
    # documento sposta l'id di tutti i chunk successivi. È il prezzo del
    # taglio cieco alla struttura, ed è misurabile.
    ordinal = 0

    for word, page in words_with_pages(text):
        if not current_chunk:
            chunk_page = page

        current_tokens += 1
        if current_tokens <= MAX_TOKENS:
            current_chunk.append(word)
        else:
            chunks.append(build_chunk(
                ' '.join(current_chunk), metadata, "", chunk_page, ordinal, config))
            ordinal += 1
            current_chunk = [word]
            current_tokens = 1
            chunk_page = page

    # Append the last chunk
    if current_chunk:
        chunks.append(build_chunk(
            ' '.join(current_chunk), metadata, "", chunk_page, ordinal, config))

    return chunks


def cut_from_structure(text, metadata=None, config="B") -> List[ChunkWithEmbedding]:
    # Split the text into lines
    lines = text.splitlines()
    chunks = []
    current_chunk = []
    current_tokens = 0
    headings = []  # pila dei titoli aperti, uno per livello
    current_page = None  # pagina aperta dall'ultimo marcatore letto
    chunk_page = None  # pagina in cui inizia il chunk in corso
    chunk_section = ""  # percorso dei titoli valido all'inizio del chunk
    # Un contatore per sezione: gli id restano stabili anche se un percorso
    # ricompare più avanti nel documento.
    ordinals = defaultdict(int)

    def take_ordinal(section):
        n = ordinals[section]
        ordinals[section] += 1
        return n

    for line in lines:
        # Il marcatore aggiorna la pagina e non entra nel testo
        marker = PAGE_RE.match(line)
        if marker:
            current_page = int(marker.group(1))
            continue

        # Il titolo aggiorna il percorso: chiude i livelli pari o inferiori
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            del headings[level - 1:]
            headings.append(heading.group(2).strip())

        if not current_chunk:
            # Le righe vuote non aprono un chunk: aspettando la prima riga di
            # testo la pagina è quella giusta anche se il marcatore viene dopo.
            if not line.strip():
                continue
            chunk_page = current_page
            chunk_section = " > ".join(headings)

        # Count tokens in the line
        line_tokens = len(line.split())
        if current_tokens + line_tokens <= MAX_TOKENS:
            current_chunk.append(line)
            current_tokens += line_tokens
        else:
            chunks.append(build_chunk(
                '\n'.join(current_chunk), metadata, chunk_section, chunk_page,
                take_ordinal(chunk_section), config))
            current_chunk = [line]
            current_tokens = line_tokens
            chunk_page = current_page
            chunk_section = " > ".join(headings)

    # Append the last chunk
    if current_chunk:
        chunks.append(build_chunk(
            '\n'.join(current_chunk), metadata, chunk_section, chunk_page,
            take_ordinal(chunk_section), config))

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
            # Solo i metadati comuni a tutto il document: `page`, `section` e
            # `ordinal` variano da chunk a chunk, li calcola la strategia.
            metadata = {
                "document": md_path.stem,
                "version": doc_version(md_path),
                "visibility": "public",
                "date": str(date.today()),
            }
            # Strategia e parametri fanno parte dell'identità: senza, i chunk
            # di A e B collidono, e ritoccare MAX_TOKENS sovrascrive i vecchi.
            config = f"{name}-{MAX_TOKENS}"
            for chunk in strategy(text, metadata, config):
                f.write(chunk.model_dump_json() + "\n")
                total += 1
        print(
            f"Strategia {name}: {total} chunk -> docs/chunks/{out_path.name}")


def generate_chunks_for_all_md() -> None:
    for md_path in MD_DIR.glob("*.md"):
        generate_chunks(md_path)
