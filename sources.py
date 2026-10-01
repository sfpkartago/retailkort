#!/usr/bin/env python3
"""
sources.py — hentere for de kilder der har et stabilt, offentligt endpoint.

Hver hente-funktion returnerer en liste af dicts:
    {'brand','name','street','postnr','by','lat','lon','kw','plug','count'}
kw/plug/count er kun sat for ladere. Adresserne er kildens rå tekst — de
normaliseres mod DAWA (se dawa.py) FØR de skrives til CSV.

Status pr. 2026-09-08 (probet):
  ✓ Clever, Go'on (+Lavpris), Ionity, Tesla, OK-tank, Circle K (HTML)
  ✗ OK-lade (geo-emobility ... /v2/clusters), Burger King (azurefd), Shell (find.shell.com/dk)
    — alle tre svarer 404; endpoints er flyttet siden juli.
"""
import json, re, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'}

def _raw(url, timeout=90):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()

def _json(url, timeout=90):
    return json.loads(_raw(url, timeout))

def _f(v):
    try: return round(float(str(v).strip()), 6)
    except (TypeError, ValueError): return None

# ---------------------------------------------------------------- Clever
def clever(floor=250):
    """Clever-ejede DC-hubs >= floor kW.

    ADVARSEL: isRoamingPartner er False paa ALLE 3565 records, og operator.name,
    partyId og origin er ligeledes uniforme ('Clever'/'CLE'). Feedet kan altsaa
    IKKE bruges til at skelne Clevers egne anlaeg fra roaming-skygger — filteret
    nedenfor er reelt en no-op. Nye anlaeg taet paa et andet maerke skal derfor
    tjekkes paa hardware (chargePointIds, vendorName) og mod OSM, ikke paa afstand
    alene: 'Veri Centret' blev 2026-09-08 foerst fejlagtigt afvist som en Eviny-
    dublet, men er et selvstaendigt Clever-anlaeg 40 m fra Eviny's."""
    d = _json('https://clever.dk/api/v2/chargers/locations')
    out = []
    for v in d.values():
        a = v.get('address') or {}
        if a.get('countryCode') != 'DK' or v.get('state') != 'Active' or v.get('isRoamingPartner'):
            continue
        fast = []
        for e in (v.get('evses') or {}).values():
            cs = list((e.get('connectors') or {}).values())
            if cs and max(c.get('maxPowerKw') or 0 for c in cs) >= floor:
                fast.append(cs)
        if not fast:
            continue
        kw = max(c.get('maxPowerKw') or 0 for cs in fast for c in cs)
        plugs = sorted({c.get('plugType') for cs in fast for c in cs if (c.get('maxPowerKw') or 0) >= floor})
        c = v.get('coordinates') or {}
        out.append({'brand': 'Clever', 'name': v.get('name') or '',
                    'street': a.get('address') or '', 'postnr': str(a.get('postalCode') or ''),
                    'by': a.get('city') or '', 'lat': _f(c.get('lat')), 'lon': _f(c.get('lng')),
                    'kw': round(kw), 'plug': '+'.join(p.replace('Combo','CCS') for p in plugs) or 'CCS',
                    'count': len(fast)})
    return out

# ---------------------------------------------------------------- Ionity
IONITY_TIERS = [('connectors600kw', 600), ('connectors500kw', 500),
                ('connectors400kw', 400), ('connectors350kw', 350),
                ('connectors200kw', 200), ('connectors50kw', 50)]

