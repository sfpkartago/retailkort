# Refresh-log

## 11. september 2026 — adversariel revision af retail-data: jeg læste § 5 n forkert

68 fund rejst af 8 reviewers, **55 bekræftet, 13 modbevist**. Det væsentligste er at min
juridiske læsning var forkert, og at den fejl forplantede sig til 1.020 rækker.

### § 5 n læst forkert — 1.020 rækker flyttet
**Møbelkæderne hører i UDVALGSVARER, ikke pladskrævende.** § 5 n, stk. 1, nr. 3 gælder
butikker *"der **alene** forhandler"* særlig pladskrævende varer. VEJ nr 9290/2010:
bestemmelsen *"omfatter ikke store butikker med mange varer og heller ikke butikker, der
både forhandler pladskrævende varer og ikke-pladskrævende varer"*, og lovbemærkningerne
fastslår at *møbler, tæpper og boligudstyr ikke er særlig pladskrævende*. JYSK (dyner,
gardiner, tæpper, opbevaring) og IKEA (køkkenudstyr, tekstil, legetøj, belysning,
fødevarer) fejler betingelsen entydigt. Både ICP (Norddjurs) og COWI (Hillerød)
kategoriserer møbelbutikker som udvalgsvarer.

**Min lovhenvisning var også forkert.** Jeg skrev "møbler med betingelsen i stk. 3".
§ 5 n, stk. 3 handler om at eksisterende aflastningsområder kan udvides — der står intet
om møbler. Ordet "møbler" forekommer præcis én gang i hele loven, i stk. 1 nr. 3.
Møbelbetingelsen ligger i **§ 11 e, stk. 7**. Og min varegruppeliste var ordlyden fra før
2017: den gældende siger "motorkøretøjer" (ikke kun biler), tilføjer "trailere" og
"ammunition og eksplosiver", og er indledt med **"f.eks."** — listen er ikke udtømmende.
Det har en praktisk konsekvens: køkkenforhandlere hører i laget (og mangler, se nedenfor),
mens trailer- og lastbilforhandlere lovligt kan ligge der.

**Apotek og Matas hører i DAGLIGVARER.** VEJ 9290/2010: *"Dagligvarer er f.eks. madvarer,
drikkevarer, artikler til personlig pleje og diverse husholdningsartikler"*. COWI's
branchefortegnelse lister 477300 Apoteker og 477500 kosmetik/personlig pleje under
dagligvarer; ICP skriver *"andre dagligvarebutikker som f.eks. parfumerier, Matas"*.
Det var desuden inkonsistent: Normal, samme branche 477500, lå allerede i dagligvarer.
Optikerne (477810) bliver i udvalgsvarer.

| Lag | Før | Efter |
|---|---|---|
| Dagligvarer | 3.152 | **3.974** (+822: Apotek 559, Matas 263) |
| Udvalgsvarer | 1.848 | **1.224** (−822, +198 møbler) |
| Pladskrævende | 1.488 | **1.290** (−198: JYSK, ILVA, Sengespecialisten, IKEA, BoConcept) |

### Rettede datafejl
- **Netto Svinninge** stod to gange — kildens eget feed har adressen som to store-id'er
  60 m fra hinanden, så et koordinattjek fanger den ikke.
- **Brugsen Bals Hjørnet** manglede: Coops API leverer den med `Location [0,0]`, så den
  faldt ud sammen med fem fængselsbutikker — men den er offentligt tilgængelig.
- **Ryvangs Allé, Hellerup:** DAWA har både "Ryvangs Allé" (med accent, husnumre til 83)
  og "Ryvangs Alle" (uden) i 2900, og normaliseringen byttede Brugsens og Nettos
  husnumre om, så Brugsen stod på Nettos adresse.
- **Zara Odense:** reverse-opslaget overskrev kildens korrekte Ørbækvej 75
  (Rosengårdcentret) med bagvejen Gørtlervej. 8 af de 12 øvrige centerrækker havde den
  rigtige adresse — lærestregen er at når kilden selv har en adresse, skal DAWA
  **validere** den, ikke erstatte den.
- **Synoptik Amager Centret** lå 2,5 m oven i Synoptik Holmbladsgade; kædens egen side
  siger Reberbanegade 3, ikke 8.
