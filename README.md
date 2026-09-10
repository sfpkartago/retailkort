# Danmark: Superladere, Fastfood-kæder og Tankstationer

Opdateret 10. september 2026. Alle rækker har adresse + koordinater (Latitude/Longitude).
CSV'er er UTF-8 med BOM (æ/ø/å vises korrekt i Excel).

## Filer
- `kort_soeg.html` — INTERAKTIVT KORT MED ADRESSESØGNING: DAWA-adressesøgning der flyver til enhver adresse og viser nærmeste stationer. Kategori-knapper, farve pr. mærke, klik-info, zoom/panorering. **Selvstændig:** kort-motoren (Leaflet + markercluster) er indlejret i filen, så den virker uden CDN — kun baggrundsfliserne (OpenStreetMap) og adressesøgningen (DAWA) kræver internet. Viser et synligt datostempel ("Data pr. …") så man altid kan se hvor friskt det er.
- `kaede_adresser.xlsx` — Excel med 3 faner (Superladere, Fastfood, Tankstationer). Latitude/Longitude/effekt/antal er ægte tal-celler (kan sorteres/filtreres numerisk).
- `superladere_dk.csv` — 798 ladeanlæg ≥250 kW: **784 til personbil + 14 lastbil-ladere**
  (kolonnen `Lastbil` = `ja` markerer sidstnævnte; de vises som eget lag på kortet)
- `fastfood_kaeder_dk.csv` — 319 restauranter fra fastfood-kæderne
- `tankstationer_dk.csv` — 2.142 tankstationer (officielle findere + OK-API)
- `dawa.py` — adressenormalisering mod DAWA. Enhver adresse verificeres mod rækkens
  EGEN koordinat: kildens husnummer beholdes kun hvis det findes og ligger ved anlægget,
  ellers vinder den nærmeste rigtige adresse. Se modulets docstring for hvorfor v1's
  fallback var farlig.
- `sources.py` — hentere for de kilder der har et stabilt endpoint (Clever, Ionity, Go'on,
  OK-ladere, Shell, Circle K-slugs). Kør `python3 sources.py` for et hurtigt liv-tjek.
- `reconcile.py` — afstemmer kilderne mod datasættet og RAPPORTERER til-/afgang uden at
  overskrive noget. Kandidater vurderes altid enkeltvis, se `REFRESH_LOG.md`.
- `apply_refresh.py` — det anvendte (og begrundede) ændringssæt fra sidste kørsel.
- `rebuild.py` — genopbygger `kort_soeg.html` + `kaede_adresser.xlsx` + `retailkort_data.json` ud fra de tre CSV'er (kør efter refresh/rettelser)
- `retailkort_data.json` — data-feed som kortet henter live (med indbygget fallback); se `AUTO_UPDATE.md`
- `AUTO_UPDATE.md` + `.github/workflows/weekly-refresh.yml` — ugentlig automatisk opdatering via GitHub Actions

## ⚡ Superladere (≥250 kW) — 784 personbil + 14 lastbil
Kilde: operatørernes officielle ladekort/API'er (Clever, Norlys, Circle K, E.ON, OK, Shell Recharge, Ionity m.fl.); Tesla autoritativt fra supercharge.info; adresser via DAWA.
Norlys 166, Clever 159, Circle K 129, OK 76, E.ON 65, Tesla 34, Uno-X 34, EWII
28, Shell Recharge 27, Allego 14, Ionity 14, Eviny 10, Spirii 9, Stella 8,
Fastned 7, AmpGo 1, Better Energy 1, EDF 1, PowerGo 1.
(personbil-laget)

