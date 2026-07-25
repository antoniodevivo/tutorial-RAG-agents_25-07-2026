# 03 — il generatore copia il contesto invece di rispondere

**Dove:** `src/scripts/chat.py`, con `CHAT_MODEL = "llava-phi3:latest"`
**Stato:** risolto cambiando modello

## Il sintomo

Ogni domanda produceva lo stesso impasto di frammenti, indipendentemente da
cosa fosse stato chiesto:

```
> su cosa mi puoi rispondere?
Inagre
It
of
ofracive.
entanyallivelement, by
fromyour
```

Il retrieval, nello stesso turno, funzionava: alla domanda sulle ferie il primo
chunk era `Art.16 - Ferie` pag. 25 al 100% di score — esattamente l'attesa di
`S2`. Il guasto era tutto a valle.

Il dettaglio che ha indirizzato la diagnosi: le parole emesse (`answer`, `of`,
`More`, `Your Answer`) sono **frammenti del prompt**, non del corpus.

## L'ipotesi sbagliata

> Il contesto viene troncato. `TOP_K = 5` chunk da `MAX_CHARS = 1800` fanno
> ~9.000 caratteri, `phi3` ha 4096 token: Ollama tronca in silenzio, la domanda
> esce dalla finestra e restano solo le istruzioni — che infatti il modello
> ripete.

Plausibile, coerente col sintomo, e **falsa**. Era anche l'ipotesi comoda:
questa pipeline aveva già avuto un overflow di contesto sugli embedding
([problema 01](01-embedding-context-overflow.md)), quindi la spiegazione
sembrava familiare.

Misurando `prompt_eval_count` — i token che Ollama dichiara di aver
processato — contro il `num_ctx` del modello:

```
 top_k     char  tok prompt  contesto  esito
     5    10569        3454      4096  ci sta, 642 token di margine
     3     6482        2057      4096  ci sta
     2     4609        1451      4096  ci sta
     1     2643         822      4096  ci sta
```

Nessuno sforamento, in nessuna configurazione. Il rapporto è ~3,06
caratteri/token: 9.000 caratteri di italiano non fanno 4.096 token.

## La causa vera

Isolando una variabile alla volta, con la stessa domanda e la stessa risposta
attesa (22 giorni di ferie su cinque giorni settimanali):

| prova | token | esito |
| --- | --- | --- |
| istruzione banale (*"reply with one word: OK"*) | 18 | `OK` — corretto |
| regole corte + 1 passaggio corto scritto a mano | 171 | **risposta corretta** |
| **regole del progetto** + stesso passaggio corto | 295 | copia il passaggio |
| regole corte + **1 chunk vero** | 697 | copia l'intestazione |
| regole corte + 2 chunk veri | 1292 | copia l'intestazione |
| regole corte + 5 chunk veri | 2923 | parole a caso |

Due letture, entrambe necessarie:

1. **Il modello sa fare il compito.** A 171 token risponde correttamente, in
   italiano: *"22 giorni lavorativi se presta la propria attività per cinque
   giorni la settimana"*. Non è incapacità del compito RAG.
2. **Degrada ben dentro il contesto nominale.** A 2923 token su 4096 disponibili
   produce parole a caso. Il limite dichiarato e il limite utile sono due cose
   diverse, e solo il secondo conta.

Il degrado ha una forma precisa: non risposte *sbagliate*, ma il modello che
**smette di seguire l'istruzione e copia l'input**. Prima l'intestazione del
passaggio, poi il testo, infine niente di leggibile.

Nota su cosa copia per primo: la catena completa dei titoli, che nel prompt
arriva così —

```
[1] ccnl_metalmeccanico_industria_conflavoro | CONTRATTO COLLETTIVO NAZIONALE
DI LAVORO > SVOLGIMENTO DEL RAPPORTO DI LAVORO > Art.7 - Articolazione
dell'orario di lavoro > Art. 7 bis – Lavoratori Discontinui > Art.16 - Ferie
```

## Il fix che non ha funzionato

Le due cause candidate erano entrambe nel prompt scritto da noi — 5 regole
dense, intestazioni lunghissime — quindi la correzione ovvia era accorciare
entrambe. Provata, con regole ridotte all'osso e `short_section()` applicata
anche al contesto:

```
 top_k   token  esito
     1     635  copia
     2    1210  copia
     3    1786  contiene la risposta, ma è ancora una copia
     5    2923  parole a caso
```

**La soglia si sposta, il comportamento no.** Vale la pena registrarlo: la
correzione era ragionevole, mirata alle cause misurate, e non ha risolto. Il
prompt non era il problema — era solo la parte del problema su cui era comodo
intervenire.

## Il fix

`CHAT_MODEL = "gemma4:cloud"`. Stessa pipeline, stesso prompt, stesso
retrieval:

```
Nel CCNL metalmeccanico, il personale ha diritto a un periodo di ferie annuali:
*   26 giorni lavorativi se l'attività è prestata per sei giorni a settimana [1]
*   22 giorni lavorativi se l'attività è prestata per cinque giorni a settimana [1]
```

Corretta, citata, nella lingua della domanda. La valutazione sistematica in
[../app/06-valutare-le-risposte.md](../app/06-valutare-le-risposte.md) misura
**fedeltà 16/16**: quando il chunk giusto arriva, questo generatore lo usa
sempre correttamente.

## Cosa resta

- **`llava-phi3` è un modello vision** (`phi3` + encoder CLIP), scelto perché
  era in locale, non perché adatto. Un modello scelto per disponibilità è un
  parametro non misurato come un altro.
- **Nessun controllo che il prompt entri nel contesto.** Sarebbe l'analogo di
  `EMBED_MAX_CHARS` in `chunking_simple.py`, che su testo troppo lungo
  solleva un errore invece di lasciar fallire il server. Qui non c'è: se un
  giorno il prompt supererà davvero il `num_ctx`, il sintomo sarà lo stesso —
  output degenere — e la diagnosi ripartirà da zero.
- **Il degrado non ha una soglia dichiarata da nessuna parte.** `ollama show`
  dice `4096`; la soglia utile misurata su questo corpus era sotto i 700 token.
  L'unico modo di conoscerla è misurarla, per ogni modello e ogni tipo di testo.

## La lezione trasferibile

Un'ipotesi plausibile che spiega il sintomo non è una diagnosi. Questa era
credibile, coerente con un guasto già visto nello stesso repo, e sarebbe
sopravvissuta a lungo senza una misura — bastava un `prompt_eval_count` per
falsificarla in un minuto.

Il costo di non misurare non è solo l'ipotesi sbagliata: è che l'intervento
successivo (accorciare il prompt) sarebbe stato dichiarato "il fix", perché a
`top_k` basso qualche risposta effettivamente migliorava.
