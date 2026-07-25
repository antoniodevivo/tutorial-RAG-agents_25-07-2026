# Valutare le risposte, non solo il recupero

Documentazione di [`src/scripts/generation.py`](../../src/scripts/generation.py).

```bash
python -m src.scripts.generation
python -m src.scripts.generation -s semantic --limit 8
python -m src.main --evalgen     # solo coi default: main.py valida per primo
                                 # e non conosce -s/--limit
```

`recall@5` risponde a *"il chunk giusto è arrivato?"*. Restano fuori le due
domande che contano per chi legge la risposta:

1. il fatto atteso è **nella** risposta, o il modello aveva il chunk giusto
   davanti e ha scritto altro?
2. quando la risposta non c'è nel corpus, il modello si astiene o inventa?

La seconda è la metà del golden set che nessuna metrica di retrieval può
toccare: le 5 domande dei blocchi A e X **non hanno chunk atteso**, e il
retrieval restituirà comunque qualcosa di pertinente.

## La misura che conta: separare le due colpe

È la richiesta esplicita del punto 2 di [come usare il golden
set](../../eval/golden_set.md#come-usarlo): *«separa gli errori di retrieval da
quelli di generazione»*. Senza, **"fondatezza" è solo il recall travestito**.

```python
if entry.get("abstain"):
    return {"ok": has_abstained(answer), ...}
facts = [is_grounded(answer, exp["anchor"]) for exp in entry["expected"]]
return {"ok": all(facts),
        "retrieved": all(found(exp, hits) for exp in entry["expected"])}
```

`found()` è **la stessa funzione di `recall_at_k()`**: l'ancora è dentro un
chunk recuperato? Costa zero chiamate in più — gli `hits` sono già lì — e
divide le domande in due gruppi che vanno letti separatamente:

| misura | su quali domande | cosa dice |
| --- | --- | --- |
| `fondatezza` | tutte quelle con risposta attesa | la **catena intera**: non può superare il `recall@5` |
| `fedeltà` | solo quelle in cui il chunk è arrivato | il **generatore da solo** |

## Il risultato

`gemma4:cloud`, strategia `hybrid`, collection `from_structure_chunking`:

```
misura                   cosa vuol dire
----------  -----  ----  -------------------------------------------------
fondatezza  17/27  63%   il fatto atteso e' nella risposta (catena intera)
fedelta'    16/16  100%  ...quando il chunk giusto era stato recuperato
astensione  4/5    80%   il modello ammette di non poter rispondere
citazioni   25/32  78%   la risposta cita almeno un passaggio

tipo             superate
---------------  ----------
semplice         10/10
parafrasi        2/5
codice           2/5
tabella          2/4
multi-passaggio  1/3
aggregazione     1/2
assente          3/3
```

**Fedeltà 16/16.** Quando il retrieval porta il chunk giusto, il generatore lo
usa correttamente ogni volta. Zero allucinazioni su materiale corretto.

Questo cambia la lettura del `63%`: non è un difetto del modello, è il
`recall@5 61%` che riemerge. Due controlli incrociati lo confermano:

- 16 domande su 27 con **tutte** le ancore recuperate = **59%**, che è
  esattamente il `complete` misurato da `recall_at_k()` sulla stessa
  configurazione;
- la colonna `colpa` addebita 10 fallimenti su 11 al retrieval, e la risposta è
  quasi sempre *"i passaggi forniti non contengono..."*.

```
id    tipo             colpa       risposta (troncata)
----  ---------------  ----------  ------------------------------------------
P1    parafrasi        retrieval   I forniti passaggi non contengono informa…
C3    codice           retrieval   I testi forniti non contengono informazio…
T2    tabella          retrieval   I documenti forniti non indicano il valor…
M1    multi-passaggio  retrieval   In base ai testi forniti: * Preavviso: …
A2    aggregazione     generatore  Il corpus rinvia alla contrattazione di s…
```

### L'unico vero errore del generatore

**A2** — *"In quanti punti del corpus si rinvia alla contrattazione di secondo
livello?"* Il modello ha elencato i punti trovati invece di astenersi. È
esattamente il fallimento previsto dal golden set: *«il retrieval restituirà
`top_k` chunk contenenti l'espressione, e il modello risponderà con `k` — cioè
con un parametro della pipeline travestito da fatto»*.

La regola *"don't count or total anything"* non ha retto. **A1 invece è
passata**, e tutte e 3 le domande del blocco X sono corrette: 3/3
sull'astensione difficile, quella in cui il contesto recuperato *sembra*
pertinente.

### La lettura per tipo

`semplice 10/10` contro `parafrasi 2/5` e `codice 2/5`. È la stessa forma già
vista sul retrieval puro in [04-recall-at-5.md](04-recall-at-5.md): il totale
non è azionabile, la ripartizione sì. E dice dove intervenire — a monte, sul
recupero, non sul prompt.

## Il giudice

Il confronto tra fatto atteso e risposta lo fa un LLM. È la stessa forma del
reranker di [retrieval.py](../../src/scripts/retrieval.py) — un modello che
legge due testi **insieme** ed emette un verdetto — e ne condivide il limite.

```python
def judge(prompt: str) -> bool:
    """Verdetto binario. Tutto cio' che non e' un SI' esplicito e' un no."""
```

Il default binario è verso il **no**: una risposta ambigua del giudice conta
come fallimento. Su una metrica di qualità, sbagliare per eccesso di severità è
il verso giusto.

Le citazioni invece si contano senza modello — `\[\d+\]`, o c'è o non c'è.
Spendere una chiamata LLM per una regex è il modo più veloce di rendere una
valutazione troppo cara per essere rilanciata spesso.

## I limiti, dichiarati

**Il giudice è lo stesso modello che genera.** Un modello che valuta se stesso è
indulgente sui propri errori. Tenerne due complicherebbe il setup senza cambiare
conclusioni che qui sono **comparative** — serve a confrontare strategie sullo
stesso set, non a dichiarare una percentuale assoluta di bontà. Vale la stessa
avvertenza del `recall@5`.

**Il fatto atteso è l'ancora del retrieval, non una risposta di riferimento.**
L'ancora è una citazione letterale troncata (`"26 giorni lavorativi se presta la
propria attivit"`), nata per verificare che un chunk contenga un passaggio. Il
prompt del giudice lo dice esplicitamente — *«the reference may be cut off
mid-word: judge the fact it expresses»* — ma resta un riuso.
[`golden_set.md`](../../eval/golden_set.md) ha il campo **Risposta** scritto a
mano per ognuna delle 32 domande; il `.jsonl` no. Portarlo nel JSONL è il passo
che renderebbe questa misura solida.

**`citazioni 78%` non verifica che la citazione punti a qualcosa.** 7 risposte
su 32 non citano nessun passaggio — quasi tutte quelle in cui il modello si
astiene, dove in effetti non c'è niente da citare. Ma un `[7]` con 5 passaggi in
contesto passerebbe il controllo.

**32 domande sono poche.** Una domanda vale il 3%: due che passano per fortuna
spostano il totale di 6 punti.

## La conseguenza per la pipeline

Il collo di bottiglia è il **retrieval**, non la generazione. Con `fedeltà
100%`, migliorare il prompt o cambiare generatore non sposta niente: il tetto è
il `recall@5`. Lo stesso principio già scritto per il reranker in
[03](03-fusione-rrf-e-reranking.md) — *il reranker non recupera niente* — vale
un anello più in là:

```
fondatezza  ≤  recall@5
```

E c'è un dato che merita attenzione: sulla collection `from_structure_chunking`
la strategia `semantic` misura `recall@5 65%`, la `hybrid` **61%**. L'ibrido
qui non è cumulativo, è peggiorativo. Il posto dove guardare è
[02-keyword-sigle-bm25.md](02-keyword-sigle-bm25.md): il tokenizer BM25
polverizza le sigle puntate, e su un corpus in cui 288 documenti su 291 sono
rumore in inglese, la gamba lessicale può portare in classifica più rumore che
segnale.