def ionity(floor=250):
    """Ionity DK. mapdata.json har state 'active'|'planned' — planlagte anlæg
    har 0 stik og SKAL udelades (ellers ryger IONITY Aalborg Skalborg og
    Odense Åsumvej ind som spøgelser). Effekten regnes ud af stik-trinnene:
    ikke alle Ionity-anlæg er 350 kW — Aarup/Ringsted/Struer er 400 kW.
    Kilden har ingen adressefelter, så adressen kommer fra DAWA-reverse."""
    d = _json('https://wf-assets.com/ionity/mapdata.json')
    out = []
    for s in d.get('LocationDetails', []):
        if s.get('country') != 'denmark' or s.get('state') != 'active':
            continue
        lat, lon = _f(s.get('latitude')), _f(s.get('longitude'))
        if lat is None or lon is None:
            continue
        fast = [(s.get(k) or 0, kw) for k, kw in IONITY_TIERS if kw >= floor and (s.get(k) or 0) > 0]
        if not fast:
            continue
        out.append({'brand': 'Ionity', 'name': s.get('name') or '',
                    'street': '', 'postnr': '', 'by': '', 'lat': lat, 'lon': lon,
                    'kw': max(kw for _, kw in fast),
                    'plug': 'CCS', 'count': sum(n for n, _ in fast)})
    return out

# ---------------------------------------------------------------- OK (ladere)
def _post(url, body, timeout=90):
    h = {**UA, 'Content-Type': 'application/json', 'DeviceId': 'kartago-refresh'}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def ok_chargers(floor=250, ceiling=600):
    """OK's ladenetværk. Endpointet i REFRESH.md (GET /api/v2/clusters) er død;
    det hedder nu POST /api/v2/clusters/search — men DEN har ingen effekt.
    POST /api/v2/locations/nearby har til gengæld et 'power'-felt, og ét kald
    med distanceM=300 km fra Danmarks midte henter alle ~1.450 lokationer.
    locationSources=['OK'] holder roaming-partnere ude.

    ceiling=600 følger validate.py's regel (600 kW er graensen for ét CCS-udtag). Det
    udelader netop 'OK Truck Korsør, Storebæltsvej': 1000 kW paa 4 CCS-udtag, altsaa et
    kabinet- eller anlaegstal, ikke udtagets effekt."""
    r = _post('https://geo-emobility.okcloud.dk/api/v2/locations/nearby',
              {'latitude': 56.1, 'longitude': 10.15, 'distanceM': 300000,
               'maxLocations': 5000, 'filters': {'locationSources': ['OK']}})
    out = []
    for x in r.get('locations', []):
        kw = x.get('power') or 0
        if not (floor <= kw <= ceiling):
            continue
        lat, lon = _f(x.get('latitude')), _f(x.get('longitude'))
        if lat is None or lon is None:
            continue
        out.append({'brand': 'OK', 'name': x.get('name') or '',
                    'street': x.get('address') or '', 'postnr': '', 'by': '',
                    'lat': lat, 'lon': lon, 'kw': kw, 'plug': 'CCS', 'count': ''})
    return out

# ---------------------------------------------------------------- Go'on / Lavpris
GOON_CATS = {'goon': "Go'on", 'goon, kombi': "Go'on", 'goon-truck': "Go'on", 'lavpris': 'Lavpris'}
# Go'ons egne pin-fejl. Uden rettelsen giver de et falsk NY+VÆK-par i reconcile.py, og
# en rapport fuld af kendt stoej bliver ikke laest. Noegle: (titel, adresse) som i kilden.
GOON_KILDEFEJL = {
    # Pinnen staar 240 m nord for stationen (DAR: Marienbergvej 94, ingen tankbygning).
    # Vores raekke staar paa BBR's tankbygning (anvendelse 325) paa nr. 100, 50 m fra
    # DAR-punktet (01-10-2026).
    ("Go'on Vordingborg", 'Marienbergvej 100, 4760 Vordingborg'): (55.000930, 11.895013),
}

