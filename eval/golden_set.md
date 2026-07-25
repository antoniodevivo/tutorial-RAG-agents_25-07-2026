# Golden set — 30 domande scritte a mano

Set di valutazione per il retrieval sul corpus in `docs/`. Ogni domanda ha la
risposta attesa e **quale pezzo di corpus deve tornare**. Scritto a mano
leggendo i documenti: ogni numero qui dentro è stato verificato sul testo.

## Il corpus: cosa c'è davvero

`docs/md/` contiene 291 Markdown, ma non sono un corpus omogeneo:

| | Quanti | Cosa sono |
| --- | --- | --- |
| CCNL Conflavoro PMI | 2 | Metalmeccanico industria (01/07/2026–30/06/2029) e Commercio, Terziario, Distribuzione e Servizi (01/02/2023–31/01/2026). Italiano, ~100 pagine l'uno, struttura ad articoli, molte tabelle. |
| Documenti hash | 288 | Atti del Congresso USA, report DHS/DOE, moduli statali, paper, verbali. Inglese, scaricati alla rinfusa, senza relazione tra loro né con i CCNL. |
| CV | 1 | `CV_Antonio_DeVivo_ITA_v5.0.3.md`, **48 byte**: il PDF non ha prodotto testo. |

Le 30 domande sono ancorate ai **due CCNL**, l'unico dominio del corpus in cui
esista una risposta verificabile. Gli altri 288 documenti non sono esclusi dalla
valutazione: restano nell'indice come rumore, ed è esattamente il loro compito.

I due CCNL sono quasi gemelli — stesso editore, stessa struttura, stessi
istituti con **numerazione degli articoli diversa** e **valori diversi**. È la
trappola più realistica del corpus: molte domande sono progettate perché una
risposta presa dal contratto sbagliato sembri corretta.

## Come è identificato il chunk atteso

`documento › articolo › pagina` + una **ancora** (citazione letterale che deve
comparire nel chunk recuperato). Non l'indice di riga del `.jsonl`: quello
cambia a ogni modifica di `MAX_TOKENS` o di strategia, l'ancora no. Il criterio
di successo è *il chunk recuperato contiene l'ancora*, valutabile su qualsiasi
configurazione di chunking.

> **Nota sui metadati attuali.** Con `MAX_TOKENS = 1200` *parole*, i chunk della
> strategia B superano gli 8.000 caratteri e coprono una decina di articoli;
> `section` registra l'ultimo titolo del chunk, non quello del contenuto. Un
> chunk etichettato `Tabella retributiva A` può contenere le declaratorie dei
> livelli. Non usare `section` come chiave di valutazione finché non è sistemato.

Legenda del campo **Chunk atteso**: `MM` = metalmeccanico, `CO` = commercio.

---

## 1. Domande semplici (10) — il funzionamento base

### S1 — Da quando a quando è in vigore il CCNL metalmeccanico?
- **Risposta:** Tre anni, dal 1° luglio 2026 al 30 giugno 2029. Resta efficace oltre la scadenza fino al rinnovo; disdetta ammessa almeno sei mesi prima.
- **Chunk atteso:** MM › `VALIDITÀ DEL CONTRATTO` › pag. 10
- **Ancora:** "durata pari a tre anni, decorrente dal 1 Luglio 2026 al 30 Giugno 2029"
- **Trappola:** il CO ha la sua sezione `VALIDITÀ DEL CONTRATTO` con date diverse (01/02/2023–31/01/2026). Recuperare quella è un fallimento, non un quasi-successo.

### S2 — Quanti giorni di ferie annuali spettano nel CCNL metalmeccanico?
- **Risposta:** 26 giorni lavorativi su sei giorni settimanali, 22 su cinque. Oltre 18 anni di anzianità: +4 giorni (6 gg/sett) o +3 (5 gg/sett).
- **Chunk atteso:** MM › `Art.16 - Ferie` › pag. 25
- **Ancora:** "26 giorni lavorativi se presta la propria attività per sei giorni la settimana"
- **Trappola:** il CO (`Art.19 - Ferie`, pag. 18) dice "4 settimane". Formulazione diversa, documento diverso, risposta diversa.

