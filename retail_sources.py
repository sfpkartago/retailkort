#!/usr/bin/env python3
"""
retail_sources.py — hentere for de 52 retailkaeder i dagligvarer/udvalgsvarer/
pladskraevende-lagene. Sidestykke til sources.py, som kun daekker tank og ladere.

HVORFOR: kilderne til 6.488 af 9.954 raekker fandtes indtil nu KUN som prosa i
REFRESH_LOG.md. Uden kode kan retail-data ikke genopfriskes maskinelt.

Hver hente-funktion returnerer en liste af dicts i SAMME format som sources.py:
    {'brand','name','street','postnr','by','lat','lon'}
Adresserne er kildens raa tekst — de normaliseres mod DAWA (se dawa.py) FOER de
skrives til CSV. Hvor kilden mangler koordinat eller postnummer staar feltet tomt
(hhv. None og ''), og DAWA maa udfylde det; det er noteret i den enkelte docstring.

KATEGORI pr. maerke staar i KATEGORI nedenfor (planlovens § 5 n, stk. 1, nr. 3 som
laest 2026-09-11: moebler hoerer i UDVALGSVARER, apotek og Matas i DAGLIGVARER).

FAELDER DER GAELDER HELE FILEN
  1. Brug IKKE re.escape() paa maerkenavne i Overpass-forespoergsler — den
     escaper mellemrum og & i Python 3.9 og giver 0 traeffere.
  2. Et tomt svar fra Overpass eller en 200 med tom liste betyder IKKE at kaeden
     ikke findes; tjenesten svarer 200 naar den timer ud internt. Proev et andet
     spejl. Samme for DAWA-datavask: hoejst 8 traade.
  3. Kaeder uden samlet liste hentes side-for-side (Matas 266 sider, jem & fix
     139, JYSK 117, Toejeksperten 106, Thiele 83, Synoptik 69, Bygma 66,
     Silvan 49, ILVA 40, IKEA 12) — ca. 950 HTTP-kald, som _pages() koerer med
     8 traade. Hele proben tager under et minut. _pages() har et `limit` til
     stikproever, hvis en enkelt kaede skal fejlfindes.
  4. ETIK: thansen.dk og normalstores.com forbyder eksplicit ClaudeBot i
     robots.txt; cvrapi.dk har 'User-agent: * / Disallow: /'. Kontrolleret
     15-09-2026. (flyingtiger.com og bluebay-marine.dk stod tidligere paa
     listen ved en FEJL — begge siger 'User-agent: ClaudeBot / Allow: /'.)
     De tre foerstnaevnte
     ClaudeBot i robots.txt og maa KUN hentes fra OSM (sources.osm_brand).
     jemogfix.dk naevner ogsaa ClaudeBot, men dens gruppe forbyder kun
     /soeg/ og /webshop/checkout/ — butikssiderne er tilladte.

Status pr. 2026-09-11 (alle 27 probet, se __main__ — 4.822 raekker, ~75 sek.):
  coop 875 · netto 584 · apoteker 559 · dagrofa 491 · rema 437 · matas 265
  lidl 171 · imerco 165 · jemogfix 139 · sport24 122 · jysk 117 · bogide 108
  toejeksperten 106 · synoptik 99 · thiele 82 · stark 81 · xlbyg 73 · bygma 64
  kopkande 52 · silvan 49 · davidsen 47 · ilva 40 · powerdk 31 · bauhaus 19
  loevbjerg 18 · plantorama 16 · ikea 12
  Antallene stemmer med CSV-erne paa naer smaa afvigelser, der alle er
  nyaabninger eller sammenlaegninger — se den enkelte docstring.
  ✗ Elgiganten, H&M, Zara, Louis Nielsen, Normal, Flying Tiger, Intersport,
    Harald Nyborg, Sengespecialisten, BoConcept, Salling/foetex/Bilka og
    bil-/have-/lystbaadsforhandlere har INGEN parser her — de kommer fra OSM
    (sources.osm_brand) eller er bag bot-beskyttelse. Se NOTER_UDEN_PARSER.
"""
import concurrent.futures as _cf
import gzip
import html as _html
import json
import re
import urllib.parse
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
      'Accept-Encoding': 'gzip'}

# Maerke -> kortlag. Bruges af apply_refresh.py til at vaelge CSV-fil.
KATEGORI = {
    # dagligvarer (§ 5 n: varer til loebende forbrug + personlig pleje)
    'Netto': 'dagligvarer', 'Apotek': 'dagligvarer', 'Apoteksudsalg': 'dagligvarer',
    'REMA 1000': 'dagligvarer', 'Coop 365discount': 'dagligvarer',
    'Brugsen': 'dagligvarer', 'SuperBrugsen': 'dagligvarer', 'Kvickly': 'dagligvarer',
    'Matas': 'dagligvarer', 'Lidl': 'dagligvarer', 'MENY': 'dagligvarer',
    'SPAR': 'dagligvarer', 'Min Købmand': 'dagligvarer', 'Let-Køb': 'dagligvarer',
    'Løvbjerg': 'dagligvarer',
    # udvalgsvarer (inkl. moebler, jf. VEJ 9290/2010)
    'Imerco': 'udvalgsvarer', 'Imerco Home': 'udvalgsvarer', 'JYSK': 'udvalgsvarer',
    'Sport 24': 'udvalgsvarer', 'Sport 24 Outlet': 'udvalgsvarer',
    'Bog & idé': 'udvalgsvarer', 'Tøjeksperten': 'udvalgsvarer',
    'Synoptik': 'udvalgsvarer', 'Thiele': 'udvalgsvarer', 'Kop & Kande': 'udvalgsvarer',
    'ILVA': 'udvalgsvarer', 'POWER': 'udvalgsvarer', 'IKEA': 'udvalgsvarer',
    'IKEA bestillingssted': 'udvalgsvarer',
    # pladskraevende (byggematerialer, toemmer, planter, havebrugsvarer)
    'STARK': 'pladskraevende', 'XL-BYG': 'pladskraevende', 'Bygma': 'pladskraevende',
    'jem & fix': 'pladskraevende', 'Davidsen': 'pladskraevende',
    'Silvan': 'pladskraevende', 'BAUHAUS': 'pladskraevende',
    'Plantorama': 'pladskraevende',
}

NOTER_UDEN_PARSER = {
    'Elgiganten': 'Vercel bot-beskyttelse — OSM',
    'H&M / H&M HOME': 'Akamai, selv robots.txt giver 403 — OSM',
    'Zara': 'bot-beskyttelse — OSM (kun 2 fundet, underrepraesenteret)',
    'Louis Nielsen': 'Cloudflare — OSM (44 mod forventede ~95)',
    'Normal': 'normalstores.com forbyder ClaudeBot — KUN OSM (165)',
    'Flying Tiger Copenhagen': 'ingen aaben butiksliste — OSM (robots.txt TILLADER ClaudeBot)',
    'Harald Nyborg / Intersport / Sengespecialisten / BoConcept': 'ingen aaben kilde fundet — OSM',
    'føtex, føtex food, Bilka, Salling': 'api.sallinggroup.com/v2/stores loeser alle fire '
        'i ét kald, men kraever gratis token fra developer.sallinggroup.com; '
        'indtil da OSM. OSM har desuden 86 "føtex Slagter", 35 "føtex Bagerudsalg" '
        'og 27 "føtex Bager" som er AFDELINGER, ikke butikker — frasortér dem.',
    '7-Eleven, Lagkagehuset': '7-Eleven fra OSM; Lagkagehuset har sources.lagkagehuset()',
    'Bilforhandler / Havecenter / Lystbådsforhandler / Campingvognsforhandler':
        'der findes intet samlet register — OSM shop=car / garden_centre / boat / caravan. '
        'shop=car_repair og car_parts er IKKE detailhandel og skal frasorteres.',
}

