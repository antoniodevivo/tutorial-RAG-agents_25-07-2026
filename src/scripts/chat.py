"""Chat sul corpus: i chunk recuperati diventano una risposta.

    python -m src.scripts.chat
    python -m src.scripts.chat -q "Quanti giorni di ferie nel metalmeccanico?"

retrieval.py si ferma al recall@5: misura *se* i chunk giusti arrivano, non
cosa farne. Qui si chiude il giro. Il pezzo che si aggiunge e' uno solo - il
prompt - ed e' l'unico che l'utente vede: tutto il lavoro sul chunking e sul
ranking passa da li' o non passa affatto.

Ogni turno e' indipendente: la domanda va al retrieval cosi' com'e'. Un "e nel
commercio?" dopo una domanda sul metalmeccanico recupera male, perche' da sola
quella frase non nomina l'argomento. Farlo funzionare vuol dire riscrivere la
domanda alla luce dei turni precedenti (query rewriting): e' un pezzo a se', e
qui non c'e'.
"""

import argparse
import re
import shutil
import sys
import textwrap
from typing import Iterator

from ..clients.ollama import oclient
from ..clients.qdrant import qclient
from .retrieval import (COLLECTIONS, RRF_K, STRATEGIES, TOP_K, Hit,
                        SearchFn, recall_at_k)

# Il generatore. llava-phi3 e' quello disponibile in locale (ed e' anche il
# reranker di retrieval.py): 3.8B parametri, fragile sull'italiano. E' la
# costante da cambiare per prima - l'astensione, cioe' i blocchi A e X del
# golden set, dipende quasi solo da qui.
CHAT_MODEL = "llava-phi3:latest"

# Collection B, il taglio sui titoli: tiene insieme intestazione e tabella, che
# sulle domande T e' la differenza tra un contesto leggibile e tre numeri nudi.
DEFAULT_COLLECTION = "from_structure_chunking"

# hybrid senza reranker. Il reranker costa una chiamata al modello per ognuno
# dei 30 candidati: e' il modo giusto di misurare, non di chiacchierare.
DEFAULT_STRATEGY = "hybrid"

# Le chiavi di STRATEGIES hanno spazi e parentesi, scomode da digitare.
STRATEGY_ALIASES = {
    "semantic": "semantic",
    "hybrid": "hybrid (RRF)",
    "reranker": "hybrid + reranker",
}

# Il prompt e' generico apposta: il vector store non contiene solo i due CCNL,
# ma centinaia di documenti eterogenei (atti, report, moduli, paper...) senza
# relazione tra loro. Le regole devono reggere per qualunque corpus ci finisca
# dentro, non solo per le trappole del golden set su cui sono state pensate.
SYSTEM_PROMPT = """Answer the question using ONLY the passages below.

- If the passages don't contain the answer, say so clearly and stop — don't infer, calculate, or fill gaps with outside knowledge.
- Cite the passage after every claim, with its number in square brackets: [1], [3].
- If two or more passages cover the same topic but disagree or come from different sources, keep them distinct — don't silently pick one and drop the rest.
- Don't count or total anything across the corpus: you're given a handful of retrieved passages, not the whole corpus.
- Answer in the same language as the question."""

USER_PROMPT = """PASSAGES:
{context}

QUESTION: {question}"""


# --------------------------------------------------------------------------
# Il prompt
# --------------------------------------------------------------------------

def source_label(hit: Hit) -> str:
    """Documento, sezione e pagina, saltando i campi vuoti."""
    parts = [hit.document, hit.section, f"pag. {hit.page}" if hit.page else ""]
    return " | ".join(p for p in parts if p)


def format_hit(n: int, hit: Hit) -> str:
    """Un passaggio numerato: senza numero la citazione [n] non ha referente."""
    return f"[{n}] {source_label(hit)}\n{hit.text}"


# Nel prompt la sezione va per intero: la catena dei titoli e' contesto utile
# al modello. A schermo no - "CCNL > CONTRATTI FLESSIBILI > Art.76 ... >
# Art.87 ..." occupa tre righe e l'unico anello che descrive il chunk e'
# l'ultimo. Il markup (`<u>`, `**`) arriva dai titoli Markdown del corpus.
MARKUP_RE = re.compile(r"</?[a-z]+>|\*+")
SECTION_WIDTH = 62


