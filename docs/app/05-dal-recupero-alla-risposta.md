# Dal recupero alla risposta

Documentazione di [`src/scripts/chat.py`](../../src/scripts/chat.py). Fino a
`retrieval.py` la pipeline finiva al `recall@5`: misura *se* i chunk giusti
arrivano, non cosa farne. Qui si chiude il giro.

```bash
python -m src.scripts.chat
python -m src.scripts.chat -q "Quanti giorni di ferie nel metalmeccanico?"
python -m src.main --chat
```

Il pezzo che si aggiunge è uno solo — **il prompt** — ed è l'unico che l'utente
vede. Tutto il lavoro sul chunking e sul ranking passa da lì o non passa
affatto.

## Il giro completo di un turno

```
domanda
   |  search_fn(question, collection, TOP_K)     riuso di retrieval.py
   v
5 Hit
   |  build_context()   ->  [1] doc | sezione | pag.\n<testo>
   |  build_messages()  ->  system (le regole) + user (passaggi + domanda)
   v
oclient.chat(CHAT_MODEL)
   |  collect_answer()  raccoglie tutto, poi wrap_answer() formatta
   v
risposta + fonti + benchmark
```

Nessuna riga di retrieval è duplicata: `STRATEGIES` arriva da `retrieval.py`,
e cambiare strategia è un flag (`-s semantic|hybrid|reranker`).

## Le quattro regole del prompt

```python
SYSTEM_PROMPT = """Answer the question using ONLY the passages below.

- If the passages don't contain the answer, say so clearly and stop — don't
  infer, calculate, or fill gaps with outside knowledge.
- Cite the passage after every claim, with its number in square brackets.
- If two or more passages cover the same topic but disagree or come from
  different sources, keep them distinct — don't silently pick one.
- Don't count or total anything across the corpus: you're given a handful of
  retrieved passages, not the whole corpus.
- Answer in the same language as the question."""
```

Ognuna risponde a un fallimento preciso del golden set, non a un'idea generica
di buona condotta:

| regola | il fallimento che previene | blocco |
| --- | --- | --- |
| astensione | il modello inventa una cifra quando il contesto *sembra* buono | X1, X2, X3 |
| citazione `[n]` | la risposta non è verificabile: nessuno sa da dove viene | tutti |
| fonti distinte | due CCNL gemelli, il modello ne sceglie uno in silenzio | S3, M3 |
| niente conteggi | il modello risponde `k`, cioè un parametro della pipeline travestito da fatto | A1, A2 |

**Il prompt è deliberatamente generico.** Il vector store non contiene solo i
due CCNL: ci sono 288 documenti eterogenei (atti del Congresso, report DHS/DOE,
paper) senza relazione tra loro. Una regola scritta su misura per i contratti
collettivi si romperebbe appena il retrieval pesca altrove — cosa che succede
davvero, come si vede nelle fonti di una domanda vaga.

## Tre decisioni, e cosa costano

### Default `hybrid`, non `reranker`

Il reranker costa **una chiamata al modello per ognuno dei 30 candidati**. È il
modo giusto di misurare, non di chiacchierare: in chat significa decine di
secondi per turno. Resta disponibile con `-s reranker`.

### Ogni turno è indipendente

La domanda va al retrieval così com'è. Un *"e nel commercio?"* dopo una domanda
sul metalmeccanico recupera male, perché da sola quella frase non nomina
l'argomento. Farlo funzionare richiede riscrivere la domanda alla luce dei turni
precedenti (*query rewriting*): è un pezzo a sé, e qui non c'è. Dichiararlo è
meglio che fingere una memoria conversazionale che non esiste.

### Si raccoglie tutta la risposta, poi si formatta

La prima versione stampava i token in streaming: il primo token si vedeva
subito, ma **gli a-capo del modello finivano a schermo così com'erano**, senza
rientro né larghezza massima. Per allineare il testo bisogna averlo tutto.

`wrap_answer()` manda a capo **riga per riga**, non riempiendo i paragrafi: se
il modello produce un elenco o una tabella, unire le righe la distruggerebbe.

## Gli score sotto la risposta

```
Fonti
  [1] 100% high   Art.16 - Ferie
                  ccnl_metalmeccanico_industria_conflavoro · pag. 25
  [2]  97% high   Art.18 - Lavoro festivo
                  ccnl_commercio_terziario_distribuzione_e_servizi · pag. 18

  Golden set, questa strategia: 61% chunk attesi · 59% domande complete
```

### Perché gli score vanno normalizzati

Le tre strategie producono numeri su scale incomparabili — lo stesso problema
che [RRF risolve fondendo le posizioni](03-fusione-rrf-e-reranking.md):

| strategia | scala grezza | normalizzazione |
| --- | --- | --- |
| `semantic` | coseno 0 → 1 | nessuna, è già in scala |
| `hybrid` | RRF ~0.01 → 0.033 | diviso il massimo teorico `2/(RRF_K+1)` |
| `reranker` | punteggio LLM 0 → 10 | diviso 10 |

Il massimo teorico di RRF è un chunk **primo in entrambe le classifiche**:
`1/(60+1) + 1/(60+1)`. Senza normalizzare, una sola soglia di confidenza
sarebbe giusta per una strategia e arbitraria per le altre due.

### Il benchmark è un riferimento, non un giudizio sulla singola risposta

`61% chunk attesi` è il `recall@5` misurato su tutto il golden set con
`recall_at_k()` — lo stesso di `retrieval.py`, non un numero inventato per
quella domanda. Serve a leggere lo score della singola fonte in scala: uno
score alto su una strategia che recupera il 61% delle volte non è una garanzia.

Si calcola **una volta all'avvio** e resta in cache. Nella prima versione era
lazy, e l'avviso *"prima misurazione, può volerci qualche minuto"* compariva
**sotto le fonti** — cioè quando l'attesa era già finita. L'attesa va dichiarata
prima di farla partire.

## Il dettaglio che non si vede: due formati per la stessa sezione

Il payload porta la catena completa dei titoli aperti:

```
CONTRATTO COLLETTIVO NAZIONALE DI LAVORO > SVOLGIMENTO DEL RAPPORTO DI LAVORO >
Art.7 - Articolazione dell'orario di lavoro > Art. 7 bis – Lavoratori
Discontinui > Art.16 - Ferie
```

Nel **prompt** va per intero: la gerarchia è contesto utile. A **schermo** no —
occupa tre righe e l'unico anello che descrive il chunk è l'ultimo. Da lì
`short_section()`, che tiene l'ultimo anello, toglie il markup (`<u>`, `**`
ereditati dai titoli Markdown) e tronca a 62 caratteri.

Su un modello piccolo quella catena non è neutra: è **la prima cosa che copia**
invece di leggerla. Vedi
[../problems/03-generatore-troppo-piccolo.md](../problems/03-generatore-troppo-piccolo.md).

## Cosa non c'è

- **Nessuna memoria conversazionale**, per la ragione detta sopra.
- **Nessun filtro sui metadati.** `visibility` e `version` sono nel payload e
  nessuno li usa: in produzione il filtro di visibilità va applicato *prima*
  del ranking.
- **Nessun controllo che la citazione `[n]` esista davvero.** Se il modello
  scrive `[7]` con 5 passaggi in contesto, nessuno se ne accorge. La
  valutazione in [06](06-valutare-le-risposte.md) verifica solo che una
  citazione ci sia, non che punti a qualcosa.
