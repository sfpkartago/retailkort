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

def ok_chargers(floor=250, ceiling=500):
    """OK's ladenetværk. Endpointet i REFRESH.md (GET /api/v2/clusters) er død;
    det hedder nu POST /api/v2/clusters/search — men DEN har ingen effekt.
    POST /api/v2/locations/nearby har til gengæld et 'power'-felt, og ét kald
    med distanceM=300 km fra Danmarks midte henter alle ~1.450 lokationer.
    locationSources=['OK'] holder roaming-partnere ude.

    ceiling=500 følger validate.py's regel. Det udelader netop 'OK Truck Korsør,
    Storebæltsvej' (1000 kW) — et megawatt-anlæg til lastbiler."""
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
GOON_CATS = {'goon': "Go'on", 'goon, kombi': "Go'on", 'lavpris': 'Lavpris'}

def goon():
    """Go'on-kortets pins. Kategorierne 'goon'+'goon, kombi' = Go'on,
    'lavpris' = Lavpris. UDELADT: 'goon-truck' og 'partner' (YX) — begge er
    ren truck-diesel (ingen benzin, truck-piktogram), jf. designreglen."""
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