def short_section(section: str) -> str:
    """L'ultimo anello del percorso dei titoli, ripulito e accorciato."""
    last = MARKUP_RE.sub("", section).split(">")[-1].strip()
    if not last:
        return "—"
    return last if len(last) <= SECTION_WIDTH else last[:SECTION_WIDTH - 1] + "…"


def build_context(hits: list[Hit]) -> str:
    return "\n\n".join(format_hit(n, h) for n, h in enumerate(hits, start=1))


def build_messages(question: str, hits: list[Hit]) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT.format(
            context=build_context(hits), question=question)},
    ]


# --------------------------------------------------------------------------
# La generazione
# --------------------------------------------------------------------------

def generate(question: str, hits: list[Hit]) -> Iterator[str]:
    """La risposta a pezzi, come arriva dal modello.

    `temperature` a 0: qui non si scrive, si riporta. Ogni grado di
    creativita' e' un grado di distanza dal testo dei documenti.
    """

    stream = oclient.chat(
        model=CHAT_MODEL,
        messages=build_messages(question, hits),
        options={"temperature": 0.0},
        stream=True,
    )
    for part in stream:
        yield part["message"]["content"]


def normalize_score(score: float, strategy: str) -> float:
    """Score grezzo -> 0-1: le tre strategie vivono su scale incomparabili.

    Coseno gia' 0-1, RRF ~0.01-0.03 (il massimo teorico e' un chunk primo in
    entrambe le liste: 2/(RRF_K+1)), reranker 0-10. Senza normalizzare, una
    sola soglia di confidenza sarebbe giusta per una strategia e arbitraria
    per le altre due.
    """
    if strategy == "reranker":
        return score / 10
    if strategy == "hybrid":
        return min(1.0, score / (2 / (RRF_K + 1)))
    return max(0.0, min(1.0, score))  # semantic: coseno, gia' in scala


def confidence_band(normalized: float) -> str:
    if normalized >= 0.65:
        return "high"
    if normalized >= 0.35:
        return "medium"
    return "low"


def format_source(n: int, hit: Hit, strategy: str) -> str:
    """Due righe per fonte: prima quanto vale e cosa dice, poi da dove viene."""
    normalized = normalize_score(hit.score, strategy)
    return (f"  [{n}] {normalized:>4.0%} {confidence_band(normalized):<6} "
            f"{short_section(hit.section)}\n"
            f"{'':18}{hit.document} · pag. {hit.page or '—'}")


def print_sources(hits: list[Hit], strategy: str) -> None:
    """Le fonti in fondo: senza, [1] e' un numero che nessuno puo' verificare."""
    print("\nFonti")
    for n, hit in enumerate(hits, start=1):
        print(format_source(n, hit, strategy))


# Il benchmark e' lo stesso recall_at_k di retrieval.py: qui serve solo da
# punto di riferimento ("questa strategia di solito recupera l'85% dei chunk
# giusti"), non a scegliere la strategia. Si calcola sul golden set intero
# una sola volta a sessione - con il reranker vuol dire ~30 chiamate al
# modello per ognuna delle domande del golden set, lo stesso ordine di costo
# della strategia scelta per la chat - e resta in cache per i turni dopo.
_BENCHMARK_CACHE: dict[tuple[str, str], dict] = {}


def strategy_benchmark(strategy: str, search_fn: SearchFn, collection: str) -> dict:
    key = (strategy, collection)
    if key not in _BENCHMARK_CACHE:
        _BENCHMARK_CACHE[key] = recall_at_k(search_fn, collection)
    return _BENCHMARK_CACHE[key]


def warm_benchmark(strategy: str, search_fn: SearchFn, collection: str) -> None:
    """Misura prima del primo turno: l'attesa va all'avvio, non in mezzo a
    una risposta gia' cominciata."""
    print("Misuro la strategia sul golden set (una volta sola)...",
          end="", flush=True)
    strategy_benchmark(strategy, search_fn, collection)
    print(" fatto.")


def print_benchmark(strategy: str, search_fn: SearchFn, collection: str) -> None:
    benchmark = strategy_benchmark(strategy, search_fn, collection)
    print(f"\n  Golden set, questa strategia: {benchmark['recall']:.0%} chunk "
          f"attesi · {benchmark['complete']:.0%} domande complete")


