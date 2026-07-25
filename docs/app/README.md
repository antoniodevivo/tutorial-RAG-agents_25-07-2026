# Il retrieval: cosa c'è dentro e perché

Documentazione di [`src/scripts/retrieval.py`](../../src/scripts/retrieval.py):
tre strategie di recupero sul corpus CCNL, tutte misurate con lo stesso
`recall@5` sullo stesso golden set.

## I documenti

| File | Contenuto |
| --- | --- |
| [01-cosa-fa-retrieval.md](01-cosa-fa-retrieval.md) | Il codice funzione per funzione: le tre strategie, i parametri, come si lancia |
| [02-keyword-sigle-bm25.md](02-keyword-sigle-bm25.md) | **La teoria della ricerca per parole chiave**: tokenizzazione, IDF, BM25, e perché le sigle sono il caso difficile — con i numeri veri del corpus |
| [03-fusione-rrf-e-reranking.md](03-fusione-rrf-e-reranking.md) | Perché si fondono le posizioni e non i punteggi; bi-encoder contro cross-encoder |
| [04-recall-at-5.md](04-recall-at-5.md) | La metrica: cosa misura, cosa non misura, come leggerla |

## Il flusso completo

```
docs/pdf/*.pdf
    |  pdf2md.py            marcatori <!-- pagina: N --> per non perdere la pagina
    v
docs/md/*.md
    |  chunking_simple.py   2 strategie -> chunk con id stabile + embedding
    v
docs/chunks/*.jsonl
    |  qdrant/ingestion.py  upsert nelle 2 collection
    v
Qdrant
    |  retrieval.py         3 strategie di ricerca, misurate su eval/golden_set.jsonl
    v
recall@5
```

Le due collection corrispondono alle due strategie di chunking, e si valutano
in parallelo: `fixed_size_chunking` (taglio a lunghezza fissa, cieco alla
struttura) e `from_structure_chunking` (taglio sui titoli Markdown).

## Come si lancia

```bash
# dalla radice del repo, non da src/
python -m src.scripts.retrieval
```

Prerequisiti, nell'ordine: `ollama pull <modello di embedding>`, le collection
create in Qdrant, l'ingestion eseguita. Senza collection lo script lo dice e si
ferma invece di fallire a metà.

## Il principio che tiene insieme tutto

Le tre strategie sono **cumulative**, non alternative:

```
1. semantica            trova per significato
2. + BM25 e RRF         aggiunge il letterale, che il significato non copre
3. + cross-encoder      riordina, non recupera
```

Ognuna copre un buco della precedente, e il golden set ha domande costruite
apposta per ciascun buco. Il punto dell'esercizio non è che la terza vince: è
capire *di quanto* e *su quali domande* — e scoprire dove invece non cambia
niente, che è l'informazione più utile delle tre.
