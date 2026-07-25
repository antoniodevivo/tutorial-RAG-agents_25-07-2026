"""Tre strategie di retrieval sulle collection Qdrant, misurate con recall@5.

    python -m src.scripts.retrieval

Le tre strategie sono cumulative, ognuna aggiunge un pezzo alla precedente:

    1. semantica          embedding della query -> vicini nel vettoriale
    2. hybrid             semantica + BM25, fusi con RRF
    3. hybrid + reranker   le prime N candidate riordinate da un cross-encoder

Il punteggio e' recall@5 sul golden set in eval/golden_set.jsonl: un chunk
conta come recuperato se il suo testo contiene l'ancora attesa e viene dal
documento atteso. Le domande di astensione (aggregazione e risposta assente)
non hanno chunk atteso e sono escluse dal calcolo: si valutano sul
comportamento del generatore, non del retrieval.
"""

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from tabulate import tabulate

from ..clients.ollama import oclient
from ..clients.qdrant import qclient
from .chunking_simple import EMBED_MODEL, embed

BASE_DIR = Path(__file__).resolve().parent.parent.parent
GOLDEN_PATH = BASE_DIR / "eval" / "golden_set.jsonl"

COLLECTIONS = ["fixed_size_chunking", "from_structure_chunking"]

TOP_K = 5        # la K di recall@5
CANDIDATES = 30  # quanti candidati raccogliere prima di fondere o riordinare

# RRF: costante che smorza il peso delle prime posizioni. 60 e' il valore del
# paper originale (Cormack et al., 2009) ed e' quello che quasi tutti usano.
RRF_K = 60

# BM25, parametri classici: k1 satura il contributo della frequenza, b regola
# quanto penalizzare i documenti lunghi.
BM25_K1 = 1.5
BM25_B = 0.75

# Il reranker. Un cross-encoder vero (es. cross-encoder/ms-marco-MiniLM-L-6-v2)
# richiede sentence-transformers, che qui non c'e': la sua controparte
# disponibile e' un LLM che assegna un punteggio leggendo query e documento
# *insieme*. Stessa forma - nessun embedding indipendente, un solo passaggio
# congiunto - costo molto piu' alto. Vedi cross_encoder_rerank().
RERANK_MODEL = "llava-phi3:latest"

TOKEN_RE = re.compile(r"\w+", re.UNICODE)
WS_RE = re.compile(r"\s+")


@dataclass
class Hit:
    """Un chunk recuperato, con il punteggio della strategia che l'ha trovato."""
    chunk_id: str
    text: str
    document: str
    section: str
    page: str
    score: float = 0.0

    @classmethod
    def from_point(cls, point, score=None) -> "Hit":
        payload = point.payload or {}
        meta = payload.get("metadata", {})
        return cls(
            chunk_id=str(point.id),
            text=payload.get("text", ""),
            document=meta.get("document", ""),
            section=meta.get("section", ""),
            page=str(meta.get("page", "")),
            score=score if score is not None else getattr(point, "score", 0.0),
        )


# --------------------------------------------------------------------------
# 1. Ricerca semantica
# --------------------------------------------------------------------------

def semantic_search(query: str, collection: str, limit: int = TOP_K) -> list[Hit]:
    """Vicini piu' prossimi della query nello spazio degli embedding.

    La query passa dallo *stesso* modello usato per i chunk: interrogare un
    indice con un modello diverso da quello che l'ha costruito produce
    risultati plausibili e sbagliati, senza nessun errore visibile.
    """

    response = qclient.query_points(
        collection_name=collection,
        query=embed(query),
        limit=limit,
        with_payload=True,
    )
    return [Hit.from_point(p) for p in response.points]


# --------------------------------------------------------------------------
# 2. BM25 + fusione RRF
# --------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