### S3 — Quante ore di permessi retribuiti sostituiscono le festività soppresse?
- **Risposta:** 32 ore, da utilizzare entro l'anno solare.
- **Chunk atteso:** MM › `Art.17 - Permessi retribuiti` › pag. 25
- **Ancora:** "i lavoratori usufruiranno di 32 ore di permessi retribuiti"
- **Trappola:** il CO ha lo **stesso identico periodo** in `Art.15` (pag. 17). Due chunk indistinguibili sul piano semantico: la domanda non specifica il settore, quindi il sistema corretto o chiede di disambiguare o restituisce entrambi. Restituirne uno solo con sicurezza è il fallimento da osservare.

### S4 — Quali orari definiscono il lavoro notturno?
- **Risposta:** Il lavoro prestato tra le 22.00 e le 6.00, salvo turni regolari.
- **Chunk atteso:** MM › `Art.13 - Lavoro notturno` › pag. 23
- **Ancora:** "è considerato lavoro notturno quello prestato tra le 22.00 e le 6.00"

### S5 — Quanti giorni di permesso spettano per il decesso di un familiare?
- **Risposta:** 3 giorni retribuiti se l'evento è nella città o provincia della sede di lavoro; 5 giorni, di cui 3 retribuiti, se fuori provincia.
- **Chunk atteso:** MM › `Art.19 - Permessi per decesso e gravi infermità di familiari` › pag. 26
- **Ancora:** "tre giorni di permesso retribuito se l'evento luttuoso si sia verificato nella città sede di lavoro"

### S6 — Quando va pagata la tredicesima nel CCNL commercio?
- **Risposta:** In coincidenza con la vigilia di Natale, pari a una mensilità della retribuzione in atto, esclusi gli assegni familiari.
- **Chunk atteso:** CO › `Art.29 - Tredicesima mensilità` › pag. 22
- **Ancora:** "In coincidenza con la vigilia di Natale di ogni anno"

### S7 — Il CCNL commercio prevede la quattordicesima?
- **Risposta:** Sì, `Art.29 bis`: una mensilità erogata con la mensilità di giugno.
- **Chunk atteso:** CO › `Art.29 bis - Quattordicesima mensilità` › pag. 22
- **Ancora:** "In coincidenza con la mensilità di giugno"
- **Trappola:** il MM **non** ha la quattordicesima. Se la domanda venisse posta sul metalmeccanico la risposta corretta sarebbe l'astensione: utile come variante.

### S8 — Con che cadenza maturano gli scatti di anzianità nel metalmeccanico e quanti al massimo?
- **Risposta:** Cadenza biennale, massimo 5 scatti.
- **Chunk atteso:** MM › `Art.31 - Scatti di anzianità` › pag. 32
- **Ancora:** "Gli scatti maturano con una cadenza biennale e per un massimo di 5 scatti"
- **Trappola:** il CO ha abolito gli scatti di anzianità e li ha sostituiti con `Art.31 Scatti di merito o di professionalità`, rinviati all'accordo aziendale. Stesso numero di articolo, istituto diverso.

### S9 — Cosa succede a un autista del commercio a cui viene ritirata la patente?
- **Risposta:** Conservazione del posto per 6 mesi, senza retribuzione né maturazione di alcun istituto contrattuale (se il motivo non comporta licenziamento).
- **Chunk atteso:** CO › `Ritiro patente` (dentro `Art.45`) › pag. 26
- **Ancora:** "diritto alla conservazione del posto per un periodo di 6 mesi"

### S10 — Quanto vale l'indennità di cassa nel metalmeccanico?
- **Risposta:** 6% della paga base nazionale conglobata di cui all'art.26, per chi è adibito con continuità a operazioni di cassa con piena responsabilità della gestione.
- **Chunk atteso:** MM › `Art.25 ter - Indennità di cassa e maneggio di denaro` › pag. 31
- **Ancora:** "un'indennità di cassa e di maneggio di denaro nella misura del 6%"

