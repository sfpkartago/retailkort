# Sådan holdes data friskt (kilder + refresh)

Datasættet er et øjebliksbillede. Sådan hentes friske data fra de officielle kilder.

## Automatisk (rene API'er)
    python3 refresh_data.py     # erstatter OK-tank + Tesla-rækker helt
    python3 reconcile.py        # RAPPORT: til-/afgang for Clever, Ionity, Go'on, OK-lade, Shell

## DAWA er lukket (1. oktober 2026) - adresser slås nu op i DAR og Adressevælgeren
DAWA lukkede "i sin helhed" 1. oktober 2026 kl. 10. `dawa.py` hedder det samme, men
går nu mod:
- **DAR via Datafordelerens GraphQL** (`graphql.datafordeler.dk/DAR/v2`) til
  adresseopslag og omvendt geokodning. Kræver en API-nøgle til frie data fra
  Datafordeler Administration (IT-systemet "Retail Kort"): miljøvariablen
  `DATAFORDELER_API_KEY` eller filen `~/.datafordeler-key`. I Actionen ligger den som
  repository-secret `DATAFORDELER_API_KEY`. Nøglen er gyldig i 2 år.
- **Klimadatastyrelsens Adressevask og Adressevælger** (`adressevaelger.dk`) til
  adresse-eksistens i `validate.py` og til kortets søgefelt. Token er obligatorisk,
  men endnu uden brugerstyring; KDS anbefaler selv `adressevaelger123`. Brugerstyring
  ventes ultimo 2026/primo 2027 - så skal tokenet skiftes (miljøvariabel
  `ADRESSEVAELGER_TOKEN` + konstanten `AVT` i `kort_soeg.html`).
Kontrolleret mod DAWA, mens den stadig svarede (29-09-2026): 798 normaliseringer og
300 omvendte geokodninger identiske; `refresh_data.py` gav byte-identiske CSV'er.
Omvendt geokodning finder kun adresser inden for 3,3 km (DAWA fandt altid én, også
68 km ude i havet); længere væk giver status `ingen-adresse`.

**v3.1 (30-09-2026): kildens eget nummer før nabonummeret, og BBR for tankstationer.**
Til og med v3.0 (og i DAWA-udgaven) lod normaliseringen alle numre på kildens vej
konkurrere på afstand. Nabonummeret vandt derfor over kildens eget, og fandtes kildens
nummer slet ikke, vandt et hvilket som helst nummer inden for 300 m. Da OK's API
30-09-2026 skrev 'Læhegnet 35' og 'Hyrdehøj Bygade 30', der ingen af dem findes, fik
rækkerne Læhegnet 71 og Hyrdehøj Bygade 248B, 281 og 282 m fra stationerne. Rækkefølgen
er nu: kildens egen adresse, hvis den findes inden for grænsen; derefter (kun OK,
`bygning='325'`) tankstationsbygningen i **BBR** (`graphql.datafordeler.dk/BBR/v2`,
samme nøgle) inden for 30 m af koordinaten; så et bogstavnummer i kildens familie tæt
på; ellers adressen ved koordinaten. Kontrolleret mod BBR: på de 53 OK/Tesla-rækker der
fik ny adresse, havde den gamle regel tankstationsbygningens adresse i 0 tilfælde, den
nye i 34, og 12 af dem kunne kun BBR afgøre. Af resten har 16 ingen tankstationsbygning;
ved OK Spentrup og OK Brande findes OK's egen adresse 36-71 m væk på samme grund, mens
bygningen har hjørneadressen. Et BBR-udfald giver `dawa-nede`, ikke en gættet adresse.