**Lastbil-ladere — 14.** Norlys 4, E.ON 3, Circle K 2, OK 2, Uno-X 2, Q8 1.
De har eget lag og egen til/fra-knap på kortet, fordi de ikke er brugbare som
bil-ladere: to af Norlys' anlæg på Gl. Århusvej og Circle K's anlæg ved Skanderborg
har `motorcar=no` i OpenStreetMap, altså kan biler slet ikke lade der. Udpeget ved at
matche alle 798 rækker mod samtlige 3.144 danske ladestationer i OSM på
`hgv`/`bus`/`socket:mcs`-tags — ikke ved navn: kun 4 af de 14 har "Truck" i navnet.
Regel: effekt 250–500 kW (verificeret: alle 798 rækker ligger i intervallet), ELLER
Tesla Supercharger. `Antal_ladere` er antallet af udtag (EVSE'er) på ≥250 kW — langsomme
AC- og CHAdeMO-stik på samme anlæg tælles IKKE med. Kortet kalder dem **ladepunkter**
(EU's AFIR-term for én ladeplads til ét køretøj), ikke "ladestandere" — Veri Centret er
fx 10 ladepunkter fordelt på 5 fysiske standere. Afstemt mod operatørens egen kilde
for 388 af 798 rækker (OK, Clever, E.ON, Uno-X, Tesla, Ionity) uden afvigelse; de øvrige
mærker er ikke afstemt. (Ionity er ikke altid 350 kW:
Aarup, Ringsted, Struer, Nørresundby og Korsør er 400 kW; effekten regnes ud af
stik-trinnene i Ionitys mapdata.) Tesla er hentet fra supercharge.info (kun OPEN ≥250 kW — udelukker 150 kW V2 og destination-ladere). Adresser via DAWA.

## 🍔 Fastfood-kæder — 319
McDonald's 121, Burger King 61, Sunset Boulevard 47, Jagger 18, Carl's Jr. 15, Subway 15,
Halifax 11, Gasoline Grill 10, Cocks & Cows 7, Domino's Pizza 6, Max Burgers 6, Five Guys 1, KFC 1.
Kilde: kædernes officielle locators/API'er; koordinater via DAWA.

## ⛽ Tankstationer — 2.142 (alle mærker)
OK 690, Uno-X 279, Shell 211, Circle K 206, Ingo 196, Go'on 194, F24 143, Q8 106, OIL! 71,
CNG/biogas 20, Oles Olie 8, Lavpris 6, Øboens 4, HK Benzin 3, Uafhængig 3, KP Benzin 1, Kai Dige Bach 1.
Kilde: OK fra officielt API; øvrige fra officielle findere/OpenStreetMap, adresser via DAWA. Marina- og
flyvepladsanlæg er holdt ude. Officiel brancheopgørelse (Drivkraft Danmark): ~2.145 — vi rammer plet.

⚠ Truckanlæg er **ikke** konsekvent holdt ude: 9 Shell CRT-anlæg (Commercial Road
Transport) ligger fortsat i tank-datasættet, mens 21 YX-lastbilanlæg er udelukket.
Se "Åbne beslutninger" i `REFRESH_LOG.md` — reglen er endnu ikke afgjort.
Circle K's egne stamdata klassificerer 8 danske anlæg som `siteType=EV` uden brændstof;
de hører i superlader-laget og er holdt ude her.

## Kortet (kort_soeg.html)
- Fire lag med hver sin til/fra-knap: Tankstationer ⛽, Fastfood 🍔, Superladere ⚡ og
  Lastbil-ladere 🚛
- Farve = mærke/operatør (signaturforklaring i højre side; klik for at skjule)
- Klik på et punkt → navn, adresse, mærke (+ effekt/stik/ladepunkter for ladere)
- Kategori til/fra, DAWA-adressesøgning (flyver til adressen + viser nærmeste stationer), zoom (scroll) og panorering (træk)

## Ingen samlekategorier
Alle punkter er tilknyttet et navngivet mærke — ingen "Andre" eller "(ukendt)". De umærkede superladere blev identificeret (via navn/nærmeste hub-nabo), OSM-stavefejl er flettet (Cirkel K/Statoil→Circle K, Ckever→Clever, EVII→EWII, Fasned→Fastned), og truck/flyveplads-poster fjernet fra tank. "Uafhængig" bruges kun om stationer der reelt ikke tilhører en kæde.

## HK Benzin → Shell Express
HK Benzin er nu nede på 3 anlæg — resten er konverteret til Shell Express (DCC Energi-handlen, godkendt Q2 2026). Følg konverteringen ved næste refresh, se `REFRESH.md`.

## Kvalitet
`validate.py` v4 tjekker: postnr, geometri, dubletter, manglende felter, effekt-interval,
**at adressen faktisk findes i DAWA**, og **afstanden fra koordinat til rækkens egen
adresse**. `reconcile.py` tjekker desuden kategori-renhed mod operatørens brændstofliste.
Se `REFRESH.md` for hvorfor de to sidste ikke kunne bygges som hårde fejl.

Sidste kørsel (10. september 2026): **0 hårde fejl**, **55 tjek-punkter** (var 141 —
91 rækker blev rettet 10. september, se `REFRESH_LOG.md`). De resterende er gennemgået
og verificeret: operatørens officielle adresse som DAWA ikke kan bekræfte, typisk store
grunde hvor adressepunktet ligger langt fra anlægget. Plus 1 benign advisory (Clever "Horsens N pendlerparkering" — koordinaten ligger ved selve pendlerparkeringen ~350 m fra det registrerede adressepunkt; reelt korrekt). Kør `python3 validate.py` efter hvert refresh.

## Sådan holdes kortet korrekt over tid
Kortets punkter er et frosset øjebliksbillede — de bliver ikke automatisk forkerte, men de bliver forældede. Fast rutine:
1. `python3 refresh_data.py` — friske OK + Tesla (+ workflow-scraperne i `REFRESH.md` for øvrige mærker)
2. `python3 validate.py` — skal give 0 hårde fejl
3. `python3 rebuild.py` — genopbyg kort + Excel (opdaterer også datostemplet)

**Automatisk (anbefalet):** de to trin ovenfor (frisk OK+Tesla → genopbyg feed) kan køre ugentligt uden hånd via GitHub Actions — kortet henter så det friske feed selv, og siden på kartago.dk røres aldrig. Se `AUTO_UPDATE.md`.

Bemærk: kortet er selvstændigt (Leaflet indlejret), så visningen overlever selv hvis CDN'er forsvinder; kun OSM-fliser + DAWA-søgning er live-afhængigheder. Ved import: pas på Clever/Eviny roaming-dubletter (samme Eviny-site kan optræde som en Clever-skygge) — se den fjernede "Veri Centret".
