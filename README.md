# Cartellino V8.1

PWA per archivio guardaroba personale con catalogo premium multi-fonte e riconoscimento foto OCR + AI.

## Installazione PWA

Pubblicare i file nella root di GitHub Pages, aprire il sito con Safari su iPhone e scegliere **Condividi → Aggiungi a Home**.

## Catalogo

`catalog.generated.json` è il catalogo usato dall'app. La base inclusa contiene prodotti correnti e di archivio da fonti pubbliche. Le immagini non vengono copiate nel repository: vengono referenziate dagli URL pubblici delle fonti e l'app usa più candidati/fallback quando disponibili.

Il backend opzionale (`scripts/build_catalog.py`) tenta di ampliare le marche sotto la soglia configurata in `data/sources.json`, privilegiando fonti ufficiali e retailer pubblici. Rispetta robots.txt e rate limit; siti chiusi, autenticati o che vietano scraping non vengono usati come sorgenti automatiche.

## Aggiornamento automatico

Il workflow `.github/workflows/update-catalog.yml` può essere avviato manualmente dalla scheda **Actions** e gira anche settimanalmente. Richiede solo i permessi `contents: write` del `GITHUB_TOKEN` del repository.

## Riconoscimento foto

La pipeline prova a combinare:
- foto prodotto;
- foto ravvicinata etichetta/logo;
- foto suola/codice;
- OCR delle scritte;
- tipo prodotto e colore sull'oggetto centrale;
- confronto con il catalogo per marca/modello.

Marca e modello sono suggerimenti probabilistici: i risultati vanno confermati prima del salvataggio.
