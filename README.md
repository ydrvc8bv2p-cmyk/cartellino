# Cartellino V7 – catalog backend

Questa versione separa l'app dal catalogo aggiornabile.

## Cosa cambia

- `index.html` contiene l'app e mantiene il catalogo incorporato come fallback offline.
- `catalog.generated.json` è il catalogo aggiornabile che l'app prova a caricare all'avvio.
- `data/catalog.base.json` contiene i 4.110 prodotti / 53 marche già presenti.
- `data/sources.json` contiene fonti ufficiali e retailer configurati.
- `scripts/build_catalog.py` aggiorna e fonde i cataloghi da fonti pubbliche.
- `.github/workflows/update-catalog.yml` esegue l'aggiornamento automatico ogni settimana e può essere avviato manualmente.

## Immagini

L'app non copia né ripubblica le fotografie dei retailer. Conserva gli URL pubblici delle immagini e la pagina sorgente. Ogni prodotto può avere più `images`; se la prima immagine non si carica, l'app prova automaticamente le successive e poi un proxy immagine come fallback tecnico.

## Fonti

Priorità:
1. store ufficiale del marchio;
2. retailer affidabili;
3. discovery su retailer internazionali configurati.

Il crawler supporta:
- Shopify `products.json` / collection JSON;
- JSON-LD `Product`;
- OpenGraph come fallback;
- pagine categoria da cui vengono seguiti un numero limitato di link prodotto.

La discovery è configurata per cercare, tra gli altri, Farfetch, MR PORTER, Giglio, Tessabit, Italist, Luisaviaroma, Le Bon Marché e Galeries Lafayette. Il crawler controlla `robots.txt`, limita il numero di pagine e applica un ritardo fra le richieste.

## Aggiornare il catalogo

Da GitHub: **Actions → Update product catalog → Run workflow**.

Oppure in locale:

```bash
pip install -r requirements.txt
python scripts/build_catalog.py
```

Per un test più rapido senza discovery esterna:

```bash
python scripts/build_catalog.py --no-discovery
```

## Nota

Alcuni siti impediscono il crawling, rendono il contenuto solo via JavaScript o cambiano struttura. In quei casi la build non si interrompe: mantiene i dati precedenti e prosegue con le altre fonti.
