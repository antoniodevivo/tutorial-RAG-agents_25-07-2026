# 04 — la domanda generica sul corpus: il retrieval non sa dire "non c'entra"

**Dove:** `src/scripts/chat.py`
**Stato:** aperto — diagnosi e soluzione descritte, non implementate

## Il sintomo

```
> dammi una risposta più lunga: cosa mi sai dire?

Risposta
  Sulla base dei documenti forniti, posso fornirti informazioni dettagliate
  su tre aree diverse:

  **1. Consultazione dei lavoratori (CCNL Metalmeccanico Conflavoro)**
  ...
  **2. Orario di lavoro e figure professionali (CCNL Metalmeccanico Conflavoro)**
  ...
  **3. Tabella retributiva (CCNL Commercio, Terziario, Distribuzione e Servizi)**
  ...

Fonti
  [1]  98% high   Informazione e consultazione dei lavoratori
  [2]  91% high   Art.7 - Articolazione dell'orario di lavoro
  [3]  83% high   Appartengono a questo livello:
  [4]  79% high   Appartengono a questo livello:
  [5]  50% medium Tabella retributiva A

  Golden set, questa strategia: 74% chunk attesi · 70% domande complete
```

L'intento dell'utente era **un riassunto degli argomenti presenti nel
database**. Quello che è tornato è un riassunto di tre argomenti scorrelati,
scritto bene, citato correttamente, e sbagliato.

## Perché non è colpa del generatore

Il modello ha fatto tutto ciò che il `SYSTEM_PROMPT` gli chiede: ha usato solo i
passaggi ricevuti, ha citato ogni affermazione, ha tenuto distinti i due CCNL
invece di sceglierne uno in silenzio, non ha inventato cifre. È coerente con
`fedeltà 16/16` misurata in
[../app/06-valutare-le-risposte.md](../app/06-valutare-le-risposte.md): quando
riceve i chunk, questo generatore li usa correttamente.

Se si giudica la risposta contro i 5 passaggi che aveva davanti, è corretta. È
il metro che è sbagliato.

## Perché non è nemmeno colpa del retrieval

`search_fn(question, collection, TOP_K)` ha restituito i 5 vicini più prossimi
all'embedding della domanda. Ha funzionato: **restituisce sempre 5 chunk**,
qualunque cosa gli si chieda. Non esiste un valore di ritorno che significhi
"nessuno di questi ha a che fare con la domanda", perché la similarità coseno
produce un ordinamento, non un giudizio di pertinenza. Anche l'embedding di una
frase che non nomina alcun argomento ha i suoi vicini.

È lo stesso limite già registrato per il reranker in
[../app/03-fusione-rrf-e-reranking.md](../app/03-fusione-rrf-e-reranking.md) —
*il reranker non recupera niente* — visto da un'altra faccia: il retrieval non
scarta niente. Ordina ciò che ha.

## La causa: una domanda di categoria diversa

*"Cosa mi sai dire?"* non è una domanda a cui si risponde con dei passaggi. È
una domanda **sul corpus**, non **nel corpus** — la stessa forma di `A1` e `A2`
del golden set, che [../app/04-recall-at-5.md](../app/04-recall-at-5.md)
esclude dal recall con la motivazione esatta: *«la risposta non è in nessun
chunk»*.

La pipeline non ha modo di accorgersene, perché tratta ogni turno allo stesso
modo: recupera 5 chunk, li mette nel prompt, genera. Il risultato è che

> **5 chunk su un indice di 291 documenti vengono presentati come se fossero la
> mappa dell'indice.**

E la mappa è falsa in modo grosso: nel vector store **288 documenti su 291 non
sono CCNL** — sono atti del Congresso, report DHS/DOE, paper, come dichiarato in
[../app/05-dal-recupero-alla-risposta.md](../app/05-dal-recupero-alla-risposta.md).
Una panoramica del database che parla solo di contratti collettivi italiani non
è incompleta: descrive l'1% e non lo dice.

Il fatto che sembri una buona panoramica è ciò che la rende peggiore di un "non
lo so". È lo stesso fallimento di `A2` — l'unico vero errore del generatore nel
referto di [06](../app/06-valutare-le-risposte.md) — dove la regola *don't count
or total anything across the corpus* ha retto a metà: il modello non ha prodotto
un numero, ma ha presentato un campione come se fosse il tutto.