# ---------------------------------------------------------------- HTTP-hjaelpere
def _raw(url, timeout=90, data=None, headers=None, method=None):
    h = dict(UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            b = gzip.decompress(b)
        return b

def _text(url, timeout=90, **kw):
    return _raw(url, timeout, **kw).decode('utf-8', 'replace')

def _json(url, timeout=90, **kw):
    return json.loads(_raw(url, timeout, **kw))

def _post_form(url, body, timeout=90):
    """POST application/x-www-form-urlencoded -> JSON."""
    return json.loads(_raw(url, timeout, data=body.encode(),
                           headers={'Content-Type': 'application/x-www-form-urlencoded'},
                           method='POST'))

def _post_json(url, obj, timeout=90, headers=None):
    h = {'Content-Type': 'application/json'}
    if headers:
        h.update(headers)
    return json.loads(_raw(url, timeout, data=json.dumps(obj).encode(),
                           headers=h, method='POST'))

def _f(v):
    """Tal eller None. Kildernes koordinater er tekst lige saa ofte som tal."""
    try:
        return round(float(str(v).strip()), 6)
    except (TypeError, ValueError):
        return None

# Danmark inkl. Bornholm. Bruges til at fange kilder der bytter lat/lon om.
DK_LAT = (54.4, 57.9)
DK_LON = (7.9, 15.3)

def _dk_koord(lat, lon):
    """Sanity-tjek et koordinatpar mod Danmarks udstraekning.

    Tre ting gaar galt i kilderne, og alle tre fanges her:
      * 0,0 ("Null Island") — Coop har 24 butikker med Location [0,0], typisk
        faengselsbutikker og bageriudsalg. De skal have None, saa DAWA geokoder
        dem fra adressen i stedet for at saette en nal i Guineabugten.
      * byttet raekkefoelge — Netto leverer coordinates som [lon, lat], men ÉN
        butik (Frederiksborgvej 71) kommer som [lat, lon]. Plantoramas GraphQL
        bytter dem om paa ALLE 16.
      * tekst i stedet for tal.
    -> (lat, lon) eller (None, None). Bytter KUN naar det byttede par er
    gyldigt og det oprindelige ikke er — ellers roeres der ikke ved noget."""
    a, b = _f(lat), _f(lon)
    ok = lambda y, x: (y is not None and x is not None
                       and DK_LAT[0] <= y <= DK_LAT[1] and DK_LON[0] <= x <= DK_LON[1])
    if ok(a, b):
        return a, b
    if ok(b, a):
        return b, a
    return None, None

def _map(fn, seq, workers=8):
    """Parallel hentning. 8 traade — 15 udtoemte DAWA-datavask 2026-09-10."""
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, seq))

# ---------------------------------------------------------------- parse-hjaelpere
def _balanced(text, start, open_c='{', close_c='}'):
    """Klip det balancerede JSON-udtryk der begynder ved text[start].
    Strengbevidst — en '}' inde i en streng afslutter ikke objektet."""
    d = 0
    i = start
    instr = esc = False
    while i < len(text):
        c = text[i]
        if instr:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c == open_c:
                d += 1
            elif c == close_c:
                d -= 1
                if d == 0:
                    return text[start:i + 1]
        i += 1
    raise ValueError('ubalanceret JSON fra position %d' % start)

def _json_after(text, key, open_c='{'):
    """Find "<key>" i text og parse det JSON-udtryk der foelger efter kolon."""
    m = re.search(r'"%s"\s*:\s*' % re.escape(key), text)
    if not m:
        raise ValueError('noeglen "%s" findes ikke i svaret' % key)
    i = text.index(open_c, m.end())
    return json.loads(_balanced(text, i, open_c, ']' if open_c == '[' else '}'))

def _next_data(h):
    """Next.js pages-router: <script id="__NEXT_DATA__">."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    if not m:
        raise ValueError('__NEXT_DATA__ ikke fundet')
    return json.loads(m.group(1))

def _flight(h):
    """Next.js app-router (13+): RSC-payloaden ligger i self.__next_f.push([1,"..."]).
    Hver chunk er en JSON-streng; de skal samles FOER de parses, fordi et objekt
    godt kan vaere delt over to chunks."""
    out = []
    for c in re.findall(r'self\.__next_f\.push\(\[1,(".*?")\]\)', h, re.S):
        try:
            out.append(json.loads(c))
        except ValueError:
            pass
    return ''.join(out)

def _find_key(o, key):
    """Alle vaerdier for `key` et vilkaarligt sted i en JSON-traestruktur."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            yield from _find_key(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from _find_key(v, key)

def _ldjson(h):
    """Alle schema.org-objekter i <script type="application/ld+json">.
    Udpakker baade lister og @graph — ILVA lagrer sin butik i et @graph.

    FAELDE: Bygma udstiller UGYLDIG JSON-LD paa 13 af 66 butikssider, paa to
    maader: manglende komma mellem to elementer i openingHoursSpecification
    ("}\n{" i stedet for "},\n{"), og efterstillet komma foer ] eller }
    ("Thursday",\n]). En streng json.loads springer de sider over, og man faar
    52 i stedet for 64 butikker. Derfor ét lempeligt reparationsforsoeg, og
    KUN naar den raa parse fejler."""
    out = []
    for b in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', h, re.S):
        b = b.strip()
        try:
            d = json.loads(b)
        except ValueError:
            lap = re.sub(r'\}\s*\{', '},{', b)
            lap = re.sub(r',\s*([\]}])', r'\1', lap)
            try:
                d = json.loads(lap)
            except ValueError:
                # sidste udvej: smid aabningstiderne vaek. Det er dem der er
                # oedelagte (manglende komma, manglende [), og vi bruger dem
                # ikke — navn, adresse og geo staar foer dem.
                k = lap.find('"openingHoursSpecification"')
                if k < 0:
                    continue
                try:
                    d = json.loads(lap[:lap.rindex(',', 0, k)] + '}')
                except ValueError:
                    continue
        stak = d if isinstance(d, list) else [d]
        while stak:
            o = stak.pop()
            if not isinstance(o, dict):
                continue
            if isinstance(o.get('@graph'), list):
                stak.extend(x for x in o['@graph'] if isinstance(x, dict))
                continue
            out.append(o)
    return out

def _ld_store(h, brand, name_fallback=''):
    """Traek ét butiks-dict ud af en sides JSON-LD. Kraever address; geo maa mangle
    (jem & fix har fx adresse i LD men koordinat i et Google Maps-link)."""
    for o in _ldjson(h):
        a = o.get('address')
        if not isinstance(a, dict) or not a.get('streetAddress'):
            continue
        if str(o.get('@type', '')) in ('Organization', 'WebSite', 'BreadcrumbList'):
            continue
        g = o.get('geo') or {}
        return {'brand': brand, 'name': (o.get('name') or name_fallback).strip(),
                'street': (a.get('streetAddress') or '').strip(),
                'postnr': str(a.get('postalCode') or '').strip(),
                'by': (a.get('addressLocality') or '').strip(),
                'lat': _f(g.get('latitude')), 'lon': _f(g.get('longitude'))}
    return None

def _sitemap(url, timeout=90, _dybde=0, _set=None):
    """Alle <loc> i et sitemap; folger sitemapindex rekursivt og pakker .gz ud
    (Plantorama udstiller kun gzippede delsitemaps). Relative <loc> i et index
    gores absolutte — ellers fejler Plantorama med 'unknown url type'."""
    seen = _set if _set is not None else set()
    if url in seen or _dybde > 2:
        return []
    seen.add(url)
    b = _raw(url, timeout)
    if b[:2] == b'\x1f\x8b':
        b = gzip.decompress(b)
    x = b.decode('utf-8', 'replace')
    locs = [s.strip() for s in re.findall(r'<loc>\s*([^<]+?)\s*</loc>', x)]
    if '<sitemapindex' in x:
        out = []
        for s in locs:
            out += _sitemap(urllib.parse.urljoin(url, s), timeout, _dybde + 1, seen)
        return out
    return locs