@dataclass
class Bm25Index:
    """BM25 in memoria sui testi della collection.

    Qdrant sa fare BM25 da solo con i vettori sparsi, ma solo se la collection
    e' stata creata con uno slot sparso: queste non ce l'hanno. Ricalcolarlo
    qui costa poco su un corpus di questa taglia e rende visibile la formula
    """

    hits: list[Hit] = field(default_factory=list)
    freqs: list[Counter] = field(default_factory=list)
    lengths: list[int] = field(default_factory=list)
    idf: dict[str, float] = field(default_factory=dict)
    avgdl: float = 0.0

    @classmethod
    def build(cls, hits: Iterable[Hit]) -> "Bm25Index":
        index = cls(hits=list(hits))
        df: Counter = Counter()
        for hit in index.hits:
            tokens = tokenize(hit.text)
            index.freqs.append(Counter(tokens))
            index.lengths.append(len(tokens))
            df.update(set(tokens))

        n = len(index.hits)
        index.avgdl = (sum(index.lengths) / n) if n else 0.0
        for term, freq in df.items():
            index.idf[term] = math.log(1 + (n - freq + 0.5) / (freq + 0.5))
        return index

    def search(self, query: str, limit: int = TOP_K) -> list[Hit]:
        query_tokens = tokenize(query)
        scored: list[tuple[float, int]] = []

        for i, freqs in enumerate(self.freqs):
            score = 0.0
            length = self.lengths[i]
            for term in query_tokens:
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                norm = 1 - BM25_B + BM25_B * \
                    (length / self.avgdl if self.avgdl else 0)
                score += self.idf.get(term, 0.0) * (tf * (BM25_K1 + 1)) / (
                    tf + BM25_K1 * norm
                )
            if score > 0:
                scored.append((score, i))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        out = []
        for score, i in scored[:limit]:
            hit = self.hits[i]
            out.append(Hit(hit.chunk_id, hit.text, hit.document,
                           hit.section, hit.page, score))
        return out


_INDEX_CACHE: dict[str, Bm25Index] = {}


def load_corpus(collection: str) -> list[Hit]:
    """Scarica tutti i chunk della collection: BM25 ha bisogno del corpus intero."""
    hits, offset = [], None
    while True:
        points, offset = qclient.scroll(
            collection_name=collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        hits.extend(Hit.from_point(p, score=0.0) for p in points)
        if offset is None:
            return hits


def bm25_index(collection: str) -> Bm25Index:
    if collection not in _INDEX_CACHE:
        _INDEX_CACHE[collection] = Bm25Index.build(load_corpus(collection))
    return _INDEX_CACHE[collection]


def bm25_search(query: str, collection: str, limit: int = TOP_K) -> list[Hit]:
    return bm25_index(collection).search(query, limit)


def rrf_fuse(rankings: list[list[Hit]], limit: int = TOP_K) -> list[Hit]:
    """Reciprocal Rank Fusion: somma 1/(K + posizione) su piu' classifiche.

    Fonde le *posizioni*, non i punteggi: BM25 e la similarita' coseno vivono
    su scale incomparabili, e normalizzarle richiederebbe assunzioni che non
    reggono da una query all'altra. Un chunk trovato da entrambi i sistemi,
    anche solo a meta' classifica, batte un chunk primo in una sola.
    """

    scores: dict[str, float] = defaultdict(float)
    by_id: dict[str, Hit] = {}

    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk_id] += 1.0 / (RRF_K + rank)
            by_id.setdefault(hit.chunk_id, hit)

    ordered = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    fused = []
    for chunk_id, score in ordered[:limit]:
        hit = by_id[chunk_id]
        fused.append(Hit(hit.chunk_id, hit.text, hit.document,
                         hit.section, hit.page, score))
    return fused


def hybrid_search(query: str, collection: str, limit: int = TOP_K) -> list[Hit]:
    """Semantica e BM25 in parallelo, fuse con RRF.

    Le due gambe si coprono i buchi a vicenda: il denso trova le parafrasi che
    non condividono una parola col testo, lo sparso trova le sigle e i numeri
    di articolo che l'embedding schiaccia. Il golden set ha domande apposta
    per ciascuno dei due casi (blocchi P e C).
    """

    dense = semantic_search(query, collection, CANDIDATES)
    sparse = bm25_search(query, collection, CANDIDATES)
    return rrf_fuse([dense, sparse], limit)


# --------------------------------------------------------------------------
# 3. hybrid + reranker cross-encoder
# --------------------------------------------------------------------------

SCORE_PROMPT = """Valuta quanto il DOCUMENTO risponde alla DOMANDA.
Rispondi SOLO con un numero intero da 0 a 10, senza altro testo.

DOMANDA: {query}

DOCUMENTO:
{document}

Punteggio (0-10):"""


def score_pair(query: str, document: str) -> float:
    """Punteggio di rilevanza leggendo query e documento insieme.

    E' la proprieta' che definisce un cross-encoder e che il bi-encoder non
    ha: qui il modello vede i due testi nello stesso contesto e puo' valutare
    la corrispondenza termine a termine, invece di confrontare due vettori
    calcolati separatamente. Il prezzo e' che il costo cresce con il numero
    di candidati, per questo si riordina solo la coda del recupero.
    """

    response = oclient.chat(
        model=RERANK_MODEL,
        messages=[{"role": "user", "content": SCORE_PROMPT.format(
            query=query, document=document[:4000])}],
        options={"temperature": 0.0, "num_predict": 8},
    )
    match = re.search(r"\d+", response["message"]["content"])
    return float(match.group()) if match else 0.0


