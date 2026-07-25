# Fondere due classifiche, e poi riordinarle

Due meccanismi distinti che vengono spesso confusi. **RRF fonde** liste diverse
in una sola; il **reranker riordina** una lista sola. Il primo aumenta il
richiamo, il secondo la precisione.

## Perché non si sommano i punteggi

La tentazione è ovvia: BM25 dà un numero, il coseno dà un numero, si sommano.
Non funziona, per un motivo che si vede subito guardando le scale:

|                   | intervallo tipico | dipende da                                                         |
| ----------------- | ----------------- | ------------------------------------------------------------------ |
| similarità coseno | 0 → 1             | il modello di embedding                                            |
| BM25              | 0 → ~40           | quanti termini ha la query, quanto sono rari, la taglia del corpus |

BM25 non ha un massimo: una query di dieci termini rari produce punteggi molto
più alti di una query di due termini comuni, **sullo stesso corpus**. Sommare
significherebbe che l'una domina in un caso e l'altra nell'altro, in modo
imprevedibile da query a query.

Normalizzare (min-max, z-score) sposta il problema senza risolverlo: la
normalizzazione va fatta sui risultati di _quella_ query, quindi un punteggio
di 0.9 non vuol dire la stessa cosa in due domande diverse.

**RRF elimina il problema alla radice: butta via i punteggi e tiene solo le
posizioni.**

## Reciprocal Rank Fusion

```
RRF(d) =  Σ   1 / (K + posizione di d nella classifica i)
        i∈liste
```

Nel codice, con `K = 60`:

```python
for ranking in rankings:
    for rank, hit in enumerate(ranking, start=1):
        scores[hit.chunk_id] += 1.0 / (RRF_K + rank)
```

### Esempio numerico

Quattro chunk, due classifiche:

| chunk | posizione nel denso | posizione nello sparso |
| ----- | ------------------- | ---------------------- |
| A     | 1ª                  | 3ª                     |
| B     | —                   | 1ª                     |
| C     | 2ª                  | 2ª                     |
| D     | 3ª                  | —                      |

Con `K = 60`:

| chunk | calcolo     | RRF         |
| ----- | ----------- | ----------- |
| **A** | 1/61 + 1/63 | **0.03227** |
| **C** | 1/62 + 1/62 | **0.03226** |
| B     | 1/61        | 0.01639     |
| D     | 1/63        | 0.01587     |

Due cose da leggere in questa tabella:

1. **A e C sono praticamente pari.** Essere primo in una lista e terzo
   nell'altra vale quanto essere secondo in entrambe. RRF non premia
   l'eccellenza in una singola gamba, premia l'**accordo tra le gambe**.
2. **B, primo assoluto nello sparso, sta sotto entrambi.** Un chunk che una
   sola gamba considera perfetto perde contro un chunk che entrambe
   considerano buono. È il comportamento voluto: se il denso e lo sparso — che
   sbagliano in modi diversi — concordano, è un segnale molto più forte.

### Cosa fa `K`

`K` smorza la differenza tra le prime posizioni:

| K   | A (1ª + 3ª) | C (2ª + 2ª) | rapporto         |
| --- | ----------- | ----------- | ---------------- |
| 1   | 0.750       | 0.667       | A avanti del 12% |
| 60  | 0.03227     | 0.03226     | pari             |
| 200 | 0.009901    | 0.009901    | pari             |

Con `K` piccolo il primo posto pesa moltissimo; con `K` grande conta solo
_esserci in entrambe le liste_. Il valore 60 viene dal paper originale
(Cormack, Clarke, Buettcher, 2009) ed è il compromesso che quasi tutti usano.

### Perché 30 candidati e non 5

```python
dense  = semantic_search(query, collection, CANDIDATES)   # 30
sparse = bm25_search(query, collection, CANDIDATES)       # 30
return rrf_fuse([dense, sparse], limit)                   # 5
```

RRF premia l'accordo, ma può vederlo solo se entrambe le liste sono
abbastanza lunghe da contenere il chunk. Un chunk ottavo nel denso e nono nello
sparso è esattamente il caso che l'ibrido deve far emergere — e con
`CANDIDATES = 5` non comparirebbe in nessuna delle due liste.