def goon():
    """Go'on-kortets pins. Kategorierne 'goon'+'goon, kombi'+'goon-truck' = Go'on,
    'lavpris' = Lavpris. 'goon-truck' er med siden 01-10-2026: lastbilanlaeggene staar i
    tanklaget (Lastbil=ja) siden designreglen blev aendret 10-09-2026, og uden dem meldte
    reconcile.py alle fem som 'VÆK'. UDELADT: 'partner' (YX = Uno-X Truck siden 2023; de
    ligger under Uno-X og hentes af retail_sources.unox())."""
    t = _raw('https://goon.nu/wp-admin/admin-ajax.php?action=msb_map_pins').decode('utf-8', 'replace')
    arr = json.loads(t[t.index('['):].rstrip().rstrip(';'))
    out = []
    for x in arr:
        brand = GOON_CATS.get((x.get('categories') or '').strip())
        if not brand:
            continue
        lat, lon = _f(x.get('lat')), _f(x.get('lng'))
        if lat is None or lon is None:
            continue
        lat, lon = GOON_KILDEFEJL.get(((x.get('title') or '').strip(),
                                       (x.get('address') or '').replace('\t', ' ').strip()), (lat, lon))
        out.append({'brand': brand, 'name': (x.get('title') or '').strip(),
                    'street': (x.get('address') or '').replace('\t', ' ').strip(),
                    'postnr': '', 'by': (x.get('town') or '').strip(),
                    'lat': lat, 'lon': lon, 'kw': '', 'plug': '', 'count': ''})
    return out

# ---------------------------------------------------------------- Shell
import html as _html, concurrent.futures as _cf

def _shell_app(url):
    h = _raw(url).decode('utf-8', 'replace')
    m = re.search(r'data-page="app"[^>]*>\s*(\{.*?\})\s*</script>', h, re.S)
    return json.loads(_html.unescape(m.group(1))) if m else None

def shell(workers=6):
    """find.shell.com. Stien i REFRESH.md (/dk) er død — den hedder nu
    /dk/fuel/locations/da_DK, og den indlejrede data-page="app"-JSON findes
    stadig. Landesiden lister 170 by-sider; hver by-side har stationerne med
    id, navn, adresse og et logo_url der skiller tankanlæg fra EV-anlæg."""
    top = _shell_app('https://find.shell.com/dk/fuel/locations/da_DK')
    cities = top['props']['geographicListProps']['locations']
    out, seen = [], set()

    def one(c):
        try:
            d = _shell_app('https://find.shell.com' + c['link'])
            return (d or {}).get('props', {}).get('stationListProps', {}).get('locations', [])
        except Exception:
            return []

    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for locs in ex.map(one, cities):
            for x in locs:
                if x['id'] in seen:
                    continue
                seen.add(x['id'])
                parts = [p.strip() for p in (x.get('formatted_address') or '').split('\n') if p.strip()]
                street = parts[0] if parts else ''
                pn = next((p for p in parts if re.fullmatch(r'\d{4}', p)), '')
                by = parts[2] if len(parts) > 2 else ''
                out.append({'brand': 'Shell', 'name': (x.get('name') or '').strip(),
                            'street': street.title(), 'postnr': pn, 'by': by.title(),
                            'lat': None, 'lon': None, 'kw': '', 'plug': '', 'count': '',
                            'id': x['id'], 'link': x.get('link'),
                            'kind': (x.get('logo_url') or '').rsplit('/', 1)[-1]})
    return out

# ---------------------------------------------------------------- Lagkagehuset
def lagkagehuset():
    """Lagkagehusets egne butiksdata. Siden er Next.js 13+, saa listen ligger i
    flight-chunks (self.__next_f.push) og ikke i __NEXT_DATA__. Hver butik har navn,
    adresse, by, land og koordinat. Kun country=DK — kaeden driver ogsaa 'Ole & Steen'
    i udlandet."""
    import codecs
    h = _raw('https://lagkagehuset.dk/butikker').decode('utf-8', 'replace')
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', h, re.S)
    raw = "".join(codecs.decode(c.encode(), 'unicode_escape').encode('latin-1')
                  .decode('utf-8', 'replace') for c in chunks)
    out, seen = [], set()
    for blob in re.findall(r'\{(?:[^{}]|\{[^{}]*\})*?"latitude"(?:[^{}]|\{[^{}]*\})*?\}', raw):
        try:
            b = json.loads(blob)
        except Exception:
            continue
        if (b.get('country') or 'DK').upper() != 'DK':
            continue
        lat, lon = _f(b.get('latitude')), _f(b.get('longitude'))
        if lat is None or b.get('id') in seen:
            continue
        seen.add(b.get('id'))
        out.append({'brand': 'Lagkagehuset', 'name': (b.get('name') or '').strip(),
                    'street': (b.get('address') or '').strip(), 'postnr': '',
                    'by': (b.get('city') or '').strip(), 'lat': lat, 'lon': lon,
                    'kw': '', 'plug': '', 'count': ''})
    return out