def cross_encoder_rerank(query: str, candidates: list[Hit],
                         limit: int = TOP_K) -> list[Hit]:
    """Riordina i candidati con il cross-encoder e tiene i primi `limit`."""
    scored = [Hit(c.chunk_id, c.text, c.document, c.section, c.page,
                  score_pair(query, c.text)) for c in candidates]
    scored.sort(key=lambda hit: hit.score, reverse=True)
    return scored[:limit]


def hybrid_rerank_search(query: str, collection: str,
                         limit: int = TOP_K) -> list[Hit]:
    """hybrid per il richiamo, cross-encoder per la precisione.

    Il reranker non puo' recuperare cio' che il retrieval non ha portato: il
    suo tetto e' il recall@CANDIDATES della ricerca hybrid. Se la strategia 3
    non migliora sulla 2, il collo di bottiglia e' a monte e alzare la qualita'
    del reranker non serve a niente.
    """

    candidates = hybrid_search(query, collection, CANDIDATES)
    return cross_encoder_rerank(query, candidates, limit)


# --------------------------------------------------------------------------
# recall@5
# --------------------------------------------------------------------------

SearchFn = Callable[[str, str, int], list[Hit]]


def normalize(text: str) -> str:
    """Spazi compattati: la strategia A unisce le righe, la B le tiene."""
    return WS_RE.sub(" ", text)


def load_golden() -> list[dict]:
    return [json.loads(line)
            for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def found(expected: dict, hits: list[Hit]) -> bool:
    """Un'attesa e' soddisfatta se un chunk del documento giusto la contiene."""
    anchor = normalize(expected["anchor"])
    return any(hit.document == expected["document"]
               and anchor in normalize(hit.text)
               for hit in hits)


def recall_at_k(search_fn: SearchFn, collection: str, k: int = TOP_K) -> dict:
    """recall@k sul golden set, con la ripartizione per tipo di domanda.

    Due numeri, perche' misurano cose diverse:
      - `recall`: quante delle attese totali sono state recuperate. Le domande
        multi-passaggio pesano per i due chunk che richiedono.
      - `complete`: quante domande hanno recuperato *tutte* le proprie attese.
        E' l'unica che conta per il multi-passaggio: mezza risposta e' sbagliata.
    """

    golden = [q for q in load_golden() if q["expected"]]
    per_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rows, n_found, n_total, n_complete = [], 0, 0, 0

    for question in golden:
        hits = search_fn(question["question"], collection, k)
        flags = [found(exp, hits) for exp in question["expected"]]

        n_found += sum(flags)
        n_total += len(flags)
        n_complete += all(flags)
        per_type[question["type"]][0] += all(flags)
        per_type[question["type"]][1] += 1
        rows.append({
            "id": question["id"],
            "type": question["type"],
            "found": sum(flags),
            "expected": len(flags),
            "complete": all(flags),
        })

    return {
        "collection": collection,
        "recall": n_found / n_total if n_total else 0.0,
        "complete": n_complete / len(golden) if golden else 0.0,
        "per_type": {t: (ok, tot) for t, (ok, tot) in per_type.items()},
        "rows": rows,
    }


STRATEGIES: dict[str, SearchFn] = {
    "semantic": semantic_search,
    "hybrid (RRF)": hybrid_search,
    "hybrid + reranker": hybrid_rerank_search,
}


def evaluate_all(collections: list[str] | None = None) -> None:
    """Esegue le tre strategie su ogni collection e stampa il confronto."""
    available = {c.name for c in qclient.get_collections().collections}
    targets = [c for c in (collections or COLLECTIONS) if c in available]

    if not targets:
        print(f"Nessuna collection trovata in Qdrant (attese: {COLLECTIONS}).")
        print("Esegui prima il chunking e l'ingestion.")
        return

    print(f"Modello di embedding: {EMBED_MODEL} | reranker: {RERANK_MODEL}")
    table, types = [], []

    for collection in targets:
        for label, search_fn in STRATEGIES.items():
            report = recall_at_k(search_fn, collection)
            table.append([collection, label,
                          f"{report['recall']:.0%}",
                          f"{report['complete']:.0%}"])
            for kind, (ok, tot) in sorted(report["per_type"].items()):
                types.append([collection, label, kind, f"{ok}/{tot}"])

    print()
    print(tabulate(table, headers=["collection", "strategia",
                                   "recall@5", "domande complete"]))
    print()
    print(tabulate(types, headers=["collection", "strategia",
                                   "tipo", "complete"]))


if __name__ == "__main__":
    evaluate_all()