---

## 2. Con sinonimi/parafrasi (5) — la ricerca semantica

Nessuna di queste domande usa il vocabolario del contratto.

### P1 — Quanti giorni di vacanza all'anno ho se lavoro dal lunedì al venerdì?
- **Risposta:** 22 giorni lavorativi (26 per chi lavora su sei giorni).
- **Chunk atteso:** MM › `Art.16 - Ferie` › pag. 25
- **Ancora:** "22 giorni lavorativi se presta la propria attività per cinque giorni la settimana"
- **Cosa testa:** "vacanza" non è mai usato per le ferie. Ma la parola **esiste nel documento** con tutt'altro significato: `Art.25 quater – Indennità di vacanza contrattuale` (pag. 31). Un retrieval lessicale va dritto sull'articolo sbagliato; è il caso in cui BM25 non solo manca il bersaglio, lo manca *con sicurezza*.

### P2 — Se mi rompo una gamba sciando, per quanto tempo l'azienda è obbligata a tenermi il posto?
- **Risposta:** Comporto breve, sulle assenze dei tre anni precedenti: 183 giorni fino a 3 anni di anzianità, 274 tra 3 e 6 anni, 365 oltre i 6 anni. Comporto prolungato in casi specifici.
- **Chunk atteso:** MM › `Art.36 - Periodo di comporto` › pag. 34
- **Ancora:** "365 giorni di calendario, per anzianità di servizio oltre i 6 anni"
- **Cosa testa:** "comporto" e "conservazione del posto" non compaiono nella domanda; "infortunio non sul lavoro" va inferito da "sciando".

### P3 — Se me ne voglio andare, con quanto anticipo devo avvisare l'azienda?
- **Risposta:** Dipende da livello e anzianità: da 10 giorni (5°–7° livello, fino a 5 anni) a 4 mesi (Quadri/1°/2°S, oltre 10 anni).
- **Chunk atteso:** MM › `Art.51 - Preavviso` › pag. 47
- **Ancora:** "|5°, 6° e 7°|10 giorni|20 giorni|1 mese|"
- **Cosa testa:** "preavviso" non è nella domanda, e la risposta è una tabella: serve che il chunk contenga sia la tabella sia l'intestazione che la rende leggibile.

### P4 — Mi sposo il mese prossimo: posso stare a casa?
- **Risposta:** Sì, 15 giorni consecutivi di calendario di congedo matrimoniale (anche per unione civile), non computabili nelle ferie né nel preavviso. Spetta al lavoratore non in prova.
- **Chunk atteso:** MM › `Congedo matrimoniale` (dentro `Art.21 – Altre tipologie di congedi`) › pag. 27
- **Ancora:** "spetta un periodo di congedo di quindici giorni consecutivi di calendario"
- **Cosa testa:** "congedo" assente dalla domanda; e il titolo del blocco è un `######` dentro un articolo, quindi la strategia strutturale deve tenerlo come sezione a sé.

### P5 — Chi si occupa di antinfortunistica per conto dei dipendenti?
- **Risposta:** I Rappresentanti dei Lavoratori per la Sicurezza (RLS) e, dove non eletti, i Rappresentanti Territoriali (RLST).
- **Chunk atteso:** MM › `Art.6 - Rappresentanti dei Lavoratori per la sicurezza-RLS/RLST` › pag. 17
- **Ancora:** "Rappresentanti dei Lavoratori per la sicurezza-RLS/RLST"
- **Cosa testa:** "antinfortunistica" non compare **mai** nel metalmeccanico. L'unica occorrenza in tutto il corpus italiano è al plurale, nell'altro contratto e in tutt'altro contesto: CO `Art.49` (pag. 28), tra le infrazioni disciplinari — "danneggiamento volontario o messa fuori opera di dispositivi antinfortunistici". Il retrieval lessicale ha quindi un solo appiglio possibile, ed è il documento sbagliato all'articolo sbagliato: qui il denso non è un miglioramento, è l'unica strada.

