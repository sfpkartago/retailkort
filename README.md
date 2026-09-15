# Danmark: Superladere, Fastfood-kæder og Tankstationer

Opdateret 10. september 2026. Alle rækker har adresse + koordinater (Latitude/Longitude).
CSV'er er UTF-8 med BOM (æ/ø/å vises korrekt i Excel).

## Filer
- `kort_soeg.html` — INTERAKTIVT KORT MED ADRESSESØGNING: DAWA-adressesøgning der flyver til enhver adresse og viser nærmeste stationer. Kategori-knapper, farve pr. mærke, klik-info, zoom/panorering. **Selvstændig:** kort-motoren (Leaflet + markercluster) er indlejret i filen, så den virker uden CDN — kun baggrundsfliserne (OpenStreetMap) og adressesøgningen (DAWA) kræver internet. Viser et synligt datostempel ("Data pr. …") så man altid kan se hvor friskt det er.
- `kaede_adresser.xlsx` — Excel med 3 faner (Superladere, Fastfood, Tankstationer). Latitude/Longitude/effekt/antal er ægte tal-celler (kan sorteres/filtreres numerisk).
- `superladere_dk.csv` — 798 ladeanlæg ≥250 kW: **784 til personbil + 14 lastbil-ladere**
  (kolonnen `Lastbil` = `ja` markerer sidstnævnte; de vises som eget lag på kortet)
- `fastfood_kaeder_dk.csv` — 475 spisesteder: fastfood, café og juicebar
- `tankstationer_dk.csv` — 2193 tankanlæg: **2133 almindelige + 60 lastbilanlæg**
  (kolonnen `Lastbil` = `ja`; de vises som eget lag på kortet)
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

## 🍔 Spisesteder — 475
McDonald's 121, Joe & The Juice 76, Espresso House 63, Burger King 61, Sunset
Boulevard 47, Jagger 18, Starbucks 17, Carl's Jr. 15, Subway 15, Halifax 11,
Gasoline Grill 10, Cocks & Cows 7, Domino's Pizza 6, Max Burgers 6, Five Guys
1, KFC 1.
Kilde: kædernes officielle locators/API'er; caféerne (Joe & The Juice, Espresso House,
Starbucks) fra OpenStreetMap, da deres butiksfindere er SPA'er uden tilgængeligt API.
Koordinater og adresser via DAWA.

Laget dækker **restauration** bredt — fastfood, café og juicebar. Det er bevidst ikke
en af planlovens tre detailhandelskategorier: restauration er ikke detailhandel.

## 🛒 Dagligvarer — 3985 (planlovens kategori 1)
Netto 582, Apotek 540, REMA 1000 437, Coop 365discount 320, Brugsen 265,
Matas 264, SuperBrugsen 218, 7-Eleven 172, Lidl 171, Min Købmand 167,
Normal 165, SPAR 138, Lagkagehuset 118, MENY 116, føtex 101, Let-Køb 69,
Kvickly 62, Apoteksudsalg 19, Løvbjerg 18, Bilka 17, føtex food 17,
Billigblomst 8
(+ 1 mærker mere)

Afgrænsningen følger Erhvervsstyrelsens vejledning (VEJ nr 9290 af 18/06/2010):
*"Dagligvarer er f.eks. madvarer, drikkevarer, artikler til personlig pleje og diverse
husholdningsartikler"*. Derfor ligger **apoteker, Matas og Normal** her og ikke i
udvalgsvarer — de er alle i branchen personlig pleje (DST 477300 og 477500), og både
ICP og COWI's kommunale detailhandelsanalyser grupperer dem under dagligvarer.
Bagerier (Lagkagehuset) og kiosker (7-Eleven) hører ligeledes her.

`Apoteksudsalg` er skilt ud som eget mærke: Apotekerforeningens egen tæller siger
**540 apoteksenheder** (222 apoteker + 318 filialapoteker), og de resterende 19 er
apoteksudsalg — en anden enhedstype med begrænset lager.

- `dagligvarer_dk.csv`