def _pages(urls, parse, limit=None, workers=8):
    """Hent en liste af butikssider parallelt og saml de parsede raekker.
    `limit` er til probe-brug: hent kun de foerste N sider."""
    ws = urls[:limit] if limit else urls
    def one(u):
        try:
            return parse(_text(u, 60), u)
        except Exception:
            return None
    return [r for r in _map(one, ws, workers) if r]

# ================================================================ DAGLIGVARER
COOP_BRANDS = {'Coop365': 'Coop 365discount', "Dagli'Brugsen": 'Brugsen',
               'SuperBrugsen': 'SuperBrugsen', 'Kvickly': 'Kvickly'}

def coop():
    """Alle Coops kaeder i ÉT POST-kald.
    POST coop.dk/umbraco/api/Chains/GetAllStores (form-body, ikke JSON):
        pageId=19807&chainsToShowStoresFrom=Alle&hideClosedStores=false
    -> 902 poster pr. 2026-09-11. Koordinat i Location = [lon, lat] — BEMAERK
    raekkefoelgen, den er omvendt af alle andre kilder her.

    FAELDER:
      * 10 butikker har Location [0.0, 0.0] — faengselsbutikker, bageriudsalg
        og et par nyaabninger. _dk_koord() sender dem videre som None, saa
        DAWA geokoder dem fra adressen. Skrives de raat til CSV, lander de i
        Guineabugten.
      * RetailGroupName 'Grønland' (17), 'FK' (Faeroerne, 6), 'FaktaGermany' (3)
        og 'Coop.dk' (webshoppen, 1) er IKKE danske butikker og frasorteres.
      * Dagli'Brugsen og Brugsen er SAMME kaede — Coop rebrandede, men API'et
        bruger stadig det gamle navn. Den hedder 'Brugsen' i vores data og
        taelles ÉN gang (271 raekker). SuperBrugsen er en anden kaede (221).
    Forventet: 875 danske raekker = Coop365 320 + Brugsen 271 + SuperBrugsen 221
    + Kvickly 63."""
    d = _post_form('https://coop.dk/umbraco/api/Chains/GetAllStores',
                   'pageId=19807&chainsToShowStoresFrom=Alle&hideClosedStores=false')
    out = []
    for x in d:
        brand = COOP_BRANDS.get((x.get('RetailGroupName') or '').strip())
        if not brand:
            continue
        loc = (x.get('Location') or [None, None]) + [None, None]
        lat, lon = _dk_koord(loc[1], loc[0])
        out.append({'brand': brand, 'name': (x.get('Name') or '').strip(),
                    'street': (x.get('Address') or '').strip(),
                    'postnr': str(x.get('Zipcode') or ''), 'by': (x.get('City') or '').strip(),
                    'lat': lat, 'lon': lon})
    return out

def netto():
    """netto.dk/find-butik/ er server-renderet Next.js (app-router). Butikslisten
    ligger i RSC-payloaden under noeglen "initialStores" — IKKE i __NEXT_DATA__,
    og IKKE i et API vi kan kalde direkte.

    FAELDE: payloaden er dobbelt-escapet (\\" i HTML'en). _flight() samler og
    afescaper chunkene; derefter kan _json_after finde noeglen. Koordinat er
    coordinates = [lon, lat] — omvendt raekkefoelge, som hos Coop. ÉN butik
    (Frederiksborgvej 71, 2400 Koebenhavn NV) kommer dog som [lat, lon];
    _dk_koord() retter den.
    Forventet: 584."""
    raw = _flight(_text('https://netto.dk/find-butik/', 120))
    arr = _json_after(raw, 'initialStores', '[')
    out = []
    for x in arr:
        a = x.get('address') or {}
        c = (x.get('coordinates') or []) + [None, None]
        lat, lon = _dk_koord(c[1], c[0])
        # Kilden HAR butiksnavne ("Netto Oebro", "Netto Chr. Moellers Plads").
        # Parseren byggede foer navnet af gade+by, saa popuppen viste adressen to
        # gange og butikkens eget navn gik tabt paa alle 582 raekker.
        out.append({'brand': 'Netto',
                    'name': (x.get('name') or '').strip() or
                            ((a.get('street') or '') + ', ' + (a.get('city') or '')).strip(', '),
                    'street': (a.get('street') or '').strip(),
                    'postnr': str(a.get('zip') or ''), 'by': (a.get('city') or '').strip(),
                    'lat': lat, 'lon': lon})
    return out

def seven_eleven():
    """7-Eleven. /find-butik/ er server-renderet HTML: hver butik er en
    <div class="store-listing" data-latitude=".." data-longitude=".."> med <h3>navn</h3>
    og <address>gade<br/>postnr by</address>.

    FAELDER:
      * <address> er HTML-escapet (K&#xF8;benhavn) — skal unescapes.
      * <h3> er ofte "Gade nr, BY" og altsaa ikke et rigtigt butiksnavn; brug det
        som det er, men saet "7-Eleven " foran naar det ikke allerede staar der.
      * Laget kom tidligere fra OSM. Antallet stemte (172=172), men populationen var
        en anden: 8 af kaedens butikker manglede og 8 CSV-raekker fandtes ikke hos
        kaeden. Derfor denne henter — afstem raekke for raekke, ikke paa totalen.
    Forventet: 172."""
    h = _text('https://www.7-eleven.dk/find-butik/', 120)
    out = []
    for m in re.finditer(r'class="store-listing"[^>]*data-latitude="([-\d.]+)"[^>]*'
                         r'data-longitude="([-\d.]+)"(.*?)</address>', h, re.S):
        lat, lon, blok = _f(m.group(1)), _f(m.group(2)), m.group(3)
        h3 = re.search(r'<h3>(.*?)</h3>', blok, re.S)
        ad = re.search(r'<address>(.*?)$', blok, re.S)
        if not ad:
            continue
        linjer = [_html.unescape(re.sub(r'<[^>]+>', '', x)).strip()
                  for x in re.split(r'<br\s*/?>', ad.group(1))]
        linjer = [x for x in linjer if x]
        gade = linjer[0] if linjer else ''
        pnby = re.match(r'(\d{4})\s+(.*)$', linjer[1]) if len(linjer) > 1 else None
        navn = _html.unescape(re.sub(r'<[^>]+>', '', h3.group(1))).strip() if h3 else ''
        # <h3> er som regel selve adressen ("Torvegade 49, KBH K"). Er den blot gaden
        # igen, saa brug byen i stedet — ellers viser popuppen adressen to gange,
        # praecis som Netto-raekkerne gjorde.
        # <h3> er som regel adressen plus en forkortet by ("Torvegade 49, KBH K").
        # Kaeden har ikke rigtige butiksnavne, saa gaden ER det mest sigende navn —
        # men by-halen skal vaek, ellers staar byen to gange i popuppen.
        kerne = re.sub(r'^7-?eleven\s*', '', navn, flags=re.I).strip()
        kerne = re.sub(r',\s*[^,]*$', '', kerne).strip() if ',' in kerne else kerne
        navn = ('7-Eleven ' + (kerne or gade)).strip()
        out.append({'brand': '7-Eleven', 'name': navn or '7-Eleven',
                    'street': gade, 'postnr': pnby.group(1) if pnby else '',
                    'by': pnby.group(2).strip() if pnby else '', 'lat': lat, 'lon': lon})
    return out