- **Sport 24 Svendborg** havde Centrumpladsen 10 (findes, derfor DAWA-kategori A) hvor
  butikken ligger i nr. 17 — kategori A er altså ikke nok som kvalitetsmål.
- **Møllegårdens Camping:** OSM-noden havde ingen adresse, så reverse valgte nærmeste
  adgangsadresse 25 m væk — en helt anden ejendom. CVR siger Skyumvej 4.

### Fire mærker skilt ud
- **Apoteksudsalg** (19): Apotekerforeningens egen tæller siger **540 apoteksenheder**
  (222 apoteker + 318 filialapoteker); de resterende 19 er apoteksudsalg med begrænset
  lager. "Apotek 559" var derfor forkert.
- **H&M HOME** (4): selvstændigt butiksformat, tælles separat i alle kædeopgørelser.
- **IKEA bestillingssted** (6 af 12): "Plan and order points" er små planlægningsstudier
  uden varelager i bymidter og centre.
- **Volvo Trucks** (1): Skifter Lastbil lå under mærket "Volvo", som alle andre steder i
  filen betyder personbiler.

### En fejl jeg selv indførte under rettelsen
Mit matcher `'Amager' in navn` ramte også "Synoptik **Amager**brogade", så jeg overskrev
en korrekt række med Reberbanegade 3's adresse og koordinat. Fanget i mit eget
log-output og gendannet fra backup. For løse matchere er dagens mest gentagne fejlkilde.

### validate.py: tjenestefejl forvekslet med datafejl
Kørslen meldte **2.579 tjek-punkter** — mod 93 før. Næsten alle var `INTET-SVAR` fra
datavask: 10.000 kald med 15 tråde udtømte DAWA, og de to sidst behandlede filer fik
2.499 falske "husnummer kan ikke bekræftes". Samme fejlklasse som Overpass' tomme
200-svar. Rettet: 8 tråde i stedet for 15, retry med voksende pause, og et udeblevet svar
rapporteres nu som **KØRSELSFEJL** og tælles ikke som tjek-punkt. Efter rettelsen:
**0 hårde fejl, 85 tjek-punkter**, og kun 8 af 9.954 rækker uden svar.