## 🛍️ Udvalgsvarer — 2103 (planlovens kategori 2)
Imerco 165, JYSK 117, Profil Optik 113, Bog & idé 108, Tøjeksperten 105,
Flügger 102, Synoptik 99, Fri BikeShop 97, Maxi Zoo 85, Skoringen 83,
Thiele 82, Louis Nielsen 79, thansen 69, Nyt Syn 59, Sport 24 Outlet 57,
Sport 24 55, Kop & Kande 52, Søstrene Grene 52, H&M 50, Elgiganten 48,
ILVA 40, Land & Fritid 36
(+ 26 mærker mere)

**Møbelkæderne ligger her, ikke i pladskrævende.** § 5 n, stk. 1, nr. 3 gælder butikker
*"der alene forhandler"* særlig pladskrævende varer, og vejledningen fastslår at
bestemmelsen *"ikke omfatter store butikker med mange varer og heller ikke butikker,
der både forhandler pladskrævende varer og ikke-pladskrævende varer"*. Lovbemærkningerne
siger direkte at møbler, tæpper og boligudstyr **ikke** er særlig pladskrævende.
JYSK (dyner, gardiner, tæpper, opbevaring) og IKEA (køkkenudstyr, tekstil, legetøj,
belysning, fødevarer) fejler "alene"-betingelsen entydigt. Møbelbetingelsen for de
butikker der *kun* sælger møbler ligger i **§ 11 e, stk. 7** — ikke i § 5 n, stk. 3,
som handler om aflastningsområder. Både ICP og COWI kategoriserer møbelbutikker som
udvalgsvarer.

`IKEA bestillingssted` er skilt ud: 6 af de 12 IKEA-lokationer er "Plan and order
points" — små planlægningsstudier uden varelager i bymidter og centre.
`H&M HOME` er ligeledes eget mærke; det er et selvstændigt butiksformat for bolig.

Elgiganten, H&M, Zara og Flying Tiger ligger bag bot-beskyttelse og kommer fra
OpenStreetMap. **Louis Nielsen er nu komplet:** alle 79 butikker fra kædens egen
locator, adresserne verificeret mod hver butiks eget koordinat (0 uverificerede).
Tidligere stod laget med 44 fra OSM.

- `udvalgsvarer_dk.csv`

## 🏗️ Særlig pladskrævende varegrupper — 1751 (planlovens § 5 n, stk. 1, nr. 3)
jem & fix 139, STARK 80, XL-BYG 73, Harald Nyborg 71, Bygma 64, Toyota 58,
Davidsen 47, Silvan 47, Kvik 35, Volkswagen 35, HTH 31, Svane Køkkenet 28,
Nettoline 27, Vordingborg Køkkenet 25, Designa 24, Ford 24
(+ 556 mærker mere)

Gældende ordlyd (LBK nr 572 af 29/05/2024): *"butikker, der alene forhandler særlig
pladskrævende varer eller varer, som frembyder særlige sikkerhedsmæssige forhold,
f.eks. motorkøretøjer, lystbåde, campingvogne, trailere, planter, havebrugsvarer,
tømmer, byggematerialer, grus, sten- og betonvarer og møbler samt ammunition og
eksplosiver"*. Bemærk **"f.eks."** — listen er ikke udtømmende, og "motorkøretøjer"
dækker bredere end personbiler.

### Hvordan grænsen mellem lagene er trukket

Planloven siger kun *"butikker, der **alene** forhandler"* og giver en liste med
*"f.eks."* foran — den leverer ingen brancheafgrænsning. Den operationelle standard er
**ICP's branchefortegnelse**, som bruges i kommunale detailhandelsanalyser. Dens liste
over særlig pladskrævende er:

| Kode | Branche |
|---|---|
| 451120 | Detailhandel med personbiler, varebiler og minibusser |
| 451910 | Engros- og detailhandel med campingkøretøjer, små trailere mv. |
| 451920 | Engros- og detailhandel med lastbiler og påhængsvogne mv. |
| 454000 | Salg, vedligeholdelse og reparation af motorcykler |
| 475220 | **Byggemarkeder og værktøjsmagasiner** |
| 476430 | **Forhandlere af lystbåde og udstyr hertil** |
| 477620 | **Planteforhandlere og havecentre** |
| 477890 | **Detailhandel med køkken- og badeværelseselementer** |

ICP skriver selv, at *"køkkenbutikker, planteforhandlere, byggemarkeder samt forhandlere
af campingvogne, både og motorcykler tæller … med under forhandlere af særlig
pladskrævende varegrupper"*. Det afgør fire spørgsmål, der ellers ville være skøn:

