# Cartelle di input/output, risolte rispetto a questo file (src/ -> ../docs/...)

from pathlib import Path
import pymupdf
import pymupdf4llm

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PDF_DIR = BASE_DIR / "docs" / "pdf"
MD_DIR = BASE_DIR / "docs" / "md"
PROBLEMS_DIR = MD_DIR / "problems"


def convert_pdf_to_markdown(pdf_path: Path, md_path: Path) -> bool:
    """Converte un singolo PDF in un file Markdown.

    Gli eventuali problemi di parsing vengono salvati in
    PROBLEMS_DIR/<nome_file>.md.

    Args:
        pdf_path: percorso del PDF di input.
        md_path: percorso del file Markdown di output.
    """

    errors = None
    pymupdf.TOOLS.reset_mupdf_warnings()

    try:
        md = pymupdf4llm.to_markdown(str(pdf_path))
        md_path.write_text(md, encoding="utf-8")
    except Exception as e:
        errors = f"{type(e).__name__}: {e}"
        print(f"Errore durante la conversione di {pdf_path.name}: {e}")

    # mupdf_warnings() restituisce (e azzera) gli avvisi di parsing accumulati.
    problems = "\n".join(filter(None, [pymupdf.TOOLS.mupdf_warnings(), errors])).strip()
    if problems:
        PROBLEMS_DIR.mkdir(parents=True, exist_ok=True)
        (PROBLEMS_DIR / f"{pdf_path.stem}.md").write_text(
            f"# Problemi di parsing: {pdf_path.name}\n\n```\n{problems}\n```\n",
            encoding="utf-8",
        )
        print(f"  Problemi di parsing salvati in {PROBLEMS_DIR.name}/{pdf_path.stem}.md")

    return errors is None


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