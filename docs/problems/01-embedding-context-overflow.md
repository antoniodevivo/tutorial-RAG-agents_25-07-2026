# 01 — `input length exceeds the context length`

**Dove:** `src/scripts/chunking_simple.py`, durante `python -m src.main --gchunks`
**Stato:** risolto
**Difetti distinti trovati:** 3

## Il sintomo

Il primo documento, alla prima chiamata di embedding:

```
File "src/scripts/chunking_simple.py", line 74, in build_chunk
    embedding=embed(text),
...
ollama._types.ResponseError: the input length exceeds the context length (status code: 500)
```

Un 500 dal server, senza dire quanto era lungo l'input né quanto poteva essere.

## Difetto 1 — il budget era in parole, il limite è in token

### La causa

```python
MAX_TOKENS = 1200          # il nome dice token
...
current_tokens += 1        # ma conta parole
if current_tokens <= MAX_TOKENS:
```

`text.split()` produce **parole**. `embeddinggemma` ha un contesto di **2048
token**. Le due unità non coincidono, e il nome della costante nascondeva la
differenza: chi ha scritto `1200` pensava a 1200 token, ne stava chiedendo il
triplo.

Un tokenizer subword spezza le parole in pezzi. Su italiano il rapporto
misurato è ~2.9 token per parola: `1200 parole ≈ 3500 token`, cioè il 70% oltre
il contesto.

### Perché non bastava abbassare il numero

Primo tentativo: `MAX_WORDS = 400`. Ha continuato a fallire, su un documento
diverso. Il motivo, misurato:

| tipo di testo                  | parole accettate | caratteri | char/token |
| ------------------------------ | ---------------- | --------- | ---------- |
| prosa italiana (articoli CCNL) | —                | **8895**  | 4.34       |
| OCR di una mappa scannerizzata | 378              | **3251**  | 1.59       |
| tabelle Markdown               | —                | **2893**  | **1.41**   |

`TQB32TPQYRF2BVFF3S4ARJ26TSIHFHHL.md` è una mappa topografica passata per OCR:
parole da **19.4 caratteri** di media, piene di `<br>` e di mojibake, contro le
~6 di un testo normale. 400 di quelle parole sono più del triplo, in caratteri,
di 400 parole di italiano.

**La lunghezza delle parole varia di 3× dentro lo stesso corpus, quindi contare
parole non può limitare i token.** Il conteggio a caratteri no: varia di 3×
anche lui (4.34 contro 1.41 char/token), ma è la variazione _residua_ dopo aver
tolto quella della lunghezza delle parole, ed è limitata dal basso da ~1.4.

### Il fix

Budget in caratteri, con il caso peggiore misurato come vincolo:

```python
MAX_CHARS = 1800        # 1800 / 1.41 = ~1280 token nel caso peggiore
EMBED_MAX_CHARS = 2400  # soglia di guardia in embed()
```

Il caso peggiore non è l'OCR, sono **le tabelle**: `|Settimo livello|€ 1.786,00|`
è quasi tutta punteggiatura e cifre, e ogni simbolo tende a diventare un token
a sé. Con 1800 caratteri restano ~38% di margine.

## Difetto 2 — una riga sola può superare qualsiasi limite

`cut_from_structure` accumula **righe intere** e non taglia mai dentro una riga:

```python
if current_tokens + line_tokens <= MAX_TOKENS:
    current_chunk.append(line)
else:
    flush(); current_chunk = [line]     # <-- la riga entra comunque
```

Se una singola riga supera il limite, finisce lo stesso in un chunk tutto suo,
**di dimensione arbitraria**. Non è ipotetico: nel corpus c'è una riga da
**1234 parole** — una tabella che la conversione PDF ha appiattito su un rigo.

Stesso problema, un livello sotto: nei documenti OCR una singola "parola" può
essere lunga centinaia di caratteri, e nemmeno l'accumulo per parole della
strategia A la contiene.

### Il fix

Due reti, `split_long_lines()` e `split_oversized()`: nessuna riga e nessuna
parola arriva all'accumulatore più lunga di `MAX_CHARS`.