* **Byggemarkederne bliver** (jem & fix, Silvan, BAUHAUS, STARK, XL-BYG, Bygma, Davidsen,
  Johannes Fog) — 475220 dækker dem, uanset at de også fører småvarer.
* **Harald Nyborg flyttede TIL pladskrævende.** Harald Nyborg A/S (CVR 37783315) er
  registreret i netop branche 475220.
* **Bådudstyrsbutikkerne flyttede TIL pladskrævende.** 476430 hedder ordret "lystbåde
  **og udstyr hertil**". De lå før splittet mellem to lag — 11 i udvalgsvarer og 4 i
  pladskrævende — hvilket ikke kunne forsvares.
* **Biltema og Land & Fritid flyttede TIL udvalgsvarer.** Biltema er registreret under
  reservedele og tilbehør til motorkøretøjer (ICP 453200, samme som thansen), og
  Land & Fritids sortiment er foder, hest, kæledyr og jagtudstyr — dyrehandel (477630),
  ikke byggemarked eller planteforhandler.

Den historiske note: § 5 n havde frem til 2017 en udtømmende varegruppeliste og et
stk. 2, der gav tømmer- og byggematerialebutikker et afsnit på op til 2.000 m² med
ikke-pladskrævende varer. **Begge dele er væk i den gældende lov** — tilbage står
"alene forhandler" med en vejledende liste. VEJ nr 9290 af 18/06/2010 er stadig
gældende og er fortsat bedste fortolkningsbidrag til "alene", herunder bagatelreglen:
*"Havecentre/planteskoler kan således foruden planter sælge andre havebrugsvarer, så som
krukker, plantejord og mindre haveredskaber."*

**Bilforhandlerne har nu deres egne navne.** Laget havde 377 rækker med mærket
"Bilforhandler" uden forhandlernavn. De er erstattet med Bilbasens forhandleroversigt
(sitemap over autoriserede forhandlere pr. mærke), så mærket er forretningens eget navn
— laget har nu 563 forskellige mærker mod 55 før.
Uafhængige forhandlere står med deres eget navn som mærke; popuppen nævner derfor kun mærket, når butiksnavnet er et andet.

`Bilforhandler` og `Havecenter` er bevaret som generiske mærker for 25 forretninger,
hvor INGEN kilde har et navn — hverken Bilbasen, kædelisterne eller OSM (efterprøvet med
en punktforespørgsel pr. koordinat: 1 af 38 havde fået et navn i OSM siden sidst).
Stedet er virkeligt og hører i kategorien, så alternativet ville være at skjule
rigtige forretninger, fordi ingen kilde kender deres navn.

- `pladskraevende_dk.csv`

## Kildesporing for retail-lagene

`retail_sources.py` har hentere for **27 kæder** — de kan køres igen og give samme data.
`sources.py` har hentere for tank/lade-kilderne. Bilforhandlerne kommer fra Bilbasens
forhandler-sitemap, Louis Nielsen fra kædens egen slug-baserede locator.

Derudover står laget med **35 mærker (1.175 rækker) fra engangshentninger, hvor
hentekoden ikke blev gemt.** Rækkerne er derfor efterprøvet mod OpenStreetMap: én
forespørgsel pr. mærkeparti på `brand`- og `name`-tagget, og hvert træf målt mod
rækkens eget koordinat (11. september 2026):

* **Fuldt bekræftet af OSM** (alle rækker inden for 150 m af et OSM-punkt med samme
  navn) — de kom fra OSM og kan hentes igen med `sources.osm_brand()`:
  Biltema, Deichmann, Ecco, Jack & Jones, NAME IT, ONLY, ONLY & SONS, PIECES,
SELECTED.

* **Delvist bekræftet** — flere rækker end OSM kender, hvilket peger på kædens egen
  liste som kilde (OSM-træf/rækker):
  Fri BikeShop 85/97, Maxi Zoo 67/85, Nyt Syn 15/59, Profil Optik 61/113,
Skechers 15/34, Skoringen 35/83, Søstrene Grene 32/52.

