# Cartelle di input/output, risolte rispetto a questo file (src/ -> ../docs/...)

from pathlib import Path
import pymupdf4llm

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PDF_DIR = BASE_DIR / "docs" / "pdf"
MD_DIR = BASE_DIR / "docs" / "md"


def convert_pdf_to_markdown(pdf_path: Path, md_path: Path) -> bool:
    """Converte un singolo PDF in un file Markdown.

    Args:
        pdf_path: percorso del PDF di input.
        md_path: percorso del file Markdown di output.
    """


    try:
        md = pymupdf4llm.to_markdown(str(pdf_path))
        md_path.write_text(md)
        return True
    except Exception as e:
        print(f"Errore durante la conversione di {pdf_path.name}: {e}")
        return False


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