# ---------------------------------------------------------------- OSM pr. maerke
def _ikke_aaben(tags, idag=None):
    """True hvis et OSM-element ikke er en aaben butik i dag.

    Brand-tagget alene er ikke nok. 29-09-2026 gav osm_brand to falske thansen-
    butikker: en byggeplads i Bjerringbro (landuse=construction, construction=retail,
    name="Thansen & Sport 24 Outlet") og en butik i Holstebro med
    opening_date=2026-10-30. Begge kom paa kortet som aabne butikker."""
    import datetime as _dt
    idag = idag or _dt.date.today().isoformat()
    if tags.get('landuse') == 'construction' or 'construction' in tags:
        return True
    if tags.get('shop') in ('vacant', 'construction'):
        return True
    if any(k.split(':', 1)[0] in ('disused', 'abandoned', 'was', 'demolished', 'razed',
                                   'removed', 'planned', 'proposed', 'construction')
           and ':' in k for k in tags):
        return True
    od = (tags.get('opening_date') or '').strip()
    # opening_date kan vaere "2026-10-30", "2026-10" eller "2026"; sammenlign kun
    # hvis den ligner en dato. En dato i fremtiden = ikke aaben endnu.
    if od[:4].isdigit() and od[:len(idag)] > idag[:len(od)]:
        return True
    return False