### Bekræftet korrekt (ikke alt var galt)
Normal → dagligvarer, Harald Nyborg → udvalgsvarer (netop fordi kæden også sælger
havebrugsvarer og derfor fejler "alene"-betingelsen), byggemarkederne → pladskrævende
(*"Et byggemarked klassificeres på trods af et evt. salg af udvalgsvarer som en butik med
særligt pladskrævende varegrupper"*), 7-Eleven og Lagkagehuset → dagligvarer,
café/juicebar → spisesteder. Coops 11 fravalgte rækker var alle korrekte (5
fængselsbutikker, 2 afdelinger, 2 API-dubletter, 1 dobbeltregistrering). REMA 437 matcher
kildens `meta.total` med 0 uparrede. Bilka 17, føtex food 17, Salling 3, Elgiganten 48 og
BoConcept 1 er alle **korrekte** — mine mistanker om underhøst var ubegrundede.
OSM-høsten af bilforhandlere er komplet: 650 af 653 matcher inden for 60 m.

### Ikke rettet — afventer beslutning
**~1.100 manglende butikker**, alle med dokumenteret kilde: Profil Optik + Nyt Syn 173,
skokæder 130 (Skoringen, Ecco, Skechers, Deichmann), køkkenforhandlere 123, Flügger 122,
Bestseller 121, Fri BikeShop 97, Maxi Zoo 86, thansen 58-68, Søstrene Grene 52, Land &
Fritid 38-40, Louis Nielsen 35, Biltema 19, H&M 15, Sports World 13, Zara 2.
Bemærk: Sportmasters 22 OSM-punkter må **ikke** lægges ind — kæden findes ikke længere.
thansen.dk og normalstores.com forbyder begge eksplicit ClaudeBot; kun OSM må bruges der.

**Bilforhandlerne:** 377 rækker uden forhandlernavn (Ukendt-bucket, bryder designreglen),
28 dubletter, 32 med opdigtet navn af formen "Bilforhandler <By>". Bilbasens
forhandleroversigt er identificeret som brugbar supplerende kilde — 326 autoriserede
mærkeforhandlere, og robots.txt tillader `/find-en-forhandler/*`.

**13 Dagrofa-rækker** ligger 430 m – 9,2 km fra kædens egen adresse (værst LETKØB
Fjelstrup, 9.222 m). De skal genskrives fra `field_address` frem for reverse-opslag.

**178 rækker har Navn = Mærke**, så popup'en viser mærket to gange. For pladskrævende
løses det med "Mærke By"; for de 117 i spisesteder kan 74 ikke løses med by alene.

---
## 10. september 2026 — alle tre retailkategorier bygget

52 kæder høstet af 11 agenter, **6.200 butikker**, alle med koordinater og de fleste fra
kædernes egne kilder. Efter DAWA-normalisering og dedublering: **6.488 rækker** i tre nye
lag. Datasættet er nu **9.954 rækker** fordelt på otte kortlag.

| Lag | Rækker | Mærker |
|---|---|---|
| Dagligvarer 🛒 | 3.152 | 18 |
| Udvalgsvarer 🛍️ | 1.848 | 18 |
| Pladskrævende 🏗️ | 1.488 | 59 |

**De tre retail-lag starter slukket.** Otte lag tændt giver 9.954 nåle og et ulæseligt
kort; siden åbner derfor med de oprindelige 3.466 punkter.

### Møbler hører i pladskrævende
Planlovens § 5n stk. 1 nr. 3 nævner **møbler eksplicit** blandt de særligt pladskrævende
varegrupper — med den særlige betingelse i stk. 3, at kommunen skal dokumentere at
butikken ikke kan placeres i bymidten. Derfor ligger JYSK, IKEA, ILVA, Sengespecialisten
og BoConcept der og ikke i udvalgsvarer. Harald Nyborg er sat i udvalgsvarer: kæden har
havebrugsvarer, men hovedsortimentet er udvalgsvarer.

### Kilder — hvad der lykkedes og hvad der ikke gjorde
**Egne kilder (bedst):** Coop leverer alle fire kæder i ét POST-kald (864). Netto ligger
server-renderet i Next.js' RSC-payload (583). REMA 1000 via deres app-API (437).
Dagrofa kører MENY, SPAR, Min Købmand og Let-Køb på samme Drupal-API (490). Danmarks
Apotekerforening har alle 559 apoteker. Lidl via Schwarz-koncernens API.

**OSM som fallback, med konsekvenser:** føtex, føtex food og Bilka — butiksfinderne
hydrerer klientsidet, så data findes ikke serverside; antallene er dog afstemt mod de
officielle butiks-slugs (føtex 101 af 103; de 2 manglende er nyere butikker der endnu ikke
er i OSM). Elgiganten, H&M, Zara og Louis Nielsen ligger bag bot-beskyttelse — de er
formentlig underrepræsenteret, tydeligst **Louis Nielsen 44 mod forventede ~95** og
**BoConcept 1** og **Zara 2**. Normal 165 fra OSM; ingen egen kilde fundet.

**Etik:** Flying Tigers `robots.txt` forbyder eksplicit ClaudeBot. Kæden blev hentet fra
deres Uberall-butiksfinder, ikke ved at skrabe sitet.

### To regler i validate.py gjort lag-afhængige
Begge blev afdækket af de nye data, og begge er rettet i reglen frem for i data:

1. **Kryds-mærke samme koordinat** var en hård fejl. Det er rigtigt for brændstof og
   ladere — to mærker kan ikke dele samme pumpe — men **normalt for detailhandel**: et
   butikscenter har mange butikker på samme adresse, og flere kæder oplyser centrets
   koordinat frem for butikkens egen. Rosengårdcentret gav Apotek + Synoptik + Matas +
   Sport 24 på samme punkt. Nu hård fejl kun for tank og superladere; tjek-punkt for
   resten (16 tilfælde).
2. **Nær-dublet** krævede før blot samme mærke under 30 m. Nu kræves også samme adresse,
   fordi lufthavne og banegårde reelt har flere udsalgssteder af samme kæde tæt sammen.

### Datapræcision værd at kende
De 16 centre-tilfælde afslører en generel begrænsning: for butikker i centre er
koordinaten ofte **centrets** og ikke butikkens egen. Det er godt nok til at finde
butikken på kortet, men ikke til at måle afstand mellem to butikker i samme center.

### Stadig ikke dækket
Bilforhandlere kommer fra OSM (`shop=car`, 377 uden kædenavn + 276 med bilmærke).
`shop=car_repair` og `car_parts` er frasorteret — værksteder er ikke detailhandel med
biler. Havecentre uden kædenavn: 98 fra OSM. Der findes ikke ét samlet register for
bilforhandlere i Danmark, så dækningen her hviler på OSM's kortlægning.

---
## 10. september 2026 — retail: spisesteder udvidet, dagligvare-lag oprettet

Brugeren bad om Lagkagehuset, Joe & The Juice "etc.", og om at retail deles op i
**planlovens tre kategorier**: dagligvarer, udvalgsvarer og særlig pladskrævende
varegrupper (§ 5n stk. 1 nr. 3).

### Hvordan de blev placeret
Planloven afgør det, og de ønskede kæder falder i to grupper:
- **Bageri og kiosk/convenience er dagligvarebutikker** — varer til løbende forbrug
  man tager med hjem. Lagkagehuset og 7-Eleven hører her.
- **Café og juicebar er restauration, ikke detailhandel** — Joe & The Juice,
  Espresso House og Starbucks hører i det eksisterende madlag.

Derfor er `Fastfood`-laget omdøbt til **`Spisesteder`** (fastfood, café, juicebar).
Feed-nøglen hedder stadig `food` af hensyn til ældre feeds; kun labelen er ændret.

### Gennemført
- **Spisesteder: 319 → 475.** 156 caféer tilføjet (Joe & The Juice 77, Espresso House
  63, Starbucks 17 — de tre kæders butiksfindere er SPA'er uden tilgængeligt API, så
  kilden er OpenStreetMap; Joe & The Juice ligger bag Storyblok med skjult token).
- **Nyt lag `Dagligvarer` (🛒, grøn): 290.** Lagkagehuset 118 fra **kædens egne data** —
  butikslisten ligger i Next.js' flight-payload (`self.__next_f.push`), ikke i
  `__NEXT_DATA__`, med navn, adresse, koordinat og åbningstider; kun `country=DK`,
  da kæden driver "Ole & Steen" i udlandet. 7-Eleven 172 fra OSM.
- Kortet har nu **seks lag**. Alle adresser er DAWA-normaliserede; ingen af kilderne
  havde postnummer, så de er reverse-geokodet fra koordinaten.
- Guldbageren og Emmerys er **udeladt**: OSM har kun 1 af hver, og en kæde vist med
  1 af ~30 butikker er mere misvisende end ingen. Kræver kædens egen kilde.
- Baresso findes ikke i OSM under det brand — kæden er formentlig ophørt/rebrandet.

### `validate.py`s dublet-regel er gjort mere præcis
Reglen var "samme mærke under 30 m = hård fejl". Den kan ikke rumme, at lufthavne og
banegårde reelt har flere udsalgssteder af samme kæde tæt sammen: Lagkagehuset har seks
i CPH med hver sin adresse i kædens egen kilde. Nu kræves **samme adresse** for en hård
fejl; samme mærke tæt på med en ANDEN adresse er et tjek-punkt. Det fangede stadig fem
ægte OSM-dubletter af 7-Eleven (samme adresse, 10–26 m — typisk et punkt der findes både
som node og som bygnings-way).

### `sources.osm_brand()` — en fælde værd at kende
To fejl blev fundet undervejs:
1. `re.escape()` escaper mellemrum og `&` i Python 3.9, så `"Joe & The Juice"` blev
   `"Joe\ \&\ The\ Juice"` og gav **0 træffere** i Overpass. Mærkenavnene sendes nu råt.
2. Overpass svarer **200 med `elements: []`** når forespørgslen timer ud internt, og et
   tomt svar er ikke til at skelne fra "kæden findes ikke". 7-Eleven gav 0 i én kørsel og
   177 i den næste. Funktionen prøver nu næste spejl ved tomt svar og returnerer først
   tomt, når alle spejle er enige.

### Kortlægning af de tre kategorier (til beslutning)
59 kæder kortlagt af fire agenter; **48 har en brugbar maskinlæsbar kilde, ca. 5.930
butikker** (efter fradrag for dobbelttælling af Brugsen/Dagli'Brugsen og Jysk/JYSK).

| Kategori | Kæder | Butikker |
|---|---|---|
| Dagligvarer | 16 | ~2.885 |
| Udvalgsvarer | 16 | ~1.767 |
| Særlig pladskrævende | 14 | ~1.278 |

**De store gennembrud:** Coop giver ALLE kæder i ét POST-kald til
`coop.dk/umbraco/api/Chains/GetAllStores` — 902 butikker med koordinater. Netto ligger
server-renderet i `netto.dk/find-butik/` (584). REMA 1000 giver alle 437 med
`?per_page=1000`. Dagrofa kører MENY, SPAR, Min Købmand og Let-Køb på **samme**
Drupal JSON:API (391 i alt) — én parser dækker fire kæder, men `page[limit]` er capped
på 50, så der SKAL pagineres. Danmarks Apotekerforening har et API med alle 559 apoteker.

**Verificerede aflysninger:** ALDI er helt ude af Danmark (alle butikker lukket, 0 i OSM).
Irma eksisterer ikke længere — Coop konverterede alle butikker i 2023, og navnet lever
kun som privat label. Nemlig.com har ingen fysiske butikker. Idemøbler er ophørt.
Optimera findes kun i Norge/Sverige.

**Blokeret af bot-beskyttelse:** Elgiganten (Vercel), H&M (Akamai — selv robots.txt
giver 403), Louis Nielsen (Cloudflare), Zara. Normal har ingen kilde fundet, men OSM har
165 — det er det største reelle hul.

**Etisk forbehold:** `flyingtiger.com/robots.txt` har eksplicit `User-agent: ClaudeBot /
Disallow: /`. Kæden bør derfor hentes fra OSM eller efter aftale, ikke ved at skrabe
deres eget site.

**Fælder ved implementering:** Brugsen og Dagli'Brugsen er SAMME kæde (Coop rebrandede,
men API'et bruger stadig det gamle navn) — tæl 271 én gang. OSM har 86 "føtex Slagter",
35 "føtex Bagerudsalg" og 27 "føtex Bager", som er afdelinger inde i butikkerne, ikke
selvstændige butikker. føtex, Bilka og Salling mangler koordinater; `api.sallinggroup.com/v2/stores`
løser alle fire Salling-brands i ét hug, men kræver et gratis token fra
developer.sallinggroup.com.

**Til beslutning:** ~5.930 butikker er næsten en fordobling af datasættet (nu 3.751
rækker). Skal vi tage alle tre kategorier, eller starte med dagligvarer? Og hører Jysk
og IKEA under udvalgsvarer eller pladskrævende? Planloven behandler møbler som
pladskrævende under visse betingelser, så det er en reel vurdering.

---
## 10. september 2026 — designreglen om lastbilanlæg er ændret

**Brugerens beslutning:** lastbil-ladere skal fremgå **separat**, og tankstationer skal
**stadig vises hvis de har diesel og AdBlue**. Den gamle regel ("ingen truck-stationer")
udelukkede dem, og den blev håndhævet ujævnt: 21 YX, 5 Go'on-truck og 32 Circle K
truckanlæg var ude, mens 9 Shell CRT og mindst 11 lastbil-ladere var inde.

### Trin 1 (gennemført): lastbil-ladere som eget lag
`superladere_dk.csv` har fået kolonne 10, `Lastbil` (`ja`/tom). Kortet har nu **fire lag
med hver sin til/fra-knap** — Tankstationer ⛽, Fastfood 🍔, Superladere ⚡ og
Lastbil-ladere 🚛 (lilla). **798 rækker: 784 personbil + 14 lastbil.**

Udpegningen er gjort systematisk, ikke ved navn: alle 798 rækker blev matchet mod
**samtlige 3.144 danske ladestationer i OpenStreetMap** (ét bulk-Overpass-kald) på
`hgv`, `bus` og `socket:mcs`. Kun 4 af de 14 har "Truck" i navnet, så `grep` ville have
fundet under en tredjedel.

**11 rækker mærket** (Norlys ×4, E.ON ×3, OK ×2, Circle K ×1, Uno-X ×1) og
**3 tilføjet**, som manglede helt: Circle K's lastbil-lader ved Skanderborg
(`way/434233297`, 2 × 400 kW, `motorcar=no`), Q8 Truck Padborg (`way/1552181377`) og
Uno-X EV Truck Horsens (`way/1352491956`).

**3 forkastet som nærheds-falske positive** — vigtige, fordi de viser at afstand alene
ikke er nok:
- Circle K "Ørstedsvej. Skanderborg **(personbil)**" — navnet siger det selv; lastbil-
  laderen på samme adresse er et selvstændigt anlæg (nu tilføjet som egen række).
- Norlys "Ladepark Aarup" (300 kW/14) — nabo til truck-anlægget (400 kW/2), eget bil-anlæg.
- Norlys "McDonald's - Stilling" — matchede Circle K's lastbil-lader 49 m væk, andet mærke.

Tre af de 14 har `motorcar=no`: biler kan **fysisk ikke lade** der. Før i dag lignede de
almindelige bil-ladere på kortet.

Kortet er bagudkompatibelt: `ORDER` filtrerer på om laget findes i feedet, så et ældre
`retailkort_data.json` uden `truck` giver stadig de tre oprindelige lag. Verificeret i
node, både med og uden laget.

### Trin 2 (gennemført): lastbil-tank som eget lag
`tankstationer_dk.csv` har fået kolonne 7, `Lastbil`. **2.193 rækker: 2.133 almindelige
+ 60 lastbilanlæg.** Femte kortlag "Lastbil-tank" 🚚 (mørkebrun) med egen til/fra-knap.

**51 tilføjet** fra operatørernes egne data, alle med diesel + AdBlue: 21 YX
(Go'on-kortets `partner`-kategori), 5 Go'on-truck og 25 Circle K truckanlæg.
**9 Shell CRT mærket** (Commercial Road Transport). **7 Circle K udeladt**, fordi de kun
har diesel eller ingen registreret brændstof — de falder uden for brugerens kriterium.

Sammenligningen med Drivkraft Danmark holder derfor stadig på samme population:
2.133 almindelige mod deres ~2.145.

### Lastbil-diesel er en større population end først antaget
Et sweep af alle **2.145 danske tankstationer i OpenStreetMap** viste at OSM's
lastbil-tagging er for tynd til at bære et systematisk udtræk (kun 13 med `hgv`, 138 med
`fuel:HGV_diesel`). Men det afdækkede noget vigtigt om virkeligheden: lastbil-diesel
leveres i Danmark i høj grad på **fælles truckstops hvor flere mærker har hver sin pumpe
side om side** — i Sæby ligger Statoil/STC, Uno-X Diesel Service, IDS og Shell Truck
Diesel inden for 50 m af hinanden; samme mønster ved Vejle DTC, Padborg og Skjern.
Dertil truck-baner ved almindelige stationer, som OSM modellerer som selvstændige punkter.

**36 sådanne lastbil-diesel-punkter findes i OSM uden en tilsvarende række hos os**,
fordelt på bl.a. IDS, Biofuel Express, OK Truck, Uno-X Truck og Shell Truck Diesel.
De er IKKE tilføjet: de kommer fra OSM og ikke fra operatørens egen kilde, og et par af
dem er formentlig samme fysiske anlæg registreret flere gange. En komplet dækning af
lastbil-diesel er sit eget projekt — og kræver en beslutning om multi-brand-truckstops
skal være ét punkt eller ét pr. mærke.

Til gengæld er 24 af vores eksisterende rækker matchet med et OSM-lastbil-punkt inden for
200 m. **Det gør dem ikke til lastbilanlæg** — det er almindelige stationer med en
truck-bane ved siden af (Circle K Albertslund, OK Brande, Uno-X Hjørring m.fl.), og de er
bevidst ikke markeret.

---
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