def rema():
    """REMA 1000's app-API: cphapp.rema1000.dk/api/v3/stores?per_page=1000.
    FAELDE: v1 og v2 svarer 405 Method Not Allowed — kun v3 virker. Uden
    per_page kommer der én side. Koordinat i location.latitude/longitude.
    `address` indeholder ofte centernavn efter et komma ("Reberbanen 7 st.,
    Cimbria Parken") — behold kun foerste led som gade.
    Forventet: 437."""
    d = _json('https://cphapp.rema1000.dk/api/v3/stores?per_page=1000')
    out = []
    for x in d.get('data', []):
        loc = x.get('location') or {}
        out.append({'brand': 'REMA 1000', 'name': (x.get('name') or '').strip(),
                    'street': (x.get('address') or '').split(',')[0].strip(),
                    'postnr': str(x.get('postal_code') or ''),
                    'by': (x.get('city') or '').strip(),
                    'lat': _f(loc.get('latitude')), 'lon': _f(loc.get('longitude'))})
    return out

DAGROFA_SITES = [('MENY', 'https://api.meny.dk'),
                 ('SPAR', 'https://api.spar.dk'),
                 ('Min Købmand', 'https://api.xn--minkbmand-o8a.dk'),
                 ('Let-Køb', 'https://api.xn--letkb-yua.dk')]

def dagrofa():
    """Dagrofas fire kaeder koerer paa SAMME Drupal JSON:API — én parser, fire
    kaeder. Sti: /api/node/store paa hvert domaene (IDN-domaenerne er
    punycode: api.xn--minkbmand-o8a.dk = api.minkøbmand.dk,
    api.xn--letkb-yua.dk = api.letkøb.dk).

    FAELDER:
      * page[limit] er capped paa 50 — der SKAL pagineres. Folg links.next;
        den URL kommer tilbage som http:// og med et stort include=, som vi
        skriver om til https og fjerner (include henter billeder og gor svaret
        6x stoerre uden at tilfoeje adresser).
      * En side med limit=50 kan give 47-49 poster (upublicerede noder).
      * Adresse i attributes.field_address, koordinat i field_location.lat/lon.
      * Én Let-Koeb-butik mangler koordinat i kilden og skal geokodes fra
        adressen med DAWA.
    Forventet: 491 i alt (Min Købmand 167, SPAR 138, MENY 116, Let-Køb 70)."""
    out = []
    for brand, base in DAGROFA_SITES:
        url = base + '/api/node/store?page%5Blimit%5D=50'
        while url:
            d = _json(url)
            for x in d.get('data', []):
                a = x.get('attributes') or {}
                ad = a.get('field_address') or {}
                lo = a.get('field_location') or {}
                if (ad.get('country_code') or 'DK') != 'DK':
                    continue
                out.append({'brand': brand, 'name': (a.get('title') or '').strip(),
                            'street': (ad.get('address_line1') or '').strip(),
                            'postnr': str(ad.get('postal_code') or ''),
                            'by': (ad.get('locality') or '').strip(),
                            'lat': _f(lo.get('lat')), 'lon': _f(lo.get('lon'))})
            nxt = ((d.get('links') or {}).get('next') or {}).get('href')
            url = re.sub(r'&include=[^&]*', '', nxt.replace('http://', 'https://')) if nxt else None
    return out

LIDL_KEY = 'KxboQtt40BG4VpBL16IhaRd2CXh0QbAc'

def lidl():
    """Lidl via Schwarz-koncernens API. Kraever header x-apikey (noeglen ligger
    aabent i lidl.dk's frontend-bundle).

    FAELDER:
      * Stien er live.api.schwarz/odj/stores-api/v2/myapi/stores-frontend/stores
        — basen UDEN /stores svarer 404 "Invalid Path", og /stores/ med
        afsluttende skraastreg ligeledes.
      * Filtret heder country_code i snake_case; countryCode giver 404.
      * limit er cappet paa 250 (meta.total siger hvor mange der er i alt).
      * Data i items; koordinat i address.latitude/longitude — ikke i roden.
    Forventet: 171."""
    d = _json('https://live.api.schwarz/odj/stores-api/v2/myapi/stores-frontend/'
              'stores?country_code=DK&limit=250', headers={'x-apikey': LIDL_KEY})
    out = []
    for x in d.get('items', []):
        a = x.get('address') or {}
        gade = ' '.join(p for p in (a.get('streetName'), a.get('streetNumber')) if p)
        out.append({'brand': 'Lidl', 'name': (x.get('storeName') or '').strip(),
                    'street': gade.strip(), 'postnr': str(a.get('zip') or ''),
                    'by': (a.get('city') or '').strip(),
                    'lat': _f(a.get('latitude')), 'lon': _f(a.get('longitude'))})
    return out

def apoteker():
    """Danmarks Apotekerforening: apoteket.dk/Pharmacy/GetAllPharmacies -> 559
    enheder i data-listen.

    FAELDE: /GetAllPharmaciesCount svarer 540, ikke 559. Forskellen er ikke en
    fejl: 19 af enhederne har pharmacyNumber med suffiks -A1..-A3 og er
    APOTEKSUDSALG — en filial, ikke et apotek. Taellingen daekker kun apoteker.
    Udsalgene faar derfor deres eget maerke 'Apoteksudsalg', saa designreglen om
    korrekt brand-attribution holder.
    Forventet: 540 Apotek + 19 Apoteksudsalg."""
    d = _json('https://www.apoteket.dk/Pharmacy/GetAllPharmacies')
    out = []
    for x in d.get('data', []):
        nr = str(x.get('pharmacyNumber') or '')
        udsalg = bool(re.search(r'-A\d$', nr))
        out.append({'brand': 'Apoteksudsalg' if udsalg else 'Apotek',
                    'name': (x.get('name') or '').strip(),
                    'street': (x.get('street') or '').strip(),
                    'postnr': str(x.get('zipCode') or ''),
                    'by': (x.get('city') or '').strip(),
                    'lat': _f(x.get('latitude')), 'lon': _f(x.get('longitude'))})
    return out

def matas():
    """Matas har intet butiks-API, men /find-butik lister alle butiks-slugs som
    /find-butik/<by>---<gade>, og HVER butiksside har schema.org-JSON-LD af typen
    HealthAndBeautyBusiness med baade address og geo.

    FAELDER:
      * Slug-formen er /find-butik/<slug>; /butik/<slug> (som ogsaa optraeder i
        HTML'en) svarer 400.
      * /butiksoversigt svarer 404 — indekset ER /find-butik.
      * 266 sider = 266 kald. Én af dem leverer ingen JSON-LD, saa udbyttet
        er 265; det er ikke en parserfejl.
    Forventet: 265 af 266 slugs (263 i CSV)."""
    h = _text('https://www.matas.dk/find-butik', 90)
    slugs = sorted(set(re.findall(r'"(/find-butik/[^"/]+)"', h)))
    urls = ['https://www.matas.dk' + s for s in slugs]
    return _pages(urls, lambda t, u: _ld_store(t, 'Matas'))

def loevbjerg():
    """Loevbjerg. Butikslisten ligger som en almindelig JS-literal
    `var locations = [...]` paa /butikker-aabningstider (Drupal-site, ingen API).
    Felterne heder lat/long (ikke lon!) og er TEKST. Forventet: 18."""
    h = _text('https://www.lovbjerg.dk/butikker-aabningstider', 60)
    i = h.index('[', h.index('var locations'))
    arr = json.loads(_balanced(h, i, '[', ']'))
    return [{'brand': 'Løvbjerg', 'name': (x.get('title') or '').strip(),
             'street': (x.get('address') or '').strip(),
             'postnr': str(x.get('zip') or ''), 'by': (x.get('city') or '').strip(),
             'lat': _f(x.get('lat')), 'lon': _f(x.get('long'))} for x in arr]

