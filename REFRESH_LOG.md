# Refresh-log

## 10. september 2026 — gennemgang af validate.py v4's 141 tjek-punkter

Alle 141 punkter blev gennemgået enkeltvis af 15 undersøgere, og hver portion blev
efterprøvet af en uafhængig skeptiker (30 agenter). Skeptikerne afviste **10 af de 141
forslag** og leverede selv det rigtige svar i 7 af dem.

**Resultat: 141 → 55 tjek-punkter. 0 hårde fejl. 91 rækker rettet** (tank 61,
fastfood 16, superladere 14). Ingen rækker tilføjet eller fjernet.

| Mønster | Antal | Eksempel |
|---|---|---|
| Manglende bogstav | 29 | `Danmarksgade 3` → **3B** (kun 3A/3B findes i 9900) |
| Anden vej | 21 | Burger King Vanløse: `Jernbane Allé 44` → **Frode Jakobsens Plads 2** (nr. 44 findes ikke; CVR-P-enhed 1023054422 bekræfter) |
| Havde intet husnummer | 21 | Halifax Lyngby: `Handelstorvet` → **Nørgaardsvej 1B** |
| Andet husnummer | 15 | Norlys: `Skovvangen 39` → **41** |
| Koordinat flyttet | 7 | CNG Frederikshavn laa **1,7 km** for langt mod syd |

De syv koordinat-rettelser var alle geokoder-artefakter, hvor adressen var rigtig:
CNG Frederikshavn 1.700 m, OIL! Gørløse 382 m, Go'on Vordingborg 287 m, OIL! Kolding
140 m, plus Stella Østbanegade, McDonald's Maribo og Cocks & Cows CPH.

`EXPRESS EBELTOFT` (den på 1.105 m) var ikke en koordinatfejl: vejen heder officielt
`Ndr. Strandvej` i 8400 og har ikke noget nr. 12, saa datavask faldt tilbage paa
"Søndre Strandvej 12" 1,1 km væk — ren edit-distance-støj. Rettet til `Ndr. Strandvej 14`.

### To forslag blev afvist af forkontrollen
Hver ny adresse blev tjekket mod DAWA før skrivning. To slap gennem BEGGE agenter men
faldt der: E.ON "Hirtshals Havn UFC" → `Auktionskajen 7` (vejen findes **slet ikke** i
9850 — gættet ud af den ødelagte kildestreng "AGBtionskajen") og Oles Olie Håstrup →
`Bygaden 50` (findes ikke i 5600; "Håstrup" er supplerende bynavn, ikke postnrnavn).
Forkontrollen er dermed ikke overflødig.

### De 44 der blev efterladt — gennemgået, ikke uundersøgt
De optræder fortsat i `validation_report.txt`, men de ER verificeret: adressen er
operatørens officielle, og DAWA kan blot ikke bekræfte den. Typisk store grunde
(centre, motorvejsanlæg, lufthavne) hvor DAWA's adressepunkt ligger 250-450 m fra
selve anlægget, eller huller i DAR's nummerrække. Kør ikke gennemgangen igen uden
grund — se `git log` for denne commit.

### 4 kræver en beslutning
1. **E.ON "Chrst. Boecksvej P-Plads"** (superladere) — husnr `634` findes ikke (vejen
   har 1-30), og operatørens egen datapost har også forkert postnummer (3840), så
   strengen er beskadiget hos E.ON. Koordinaten er rigtig men ligger på vejlitra-matriklen,
   så ingen adresse ligger "på" den.
2. **Norlys "Dieselvej 8"** (superladere) — adressen findes ikke (Dieselvej i 4600 har
   kun 4, 5, 6). Norlys' bil-lynladepark i Køge er en ANDEN række (Servicevej 2, 185 m
   væk), og dette ser ud til at være deres lastbil-/bus-ladepark. Hører formentlig under
   den uafgjorte lastbil-regel.
