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
from typing import Iterator

from ..clients.ollama import oclient
from ..clients.qdrant import qclient
from .retrieval import COLLECTIONS, STRATEGIES, TOP_K, Hit, SearchFn

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
    "semantic": "semantica",
    "hybrid": "hybrid (RRF)",
    "reranker": "hybrid + reranker",
}

# Le quattro regole sono quattro trappole del golden set, in ordine: la
# risposta assente (blocco X), la citazione verificabile, i due contratti
# gemelli con valori diversi, il conteggio che il RAG non puo' fare (blocco A).
SYSTEM_PROMPT = """Rispondi a domande sui contratti collettivi usando SOLO i passaggi forniti.

- Se i passaggi non contengono la risposta, scrivi "Non è nei documenti." e fermati. Non dedurre, non calcolare, non completare con quello che sai già.
- Cita il passaggio dopo ogni affermazione, con il suo numero tra parentesi quadre: [1], [3].
- I due contratti (metalmeccanico e commercio) regolano gli stessi istituti con valori diversi. Se la domanda non dice quale, rispondi per entrambi: non sceglierne uno in silenzio.
- Non contare e non fare totali: ricevi i primi passaggi trovati, non il corpus."""

USER_PROMPT = """PASSAGGI:
{context}

DOMANDA: {question}"""


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
    """La risposta a pezzi, cosi' il primo token si vede subito.

    `temperature` a 0: qui non si scrive, si riporta. Ogni grado di
    creativita' e' un grado di distanza dal testo del contratto.
    """

    stream = oclient.chat(
        model=CHAT_MODEL,
        messages=build_messages(question, hits),
        options={"temperature": 0.0},
        stream=True,
    )
    for part in stream:
        yield part["message"]["content"]


def print_sources(hits: list[Hit]) -> None:
    """Le fonti in fondo: senza, [1] e' un numero che nessuno puo' verificare."""
    print("\n\nFonti:")
    for n, hit in enumerate(hits, start=1):
        print(f"  [{n}] {source_label(hit)}")


def answer(question: str, search_fn: SearchFn, collection: str) -> None:
    """Un turno intero: recupera, genera, dice da dove viene la risposta."""
    hits = search_fn(question, collection, TOP_K)
    if not hits:
        print("Nessun passaggio recuperato.\n")
        return

    for piece in generate(question, hits):
        print(piece, end="", flush=True)
    print_sources(hits)
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


def chat_loop(search_fn: SearchFn, collection: str) -> None:
    while True:
        question = read_question()
        if question is None:
            print("\nA presto.")
            return
        if question:
            answer(question, search_fn, collection)


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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not qclient.collection_exists(args.collection):
        print(f"Collection '{args.collection}' assente in Qdrant.")
        print("Esegui prima il chunking e l'ingestion.")
        return

    search_fn = STRATEGIES[STRATEGY_ALIASES[args.strategy]]
    print(f"Collection: {args.collection} | strategia: {args.strategy} | "
          f"modello: {CHAT_MODEL}")

    if args.question:
        answer(args.question, search_fn, args.collection)
        return

    print("Scrivi la domanda. 'esci' per uscire.\n")
    chat_loop(search_fn, args.collection)


if __name__ == "__main__":
    main()