# ================================================================ UDVALGSVARER
def imerco():
    """Imerco. ENHVER butiksside (type p71StoreDetailsPage) har hele
    butikslisten indlejret under noeglen "storeList" -> data[]. Der er altsaa
    ingen grund til at hente 165 sider — ét kald raekker.

    FAELDER:
      * storeList._count siger 200; det er sidestoerrelsen, ikke antallet.
        len(data) er 165.
      * name er "Imerco Home <by>" for Home-butikkerne. Vi beholder ét maerke
        'Imerco' (som i CSV'en) og lader navnet baere Home-varianten.
      * /butikker svarer 404 — stien er /find-imerco/<slug>.
    Forventet: 165."""
    h = _text('https://www.imerco.dk/find-imerco/imerco-aarhus-store-torv', 90)
    L = _json_after(h, 'storeList')['data']
    return [{'brand': 'Imerco', 'name': (x.get('name') or '').strip(),
             'street': (x.get('address1') or '').strip(),
             'postnr': str(x.get('postalCode') or ''), 'by': (x.get('city') or '').strip(),
             'lat': _f(x.get('latitude')), 'lon': _f(x.get('longitude'))}
            for x in L if (x.get('countryCode') or 'DK') == 'DK']

def kopkande():
    """Kop & Kande koerer samme Umbraco-platform som Imerco (samme ejer), men
    noeglen heder "stateCmsStores" og ligger paa /find-butik.

    FAELDER:
      * Domaenet er kop-kande.dk. kopkande.dk og kopogkande.dk findes ikke /
        redirecter; www.kopkande.dk har intet DNS.
      * /butikker svarer 404 — stien er /find-butik.
      * latitude/longitude er TEKST, og hver post har et description-felt med
        HTML der indeholder baade { og } — derfor skal udklippet vaere
        strengbevidst (_balanced), ikke et regex.
      * `country` er fritekst og staves TRE maader for Danmark: 'Danmark' (50),
        'Denmark' (1) og 'DK' (1). Et filter paa 'Danmark' alene taber to
        butikker. De 4 oevrige poster er Groenland, Island, Faeroerne og Kina
        og SKAL ud.
    Forventet: 56 poster, hvoraf 52 danske."""
    h = _text('https://kop-kande.dk/find-butik', 90)
    L = _json_after(h, 'stateCmsStores', '[')
    return [{'brand': 'Kop & Kande', 'name': (x.get('storeName') or '').strip(),
             'street': (x.get('address') or '').strip(),
             'postnr': str(x.get('postalCode') or ''), 'by': (x.get('city') or '').strip(),
             'lat': _f(x.get('latitude')), 'lon': _f(x.get('longitude'))}
            for x in L
            if (x.get('country') or 'Danmark').strip().lower() in ('danmark', 'denmark', 'dk')]

def sport24():
    """Sport 24. /stores/ er Next.js pages-router; butikslisten ligger i
    __NEXT_DATA__ under "stores".

    FAELDER:
      * /butikker svarer 308 med tom body — stien er /stores/ MED skraastreg.
      * locationCoordinates er ÉN streng "lat,lon" — ikke to felter.
      * `type` skiller de to kaeder: 'Sport 24' (61), 'Sport 24 Outlet' (58) og
        3 kombinationsbutikker ('SPORT 24 & SPORT 24 OUTLET'). Vi bruger type
        som maerke, jf. designreglen om korrekt brand-attribution; de tre
        kombi-butikker faar 'Sport 24' (den primaere kaede paa adressen).
    Forventet: 122 (64 Sport 24 + 58 Sport 24 Outlet; 112 i CSV, hvor de to
    kaeder var slaaet sammen under ét maerke)."""
    d = _next_data(_text('https://www.sport24.dk/stores/', 90))
    L = next(x for x in _find_key(d, 'stores') if isinstance(x, list) and x
             and isinstance(x[0], dict) and 'street' in x[0])
    out = []
    for x in L:
        if not x.get('status'):
            continue
        t = (x.get('type') or 'Sport 24').strip()
        brand = 'Sport 24' if t.upper().startswith('SPORT 24 &') else t
        co = (x.get('locationCoordinates') or '').split(',')
        out.append({'brand': brand, 'name': ('Sport 24 ' + (x.get('name') or '')).strip(),
                    'street': (x.get('street') or '').strip(),
                    'postnr': str(x.get('zipcode') or ''), 'by': (x.get('city') or '').strip(),
                    'lat': _f(co[0]) if co else None,
                    'lon': _f(co[1]) if len(co) > 1 else None})
    return out

def bogide():
    """Bog & idé. Shopify-butik med Indeks Retails store-locator-app. Appen
    henter fra en app-proxy paa butikkens EGET domaene:
        /apps/indeks-store-locator/store-locator/locations
    (API_BASE_URL staar i store-locator.js paa cdn.shopify.com).

    FAELDER:
      * Domaenet er bog-ide.dk; bogogide.dk har intet DNS.
      * /butikker svarer 404 — locator-siden er /pages/find-butik.
      * Svaret er UTF-8 men serveres uden charset; afkod eksplicit.
      * coordinates.lat/lng (ikke lon).
    Forventet: 108."""
    d = _json('https://www.bog-ide.dk/apps/indeks-store-locator/store-locator/locations', 60)
    out = []
    for x in d.get('locations', []):
        a = x.get('address') or {}
        c = x.get('coordinates') or {}
        if (a.get('country') or 'Denmark') not in ('Denmark', 'Danmark', 'DK'):
            continue
        out.append({'brand': 'Bog & idé', 'name': (x.get('name') or '').strip(),
                    'street': (a.get('address1') or '').strip(),
                    'postnr': str(a.get('zip') or ''), 'by': (a.get('city') or '').strip(),
                    'lat': _f(c.get('lat')), 'lon': _f(c.get('lng'))})
    return out

def synoptik():
    """Synoptik. Der findes et api.synoptik.dk/stores, men det kan KUN slaa en
    enkelt butik op (/stores/<id>); GET /stores svarer "Cannot GET /stores".
    Indgangen er /butiksoversigt, der linker til ALLE butikker.

    FAELDER:
      * Oversigten linker TO slags URL'er: 14 by-sider (/butikker/<by>) for de
        store byer og 55 enkeltbutiks-sider (/butikker/<by>/<butik>). Man skal
        hente BEGGE slags. Et regex der kun tager /butikker/<noget> og kalder
        det en by-side giver 54 x 404, fordi de fleste byer ikke HAR en by-side.
      * By-siden har listen i initialProps.pageProps.stores; enkeltbutiks-siden
        har ÉN butik i initialProps.pageProps.storeData. Samme feltnavne
        (streetName, postalCode, town, lat, lon, code).
      * country 'GL' forekommer (Nuuk) og skal frasorteres.
      * De to slags sider overlapper — dedupliker paa `code`.
    Forventet: 99."""
    h = _text('https://www.synoptik.dk/butiksoversigt', 90)
    urls = sorted(set(re.findall(r'https://www\.synoptik\.dk/butikker/[^"\s<]+', h)))
    def one(u):
        try:
            d = _next_data(_text(u, 60))
        except Exception:
            return []
        ud = []
        for L in _find_key(d, 'stores'):
            if isinstance(L, list) and L and isinstance(L[0], dict) and 'streetName' in L[0]:
                ud += L
        for x in _find_key(d, 'storeData'):
            if isinstance(x, dict) and 'streetName' in x:
                ud.append(x)
        return ud
    ud, set_ = [], set()
    for L in _map(one, urls):
        for x in L:
            k = x.get('code') or (x.get('slug'), x.get('postalCode'))
            if k in set_ or (x.get('country') or 'DK') != 'DK':
                continue
            set_.add(k)
            ud.append({'brand': 'Synoptik', 'name': (x.get('name') or '').strip(),
                       'street': (x.get('streetName') or '').strip(),
                       'postnr': str(x.get('postalCode') or ''),
                       'by': (x.get('town') or '').strip(),
                       'lat': _f(x.get('lat')), 'lon': _f(x.get('lon'))})
    return ud

