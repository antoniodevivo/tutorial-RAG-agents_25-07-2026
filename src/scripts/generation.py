"""Valutazione della generazione: recall@5 misura il recupero, questo le risposte.

    python -m src.scripts.generation
    python -m src.scripts.generation -s semantic --limit 8
    python -m src.main --evalgen        # solo coi valori di default: main.py
                                        # valida per primo e non conosce -s/--limit

retrieval.py risponde a "il chunk giusto e' arrivato?". Restano fuori le due
domande che contano per chi legge la risposta:

    1. il fatto atteso e' *nella* risposta, o il modello aveva il chunk giusto
       davanti e ha scritto altro?
    2. quando la risposta non c'e' nel corpus, il modello si astiene o inventa?

La seconda e' la meta' del golden set che nessuna metrica di retrieval puo'
toccare: le 5 domande dei blocchi A (aggregazione) e X (risposta assente) non
hanno chunk atteso, e il retrieval restituira' comunque qualcosa di pertinente.
Il fallimento da misurare e' che il modello risponda lo stesso, con sicurezza.

Il giudice e' un LLM: confronta il fatto atteso con la risposta e dice se c'e'.
E' la stessa forma del reranker in retrieval.py - un modello che legge due
testi insieme ed emette un verdetto - e ne condivide il limite: un giudice
debole sbaglia a giudicare, esattamente come un generatore debole sbaglia a
rispondere. Vale come misura relativa tra strategie, non come verita' assoluta.
"""

import argparse
import re
import sys

from tabulate import tabulate

from ..clients.ollama import oclient
from ..clients.qdrant import qclient
from .chat import (CHAT_MODEL, DEFAULT_COLLECTION, DEFAULT_STRATEGY,
                   STRATEGY_ALIASES, generate)
from .retrieval import (COLLECTIONS, STRATEGIES, TOP_K, Hit, SearchFn, found,
                        load_golden)

# Il giudice e' lo stesso modello che genera. Non e' l'ideale - un modello che
# valuta se stesso e' indulgente sui propri errori - ma tenerne due complica il
# setup senza cambiare le conclusioni, che qui sono comparative.
JUDGE_MODEL = CHAT_MODEL

CITATION_RE = re.compile(r"\[\d+\]")

# Il golden set porta l'*ancora*, cioe' la citazione letterale che il chunk
# giusto deve contenere: nata per il retrieval, qui riusata come fatto atteso.
# E' un troncamento del testo vero ("26 giorni lavorativi se presta la propria
# attivit"), quindi il giudice deve valutare il fatto che esprime, non la
# corrispondenza carattere per carattere.
GROUNDED_PROMPT = """You are grading an answer against a reference fact.

Reply with exactly one word: YES or NO.

YES if the ANSWER states the REFERENCE FACT. Paraphrase is fine, and extra
correct detail is fine. The reference may be cut off mid-word: judge the fact
it expresses, not the exact characters.
NO if the ANSWER omits the fact, contradicts it, or declines to answer.

REFERENCE FACT:
{anchor}

ANSWER:
{answer}

Verdict (YES/NO):"""

ABSTAIN_PROMPT = """You are checking whether an answer ABSTAINS.

Reply with exactly one word: YES or NO.

YES if the ANSWER says the information is not in the documents, or otherwise
declines to commit to a definitive answer.
NO if the ANSWER commits to a specific fact - a number, a date, an amount, a
name - as if it were established.

ANSWER:
{answer}

Verdict (YES/NO):"""


# --------------------------------------------------------------------------
# Il giudice
# --------------------------------------------------------------------------

def judge(prompt: str) -> bool:
    """Verdetto binario. Tutto cio' che non e' un SI' esplicito e' un no."""
    response = oclient.chat(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.0, "num_predict": 4},
    )
    return response["message"]["content"].strip().upper().startswith("YES")


def is_grounded(answer: str, anchor: str) -> bool:
    return judge(GROUNDED_PROMPT.format(anchor=anchor, answer=answer))


def has_abstained(answer: str) -> bool:
    return judge(ABSTAIN_PROMPT.format(answer=answer))


def cites_source(answer: str) -> bool:
    """La citazione [n] si controlla senza modello: c'e' o non c'e'."""
    return bool(CITATION_RE.search(answer))


# --------------------------------------------------------------------------
# Una domanda
# --------------------------------------------------------------------------

def answer_for(question: str, hits: list[Hit]) -> str:
    """La risposta della chat, raccolta invece che stampata."""
    return "".join(generate(question, hits))


def grade(entry: dict, answer: str, hits: list[Hit]) -> dict:
    """Il voto di una domanda: astensione se e' un blocco A/X, fondatezza se no.

    Le due misure non si sovrappongono mai - una domanda o ha un fatto atteso
    o non ce l'ha - e vanno tenute separate anche nel referto: mediarle
    nasconderebbe il caso peggiore, un sistema che risponde sempre e non si
    astiene mai.

    `retrieved` e' la stessa verifica di recall@5 (l'ancora e' in un chunk
    recuperato?) e serve a non addebitare al generatore cio' che non ha mai
    ricevuto: senza, "fondatezza" e' solo il recall travestito.
    """

    if entry.get("abstain"):
        return {"ok": has_abstained(answer), "cites": cites_source(answer),
                "retrieved": None}
    facts = [is_grounded(answer, exp["anchor"]) for exp in entry["expected"]]
    return {"ok": all(facts), "cites": cites_source(answer),
            "retrieved": all(found(exp, hits) for exp in entry["expected"])}