---

## 3. Con codici, sigle, numeri di articolo (5) — la ricerca per parole chiave

### C1 — Cosa prevede l'art. 5 bis su MOG(S) e SGSL?
- **Risposta:** L'adozione di Modelli di Organizzazione e Gestione della Sicurezza e di Sistemi di Gestione della Salute e Sicurezza sul Lavoro.
- **Chunk atteso:** MM › `Art.5 bis - Adozione di MOG(S) e SGSL` › pag. 16
- **Ancora:** "Adozione di MOG(S) e SGSL"
- **Cosa testa:** sigla rara, con parentesi. Un embedding la tokenizza male; il match esatto la trova subito. È il caso da manuale in cui il retrieval ibrido batte il denso puro.

### C2 — Su quali riferimenti normativi si fondano le festività soppresse?
- **Risposta:** Legge n.54/1977 e DPR n.792/1985.
- **Chunk atteso (doppio, entrambi corretti):** MM › `Art.17 - Permessi retribuiti` › pag. 25 **e** CO › `Art.15 - Permessi retribuiti` › pag. 17
- **Ancora:** "festività soppresse di cui alla Legge n.54/1977 e al DPR n.792/1985"
- **Cosa testa:** la stessa frase, identica al carattere, in due documenti. Se il ranking ne restituisce due copie occupando i primi due slot del contesto, il budget è sprecato: serve deduplicazione a livello di testo, non di documento.

### C3 — Che cos'è l'EGR?
- **Risposta:** Elemento di Garanzia Retributiva, disciplinato dall'art.30 insieme al premio di risultato.
- **Chunk atteso:** MM › `Art.30 - Premio di risultato e Elemento di Garanzia Retributiva` › pag. 32
- **Ancora:** "Elemento di Garanzia Retributiva"
- **Cosa testa:** la sigla "EGR" **non compare mai** nel documento, solo la forma estesa. È l'inverso di C1: qui il match esatto fallisce e serve il semantico. Le due domande insieme dimostrano perché serve l'ibrido.