def thiele():
    """Thiele. Butikssiderne staar i /butikker-sitemap.xml (under
    sitemap_index.xml). Hver side har koordinat og adresse i et HTML-attribut:
        <div id="single-butik-map" data-butik='{"title":...,"lat":..,"lng":..}'>

    FAELDER:
      * JSON-LD paa siderne er tom (@type mangler) — brug data-butik.
      * address1 er ÉN streng "Jernbanegade 7, 6900, Skjern" (gade, postnr, by)
        — den skal splittes paa komma.
      * Sitemappet indeholder ogsaa 'thiele-ojenlaser-klinik', som er en klinik
        og ikke en optikerbutik. Den frasorteres.
    Forventet: 82 butikker (83 sider minus klinikken; 83 i CSV, som altsaa
    har klinikken med)."""
    urls = [u for u in _sitemap('https://www.thiele.dk/sitemap_index.xml')
            if re.search(r'/butikker/[^/]+/?$', u) and 'klinik' not in u]
    def parse(t, u):
        m = re.search(r"data-butik='(\{.*?\})'", t, re.S)
        if not m:
            return None
        b = json.loads(_html.unescape(m.group(1)))
        dele = [p.strip() for p in (b.get('address1') or '').split(',')]
        pn = next((p for p in dele if re.fullmatch(r'\d{4}', p)), '')
        return {'brand': 'Thiele', 'name': (b.get('title') or '').strip(),
                'street': dele[0] if dele else '', 'postnr': pn,
                'by': dele[-1] if len(dele) > 2 else '',
                'lat': _f(b.get('lat')), 'lon': _f(b.get('lng'))}
    return _pages(urls, parse)

def powerdk():
    """POWER. Rent JSON-API: www.power.dk/api/v2/stores — ingen noegle, ingen
    paginering, lat/longitude direkte i posten.

    FAELDER:
      * /butikker og /butikker/find svarer 500; find-butik-siden er en Angular-
        SPA uden data i HTML'en. API'et er den eneste kilde.
      * isDealer/isFlagship findes; alle 31 er pt. False/False.
    Forventet: 31 (30 i CSV)."""
    d = _json('https://www.power.dk/api/v2/stores', 60)
    return [{'brand': 'POWER', 'name': (x.get('name') or '').strip(),
             'street': (x.get('address') or '').strip(),
             'postnr': str(x.get('zipCode') or ''), 'by': (x.get('city') or '').strip(),
             'lat': _f(x.get('latitude')), 'lon': _f(x.get('longitude'))} for x in d]

def toejeksperten():
    """Toejeksperten. Butikssiderne staar i sitemappet /da-dk/sitemap/content
    (sitemap-INDEKSET er /da-dk/sitemap/root). Hver side er Next.js
    pages-router, og butikkens data ligger FLADT i __NEXT_DATA__ som
    storeName / address / zipcode / city / latitude / longitude / countryCode.

    FAELDER:
      * Siderne har OGSAA et meta.markup med LocalBusiness-JSON-LD, men det er
        null paa 2/3 af butikkerne (fx Aalborg Stc., Randers Storcenter,
        Esbjerg). En parser der laener sig paa markup faar kun ~35 af 105.
        Brug de flade felter.
      * Der findes ingen /butikker-oversigt med data — kun sitemappet.
    Forventet: 106."""
    urls = [u for u in _sitemap('https://www.toejeksperten.dk/da-dk/sitemap/root')
            if re.search(r'/butikker/.+', u)]
    def parse(t, u):
        d = _next_data(t)
        # find det objekt der HAR baade storeName og latitude
        stak = [d]
        while stak:
            o = stak.pop()
            if isinstance(o, dict):
                if 'storeName' in o and 'latitude' in o:
                    if (o.get('countryCode') or 'DK') != 'DK':
                        return None
                    return {'brand': 'Tøjeksperten', 'name': (o.get('storeName') or '').strip(),
                            'street': (o.get('address') or '').strip(),
                            'postnr': str(o.get('zipcode') or ''),
                            'by': (o.get('city') or '').strip(),
                            'lat': _f(o.get('latitude')), 'lon': _f(o.get('longitude'))}
                stak.extend(o.values())
            elif isinstance(o, list):
                stak.extend(o)
        return None
    return _pages(urls, parse)

def jysk():
    """JYSK. Butikssiderne staar i jysk.dk/sitemap.xml som
    /butikker-og-abningstider/<by>/<vej> (117 stk.). Hver side har JSON-LD af
    typen Store med address + geo.

    FAELDER:
      * Oversigtssiden findes i to stavemaader — /butikker-og-aabningstider
        (med dobbelt-a) og /butikker-og-abningstider. Kun den SIDSTE bruges
        som praefiks for butikssiderne.
      * RSC-payloaden (__next_f) indeholder INGEN koordinater; det er kun
        JSON-LD'en der har dem.
    Forventet: 117."""
    urls = [u for u in _sitemap('https://jysk.dk/sitemap.xml')
            if re.search(r'/butikker-og-abningstider/[^/]+/[^/]+$', u)]
    return _pages(urls, lambda t, u: _ld_store(t, 'JYSK'))

def ilva():
    """ILVA. Butikssiderne staar i ilva.dk/sitemap.xml som
    /om-ilva/aabningstider/<butik>/s-<id>/. Hver side har JSON-LD, men typen
    Store ligger inde i et @graph sammen med Organization og WebSite — en
    naiv "foerste ld+json"-parser rammer Organization og faar ingen adresse.
    _ldjson() pakker @graph ud.

    FAELDE: /butikker og /pages/butikker svarer 404/301 — der er ingen
    butiksoversigt paa et forudsigeligt sted; sitemappet er indgangen.
    Forventet: 40."""
    urls = [u for u in _sitemap('https://ilva.dk/sitemap.xml')
            if re.search(r'/om-ilva/aabningstider/[^/]+/s-\d+/?$', u)]
    return _pages(urls, lambda t, u: _ld_store(t, 'ILVA'))

IKEA_SIDER = ['https://www.ikea.com/dk/da/stores/%s/' % s for s in
              ('aalborg', 'aarhus', 'gentofte', 'kobenhavn', 'odense', 'taastrup')]

def ikea():
    """IKEA Danmark. /dk/da/stores/ lister de 6 varehuse, og
    /dk/da/stores/planning-studios/ lister de 6 'Plan and order points'.
    Hver side har et <script type="text/hydrate"> med data.storeConfig:
    name, lat, lng, address.street/zipCode/city.

    FAELDER:
      * /dk/da/meta-data/navigation/stores*.json (det gamle IKEA-API) svarer 404.
      * JSON-LD findes kun paa varehussiderne (FurnitureStore), ikke paa
        PAOP-siderne — brug storeConfig for begge.
      * window.ikea.geo i sidehovedet er BESOEGENDES position (55.67594,
        Koebenhavn), ikke butikkens. Den maa aldrig opfanges som koordinat.
      * Plan and order points er bestillingssteder, ikke varehuse, og faar
        eget maerke 'IKEA bestillingssted' (6 af de 12 lokationer).
    Forventet: 6 + 6."""
    ps = _text('https://www.ikea.com/dk/da/stores/planning-studios/', 90)
    paop = ['https://www.ikea.com' + p for p in
            sorted(set(re.findall(r'/dk/da/stores/planning-studios/[a-z0-9\-]+/', ps)))]
    def parse(t, u):
        for m in re.finditer(r'<script type="text/hydrate"[^>]*>', t):
            i = t.index('{', m.end())
            try:
                d = json.loads(_balanced(t, i))
            except ValueError:
                continue
            sc = next((x for x in _find_key(d, 'storeConfig') if isinstance(x, dict)), None)
            if not sc:
                continue
            a = sc.get('address') or {}
            nv = (sc.get('name') or '').strip()
            return {'brand': 'IKEA bestillingssted' if 'order point' in nv.lower() else 'IKEA',
                    'name': nv, 'street': (a.get('street') or '').strip(),
                    'postnr': str(a.get('zipCode') or ''), 'by': (a.get('city') or '').strip(),
                    'lat': _f(sc.get('lat')), 'lon': _f(sc.get('lng'))}
        return None
    return _pages(IKEA_SIDER + paop, parse)

