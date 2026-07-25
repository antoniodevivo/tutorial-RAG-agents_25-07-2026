# Ricerca per parole chiave: BM25, e perché le sigle sono il caso difficile

Tutti i numeri di questo documento sono calcolati sul corpus reale: i due CCNL
tagliati con la strategia B, **97 chunk**, lunghezza media **1206 token**.

## Il problema

La ricerca semantica confronta *significati*. Ma una parte delle domande non
chiede un significato, chiede una **stringa**:

> Cosa prevede l'art. 5 bis su **MOG(S)** e **SGSL**?

Qui non c'è niente da capire: o quella sigla è nel documento, o non c'è. Un
modello di embedding, che lavora per somiglianza di senso, su una sigla non ha
senso da usare — e le restituisce un vettore che assomiglia a quello di ogni
altra sigla. La ricerca lessicale fa l'opposto: non capisce niente, ma sa
esattamente dove sta scritta una stringa.

Sono due strumenti con guasti opposti. Da lì nasce l'ibrido.

## Come funziona la ricerca lessicale

### Passo 1: la tokenizzazione

Il testo diventa una lista di token. Nel codice:

```python
TOKEN_RE = re.compile(r"\w+", re.UNICODE)

def tokenize(text):
    return TOKEN_RE.findall(text.lower())
```

Minuscolo, e ogni sequenza di caratteri alfanumerici è un token. Sembra
innocuo. Non lo è — ecco cosa fa davvero alle stringhe del nostro corpus:

| Stringa nel documento | Token prodotti |
| --- | --- |
| `SGSL` | `['sgsl']` |
| `EGR` | `['egr']` |
| `2S` | `['2s']` |
| `13a` | `['13a']` |
| `RLS/RLST` | `['rls', 'rlst']` |
| `MOG(S)` | `['mog', 's']` |
| `art.7` | `['art', '7']` |
| `Legge n.604/1966` | `['legge', 'n', '604', '1966']` |
| `D.LGS 81/08` | `['d', 'lgs', '81', '08']` |
| `1.886,50` | `['1', '886', '50']` |
| `E.BI.A.S.P.` | `['e', 'bi', 'a', 's', 'p']` |

Le ultime righe sono il punto dolente, e ci torniamo sotto.

### Passo 2: quanto vale un token — l'IDF

Un token che compare in **tutti** i documenti non distingue niente. Uno che
compare in **uno solo** identifica quel documento da solo. L'IDF misura
esattamente questo:

```
idf(t) = ln( 1 + (N - df(t) + 0.5) / (df(t) + 0.5) )
```

dove `N` è il numero di chunk (97) e `df(t)` in quanti chunk compare il token.

I valori veri del corpus, ordinati dal più informativo al meno:

| Token | df | idf | Commento |
| --- | --- | --- | --- |
| `2s` | 1 | **4.180** | un solo chunk: il massimo potere discriminante |
| `886` | 1 | **4.180** | frammento di `1.886,50` |
| `sgsl` | 2 | 3.669 | sigla rara = oro |
| `1977`, `792`, `1985` | 2 | 3.669 | i riferimenti normativi delle festività soppresse |
| `mog` | 3 | 3.332 | |
| `rls` | 4 | 3.081 | |
| `604`, `1966` | 5 | 2.880 | la Legge 604/1966 |
| `rlst` | 8 | 2.445 | |
| `bi` | 21 | 1.517 | frammento di `E.BI.A.S.P.` — già quasi rumore |
| `p` | 31 | 1.135 | |
| `ferie` | 34 | 1.044 | parola comune del dominio |
| `s` | 44 | 0.789 | |
| `lavoratore` | 86 | 0.125 | quasi ovunque: non discrimina |
| `contratto`, `e`, `a`, `di` | 97 | **0.005** | in tutti i chunk: contributo nullo |

Da notare: **non serve una lista di stopword**. `di`, `e`, `a` valgono 0.005
contro i 4.180 di `2s`: sono 800 volte meno influenti, si azzerano da soli. È
la proprietà più elegante dell'IDF.

### Passo 3: quante volte compare — la TF, saturata

Se una parola compare 100 volte invece di 1, il chunk è 100 volte più
pertinente? No. BM25 satura:

```
        tf · (k1 + 1)
   ─────────────────────────
   tf + k1 · (1 - b + b · len/avgdl)
```

Con `k1 = 1.5` e un chunk di lunghezza media, il contributo cresce così:

| occorrenze | contributo |
| --- | --- |
| 1 | 1.000 |
| 2 | 1.429 |
| 5 | 1.923 |
| 10 | 2.174 |
| 100 | 2.463 |
| ∞ | 2.500 |

Cento occorrenze valgono 2.46 volte una sola, non cento. `k1` è la manopola:
più è basso, prima satura.

### Passo 4: la lunghezza — la normalizzazione `b`

Un chunk lungo contiene più parole, quindi ha più probabilità di contenere la
query per puro caso. `b = 0.75` corregge:

```
norm = 1 - b + b · (len / avgdl) = 0.25 + 0.75 · (len / 1206)
```

Con una sola occorrenza del termine:

| lunghezza chunk | norm | contributo |
| --- | --- | --- |
| 300 token | 0.44 | **1.51** |
| 1206 (media) | 1.00 | 1.00 |
| 3000 token | 2.12 | **0.60** |