### C4 — Che ruolo ha l'art.7 della Legge n.604/1966 nel periodo di comporto?
- **Risposta:** Fa salva la sua disciplina rispetto al diritto alla conservazione del posto durante il preavviso.
- **Chunk atteso:** CO › `Art.36 - Periodo di comporto`, comma 3 › pag. 23
- **Ancora:** "salvo quanto previsto dall'art.7 della Legge n.604/1966"
- **Cosa testa:** due numeri di articolo nella stessa domanda (art.7 di una legge dentro l'art.36 di un contratto). La stessa legge è citata anche in `Art.130` del CO e `Art.124` del MM in tutt'altro contesto.

### C5 — Cosa disciplina l'Art.118 del CCNL metalmeccanico?
- **Risposta:** L'Ente Bilaterale autonomo del settore privato E.BI.A.S.P.
- **Chunk atteso:** MM › `Art.118 - Ente Bilaterale autonomo del settore privato E.BI.A.S.P.` › pag. 75
- **Ancora:** "Art.118 - Ente Bilaterale autonomo del settore privato E.BI.A.S.P."
- **Cosa testa:** **è l'unico articolo del CCNL che la conversione non ha reso come titolo Markdown** — è testo semplice (riga 4407). La strategia strutturale non lo vede come confine di sezione, quindi finisce assorbito nel chunk precedente con l'etichetta sbagliata. Un difetto della pipeline di conversione che solo una domanda mirata fa emergere.

---

## 4. Con risposta dentro una tabella (4) — il parsing

### T1 — Quanto dura il periodo di prova per un sesto livello metalmeccanico?
- **Risposta:** 1 mese e mezzo (durata ordinaria); 1 mese nella durata ridotta. Il 6° rientra nella fascia "Dal 7° al 5° livello".
- **Chunk atteso:** MM › `Art.2 - Periodo di prova` › pag. 14
- **Ancora:** "|Dal 7° al 5° livello|1 mese e mezzo|1 mese|"
- **Cosa testa:** la riga non nomina il 6° livello: va dedotto dall'intervallo. Se il chunk perde l'intestazione `|Livello|Durata ordinaria|Durata ridotta|`, le due colonne diventano indistinguibili e "1 mese e mezzo" e "1 mese" sono intercambiabili.

### T2 — Quanto vale uno scatto di anzianità per un secondo livello super?
- **Risposta:** € 37,00.
- **Chunk atteso:** MM › `Art.31 - Scatti di anzianità` › pag. 32
- **Ancora:** "|2S|€ 37,00|"
- **Cosa testa:** la chiave di riga è la sigla "2S". Nel resto del contratto lo stesso livello è scritto "Secondo livello S" e "2°S": tre grafie per la stessa cosa, e solo una è nella tabella.

### T3 — Quale sarà il minimo tabellare del settimo livello metalmeccanico dal 1° giugno 2028?
- **Risposta:** € 1.886,50.
- **Chunk atteso:** MM › `Tabella retributiva A` › pag. 95
- **Ancora:** "|Settimo livello|€ 1.786,00|€ 1.834,00|€ 1.886,50|"
- **Cosa testa:** la riga contiene **tre importi**, uno per decorrenza (01.07.2026 / 01.06.2027 / 01.06.2028). Senza l'intestazione nello stesso chunk la risposta è un tiro a indovinare tra tre numeri plausibili. È il test di parsing più severo del set.

### T4 — A che livello è inquadrato un Business Analyst nel CCNL commercio?
- **Risposta:** Secondo livello.
- **Chunk atteso:** CO › tabella dei profili professionali ICT › pag. 60
- **Ancora:** "|Business Analyst|Individua aree dove sono necessari cambiamenti del sistema informativo"
- **Cosa testa:** tabella con celle lunghe centinaia di caratteri e `<br>` interni — un solo profilo può saturare il chunk. Inoltre in questa tabella il footer di pagina è finito **dentro una cella**: la riga di ICT Operations Manager inizia con "Il contenuto di q" e la colonna successiva con "uesto contratto è di proprietà di Conflavoro PMI…". Il titolo più vicino sopra la tabella è `SETTIMO LIVELLO`, quindi il chunk eredita anche una sezione fuorviante. Tre difetti di parsing nello stesso punto.

---

## 5. Multi-passaggio (3) — i limiti del retrieval singolo

Nessuna di queste ha risposta in un chunk solo. Servono a misurare quanto in
fretta il sistema risponde comunque, con metà dell'informazione.

### M1 — Un quinto livello metalmeccanico assunto 12 anni fa si dimette: quanto preavviso deve dare e quale minimo tabellare percepisce dal 1° giugno 2027?
- **Risposta:** 1 mese di preavviso (fascia 5°/6°/7° livello, anzianità oltre 10 anni) e minimo di € 2.077,50.
- **Chunk attesi (2):**
  1. MM › `Art.51 - Preavviso` › pag. 47 — ancora: "|5°, 6° e 7°|10 giorni|20 giorni|1 mese|"
  2. MM › `Tabella retributiva A` › pag. 95 — ancora: "|Quinto livello|€ 2.023,00|€ 2.077,50|€ 2.137,00|"
- **Cosa testa:** due tabelle a 48 pagine di distanza, entrambe indicizzate per livello. Con `top_k` basso ne arriva una sola e la risposta esce dimezzata ma sicura di sé.

### M2 — Un autista del commercio fa una missione extraurbana di 14 ore: cosa gli spetta, e in cosa differisce dalla diaria ordinaria?
- **Risposta:** Un'indennità forfettaria pari all'81% della quota giornaliera della normale retribuzione (fascia 12–16 ore), **in sostituzione** della diaria; la diaria ordinaria sarebbe stata € 15 al giorno (missioni oltre le 8 e fino alle 24 ore).
- **Chunk attesi (2):**
  1. CO › `Trasferte e missioni` › pag. 25 — ancora: "una diaria di euro 15 al giorno per missioni eccedenti le 8 ore"
  2. CO › tabella indennità autisti › pag. 26 — ancora: "|da 12 a 16 ore|81%|"
- **Cosa testa:** i due pezzi sono **contigui nel documento ma separati dal salto di pagina**, con footer e intestazione in mezzo. Se il chunking taglia sul confine di pagina la tabella perde la frase che dice "in sostituzione della diaria" e la risposta diventa una somma illegittima dei due trattamenti.

### M3 — Un lavoratore con 8 anni di anzianità è più tutelato in malattia nel metalmeccanico o nel commercio?
- **Risposta:** Nel metalmeccanico: 365 giorni di comporto (anzianità oltre 6 anni) contro 180 giorni del commercio, che non gradua per anzianità. Il commercio arriva a 720 giorni solo per patologie di particolare gravità.
- **Chunk attesi (2, uno per documento):**
  1. MM › `Art.36 - Periodo di comporto` › pag. 34 — ancora: "365 giorni di calendario, per anzianità di servizio oltre i 6 anni"
  2. CO › `Art.36 - Periodo di comporto` › pag. 23 — ancora: "180 giorni di calendario con malattia continuativa certificata in un anno solare"
- **Cosa testa:** confronto tra documenti, con **stesso numero di articolo e stesso titolo**. È il caso in cui il ranking, vedendo due chunk quasi identici per similarità, ne tiene uno e scarta l'altro come ridondante — e il confronto diventa impossibile per costruzione.

---

## 6. Conteggio/aggregazione (2) — ciò che il RAG non sa fare

Qui non si misura la risposta, si misura se il sistema **ammette di non poterla dare**.

### A1 — Quanti articoli contiene il CCNL metalmeccanico?
- **Risposta:** La numerazione arriva a 143 (`Art.143 - Classificazione del personale`, pag. 83), più gli articoli *bis*, *ter*, *quater*. Nel Markdown i titoli di articolo sono 142: manca l'Art.118, che la conversione ha degradato a testo semplice (cfr. C5).
- **Chunk atteso:** **nessuno.** Non esiste un passaggio che dica quanti sono. La risposta richiede di enumerare l'intero documento, cioè di leggere ~100 chunk.
- **Cosa testa:** il fallimento tipico non è "non lo so", è che il modello prende l'ultimo numero visto in un chunk e lo spaccia per totale. Da segnare come errore anche se il numero esce giusto per caso.

### A2 — In quanti punti del corpus si rinvia alla "contrattazione di secondo livello"?
- **Risposta:** 3 occorrenze, tutte nel CCNL commercio; zero nel metalmeccanico, che usa "contrattazione collettiva decentrata".
- **Chunk atteso:** **nessuno.** Il conteggio esiste solo a livello di indice, non di documento.
- **Cosa testa:** aggregazione su tutto il corpus. Il retrieval restituirà `top_k` chunk contenenti l'espressione, e il modello risponderà con `k` — cioè con un parametro della pipeline travestito da fatto. È il modo più netto per vedere che il numero restituito dipende dalla configurazione, non dai documenti.

---

## 7. Con risposta assente dal corpus (3) — l'astensione

Le prime due hanno **forte sovrapposizione lessicale** con chunk realmente
presenti: il retrieval restituirà qualcosa di pertinente, e il modello dovrà
astenersi *nonostante* il contesto sembri buono. È molto più difficile di una
domanda fuori tema, ed è il caso che si verifica in produzione.

### X1 — Qual è l'importo del buono pasto previsto dal CCNL commercio?
- **Risposta corretta:** *Il contratto non lo stabilisce.* I buoni pasto compaiono solo come materia demandata alla contrattazione di secondo livello (CO `Art.53`, pag. 31; MM pag. 49) e tra le voci comprimibili nelle crisi aziendali (`Art.53 bis`). Nessun importo.
- **Chunk che verranno recuperati:** CO › `Art.53 - Contrattazione collettiva decentrata` › pag. 31 — ancora: "mensa o buoni pasto"
- **Cosa testa:** il chunk giusto arriva, contiene le parole della domanda e non contiene la risposta. Il fallimento atteso è l'invenzione di una cifra, o il prestito del valore di un altro istituto (es. i 13,15 € del pasto in trasferta del metalmeccanico, pag. 41 — che è un rimborso, non un buono pasto).

### X2 — Quali aumenti retributivi sono previsti dal 2030 per il metalmeccanico?
- **Risposta corretta:** *Nessuno: il corpus non arriva al 2030.* La `Tabella retributiva A` si ferma alla decorrenza 01.06.2028 e il contratto scade il 30/06/2029. Oltre, c'è solo la regola di ultrattività e l'indennità di vacanza contrattuale (`Art.25 quater`).
- **Chunk che verranno recuperati:** MM › `Tabella retributiva A` › pag. 95 e `VALIDITÀ DEL CONTRATTO` › pag. 10
- **Cosa testa:** estrapolazione. Il modello ha davanti tre importi crescenti e una regola di adeguamento all'inflazione: ha tutto il necessario per **calcolare** una risposta plausibile e falsa. Astenersi qui è controintuitivo, ed è il punto.

### X3 — Quali certificazioni ha Antonio De Vivo?
- **Risposta corretta:** *Non ricavabile.* Il documento è nel corpus (`CV_Antonio_DeVivo_ITA_v5.0.3`) ma il Markdown è di 48 byte: solo i due marcatori di pagina, nessun testo. Il PDF non è estraibile con il convertitore attuale.
- **Chunk che verranno recuperati:** eventualmente un chunk vuoto o quasi, con `document: CV_Antonio_DeVivo_ITA_v5.0.3`.
- **Cosa testa:** non è un'assenza, è un **fallimento a monte del retrieval**. Il documento risulta indicizzato, il sistema lo conta come coperto, e nessuna metrica di retrieval se ne accorge — l'unica traccia è in `docs/md/problems/`. È il fallimento strutturale più grave del set, e nessuna delle altre 29 domande lo avrebbe rivelato.

---

## Come usarlo

1. **Prima il retrieval, da solo.** Per ognuna delle 25 domande con chunk atteso: il chunk che contiene l'ancora è tra i primi `k`? Recall@k prima di guardare le risposte generate. Se il chunk giusto non arriva, il resto non è diagnosticabile.
2. **Poi le risposte**, con i chunk giusti forzati nel contesto. Separa gli errori di retrieval da quelli di generazione.
3. **Le 5 domande finali** (A1, A2, X1, X2, X3) si valutano solo sul comportamento: astensione = successo; risposta plausibile = fallimento, anche se il numero è corretto.
4. **Non aggiustare le domande per farle passare.** Se una domanda fallisce sistematicamente, quella è la diagnosi: valore di `MAX_TOKENS`, assenza di overlap, tabelle spezzate, `section` inaffidabile, ranking che deduplica documenti gemelli.

### Punteggio

| Blocco | Domande | Metrica | Soglia di allarme |
| --- | --- | --- | --- |
| Semplici | S1–S10 | recall@5 | < 9/10 → problema di base |
| Parafrasi | P1–P5 | recall@5 | < 4/5 → il denso non lavora |
| Codici | C1–C5 | recall@5 | < 4/5 → serve retrieval ibrido |
| Tabelle | T1–T4 | risposta esatta | < 3/4 → chunking da rivedere |
| Multi-passaggio | M1–M3 | entrambi i chunk in top-k | < 2/3 → serve query decomposition |
| Aggregazione | A1–A2 | astensione | qualsiasi risposta numerica secca |
| Assenti | X1–X3 | astensione | qualsiasi risposta |