## Il cross-encoder

### Bi-encoder: cosa fa la ricerca semantica

```
   query  ──> [modello] ──> vettore_q  ┐
                                       ├──> coseno ──> punteggio
   chunk  ──> [modello] ──> vettore_d  ┘
```

I due testi passano dal modello **separatamente**. Conseguenza pratica
enorme: i vettori dei chunk si calcolano **una volta sola**, in fase di
ingestion, e restano nell'indice. A query time si calcola un solo vettore e si
cerca il vicino più prossimo. È l'unico motivo per cui la ricerca vettoriale è
praticabile su milioni di documenti.

Il prezzo: query e documento non si vedono mai. Il vettore del chunk è stato
prodotto senza sapere che domanda gli sarebbe stata fatta — deve riassumere
_tutto_ il chunk in poche centinaia di numeri, e il dettaglio che risponde alla
domanda specifica può semplicemente non sopravvivere alla compressione.

### Cross-encoder: cosa fa il reranker

```
   [query ; chunk] ──> [modello] ──> punteggio di rilevanza
```

Un solo passaggio, i due testi **nello stesso contesto**. Il modello può
mettere in relazione un termine della domanda con un termine del documento,
cosa che due vettori calcolati separatamente non permettono. È molto più
accurato.

Il prezzo è simmetrico al vantaggio: **non si può precalcolare niente**. Il
punteggio dipende dalla coppia, quindi ogni domanda richiede un passaggio del
modello per ogni candidato.

|               | passaggi per query | precalcolabile |
| ------------- | ------------------ | -------------- |
| bi-encoder    | 1 (solo la query)  | sì, i chunk    |
| cross-encoder | 1 per candidato    | no             |

Su questo corpus: riordinare tutti i 521 chunk richiederebbe 521 chiamate per
ogni domanda. Riordinarne 30 ne richiede 30. Su un corpus vero da un milione di
chunk la prima opzione semplicemente non esiste.

**Da qui l'architettura a imbuto**, che è lo schema standard di ogni sistema di
ricerca serio:

```
1.000.000 chunk  ──[bi-encoder + BM25]──>  30  ──[cross-encoder]──>  5
      economico, approssimativo              costoso, accurato
```

### Il tetto del reranker

Il reranker **non recupera niente**: riordina quello che gli arriva. Quindi

```
recall@5 (hybrid + reranker)  ≤  recall@30 (hybrid)
```

Se il chunk giusto non è tra i 30 candidati, nessun riordino lo farà comparire.
È la diagnosi più utile che questa pipeline produce: **se la strategia 3 non
migliora sulla 2, il problema è a monte** — chunking, embedding, o `CANDIDATES`
troppo basso — e cambiare reranker non serve a niente.

### Il reranker di questo progetto

Un cross-encoder vero (`cross-encoder/ms-marco-MiniLM-L-6-v2` e simili) richiede
`sentence-transformers`, quindi torch: circa 2 GB di dipendenza non presenti in
questo ambiente. Al suo posto `score_pair()` usa un LLM via Ollama, con un
prompt che chiede un voto da 0 a 10:

```python
response = oclient.chat(
    model=RERANK_MODEL,
    messages=[{"role": "user", "content": SCORE_PROMPT.format(...)}],
    options={"temperature": 0.0, "num_predict": 8},
)
```

**Ha la stessa forma architetturale** — query e documento letti insieme, nessun
embedding indipendente, nessun precalcolo — a un costo per candidato molto più
alto e con punteggi più rumorosi (un LLM tende a concentrarsi su pochi valori,
tipicamente 7 e 8, il che riduce la capacità di ordinare).

`score_pair()` è il punto di sostituzione: installando `sentence-transformers`
si rimpiazza quella sola funzione con

```python
from sentence_transformers import CrossEncoder
_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

def score_pair(query, document):
    return float(_model.predict([(query, document[:4000])])[0])
```

e tutto il resto della pipeline resta identico. Nota: quel modello è addestrato
sull'inglese — su un corpus italiano serve un multilingua, per esempio
`BAAI/bge-reranker-v2-m3`.
