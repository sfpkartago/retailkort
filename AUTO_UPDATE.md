# Automatisk ugentlig opdatering (data-feed + fallback)

Kortet på kartago.dk henter en frisk `retailkort_data.json` ved hver indlæsning og
falder tilbage til den indbyggede data, hvis feed'et er utilgængeligt. En GitHub Action
genopbygger feed'et ugentligt. **Når det først er sat op, rører du aldrig kartago.dk igen.**

## Sådan virker det
```
GitHub Action (hver mandag)                     kartago.dk (rørt ÉN gang)
  refresh_data.py  →  OK + Tesla friske            <iframe src="…/retailkort"> med
  rebuild.py       →  retailkort_data.json         FEED_URL sat til Pages-URL'en
  sanity-tjek      →  afbryder hvis tal kollapser        │
  git push         →  GitHub Pages server feed'et  ──────┘  (henter feed ved load)
```

## Engangsopsætning
1. **Opret et GitHub-repo** og push hele denne mappe op i det (inkl. `.github/`-mappen).
2. **Feed-URL er sat** i `kort_soeg.html` til GitHub Pages (samme kilde som kortet selv):
   `https://sfpkartago.github.io/retailkort/retailkort_data.json`
3. **Giv robotten skrive-adgang:** repo → Settings → Actions → General →
   Workflow permissions → "Read and write permissions".
4. **Upload `kort_soeg.html` til kartago.dk** denne ene sidste gang.
5. Færdig. Fra nu af opdaterer robotten kun feed'et — siden er urørt.
   (jsDelivr cacher branch-filer nogle timer, så en ny ugentlig opdatering kan tage lidt tid at slå igennem.)

## Hvad der er automatiseret
- **Ugentligt (Action), tank og lade:** OK-tankstationer + Tesla-superladere via deres
  offentlige API'er (`refresh_data.py`).
- **Ugentligt (Action), detailhandel, tank, spisesteder og ladere:** 75 kilder via `refresh_retail.py`
  — 58 kæder og 17 ladeoperatørers egne lister (fra 13-10-2026: E.ON, Uno-X, Allego, Eviny,
  Fastned, AmpGo, Q8, Clever, Ionity og OK tilføjes automatisk; Circle K, Norlys'
  lastbilstationer, Shell Recharge, PowerGo, Spirii, EDF og Stella meldes kun). De, der kun
  rapporteres, står i `KUN_RAPPORT`. Kørslen
  **tilføjer kun** nye butikker. Mulige lukninger og koordinat-afvigelser rapporteres
  i jobbets log og i `retail_refresh_report.txt` og skal vurderes i hånden.

  ⚠ Her stod tidligere at de øvrige mærker måtte hentes kvartalsvis i hånden, fordi
  "SPA-sider ikke kan automatiseres stabilt". Det var skrevet før `retail_sources.py`
  fandtes. En probe 16-09-2026 viste at alle 35 hentere svarer, de fleste på under et
  sekund.

  **Hvorfor den ikke erstatter:** en målt erstatnings-kørsel omskrev 1.248 adresser,
  genindførte 3 dubletter og forværrede 12 navne. `dawa.normalize_rows` er bygget til
  at normalisere rå kildeadresser ÉN gang; kørt igen på håndrettede data flytter den
  adressen til nærmeste DAWA-punkt. Se REFRESH_LOG 17-09-2026.

Sikkerhedsspærre: hvis en kilde returnerer skrald og tallene kollapser, fejler jobbet
**før** commit — så bliver det sidste gode feed liggende, og kortet viser stadig data.

**Rapporter:** `retail_refresh_report.txt`, `validation_report.txt`, `reconcile_report.txt`,
`cvr_report.txt` og `refresh_data_report.txt` committes hver uge; hver af dem skriver 'BLEV IKKE
FÆRDIG' først, så en død kørsel ikke ligner en ren. Et robots-stop for OK eller Tesla får jobbet til
at lyse rødt efter commit (GitHub sender en fejlmail), mens dataene fra de andre kilder udgives.

**Selvtest (fra 14-10-2026):** `tests/` kører to gange i hver kørsel og stopper jobbet, hvis
en regel er brudt. Først kode-testene (alt undtagen `test_data.py`), før noget hentes: hvert
netkald spørger robots.txt først (også ved omdirigeringer), ingen forbudte værter eller
Referer/Origin-headers, ingen e-mailadresser, registrene i `refresh_retail.py` hænger sammen,
og add-only-vagterne virker. Derefter `tests.test_data` på de nye data, efter genopbygningen og
før commit: BOM/CRLF, kolonner, sortering, dubletter, ladernes kW og antal, feedets og kortets
punkter. README's tal tjekkes i et eget trin, der ikke blokerer (en markørfejl må ikke stoppe ugens
data). (test_data kører ikke før hentningen: en README eller et feed, der er bagud, retter jobbets
egen rebuild.py.) Testene bruger ikke nettet og tager få sekunder. README.md's
datatal skrives af `rebuild.py` (`readme_tal.py`) og committes sammen med feedet.

## Test / kør manuelt
GitHub → Actions → "Ugentlig data-refresh" → "Run workflow". Se at jobbet bliver grønt, og at
`retailkort_data.json` opdateres, når data er ændret. Datostemplet følger CSV'ernes dato og flytter
sig kun, når data faktisk ændres.

## Hvis CORS driller
GitHub Pages sender normalt `Access-Control-Allow-Origin: *`. Skulle det volde problemer,
kan `FEED_URL` i stedet pege på jsDelivr:
`https://cdn.jsdelivr.net/gh/<BRUGER>/<REPO>@main/retailkort_data.json`
(fuld CORS, men cacher nogle timer — feed'et opdateres altså med lidt forsinkelse).