# ================================================================ PLADSKRAEVENDE
def stark():
    """STARK. /forretninger har butikslisten i et Vue-attribut,
    HTML-entity-escapet: <delievery-and-shop v-bind:stores="[{&quot;StoreId&quot;...

    FAELDE: v-bind:stores optraeder TRE gange paa siden. To af dem har kun
    {StoreId, Name} (butiksvaelgeren i sidehovedet og -foden); kun ÉN har
    Address/ZipCode/Lat/Lon. Vaelg derfor den forekomst der har 'Lat' — ellers
    faar man 81 butikker uden adresse.
    Forventet: 81 (80 i CSV)."""
    h = _text('https://www.stark.dk/forretninger', 120)
    bedst = None
    for m in re.finditer(r'v-bind:stores="(\[.*?\])"', h, re.S):
        try:
            L = json.loads(_html.unescape(m.group(1)))
        except ValueError:
            continue
        if L and isinstance(L[0], dict) and 'Lat' in L[0]:
            bedst = L
    if bedst is None:
        raise RuntimeError('stark: ingen v-bind:stores med Lat paa /forretninger')
    return [{'brand': 'STARK', 'name': (x.get('Name') or '').strip(),
             'street': (x.get('Address') or '').strip(),
             'postnr': str(x.get('ZipCode') or ''), 'by': (x.get('City') or '').strip(),
             'lat': _f(x.get('Lat')), 'lon': _f(x.get('Lon'))} for x in bedst]

def xlbyg():
    """XL-BYG. /find-xl-byg er Next.js app-router; forhandlerlisten ligger i
    RSC-payloaden under "stores" med latitude/longitude/postalCode/address/city.

    FAELDER:
      * Stien er /find-xl-byg — /forhandlere og /find-forhandler svarer 404.
      * Payloaden er 2,8 MB; hent med gzip (UA ovenfor saetter Accept-Encoding).
      * Navnene indeholder forhandlerens EGET firmanavn
        ("XL-BYG Grønvold & Schou A/S Slagelse (G&S)") — det skal bevares,
        jf. designreglen om rigtige forretningsnavne.
    Forventet: 73 (65 i CSV)."""
    raw = _flight(_text('https://www.xl-byg.dk/find-xl-byg', 150))
    L = _json_after(raw, 'stores', '[')
    return [{'brand': 'XL-BYG', 'name': (x.get('name') or '').strip(),
             'street': (x.get('address') or '').strip(),
             'postnr': str(x.get('postalCode') or ''), 'by': (x.get('city') or '').strip(),
             'lat': _f(x.get('latitude')), 'lon': _f(x.get('longitude'))} for x in L]

def bygma():
    """Bygma. Butikssiderne staar i bygma.dk/sitemap.xml som /butikker/<slug>/.
    Hver side har JSON-LD af typen HardwareStore med address + geo.

    FAELDER:
      * /forhandlere svarer 301. Stien er /butikker/.
      * Sitemappet har BAADE /butikker/bygma-esbjerg-n/ og /butikker/esbjergn/
        for samme afdeling (gammel og ny slug) — dedupliker paa adresse, ellers
        faar man 66 raekker hvor der er 64 butikker.
      * Bygmas JSON-LD er UGYLDIG paa 13 sider (se _ldjson) og HELT TOM paa 2
        (Soroe og Nykoebing F). De to har en HTML-fallback nedenfor. Uden begge
        lapper giver kilden 52 i stedet for 64.
    Forventet: 64 efter dedublering (66 URL'er)."""
    urls = [u for u in _sitemap('https://www.bygma.dk/sitemap.xml')
            if re.search(r'/butikker/[^/]+/?$', u)]

    def parse(t, u):
        r = _ld_store(t, 'Bygma')
        if r:
            return r
        # to sider (Sorø, Nykøbing F) har en HELT TOM ld+json-blok. Deres
        # adresse staar i info-boksen og koordinaten i Google-rutelinket.
        nv = re.search(r'<h1[^>]*>([^<]+)</h1>', t)
        ad = re.search(r'<h4>Adresse- og kontaktinfo</h4>\s*<div>([^<]+)</div>\s*'
                       r'<div>(\d{4})\s+([^<]+)</div>', t, re.S)
        co = re.search(r'destination=(-?\d+\.\d+),(-?\d+\.\d+)', t)
        if not (nv and ad):
            return None
        return {'brand': 'Bygma',
                'name': _html.unescape(nv.group(1)).split(' - ')[0].strip(),
                'street': _html.unescape(ad.group(1)).strip(),
                'postnr': ad.group(2), 'by': _html.unescape(ad.group(3)).strip(),
                'lat': _f(co.group(1)) if co else None,
                'lon': _f(co.group(2)) if co else None}
    raekker = _pages(urls, parse)
    ud, set_ = [], set()
    for r in raekker:
        k = (r['street'].lower(), r['postnr'])
        if k in set_:
            continue
        set_.add(k)
        ud.append(r)
    return ud

def jemogfix():
    """jem & fix. Butikssiderne staar i jemogfix.dk/sitemap som
    /butikker-og-aabningstider/<by>/. JSON-LD'en (HardwareStore) har adresse
    men INGEN geo — koordinaten staar i sidens "Find vej"-link:
        maps.google.com/?q=<lat>,<lon>

    FAELDER:
      * robots.txt naevner ClaudeBot, men den gruppe forbyder kun /soeg/ og
        /webshop/checkout/. Butikssiderne er tilladte.
      * JSON-LD'ens description kan naevne en ANDEN vej end streetAddress
        (Billund: "Søndre Elkærvej 2" i teksten, "Lille Elkærvej 2" i
        streetAddress). streetAddress er den rigtige.
      * addressLocality har foranstillet mellemrum (" Billund") — strip.
      * JSON-LD'ens name er sidens TITEL, ikke butikkens navn ("Lavpris
        byggemarked på Jagtvej 141 | jem & fix"). Navnet saettes derfor ud fra
        byen, som de ovrige kaeder ("jem & fix Valby"); to butikker i samme by
        skelnes af vejnavnet.
    Forventet: 139."""
    urls = [u for u in _sitemap('https://www.jemogfix.dk/sitemap')
            if re.search(r'/butikker-og-aabningstider/[^/]+/?$', u)]
    def parse(t, u):
        r = _ld_store(t, 'jem & fix')
        if not r:
            return None
        m = re.search(r'maps\.google\.com/\?q=(-?\d+\.\d+),(-?\d+\.\d+)', t) \
            or re.search(r'maps/place/(-?\d+\.\d+),(-?\d+\.\d+)', t)
        if m:
            r['lat'], r['lon'] = _f(m.group(1)), _f(m.group(2))
        r['name'] = 'jem & fix ' + (r.get('by') or '').strip()
        return r
    rows = _pages(urls, parse)
    optalt = {}
    for r in rows:
        optalt[r['name']] = optalt.get(r['name'], 0) + 1
    for r in rows:
        if optalt.get(r['name'], 0) > 1:
            vej = re.sub(r'\s+\d+.*$', '', r.get('street') or '').strip()
            if vej:
                r['name'] = f"{r['name']} ({vej})"
    return rows

def davidsen():
    """Davidsen (Davidsen Trælast & Byggecenter). /find-butik har hele listen i
    et FindShopBlock -> "shops" i sidens inline-JSON.

    FAELDER:
      * Domaenet er davidsen.dk; davidsenshop.dk og davidsen.as redirecter dertil.
      * Hver post har et description-felt med HTML (inkl. { og }) — udklippet
        skal vaere strengbevidst.
      * Feltet heder postalCode, ikke zip.
    Forventet: 47."""
    h = _text('https://www.davidsen.dk/find-butik', 120)
    L = _json_after(h, 'shops', '[')
    return [{'brand': 'Davidsen', 'name': (x.get('name') or '').strip(),
             'street': (x.get('address') or '').strip(),
             'postnr': str(x.get('postalCode') or ''), 'by': (x.get('city') or '').strip(),
             'lat': _f(x.get('latitude')), 'lon': _f(x.get('longitude'))} for x in L]

