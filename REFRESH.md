# Sådan holdes data friskt (kilder + refresh)

Datasættet er et øjebliksbillede. Sådan hentes friske data fra de officielle kilder.

## Automatisk (rene API'er)
    python3 refresh_data.py
Henter **OK** (tank) og **Tesla** (superladere) friskt fra deres offentlige API'er og
opdaterer CSV'erne in-place. Bagefter skal kort/Excel genopbygges (se nederst).

## Alle datakilder (endpoints)
### Tankstationer
- OK: https://mobility-prices.ok.dk/api/v1/fuel-prices  (JSON, ingen nøgle)
- Circle K + Ingo: https://www.circlek.dk/stations  (HTML-liste → /station/<slug>; ingo-* = Ingo)
- Shell: https://find.shell.com/dk  (embedded JSON i script data-page="app")
- Uno-X: https://unoxmobility.dk/privat/find-station  (Next.js station-feed)
- F24: https://www.f24.dk/find-station/  (station/<by>/<adresse>-slugs)
- Go'on: https://goon.nu/wp-admin/admin-ajax.php?action=msb_map_pins  (JSON pins)
- Q8: https://www.q8.dk/find-station/
- OIL!: https://www.oil-tankstationer.dk/tankstationer-find-din-station/
- CNG/biogas: https://tankbiogas.dk/find-gastankstationerne/
- Lokale (Oles Olie, Øboens, Lavpris, HK Benzin m.fl.): egne sider

### Superladere (≥250 kW)
- Clever: https://clever.dk/api/v2/chargers/locations  (JSON; filtrér maxPowerKw≥250, countryCode=DK, isRoamingPartner=false)
- Norlys: https://api.monta.app (Monta-platform, operator=norlys)
- Circle K: https://www.circlek.dk/opladning/opladningskort
- E.ON: https://www.edri.com/da-dk/where-to-charge
- OK: https://geo-emobility.okcloud.dk/api/v2/clusters
- Shell Recharge: https://find.shell.com/dk
- Ionity: https://wf-assets.com/ionity/mapdata.json  (alle 350 kW)
- Tesla: https://supercharge.info/service/supercharge/allSites  (filtrér Denmark, OPEN, ≥250)
- EWII/Allego/Spirii/Fastned/Eviny m.fl.: egne kort / Monta

### Fastfood
- McDonald's: www.mcdonalds.com geolocation-API (country=dk)
- Burger King: bk-dk-ordering-api...azurefd.net/api/v2/restaurants
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