def osm_brand(brands, timeout=200):
    """Hent kaeder fra OpenStreetMap paa brand-tag. Bruges hvor kaedens egen
    butiksfinder er en SPA uden tilgaengeligt API (Joe & The Juice og Espresso House
    henter via Storyblok med skjult token; 7-Eleven har ingen aaben liste).
    OSM har ingen adresser paa disse punkter — de skal geokodes fra koordinaten
    med dawa.normalize_one(). -> liste af raekke-dicts."""
    import urllib.parse
    # IKKE re.escape: den escaper mellemrum i Python 3.9 ("Joe\\ &\\ The\\ Juice"),
    # hvilket giver 0 traeffere i Overpass. Maerkenavnene er vores egne, ikke brugerinput.
    rx = "|".join(brands)
    q = ('[out:json][timeout:120];area["ISO3166-1"="DK"][admin_level=2]->.dk;'
         f'nwr(area.dk)["brand"~"{rx}",i];out center tags;')
    # Et gyldigt men TOMT svar er ikke til at skelne fra "kaeden findes ikke": Overpass
    # svarer 200 med elements=[] naar forespoergslen timer ud internt. 7-Eleven gav
    # saaledes 0 i én koersel og 177 i den naeste. Derfor: tomt svar -> proev naeste
    # spejl, og returnér foerst tomt naar ALLE spejle er enige.
    sidst, els = None, None
    for m in ('https://overpass-api.de/api/interpreter',
              'https://overpass.kumi.systems/api/interpreter',
              'https://overpass.private.coffee/api/interpreter'):
        try:
            req = urllib.request.Request(m, data=urllib.parse.urlencode({'data': q}).encode(),
                                         headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                svar = json.loads(r.read()).get('elements', [])
            if svar:
                els = svar; break
            els = []          # husk det tomme svar, men prøv videre
        except Exception as e:
            sidst = e
    if els is None:
        raise RuntimeError(f'alle Overpass-spejle fejlede: {sidst}')
    out = []
    for e in els:
        y = e.get('lat') or (e.get('center') or {}).get('lat')
        x = e.get('lon') or (e.get('center') or {}).get('lon')
        if y is None:
            continue
        t = e.get('tags', {})
        if _ikke_aaben(t):
            continue
        br = t.get('brand') or ''
        navn = t.get('name') or br
        out.append({'brand': br, 'name': navn.strip(),
                    'street': f"{t.get('addr:street','')} {t.get('addr:housenumber','')}".strip(),
                    'postnr': t.get('addr:postcode') or '', 'by': t.get('addr:city') or '',
                    'lat': _f(y), 'lon': _f(x), 'kw': '', 'plug': '', 'count': '',
                    'osm': f"{e['type']}/{e['id']}"})
    return out

# ---------------------------------------------------------------- Circle K stamdata
def circlek_sites():
    """Circle K's egne stamdata for alle 443 danske anlæg, fra den indlejrede
    drupalSettings-JSON på /station-search (ck_sim_search.station_results).

    Hvert anlæg har `siteType` ('ST' = station, 'EV' = ren ladelokation) og en
    brændstofliste. Det er DEN kilde der afgør kategori-renhed — ikke navnet:
    'CIRCLE K RECHARGE CITY' lyder som en ladehub men er siteType=ST med miles 95,
    miles Diesel og HVO100, mens 'CIRCLE K EV VTS VOJENS' er siteType=EV uden
    brændstof. En navnebaseret vurdering slettede 2026-09-08 den forkerte af de to.

    -> {navn_uppercase: {'id','siteType','fuels','har_braendstof'}}
    """
    h = _raw('https://www.circlek.dk/station-search').decode('utf-8', 'replace')
    i = h.find('"station_results"')
    if i < 0:
        raise RuntimeError('station_results ikke fundet i circlek.dk/station-search')
    j = h.index('{', i + len('"station_results"'))
    depth = 0; k = j; instr = False; esc = False
    while k < len(h):
        c = h[k]
        if instr:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': instr = False
        else:
            if c == '"': instr = True
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0: k += 1; break
        k += 1
    SR = json.loads(h[j:k])
    # 'EL Ladestander' og 'AdBlue pumpe' er ikke bilbrændstof
    IKKE_BRAENDSTOF = {'EU_EV_CHARGER', 'EU_ADBLUE', 'EL LADESTANDER', 'ADBLUE PUMPE'}
    out = {}
    for sid, v in SR.items():
        site = v.get('/sites/{siteId}') or {}
        fuels = v.get('/sites/{siteId}/fuels') or []
        names = [str(f.get('name') or f.get('fuelName') or f) for f in fuels] if isinstance(fuels, list) else []
        real = [n for n in names if n.upper() not in IKKE_BRAENDSTOF]
        nm = (site.get('name') or '').strip()
        if nm:
            out[nm.upper()] = {'id': sid, 'siteType': site.get('siteType'),
                              'fuels': names, 'har_braendstof': bool(real)}
    return out

# ---------------------------------------------------------------- Circle K / Ingo
def circlek():
    """circlek.dk/stations er en HTML-liste med /station/<slug>-links.
    ingo-* slugs = Ingo, resten Circle K. Koordinater findes ikke i listen —
    de hentes pr. station, så denne bruges KUN til at opdage nye/lukkede slugs."""
    html = _raw('https://www.circlek.dk/stations').decode('utf-8', 'replace')
    slugs = sorted(set(re.findall(r'/station/([a-z0-9\-]+)', html)))
    return [{'brand': 'Ingo' if s.startswith('ingo-') else 'Circle K', 'slug': s} for s in slugs]

if __name__ == '__main__':
    for fn in (clever, ionity, goon):
        try:
            r = fn(); print(f"{fn.__name__:9} {len(r):4} rækker   fx {r[0] if r else '-'}")
        except Exception as e:
            print(f"{fn.__name__:9} FEJL: {type(e).__name__}: {e}")
    try:
        r = circlek()
        import collections
        print(f"circlek   {len(r):4} slugs   {collections.Counter(x['brand'] for x in r).most_common()}")
    except Exception as e:
        print(f"circlek   FEJL: {type(e).__name__}: {e}")
