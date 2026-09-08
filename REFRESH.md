# Sådan holdes data friskt (kilder + refresh)

Datasættet er et øjebliksbillede. Sådan hentes friske data fra de officielle kilder.

## Automatisk (rene API'er)
    python3 refresh_data.py     # erstatter OK-tank + Tesla-rækker helt
    python3 reconcile.py        # RAPPORT: til-/afgang for Clever, Ionity, Go'on, OK-lade, Shell

**To slags refresh, med vilje forskellige:**
- `refresh_data.py` **erstatter** alle OK-tank- og Tesla-rækker. Det er forsvarligt,
  fordi begge kilder er komplette og entydige. Adresserne normaliseres mod DAWA
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
koordinaten, vejnavnet får DAWA's kanoniske stavemåde. Målte eksempler:
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
  og `partner` (21 × YX) UDELADES — alle 21 YX er ren lastbil-diesel (ingen benzin,
  truck-piktogram, adresser som Dieselvej/Cargovej).
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
  ⚠ `len(spots)` er IKKE antal ladestandere — tæl kun `connectorTypes == 'Ccs'`.
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
- McDonald's: www.mcdonalds.com geolocation-API (country=dk)
- Burger King: **bk-dk-ordering-api...azurefd.net/api/v2/restaurants er død (404).**
  burgerking.dk er nu en Angular-app uden API-spor i HTML'en — endpointet skal
  findes i JS-bundlet. IKKE genfundet pr. 2026-09-08.
- Øvrige kæder: deres officielle store-locators

## Fuld genopfriskning (SPA-kilder via workflows)
De kilder der er JS-apps hentes lettest ved at gen-køre de gemte Claude Code-workflows
(re-fetcher alt live). Scripts ligger i:
  ~/.claude/projects/<projekt>/workflows/scripts/
    fetch-official-fuel-stations-*.js      (Circle K, Ingo, Shell, Uno-X, F24, Go'on, Q8, OIL!, HK)
    fetch-official-superchargers-*.js       (Clever, Norlys, Circle K, E.ON, OK, Shell, Ionity)
    dk-fastfood-chains-*.js                 (fastfood-kæderne)
Adresser uden koordinater geokodes via DAWA: https://api.dataforsyningen.dk/adgangsadresser

## Genopbyg kort + Excel efter refresh
    python3 rebuild.py
Genopbygger kort_soeg.html + kaede_adresser.xlsx ud fra de tre CSV'er og opdaterer
datostemplet. Kort-motoren (Leaflet) er indlejret i kort_soeg.html og bevares mellem
builds — kun DATA-blokken udskiftes, så kortet forbliver selvstændigt/offline-robust.

## Kvalitetskontrol
    python3 validate.py

⚠ `validate.py` er IKKE tilstrækkelig alene. Den verificerer ikke at et husnummer
FINDES, og dens "koord på anden vej"-tjek måler afstand til reverse-punktet — ikke
til den påståede adresse. Derfor gav den "0 hårde fejl" mens 74 rækker havde en
adresse DAWA ikke har (2026-09-08). Kør derfor efter hvert refresh også:

    python3 - <<'EOF'
    import csv, dawa, concurrent.futures, collections
    def st(vej,hn,pn):
        if not hn: return 'INGEN_HUSNR' if dawa.on_street(vej,pn) else 'VEJ_MANGLER'
        return 'OK' if dawa.lookup(vej,hn,pn) else 'HUSNR_MANGLER'
    for fn,ai,pi in (('tankstationer_dk.csv',2,3),('superladere_dk.csv',2,3),
                     ('fastfood_kaeder_dk.csv',2,3)):
        rows=list(csv.reader(open(fn,encoding='utf-8-sig')))[1:]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            res=list(ex.map(lambda r: st(*dawa.split_street(r[ai]), str(r[pi]).strip()), rows))
        print(fn, collections.Counter(res).most_common())
    EOF
Præcis validator (v3): skiller HÅRDE FEJL (ugyldigt postnr, koord uden for DK,
ombyttet lat/lon, kryds-mærke-dublet, nær-dublet, manglende felter, effekt uden
for 250-500 kW) fra en TJEK-liste (mulige — postnummergrænse/hjørne/forskydning,
kan være falske positiver). Kør efter hvert refresh. Status pr. 2026-07-08: 0 hårde
fejl, 1 benign advisory.

Den DYBE fejl-jagt (koordinat-forskydning, kategori-renhed, manglende kæder,
brand-attribution) blev kørt som et multi-agent QA-workflow (qa-audit-datasets)
med adversariel verifikation — gen-kør det for en fuld revision, ikke bare validate.py.

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
