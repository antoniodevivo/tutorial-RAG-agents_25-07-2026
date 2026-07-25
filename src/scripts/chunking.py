# Chunking dei Markdown in docs/md. Due strategie, entrambe eseguibili.
# Solo libreria standard: nessuna dipendenza esterna.

import json
import random
import re
from datetime import date
from itertools import groupby
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PDF_DIR = BASE_DIR / "docs" / "pdf"
MD_DIR = BASE_DIR / "docs" / "md"
CHUNK_DIR = BASE_DIR / "docs" / "chunks"

MAX_CHARS = 1200  # dimensione obiettivo di un chunk
# caratteri ripetuti tra un chunk e il successivo (solo strategia A)
OVERLAP = 200

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)")
PAGE_RE = re.compile(r"^<!--\s*pagina:\s*(\d+)\s*-->")
VERSION_RE = re.compile(r"[_-]v(\d+(?:\.\d+)*)", re.IGNORECASE)

# Chi può vedere il document. Default pubblico, eccezioni elencate qui.
VISIBILITY = {
    "CV_Antonio_DeVivo_ITA_v5.0.3": "privato",
}


def parse_blocks(text: str) -> list[dict]:
    """Divide il Markdown in blocchi atomici, annotati con sezione e pagina.

    Un blocco è un paragrafo oppure una tabella *intera*: le righe che iniziano
    con '|' vengono accumulate finché la tabella non finisce, così nessuna
    strategia può spezzarla a metà.

    Args:
        text: contenuto del file Markdown.

    Returns:
        Lista di blocchi con chiavi `text`, `section`, `page`, `is_table`.
    """

    blocks: list[dict] = []
    headings: list[str] = []  # pila dei titoli aperti, uno per livello
    page: int | None = None
    buffer: list[str] = []
    in_table = False

    def flush() -> None:
        """Chiude il blocco in corso usando la sezione valida al suo inizio."""
        nonlocal buffer, in_table
        body = "\n".join(buffer).strip()
        if body:
            blocks.append(
                {
                    "text": body,
                    "section": " > ".join(headings),
                    "page": page,
                    "is_table": in_table,
                }
            )
        buffer, in_table = [], False

    for line in text.splitlines():
        marker = PAGE_RE.match(line)
        if marker:
            page = int(marker.group(1))
            continue

        is_table_line = line.lstrip().startswith("|")
        if in_table and not is_table_line:
            flush()  # la tabella finisce alla prima riga che non è una tabella

        heading = HEADING_RE.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            # chiude i titoli di livello pari o inferiore
            del headings[level - 1:]
            headings.append(heading.group(2).strip())
            buffer = [line]  # il titolo apre il blocco successivo
        elif is_table_line:
            if not in_table:
                flush()
                in_table = True
            buffer.append(line)
        elif not line.strip():
            flush()
        else:
            buffer.append(line)

    flush()
    return blocks


def doc_metadata(path: Path) -> dict:
    """Metadati comuni a tutti i chunk di un document.

    `data` è la data del PDF sorgente (o del Markdown se il PDF non c'è):
    è un proxy della data del document, l'unico ricavabile senza leggerne il text.

    Args:
        path: percorso del file Markdown.

    Returns:
        Dizionario con `document`, `data`, `version`, `visible_to`.
    """

    pdf_path = PDF_DIR / f"{path.stem}.pdf"
    source = pdf_path if pdf_path.exists() else path
    version = VERSION_RE.search(path.stem)
    return {
        "document": path.stem,
        "data": date.fromtimestamp(source.stat().st_mtime).isoformat(),
        "version": version.group(1) if version else "1.0",
        "visible_to": VISIBILITY.get(path.stem, "pubblico"),
    }


def build_chunk(units: list[dict], meta: dict, prefix: str = "") -> dict:
    """Unisce le unità in un chunk, prendendo sezione e pagina dalla prima."""
    return {
        "text": prefix + "\n".join(u["text"] for u in units).strip(),
        "document": meta["document"],
        "section": units[0]["section"],
        "pagina": units[0]["page"],
        "data": meta["data"],
        "version": meta["version"],
        "visible_to": meta["visible_to"],
    }


def overlap_tail(window: list[dict]) -> list[dict]:
    """Ultime unità della finestra entro OVERLAP caratteri, tabelle escluse."""
    tail: list[dict] = []
    size = 0
    for unit in reversed(window):
        if unit["is_table"] or size + len(unit["text"]) > OVERLAP:
            break
        tail.insert(0, unit)
        size += len(unit["text"]) + 1
    return tail