```python
lines = split_long_lines(text.splitlines(), MAX_CHARS)
```

## Difetto 3 — il testo vuoto produce un vettore di dimensione 0

Trovato mentre si verificava il fix, non è la causa del crash ma sarebbe
esploso subito dopo:

```python
oclient.embeddings(model="embeddinggemma", prompt="")
# -> nessun errore, embedding di dimensione 0
oclient.embeddings(model="embeddinggemma", prompt="   ")
# -> embedding di dimensione 768
```

Su stringa vuota Ollama **non solleva un errore**: restituisce un vettore
vuoto. Quel vettore passa la validazione Pydantic (`list[float]` accetta la
lista vuota), viene scritto nel `.jsonl`, e fallisce molto più avanti
nell'upsert Qdrant con un errore di dimensione che non fa capire da dove
venga — a quel punto separato dalla causa da migliaia di chunk.

### Il fix

`embed()` controlla prima di chiamare:

```python
if not text.strip():
    raise ValueError("embed(): testo vuoto, il modello restituirebbe un "
                     "vettore di dimensione 0")
if len(text) > EMBED_MAX_CHARS:
    raise ValueError(f"embed(): {len(text)} caratteri eccedono il contesto ...")
```

Nessuna troncatura silenziosa: se un chunk non ci sta, è un errore di
configurazione e va detto, non nascosto perdendo testo.

## Verifica

Sui tre casi che rompevano, dopo il fix:

```
MAX_CHARS=1800 EMBED_MAX_CHARS=2400
TQB32TPQYRF2BVFF3S4ARJ26TSIHFHHL.md   A: 16 chunk    B: 17 chunk
CV_Antonio_DeVivo_ITA_v5.0.3.md       A: 0 chunk     B: 0 chunk
ccnl_metalmeccanico_industria_...md   A: 282 chunk   B: 318 chunk
```

Il CV a 0 chunk è corretto: quel Markdown è di 48 byte, solo marcatori di
pagina. Prima del difetto 3 avrebbe potuto produrre un chunk vuoto con un
vettore nullo.

## L'effetto collaterale che conta

Il fix ha ridotto la taglia dei chunk di ~5×, e questo **cambia le misure di
retrieval**. Sui due CCNL, strategia B:

|                 | prima (1200 parole) | dopo (1800 caratteri) |
| --------------- | ------------------- | --------------------- |
| chunk totali    | 97                  | **521**               |
| lunghezza media | 1206 token          | **224 token**         |
| BM25 recall@5   | 61%                 | **55%**               |
| di cui `codice` | 5/5                 | **3/5**               |

Il punteggio è **sceso**, e va letto bene: non è un peggioramento della
pipeline, è la fine di un'illusione. Con chunk da 1200 parole ognuno copriva
una decina di articoli, quindi "il chunk contiene l'ancora attesa" era quasi
gratis. Il 5/5 sui codici era in buona parte un artefatto della taglia.

Il 55% con chunk da 224 token è una misura molto più onesta — e i chunk
piccoli sono anche quelli che si vogliono davvero, perché il generatore riceve
contesto pertinente invece di dieci articoli da setacciare.

**Regola:** un recall alto su chunk enormi non è una buona pipeline di
recupero. Guardare sempre recall@5 e taglia media insieme.

## Cosa resta fragile

- **`MAX_CHARS` è tarato su questo modello.** Cambiare modello di embedding
  cambia sia il contesto sia il tokenizer: va rimisurato, non ereditato.
- **Il rapporto char/token è empirico.** Un documento con caratteristiche
  peggiori delle tabelle (CJK, base64, formule) potrebbe ancora sfondare. La
  guardia in `embed()` lo intercetterebbe con un messaggio chiaro invece di un 500.
- **La soluzione a prova di bomba sarebbe contare i token veri**, ma Ollama non
  espone il tokenizer. L'alternativa è caricare il tokenizer di Gemma
  separatamente, che aggiunge una dipendenza per un problema che 1800 caratteri
  già risolvono su questo corpus.