3. **Norlys "Flextrafik - Køge Sygehus"** (superladere) — `Lykkebækvej 1` er hospitalets
   hovedadresse, og DAWA's punkt sidder ved hovedindgangen 256 m væk. Intern afstand på
   en meget stor hospitalsgrund. Ret eller efterlad?
4. **`SHELL CRT KVISTGÅRD`** (tank) — `Oldenvej 10` er Shells officielle adresse, men DAR
   har delt grunden i 10A-10D. Shells egen koordinat falder på 10D's jordstykke, mens
   OSM's Shell-truck-node ligger 196 m nordvest i truck-klyngen. Kan ikke afgøres uden
   at vide hvilket anlæg der er hvilket — og rækken er i øvrigt et CRT-lastbilanlæg,
   altså også omfattet af den uafgjorte lastbil-regel.

---
## 8. september 2026 — første refresh siden 21. juli

Data var 7 uger gammelt. Ni kilder blev probet; seks svarede, tre var flyttet
(to genfundet). Slutresultat, verificeret mod filerne:

| Lag | 21. juli | 8. september |
|---|---|---|
| Tankstationer | 2.149 | **2.142** |
| Superladere | 788 | **795** |
| Fastfood | 319 | 319 |

`validate.py`: **0 hårde fejl**, 1 kendt benign advisory (Clever "Horsens N
pendlerparkering"). Alle 795 lader-rækker ligger i 250–500 kW og har `Antal_ladere`.

### Kilder der blev friskt hentet
| Kilde | Endpoint | Resultat |
|---|---|---|
| OK (tank) | `mobility-prices.ok.dk/api/v1/fuel-prices` | 690, uændret antal |
| Tesla | `supercharge.info/.../allSites` | 35 → 34 |
| Clever | `clever.dk/api/v2/chargers/locations` | 157 → 159 |
| Ionity | `wf-assets.com/ionity/mapdata.json` | 14, effekt/antal rettet på 6 |
| Go'on + Lavpris | `goon.nu/…msb_map_pins` | 194 + 6, én tilgang og én dublet hver |
| OK (ladere) | **nyt:** `POST geo-emobility…/api/v2/locations/nearby` | 72 → 78 |
| Shell | **ny sti:** `find.shell.com/dk/fuel/locations/da_DK` | 211 → 211 (+1 tilgang, −1 EV-anlæg) |

### Døde endpoints
- **Burger King** — `bk-dk-ordering-api…azurefd.net/api/v2/restaurants` → 404. Sitet er
  en Angular-app uden API-spor i HTML'en. **Ikke genfundet.**
- **OK-ladere** — `GET /api/v2/clusters` → 404. Genfundet via deres Swagger.
- **Shell** — `find.shell.com/dk` → 404. Genfundet: locale-stien.

### Stadig på juli-data
Uno-X, F24, Q8, OIL!, CNG/biogas, Circle K + Ingo (tank), Oles Olie, Øboens,
HK Benzin, Uafhængig, KP Benzin, Kai Dige Bach · Norlys, Circle K, E.ON, EWII,
Allego, Spirii, Fastned, Eviny, Stella, Uno-X (ladere) · **hele fastfood-laget**.

---

## Rettet årsag: refresh forringede adresser

`refresh_data.py` skrev kildernes rå adressefelt direkte i CSV'en, hvilket flyttede
stationer til forkerte postnumre ved hver kørsel:

| Anlæg | kildens adresse | korrekt (DAWA) |
|---|---|---|
| Tesla Aalborg | Hobrovej 452, **9300** Aalborg | 9200 Aalborg SV (9300 = Sæby) |
| Tesla Rødovre | Rødovre Centrum 254, **2800** | 2610 Rødovre (2800 = Kgs. Lyngby) |
| Tesla Viby J | Hasselager Centervej 30, 8260 **Aarhus** | 8260 Viby J |
| OK Esbjerg | Strandby Kirkevej 185, **6700** | 6705 Esbjerg Ø |

Nyt modul `dawa.py`. Se næste afsnit — den første version af det modul havde selv
en alvorlig fejl.

## Adversariel revision af dette refresh (samme dag)

Efter refresh'et blev arbejdet revideret af 7 uafhængige reviewers, hver med sin
dimension, og hvert fund sendt til en skeptiker der skulle forsøge at modbevise det.
**57 fund rejst, 17 modbevist, 40 bekræftet.** De væsentligste, og hvad der blev gjort:

### 1. `dawa.py` v1 gjorde et miss til et hit
`lookup()` havde et fallback der returnerede *(DAWA's vejnavn, KILDENS husnr)* når
husnummeret ikke fandtes. Så så et miss ud som et verificeret hit, og `normalize_one`
beholdt kildens tekst uden at konsultere reverse. **74 af 724 normaliserede rækker
fik en adresse DAWA ikke har**, og tre blev direkte forkerte:

- Tesla Ikast: `Uhregårds Alle 6` — **1.813 m** fra rækkens egen koordinat
- Tesla Odense: `Ørbækvej 75, 5230 Odense M` — findes ikke (Ørbækvej 75 er 5220)
- Tesla Kliplev: husnr `12` — det **fjerneste** punkt på vejen (47 m var nærmest)

`validate.py` fangede intet af det: den tjekker aldrig at husnummeret findes, og dens
vej-tjek måler afstand til reverse-punktet, ikke til den påståede adresse.

**Rettet (dawa.py v2.1):** ingen fallback. En kandidat verificeres altid mod rækkens
koordinat, og kildens husnummer beholdes kun hvis det findes og ligger ved anlægget.
Grænsen er `max(reverse-afstand + 150 m, 300 m)` — sat på anlægs-udstrækning, så et
stort center- eller motorvejsanlæg accepteres (Hobrovej 452 er 289 m fra Tesla-laderen
ved Aalborg Storcenter og passerer grænsen), mens Odense (444 m) og Ikast (1.813 m)
afvises. Rækken ender på **`Hobrovej 452C`** — ikke 452 — fordi 452C er det nærmeste
husnummer på vejen (35 m).

Efter rettelsen: **0 af 724 rækker har en adresse DAWA ikke har.** Tesla Odense blev
`Carl Blochs Vej 151, 5230 Odense M` — verificeret: Tesla har flyttet anlægget 444 m,
og OSM har superladeren 12 m fra den nye koordinat.

### 2. To beslutninger var forkerte og er omgjort

**Clever "Veri Centret" blev fejlagtigt afvist.** Begrundelsen var at den lå 37 m fra
Eviny's "VERI Center" på samme adresse. Men OSM har **to separate anlæg** på grunden:
en Clever-node (`brand=Clever`, capacity 10, 300 kW) og en Eviny-way (capacity 8,
360 kW) ~40 m derfra. Clever-anlægget har egne 5 alpitronic-standere
(`chargePointIds` 15464–15468) og `roamingAgreement=null`. **Nu tilføjet.**

**"CIRCLE K RECHARGE CITY" blev fejlagtigt slettet** fra tank som "ladehub". Circle K's
stamdata fører den som `siteType=ST` med miles 95, miles Diesel, miles+ 95,
miles+ Diesel, HVO100 og AdBlue, og stationssiden
(`circlek.dk/station/circle-k-recharge-city`) viser live literpriser — 17,79 / 18,49 /
18,69 / 19,39 DKK. (Priserne ligger på stationssiden, ikke i `station-search`-JSON'en.)
OSM bekræfter uafhængigt: node 11 m fra koordinaten med `amenity=fuel`,
`brand=Circle K`, `fuel:octane_95=yes`, `fuel:diesel=yes`. Det *er* en tankstation med
ladehub. **Nu bevaret**, med en vagt i `apply_refresh.py` der afbryder hvis den
forsvinder igen — bundet til mærke + fuldt navn, fordi substringen "RECHARGE CITY"
også matches af Shells reelle "Shell Truck Recharge City" på samme grund, og som
`SystemExit` frem for `assert`, der fjernes af `python3 -O`.

Lærdommen: afstand og navn er ikke bevis. Brug operatørens egne stamdata
(`siteType`, brændstofliste, hardware-id'er) og OSM.

### 3. Kategorifejlene lå et andet sted
Circle K klassificerer selv præcis 8 danske anlæg som `siteType=EV`. Kriteriet er
`siteType`, ikke "tom brændstofliste": tre af de otte har `fuels=['EL Ladestander']`,
og to `ST`-anlæg (Billund Lufthavn, Truck Home Contino) har faktisk tom liste uden at
være EV-anlæg. **Seks af de otte lå i tank-datasættet** — fire som kryds-lags-dublet med
en superlader-række, dvs. samme anlæg vist som både tankstation og lader på kortet.
Plus `CIRCLE K EV HOVEDKONTOR`, som slet ikke findes blandt Circle K's 443 stationer.
Alle syv fjernet (Circle K 213 → 206). `SHELL RECHARGE AALBORG ØST`
(`fuels: ["shell_recharge"]`) ligeledes.

### 4. `Antal_ladere` talte langsomme stik med
- `OK Århus, Årslev, Logistikparken` var sat til 6 = alle spots, men to er Type2-AC. → **4**
- Fem OK-motorvejsanlæg talte et 100 kW CHAdeMO-stik med som lynlader
  (Karlslunde V/Ø 15→**14**, Skærup Øst 11→**10**, Ejer Bavnehøj V/Ø 9→**8**)
- `OK Støvring, Juelstrupparken` var omvendt sat for lavt: 4 → **6**
- Fire E.ON-anlæg havde samme fejl (fundet ved efterprøvningen, verificeret mod
  `edri.com/api/stations`): Rødovre Centrum 16 → **6** (70 EVSE'er, kun 6 på 300 kW;
  44 er 22 kW AC), Harte Syd 8 → **6**, Harte Nord 8 → **6**,
  Omtankestation Frederikshavn 11 → **10**. De øvrige 64 E.ON-rækker var korrekte.

### 5. Den ugentlige Action ville ikke have publiceret noget
`dawa.py` var **untracked**, og `refresh_data.py` importerer den på modulniveau uden
`continue-on-error` → jobbet døde før rebuild, sanity og commit. Verificeret ved at
checke præcis det Git kendte ud i en tom mappe. **Rettet:** filerne er nu i Git.

Yderligere hærdet:
- **Sanity-gaten var for svag.** Et halvt OK-svar (200 af 690) giver tank = 1.657,
  altså over minimum 1.500, og ville være blevet publiceret. Den sammenligner nu også
  mod det sidst committede feed (fald over 2 % afbryder) og afviser rækker uden postnr/by.
- **`refresh_data.py` fejler nu fail-fast** hvis en kilde giver mistænkeligt få rækker,
  og hvis DAWA ikke svarer — frem for tavst at skrive kildens forkerte postnumre.
- **`| tee` skjulte exit-koden**, så en død kilde blev committet som en tom rapport der
  lignede en ren afstemning. Nu `set -o pipefail`.
- **`git add` på en manglende fil** (exit 128) kunne dræbe hele commit-trinnet. Nu
  filtreres listen for filer der findes.

### 6. Forkerte påstande i den første afrapportering
- "Tesla Ikast flyttet" — koordinaten var **uændret**; det var adressen der blev
  flyttet 1,8 km væk. Det Tesla-anlæg der faktisk er flyttet, er Odense (444 m).
- "Efter rettelsen var diffen kun forbedringer" — tre Tesla-rækker blev forringet.
- "Tesla Hjørring lukket" — kilden siger `CLOSED_TEMP` med `dateClosed=None`, og
  Hjørring har fortsat en åben supercharger 111 m derfra (Sprogøvej 1A). Faldet
  35 → 34 skyldes alene `OPEN`-filteret, ikke en lukning.
- "26 kandidater, 12 falske" — passede ikke med tabellen. Det korrekte er
  **46 kandidater: 11 accepteret, 35 afvist** (se nedenfor).
- `REFRESH.md` påstod at `reconcile.py` afstemmer OK-ladere og Shell. Det gjorde den
  ikke — nu gør den.
- `sources.clever()`'s docstring påstod at Eviny-skygger var filtreret væk.
  `isRoamingPartner` er `False` på alle 3.565 records, så filteret er en no-op.
  Docstringen advarer nu i stedet.

### 7. Efterprøvning af rettelserne
Rettelserne blev selv efterprøvet af uafhængige verifikatorer (kørslen blev afbrudt af
en session-grænse, så 2 af 6 områder nåede igennem; resten mangler). Det bekræftede:
Veri Centret er korrekt tilføjet med korrekt adresse (`5` findes ikke i 8240 — kun i
4600 Køge og 7400 Herning); Recharge City sælger brændstof (bekræftet ad tre veje);
ingen af de syv fjernede rækker sælger brændstof; og `Antal_ladere` matcher operatørens
kilde 100 % for OK 78/78, Clever 159/159, Ionity 14/14, Tesla 34/34, Uno-X 35/35.

Den fandt fire ting mere, som er rettet ovenfor: de fire E.ON-antal, den for løse vagt
om Recharge City, og to upræcise formuleringer (EV-kriteriet og 795-konsistensen).
Ét fund blev modbevist: literpriserne findes, blot på stationssiden frem for i
`station-search`-JSON'en.

### 8. Anden efterprøvningsrunde — de fire manglende områder
Områderne der ikke nåede igennem første gang blev kørt færdige: **22 fund rejst,
6 modbevist, 16 bekræftet.** Fire var reelle fejl, fire latente, otte forkerte påstande.

**Rettet:**
- **`refresh_data.py` skrev det trunkerede CSV til disk FØR fail-fast.** Antals-tjekket
  lå i `__main__`, altså efter `write()`. Målt: et halvt OK-svar overskrev
  tankstationer_dk.csv med 1.652 rækker, hvorefter afbrydelsen kom — for sent. Tjekket
  ligger nu inde i `refresh_ok`/`refresh_tesla` før skrivningen. Verificeret: CSV'erne
  er nu byte-identiske efter en afbrydelse.
- **`on_street()` hentede kun de 200 første adresser.** DAWA sorterer stigende efter
  husnummer, så "nærmeste husnummer på vejen" blev valgt blandt de 200 **laveste**.
  På Søndergade i 9900 (387 adresser) gav det Søndergade 121 (1.295 m) i stedet for
  250A (15 m). Nu pagineret.
- **Trin 2 havde ingen afstandsgrænse.** Et husnummer der *findes* på vejen blev
  accepteret uanset afstand — også når det tilhørte et andet anlæg. `OK Vordingborg`
  stod med "Højgaardsvej 13", som er IONITY's adresse 308 m væk; anlægget ligger på
  3A. Nu gates trin 2 også, med en undtagelse for samme adressefamilie (75 vs 75A,
  97 vs 97E), så bogstav-underadresser på samme grund ikke bliver omskrevet.
- **`reverse_full` blev kaldt to gange pr. række** for at afgøre om DAWA svarede.
  Lykkedes det andet kald hvor det første fejlede, blev rækken talt som normaliseret
  (`skipped=0`) selvom den stod med kildens rå postnr — så afbryd-vagten fyrede ikke.
  Og `float(r[lat])` var ubeskyttet i det andet kald, så en ikke-numerisk koordinat
  væltede hele normaliseringen. Nu ét kald, med status retur.
- **Burger King Taastrup's koordinat lå 465 m fra rækkens egen adresse** (Helgeshøj
  Alle 32B) — inde i kontorparken ved Hveen Boulevard, hvor der ingen fast food er
  (Overpass: 0 `fast_food` inden for 250 m). Præeksisterende fejl. Koordinaten er sat
  til DAWA's punkt for adressen. `validate.py` er blind for den: dens forskydnings-tjek
  slår kun til når reverse-**vejnavnet** afviger, og her er begge "Helgeshøj Alle".

**Kendt, ikke rettet:** mindst 93 rækker i de mærker der IKKE normaliseres (tank ~66,
superladere ~19, fastfood ~8) angiver et husnummer DAWA ikke har på vejen i det
postnummer, og 13 rækker har slet intet husnummer ("Motorvejen Nord, 4000 Roskilde",
"Rosengårdscentret, 5220 Odense SØ", "Københavns Hovedbanegård, 1570 København V").
Tallet er et minimum — DAWA's datavask matcher også historiske adresser, så der kan
ligge flere. `refresh_data.py` normaliserer kun OK-tank og Tesla (724 rækker), hvor
tallet er 0. At køre normaliseringen bredt er ikke risikofrit: for anlæg på store
grunde er kildens adresse ofte den rigtige, selvom DAWA's adressepunkt ligger langt
fra koordinaten.

**Modbevist** (6): bl.a. at `normalize_rows` skulle kaste på en række uden koordinat,
at `split_street` skulle miste husnumre på 93 rækker, og at DAWA's `vejnavn`-parameter
skulle være versalfølsom.

---

## Afstemning frem for erstatning

`refresh_data.py` erstatter OK/Tesla helt — begge kilder er komplette og entydige.
For de øvrige mærker ville det overskrive hånd-QA'ede adresser med kildernes dårligere
tekst, så `reconcile.py` matcher på koordinat-nærhed og **rapporterer** kun.

Af **46 kandidater** blev **11 accepteret** og **35 afvist**:

| Afvist | Antal | Fordi |
|---|---|---|
| YX (Go'on partner) | 21 | Ren lastbil-diesel: ingen benzin, truck-piktogram, adresser som Dieselvej/Cargovej |
| Shell "nye" stationer | 6 | Shells egne postnumre var forkerte — DAWA gav datasættet ret i 5 af 6 |
| Lastbilanlæg | 3 | Shell CRT Padborg Nord, Shell Truck Recharge City, TRUCKSTOP Port of Aarhus |
| Ionity | 2 | `state: "planned"`, 0 stik (Aalborg Skalborg, Odense Åsumvej) |
| OK Aarhus N, Katrinebjergvej | 1 | Samme anlæg som "Stella Aarhus": Katrinebjergvej 58, 4 CCS-stik, 34 m |
| OK Aarslev Logistikparken E-truck | 1 | Lastbil-lader |
| OK Truck Korsør | 1 | 1000 kW lastbil-megawattlader, over 500 kW-grænsen |

Accepteret: Clever ×2 (Odsherred Musikskole, Veri Centret), OK-ladere ×6, Go'on ×1
(Stenderup-Krogager), Lavpris ×1 (Svankjær), Shell ×1 (Hedehusene Roskildevej).

Kildernes husnumre holdt ikke ved tre af tilgangene — `dawa.py` rettede dem:
Frijsenborgvej 5 → **5F** (5 findes kun i Køge og Herning), Storegade 30 → **29**
(30 findes ikke i 7200), Logistikparken 12 → **12C** (12 findes ikke i DK).

### Dubletter fundet i vores eget datasæt
`validate.py`'s dublet-grænse er 30 m, så to par slap igennem: "Go'on Billum"
(163 m, Vesterhavsvej 34 vs 40B) og "Lavpris Benzin – Merko Koldby" (70 m, Svinget 2B
vs Limfjordsgade 15). Kilderne har hver station én gang; den overtallige er fjernet.

### Manglende station fundet
`SHELL HEDEHUSENE ROSKILDEVEJ`. Shell stempler den med nabo-anlæggets koordinat
(Hovedgaden 482, 2 m derfra), men Roskildevej 335 ligger 1,2 km væk, og OSM har en
Shell-tankstation 6 m fra netop den adresse. Tilføjet med DAWA's koordinat.

### Værd at holde øje med
Clever "Bilka – Odense Øst" er gået fra 12 til 2 ladepunkter iflg. Clevers eget API,
og koordinaten er flyttet 136 m. Usædvanligt stort fald.

---

## Åbne beslutninger (ikke afgjort)

1. **9 Shell CRT-anlæg ligger i tank-datasættet** (Taastrup, Kvistgård, Køge, Kolding,
   Vojens, DTC Vejle, Aalborg Øst, Svenstrup, Hirtshals). CRT = Commercial Road
   Transport, altså lastbilanlæg. Det strider mod designreglen "ingen truck-stationer"
   og er inkonsistent med at 21 YX-lastbilanlæg holdes ude. Enten ryger de 9 ud, eller
   reglen blødes op og Padborg Nord + Truckstop Aarhus ind.
2. **Mindst 11 lastbil-ladere ligger i superladere** — ikke 4, som denne liste tidligere
   påstod. `grep -i truck` finder kun fire, fordi de øvrige ikke har "Truck" i navnet.
   Ni er verificeret mod OSM's `hgv`-tags via OSM's eget API:

   | Mærke | Navn | kW/antal | OSM |
   |---|---|---|---|
   | Norlys | Gl. Århusvej 6, Sdr. Borup | 400/8 | `way/1458242626` + `627`, `hgv=yes` **`motorcar=no`** |
   | Norlys | Industrivej 20 (Aarup) | 400/2 | `way/1511023217`, `hgv=designated` — Norlys' egen pressemeddelelse: "ladestation til ellastbiler og elbusser" |
   | Norlys | Dieselvej 8 | 400/8 | `way/1553043488`, `hgv=designated` |
   | Norlys | Transportbuen 7, Herning | 400/8 | `way/1459682583`, `hgv=designated` |
   | E.ON | Toldbodvej 8, Padborg | 400/14 | `way/1552173475`, `hgv=yes` |
   | E.ON | MAN Avedøre Holme | 400/8 | `way/1510980452`, `hgv=designated` |
   | E.ON | Hirtshals Transport Center | 400/6 | `node/13793754382`, `hgv=designated` |
   | OK | OK Truck Taulov, Europavej | 300/4 | `way/1225137976`, `hgv=yes` |
   | OK | OK Truck Sdr. Borup, Engelsholmvej | 400/2 | `node/13166760063`, navn "OK TRUCK" |

   Plus Circle K Truck Sdr Borup og Uno-X Truck Nyborg, navngivet som lastbilanlæg.
   To af dem (Norlys Gl. Århusvej) har `motorcar=no` — biler kan **ikke** lade der, men
   de vises i dag på kortet som bil-superladere. Beslutningen kan altså ikke træffes
   ved et grep; den kræver en systematisk gennemgang mod et lastbil-kriterium
   (`hgv`, `bus`, `socket:mcs`, navn/adresse).
3. ~~**`Antal_ladere`-konventionen.**~~ **AFKLARET 8. september.** Kolonnen tæller
   EVSE'er (udtag) på ≥250 kW, ikke fysiske standere — Veri Centret er 10 udtag på 5
   alpitronic-standere, Årslev 4 udtag på 2 standere. Konventionen er **verificeret mod
   operatørens egen kilde for 388 af de 795 rækker** (OK 78/78, Clever 159/159,
   E.ON 68/68 efter rettelsen, Uno-X 35/35, Tesla 34/34, Ionity 14/14) uden afvigelse.
   Tallet er altså rigtigt; det var **ordet** der var forkert. Popup'en sagde
   "N ladestandere", hvor en *stander* er den fysiske søjle. Rettet til
   "N **ladepunkter**" — EU's AFIR-term for netop én ladeplads til ét køretøj.
   Kolonnen er ikke genberegnet, og de resterende 407 rækker (Norlys 170, Circle K 130,
   EWII 28, Shell Recharge 27, Allego, Eviny, Spirii, Stella, Fastned m.fl.) er stadig
   ikke afstemt mod operatørens kilde.
4. **De to fjernede Circle K/Shell EV-anlæg** hører måske i superlader-laget, hvis de
   er ≥250 kW. Circle K har desuden 2 `siteType=EV`-anlæg (Amagerbrogade, Hundige) der
   hverken er i tank- eller superlader-CSV'en.