* **Næsten ikke i OSM** — køkken-, bad- og malerkæder er showroom-forretninger, som
  OSM kun kender sporadisk. Rækketallene svarer til kædernes egen butiksstørrelse
  (Flügger har omkring 100 butikker; OSM kender 11), så kilden må være kædens egen
  liste. Kan ikke efterprøves mod OSM:
  AUBO Køkken & Bad 3/22, DLG Landbutik 0/1, Designa 2/24, Flügger 9/102, HTH
9/31, Invita 6/19, JKE Design 1/17, Kvik 13/35, Land & Fritid 3/36, Multiform
0/6, Nettoline 4/27, Sports World 2/13, Svane Køkkenet 6/28, Tvis Køkken 2/20.

* **Bekræftet ved gentagen kørsel:** VILA **4 af 4** og Vero Moda **23 af 25**, alle
  på 0 m. Første forsøg gav intet svar fra nogen af de fire Overpass-spejle — en
  kørselsfejl, ikke et udsagn om rækkerne. De 2 ubekræftede Vero Moda-rækker
  (Glostrup Shoppingcenter, Aabenraa Ramsherred 33A) er bevaret.

Efterprøvet enkeltvis med punktforespørgsler bagefter: **Vordingborg Køkkenet 15 af 25**
(delvist bekræftet, som de øvrige kæder med egen liste) og **uno form 0 af 9** — samme
mønster som de andre køkken-showrooms, OSM kender dem ikke.

**`thansen` er afklaret: kilden er OpenStreetMap.** En punktforespørgsel pr. koordinat
bekræftede **65 af 69 rækker**, de fleste med 0 m afvigelse. OSM er netop den eneste
kilde kæden må hentes fra, da thansen.dk udtrykkeligt forbyder ClaudeBot i robots.txt.
De 4 ubekræftede — Ringsted, Skjern, Bjerringbro og Randers NV — er bevaret: et
manglende OSM-punkt er ikke bevis for at butikken ikke findes. Samme lære gjaldt Clevers
"Veri Centret", som blev slettet på for løst grundlag og måtte tilbage.

⚠ **Fælde i efterprøvningen, værd at huske:** mærke-forespørgslen gav 0 for thansen,
fordi OSM tagger kæden `brand=thansen.dk`, mens mit verifikations-regex var ANKRET
(`^thansen$`). Det tomme svar lignede "findes ikke", men skyldtes regexet.
`sources.osm_brand()` ankrer ikke sit regex og rammer derfor rigtigt — fejlen var kun
i verifikationsscriptet.

## ⛽ Tankstationer — 2133 almindelige + 60 lastbilanlæg
OK 690, Uno-X 279, Circle K 206, Shell 202, Ingo 196, Go'on 194, F24 143, Q8
106, OIL! 71, CNG/biogas 20, Oles Olie 8, Lavpris 6, Øboens 4, HK Benzin 3,
Uafhængig 3, KP Benzin 1, Kai Dige Bach 1.
Kilde: OK fra officielt API; øvrige fra officielle findere/OpenStreetMap, adresser via DAWA. Marina- og
flyvepladsanlæg er holdt ude; lastbilanlæg er med, men i eget lag. Officiel brancheopgørelse (Drivkraft Danmark): ~2.145 — vi rammer plet.

**Lastbilanlæg — 60.** Circle K 25, YX 21, Shell 9, Go'on 5.
Diesel + AdBlue uden benzin, altså ikke brugbare for en bilist. De har eget lag og egen
til/fra-knap 🚚, så sammenligningen med Drivkraft Danmarks opgørelse af offentlige
tankstationer stadig går på samme population (2133 mod deres ~2.145).
Circle K's egne stamdata klassificerer 8 danske anlæg som `siteType=EV` uden brændstof;
de hører i superlader-laget og er holdt ude her.

## Kortet (kort_soeg.html)
- **Otte lag** med hver sin til/fra-knap: Tankstationer ⛽, Lastbil-tank 🚚,
  Spisesteder 🍔, Dagligvarer 🛒, Udvalgsvarer 🛍️, Pladskrævende 🏗️, Superladere ⚡
  og Lastbil-ladere 🚛
- De tre retail-lag starter **slukket**: alle otte tændt giver næsten 10.000 nåle og et
  ulæseligt kort. Kortet åbner derfor med 3.466 punkter og resten tændes efter behov.
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
