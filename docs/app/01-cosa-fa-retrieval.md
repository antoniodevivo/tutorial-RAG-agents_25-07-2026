# Cosa fa `retrieval.py`

Walkthrough del codice. Per la teoria dietro le scelte:
[BM25 e sigle](02-keyword-sigle-bm25.md), [RRF e reranking](03-fusione-rrf-e-reranking.md).

## Il tipo che circola: `Hit`

Tutte e tre le strategie restituiscono `list[Hit]`. Un `Hit` è un chunk
recuperato più il punteggio di **chi l'ha trovato**:

```python
@dataclass
class Hit:
    chunk_id: str   # l'UUID del punto Qdrant
    text: str       # il testo del chunk
    document: str   # da quale documento viene
    section: str    # il percorso dei titoli
    page: str
    score: float
```

Il campo `score` cambia significato da una strategia all'altra — similarità
coseno, punteggio BM25, punteggio RRF, voto del reranker — e **non è
confrontabile tra strategie diverse**. È il motivo per cui la fusione lavora
sulle posizioni: vedi [03](03-fusione-rrf-e-reranking.md).

`Hit.from_point()` è l'adattatore da punto Qdrant: legge `payload["text"]` e
`payload["metadata"]`, così il resto del codice non sa niente della forma del
payload.

## 1. Ricerca semantica

```python
def semantic_search(query, collection, limit=TOP_K) -> list[Hit]:
    response = qclient.query_points(
        collection_name=collection,
        query=embed(query),
        limit=limit,
        with_payload=True,
    )
    return [Hit.from_point(p) for p in response.points]
```

Tre righe, e una sola cosa da non sbagliare: `embed` è **importato da
`chunking_simple`**, non riscritto qui.

```python
from .chunking_simple import EMBED_MODEL, embed
```

Query e documenti devono passare dallo stesso modello. Un indice costruito con
un modello e interrogato con un altro non solleva nessun errore: restituisce
risultati, e sono rumore. È il tipo di guasto che si scopre settimane dopo,
guardando un `recall@5` inspiegabilmente basso.

## 2. Ricerca hybrid

Tre pezzi: un indice BM25, la ricerca sparsa, la fusione.

### `Bm25Index`

Costruito in memoria dai testi della collection. Alla costruzione calcola una
volta sola quello che serve a tutte le query:

- `freqs[i]` — quante volte ogni token compare nel chunk `i`
- `lengths[i]` — lunghezza del chunk `i` in token
- `avgdl` — lunghezza media dei chunk
- `idf[t]` — quanto è raro, quindi informativo, il token `t`

`load_corpus()` scarica tutti i punti con `qclient.scroll()` paginando finché
l'offset non torna `None`. BM25 ha bisogno del **corpus intero**: l'IDF è una
statistica globale, non si può calcolare sui soli risultati di una query.

L'indice è in `_INDEX_CACHE` per collection: si costruisce al primo uso e
resta lì per tutte le domande del golden set.

> **Perché non lo fa Qdrant.** Qdrant supporta BM25 nativo con i vettori
> sparsi, ma solo se la collection è stata creata con uno slot sparso
> (`sparse_vectors_config`) — queste non ce l'hanno. Su 521 chunk ricalcolarlo
> in Python costa millisecondi, e in un tutorial ha il vantaggio di rendere la
> formula leggibile invece di nasconderla dietro una chiamata.

### `rrf_fuse`

```python
scores[hit.chunk_id] += 1.0 / (RRF_K + rank)
```

Somma su più classifiche il reciproco della posizione. Dettaglio e esempio
numerico in [03](03-fusione-rrf-e-reranking.md).

### `hybrid_search`

```python
dense  = semantic_search(query, collection, CANDIDATES)   # 30
sparse = bm25_search(query, collection, CANDIDATES)       # 30
return rrf_fuse([dense, sparse], limit)                   # 5
```

Le due gambe recuperano **30** candidati ciascuna e la fusione ne tiene 5.
Recuperare 30 per tenerne 5 non è spreco: la fusione ha bisogno di vedere un
chunk in _entrambe_ le classifiche per premiarlo, e un chunk che sta ottavo nel
denso e nono nello sparso è esattamente il caso che l'ibrido deve far salire.
Con `CANDIDATES = 5` quel chunk non lo vedrebbe nessuno.

## 3. hybrid + reranker

```python
candidates = hybrid_search(query, collection, CANDIDATES)  # 30
return cross_encoder_rerank(query, candidates, limit)      # 5
```

Il reranker chiama `score_pair()` una volta per candidato: 30 chiamate al
modello per ogni domanda. È il pezzo lento, ed è il motivo per cui si riordina
solo la coda e non tutto il corpus.

**Il reranker non recupera niente.** Il suo tetto è il `recall@30` della
ricerca hybrid: se il chunk giusto non è tra i 30 candidati, nessun riordino lo
farà comparire. Da cui la regola diagnostica scritta nel docstring: se la
strategia 3 non migliora sulla 2, il collo di bottiglia è a monte, e cambiare
reranker non serve a niente.

Sul perché `score_pair` è un LLM e non un vero cross-encoder:
[03](03-fusione-rrf-e-reranking.md#il-cross-encoder).

## Il calcolo del recall

`recall_at_k(search_fn, collection, k)` prende **una funzione di ricerca** e la
misura. Tutte e tre le strategie hanno la stessa firma:

```python
SearchFn = Callable[[str, str, int], list[Hit]]   # query, collection, limit
```

per questo `STRATEGIES` è un semplice dizionario nome → funzione, e aggiungere
una quarta strategia non richiede di toccare l'harness.

Il criterio di successo è in `found()`:

```python
anchor in normalize(hit.text) and hit.document == expected["document"]
```

Un chunk conta se **viene dal documento giusto** e **contiene l'ancora attesa**.
Non l'indice di riga, non l'id: quelli cambiano a ogni modifica dei parametri
di chunking, l'ancora no. Dettagli in [04](04-recall-at-5.md).

`normalize()` compatta gli spazi, perché la strategia A unisce le righe in un
unico flusso di parole mentre la B conserva gli a-capo: senza, la stessa ancora
matcherebbe su una collection e no sull'altra, e il confronto tra le due
strategie di chunking — che è il punto dell'esercizio — sarebbe falsato.

## I parametri, e cosa succede a muoverli

| Costante     | Valore | Effetto                                                                                              |
| ------------ | ------ | ---------------------------------------------------------------------------------------------------- |
| `TOP_K`      | 5      | La K di recall@5. Alzarlo alza il recall e basta: non è un miglioramento, è una misura diversa       |
| `CANDIDATES` | 30     | Profondità del recupero prima di fondere o riordinare. Alzarlo alza il tetto del reranker e il costo |
| `RRF_K`      | 60     | Quanto smorzare il peso delle prime posizioni                                                        |
| `BM25_K1`    | 1.5    | Quanto satura la frequenza di un termine                                                             |
| `BM25_B`     | 0.75   | Quanto penalizzare i chunk lunghi                                                                    |

## Cosa non c'è

- **Nessun filtro sui metadati.** `visibility`, `version` e `date` sono nel
  payload ma nessuna strategia li usa. In produzione il filtro per visibilità
  va applicato _prima_ del ranking, non dopo.
- **Nessuna cache degli embedding di query.** Ogni esecuzione del golden set
  ricalcola 27 embedding di query.
- **Nessuna generazione.** Qui si misura solo il recupero. Le 5 domande di
  astensione del golden set non sono valutabili a questo livello.