def strategy_a(blocks: list[dict], meta: dict) -> list[dict]:
    """(A) Taglio a lunghezza fissa con overlap, cieco alla struttura.

    Il text viene tagliato riga per riga appena si supera MAX_CHARS; la tabella
    resta un'unità sola, quindi il taglio la scavalca anche se sfora.

    Args:
        blocks: blocchi del document.
        meta: metadati comuni del document.

    Returns:
        Lista di chunk.
    """

    units = [
        block if block["is_table"] else {**block, "text": line}
        for block in blocks
        for line in ([block["text"]] if block["is_table"] else block["text"].split("\n"))
    ]

    chunks: list[dict] = []
    window: list[dict] = []
    size = 0
    for unit in units:
        if window and size + len(unit["text"]) > MAX_CHARS:
            chunks.append(build_chunk(window, meta))
            window = overlap_tail(window)
            size = sum(len(u["text"]) + 1 for u in window)
        window.append(unit)
        size += len(unit["text"]) + 1

    if window:
        chunks.append(build_chunk(window, meta))
    return chunks


def strategy_b(blocks: list[dict], meta: dict) -> list[dict]:
    """(B) Taglio sulla struttura: si taglia sui titoli Markdown.

    Una sezione troppo lunga viene divisa sui confini tra blocchi (mai dentro
    una tabella) e ogni pezzo ripete in testa il percorso dei titoli, così il
    chunk resta leggibile da solo.

    Args:
        blocks: blocchi del document.
        meta: metadati comuni del document.

    Returns:
        Lista di chunk.
    """

    chunks: list[dict] = []
    for section, section_blocks in groupby(blocks, key=lambda b: b["section"]):
        breadcrumb = " > ".join(filter(None, [meta["document"], section]))
        prefix = f"[{breadcrumb}]\n\n"

        group: list[dict] = []
        size = 0
        for block in section_blocks:
            if group and size + len(block["text"]) > MAX_CHARS:
                chunks.append(build_chunk(group, meta, prefix))
                group, size = [], 0
            group.append(block)
            size += len(block["text"]) + 1
        if group:
            chunks.append(build_chunk(group, meta, prefix))
    return chunks


STRATEGIES = {"A": strategy_a, "B": strategy_b}


def generate_chunks() -> None:
    """Applica entrambe le strategie a tutti i Markdown e scrive un JSONL per strategia."""
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)

    documents = [(p, parse_blocks(p.read_text(encoding="utf-8")))
                 for p in sorted(MD_DIR.glob("*.md"))]
    if not documents:
        print(f"Nessun Markdown trovato in {MD_DIR}")
        return

    for name, strategy in STRATEGIES.items():
        out_path = CHUNK_DIR / f"chunks_{name}.jsonl"
        total = 0
        with out_path.open("w", encoding="utf-8") as f:
            for md_path, blocks in documents:
                for chunk in strategy(blocks, doc_metadata(md_path)):
                    f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                    total += 1
        print(
            f"Strategia {name}: {total} chunk -> docs/chunks/{out_path.name}")


def lonely_chunk_test(sample_size: int = 10, seed: int = 0) -> None:
    """Il test del chunk solitario: estrae N chunk a caso per strategia.

    Scrive i chunk campionati in docs/chunks/test_solitario.md, senza il resto
    del document. Vanno letti e contati a mano: il punteggio è quanti si
    capiscono da soli.

    Args:
        sample_size: chunk da estrarre per ogni strategia.
        seed: seme del campionamento, per poter ripetere lo stesso test.
    """

    lines = [
        "# Test del chunk solitario",
        "",
        f"{sample_size} chunk a caso per strategia (seed {seed}).",
        "Leggi ogni chunk **senza** il resto del document e segna [x] se si capisce da solo.",
        "",
    ]

    for name in STRATEGIES:
        source = CHUNK_DIR / f"chunks_{name}.jsonl"
        if not source.exists():
            print(f"Manca {source.name}: genera prima i chunk.")
            return

        pool = source.read_text(encoding="utf-8").splitlines()
        lines.append(f"## Strategia {name} — punteggio: __/{sample_size}\n")
        for i, raw in enumerate(random.Random(seed).sample(pool, sample_size), start=1):
            chunk = json.loads(raw)
            meta = " | ".join(
                [
                    chunk["document"],
                    f"sez: {chunk['section'] or '-'}",
                    f"pag: {chunk['pagina']}",
                    chunk["data"],
                    f"v{chunk['version']}",
                    chunk["visible_to"],
                ]
            )
            lines.append(f"### {name}{i} — [ ] comprensibile da solo")
            lines.append(f"`{meta}`\n")
            lines.append(f"```\n{chunk['text']}\n```\n")

    out_path = CHUNK_DIR / "test_solitario.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"Campione scritto in docs/chunks/{out_path.name}: leggilo e scrivi i due punteggi.")
