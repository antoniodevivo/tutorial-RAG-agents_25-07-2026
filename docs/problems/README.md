# Problemi incontrati

Guasti reali della pipeline, con la diagnosi e il fix. Non un changelog: qui
sta **perché** una cosa si è rotta, che è l'unica parte che serve la prossima
volta.

| #                                      | Problema                                                      | Dove                 | Stato   |
| -------------------------------------- | ------------------------------------------------------------- | -------------------- | ------- |
| [01](01-embedding-context-overflow.md) | `input length exceeds the context length` durante il chunking | `chunking_simple.py` | risolto |
| [02](02-vector-size-mismatch.md) | Dimensione del vettore Qdrant (1536) diversa da quella di `embeddinggemma` (768) | `qdrant/ingestion.py` | risolto |
| [03](03-generatore-troppo-piccolo.md) | Il generatore copia il contesto invece di rispondere — e l'ipotesi ovvia (contesto troncato) era falsa | `chat.py` | risolto |
| [04](04-domanda-generica-sul-corpus.md) | "Cosa mi sai dire?" — 5 chunk su 291 documenti presentati come se fossero la mappa dell'indice. Generatore corretto, retrieval corretto, risposta sbagliata | `chat.py` | aperto |

## Problemi noti ancora aperti

Trovati e documentati, non ancora sistemati:

| Problema                                                                                                                                                                        | Dove                               | Impatto                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `ingestion.py` non crea le collection: l'upsert su una collection inesistente fallisce                                                                                          | `qdrant/ingestion.py`              | blocca l'ingestion                                                                                        |
| Client Qdrant 1.18.0 contro server 1.15.4: tre minor version di scarto, il client lo segnala come non supportato                                                                | `clients/qdrant.py`                | `UserWarning` a ogni chiamata, comportamento non garantito su query e upsert                              |
| `Art.118` del CCNL metalmeccanico non è un titolo Markdown: la conversione l'ha degradato a testo semplice, quindi la strategia strutturale non lo vede come confine di sezione | `docs/md/ccnl_metalmeccanico_*.md` | un articolo su 143 finisce nella sezione sbagliata                                                        |
| Il CV produce 0 chunk: il PDF non contiene testo estraibile                                                                                                                     | `docs/md/CV_*.md`                  | il documento risulta indicizzato ma è vuoto, e nessuna metrica di retrieval se ne accorge                 |
| Il tokenizer BM25 (`\w+`) polverizza le sigle puntate: `E.BI.A.S.P.` → `['e','bi','a','s','p']`                                                                                 | `retrieval.py`                     | le sigle con punti sono irrecuperabili per via lessicale — vedi [teoria](../app/02-keyword-sigle-bm25.md) |
