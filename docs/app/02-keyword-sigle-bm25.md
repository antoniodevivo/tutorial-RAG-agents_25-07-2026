# Ricerca per parole chiave: BM25, e perché le sigle sono il caso difficile

Tutti i numeri di questo documento sono calcolati sul corpus reale: i due CCNL
tagliati con la strategia B a `MAX_CHARS = 1800`, **521 chunk**, lunghezza
media **224 token**.

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

dove `N` è il numero di chunk (521) e `df(t)` in quanti chunk compare il token.

I valori veri del corpus, dal più informativo al meno:

| Token | df | idf | Commento |
| --- | --- | --- | --- |
| `2s` | 1 | **5.852** | un solo chunk: il massimo potere discriminante |
| `886` | 1 | **5.852** | frammento di `1.886,50` |
| `sgsl` | 2 | 5.341 | sigla rara = oro |
| `1977`, `792`, `1985` | 2 | 5.341 | i riferimenti delle festività soppresse |
| `garanzia` | 2 | 5.341 | |
| `perequativo` | 3 | 5.005 | |
| `mog` | 4 | 4.754 | |
| `604`, `1966` | 5 | 4.553 | la Legge 604/1966 |
| `rls` | 7 | 4.243 | |
| `54` | 12 | 3.732 | |
| `rlst` | 14 | 3.584 | |
| `bi` | 35 | 2.688 | frammento di `E.BI.A.S.P.` — già quasi rumore |
| `ferie` | 42 | 2.508 | parola comune del dominio |
| `p` | 58 | 2.189 | |
| `s` | 77 | 1.907 | |
| `lavoratore` | 267 | 0.669 | in metà dei chunk: discrimina poco |
| `contratto` | 288 | 0.593 | |
| `a` | 461 | 0.123 | |
| `e` | 507 | 0.028 | |
| `di` | 521 | **0.001** | in *tutti* i chunk: contributo nullo |

Da notare: **non serve una lista di stopword**. `di` vale 0.001 contro i 5.852
di `2s`: si azzera da solo. È la proprietà più elegante dell'IDF.

Da notare anche che `bi`, il frammento centrale di `E.BI.A.S.P.`, vale *meno* di
`ferie`. Ci torniamo.

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
norm = 1 - b + b · (len / avgdl) = 0.25 + 0.75 · (len / 224)
```

Con una sola occorrenza del termine:

| lunghezza chunk | norm | contributo |
| --- | --- | --- |
| 100 token | 0.59 | **1.33** |
| 224 (media) | 1.00 | 1.00 |
| 500 token | 1.92 | **0.64** |

La stessa singola occorrenza vale **il doppio** in un chunk corto che in uno
lungo. È il motivo per cui la taglia dei chunk non è un dettaglio: vedi
[l'effetto misurato](../problems/01-embedding-context-overflow.md#leffetto-collaterale-che-conta)
del passaggio da 1206 a 224 token medi.

### Il punteggio finale

```
BM25(q, d) = Σ  idf(t) · saturazione(tf, len)
            t∈q
```

Somma sui termini della query. Nel codice, `Bm25Index.search()`.

## Perché le sigle sono il caso difficile

Ci sono **due modi diversi** di fallire su una sigla, e vanno distinti perché
si curano diversamente.

### Guasto 1 — la sigla c'è, ma il tokenizer la distrugge

`E.BI.A.S.P.` è l'Ente Bilaterale citato dall'Art.118. Nel corpus c'è, scritto
per esteso. Ma:

```
'E.BI.A.S.P.'  ->  ['e', 'bi', 'a', 's', 'p']
```

Cinque token, di cui quattro sono lettere singole. I loro IDF:

| token | df | idf |
| --- | --- | --- |
| `e` | 507 | 0.028 |
| `a` | 461 | 0.123 |
| `s` | 77 | 1.907 |
| `p` | 58 | 2.189 |
| `bi` | 35 | 2.688 |

Il token che identificherebbe la sigla — `biasp`, o `ebiasp` — **non esiste
nell'indice**: `df = 0`. La sigla è stata polverizzata in frammenti generici, e
la somma dei cinque IDF non raggiunge quella di un solo token raro.

Confronta con `SGSL`, che non ha punti dentro: resta intero, `df = 2`,
`idf = 5.341`, e chi lo cerca lo trova al primo colpo.

**La differenza tra le due sigle non è semantica, è punteggiatura.**

### Guasto 2 — la sigla non c'è proprio

> Che cos'è l'**EGR**?

```
'egr'  ->  df = 0
```

Il documento parla di "Elemento di Garanzia Retributiva" per esteso, in
`Art.30`, e **la sigla EGR non compare mai**. BM25 non ha nessun token da
agganciare: il punteggio è zero, la ricerca lessicale restituisce il nulla — e
infatti nella misura sotto la domanda C3 fallisce.

Qui l'unica strada è la semantica, che può avvicinare "EGR" alla forma estesa,
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

BM25 da solo sul golden set, 521 chunk, strategia B:

```
recall@5 55%  |  domande complete 52%

   semplice         8/10
   codice           3/5     <- falliscono C2 e C3
   tabella          2/4
   multi-passaggio  1/3
   parafrasi        0/5     <- azzerato
```

Le due righe estreme sono la firma del metodo. `parafrasi 0/5`: dove la domanda
non condivide vocabolario col documento, il lessicale non ha niente su cui
lavorare. `codice 3/5`: dove c'è una stringa da agganciare funziona — e i due
fallimenti sono esattamente quelli che la teoria prevede.

- **C3 (EGR)** fallisce per il guasto 2: `df = 0`, non c'è niente da trovare.
- **C2** chiede i riferimenti delle festività soppresse, e la stessa frase
  identica sta in **entrambi** i CCNL. Servono due chunk, uno per documento, e
  BM25 li ordina quasi allo stesso punteggio: nei primi 5 ne entra uno solo.

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
perché `886` è raro (`df = 1`). Con `1.234,00` i frammenti sarebbero comuni e il
match sparirebbe. Un token `1.886,50` intero sarebbe stabile.

Nessuno di questi serve alle parafrasi: quelle restano di competenza della
ricerca semantica, ed è esattamente il motivo per cui la strategia 2 fonde le
due. Vedi [03-fusione-rrf-e-reranking.md](03-fusione-rrf-e-reranking.md).
