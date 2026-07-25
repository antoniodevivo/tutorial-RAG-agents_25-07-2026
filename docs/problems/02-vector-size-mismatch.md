# 02 — dimensione del vettore Qdrant non corrisponde a `embeddinggemma`

**Dove:** `src/scripts/qdrant/ingestion.py`, alla creazione delle collection
**Stato:** risolto

## Il sintomo

Non ancora osservato in produzione (trovato in revisione codice, prima del
primo `--ingest` su questo corpus), ma garantito al primo upsert:

```python
vectors_config=models.VectorParams(
    size=1536, distance=models.Distance.COSINE),
```

`1536` è la dimensione tipica degli embedding OpenAI
(`text-embedding-ada-002` / `3-small`). Il modello effettivamente usato per
generare gli embedding è `embeddinggemma` via Ollama
([chunking_simple.py:20](../../src/scripts/chunking_simple.py#L20)), che
restituisce vettori a **768** dimensioni — misurato direttamente, vedi
[problema 01, difetto 3](01-embedding-context-overflow.md#difetto-3--il-testo-vuoto-produce-un-vettore-di-dimensione-0):

```
oclient.embeddings(model="embeddinggemma", prompt="   ")
# -> embedding di dimensione 768
```

Con la collection configurata a 1536, `qclient.upsert()` fallisce su ogni
punto con un errore di dimensione del vettore, dopo aver già speso la
chiamata di embedding. `1536` non veniva da una misura: era un valore
copiato da un altro provider e mai verificato contro il modello davvero in
uso.

## La causa

`ingestion.py` definiva la dimensione del vettore come costante locale,
scollegata dal modello di embedding definito in `chunking_simple.py`. Le due
informazioni — quale modello embedda e quanto è lungo il suo output — vivono
in file diversi con nessuna verifica che restino coerenti.

## Il fix

La dimensione diventa una costante accanto a `EMBED_MODEL`, così i due valori
si aggiornano insieme:

```python
# chunking_simple.py
EMBED_MODEL = "embeddinggemma"
EMBED_DIM = 768
```

e `ingestion.py` la importa invece di ridichiararla:

```python
from ..chunking_simple import EMBED_DIM
...
vectors_config=models.VectorParams(size=EMBED_DIM, distance=models.Distance.COSINE)
```

Non elimina il rischio — è comunque un numero scritto a mano, non letto dal
modello — ma elimina la copia duplicata che poteva disallinearsi in
silenzio.

## Attenzione se hai già lanciato `--ingest`

Il fix vale solo per le collection create **da questo punto in poi**:
`ingestion.py` chiama `recreate_collection` solo se `has_collection()` è
`False`. Se `--ingest` è già girato con `size=1536`, la collection esiste
già con la dimensione sbagliata e il fix non la tocca: va droppata a mano
(`qclient.delete_collection(...)`) prima del prossimo `--ingest`, altrimenti
l'upsert continua a fallire sulla stessa collection.

## Cosa resta fragile

- **`EMBED_DIM` è un numero misurato a mano, come `MAX_CHARS`.** Cambiare
  `EMBED_MODEL` senza aggiornare `EMBED_DIM` riproduce esattamente questo
  bug, solo con un valore diverso.
- **Nessun controllo a runtime.** Un modo più robusto sarebbe imporre
  `size=len(embed("_"))` alla creazione della collection, così la dimensione
  è sempre quella vera e non richiede una seconda costante da tenere in
  sync — non fatto qui per non aggiungere una chiamata di rete solo per una
  verifica.
