"""
Created entirely by Claude Opus 5

Rigenera eval/golden_set.jsonl da eval/golden_set.md.

    python -m src.scripts.golden_set            # dry-run: cosa cambierebbe
    python -m src.scripts.golden_set --write    # riscrive il .jsonl
    python -m src.scripts.golden_set --check    # exit 1 se il .jsonl e' obsoleto

Il .md e' la fonte di verita': le domande si scrivono la' dentro, con la
risposta attesa, il chunk atteso, l'ancora e la trappola. Il .jsonl e' solo la
forma che il codice legge, e va rigenerato invece di essere ritoccato a mano:
altrimenti i due divergono e le domande *documentate* non sono piu' quelle
*misurate*.

Prima di scrivere, ogni ancora viene verificata due volte:

  1. contro il Markdown di partenza in docs/md. Se l'ancora non c'e', e' una
     citazione sbagliata nel .md: errore, e lo script non scrive niente.
  2. contro i chunk in docs/chunks. Se l'ancora esiste nel documento ma nessun
     singolo chunk la contiene, il chunking l'ha spezzata a meta' e quella
     domanda non potra' mai passare, con nessuna strategia di retrieval. Non
     blocca la scrittura - e' una diagnosi, ed e' il motivo per cui questo
     script va rilanciato dopo ogni modifica di MAX_CHARS.

La normalizzazione usata per verificare e' `normalize()` di retrieval.py, la
stessa che usa `found()` per assegnare il punteggio. Verificare con un
normalizzatore diverso da quello che misura renderebbe la verifica inutile.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from tabulate import tabulate

from .chunking_simple import CHUNK_DIR, MD_DIR
from .retrieval import GOLDEN_PATH, load_golden, normalize

BASE_DIR = Path(__file__).resolve().parent.parent.parent
GOLDEN_MD = BASE_DIR / "eval" / "golden_set.md"

# Le due sigle della legenda del .md ("MM = metalmeccanico, CO = commercio").
# Il valore e' lo stem del file in docs/md, cioe' il `document` nei metadati.
DOC_BY_CODE = {
    "MM": "ccnl_metalmeccanico_industria_conflavoro",
    "CO": "ccnl_commercio_terziario_distribuzione_e_servizi",
}

# Il tipo viene dal prefisso dell'id, non dal titolo della sezione: il titolo
# si puo' riscrivere, l'id no - e' citato nei report e nei documenti di
# problems/. Un prefisso non elencato qui e' un errore, non un tipo nuovo.
TYPE_BY_PREFIX = {
    "S": "semplice",
    "P": "parafrasi",
    "C": "codice",
    "T": "tabella",
    "M": "multi-passaggio",
    "A": "aggregazione",
    "X": "assente",
}

# Le configurazioni di chunking prodotte da chunking_simple.py.
CHUNK_CONFIGS = ["A", "B"]

QUESTION_RE = re.compile(
    r"^###\s+(?P<id>[A-Z]+\d+)\s+—\s+(?P<question>.+?)\s*$")
# "- **Chunk atteso:** ...", "- **Chunk attesi (2):**", e anche
# "- **Chunk che verranno recuperati:** ...", che NON e' un'attesa.
CHUNK_LINE_RE = re.compile(
    r"^-\s+\*\*(?P<label>Chunk[^:]*?):\*\*\s*(?P<rest>.*)$")
ANCHOR_RE = re.compile(r'^-\s+\*\*Ancora:\*\*\s*"(?P<anchor>.+)"\s*$')
# Le multi-passaggio elencano un'ancora per documento, in una lista numerata:
#   1. MM › `Art.51 - Preavviso` › pag. 47 — ancora: "..."
ITEM_RE = re.compile(
    r'^\s+\d+\.\s+(?P<code>[A-Z]{2})\s+›.*?—\s+ancora:\s*"(?P<anchor>.+)"\s*$')
# Il riferimento a un documento e' sempre "SIGLA › ": senza il ›, "CO" sarebbe
# una sigla come tante nel testo della riga. Il lookbehind evita di leggere la
# coda di una parola piu' lunga: "ICT ›" della T4 non e' un "CT ›".
DOC_REF_RE = re.compile(r"(?<![A-Za-z])(?P<code>[A-Z]{2})\s+›")


# --------------------------------------------------------------------------
# Lettura del .md
# --------------------------------------------------------------------------

def parse_md(text: str) -> list[dict]:
    """I blocchi `### ID — domanda` con i campi che servono al .jsonl.

    Restituisce la forma grezza: la riga del chunk atteso non e' ancora
    interpretata, perche' distinguere un'attesa da un'astensione richiede di
    aver visto tutto il blocco.
    """

    blocks, current = [], None

    for line in text.splitlines():
        match = QUESTION_RE.match(line)
        if match:
            current = {"id": match["id"], "question": match["question"],
                       "label": None, "rest": "", "anchor": None, "items": []}
            blocks.append(current)
            continue

        if current is None:      # preambolo del documento, prima di S1
            continue

        match = CHUNK_LINE_RE.match(line)
        if match and current["label"] is None:
            current["label"] = match["label"]
            current["rest"] = match["rest"]
            continue

        match = ANCHOR_RE.match(line)
        if match and current["anchor"] is None:
            current["anchor"] = match["anchor"]
            continue

        match = ITEM_RE.match(line)
        if match:
            current["items"].append((match["code"], match["anchor"]))

    return blocks


def build_entry(block: dict) -> tuple[dict, str | None]:
    """Un blocco del .md diventa una riga del .jsonl. Il secondo valore e'
    l'errore di parsing, se c'e'.

    Le attese si leggono cosi':
      - "Chunk atteso"/"Chunk attesi" e' vincolante; qualsiasi altra etichetta
        (es. "Chunk che verranno recuperati" delle X) e' informativa, e la
        domanda va nel gruppo astensione.
      - "nessuno" nella riga (le A) e' un'astensione dichiarata.
      - se ci sono voci numerate, ognuna porta il suo documento e la sua
        ancora; se no, l'unica ancora del blocco vale per tutti i documenti
        citati nella riga - e' il caso della C2, stessa frase in due contratti.
    """

    qid = block["id"]
    if qid[0] not in TYPE_BY_PREFIX:
        return {}, f"{qid}: prefisso sconosciuto, aggiungilo a TYPE_BY_PREFIX"

    entry = {"id": qid, "type": TYPE_BY_PREFIX[qid[0]],
             "question": block["question"], "expected": []}

    label = block["label"] or ""
    binding = label.startswith("Chunk attes")
    declared_none = "nessuno" in block["rest"].lower()

    if binding and not declared_none:
        if block["items"]:
            pairs = block["items"]
        elif block["anchor"]:
            pairs = [(m["code"], block["anchor"])
                     for m in DOC_REF_RE.finditer(block["rest"])]
        else:
            pairs = []

        if not pairs:
            # Silenziosamente diventerebbe una domanda di astensione, cioe'
            # spariterebbe dal recall@5 senza che nessuno se ne accorga.
            return {}, (f"{qid}: attesa dichiarata ma nessuna coppia "
                        f"documento+ancora leggibile")

        unknown = [code for code, _ in pairs if code not in DOC_BY_CODE]
        if unknown:
            return {}, f"{qid}: sigla documento sconosciuta {unknown}"

        entry["expected"] = [{"document": DOC_BY_CODE[code], "anchor": anchor}
                             for code, anchor in pairs]

    if not entry["expected"]:
        entry["abstain"] = True

    return entry, None


def read_md() -> tuple[list[dict], list[str]]:
    blocks = parse_md(GOLDEN_MD.read_text(encoding="utf-8"))
    entries, errors = [], []

    for block in blocks:
        entry, error = build_entry(block)
        if error:
            errors.append(error)
        else:
            entries.append(entry)

    seen = defaultdict(int)
    for entry in entries:
        seen[entry["id"]] += 1
    errors += [f"{qid}: id duplicato ({n} volte)"
               for qid, n in seen.items() if n > 1]

    return entries, errors


# --------------------------------------------------------------------------
# Verifica delle ancore
# --------------------------------------------------------------------------

def load_corpus() -> dict[str, str]:
    """Il Markdown di partenza, normalizzato una volta sola."""
    return {document: normalize((MD_DIR / f"{document}.md").read_text(encoding="utf-8"))
            for document in DOC_BY_CODE.values()}


def load_chunk_texts() -> dict[tuple[str, str], list[str]]:
    """I testi dei chunk per (documento, configurazione), normalizzati.

    Le configurazioni non ancora generate mancano dal dizionario: la verifica
    le salta invece di inventarsi un fallimento.
    """

    texts = {}
    for document in DOC_BY_CODE.values():
        for config in CHUNK_CONFIGS:
            path = CHUNK_DIR / f"md_{document}.md_chunks-{config}.jsonl"
            if not path.exists():
                continue
            texts[(document, config)] = [
                normalize(json.loads(line)["text"])
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    return texts


def verify(entries: list[dict]) -> tuple[list[str], list[str]]:
    """Errori (bloccano la scrittura) e diagnosi (non la bloccano)."""

    corpus = load_corpus()
    chunk_texts = load_chunk_texts()
    errors, notes = [], []

    for entry in entries:
        for expected in entry["expected"]:
            document, anchor = expected["document"], expected["anchor"]
            needle = normalize(anchor)

            if needle not in corpus[document]:
                errors.append(f"{entry['id']}: l'ancora non e' in {document} "
                              f"-> {anchor!r}")
                continue

            broken = [config for config in CHUNK_CONFIGS
                      if (document, config) in chunk_texts
                      and not any(needle in text
                                  for text in chunk_texts[(document, config)])]
            if broken:
                notes.append(f"{entry['id']}: ancora spezzata dal chunking "
                             f"(strategia {', '.join(broken)}) -> {anchor!r}")

            elsewhere = [other for other in corpus
                         if other != document and needle in corpus[other]]
            if elsewhere:
                notes.append(f"{entry['id']}: ancora presente anche in "
                             f"{', '.join(elsewhere)} - found() la distingue "
                             f"solo per `document`")

    if not chunk_texts:
        notes.append("docs/chunks/ vuota per i CCNL: verifica sui chunk saltata "
                     "(lancia chunking_simple.py)")

    return errors, notes


# --------------------------------------------------------------------------
# Diff e scrittura
# --------------------------------------------------------------------------

def render(entries: list[dict]) -> str:
    """Una riga per domanda, chiavi in ordine fisso perche' il diff si legga."""
    lines = []
    for entry in entries:
        ordered = {key: entry[key]
                   for key in ("id", "type", "question", "expected", "abstain")
                   if key in entry}
        lines.append(json.dumps(ordered, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def diff(old: list[dict], new: list[dict]) -> list[str]:
    """Cosa cambia nel .jsonl, per id. Un diff di testo sarebbe illeggibile:
    le righe sono lunghe e cambiano quasi tutte per un accento."""

    by_id_old = {entry["id"]: entry for entry in old}
    by_id_new = {entry["id"]: entry for entry in new}
    changes = []

    for qid in sorted(set(by_id_old) - set(by_id_new)):
        changes.append(f"- {qid} rimossa dal .md")
    for qid in sorted(set(by_id_new) - set(by_id_old)):
        changes.append(f"+ {qid} nuova nel .md")

    for qid, entry in by_id_new.items():
        before = by_id_old.get(qid)
        if before is None:
            continue

        if before.get("type") != entry["type"]:
            changes.append(
                f"~ {qid} tipo: {before.get('type')} -> {entry['type']}")

        if before.get("question") != entry["question"]:
            changes.append(f"~ {qid} domanda:\n    - {before.get('question')}"
                           f"\n    + {entry['question']}")

        old_exp = [(e["document"], e["anchor"])
                   for e in before.get("expected", [])]
        new_exp = [(e["document"], e["anchor"]) for e in entry["expected"]]
        if old_exp != new_exp:
            if len(old_exp) != len(new_exp):
                changes.append(
                    f"~ {qid} attese: {len(old_exp)} -> {len(new_exp)}")
            for i in range(max(len(old_exp), len(new_exp))):
                was = old_exp[i] if i < len(old_exp) else None
                now = new_exp[i] if i < len(new_exp) else None
                if was == now:
                    continue
                changes.append(f"~ {qid} ancora [{i}]:"
                               f"\n    - {was[1] if was else '(assente)'}"
                               f"\n    + {now[1] if now else '(assente)'}")
                if was and now and was[0] != now[0]:
                    changes.append(f"    documento: {was[0]} -> {now[0]}")

    return changes


def summary(entries: list[dict]) -> str:
    per_type = defaultdict(lambda: [0, 0, 0])
    for entry in entries:
        row = per_type[entry["type"]]
        row[0] += 1
        row[1] += len(entry["expected"])
        row[2] += bool(entry.get("abstain"))

    rows = [[t, n, attese, astensioni] for t, (n, attese, astensioni)
            in per_type.items()]
    rows.append(["TOTALE", sum(r[1] for r in rows), sum(r[2] for r in rows),
                 sum(r[3] for r in rows)])
    return tabulate(rows, headers=["tipo", "domande", "attese", "astensioni"])


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rigenera eval/golden_set.jsonl da eval/golden_set.md.")
    parser.add_argument("--write", action="store_true",
                        help="riscrive eval/golden_set.jsonl")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 se il .jsonl non e' allineato al .md")
    args = parser.parse_args()

    entries, errors = read_md()
    print(f"\n{GOLDEN_MD.name}: {len(entries)} domande\n")
    print(summary(entries))

    verify_errors, notes = verify(entries)
    errors += verify_errors

    if notes:
        print("\nDiagnosi:")
        for note in notes:
            print(f"  {note}")

    if errors:
        print("\nErrori (il .jsonl non viene scritto):")
        for error in errors:
            print(f"  {error}")
        return 1

    current = load_golden() if GOLDEN_PATH.exists() else []
    changes = diff(current, entries)

    if not changes:
        print(f"\n{GOLDEN_PATH.name} e' allineato al .md.")
        return 0

    print(f"\n{len(changes)} differenze rispetto a {GOLDEN_PATH.name}:")
    for change in changes:
        print(f"  {change}")

    if args.check:
        print("\n--check: il .jsonl e' obsoleto, rilancia con --write.")
        return 1

    if args.write:
        GOLDEN_PATH.write_text(render(entries), encoding="utf-8")
        print(f"\nScritto {GOLDEN_PATH}.")
        print("Le ancore sono cambiate: i punteggi non sono confrontabili con "
              "quelli misurati prima. Rilancia retrieval.py.")
        return 0

    print("\nDry-run: niente scritto. Usa --write per applicare.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