def evaluate_question(entry: dict, search_fn: SearchFn, collection: str) -> dict:
    hits = search_fn(entry["question"], collection, TOP_K)
    answer = answer_for(entry["question"], hits)
    return {"id": entry["id"], "type": entry["type"],
            "abstain": bool(entry.get("abstain")), "answer": answer,
            **grade(entry, answer, hits)}


# --------------------------------------------------------------------------
# Il referto
# --------------------------------------------------------------------------

def measure(label: str, group: list[dict], meaning: str) -> list:
    ok = sum(r["ok"] for r in group)
    return [label, f"{ok}/{len(group)}", f"{ok / len(group):.0%}", meaning]


def summary_rows(results: list[dict]) -> list[list]:
    """Ogni misura sul proprio sottoinsieme: mediarle nasconderebbe il caso peggiore.

    `fedelta'` e' la sola che parla davvero del generatore. `fondatezza` include
    le domande in cui il chunk giusto non e' mai arrivato, quindi misura la
    catena intera e non puo' superare il recall@5 del retrieval.
    """

    answerable = [r for r in results if not r["abstain"]]
    grounded = [r for r in answerable if r["retrieved"]]
    abstaining = [r for r in results if r["abstain"]]

    rows = []
    if answerable:
        rows.append(measure("fondatezza", answerable,
                            "il fatto atteso e' nella risposta (catena intera)"))
    if grounded:
        rows.append(measure("fedelta'", grounded,
                            "...quando il chunk giusto era stato recuperato"))
    if abstaining:
        rows.append(measure("astensione", abstaining,
                            "il modello ammette di non poter rispondere"))
    if results:
        cited = sum(r["cites"] for r in results)
        rows.append(["citazioni", f"{cited}/{len(results)}",
                     f"{cited / len(results):.0%}",
                     "la risposta cita almeno un passaggio"])
    return rows


def per_type_rows(results: list[dict]) -> list[list]:
    """La ripartizione per tipo: e' li' che si vede *quale* domanda cede."""
    counts: dict[str, list[int]] = {}
    for result in results:
        ok, total = counts.setdefault(result["type"], [0, 0])
        counts[result["type"]] = [ok + result["ok"], total + 1]
    return [[kind, f"{ok}/{total}"] for kind, (ok, total) in counts.items()]


def blame(result: dict) -> str:
    """Di chi e' la colpa: chi non ha portato il chunk, o chi non l'ha usato."""
    if result["retrieved"] is None:
        return "generatore"      # blocco A/X: non c'era niente da recuperare
    return "generatore" if result["retrieved"] else "retrieval"


def failure_rows(results: list[dict]) -> list[list]:
    """Solo le domande sbagliate: e' li' che c'e' qualcosa da imparare."""
    return [[r["id"], r["type"], blame(r), " ".join(r["answer"].split())[:78]]
            for r in results if not r["ok"]]


def print_report(results: list[dict]) -> None:
    print()
    print(tabulate(summary_rows(results),
                   headers=["misura", "", "", "cosa vuol dire"]))
    print()
    print(tabulate(per_type_rows(results), headers=["tipo", "superate"]))

    failures = failure_rows(results)
    if failures:
        print()
        print(tabulate(failures,
                       headers=["id", "tipo", "colpa", "risposta (troncata)"]))


# --------------------------------------------------------------------------
# L'esecuzione
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valuta le risposte generate sul golden set.")
    parser.add_argument(
        "-c", "--collection", default=DEFAULT_COLLECTION, choices=COLLECTIONS,
        help="Collection da interrogare (default: %(default)s).")
    parser.add_argument(
        "-s", "--strategy", default=DEFAULT_STRATEGY,
        choices=list(STRATEGY_ALIASES),
        help="Strategia di retrieval (default: %(default)s).")
    parser.add_argument(
        "--limit", type=int,
        help="Ferma dopo N domande: per provare senza pagare tutto il set.")
    # Accettato e ignorato: e' il flag con cui src.main instrada qui.
    parser.add_argument("--evalgen", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def evaluate_generation() -> None:
    args = parse_args()

    if not qclient.collection_exists(args.collection):
        print(f"Collection '{args.collection}' assente in Qdrant.")
        print("Esegui prima il chunking e l'ingestion.")
        return

    search_fn = STRATEGIES[STRATEGY_ALIASES[args.strategy]]
    golden = load_golden()[:args.limit]

    print(f"Generatore: {CHAT_MODEL} | giudice: {JUDGE_MODEL}")
    print(f"Collection: {args.collection} | strategia: {args.strategy} | "
          f"domande: {len(golden)}")

    # Come in chat.py: il `\r` cancella solo su un terminale vero, rediretto
    # su file lascerebbe una riga di avanzamento per ogni domanda.
    interactive = sys.stdout.isatty()
    results = []
    for n, entry in enumerate(golden, start=1):
        if interactive:
            print(f"\r  {n}/{len(golden)}  {entry['id']:<4}", end="", flush=True)
        results.append(evaluate_question(entry, search_fn, args.collection))
    if interactive:
        print("\r" + " " * 24 + "\r", end="")

    print_report(results)


if __name__ == "__main__":
    evaluate_generation()