**Rettelser af OK og Tesla skal ligge i koden, aldrig kun i dataene.** `refresh_data.py`
erstatter alle OK- og Tesla-rækker hver uge. De to OK-adresser ovenfor blev håndrettet i
CSV'en 10-09-2026 (commit f350ea4) uden en rettelse i koden, og den første ugentlige
kørsel, der nåede at committe (30-09-2026), skrev de forkerte tilbage. OK's egne fejl
ligger nu i `refresh_data.OK_KILDEFEJL`, med OK's egen CVR-P-enhed som belæg. P-enhederne
under OK a.m.b.a. (CVR 39170418) hedder '<OK's stations-id> - <sted>' og har stationens
registrerede adresse; det er den bedste kilde, når OK's API skriver en adresse, der ikke
findes.

**robots.txt (gennemgået 30-09-2026 for alle henteres URL'er).** Coops butiks-API lå
under `/umbraco/`, som robots.txt på coop.dk og alle fire kædedomæner forbyder for alle
bots. `retail_sources.coop()` henter nu Coops fire kæder fra eTilbudsavis/Tjek, som Coop
selv fodrer. Efterprøvet: alle 864 Coop-rækker blev genfundet inden for 150 m, og en
tørkørsel gav 0 nye, 0 lukninger og 0 afvigelser. Kædernes sitemaps er tilladte, men de
giver kun listen; adresserne hentes fra `/umbraco/`. Sport 24 er taget ud af den ugentlige
kørsel, fordi sport24.dk's CloudFront svarer 403 på alt, også robots.txt, ligesom
thansen.dk. De øvrige fund var enten falske alarmer eller ikke overtrædelser. goon.nu:
Pythons robotparser ignorerer `Allow` med længste match. Overpass: `Disallow: /api/`
gælder crawlere, og brugspolitikken tillader API-kald. Tjek selv, før en ny henter
kommer ind: `urllib.robotparser` på værtens robots.txt.

**CVR er godt til adresser, ikke til åbent/lukket.** CVR halter begge veje: 30-09-2026
stod Brugsen Virklund stadig som aktiv en uge efter lukningen, og SuperBrugsen Virklund
havde været aktiv siden april, fem måneder før åbningen. Brug kædens egen liste til
"findes butikken", og CVR til "hvilken adresse har den".

**`cvr_tjek.py` (ugentligt, rapport, blokerer ikke)** holder tanklaget op mod CVR's
produktionsenheder: alle aktive P-enheder med branche 473000 (motorbrændstof) plus OK
a.m.b.a.'s egne (de står under engros, 468100), slået op i DAR. En række sammenlignes kun
med P-enheder fra samme kæde inden for 80 m. Mærket afgøres af P-enhedens navn, for
Circle K ejer også Ingo og Q8 også F24, og ellers af ejeren. Vaskehaller springes over.
Stavevarianter (Gl./Gammel, Allé/Alle) og intervaller (81-83) godtages, og CVR har
intet husbogstav. Afgjorte tilfælde, hvor rækken er rigtig og CVR ikke, står i
`cvr_tjek.KENDTE` med belæg. Første kørsel (30-09-2026) dækkede 806 af 2.194 rækker og
fandt to fejl i vores data: Ingo Seggelund stod på "Hovedvej 55", som ikke findes
(Seggelund Hovedvej 55), og F24 Løgten på "Grenåvej  740f". De stationer, forhandlere og
brugsforeninger driver (fx OK Harlev J under Brugsforeningen TRYG), står ofte under
forhandlerens egen branche og fanges ikke. Rapporten ligger i `cvr_report.txt`.

**Etape 2 (30-09-2026): ugentlige hentere for de største uovervågede kæder.** Normal,
Harald Nyborg, føtex og føtex food, Bilka, Profil Optik, Nyt Syn, Flügger, Fri BikeShop,
Maxi Zoo og Skoringen hentes nu fra kædernes egne lister (39 hentere i alt). Hver er bygget
af en efterforsker og kørt igen uafhængigt af en skeptiker, der kontrollerede robots.txt,
filtrering af ikke-butikker og ikke-åbnede butikker og stikprøver af uoverensstemmelserne.
Første kørsel fandt tre butikker, der manglede eller var flyttet: Normal Aalborg Kennedy
Arkaden (åbnet 30-09-2026), Normal Haderslev (flyttede 29-04-2026 fra Gravene til Bispegade
15) og Nyt Syn Brande. Den fandt også fire fejl i vores egne rækker: en Normal-dublet i
Silkeborg, føtex Herlev fejlnavngivet som "føtex Big", Fri BikeShop Skagen på ejernes
sæsonudlejning og Maxi Zoo Kolding N på et nummer uden for kædens interval. Louis Nielsen
er afvist, fordi siden har en Cloudflare-udfordring og Tjek er forældet; laget kan kun
overvåges via CVR. Dagligvarer overvåges nu ugentligt 100 %, udvalgsvarer 69 %;
tank (uden for OK), lade (uden for Tesla) og spisesteder mangler stadig.

**Etape 3a (01-10-2026): tankkæderne.** Uno-X (bil og lastbil), Circle K og Ingo, OIL! og Shell hentes nu fra kædernes egne lister og er koblet på `refresh_retail.py`, som nu også skriver `tankstationer_dk.csv`: Lastbil-kolonnen udfyldes, og bil- og lastbilanlæg af samme mærke matches hver for sig (nøglen 'mærke|lastbil'). Shell er `KUN_RAPPORT`: Shells egne pins var forkerte for 6 af de 24 anlæg, Shell tilføjede i 2025-26, så nye Shell-anlæg meldes, men tilføjes ikke. Første kørsel fandt 60 Uno-X Truck-anlæg, der manglede (lastbillaget gik fra 62 til 123), og skeptikerne fandt 36 rækkefejl: 19 Ingo-adresser, der ikke findes i DAR, Shell-pins 127-141 m vest for stationen (Råsted, Ryomgård, Tørring, Vorup), Shell Kildebjerg Nord på den forkerte side af E20, OIL!-pins 110-138 m forkert, Q8 Kildebjerg Nord (blev Shell 01-01-2026) og OIL! Randers NØ (kun for firmakort-kunder, nu i `UDELADT`). `validate.py` v5.1 skelner bil og lastbil i reglen om samme mærke inden for 30 m, for et lastbilspor ved en bilstation af samme mærke er to anlæg. Q8 og F24 kom med samme dag (`q8_f24()`). Begge værter, q8.dk og f24.dk, hentes og flettes, fordi q8.dk mangler F24 Thisted. Kun anlæg med rigtigt brændstof tæller, så F24's to vaskehaller (Frejasvej 23D, Vintapperbuen 1A) er slettet sammen med Q8 Frøslev Vest og F24 Frøslev Øst (begge Circle K fra 01-01-2026 ifølge CVR) og "Q8 Vestervig" (hverken i Q8's liste i juni eller nu, ingen Q8-enhed i CVR). Q8Truck's 19 rene lastbilanlæg er ikke med, for flere ligger på andre kæders eller vognmænds grunde, og mærket skal afgøres først; `q8truck()` er skrevet, men ikke koblet på. Ladere og spisesteder følger.