def silvan():
    """Silvan. Butikslisten paa /butikker hydreres klientsidet og findes IKKE i
    HTML'en; til gengaeld har hver butiksside (/butikker/<by>, 49 i sitemappet)
    sin butik i Nuxt's payload.

    FAELDE — payloaden er devalue-FLADET: et <script> med én stor JSON-liste,
    hvor objekternes vaerdier er HELTALS-INDEKS ind i samme liste. `{"name":4093,
    "latitude":4095}` betyder A[4093] og A[4095]. Man skal altsaa slaa op, ikke
    laese direkte — og address er selv et saadant objekt.

    Silvans webapi (webapi.silvan.dk/api/experience/*) har intet store-endpoint,
    og deres Contentful-space har ingen store-content-type; sitemappet er vejen.
    Forventet: 49 (47 i CSV)."""
    urls = [u for u in _sitemap('https://www.silvan.dk/sitemap.xml')
            if re.search(r'/butikker/[^/]+$', u)]
    def parse(t, u):
        for m in re.finditer(r'<script[^>]*>(\[.*?\])</script>', t, re.S):
            s = m.group(1)
            if '"latitude"' not in s:
                continue
            A = json.loads(s)
            res = lambda v: A[v] if isinstance(v, int) and 0 <= v < len(A) else v
            for o in A:
                if isinstance(o, dict) and 'latitude' in o and 'address' in o:
                    st = {k: res(v) for k, v in o.items()}
                    ad = st.get('address')
                    ad = {k: res(v) for k, v in ad.items()} if isinstance(ad, dict) else {}
                    return {'brand': 'Silvan', 'name': 'Silvan ' + (st.get('name') or '').strip(),
                            'street': (ad.get('streetName') or '').strip(),
                            'postnr': str(ad.get('postalCode') or ''),
                            'by': (ad.get('city') or '').strip(),
                            'lat': _f(st.get('latitude')), 'lon': _f(st.get('longitude'))}
        return None
    return _pages(urls, parse)

def bauhaus():
    """BAUHAUS. /varehus har alle varehuse i et inline-script:
        $('#google-map').googleMapConfig({ stores: {"59":{...},"91":{...}} })
    — et OBJEKT med entity_id som noegle, ikke en liste.

    FAELDER:
      * /butikker, /varehuse og /find-varehus svarer 404. Stien er /varehus
        (ental).
      * Siden har ogsaa et <symbol id="stores"> i sit SVG-sprite; et regex paa
        "stores" alene rammer det foerst. Soeg paa 'stores:' i script-blokken
        eller paa entity_id.
      * latitude/longitude er TEKST med efterstillede nuller ("55.50850700").
      * `link` er slug, `name` er kun bynavnet — praefiks 'BAUHAUS'.
      * country_id er UBRUGELIG som filter: ét varehus (Tilst) har
        country_id='Anelystparken 16', altsaa sin egen gadeadresse — felterne
        er forskudt i kildedata. Et filter country_id=='DK' taber det varehus.
        Alle 19 er danske; filtrér kun paa status.
    Forventet: 19."""
    h = _text('https://www.bauhaus.dk/varehus', 120)
    m = re.search(r'stores:\s*\{', h)
    if not m:
        raise RuntimeError('bauhaus: "stores:" ikke fundet paa /varehus')
    d = json.loads(_balanced(h, h.index('{', m.end() - 1)))
    out = []
    for x in d.values():
        if str(x.get('status')) not in ('1', 'True', 'true'):
            continue
        out.append({'brand': 'BAUHAUS', 'name': 'BAUHAUS ' + (x.get('name') or '').strip(),
                    'street': (x.get('address') or '').strip(),
                    'postnr': str(x.get('postcode') or ''), 'by': (x.get('name') or '').strip(),
                    'lat': _f(x.get('latitude')), 'lon': _f(x.get('longitude'))})
    return out

PLANTORAMA_GQL = 'https://www.plantorama.dk/prod-app-api/graphql'

def plantorama():
    """Plantorama. GraphQL: POST /prod-app-api/graphql med query getAllStores.
    (Endpointet og forespoergslen staar i /assets/javascripts/site.js.)

    FAELDE — VIGTIG: kilden har BYTTET OM paa latitude og longitude. Viborg
    kommer som latitude=9.364051, longitude=56.445664; 9,36 kan ikke vaere en
    dansk breddegrad. Vi bytter dem tilbage her. Tjek ved enhver genopfriskning
    om Plantorama har rettet fejlen — hvis de gor, skal byttet FJERNES.
    _dk_koord() bytter tilbage og er selvkorrigerende: retter Plantorama
    fejlen i kilden, gaar det stadig godt — den bytter kun naar det er noedigt.

    Butikssiderne (/find-center-og-aabningstider/<slug>) har hverken JSON-LD
    eller koordinat — de henter fra samme GraphQL. Plantorama.dk's robots.txt
    og llms.txt tillader eksplicit AI-crawlere paa butikssider.
    Forventet: 16."""
    q = ('query getAllStores { allStores { value { address city id latitude '
         'longitude name phone zipCode } } }')
    d = _post_json(PLANTORAMA_GQL, {'query': q}, 60)
    out = []
    for x in ((d.get('data') or {}).get('allStores') or {}).get('value') or []:
        a, b = _dk_koord(x.get('latitude'), x.get('longitude'))
        out.append({'brand': 'Plantorama',
                    'name': 'Plantorama ' + (x.get('name') or '').strip(),
                    'street': (x.get('address') or '').split(',')[0].strip(),
                    'postnr': str(x.get('zipCode') or ''),
                    'by': (x.get('city') or '').strip(), 'lat': a, 'lon': b})
    return out

# ---------------------------------------------------------------- alle kilder
KILDER = [coop, netto, rema, dagrofa, lidl, apoteker, matas, loevbjerg,
          imerco, kopkande, sport24, bogide, synoptik, thiele, powerdk,
          toejeksperten, jysk, ilva, ikea,
          stark, xlbyg, bygma, jemogfix, davidsen, silvan, bauhaus, plantorama]

# Kilder der henter én side pr. butik (mange HTTP-kald, se faelde 3 i hovedet).
SIDE_FOR_SIDE = {'matas', 'thiele', 'toejeksperten', 'jysk', 'ilva', 'bygma',
                 'jemogfix', 'silvan', 'ikea', 'synoptik'}

if __name__ == '__main__':
    import collections
    import sys
    import time
    kun = set(sys.argv[1:])
    print('%-14s %6s %7s  %s' % ('kilde', 'raekker', 'sek', 'maerker / fejl'))
    print('-' * 96)
    ialt = 0
    for fn in KILDER:
        if kun and fn.__name__ not in kun:
            continue
        t0 = time.time()
        try:
            r = fn()
            ialt += len(r)
            c = collections.Counter(x['brand'] for x in r)
            ukoord = sum(1 for x in r if x['lat'] is None or x['lon'] is None)
            note = ', '.join('%s %d' % (k, v) for k, v in c.most_common(6))
            if ukoord:
                note += '   [%d uden koordinat]' % ukoord
            print('%-14s %6d %7.1f  %s' % (fn.__name__, len(r), time.time() - t0, note))
        except Exception as e:
            print('%-14s %6s %7.1f  FEJL %s: %s'
                  % (fn.__name__, '-', time.time() - t0, type(e).__name__, e))
    print('-' * 96)
    print('%-14s %6d' % ('I ALT', ialt))