WAIT_MESSAGE = "Genero la risposta..."


def collect_answer(question: str, hits: list[Hit]) -> str:
    """Raccoglie la risposta intera, poi cancella l'attesa dalla riga.

    Lo streaming a schermo dava il primo token subito, ma stampava anche gli
    a-capo del modello cosi' com'erano: per rientrare e mandare a capo il
    testo bisogna averlo tutto. Il messaggio di attesa tiene il posto del
    feedback immediato.
    """

    # Solo su un terminale vero: rediretto su file, il `\r` non cancella
    # niente e l'attesa resterebbe incollata alla prima riga di risposta.
    interactive = sys.stdout.isatty()
    if interactive:
        print(WAIT_MESSAGE, end="", flush=True)
    text = "".join(generate(question, hits))
    if interactive:
        print("\r" + " " * len(WAIT_MESSAGE) + "\r", end="")
    return text


def answer_width() -> int:
    """La larghezza del terminale, ma senza righe illeggibilmente lunghe."""
    return min(shutil.get_terminal_size().columns - 4, 76)


def wrap_answer(text: str) -> str:
    """Rientro costante, a-capo sulla larghezza, righe vuote ripetute a una.

    Si manda a capo riga per riga invece di riempire i paragrafi: se il
    modello produce un elenco o una tabella, unire le righe la distruggerebbe.
    """

    width, out, blank = answer_width(), [], False
    for line in text.splitlines():
        if not line.strip():
            blank = bool(out)
            continue
        if blank:
            out.append("")
        blank = False
        out.extend(textwrap.wrap(line.strip(), width=width,
                                 initial_indent="  ", subsequent_indent="  "))
    return "\n".join(out)


def print_answer(question: str, hits: list[Hit]) -> None:
    """La risposta, formattata solo dopo essere arrivata per intero."""
    body = wrap_answer(collect_answer(question, hits))
    print(body or "  (il modello non ha prodotto testo)")


def answer(question: str, search_fn: SearchFn, collection: str, strategy: str) -> None:
    """Un turno intero: recupera, genera, dice da dove viene la risposta."""
    hits = search_fn(question, collection, TOP_K)
    if not hits:
        print("\nNessun passaggio recuperato.\n")
        return

    print("\nRisposta")
    print_answer(question, hits)
    print_sources(hits, strategy)
    print_benchmark(strategy, search_fn, collection)
    print()


# --------------------------------------------------------------------------
# La sessione
# --------------------------------------------------------------------------

def read_question() -> str | None:
    """La domanda, o None quando l'utente chiude: 'esci', Ctrl-C, Ctrl-D."""
    try:
        question = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return None if question.lower() in {"esci", "exit", "quit"} else question


def chat_loop(search_fn: SearchFn, collection: str, strategy: str) -> None:
    while True:
        question = read_question()
        if question is None:
            print("\nA presto.")
            return
        if question:
            answer(question, search_fn, collection, strategy)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chat sul corpus indicizzato in Qdrant.")
    parser.add_argument(
        "-q", "--question",
        help="Una domanda sola, senza aprire la sessione interattiva.")
    parser.add_argument(
        "-c", "--collection", default=DEFAULT_COLLECTION, choices=COLLECTIONS,
        help="Collection da interrogare (default: %(default)s).")
    parser.add_argument(
        "-s", "--strategy", default=DEFAULT_STRATEGY,
        choices=list(STRATEGY_ALIASES),
        help="Strategia di retrieval (default: %(default)s).")
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Avvia la sessione di chat interattiva.",
    )
    return parser.parse_args()


def chat_main() -> None:
    args = parse_args()

    if not qclient.collection_exists(args.collection):
        print(f"Collection '{args.collection}' assente in Qdrant.")
        print("Esegui prima il chunking e l'ingestion.")
        return

    search_fn = STRATEGIES[STRATEGY_ALIASES[args.strategy]]
    print(f"Collection: {args.collection} | strategia: {args.strategy} | "
          f"modello: {CHAT_MODEL}")
    warm_benchmark(args.strategy, search_fn, args.collection)

    if args.question:
        answer(args.question, search_fn, args.collection, args.strategy)
        return

    print("\nScrivi la domanda. 'esci' per uscire.\n")
    chat_loop(search_fn, args.collection, args.strategy)


if __name__ == "__main__":
    chat_main()