## I segnali che erano già a schermo

Nessuno di questi è un controllo automatico, ma sono tutti visibili nel turno
stesso:

| segnale | in questo caso |
| --- | --- |
| dispersione delle fonti | 5 passaggi, 2 contratti diversi, 3 argomenti senza relazione |
| coda dello score | `[5] 50% medium`, cioè poco sopra la soglia `low` (0.35) di `confidence_band()` |
| forma dell'incipit | *«posso fornirti informazioni su tre aree diverse»* — la risposta **indicizza il contesto** invece di rispondere |

Il terzo è il più affidabile a occhio: quando un sistema RAG apre elencando aree
tematiche, sta descrivendo ciò che ha ricevuto perché non ha trovato cosa
rispondere.

E il `74% · 70%` in fondo non c'entra: è `recall_at_k()` sul golden set intero,
calcolato una volta all'avvio e uguale per ogni turno. Serve a leggere in scala
lo score delle fonti, non a giudicare la singola risposta — è già scritto in
[05](../app/05-dal-recupero-alla-risposta.md), ma è esattamente il numero che si
guarda per primo quando una risposta insospettisce, ed è muto proprio lì.

## La soluzione: due strumenti, e il modello che sceglie

La correzione ovvia è un comando — `/corpus` — che elenca i documenti indicizzati.
**Non è la soluzione giusta**, ed è utile dire perché: un comando richiede che
sia l'utente a classificare la propria domanda *prima* di scriverla, e a sapere
che il sistema ha una funzione apposta. Chi scrive "cosa mi sai dire?" sta
dichiarando proprio di non sapere cosa c'è dentro. Chiedergli di scegliere lo
strumento è chiedergli la risposta che è venuto a cercare.

Il riconoscimento va dove c'è già un modello che legge la domanda: **tool
calling**. Il generatore riceve la domanda e due strumenti, e decide quale
serve.

```python
TOOLS = [
    {"type": "function", "function": {
        "name": "search_passages",
        "description": "Cerca passaggi pertinenti a una domanda specifica su "
                       "un contenuto: articoli, importi, definizioni, procedure.",
        "parameters": {"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "corpus_overview",
        "description": "Elenca cosa contiene l'indice: quali documenti, quanti "
                       "passaggi ciascuno, quali sezioni. Da usare quando la "
                       "domanda riguarda il corpus nel suo insieme e non un "
                       "contenuto specifico.",
        "parameters": {"type": "object", "properties": {}}}},
]
```

La descrizione dello strumento è il posto dove vive la distinzione
*sul corpus / nel corpus*. È prompt engineering come il `SYSTEM_PROMPT`, con la
differenza che qui il modello non deve **seguire** una regola: deve solo
scegliere tra due opzioni descritte.

### Cosa fa `corpus_overview()`

Non è retrieval e non usa embedding. È uno `scroll` sui payload Qdrant con
`with_vectors=False`, aggregato per documento:

La forma dell'output — i conteggi dei due CCNL sono quelli misurati in
[01](01-embedding-context-overflow.md) per la strategia B, il resto è da
misurare:

```
documento                                        chunk
ccnl_metalmeccanico_industria_conflavoro           318
ccnl_commercio_terziario_distribuzione_e_servizi   203
altri 288 documenti (atti, report, paper)          ...
```

Tre proprietà che il retrieval non può avere:

1. **è completo per costruzione** — legge tutti i punti, non i primi 5;
2. **è deterministico** — nessun modello tra la domanda e il dato;
3. **non può allucinare la composizione del corpus**, che è precisamente
   l'errore del sintomo.

Va aggregato, non enumerato: 291 righe nel contesto sono un altro modo di
sfondarlo. Il taglio giusto è per documento con i conteggi, e i documenti fuori
dai CCNL raggruppati.

### Il giro nuovo di un turno

Oggi `answer()` recupera **sempre e prima**:

```
domanda → search_fn(...) → 5 Hit → prompt → generazione
```

Con il routing il retrieval smette di essere incondizionato:

```
domanda → modello (+ TOOLS)
             ├─ search_passages("...")  → 5 Hit ─┐
             └─ corpus_overview()       → tabella ┤
                                                  └→ modello → risposta
```

Due conseguenze da mettere in conto:

- **una chiamata in più per turno.** La prima decide, la seconda risponde.
- **la prima chiamata non può essere in streaming**, perché bisogna leggere
  `message.tool_calls` prima di stampare qualcosa. Costa poco: `collect_answer()`
  già raccoglie tutta la risposta prima di formattarla
  ([chat.py:205](../../src/scripts/chat.py#L205)), quindi lo streaming a schermo
  qui non esiste comunque.
- **il modello deve supportare i tool.** Va verificato su `gemma4:cloud`: se il
  campo `tool_calls` non arriva mai, la soluzione non è applicabile con questo
  modello e la diagnosi resta valida ma il fix cambia.

### La rete di sicurezza obbligatoria

Se il modello **non** chiama nessuno strumento e risponde direttamente, sta
rispondendo dalla propria conoscenza — cioè esattamente ciò che l'intero
`SYSTEM_PROMPT` è costruito per impedire. Quel caso non va accettato: se
`tool_calls` è vuoto, si forza `search_passages` con la domanda originale e si
torna al comportamento di oggi. Meglio il bug noto di questo documento che una
risposta senza fonti.

## Cosa questo rompe nella valutazione

Il router è un punto di guasto nuovo, e sbaglia in **due** direzioni:

| errore | effetto |
| --- | --- |
| domanda specifica → `corpus_overview` | l'utente chiede le ferie e riceve un elenco di documenti |
| domanda generica → `search_passages` | il bug di questo documento, invariato |

Nessuna delle misure di [`generation.py`](../../src/scripts/generation.py) lo
vede: `fondatezza`, `fedeltà` e `astensione` valutano la risposta, non la scelta
dello strumento. Serve una misura nuova — **quale strumento è stato chiamato,
contro quale era atteso** — che è la più economica di tutte, perché non richiede
il giudice LLM: è un confronto tra due stringhe.

E c'è un effetto sul golden set che va deciso prima di scrivere il codice: per
il blocco **A** (`A1`, `A2`) l'esito corretto oggi è l'**astensione**. Con
`corpus_overview` disponibile, l'esito corretto diventa **la risposta giusta**,
e `A1`/`A2` cambiano di natura. Il blocco **X** no: quelle risposte non esistono
nel corpus e nessuno strumento le fa comparire, l'astensione resta l'unico esito
accettabile. Metà del blocco che oggi misura l'astensione passerebbe a misurare
il routing, e la riga `astensione 4/5` del referto non sarebbe più confrontabile
con quelle di prima.

## Cosa resta

- **La soglia di confidenza è un fix diverso e complementare.** Se la fonte
  migliore sta sotto la banda `low`, la risposta corretta è astenersi — vale per
  le domande specifiche a cui il corpus non risponde, cioè il blocco X, e non
  richiede alcun tool calling. Le due correzioni non si sostituiscono.
- **Il routing non risolve `A2`.** *"In quanti punti del corpus si rinvia alla
  contrattazione di secondo livello?"* è una domanda di conteggio su tutto il
  corpus: `corpus_overview` sa quanti chunk ci sono per documento, non quanti
  contengono un'espressione. Servirebbe un terzo strumento (un conteggio
  lessicale su tutto l'indice) — e la domanda se valga la pena resta aperta.
- **Nessun filtro di visibilità.** `corpus_overview` leggerebbe tutti i payload,
  inclusi quelli che un filtro `visibility` dovrebbe nascondere. Su un indice
  multi-tenant una funzione che elenca il contenuto è il primo posto dove quel
  filtro va applicato, non l'ultimo.
- **La domanda del sintomo resta legittima.** Un utente che chiede "cosa c'è qui
  dentro?" ha fatto la domanda giusta a un sistema che non aveva come
  rispondere. Il difetto non è nella domanda.

## La lezione trasferibile

Il generatore era corretto, il retrieval era corretto, la risposta era sbagliata.
Quando ogni componente supera il proprio test e l'output è comunque cattivo, il
difetto sta nel **giunto**: qui, l'assunzione implicita che ogni domanda si
risponda recuperando passaggi. Un'assunzione così non compare in nessuna
metrica, perché tutte le metriche sono state scritte dentro di essa — il golden
set misura il recall su 27 domande che quell'assunzione la rispettano, e le 5
che non la rispettano erano già state messe da parte come casi speciali.

Erano il sintomo, non l'eccezione.
