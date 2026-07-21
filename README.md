# Danmark: Superladere, Fastfood-kæder og Tankstationer

Opdateret 9. juli 2026. Alle rækker har adresse + koordinater (Latitude/Longitude).
CSV'er er UTF-8 med BOM (æ/ø/å vises korrekt i Excel).

## Filer
- `kort_soeg.html` — INTERAKTIVT KORT MED ADRESSESØGNING: DAWA-adressesøgning der flyver til enhver adresse og viser nærmeste stationer. Kategori-knapper, farve pr. mærke, klik-info, zoom/panorering. **Selvstændig:** kort-motoren (Leaflet + markercluster) er indlejret i filen, så den virker uden CDN — kun baggrundsfliserne (OpenStreetMap) og adressesøgningen (DAWA) kræver internet. Viser et synligt datostempel ("Data pr. …") så man altid kan se hvor friskt det er.
- `kaede_adresser.xlsx` — Excel med 3 faner (Superladere, Fastfood, Tankstationer). Latitude/Longitude/effekt/antal er ægte tal-celler (kan sorteres/filtreres numerisk).
- `superladere_dk.csv` — 788 superladere ≥250 kW (officielle ladekort + Tesla)
- `fastfood_kaeder_dk.csv` — 319 restauranter fra fastfood-kæderne
- `tankstationer_dk.csv` — 2.149 tankstationer (officielle findere + OK-API)
- `rebuild.py` — genopbygger `kort_soeg.html` + `kaede_adresser.xlsx` + `retailkort_data.json` ud fra de tre CSV'er (kør efter refresh/rettelser)
- `retailkort_data.json` — data-feed som kortet henter live (med indbygget fallback); se `AUTO_UPDATE.md`
- `AUTO_UPDATE.md` + `.github/workflows/weekly-refresh.yml` — ugentlig automatisk opdatering via GitHub Actions

## ⚡ Superladere (≥250 kW) — 788
Kilde: operatørernes officielle ladekort/API'er (Clever, Norlys, Circle K, E.ON, OK, Shell Recharge, Ionity m.fl.); Tesla autoritativt fra supercharge.info; adresser via DAWA.
Norlys 170, Clever 157, Circle K 130, OK 72, E.ON 68, Tesla 35, Uno-X 35, EWII 28,
Shell Recharge 27, Allego 14, Ionity 14, Eviny 10, Spirii 9, Stella 8, Fastned 7,
AmpGo 1, Better Energy 1, EDF 1, PowerGo 1.
Regel: effekt ≥250 kW, ELLER Ionity (altid 350 kW), ELLER Tesla Supercharger. Tesla er hentet fra supercharge.info (kun OPEN ≥250 kW — udelukker 150 kW V2 og destination-ladere). Adresser via DAWA.

## 🍔 Fastfood-kæder — 319
McDonald's 121, Burger King 61, Sunset Boulevard 47, Jagger 18, Carl's Jr. 15, Subway 15,
Halifax 11, Gasoline Grill 10, Cocks & Cows 7, Domino's Pizza 6, Max Burgers 6, Five Guys 1, KFC 1.
Kilde: kædernes officielle locators/API'er; koordinater via DAWA.

## ⛽ Tankstationer — 2.149 (alle mærker)
OK 690, Uno-X 279, Circle K 213, Shell 211, Ingo 196, Go'on 194, F24 143, Q8 106, OIL! 71,
CNG/biogas 20, Oles Olie 8, Lavpris 6, Øboens 4, HK Benzin 3, Uafhængig 3, KP Benzin 1, Kai Dige Bach 1.
Kilde: OK fra officielt API; øvrige fra officielle findere/OpenStreetMap, adresser via DAWA. Marina-, flyplads-
og truckanlæg er holdt ude. Officiel brancheopgørelse (Drivkraft Danmark): ~2.145 — vi rammer plet.

## Kortet (kort_soeg.html)
- Form = kategori (trekant=superlader, firkant=fastfood, cirkel=tankstation)
- Farve = mærke/operatør (signaturforklaring i højre side; klik for at skjule)
- Klik på et punkt → navn, adresse, mærke (+ effekt/stik for ladere)
- Kategori til/fra, DAWA-adressesøgning (flyver til adressen + viser nærmeste stationer), zoom (scroll) og panorering (træk)

## Ingen samlekategorier
Alle punkter er tilknyttet et navngivet mærke — ingen "Andre" eller "(ukendt)". De umærkede superladere blev identificeret (via navn/nærmeste hub-nabo), OSM-stavefejl er flettet (Cirkel K/Statoil→Circle K, Ckever→Clever, EVII→EWII, Fasned→Fastned), og truck/flyveplads-poster fjernet fra tank. "Uafhængig" bruges kun om stationer der reelt ikke tilhører en kæde.

## HK Benzin → Shell Express
HK Benzin er nu nede på 3 anlæg — resten er konverteret til Shell Express (DCC Energi-handlen, godkendt Q2 2026). Følg konverteringen ved næste refresh, se `REFRESH.md`.

## Kvalitet
Sidste `validate.py`-kørsel: **0 hårde fejl**, 1 benign advisory (Clever "Horsens N pendlerparkering" — koordinaten ligger ved selve pendlerparkeringen ~350 m fra det registrerede adressepunkt; reelt korrekt). Kør `python3 validate.py` efter hvert refresh.

## Sådan holdes kortet korrekt over tid
Kortets punkter er et frosset øjebliksbillede — de bliver ikke automatisk forkerte, men de bliver forældede. Fast rutine:
1. `python3 refresh_data.py` — friske OK + Tesla (+ workflow-scraperne i `REFRESH.md` for øvrige mærker)
2. `python3 validate.py` — skal give 0 hårde fejl
3. `python3 rebuild.py` — genopbyg kort + Excel (opdaterer også datostemplet)

**Automatisk (anbefalet):** de to trin ovenfor (frisk OK+Tesla → genopbyg feed) kan køre ugentligt uden hånd via GitHub Actions — kortet henter så det friske feed selv, og siden på kartago.dk røres aldrig. Se `AUTO_UPDATE.md`.

Bemærk: kortet er selvstændigt (Leaflet indlejret), så visningen overlever selv hvis CDN'er forsvinder; kun OSM-fliser + DAWA-søgning er live-afhængigheder. Ved import: pas på Clever/Eviny roaming-dubletter (samme Eviny-site kan optræde som en Clever-skygge) — se den fjernede "Veri Centret".