**Ladere fundet via afstemningen (01-10-2026).** `reconcile.py` havde i op til tre uger meldt 11 ladeanlæg, som operatørerne lister, men som manglede på kortet, og ingen handlede på det. Rapporten var fuld af kendt støj: alle fem Go'on-lastbilanlæg stod som "VÆK", fordi `sources.goon()` stadig frasorterede `goon-truck` fra før lastbillaget, og Go'on Vordingborg stod som både NY og VÆK, fordi Go'ons pin ligger 240 m forkert. 10 anlæg er tilføjet: Clever Lynladestation BR (Rødovre, 16 × 600 kW alpitronic) og Hørsholm Midtpunkt, IONITY Odense Åsumvej (var "planned" 8/9, nu aktiv) og 7 OK-anlæg, deraf Aarslev E-truck som lastbillader (afvist 8/9 som "lastbil-lader", før lastbillaget kom 10/9). Antal ladepunkter er OK's CCS-udtag fra `clusters/search` og Clevers/Ionitys udtag på ≥250 kW. `validate.py` tillader nu 250–600 kW (600 kW er grænsen for ét CCS-udtag; OK Truck Korsørs 1000 kW på 4 CCS-udtag er et kabinettal og holdes ude), og bil- og lastbilanlæg af samme mærke skelnes også i ladefilen. Støjen er fjernet i koden: `goon()` tager `goon-truck` med, `GOON_KILDEFEJL` retter Vordingborg-pinnen, og `reconcile.AFGJORT` viser afgjorte kandidater (OK Katrinebjergvej = Stella Aarhus) som "= AFGJORT" i stedet for NY. Efter rettelserne melder afstemningen 0 tilgang og 0 afgang for Clever, Ionity, OK og Go'on.

