# Cartelle di input/output, risolte rispetto a questo file (src/ -> ../docs/...)

from pathlib import Path
import pymupdf
import pymupdf4llm

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PDF_DIR = BASE_DIR / "docs" / "pdf"
MD_DIR = BASE_DIR / "docs" / "md"
PROBLEMS_DIR = MD_DIR / "problems"


def to_markdown(source, **kwargs) -> str:
    """Converte in Markdown anteponendo a ogni pagina un marcatore `<!-- pagina: N -->`.

    Il marcatore è l'unica traccia del numero di pagina che sopravvive alla
    conversione: serve al chunking per compilare il metadato `pagina`.

    Args:
        source: percorso del PDF o documento pymupdf già aperto.
        **kwargs: opzioni passate a pymupdf4llm.to_markdown (es. pages).

    Returns:
        Il Markdown del documento, con i marcatori di pagina.
    """

    pages = pymupdf4llm.to_markdown(source, page_chunks=True, show_progress=False, **kwargs)
    first = kwargs.get("pages", [0])[0] + 1  # numero della prima pagina convertita
    return "".join(f"\n<!-- pagina: {first + i} -->\n\n{p['text']}" for i, p in enumerate(pages))


def convert_page_by_page(pdf_path: Path, errors: list[str]) -> str:
    """Converte il PDF una pagina alla volta, saltando quelle che danno errore.

    Usata come ripiego quando la conversione dell'intero documento fallisce:
    permette di recuperare le pagine leggibili invece di perdere tutto il file.

    Args:
        pdf_path: percorso del PDF di input.
        errors: lista a cui vengono aggiunti i messaggi di errore incontrati.

    Returns:
        Il Markdown delle sole pagine convertite correttamente.
    """

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        errors.append(f"Apertura del PDF fallita: {type(e).__name__}: {e}")
        return ""

    pages = []
    total = doc.page_count
    for i in range(total):
        try:
            pages.append(to_markdown(doc, pages=[i]))
        except Exception as e:
            errors.append(f"Pagina {i + 1} saltata: {type(e).__name__}: {e}")
    doc.close()

    if total == 0:
        errors.append("Il PDF non contiene pagine leggibili (file troncato o corrotto).")
    else:
        errors.append(f"Recuperate {len(pages)}/{total} pagine.")
    return "".join(pages)


def convert_pdf_to_markdown(pdf_path: Path, md_path: Path) -> bool:
    """Converte un singolo PDF in un file Markdown.

    Se la conversione dell'intero documento fallisce, riprova pagina per pagina
    e salva le pagine recuperate. Gli eventuali problemi di parsing vengono
    salvati in PROBLEMS_DIR/<nome_file>.md.

    Args:
        pdf_path: percorso del PDF di input.
        md_path: percorso del file Markdown di output.
    """

    errors: list[str] = []
    pymupdf.TOOLS.reset_mupdf_warnings()

    try:
        md = to_markdown(str(pdf_path))
    except Exception as e:
        print(f"Errore durante la conversione di {pdf_path.name}: {e}")
        print("  Riprovo pagina per pagina...")
        errors.append(f"Conversione dell'intero documento fallita: {type(e).__name__}: {e}")
        md = convert_page_by_page(pdf_path, errors)

    if md:
        md_path.write_text(md, encoding="utf-8")
    else:
        errors.append("Nessun contenuto estratto: il file Markdown non è stato creato.")

    # mupdf_warnings() restituisce (e azzera) gli avvisi di parsing accumulati.
    # dict.fromkeys() elimina i doppioni mantenendo l'ordine.
    rows = [*pymupdf.TOOLS.mupdf_warnings().splitlines(), *errors]
    problems = "\n".join(dict.fromkeys(filter(None, rows))).strip()
    if problems:
        PROBLEMS_DIR.mkdir(parents=True, exist_ok=True)
        (PROBLEMS_DIR / f"{pdf_path.stem}.md").write_text(
            f"# Problemi di parsing: {pdf_path.name}\n\n```\n{problems}\n```\n",
            encoding="utf-8",
        )
        print(f"  Problemi di parsing salvati in {PROBLEMS_DIR.name}/{pdf_path.stem}.md")

    return bool(md)


def convert_all_pdfs() -> None:
    """Converte tutti i PDF in PDF_DIR in file Markdown dentro MD_DIR."""
    MD_DIR.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"Nessun PDF trovato in {PDF_DIR}")
        return

    for pdf_path in pdf_files:
        md_path = MD_DIR / f"{pdf_path.stem}.md"

        if not md_path.exists():
            print(f"Conversione: {pdf_path.name} -> {md_path.name}")
            convert_pdf_to_markdown(pdf_path, md_path)
        else:
            print(f"File Markdown già esistente: {md_path.name}, salto la conversione.")