La stessa singola occorrenza vale **2.5 volte di più** in un chunk corto che in
uno lungo. Ha una conseguenza diretta sull'esercizio del chunking: con
`MAX_TOKENS = 1200` i chunk sono enormi, la normalizzazione li penalizza tutti
allo stesso modo, e BM25 perde gran parte della sua capacità di discriminare.

### Il punteggio finale

```
BM25(q, d) = Σ  idf(t) · saturazione(tf, len)
            t∈q
```

Somma sui termini della query. Nel codice, `Bm25Index.search()`, righe 144-169.

## Perché le sigle sono il caso difficile

Ci sono **due modi diversi** di fallire su una sigla, e vanno distinti perché
si curano diversamente.

### Guasto 1 — la sigla c'è, ma il tokenizer la distrugge

`E.BI.A.S.P.` è l'Ente Bilaterale citato dall'Art.118. Nel corpus c'è, scritto
per esteso. Ma:

```
'E.BI.A.S.P.'  ->  ['e', 'bi', 'a', 's', 'p']
```

Cinque token, di cui quattro sono lettere singole. Guardiamo i loro IDF:

| token | df | idf |
| --- | --- | --- |
| `e` | 97 | 0.005 |
| `a` | 97 | 0.005 |
| `s` | 44 | 0.789 |
| `p` | 31 | 1.135 |
| `bi` | 21 | 1.517 |

Il token che identificherebbe la sigla — `biasp`, o `ebiasp` — **non esiste
nell'indice**: `df = 0`. La sigla è stata polverizzata in frammenti generici, e
la query "Cosa disciplina l'Art.118?" viene salvata solo da `118`, non dalla
sigla.

Confronta con `SGSL`, che non ha punti dentro: resta intero, `df = 2`,
`idf = 3.669`, e chi lo cerca lo trova al primo colpo.

**La differenza tra le due sigle non è semantica, è punteggiatura.**

### Guasto 2 — la sigla non c'è proprio

> Che cos'è l'**EGR**?

```
'egr'  ->  df = 0
```

Il documento parla di "Elemento di Garanzia Retributiva" per esteso, in
`Art.30`, e **la sigla EGR non compare mai**. BM25 non ha nessun token da
agganciare: il punteggio è zero, la ricerca lessicale restituisce il nulla.

Qui l'unica strada è la semantica, che può avvicinare "EGR" alla forma estesa —
o un dizionario di sinonimi che espanda la sigla prima della query.

### Il caso speculare: la parafrasi

> Chi si occupa di **antinfortunistica** per conto dei dipendenti?

```
'antinfortunistica'  ->  df = 0
```

Nel CCNL metalmeccanico la parola non c'è mai. L'unica occorrenza in tutto il
corpus italiano è al plurale, **nell'altro contratto e in tutt'altro contesto**
(commercio, Art.49, "danneggiamento di dispositivi antinfortunistici"). Un
sistema lessicale o non trova niente, o trova il documento sbagliato con
sicurezza. La risposta giusta — `Art.6 - RLS/RLST` — non condivide **una sola
parola** con la domanda.

### Il risultato misurato

BM25 da solo sul golden set, 97 chunk, strategia B:

```
recall@5 61%  |  domande complete 59%

   codice           5/5     <- sigle, articoli, riferimenti normativi
   semplice         8/10
   tabella          2/4
   multi-passaggio  1/3
   parafrasi        0/5     <- azzerato
```

**5/5 sui codici e 0/5 sulle parafrasi.** Non è un caso, è la firma del
metodo: dove c'è una stringa da agganciare, il lessicale vince; dove la
domanda non condivide vocabolario col documento, non ha niente su cui lavorare.

> Una cautela sul 5/5: con `MAX_TOKENS = 1200` ogni chunk copre una decina di
> articoli, quindi *contenere l'ancora* è più facile del dovuto. Il pattern
> resta valido, i valori assoluti vanno riletti con chunk più piccoli.

## Cosa si può fare (non ancora implementato)

Tre interventi, in ordine di rapporto risultato/costo:

**1. Normalizzare le sigle prima di tokenizzare.** Riconoscere il pattern
"lettera-punto ripetuto" e collassarlo, indicizzando *entrambe* le forme:

```
E.BI.A.S.P.  ->  ['e','bi','a','s','p']  +  ['ebiasp']
D.LGS        ->  ['d','lgs']             +  ['dlgs']
```

Costa poche righe in `tokenize()` e recupera il guasto 1 per intero.

**2. Un dizionario di espansione a livello di query.** `EGR → Elemento di
Garanzia Retributiva`, `RLST → Rappresentante dei Lavoratori per la Sicurezza
Territoriale`. Cura il guasto 2, ma va scritto a mano e mantenuto: si giustifica
solo per le sigle che ricorrono davvero nel dominio.

**3. Tenere i numeri interi.** `1.886,50 → ['1','886','50']` funziona per caso,
perché `886` è raro. Con `1.234,00` i frammenti `1`, `234`, `00` sono comuni e
il match sparisce. Un token `1.886,50` intero sarebbe stabile.

Nessuno di questi serve alle parafrasi: quelle restano di competenza della
ricerca semantica, ed è esattamente il motivo per cui la strategia 2 fonde le
due. Vedi [03-fusione-rrf-e-reranking.md](03-fusione-rrf-e-reranking.md).