**Etape 3b (01-10-2026): spisestederne.** 14 hentere er bygget af efterforskere, genkørt og rettet af skeptikere og koblet på `refresh_retail.py`, som nu også skriver `fastfood_kaeder_dk.csv`: Burger King, Espresso House, Sunset Boulevard, Jagger, Carl's Jr., Subway, Gasoline Grill, Halifax, Domino's, Max og Five Guys tilføjes automatisk; Starbucks, KFC og Cocks & Cows er `KUN_RAPPORT`. Skeptikerne tilføjede pin-vagter mod DAR, for kædernes egne pins står forkert netop for nye restauranter (Burger King 4 af 61 med 465-3.111 m, Sunset 5 af 46, den nyeste Hammelev 7,2 km, Carl's Jr. Kolding 1,9 km), samt filtre for "åbner snart", lukkede og rene leveringskøkkener. Espresso House' API lister stadig en café, der lukkede 30-04-2025 (Østerbrogade); den frasorteres. Første kørsel fandt 7 manglende restauranter og 6 rækker, der ikke hørte til; fem Jagger-rækker stod på søsterkæden Ottos husnumre. `refresh_retail.KENDT_UDEN_KILDE` viser rækker, vi beholder med belæg, selv om kilden udelader dem (to Espresso House på Lalandia), som "KENDT" i stedet for "MULIG LUKNING". McDonald's og Joe & The Juice har ingen tilladt kilde; en CVR-baseret overvågning er afprøvet, men giver for meget støj (17 "nye" og 11 "lukninger" hver uge for Joe) til at køre uden en afgjort-liste.

**To slags refresh, med vilje forskellige:**
- `refresh_data.py` **erstatter** alle OK-tank- og Tesla-rækker. Det er forsvarligt,
  fordi begge kilder er komplette og entydige. Adresserne normaliseres mod DAR
  (`dawa.py`) — kildernes egne postnr/by-felter er upålidelige, se nedenfor.
- `reconcile.py` **rapporterer kun**. Den matcher kilden mod datasættet på
  koordinat-nærhed og lister til-/afgang, så hånd-QA'ede adresser ikke overskrives.
  Kandidaterne SKAL vurderes enkeltvis — kørslen 2026-09-08 viste hvorfor:
  planlagte anlæg, lastbilanlæg og dubletter i kildernes egne data.
  Men vurdér på KILDEDATA, ikke på afstand: Clever "Veri Centret" blev først
  fejlagtigt afvist som en Eviny-dublet fordi den lå 37 m fra Eviny's anlæg — det er
  et selvstændigt Clever-anlæg med eget hardware. Brug operatørens stamdata
  (`siteType`, brændstofliste, `chargePointIds`/`vendorName`) og OSM som dommer.
  `reconcile.py` FLAGGER naboer på tværs af mærker; den afviser dem ikke.

## Kildernes adressefelter er upålidelige — koordinaten er ikke
Normalisér ALTID nye rækker gennem `dawa.normalize_one()`. Postnr/by tages fra
koordinaten, vejnavnet får DAR's kanoniske stavemåde. Målte eksempler:
- supercharge.info: "Hobrovej 452, **9300** Aalborg" (anlægget ligger i 9200 Aalborg SV),
  "Rødovre Centrum 254, **2800** Rødovre" (Rødovre er 2610), "8260 **Aarhus**" (= Viby J).
- find.shell.com: DAWA gav datasættet ret i **5 af 6** postnummer-uenigheder med Shell.
- Shell gav to forskellige stationer i Hedehusene **samme** koordinat (2 m fra hinanden),
  selvom adresserne ligger 1,2 km fra hinanden.

## Alle datakilder (endpoints)
### Tankstationer
- OK: https://mobility-prices.ok.dk/api/v1/fuel-prices  (JSON, ingen nøgle)
- Circle K + Ingo: https://www.circlek.dk/stations  (HTML-liste → /station/<slug>; ingo-* = Ingo)
- Shell: **https://find.shell.com/dk (uden locale) er død (404).** Ny sti:
  https://find.shell.com/dk/fuel/locations/da_DK — `data-page="app"`-JSON findes stadig.
  Landesiden har 170 by-sider i `props.geographicListProps.locations`; hver by-side har
  stationerne i `props.stationListProps.locations` (id, navn, adresse, `logo_url`).
  `logo_url` skiller anlægstyperne: conventional-fuel-site / -with-ev / destination-charging-ev.
- Uno-X: https://unoxmobility.dk/privat/find-station  (Next.js station-feed)
- F24: https://www.f24.dk/find-station/  (station/<by>/<adresse>-slugs)
- Go'on: https://goon.nu/wp-admin/admin-ajax.php?action=msb_map_pins  (`var data = [...]`)
  Kategorier: `goon` + `goon, kombi` = Go'on (194) · `lavpris` = Lavpris · `goon-truck` (5)
  og `partner` (21 × YX) UDELADES — alle 21 er ren lastbil-diesel (ingen benzin,
  truck-piktogram, adresser som Dieselvej/Cargovej). YX Truck blev Uno-X Truck i april 2023
  (CVR 33807910 skiftede navn 27-03-2023), så de 21 står i datasættet som Uno-X, Lastbil=ja,
  med Uno-X' egne stationsnavne; Go'ons partnerpins var forkerte for Taastrup, Aarhus og Odense.
- Q8: https://www.q8.dk/find-station/
- OIL!: https://www.oil-tankstationer.dk/tankstationer-find-din-station/
- CNG/biogas: https://tankbiogas.dk/find-gastankstationerne/
- Lokale (Oles Olie, Øboens, Lavpris, HK Benzin m.fl.): egne sider

### Superladere (≥250 kW)
- Clever: https://clever.dk/api/v2/chargers/locations  (JSON; filtrér maxPowerKw≥250, countryCode=DK, state=Active)
  ⚠ `isRoamingPartner` er nu **False på alle 3.565 records** og kan IKKE længere bruges til
  at sortere roaming-skygger fra. Tjek nye Clever-anlæg mod ANDRE mærker inden for 150 m
  (2026-09-08: "Veri Centret" var Eviny's "VERI Center" 37 m væk, samme adresse).
- Norlys: https://api.monta.app (Monta-platform, operator=norlys)
- Circle K: https://www.circlek.dk/opladning/opladningskort
- E.ON: https://www.edri.com/da-dk/where-to-charge
- OK: **GET /api/v2/clusters er død (404).** Brug i stedet:
  POST https://geo-emobility.okcloud.dk/api/v2/locations/nearby  — har et `power`-felt;
  ét kald med {latitude:56.1, longitude:10.15, distanceM:300000, maxLocations:5000,
  filters:{locationSources:["OK"]}} henter alle ~1.450 lokationer med effekt.
  POST /api/v2/clusters/search giver `spots` pr. lokation, men ingen effekt; kræver
  lille bbox for at returnere locations frem for clusters.
  ⚠ `len(spots)` er IKKE antal ladepunkter — tæl kun `connectorTypes == 'Ccs'`.
  Årslev Logistikparken har 4 Ccs + 2 langsomme Type2-AC, og fem OK-motorvejsanlæg
  har et 100 kW CHAdeMO-stik med i spot-listen. Begge blev fejlagtigt talt med.
  Swagger: https://geo-emobility.okcloud.dk/swagger/v1/swagger.json
- Shell Recharge: https://find.shell.com/dk/fuel/locations/da_DK (se Shell under tank)
- Ionity: https://wf-assets.com/ionity/mapdata.json → `LocationDetails`
  ⚠ filtrér `state=="active"` — planlagte anlæg har 0 stik (2026-09-08 ville Aalborg
  Skalborg og Odense Åsumvej ellers ryge ind som spøgelser). `country=="denmark"`.
  Effekten skal REGNES ud af `connectors{600,500,400,350}kw` — det er IKKE altid 350 kW
  (Aarup, Ringsted, Struer, Nørresundby og Korsør er 400 kW).
- Tesla: https://supercharge.info/service/supercharge/allSites  (filtrér Denmark, OPEN, ≥250)
- EWII/Allego/Spirii/Fastned/Eviny m.fl.: egne kort / Monta

### Fastfood
De ugentlige hentere står i `retail_sources.py` under "ETAPE 3B: SPISESTEDER" med kilde,
faelder og forventet antal i hver docstring. Kort:
- McDonald's: **www.mcdonalds.com svarer Akamai 403 på alt, også robots.txt (01-10-2026)**,
  og der er ingen anden officiel liste. Ingen ugentlig henter; nye restauranter må findes
  via CVR (P-enheder i branche 5611xx) og smiley.
- Burger King: kædens bestillings-API, `bk-dk-ordering-api-…azurefd.net/api/v2/restaurants`,
  virker igen (01-10-2026): uden parametre giver den alle 61. Med kun lat/lon er svaret tomt.
- Joe & The Juice: www.joejuice.com svarer med en Vercel-udfordring (HTTP 429), også på
  robots.txt. Ingen ugentlig henter.
- Øvrige kæder: deres egne store-locators/API'er (se docstrings).

## Fuld genopfriskning (SPA-kilder via workflows)
De kilder der er JS-apps hentes lettest ved at gen-køre de gemte Claude Code-workflows
(re-fetcher alt live). Scripts ligger i:
  ~/.claude/projects/<projekt>/workflows/scripts/
    fetch-official-fuel-stations-*.js      (Circle K, Ingo, Shell, Uno-X, F24, Go'on, Q8, OIL!, HK)
    fetch-official-superchargers-*.js       (Clever, Norlys, Circle K, E.ON, OK, Shell, Ionity)
    dk-fastfood-chains-*.js                 (fastfood-kæderne)
Adresser uden koordinater geokodes via Adressevælgeren (https://adressevaelger.dk/husnumre/soeg,
se `dawa.py`); DAWA er lukket.

## Genopbyg kort + Excel efter refresh
    python3 rebuild.py
Genopbygger kort_soeg.html + kaede_adresser.xlsx ud fra de tre CSV'er og opdaterer
datostemplet. Kort-motoren (Leaflet) er indlejret i kort_soeg.html og bevares mellem
builds — kun DATA-blokken udskiftes, så kortet forbliver selvstændigt/offline-robust.

## Kvalitetskontrol
    python3 validate.py

`validate.py` v4 tjekker nu også (tilføjet 2026-09-08, fordi v3 gav "0 hårde fejl"
mens 74 rækker havde en adresse DAWA ikke har):

- **ADRESSE-EKSISTENS** via Klimadatastyrelsens Adressevask (v5.0; indtil 29-09-2026
  DAWA's `datavask`). Vaskens koder oversættes til A (1000/800/700), B (900, vejnavn
  rettet) og C (negative = findes ikke). Vasken arbejder på ENHEDER (etage/dør), så ved
  -500/-600 og ved de øvrige negative koder slås husnummeret op direkte i Adressevælgeren
  (fonetisk vejnavn, eksakt husnr+postnr); et eksakt træf betyder at adressen findes.
  Nyt tjek: **forældet betegnelse** - vasken svarer med et andet husnummer, og vores
  findes ikke i DAR i dag (fx "Vestergade 29, 7100" hedder nu 29B). v4.1 så det aldrig:
  DAWA's datavask svarede med den historiske version (kategori A) og lagde den nye i
  `aktueladresse`, som v4.1 ikke læste. 59 er rettet (commit 637347d), 11 står tilbage. BEMÆRK: DAWA's "C med samme husnr" (INFO) skjulte også
  rækker på en ANDEN vej (Smedeland 1 -> Murervangen 1); de er nu tjek-punkter. Et almindeligt `/adgangsadresser`-opslag
  kan IKKE bruges: `vejnavn`-parameteren kræver eksakt match, så "Helgeshøj Allé"
  (staves "Alle"), "Gl. Hovedvej" ("Gl.Hovedvej") og "Nr. Virumvej" ("Nr Viumvej")
  gav 250 falske fejl. Adressefeltet renses først — mellem-segmenter ("Bårse Runddel",
  "Terminal 3"), parenteser ("(2020)") og husnummer-intervaller ("51-53") fjernes,
  ellers drukner tjekket i parse-støj.
  Kategori C med SAMME husnr og postnr som rækken regnes som en stavevariant af
  vejnavnet, ikke en manglende adresse.
- **ADRESSE vs KOORDINAT**: afstanden fra rækkens koordinat til dens EGEN adresse.
  Kun en tjek-liste, ikke en hård fejl — de fjerneste legitime rækker ligger 428-449 m
  ude (store grunde), og forholdet "egen/nærmeste adresse" kan ikke skelne legitimt fra
  fejl. Listen fangede straks `EXPRESS EBELTOFT` på 1.104 m.

**Hård fejl kun hvor pipelinen garanterer noget:** `refresh_data.py` normaliserer OK-tank
og Tesla mod DAR, så en uafklaret adresse dér er en hård fejl. For de øvrige mærker er
det et kendt gap (se `REFRESH_LOG.md`) og havner på tjek-listen.

**Kategori-renhed** (sælger tank-rækken faktisk brændstof?) ligger i `reconcile.py`, ikke
i `validate.py`: samplacering på tværs af lagene er normal — 213 par ligger inden for
150 m, fordi Uno-X og Circle K sælger både brændstof og strøm samme sted. Kun operatørens
egen brændstofliste kan afgøre det. `reconcile.py` henter Circle K's `siteType` +
brændstofliste fra den indlejrede JSON på circlek.dk/station-search og Shells `logo_url`,
og afstemmer samtidig antallet (Circle K 206/206, Ingo 196/196).

Kørselstid: `validate.py` v5.0 bruger ~5 min lokalt (reverse 24 tråde mod DAR, vask +
adgangspunkt 16 tråde mod Adressevælgeren - den bryder sammen ved 32). Actionen giver 40 min.

## Kendte freshness-punkter (skal følges)
- **HK Benzin → Shell Express**: Hornsyld Købmandsgaard sælger sine ~21 jyske
  tankanlæg til DCC Energi; de konverteres til Shell Express (godkendt Q2 2026).
  HK Benzin-mærket forsvinder gradvist. Tjek https://hk-hornsyld.dk/find-tankstation
  og find.shell.com/dk ved næste refresh. (Fåborgvej 49 Årre er allerede konverteret.)
- Nyåbninger af eksisterende kæder (McDonald's, Circle K-ladehubs, Sunset) fanges
  ikke af validate.py — kræver re-scrape af kædernes egne finders.

## Restrisiko (ikke automatisk dækket) — se qa-audit critic
liveness/lukkede "zombie"-stationer · manglende enkelt-lokationer af dækkede kæder
(set-level reconciliation) · husnummer-nøjagtighed · cross-dataset-konsistens.
