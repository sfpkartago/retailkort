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
- **Ugentligt (Action):** OK-tankstationer + Tesla-superladere via deres offentlige API'er.
  De to mest dynamiske, rene kilder holdes friske uden vedligehold.
- **Kvartalsvis (manuelt):** de øvrige mærker hentes via workflow-scraperne i `REFRESH.md`
  (SPA-sider kan ikke automatiseres stabilt). Kør dem, `python3 rebuild.py`, commit.

Sikkerhedsspærre: hvis en kilde returnerer skrald og tallene kollapser, fejler jobbet
**før** commit — så bliver det sidste gode feed liggende, og kortet viser stadig data.

## Test / kør manuelt
GitHub → Actions → "Ugentlig data-refresh" → "Run workflow". Se at `retailkort_data.json`
opdateres, og at datostemplet på kortet flytter sig.

## Hvis CORS driller
GitHub Pages sender normalt `Access-Control-Allow-Origin: *`. Skulle det volde problemer,
kan `FEED_URL` i stedet pege på jsDelivr:
`https://cdn.jsdelivr.net/gh/<BRUGER>/<REPO>@main/retailkort_data.json`
(fuld CORS, men cacher nogle timer — feed'et opdateres altså med lidt forsinkelse).
