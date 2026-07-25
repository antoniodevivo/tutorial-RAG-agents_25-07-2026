# recall@5: cosa misura e come leggerlo

## La definizione

> Di tutti i chunk che **dovevano** essere recuperati, quanti sono comparsi tra
> i primi 5?

Solo il recupero. Non la qualità della risposta finale, non se il modello ha
capito il documento: se il chunk giusto non arriva nel contesto, tutto quello
che viene dopo è irrilevante. Per questo il recall si misura **da solo,
prima**.

Perché 5: è il numero di chunk che tipicamente si mettono nel contesto del
generatore. Misurare a K diverso dalla K che si usa davvero risponde a una
domanda che nessuno ha fatto.

## Da dove viene la verità

[`eval/golden_set.jsonl`](../../eval/golden_set.jsonl), 27 domande scritte a
mano leggendo i CCNL, 31 attese totali. Ogni attesa è una coppia
**documento + ancora**:

```json
{"id": "C1", "type": "codice",
 "question": "Cosa prevede l'art. 5 bis su MOG(S) e SGSL?",
 "expected": [{"document": "ccnl_metalmeccanico_industria_conflavoro",
               "anchor": "Adozione di MOG(S) e SGSL"}]}
```

Il criterio di successo, in `found()`:

```python
anchor in normalize(hit.text) and hit.document == expected["document"]
```

### Perché l'ancora e non l'id del chunk

Un `chunk_id` dipende da `MAX_CHARS`, dalla strategia, dal namespace: cambia
un parametro e l'intero golden set va riscritto. Un'**ancora testuale** — una
citazione letterale che deve comparire nel chunk recuperato — è indipendente da
come il documento è stato tagliato. Lo stesso golden set misura la strategia A e
la B, prima e dopo un cambio di parametri, senza toccare una riga.

`normalize()` compatta gli spazi perché la strategia A unisce le righe in un
flusso continuo di parole mentre la B conserva gli a-capo. Senza, la stessa
ancora matcherebbe su una collection e no sull'altra — e il confronto tra le due
strategie di chunking, che è il punto dell'esercizio, sarebbe falsato.

## I due numeri, e perché non basta il primo

```python
"recall":   n_found / n_total          # ancore recuperate / ancore attese
"complete": n_complete / len(golden)   # domande con TUTTE le ancore recuperate
```

Su 23 domande a un'ancora sola i due numeri coincidono. Divergono sulle 3
domande multi-passaggio, che ne hanno due ciascuna:

> **M1** — Un quinto livello metalmeccanico assunto 12 anni fa si dimette:
> quanto preavviso deve dare e quale minimo tabellare percepisce dal 1 giugno
> 2027?

Servono la tabella dei preavvisi (pag. 47) **e** la tabella retributiva
(pag. 95). Recuperarne una sola dà `recall = 0.5` ma `complete = 0`: e
`complete` ha ragione, perché mezza risposta a questa domanda è una risposta
sbagliata data con sicurezza.

**Guarda `complete`. `recall` serve a capire *quanto* manca quando `complete`
è basso.**

## La ripartizione per tipo

È il motivo per cui il golden set ha una composizione obbligata. Il totale non
dice niente di azionabile; la ripartizione dice cosa aggiustare:

| tipo | n | cosa mette alla prova | se fallisce |
| --- | --- | --- | --- |
| `semplice` | 10 | il funzionamento base | qualcosa è rotto a monte |
| `parafrasi` | 5 | la ricerca semantica | il denso non lavora — modello o lingua sbagliati |
| `codice` | 5 | la ricerca lessicale | serve l'ibrido, o il tokenizer rompe le sigle |
| `tabella` | 4 | il parsing e la taglia dei chunk | tabelle spezzate dall'intestazione |
| `multi-passaggio` | 3 | i limiti del recupero singolo | serve scomporre la query |

Un `recall@5` del 55% non dice cosa fare. `parafrasi 0/5` sì.

## Cosa è escluso, e perché

Cinque domande hanno `expected: []` e non entrano nel calcolo:

- **A1, A2** (conteggio/aggregazione) — la risposta non è in nessun chunk. "Quanti
  articoli contiene il CCNL?" richiede di enumerare tutto il documento.
- **X1, X2, X3** (risposta assente) — la risposta non esiste nel corpus.

Non sono escluse perché sono facili: sono escluse perché **il recall non è la
metrica giusta per loro**. Si valutano sul comportamento del generatore, dove
l'unico esito corretto è l'astensione. Con una trappola deliberata: X1 e X2
hanno forte sovrapposizione lessicale col corpus, quindi il retrieval
restituirà chunk pertinenti — e il modello dovrà astenersi *nonostante* il
contesto sembri buono. È il caso che si verifica in produzione.

## Il risultato che abbiamo

L'unica misura completata finora è BM25 da solo, su 521 chunk della strategia B
(le collection Qdrant non sono ancora popolate):

```
recall@5 55%  |  domande complete 52%

   semplice         8/10
   codice           3/5
   tabella          2/4
   multi-passaggio  1/3
   parafrasi        0/5
```

Da leggere così: la ricerca lessicale funziona dove c'è una stringa da
agganciare e non serve a niente dove non c'è. Il `55%` complessivo nasconde
entrambe le informazioni; la ripartizione le rende evidenti. Vedi
[02-keyword-sigle-bm25.md](02-keyword-sigle-bm25.md).

## Le insidie

**Il chunking gonfia il punteggio.** Non è teoria: con `MAX_TOKENS = 1200`
*parole* i chunk erano da 1206 token e coprivano una decina di articoli, e la
stessa misura dava `recall@5 61%` con `codice 5/5`. Passando a chunk da 224
token il punteggio è **sceso** a 55% e 3/5 — perché prima contenere l'ancora
era quasi gratis. Un recall alto su chunk enormi non è una buona pipeline di
recupero, è un contesto che il generatore dovrà setacciare da solo. Confronta
sempre recall@5 e taglia media dei chunk. Storia completa in
[../problems/01-embedding-context-overflow.md](../problems/01-embedding-context-overflow.md).

**Alzare K non è un miglioramento.** `recall@20` sarà sempre ≥ `recall@5`. Se
si alza K bisogna alzarlo anche nel sistema vero, e pagare il contesto in più.

**27 domande sono poche.** Una domanda vale quasi il 4%: due che passano per fortuna
spostano il totale di 8 punti. I numeri servono a confrontare strategie sullo
stesso set, non a dichiarare una percentuale assoluta di bontà.

**Il golden set non si aggiusta per farlo passare.** Se una domanda fallisce
sistematicamente, quella è la diagnosi — non un difetto della domanda.
