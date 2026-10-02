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
  4. ETIK: thansen.dk forbyder eksplicit ClaudeBot i robots.txt (thansen hentes
     derfor fra Tjek, se thansen()); cvrapi.dk har 'User-agent: * / Disallow: /'.
     normalstores.com forbød ClaudeBot 15-09-2026, men havde 30-09-2026 fjernet
     forbuddet ('User-agent: * / Disallow:'); dens Cloudflare afviser stadig
     ClaudeBot/anthropic-ai-UA'erne (Anthropics crawlere), men tillader Claude-User,
     dvs. brugerstyrede hentninger som denne. normal() tjekker robots.txt ved hver
     koersel og stopper, hvis forbuddet kommer igen. (flyingtiger.com og
     bluebay-marine.dk stod tidligere paa listen ved en FEJL — begge siger
     'User-agent: ClaudeBot / Allow: /'.) jemogfix.dk naevner ogsaa ClaudeBot, men
     dens gruppe forbyder kun /soeg/ og /webshop/checkout/ — butikssiderne er
     tilladte. coop.dk forbyder /umbraco/ (se coop()).

Status pr. 2026-09-11 (alle 27 probet, se __main__ — 4.822 raekker, ~75 sek.):
  coop 875 · netto 584 · apoteker 559 · dagrofa 491 · rema 437 · matas 265
  lidl 171 · imerco 165 · jemogfix 139 · sport24 122 · jysk 117 · bogide 108
  toejeksperten 106 · synoptik 99 · thiele 82 · stark 81 · xlbyg 73 · bygma 64
  kopkande 52 · silvan 49 · davidsen 47 · ilva 40 · powerdk 31 · bauhaus 19
  loevbjerg 18 · plantorama 16 · ikea 12
  Antallene stemmer med CSV-erne paa naer smaa afvigelser, der alle er
  nyaabninger eller sammenlaegninger — se den enkelte docstring.
  30-09-2026 (etape 2) kom egne hentere til: normal, harald_nyborg, foetex (føtex
  og føtex food), bilka, profiloptik, nytsyn, fluegger, fribikeshop, maxizoo og
  skoringen - se afsnittet ETAPE 2 nederst.
  ✗ Elgiganten, H&M, Zara, Louis Nielsen, Flying Tiger, Intersport,
    Sengespecialisten, BoConcept og bil-/have-/lystbaadsforhandlere har INGEN
    parser her — de kommer fra OSM (sources.osm_brand) eller er bag bot-beskyttelse.
    Se NOTER_UDEN_PARSER.
"""
import concurrent.futures as _cf
import time
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
    'Louis Nielsen': 'louisnielsen.dk svarer med en Cloudflare Managed Challenge paa alt '
        '(30-09-2026), og Tjek er foraeldet (har Fisketorvet, lukket 2023). De 80 raekker '
        'stammer fra arkiverede sider; laget kan kun overvaages via CVR (82 aktive '
        'P-enheder i branche 477410 daekker alle 80).',
    'Flying Tiger Copenhagen': 'ingen aaben butiksliste — OSM (robots.txt TILLADER ClaudeBot)',
    'Intersport / Sengespecialisten / BoConcept': 'ingen aaben kilde fundet — OSM',
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

def _ren(s):
    """Afkod HTML-entiteter og saml mellemrum.

    thiele() udsendte "THIELE RO&#8217;s Torv" — en raa entitet direkte i
    butiksnavnet. Kilderne leverer HTML, saa det skal ske ét sted, ikke pr. henter."""
    return ' '.join(_html.unescape(s or '').split())


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
    # '+' kan vaere HTML-kodet: jemogfix.dk skriver type="application/ld&#x2B;json"
    # (30-09-2026). Med kun 'ld\+json' fandt henteren 0 af 139 butikker.
    for b in re.findall(r'<script[^>]+application/ld(?:\+|&#x2[bB];|&#43;)json[^>]*>(.*?)</script>', h, re.S):
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
        return {'brand': brand, 'name': _ren(o.get('name') or name_fallback),
                'street': _ren(a.get('streetAddress')),
                'postnr': str(a.get('postalCode') or '').strip(),
                'by': _ren(a.get('addressLocality')),
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

MAX_SIDEFEJL = 0.02      # over dette afbrydes henteren i stedet for at svare halvt


def _pages(urls, parse, limit=None, workers=8):
    """Hent en liste af butikssider parallelt og saml de parsede raekker.
    `limit` er til probe-brug: hent kun de foerste N sider.

    AFBRYDER hvis for mange sider fejler. Foer slugte den enhver undtagelse pr.
    side og filtrerede resultatet vaek, saa et netvaerkshik paa 50 af Matas' 265
    sider gav 215 butikker — og refresh_retail.py ville melde 50 FALSKE lukninger.
    Samme faelde som "tomt svar ser ud som findes ikke", blot paa sideniveau.
    En halv hentning er aldrig brugbar; derfor fejler den hoejt."""
    ws = urls[:limit] if limit else urls
    fejl = []
    def one(u):
        try:
            return parse(_text(u, 60), u)
        except Exception as e:
            fejl.append((u, f'{type(e).__name__}: {e}'[:80]))
            return None
    ud = [r for r in _map(one, ws, workers) if r]
    # Proev de fejlede sider ÉN gang til foer vagten doemmer. En levende side med
    # 117 undersider har jaevnligt et par forbigaaende timeouts; uden dette faldt
    # hele kaeden ud paa 6 af 117 (maalt 17-09-2026), og saa mister man ugens
    # aegte nyheder for noget der forsvinder ved naeste forsoeg.
    if fejl:
        igen = [u for u, _ in fejl]
        fejl = []
        time.sleep(2)
        ud += [r for r in _map(one, igen, max(2, workers // 2)) if r]
    if len(fejl) > max(2, len(ws) * MAX_SIDEFEJL):
        raise RuntimeError(f'{len(fejl)} af {len(ws)} butikssider fejlede '
                           f'(fx {fejl[0][0]} — {fejl[0][1]}) — AFBRYDER frem for '
                           f'at svare med {len(ud)} butikker')
    # Sider der returnerer None UDEN undtagelse er en anden sag: Bygmas JSON-LD er
    # tom paa to sider, og det er et kendt vilkaar, ikke en fejl. De taelles ikke her.
    return ud

# ================================================================ DAGLIGVARER
# Coops fire kaeder i eTilbudsavis/Tjek: (vores maerke, Tjek-forhandler, navnepraefiks,
# forventet antal). Se coop().
COOP_TJEK = (('Coop 365discount', 'DWZE1w', '365discount', (270, 380)),
             ('Brugsen', 'd311fg', None, (220, 320)),
             ('SuperBrugsen', '0b1e8', None, (180, 260)),
             ('Kvickly', 'c1edq', None, (50, 75)))

# Kendte fejl i kildernes EGNE data. Rettes HER, ikke i CSV'en — ellers foreslaar
# refresh_retail.py dem igen ved hver ugentlig koersel, og en erstatningskoersel
# ruller dem tilbage. Maalt 16-09-2026: uden disse blev 11 haandrettede koordinater
# meldt som afvigelser og fire raekker som "ny butik" + "mulig lukning".
#
# KOORDINATERNE ER LAEST UD AF CSV'EN, ikke skoennet. Foerste udgave havde tal jeg
# skrev ud af hovedet — Soebysoegaard endte 2.990 m fra sin egen adresse i stedet
# for paa den. Enhver koordinat her skal kunne findes i den raekke den retter.
#
# NOEGLEN er (maerke, kildens gadetekst i lowercase) — IKKE (maerke, postnr), som
# ville ramme hver butik kaeden har i det postnummer. Vaerdien er de felter der skal
# overskrives, og hver post skal have belaegget skrevet ved siden af.
KILDEFEJL = {
    # bygma.dk's JSON-LD har navnet haardkodet til "Bygma Bindslev" paa tre
    # butikssider i tre landsdele. Sidens egen <h1> er rigtig.
    ('Bygma', 'strandvejen 10b'): {'name': 'Bygma Fanø'},
    ('Bygma', 'suderbovej 11'): {'name': 'Bygma Frederikshavn'},
    # matas.dk's JSON-LD peger paa Borgerdiget 70B, 1,2 km fra butikken paa Herlev Torv.
    ('Matas', 'herlev bymidte butikscenter'): {'street': 'Herlev Torv 2', 'postnr': '2730',
                                               'lat': 55.723627, 'lon': 12.439253},
    # Matas' slug siger "gaagaden-2-b"; OEstergade 2B findes, OEstergade 2 goer ikke.
    # Kildens koordinat ligger 1.373 m fra bymidten.
    ('Matas', 'østergade 2'): {'street': 'Østergade 2B', 'lat': 55.095010, 'lon': 10.243210},
    # Matas' koordinat for Holstebro ligger 7 km ude ved Struer.
    ('Matas', 'gågaden, nørregade 12'): {'lat': 56.358887, 'lon': 8.617200},
    # Shell Kildebjerg Nord: Shells pin staar paa den forkerte side af E20, 55 m fra Syd-
    # stationens tankbygning. Nord har BBR-tankbygning (1993) paa 532A. Syd: tankbygning og
    # tanke er registreret paa 531A, ikke 531B (efterproevet 01-10-2026).
    ('Shell', 'fynske motorvej 532a'): {'lat': 55.394674, 'lon': 10.190558},
    ('Shell', 'fynske motorvej 531b'): {'street': 'Fynske Motorvej 531A', 'lat': 55.39424, 'lon': 10.18654},
    # Fri BikeShop Skagen: kaedens butiksobjekt har ejernes saesonudlejning 'Skagen
    # BikeRental' (Vestre Strandvej 4); kaedens egen Skagen-side siger at udlejningen
    # resten af aaret foregaar fra butikken paa Fiskergangen. OSM: 'Fri BikeShop'
    # Fiskergangen 10, 291 m fra udlejningen (efterproevet 30-09-2026).
    ('Fri BikeShop', 'vestre strandvej 4'): {'street': 'Fiskergangen 10', 'lat': 57.718862, 'lon': 10.584309},
    # Maxi Zoo Kolding N: kaedens 'Vejlevej 251-261' findes ikke i DAR, og Stockist-pinnen
    # reverse-geokoder til nr. 249 - uden for kaedens eget interval. CVR-P-enheden
    # 'Maxi Zoo Kolding N' og OSM-noden staar paa 255A (efterproevet 30-09-2026).
    ('Maxi Zoo', 'vejlevej 251-261'): {'street': 'Vejlevej 255A', 'lat': 55.514166, 'lon': 9.454399},
    # jem & fix Silkeborg flyttede til en ny bygning (BBR: 322, opfoert 2026, 1.598 m2;
    # aabningsfest 20-09-2026). Kaedens pin ligger 180 m vest for den, paa Gubsøtoften;
    # bygningen staar 7 m fra DAR-punktet for Nordre Højmarksvej 25.
    ('jem & fix', 'nordre højmarksvej 25'): {'lat': 56.198026, 'lon': 9.549040},
    # REMA's pin for Sluseholmen (aabnet 24-09-2026) ligger i nabohuset AL-Huset ved
    # metroen (Sluseholmen 3), 170 m fra butikken. Butikken er den eneste detailenhed i
    # Forbundshuset, Sluseholmen 1A (BBR: 1.201 m2, enhed 322); OSM-noden staar 4 m
    # derfra. Adressen 'Sluseholmen 1' er REMA's, CVR-P-enhedens og Foedevarestyrelsens.
    ('REMA 1000', 'sluseholmen 1'): {'lat': 55.644312, 'lon': 12.545965},
    # Dagrofas feed har koordinater 1-9 km fra butikkernes egne adresser. Adressen
    # svarer i alle syv tilfaelde til butikkens navn (LETKOEB Fjelstrup <-> Fjelstrup
    # Noerrevej), saa det er koordinatet der er forkert.
    ('Let-Køb', 'fjelstrup nørrevej 3'): {'lat': 55.323105, 'lon': 9.563612},
    ('Let-Køb', 'nykøbingvej 177'): {'lat': 54.804322, 'lon': 11.994108},
    ('Let-Køb', 'møllevej 21'): {'lat': 54.741822, 'lon': 11.957523},
    ('Let-Køb', 'svendborgvej 1'): {'lat': 55.178479, 'lon': 10.524476},
    # LETKØB Kramnitze: kaedens pin staar paa en gaard paa Klokkerholmsvej 2/4, 6,9 km fra
    # butikken, og 'Kramnitsevej' findes ikke i DAR. CVR-P-enheden 1027210194 (Kramnitze
    # Købmand ApS, branche 471120) har Kramnitzevej 45A, og BBR har en butiksbygning (322,
    # 335 m2) 2 m fra DAR-punktet for 45A. Stod forkert paa kortet fra 10-09 til 02-10-2026
    # (fundet i review; refresh_retail parrede den paa navn og saa aldrig afstanden).
    ('Let-Køb', 'kramnitsevej 45'): {'street': 'Kramnitzevej 45A', 'lat': 54.704932, 'lon': 11.258109},
    ('Min Købmand', 'amtoftvej 22'): {'lat': 57.007704, 'lon': 8.941656},
    ('Min Købmand', 'holmeåvej 15'): {'lat': 55.605104, 'lon': 8.940223},
    ('MENY', 'blåvandvej 26'): {'lat': 55.555522, 'lon': 8.133708},
    ('SPAR', 'skomagertorvet 7'): {'lat': 56.981296, 'lon': 9.637495},
    # synoptik.dk's koordinat for Amager Centret er Holmbladsgade-butikkens punkt.
    ('Synoptik', 'reberbanegade 3'): {'lat': 55.662829, 'lon': 12.603788},
    # thansen: kaedens egen liste (eTilbudsavis/Tjek) er den rigtige POPULATION, men
    # dens tekst er ikke altid en DAR-adresse (centernavne, "8-10", historiske
    # betegnelser), og fire koordinater ligger 259-1.712 m fra butikken - kaeden har
    # opdateret adressen men ikke pinnen (Skive staar stadig ved den gamle butik paa
    # Holstebrovej 68A). Vaerdierne er LAEST FRA CSV'EN 29-09-2026, ikke skrevet i haanden.
    # thansen Bramming: kaedens koordinat ligger 259 m fra adressen
    ('thansen', 'vardevej 4d'): {'street': 'Vardevej 4D', 'postnr': '6740', 'lat': 55.469040, 'lon': 8.678335},
    # thansen Brøndby: kaeden skriver 'Roskildevej 537'
    ('thansen', 'roskildevej 537'): {'street': 'Roskildevej 537A', 'postnr': '2605', 'lat': 55.667621, 'lon': 12.421145},
    # thansen Egå: kaeden skriver 'Gåseagervej 8-10'
    ('thansen', 'gåseagervej 8-10'): {'street': 'Gåseagervej 10B', 'postnr': '8250', 'lat': 56.213889, 'lon': 10.280975},
    # thansen Esbjerg: kaeden skriver 'Gl. Vardevej 233'
    ('thansen', 'gl. vardevej 233'): {'street': 'Gl Vardevej 233', 'postnr': '6715', 'lat': 55.507377, 'lon': 8.451489},
    # thansen Faaborg: kaedens koordinat ligger 342 m fra adressen
    ('thansen', 'markedspladsen 7d'): {'street': 'Markedspladsen 7D', 'postnr': '5600', 'lat': 55.099784, 'lon': 10.242799},
    # thansen Frederikshavn: kaeden skriver 'H.C. Ørstedsvej 1'
    ('thansen', 'h.c. ørstedsvej 1'): {'street': 'H.C. Ørsteds Vej 1', 'postnr': '9900', 'lat': 57.445068, 'lon': 10.494324},
    # thansen Frederiksværk: kaeden skriver 'Industrivej 1B'
    ('thansen', 'industrivej 1b'): {'street': 'Industrivej 1K', 'postnr': '3300', 'lat': 55.978611, 'lon': 12.004594},
    # thansen Grindsted: kaeden skriver 'Trehøjevej 14'
    ('thansen', 'trehøjevej 14'): {'street': 'Trehøjevej 14A', 'postnr': '7200', 'lat': 55.763830, 'lon': 8.899600},
    # thansen Hadsten: kaeden skriver 'Gadebergcentret'
    ('thansen', 'gadebergcentret'): {'street': 'Gammel Sellingvej 1B', 'postnr': '8370', 'lat': 56.321722, 'lon': 10.043318},
    # thansen Haslev: kaeden skriver 'Lysholm Allé 87'
    ('thansen', 'lysholm allé 87'): {'street': 'Lysholm Alle 87', 'postnr': '4690', 'lat': 55.328527, 'lon': 11.931921},
    # thansen Holbæk: kaeden skriver 'Holbæk Megacenter'
    ('thansen', 'holbæk megacenter'): {'street': 'Frejasvej 14', 'postnr': '4300', 'lat': 55.704311, 'lon': 11.672046},
    # thansen Horsens: kaeden skriver 'Høegh Guldbergsgade 15E'
    ('thansen', 'høegh guldbergsgade 15e'): {'street': 'Høegh Guldbergs Gade 15E', 'postnr': '8700', 'lat': 55.854156, 'lon': 9.851458},
    # thansen Korsør: kaeden skriver 'Motalavej 145'
    ('thansen', 'motalavej 145'): {'street': 'Motalavej 145B', 'postnr': '4220', 'lat': 55.349718, 'lon': 11.141601},
    # thansen Køge: kaeden skriver 'Gl. Lyngvej 21C'
    ('thansen', 'gl. lyngvej 21c'): {'street': 'Gammel Lyngvej 21C', 'postnr': '4600', 'lat': 55.481939, 'lon': 12.182985},
    # thansen Maribo: kaeden skriver 'Vesterbrogade 1 c'
    ('thansen', 'vesterbrogade 1 c'): {'street': 'Vesterbrogade 1C', 'postnr': '4930', 'lat': 54.774876, 'lon': 11.493188},
    # thansen Ribe: kaeden skriver 'Marskcentret'
    ('thansen', 'marskcentret'): {'street': 'Moltkes Alle 12', 'postnr': '6760', 'lat': 55.334581, 'lon': 8.772820},
    # thansen Rødovre: kaeden skriver 'Sandbækvej 3'
    ('thansen', 'sandbækvej 3'): {'street': 'Sandbækvej 3A', 'postnr': '2610', 'lat': 55.693005, 'lon': 12.430812},
    # thansen Skive: kaedens koordinat ligger 470 m fra adressen
    ('thansen', 'østergårdsbakken 5'): {'street': 'Østergårdsbakken 5', 'postnr': '7800', 'lat': 56.569789, 'lon': 8.997008},
    # thansen Svendborg: kaeden skriver 'Svendborg Storcenter'
    ('thansen', 'svendborg storcenter'): {'street': 'Vestergade 167D', 'postnr': '5700', 'lat': 55.063416, 'lon': 10.588694},
    # thansen Tønder: kaeden skriver 'Ndr. Landevej 26c'; kaedens koordinat ligger 1712 m fra adressen
    ('thansen', 'ndr. landevej 26c'): {'street': 'Centerbuen 4', 'postnr': '6270', 'lat': 54.951120, 'lon': 8.886813},
    # thansen Vejle Nord: kaeden skriver 'Solkilde Allé 5b'
    ('thansen', 'solkilde allé 5b'): {'street': 'Solkilde Alle 5B', 'postnr': '7100', 'lat': 55.725245, 'lon': 9.583609},
    # thansen Viborg: kaeden skriver 'Viborg Storcenter'
    ('thansen', 'viborg storcenter'): {'street': 'Holstebrovej 81M', 'postnr': '8800', 'lat': 56.446545, 'lon': 9.364496},
    # thansen Ølstykke: kaeden skriver 'Egedal Storbutikker'
    ('thansen', 'egedal storbutikker'): {'street': 'Valdemarsvej 1B', 'postnr': '3650', 'lat': 55.777221, 'lon': 12.184014},
}


def _kfnoegle(r):
    return (r.get('brand'), ' '.join((r.get('street') or '').lower().split()))


def _ret_kildefejl(rows):
    """Anvend KILDEFEJL paa en henters raekker."""
    for r in rows:
        f = KILDEFEJL.get(_kfnoegle(r))
        if f:
            r.update(f)
    return rows


def _uniq(rows):
    """Fjern kildens egne dubletter: samme navn OG samme koordinat.

    7-eleven.dk lister "7-Eleven Bispebjerg Hospital" to gange med identiske
    koordinater; netto.dk har Svinninge som to store-id'er 60 m fra hinanden.
    Uden dette kom dubletterne igen ved hver ugentlig koersel."""
    set_, ud = set(), []
    for r in rows:
        k = ((r.get('name') or '').strip().lower(),
             round(float(r['lat']), 6) if r.get('lat') else None,
             round(float(r['lon']), 6) if r.get('lon') else None)
        if k in set_:
            continue
        set_.add(k); ud.append(r)
    return ud


def _naer_uniq(rows, m=120):
    """Som _uniq, men fanger ogsaa dubletter der ligger LIDT fra hinanden.

    netto.dk's feed har Svinninge to gange med samme navn og adresse, men 60 m
    mellem koordinaterne, saa _uniq's eksakte sammenligning misser den."""
    import math as _m
    ud = []
    for r in rows:
        try:
            la, lo = float(r['lat']), float(r['lon'])
        except (TypeError, ValueError, KeyError):
            ud.append(r); continue
        dub = False
        for o in ud:
            try:
                oa, ob = float(o['lat']), float(o['lon'])
            except (TypeError, ValueError, KeyError):
                continue
            # Navn ALENE duer ikke: alle Matas-raekker hedder "Matas", saa en Matas og
            # en Matas LIFE 8 m fra hinanden i Frederiksberg Centret blev slaaet
            # sammen. Gaden skal med — den skelner de to formater.
            if (o.get('name') or '').strip().lower() != (r.get('name') or '').strip().lower():
                continue
            if ' '.join((o.get('street') or '').lower().split()) != \
               ' '.join((r.get('street') or '').lower().split()):
                continue
            R = 6371000.0; rad = _m.pi / 180
            x = (oa - la) * rad; y = (ob - lo) * rad
            d = 2 * R * _m.asin(_m.sqrt(_m.sin(x / 2) ** 2 +
                                        _m.cos(la * rad) * _m.cos(oa * rad) * _m.sin(y / 2) ** 2))
            if d < m:
                dub = True; break
        if not dub:
            ud.append(r)
    return ud


def coop():
    """Coops fire kaeder (Coop 365discount, Brugsen, SuperBrugsen, Kvickly) fra
    eTilbudsavis/Tjek, som Coop selv fodrer. Se _tjek().

    30-09-2026: erstatter POST coop.dk/umbraco/api/Chains/GetAllStores. robots.txt paa
    coop.dk og alle fire kaededomaener forbyder /umbraco/ for alle bots, og det var den
    sti henteren kaldte hver uge. Kaedernes sitemaps (/find-butik/<navn>/<id>/) er
    tilladte, men butikssiderne henter adresse og koordinat i browseren fra samme
    /umbraco/-API, saa sitemaps'ene giver kun listen - ikke hvor butikkerne ligger.

    Kontrolleret 30-09-2026 mod vores 864 Coop-raekker, der kom fra /umbraco/-API'et:
    alle 864 genfundet inden for 150 m (365discount 320/320, Brugsen 264/264,
    SuperBrugsen 218/218, Kvickly 62/62). Tjek havde allerede fjernet Brugsen Virklund
    (lukket 24-09-2026) og havde SuperBrugsen Virklund (aabnet samme dag). Kaedernes
    sitemaps har 873 butikssider; forskellen er faengselsbutikker og et bageriudsalg,
    som /umbraco/-API'et heller ikke gav en koordinat for. Tjek er dermed IKKE
    foraeldet for Coop, som det er for Kvik og Fluegger (se _tjek).

    FAELDER:
      * Tjek kalder kaeden '365discount' og butikkerne '365discount <sted>'; vores
        maerke hedder 'Coop 365discount', butiksnavnene '365discount <sted>' - derfor
        praefikset. Uden det blev navnet 'Coop 365discount 365discount Struer'.
      * Kvickly-forhandleren har ogsaa vinbutikken 'Kvickly Odder MEGAVIN' (Stampmøllevej
        52B), som /umbraco/-API'et ikke leverede og som ikke er et supermarked.
      * Tjek har faengselsbutikken SuperBrugsen Søbysøgård Fængsel (Søvej 27). Den er
        ikke aaben for offentligheden og udelades i refresh_retail.UDELADT."""
    out = []
    for brand, forhandler, praefiks, n in COOP_TJEK:
        out += _tjek(forhandler, brand, forventet=n, prefiks=praefiks,
                     behold=lambda s: 'megavin' not in (s.get('name') or '').lower())
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
    return _naer_uniq(out)

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
    return _uniq(out)

def thansen():
    """thansen (T. Hansen Gruppen A/S, CVR 15242485) fra kaedens EGEN butiksliste.

    Kilden er eTilbudsavis' butiks-API (Tjek), som kaeden selv fodrer:
    squid-api.tjek.com/v2/stores?dealer_ids=bf85Cg. Den gav 29-09-2026 praecis 86
    butikker - samme tal som kaeden selv oplyser - og CVR bekraeftede 82 af dem paa
    samme adresse og de sidste 4 paa et gammelt nabonummer. Hverken squid-api.tjek.com
    (ingen robots.txt) eller tjek.com (Allow: /) forbyder hentning. API'et er
    udokumenteret; forsvinder det, skal fejlen vaere hoej, ikke tavs.

    thansen.dk selv svarer 403 Forbidden til automatiserede klienter (29-09-2026),
    ogsaa paa robots.txt.

    HVORFOR IKKE OSM LAENGERE: det OSM-baserede lag havde kun 63 af 86 rigtige.
    13 pins var forkerte - flyttede butikker (Glostrup, Maribo, Ikast, Grenaa,
    Lemvig, Slagelse, Tilst, Hobro, Nykoebing F, Helsinge), en dublet (Skive), en
    byggeplads (Bjerringbro) og en butik der foerst aabner 30-10-2026 (Holstebro
    Hyldgaardvej). OSM OG openhours.dk var enige om flere af de forkerte: to
    kilder der kopierer samme foraeldede oplysning er ikke to bekraeftelser.

    FAELDER:
      * Kaedens tekst er ikke altid en DAR-adresse, og fire koordinater er
        foraeldede. Begge dele rettes via KILDEFEJL (noeglet paa kaedens gadetekst).
      * Kaedens KOORDINAT er ikke til at stole paa, dens ADRESSE er: i alle fire
        tilfaelde laa vores pin 7-25 m fra adressens officielle punkt, kaedens
        257-1.712 m vaek.
    Forventet: ~86."""
    return _tjek('bf85Cg', 'thansen', forventet=(60, 130))


def _tjek(dealer_id, brand, forventet, prefiks=None, behold=None):
    """En kaedes EGEN butiksliste fra eTilbudsavis/Tjek (squid-api.tjek.com), som kaeden
    selv fodrer. Bygget til thansen (29-09-2026: praecis kaedens 86) og genbrugt til
    kaeder uden officiel henter.

    FAELDER (maalt):
      * country.id == 'DK' omfatter Faeroeerne, Island og Groenland (Sport 24 har 9
        dér). Kraev et 4-cifret postnr og en koordinat i DK-boksen.
      * Kaedens ADRESSE er til at stole paa, dens KOORDINAT ikke altid (thansen:
        fire pins 259-1.712 m vaek). Den slags rettes i KILDEFEJL.
      * "Kolding (Sdr. Ringvej)" -> "Kolding Sdr. Ringvej": to butikker i samme by.
      * En forhandler kan rumme andre kaeder (Salling: Matinique, Hugo, Boss) -
        filtrér med behold(butik) -> bool.
    forventet = (min, max); uden for det er en koerselsfejl, ikke lukninger/aabninger.

    BRUG KUN HVOR LISTEN ER EFTERPROEVET. Tjek-listen er kaedens tilbudsavis-opsaetning,
    ikke dens butiksregister, og mange kaeder rydder den ikke op. Gennemgang 29-30/9-2026
    (16 kaeder, 173 uoverensstemmelser, efterforsker + skeptiker pr. post):
      * PAALIDELIG: thansen (praecis 86), Harald Nyborg (3 manglende fundet).
      * BRUGBAR MED FORBEHOLD: Normal (8 manglende fundet, men listen har ogsaa
        kaedens cafe 'Original' i Silkeborg og en butik foer aabningsdagen).
      * FORAELDET - brug kaedens egen butiksfinder: Kvik (kvik.dk/find-butik har 35 =
        vores 35; Tjek har 11 lukkede, bl.a. Roenne lukket 31/8-2023), Fluegger (egen
        liste 102 = vores; Tjek har lukkede og malerfirmaer der ikke laengere er Fluegger),
        Intersport (ikke ryddet op siden 2024: lukkede butikker og butikker der blev til
        Sport 24 i 2025), Louis Nielsen (Fisketorvet, lukket feb. 2023, staar der stadig).
      * DELMAENGDE (kun tilbudsavis-butikker): Bygma, Davidsen, Silvan.
      * BLANDER KAEDER: Salling (Matinique/Hugo/Boss), foetex (Outlet = non-food),
        Bilka ('Bilka Hjoerring' er A-Z).
    En foraeldet liste i refresh_retail ville GENINDFOERE lukkede butikker hver uge."""
    ud, off = [], 0
    while True:
        side = _json(f'https://squid-api.tjek.com/v2/stores?dealer_ids={dealer_id}&limit=100&offset={off}', 60)
        if not isinstance(side, list):
            raise RuntimeError(f'{brand}: uventet svar fra Tjek: {str(side)[:200]}')
        ud += side
        if len(side) < 100:
            break
        off += 100
    out = []
    for s in ud:
        if (s.get('country') or {}).get('id') != 'DK':
            continue
        if not re.fullmatch(r'\d{4}', str(s.get('zip_code') or '').strip()) or _dk_koord(s.get('latitude'), s.get('longitude'))[0] is None:
            continue
        if behold and not behold(s):
            continue
        navn = (s.get('name') or '').strip()
        m = re.match(r'(.*?)\s*\((.*)\)\s*$', navn)
        navn = f'{m.group(1)} {m.group(2)}' if m else navn
        pre = brand if prefiks is None else prefiks
        if pre and navn.lower().startswith(pre.lower()):
            navn = navn[len(pre):].strip(' -')
        out.append({'brand': brand, 'name': f'{pre} {navn}'.strip() if pre else navn,
                    'street': ' '.join((s.get('street') or '').split()),
                    'postnr': (s.get('zip_code') or '').strip(), 'by': (s.get('city') or '').strip(),
                    'lat': _f(s.get('latitude')), 'lon': _f(s.get('longitude'))})
    out = _ret_kildefejl(_uniq(out))
    lo, hi = forventet
    if not lo <= len(out) <= hi:
        raise RuntimeError(f'{brand}: Tjek gav {len(out)} butikker (forventet {lo}-{hi}) '
                           f'- behandles som en koerselsfejl, ikke som lukninger/aabninger')
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
    return _ret_kildefejl(out)

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
      * Én Let-Koeb-post mangler koordinat: 'LETKØB H.C. Ørstedsvej - Shopbox',
        oprettet og sidst aendret 09-08-2022, med adressen Classensgade 44, 2100 -
        MIN KØBMAND København Ø's adresse. Det er en efterladt skabelonpost, ikke en
        butik (efterproevet 01-10-2026). refresh_retail springer poster uden
        koordinat over og melder dem som INFO.
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
    return _ret_kildefejl(out)

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
    return _ret_kildefejl(_pages(urls, lambda t, u: _ld_store(t, 'Matas')))

def loevbjerg():
    """Loevbjerg. Butikslisten ligger som en almindelig JS-literal
    `var locations = [...]` paa /butikker-aabningstider (Drupal-site, ingen API).
    Felterne heder lat/long (ikke lon!) og er TEKST. Forventet: 18."""
    h = _text('https://www.lovbjerg.dk/butikker-aabningstider', 60)
    i = h.index('[', h.index('var locations'))
    arr = json.loads(_balanced(h, i, '[', ']'))
    # address har ved centerbutikker centernavnet paa sin egen linje: "Tarup Centret
    # \nRugvang 36-38". Linjeskiftet endte inde i CSV-feltet (Tarup, Trøjborg; fundet
    # 30-09-2026). Kun sidste linje er gadeadressen; centret staar allerede i navnet.
    return [{'brand': 'Løvbjerg', 'name': _ren(x.get('title')),
             'street': _ren((x.get('address') or '').strip().split('\n')[-1]),
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
      * name er "Imerco Home <by>" for Home-butikkerne. De faar deres EGET maerke
        'Imerco Home' (41 butikker) — samme regel som H&M HOME, IKEA
        bestillingssted og Sport 24 Outlet. Laa de under 'Imerco', sagde de fire
        afgoerelser fire forskellige ting.
      * /butikker svarer 404 — stien er /find-imerco/<slug>.
    Forventet: 165."""
    h = _text('https://www.imerco.dk/find-imerco/imerco-aarhus-store-torv', 90)
    L = _json_after(h, 'storeList')['data']
    return [{'brand': 'Imerco Home' if (x.get('name') or '').strip().startswith('Imerco Home')
                      else 'Imerco',
             'name': (x.get('name') or '').strip(),
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
        # Navnet skal baere maerket, ogsaa naar det er outlet-formatet: ellers hed
        # alle 57 outlet-raekker 'Sport 24 <by>' under maerket 'Sport 24 Outlet'.
        out.append({'brand': brand, 'name': (brand + ' ' + (x.get('name') or '')).strip(),
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
    return _ret_kildefejl(ud)

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
        # title er DOBBELT-kodet: attributten afkodes ovenfor, men vaerdien inde i
        # JSON'en er selv escapet ("RO&#8217;s Torv"). Derfor _ren paa felterne.
        return {'brand': 'Thiele', 'name': _ren(b.get('title')),
                'street': _ren(dele[0]) if dele else '', 'postnr': pn,
                'by': _ren(dele[-1]) if len(dele) > 2 else '',
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
    return _ret_kildefejl(ud)

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
    Forventet: 139.

    30-09-2026: sitemap'et (www.jemogfix.dk/sitemap -> /umbraco/surface/Sitemap/
    GetContentSiteMap) var TOMT - 0 adresser - og henteren gav 0 butikker, selvom
    butikssiderne stadig svarede 200. Butikslisten tages nu fra oversigtssiden, der
    linker til alle 139; sitemap'et bruges oveni, hvis det kommer igen."""
    h = _text('https://www.jemogfix.dk/butikker-og-aabningstider/', 90)
    urls = {'https://www.jemogfix.dk' + p
            for p in re.findall(r'href="(/butikker-og-aabningstider/[^/"]+/)"', h)}
    try:
        urls |= {u.rstrip('/') + '/' for u in _sitemap('https://www.jemogfix.dk/sitemap')
                 if re.search(r'/butikker-og-aabningstider/[^/]+/?$', u)}
    except Exception:
        pass    # oversigtssiden er hovedkilden; et doedt sitemap maa ikke vaelte den
    urls = sorted(urls)
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
    return _ret_kildefejl(rows)

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

# ================================================================ ETAPE 2: KAEDERNES EGNE LISTER
# Tilfoejet 30-09-2026 for at daekke maerker, der ikke blev overvaaget ugentligt. Hver kilde
# er kaedens egen, robots.txt-kontrolleret og efterproevet mod vores raekker; se docstrings.

# ---- Normal (etape 2, 30-09-2026: bygget af en efterforsker, genkoert og godkendt af en skeptiker)
import urllib.error

_ROBOTS = {}
_CLAUDE_AGENTER = ('claudebot', 'claude-user', 'claude-searchbot', 'claude-web', 'anthropic-ai')


def _robots_tilladt(url, agenter=_CLAUDE_AGENTER):
    """Maa `url` hentes efter vaertens robots.txt? Laeses i haanden efter RFC 9309,
    fordi urllib.robotparser ignorerer reglen om laengste match (se REFRESH.md, goon.nu).

    Vi skal overholde BAADE '*'-gruppen og enhver gruppe der naevner en Claude-agent:
    henteren sender en browser-UA, men repoets regel er at et eksplicit ClaudeBot-forbud
    respekteres (normalstores.com havde et 15-09-2026 og havde fjernet det 30-09-2026).
    Den strengeste fortolkning er valgt med vilje: forbyder EN af grupperne stien, hentes
    der ikke. 4xx paa robots.txt = ingen regler (RFC 9309 2.3.1.3) - undtagen 401/403/429,
    som er en blokering; 5xx og timeout = alt forbudt (2.3.1.4). En omdirigering, som
    urllib i Python 3.9 ikke foelger (308), giver ogsaa 'forbudt' - fejler hoejt, ikke tavst.

    Til hentere hvis vaert har skiftet robots.txt for nylig: en ugentlig hentning maa
    ikke fortsaette i stilhed, hvis vaerten lukker igen. Ét ekstra kald pr. vaert."""
    p = urllib.parse.urlsplit(url)
    vaert = f'{p.scheme}://{p.netloc}'
    if vaert not in _ROBOTS:
        try:
            _ROBOTS[vaert] = _text(vaert + '/robots.txt', 30)
        except urllib.error.HTTPError as e:
            _ROBOTS[vaert] = '' if 400 <= e.code < 500 and e.code not in (401, 403, 429) else None
        except Exception:
            _ROBOTS[vaert] = None
    tekst = _ROBOTS[vaert]
    if tekst is None:
        return False
    # _text afkoder med 'utf-8', saa en BOM bliver staaende som '﻿' foran foerste
    # linje, og str.strip() fjerner den ikke. Saa blev 'User-agent: ClaudeBot / Disallow: /'
    # ikke genkendt, og stien blev meldt TILLADT (testet 30-09-2026; ligeher.nu og
    # pub.fvst.dk leverer netop filer med BOM).
    tekst = tekst.lstrip('﻿')
    grupper, cur, regler_set = [], None, False
    for linje in tekst.splitlines():
        linje = linje.split('#', 1)[0].strip()
        if ':' not in linje:
            continue
        k, v = (s.strip() for s in linje.split(':', 1))
        k = k.lower()
        if k == 'user-agent':
            if cur is None or regler_set:
                cur = ([], []); grupper.append(cur); regler_set = False
            cur[0].append(v.lower().split('/')[0].strip())
        elif k in ('allow', 'disallow') and cur is not None:
            regler_set = True
            if v:
                cur[1].append((k == 'allow', v))
    sti = (p.path or '/') + ('?' + p.query if p.query else '')

    def rammer(m):
        rx = ''.join('.*' if c == '*' else '$' if (c == '$' and i == len(m) - 1) else re.escape(c)
                     for i, c in enumerate(m))
        return re.match(rx, sti) is not None

    def tillader(regler):
        bedst = None                        # (laengde, allow): laengst vinder, Allow ved lige
        for allow, m in regler:
            if rammer(m) and (bedst is None or (len(m), allow) > bedst):
                bedst = (len(m), allow)
        return bedst is None or bedst[1]
    relevante = [g for g in grupper if any(a == '*' or a in agenter for a in g[0])]
    return all(tillader(g[1]) for g in relevante)


# Etage/lejemaal som et helt komma-led: 'st. th.', '1. 7', 'st. 4', 'lejemål 2300',
# 'Plan 2 - butik 63'.
_ENHED = re.compile(r'^(?:st|stuen|kl|kld|\d{1,2})\.?(?:\s*(?:th|tv|mf|\d{1,3})\.?)?$'
                    r'|^(?:lejemål|lejemaal|plan|butik|unit)\b', re.I)


def _normal_gade_nr(s):
    """Kaedens adressetekst -> 'Vej nr'.

    Fjerner etage/lejemaal ('Kastetvej 37, st.', 'Ballerup-Centret 2, 1. 7'),
    centernavne som ekstra komma-led - baade FOER vejen ('Metropol, Østergade 30') og
    EFTER ('Løven 4, City Syd') -, skriver 'Markedsvej 24 B' som '24B' og goer et
    husnummer-interval til dets foerste nummer ('Torvegade 45-47' -> 'Torvegade 45',
    'Skråvej 6A-6B' -> 'Skråvej 6A', 'Fælledvej 1C-D' -> 'Fælledvej 1C').
    dawa.split_street klarer selv intervaller uden bogstav, men ikke '6A-6B' og ikke et
    centernavn foran vejen; og KILDEFEJL/UDELADT noegler paa netop denne tekst."""
    dele = [d.strip() for d in _ren(s).split(',') if d.strip()]
    rest = [d for d in dele if not _ENHED.search(d)] or dele[:1]
    med_nr = [d for d in rest if re.search(r'[^\W\d_].*\s\d', d)]
    g = med_nr[0] if med_nr else (rest[0] if rest else '')
    g = re.sub(r'\s+(?:st|stuen)\.?(?:\s*(?:th|tv|mf)\.?)?$', '', g, flags=re.I)
    g = re.sub(r'(\d+)\s*([A-Za-zÆØÅæøå]?)\s*-\s*\d*\s*[A-Za-zÆØÅæøå]?$',
               lambda m: m.group(1) + m.group(2).upper(), g)
    g = re.sub(r'(\d)\s+([A-Za-zÆØÅæøå])$', lambda m: m.group(1) + m.group(2).upper(), g)
    return g.strip()


def _dk_postnr(pn):
    """4 cifre og ikke 39xx (Groenland). Faeroeerne har 3 cifre, Sverige/Tyskland 5."""
    pn = str(pn or '').strip()
    return pn if re.fullmatch(r'\d{4}', pn) and not pn.startswith('39') else ''


def _afst_m(a, b, c, d):
    """Afstand i meter (haversine) mellem (a, b) og (c, d)."""
    import math as _m
    r = _m.pi / 180
    x, y = (c - a) * r, (d - b) * r
    return 2 * 6371000.0 * _m.asin(_m.sqrt(_m.sin(x / 2) ** 2 +
                                           _m.cos(a * r) * _m.cos(c * r) * _m.sin(y / 2) ** 2))


def _gmaps_naal(url, lat, lon):
    """Kaedens koordinat -> Google-stedets naal, NAAR koordinaten er kortets midtpunkt.

    Et Google Maps-link har to slags koordinater: '@lat,lon' er KORTUDSNITTETS midte,
    '!3d<lat>!4d<lon>' (den sidste i linket) er selve stedets naal. For de tre nyeste
    Normal-poster (30-09-2026: Aalborg Kennedy Arkaden, Espergærde Centret, Fredericia
    Erritsø) er latitude/longitude kopieret fra '@', og naalen ligger 156-162 m vaek:
    Erritsø-naalen staar 0 m fra DAR-punktet for CVR-adressen Strevelinsvej 1C, mens
    kaedens koordinat giver 'Gl. Landevej 63'; Kennedy-naalen 56 m fra CVR's John F.
    Kennedys Plads 1B mod 206 m. Rettes KUN naar koordinaten er '@' (hoejst 3 m) og
    naalen ligger over 30 m derfra - det rammer ingen af de 168 aabne butikker i dag.
    (Et link kan pege paa en ANDEN butik, fx Køge Brogade -> 'NORMAL Køge, Strædet', men
    der er koordinaten ikke '@', saa den roeres ikke.)"""
    if lat is None or not url:
        return lat, lon
    vp = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
    naale = re.findall(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', url)
    if not vp or not naale:
        return lat, lon
    nla, nlo = _dk_koord(*naale[-1])
    if nla is None or _afst_m(lat, lon, float(vp.group(1)), float(vp.group(2))) > 3 \
            or _afst_m(lat, lon, nla, nlo) <= 30:
        return lat, lon
    return nla, nlo


_MAANED = {'januar': 1, 'februar': 2, 'marts': 3, 'april': 4, 'maj': 5, 'juni': 6, 'juli': 7,
           'august': 8, 'september': 9, 'oktober': 10, 'november': 11, 'december': 12}


def _aabner_senere(tekst, idag=None):
    """'(åbner snart)' -> True; '(åbner den 30. september)' -> True indtil den dag.
    En aabningstekst vi ikke kan laese regnes som 'endnu ikke aaben'. Uden aar: en dato
    mere end et halvt aar tilbage er naeste aars ('åbner den 5. januar' set i december)."""
    import datetime as _dt
    t = _ren(tekst).lower()
    if 'åbner' not in t and 'aabner' not in t:
        return False
    idag = idag or _dt.date.today()
    m = re.search(r'(\d{1,2})\.?\s*([a-zæøå]+)', t)
    if not m or m.group(2) not in _MAANED:
        return True
    try:
        d = _dt.date(idag.year, _MAANED[m.group(2)], int(m.group(1)))
        if (idag - d).days > 183:
            d = d.replace(year=idag.year + 1)
    except ValueError:
        return True
    return d > idag


NORMAL_URL = 'https://www.normalstores.com/stores?culture=da-dk'


def normal():
    """Normal (NORMAL A/S, CVR 34883793) fra kaedens EGEN butiksfinder.

    Kilde: www.normalstores.com/stores?culture=da-dk - det JSON-endpoint som
    /dk/find-butikaabningstid/ selv kalder (Vue-appens storesGet; basePath er
    window.appData.cmsHost). Ét kald, 173 poster 30-09-2026. normal.dk og
    www.normal.dk viderestiller til www.normalstores.com/dk/.

    ROBOTS: 15-09-2026 forbød normalstores.com ClaudeBot. Det var Cloudflares styrede
    robots.txt (Wayback 03-05-2026: 'Content-Signal: search=yes,ai-train=no' og
    'User-agent: ClaudeBot / Disallow: /' m.fl.). 30-09-2026 er den slaaet fra: robots.txt
    er 'User-agent: * / Disallow:' uanset UA. Cloudflare BLOKERER dog stadig UA'erne
    ClaudeBot og anthropic-ai paa /stores og /dk/robots.txt ('Your request was blocked.',
    403; kun /robots.txt svarer dem) - et fravalg af AI-TRAENING; Claude-User og
    Claude-SearchBot faar 200 paa /stores. Listen bruges ikke til traening. Slaar
    vaerten den styrede robots.txt til igen, fanger _robots_tilladt ClaudeBot-gruppen, og
    henteren fejler hoejt i stedet for at hente. Pythons standard-UA faar Cloudflare 1010.

    Efterproevet 30-09-2026 mod de 168 CSV-raekker, CVR's P-enheder (183 aktive under
    34883793) og Foedevarestyrelsens smiley-register (180 registreringer):
      * Alle 168 aabne butikker svarer til en P-enhed/smiley-registrering; de oevrige
        P-enheder er HQ, lagre, kantiner, e-handel, cafeen Original, City Vest (2015) og
        seks 2021-enheder (Blåvand, Faaborg, Assens, Marielyst, Løkken, Ringkøbing) - de
        syv sidste uden butik i listen og uden smiley-registrering. De nyeste P-enheder
        (Kennedy Arkaden 28-07-2026, Erritsø 14-07-2026) staar i listen: kilden er aktuel.
      * 165 parret inden for 150 m efter KILDEFEJL. Lyngby Storcenter (kaedens pin 183 m
        forkert; centrets egen side og naboerne afgjorde det) er rettet i KILDEFEJL
        01-10-2026, saa alle parres nu uden KOORD-AFVIGELSE.
      * 1 ny: Aalborg Kennedy Arkaden, aabnede 30-09-2026 (LigeHer.nu, Ritzau).
      * 1 CSV-dublet: 'Normal Silkeborg', Viborgvej 14 - samme butik som 'Normal Silkeborg
        Nørrevænget' (Viborgvej 16A): kaedens telefon +45 42 13 04 22 staar paa den
        OSM-node raekken kom fra; CVR og smiley har én enhed dér.
      * Haderslev FLYTTEDE 29-04-2026 fra Gravene til Bispegade 15 (kaedens
        pressemeddelelse 18-04-2026; CVR-adressen skiftede med virkning mellem 15-04 og
        01-05-2026; ny smiley-registrering 1515377). Kaedens pin staar stadig ved den
        gamle butik - se KILDEFEJL.
    Tjek (pZEC1r) havde samme dag 169: de 168 + cafeen Original, men ikke de 2 uaabnede.

    FAELDER:
      * Listen er IKKE kun butikker: cafeen 'Original' i Silkeborg ('(Lukket permanent)',
        cafeoriginal@normal.dk) og to 'Kaffebar' Rolig' (Aalborg Algade 19, Aarhus
        Søndergade 39-43) paa samme adresse som en butik. Rigtige butikker har en
        butiksmail DKnnnn@normal.dk (Rosengårdcentret skriver 'dk1081' med smaat);
        de tre har ingen. Filtrér paa mailen OG navnet.
      * Status staar i namePostFix, ikke i et felt: '(åbner snart)' (Espergærde,
        Fredericia Erritsø), '(åbner den 30. september)' (Aalborg Kennedy Arkaden) og
        '(Lukket permanent)'. Uaabnede butikker har desuden closed=true alle ugens dage
        - bruges som reserve, hvis teksten mangler. Hørsholm har en gammel
        '(Lukket i perioden 23/8 - 4/9 - genåbning 5/9)' og er aaben.
      * NYE butikker faar kortudsnittets midte som koordinat i stedet for stedets naal
        (156-162 m forkert paa de tre nyeste) - se _gmaps_naal. Uden rettelsen skrev
        refresh_retail Kennedy Arkaden som 'John F. Kennedys Plads 3' (7-Eleven Aalborg
        Station), og Espergærde ville faa 'Vestermarken 12'.
      * Kaeden opdaterer adresseTEKSTEN, men ikke altid pinnen: Haderslev staar paa
        Bispegade 15 med pin ved den gamle butik, og ugekoerslen ser det ikke, fordi
        pinnen stadig er enig med vores gamle raekke.
      * Kaedens pin ligger over 150 m fra DAR-punktet for dens EGEN adresse i 12 af 168
        tilfaelde, mest i storcentre. Google-linket i googleMapsUrl peger undertiden paa
        en ANDEN butik ('NORMAL Køge, Strædet' for Brogade) eller et gammelt navn
        ('NORMAL Haderslev, Gravene').
      * address er fri tekst: centernavne foran vejen ('Metropol, Østergade 30'),
        lejemaal ('Plan 2 - butik 63'), etager ('1. 7', 'st. th.'), intervaller
        ('Nygade 1-3') og forkortelser ('John F. Kennedys Pl. 1', som DAR ikke kender).
        Se _normal_gade_nr. 32 af 168 findes ikke ordret i DAR.
      * Enkelte koordinater har kun 3 decimaler (Viborg Sct. Mathias Centret 56.449,
        9.405; Vejle Bryggen 55.705, 9.53).
      * culture=da-dk giver kun danske butikker; postnr- og DK-tjek er en sikring.
    Navn: 'Normal <by> <sted>' ud fra kaedens '<by>, <sted>'; staar byen allerede
    forrest i stedet ('Lyngby, Lyngby Storcenter'), bruges kun stedet.
    Forventet: 168 (170 butiksposter minus 2 'åbner snart', 30-09-2026)."""
    if not _robots_tilladt(NORMAL_URL):
        raise RuntimeError('normal: robots.txt paa www.normalstores.com forbyder nu /stores '
                           '- henter ikke (ClaudeBot var forbudt 15-09-2026)')
    d = _json(NORMAL_URL, 60)
    if not isinstance(d, list):
        raise RuntimeError(f'normal: uventet svar fra /stores: {str(d)[:200]}')
    out = []
    for x in d:
        navn = _ren(x.get('name'))
        post = _ren(x.get('namePostFix')).lower()
        if not re.fullmatch(r'dk\d{3,5}@normal\.dk', (x.get('email') or '').strip().lower()):
            continue                     # cafeen Original og Kaffebar' Rolig
        if re.search(r'kaffebar|caf[eé]|^original\b', navn, re.I):
            continue
        if 'permanent' in post or _aabner_senere(post):
            continue
        tider = x.get('openingHours') or []
        if tider and all(t.get('closed') for t in tider) and 'midlertidig' not in post:
            continue                     # lukket alle ugens dage = ikke aaben
        pn = _dk_postnr(x.get('postalCode'))
        lat, lon = _dk_koord(x.get('latitude'), x.get('longitude'))
        if not pn or (lat is None and x.get('latitude') not in (None, '', 0)):
            continue                     # udenlandsk post eller koordinat uden for DK
        lat, lon = _gmaps_naal(x.get('googleMapsUrl'), lat, lon)
        by_, _, sted = (s.strip() for s in navn.partition(','))
        if sted.lower().startswith(by_.lower()):
            by_ = ''
        out.append({'brand': 'Normal', 'name': ' '.join(p for p in ('Normal', by_, sted) if p),
                    'street': _normal_gade_nr(x.get('address')), 'postnr': pn,
                    'by': _ren(x.get('city')), 'lat': lat, 'lon': lon})
    out = _ret_kildefejl(_uniq(out))
    if not 140 <= len(out) <= 210:
        raise RuntimeError(f'normal: {len(out)} butikker (forventet 140-210) - behandles som '
                           f'en koerselsfejl, ikke som lukninger/aabninger')
    return out


# Kendte fejl hos Normal (30-09-2026). Noeglen er kaedens gadetekst EFTER _normal_gade_nr.
# Koordinaterne er LAEST UD AF CSV'EN (vores raekke for samme butik) - undtagen Haderslev,
# hvor vores raekke er den gamle butik; dér er det DAR-punktet for den adresse CVR, smiley
# og kaeden selv angiver. Kan flyttes ind i KILDEFEJL-literalen. For Køge, Viborg, Herlev,
# Egedal og Ballerup er navnene forskellige OG pinnene over 150 m fra hinanden: uden posten
# tilfoejer refresh_retail butikken som NY BUTIK - en dublet - og melder vores raekke som
# mulig lukning.
KILDEFEJL.update({
    # --- Kaedens pin er forkert; CVR, smiley og OSM staar paa vores raekke.
    # Normal Køge Brogade: kaedens pin staar 45 m fra dens egen 'Køge, Strædet' (Rådhusstræde
    # 8C) og 322 m fra DAR-punktet for Brogade 11. Vores raekke staar 2 m fra det; CVR
    # P 1021500484 har Brogade 11 siden 2016, og OSM-noden med samme P-nummer staar 0 m fra
    # vores raekke. Kaedens Google-link peger paa 'NORMAL Køge, Strædet'.
    ('Normal', 'brogade 11'): {'lat': 55.455436, 'lon': 12.182177},
    # Normal Viborg Sct. Mathias Gade: CVR P 1020550690 har nr. 33 siden 2015; vores raekke
    # og OSM-noden staar 1 m fra DAR-punktet for 33, kaedens pin 182 m vest ved nr. 15C.
    ('Normal', 'sct. mathias gade 33'): {'lat': 56.449438, 'lon': 9.407599},
    # Normal Aarhus Storcenter Nord: CVR P 1026265866 = Finlandsgade 17, 41 m fra vores
    # raekke (= OSM-vejen); kaedens pin staar 248 m vaek i et andet postnummer (8210).
    ('Normal', 'finlandsgade 17'): {'lat': 56.169714, 'lon': 10.188919},
    # Normal Rødovre Centrum: 'Rødovre Centrum 35' findes ikke i DAR. CVR P 1021152508 =
    # Rødovre Centrum 1M, 35 m fra vores raekke (= OSM-noden); kaedens eget Google-sted
    # ligger 57 m fra vores raekke og 190 m fra kaedens pin.
    ('Normal', 'rødovre centrum 35'): {'street': 'Rødovre Centrum 1N', 'lat': 55.679313, 'lon': 12.458711},
    # Normal Lyngby Storcenter: centrets egen butiksside siger 'i stueetagen, lige ved
    # indgangen fra Kanalvejsparken ... mellem Søstrene Grene og Joe & the Juice'. Kanalvej
    # er centrets oestside. Vores raekke (= OSM-noden 8598925318, shop=chemist) staar 14 m
    # fra vores Joe & The Juice Kanalvej og 63 m fra Søstrene Grene Lyngby Storcenter;
    # kaedens pin staar 183 m vaek i centrets sydvestlige hjoerne (01-10-2026).
    ('Normal', 'lyngby storcenter 1'): {'lat': 55.772424, 'lon': 12.50659},
    # --- UAFKLARET: kilderne er uenige om HVOR i centret butikken ligger (167-264 m).
    # Posterne holder vores pin, saa der ikke kommer en dublet. Revurdér; flyttes vores
    # raekke, skal posten slettes eller have de nye koordinater.
    # Normal Herlev Bymidte: FOR vores raekke: OSM-noden (P 1020550704, level 0,
    # start_date 2023-09-28), og den gamle OSM-node 200 m nord er sat til shop=vacant.
    # IMOD: CVR (Herlev Torv 28D -> Herlev Bygade 22 mellem 2022 og 2024), den nye
    # smiley-registrering 1359332 (Herlev Bygade 22), kaedens pin (29 m fra Herlev Bygade 22)
    # og kaedens Google-sted (5 m). Vores raekke staar 28 m fra centerbygningen (BBR 324).
    ('Normal', 'herlev torv 2'): {'lat': 55.723395, 'lon': 12.440382},
    # Normal Egedal Centret: FOR vores raekke (DAR-punktet for Centertorvet 4, lagt ind
    # 30-09-2026 ud fra kaedens tekst): kaedens tekst 'Centertorvet 4-8' og Egedal Centrets
    # egen butiksside (Centertorvet 4, rettet 26-03-2025). IMOD: CVR P 1020998578 (Egedal
    # Centret 90 siden 2019, 44E i 2016), smiley 577918 (Egedal Centret 90, sidst kontrolleret
    # 2017), kaedens pin (7 m fra Egedal Centret 90) og kaedens Google-sted (22 m). Ingen
    # OSM-node.
    ('Normal', 'centertorvet 4'): {'lat': 55.768270, 'lon': 12.195231},
    # Normal Ballerup Stationscenter: butikken er i Ballerup Centret (centrets egen
    # butiksliste; CVR P 1019794152 = Ballerup-Centret 2 siden 2019, foer Banetoften 30).
    # Vores raekke er DAR-punktet for Ballerup-Centret 2 (lagt ind 30-09-2026) ved
    # indkoerslen, 100 m fra centerbygningen (BBR 324, 1973); kaedens pin og navn samt den
    # gamle smiley-registrering ('Ballerup Stationscenter', Banetoften 30) peger paa
    # stationsdelen (BBR 324 Banegårdspladsen 3, 1989), 167 m fra vores. Ingen OSM-node.
    ('Normal', 'ballerup-centret 2'): {'lat': 55.728983, 'lon': 12.355854},
    # --- Ny og flyttet butik.
    # Normal Aalborg Kennedy Arkaden (aabnede 30-09-2026): CVR P 1032601460 og smiley
    # 1599052 har John F. Kennedys Plads 1B. Kaedens 'John F. Kennedys Pl. 1' findes ikke i
    # DAR ('Pl.' genkendes ikke, og der er kun 1A-1U), saa refresh_retail faldt tilbage til
    # adressen ved pinnen. Pinnen rettes af _gmaps_naal til Google-stedet (56 m fra 1B).
    ('Normal', 'john f. kennedys pl. 1'): {'street': 'John F. Kennedys Plads 1B'},
    # Normal Haderslev Bispegade: flyttede 29-04-2026 fra Gravene til Bispegade 15 (kaedens
    # pressemeddelelse 18-04-2026; CVR P 1021873221 skiftede adresse med virkning mellem
    # 15-04 og 01-05-2026; ny smiley-registrering 1515377). Kaedens pin staar stadig 77 m
    # fra vores GAMLE raekke (Nørregade 19 / Gravene 1). Koordinat = DAR-punktet for
    # Bispegade 15 (BBR-butiksbygningen Bispegade 13 staar 17 m derfra). Foerste ugekoersel
    # tilfoejer derfor 'Normal Haderslev Bispegade' og melder 'Normal Haderslev' som mulig
    # lukning; den gamle raekke skal slettes i haanden (eller flyttes hertil foerst).
    ('Normal', 'bispegade 15'): {'lat': 55.250509, 'lon': 9.485774},
})


# ---- Harald_Nyborg (etape 2, 30-09-2026: bygget af en efterforsker, genkoert og godkendt af en skeptiker)
# Kraever hjaelperne _robots_tilladt, _normal_gade_nr og _dk_postnr fra Normal-blokken
# (retail_sources.normal); indsaet den foerst.

HARALD_NYBORG_URL = 'https://www.harald-nyborg.dk/butikker'


def harald_nyborg():
    """Harald Nyborg (Harald Nyborg A/S, CVR 37783315) fra kaedens EGEN butiksliste.

    Kilde: www.harald-nyborg.dk/butikker. Siden er server-renderet og har HELE listen
    i window.initialQueryClientState - en dehydreret React Query-cache, hvor 'state' er
    en JSON-STRENG med JSON indeni (to json.loads). Listen ligger under queryKey
    '/internal/physicalshop/listAllPhysicalShops'.

    ROBOTS: 'Disallow: /api/' og 'Disallow: /internal/' for alle. Klientens eget kald
    til /internal/physicalshop/... er altsaa FORBUDT og maa ikke bruges direkte - men
    /butikker er tilladt, og dataene staar allerede i den side. Henteren laeser
    robots.txt ved hver koersel og fejler hoejt, hvis /butikker bliver forbudt.
    Sitemap'et (sitemap-bizzkitcms.xml) har kun /butikker, ingen butikssider.

    Efterproevet 30-09-2026: 74 butikker = vores 74, samme butikker. 70 parret inden
    for 150 m (median 28 m); de sidste 4 (Grenå, Næstved, Nykøbing Mors, Ribe) har
    kaedens pin 155-253 m fra vores raekke og 167-250 m fra DAR-punktet for kaedens egen
    adresse, mens vores raekke staar ved BBR-butiksbygningen med den adresse - rettes i
    KILDEFEJL. Tjek (883cJ) gav de samme 74 med samme pins og adresser. Kaeden skriver
    selv 'mere end 70 butikker' paa siden.

    FAELDER:
      * address har ekstra led: 'Løven 4, City Syd', 'Prøvestenscenteret, Birkedalsvej
        16', 'Herlev Hovedgade 41, BIG', 'Industrivej Syd 5, Birk'; intervaller
        ('Gladsaxevej 367-371', 'Fælledvej 1C-D') og 'Markedsvej 24 B'. Se _normal_gade_nr.
      * 14 af 74 adresser findes ikke ordret i DAR: stavemaader ('Gl. Lyngvej',
        'H.C.Ørstedsvej', 'Midtpunkt 37' for Hørsholm Midtpunkt) og bogstaver der
        mangler eller er for meget (Vejlevej 255 -> DAR 255C, Marsvej 19 -> 19C,
        Vindrosen 1A -> 1). Afstem paa koordinat, ikke paa tekst.
      * city kan have bydel efter komma ('Tilst, Århus', 'Viby J., Århus') og
        foranstillede mellemrum (' Haslev'); name kan have efterstillet mellemrum
        ('Hørsholm ').
      * Lat/lon er TEKST ('57.151698').
    Navn: 'Harald Nyborg <kaedens navn>', ' - ' -> ' ' ('Aarhus - Tilst' -> 'Aarhus
    Tilst') og uden formatet ' - Citybutik' (København NV/V), som vores raekker.
    Forventet: 74."""
    if not _robots_tilladt(HARALD_NYBORG_URL):
        raise RuntimeError('harald_nyborg: robots.txt paa www.harald-nyborg.dk forbyder nu '
                           '/butikker - henter ikke')
    h = _text(HARALD_NYBORG_URL, 90)
    m = re.search(r'window\.initialQueryClientState\s*=\s*', h)
    if not m:
        raise RuntimeError('harald_nyborg: initialQueryClientState findes ikke paa /butikker')
    ydre = json.loads(_balanced(h, h.index('{', m.end())))
    st = ydre.get('state', ydre)
    st = json.loads(st) if isinstance(st, str) else st
    butikker = None
    for q in (st or {}).get('queries') or []:
        if 'physicalshop' in json.dumps(q.get('queryKey')).lower():
            butikker = (q.get('state') or {}).get('data')
            break
    if not isinstance(butikker, list):
        raise RuntimeError('harald_nyborg: butikslisten (physicalshop) mangler paa /butikker')
    out = []
    for x in butikker:
        a = x.get('address') or {}
        pn = _dk_postnr(a.get('zipCode'))
        lat, lon = _dk_koord(a.get('latitude'), a.get('longitude'))
        if not pn or (lat is None and a.get('latitude') not in (None, '')):
            continue
        navn = re.sub(r'\s*-\s*citybutik$', '', _ren(x.get('name')), flags=re.I)
        navn = _ren(navn.replace(' - ', ' ')).rstrip('.')
        out.append({'brand': 'Harald Nyborg', 'name': f'Harald Nyborg {navn}',
                    'street': _normal_gade_nr(a.get('address')), 'postnr': pn,
                    'by': _ren(_ren(a.get('city')).split(',')[0]), 'lat': lat, 'lon': lon})
    out = _ret_kildefejl(_uniq(out))
    if not 60 <= len(out) <= 95:
        raise RuntimeError(f'harald_nyborg: {len(out)} butikker (forventet 60-95) - behandles '
                           f'som en koerselsfejl, ikke som lukninger/aabninger')
    return out


# Kendte pin-fejl hos Harald Nyborg (30-09-2026). KOORDINATERNE ER LAEST UD AF CSV'EN
# (vores raekke for samme butik); noeglen er kaedens gadetekst EFTER _normal_gade_nr. Navnene er
# ens, saa uden posterne ville refresh_retail melde fire KOORD-AFVIGELSER hver uge.
KILDEFEJL.update({
    # Harald Nyborg: kaedens pin 167-250 m fra adressen og paa en anden adresse (reverse:
    # Hesselvang 7, Lunavej 2, Næssundvej 9A, Bohrsvej 2); vores raekke staar 7-48 m fra
    # DAR-punktet og ved BBR-butiksbygningen med kaedens egen adresse (Næstved: centret
    # Vestergårdsvej 30).
    ('Harald Nyborg', 'hesselvang 20'): {'lat': 56.384362, 'lon': 10.865404},
    ('Harald Nyborg', 'vestergårdsvej 32'): {'lat': 55.254567, 'lon': 11.792685},
    ('Harald Nyborg', 'vester fald 4'): {'lat': 56.788959, 'lon': 8.827509},
    ('Harald Nyborg', 'industrivej 20c'): {'lat': 55.350747, 'lon': 8.778473},
})


# ---- foetex (etape 2, 30-09-2026: bygget af en efterforsker, genkoert og godkendt af en skeptiker)
# Salling Group: foetex.dk og bilka.dk er samme Nuxt 2-frontend. Butiksoversigten har
# kaedens egen butiksliste i window.__NUXT__ som stores:{<butiksnr>:"/kundeservice/
# find-butik/<slug>/c/<slug>/",...}. Adresse og koordinat henter siden derimod i
# browseren fra api.sallinggroup.com/v2/stores, og robots.txt paa api.sallinggroup.com
# er 'Disallow: /' med Allow KUN for /v1/ecommerce/*/search/ og /v1/ecommerce/*/cms/pages
# (laest 30-09-2026). Den sti kaldes derfor ikke - heller ikke med frontendens token.
SALLING_OVERSIGT = {
    'foetex': 'https://www.foetex.dk/kundeservice/find-din-foetex/',
    'bilka': 'https://www.bilka.dk/kundeservice/info/find-din-bilka/c/find-din-bilka/',
}
# Butikssider der staar i kaedens oversigt, selv om butikken er lukket. Hver post skal
# have sit belaeg skrevet ved siden af.
SALLING_UDGAAET = {
    # foetex.dk side 1346 'føtex City Vest' (Aarhus V). Siden er en tom CMS-skal som alle
    # butikssider (adressen kommer fra /v2/stores). Salling Group opgiver 119 butikker
    # under 'føtex, føtex food og føtex city' (sallinggroup.com/kaeder-butikker/noegletal,
    # pr. 31-08-2026) mod 120 sider; Tjek har 119 og ingen City Vest, og CVR har ingen
    # Salling-P-enhed i City Vest. De 119 andre sider parrer 1:1 med Tjek. (30-09-2026)
    'foetex-city-vest',
}
SALLING_SLAEK = 2    # tilladt forskel mellem Tjek og kaedens egen liste pr. maerke

# Tjek-koordinater der ligger 157-490 m fra vores pin. Toerkoersel af refresh_retail
# 30-09-2026 UDEN disse: 4 NY BUTIK (alle fire DUBLETTER - de har et andet navn end vores
# raekke og slipper under 10 %-spaerren, saa --apply ville skrive dem ind), 4 falske
# MULIG LUKNING og 6 ugentlige KOORD-AFVIGELSER. Koordinaterne er LAEST FRA
# dagligvarer_dk.csv 30-09-2026, og i 9 af 10 tilfaelde ligger vores pin 4-61 m fra
# DAR-punktet for butikkens egen adresse og/eller ved BBR-bygningen (322 detailhandel)
# paa den adresse; Tjeks pin goer ikke.
KILDEFEJL.update({
    # Tjek-pin ved Perlegade 81 (bymidten), 485 m fra DAR-punktet for Kastanie Alle 3
    ('føtex', 'kastanie allé 3'): {'lat': 54.909249, 'lon': 9.792012},
    # Tjek-pin ved H.C. Ørsteds Vej 27, 392 m fra nr. 4B; vores pin 4 m fra 4B
    ('føtex', 'hc ørstedsvej 4'): {'lat': 55.675844, 'lon': 12.545707},
    # 'Kanalgaden 1' findes ikke i DAR; vores pin staar ved BBR-butiksbygningen
    # (Kanaltorvet 1) og 42 m fra CVR-adressen Nordmarks Alle 10
    ('føtex', 'kanalgaden 1'): {'lat': 55.655568, 'lon': 12.355420},
    # DR Byen: Tjek-pin (4 decimaler) 147 m fra DAR-punktet for nr. 102, vores 50 m.
    # NB: vores raekke hedder 'føtex Ørestad, Amagerfælledvej 108'; kaeden OG CVR siger 102.
    ('føtex', 'amagerfælledvej 102'): {'lat': 55.656741, 'lon': 12.592205},
    # Fisketorvet: TVIVLSOM. Begge pins ligger i centret (BBR 324, 124.377 m2; 87 hhv.
    # 107 m fra bygningens punkt), men DAR-punktet for Kalvebod Brygge 59 er 40 m fra
    # Tjeks pin og 155 m fra vores. Flyttes CSV-raekken, skal denne post slettes.
    ('føtex', 'kalvebod brygge 59'): {'lat': 55.661658, 'lon': 12.559903},
    # Tjek-pin ved Emma Gads Vej 31; DAR nr. 13 og 15 ligger begge 5 m fra vores pin
    ('føtex food', 'michael strungesvej 15'): {'lat': 55.637912, 'lon': 12.581626},
    # Bilka: vores pin staar ved BBR-butiksbygningen paa kaedens egen adresse, Tjeks ikke
    ('Bilka', 'høegh guldbergsgade 10'): {'lat': 55.857608, 'lon': 9.852333},
    ('Bilka', 'niels bohrs alle 150'): {'lat': 55.378061, 'lon': 10.431422},
    ('Bilka', 'over bølgen 1'): {'lat': 55.598719, 'lon': 12.325443},
    ('Bilka', 'idagårdsvej 1'): {'lat': 55.390199, 'lon': 11.355717},
})


def _salling_kaedeliste(kaede):
    """Slugs i kaedens egen butiksliste (foetex.dk/bilka.dk), minus SALLING_UDGAAET."""
    url = SALLING_OVERSIGT[kaede]
    h = _text(url, 60)
    i = h.find('stores:{', max(0, h.find('window.__NUXT__')))
    if i < 0:
        raise RuntimeError(f'{kaede}: ingen stores:{{...}} i __NUXT__ paa {url} - '
                           f'siden er lagt om, og Tjek kan ikke efterproeves')
    blok = _balanced(h, i + len('stores:'))
    slugs = set(re.findall(r'\d+:"/kundeservice/find-butik/([^/"]+)/', blok))
    if len(slugs) < 10:
        raise RuntimeError(f'{kaede}: kun {len(slugs)} butikker i kaedens liste paa {url}')
    return slugs - SALLING_UDGAAET


def _salling_gade(s):
    """Tjek-gadetekst -> kun gade + husnummer. Tjek skriver etage, lokale og ekstra
    numre efter nummeret: 'Strandgade 83, St', "Ro's Torv 1, St 41", 'Nørre Voldgade
    94,96', 'Tordenskjoldsgade 21 St', 'Cityringen 24 DØR 392'. dawa.split_street
    laeser 'Cityringen 24 DØR 392' som vej 'Cityringen 24 DØR' nr. 392."""
    s = ' '.join((s or '').split()).split(',')[0].strip()
    return re.sub(r'\s+(?:st|kl|d[øo]r)\.?(?:\s+\S+)?$', '', s, flags=re.I)


def _salling_vagt(maerke, raekker, egne):
    if abs(len(raekker) - len(egne)) > SALLING_SLAEK:
        raise RuntimeError(f'{maerke}: Tjek har {len(raekker)} butikker, kaedens egen liste '
                           f'{len(egne)} - Tjek er ikke efterproevet og bruges ikke '
                           f'(behandles som en koerselsfejl, ikke som lukninger/aabninger)')


def foetex():
    """føtex og føtex food (Salling Group) fra eTilbudsavis/Tjek, som Salling selv fodrer
    (squid-api.tjek.com, forhandler bdf5A), EFTERPROEVET mod kaedens egen butiksliste paa
    foetex.dk/kundeservice/find-din-foetex/ ved hver koersel (SALLING_SLAEK).

    HVORFOR TJEK: foetex.dk har kaedens liste (120 butikssider, se SALLING_OVERSIGT), men
    ingen adresser; de kommer fra api.sallinggroup.com/v2/stores, som robots.txt forbyder,
    og developer-API'et kraever en noegle vi ikke har. Tjek bruges kun fordi den stemmer
    med kaedens EGEN liste - og det kontrolleres ved hver koersel.

    Kontrolleret 30-09-2026: Tjek 120 = 102 føtex (inkl. City og Go!) + 17 føtex food +
    1 føtex Outlet. De 119 butikker parrer 1:1 med kaedens sider; den 120. side (City Vest)
    er lukket, se SALLING_UDGAAET. Salling Group opgiver 119 (noegletal pr. 31-08-2026).
    Mod vores CSV: samme 102 + 17 butikker, ingen nye og ingen lukkede. 113 parrede inden
    for 150 m; 6 Tjek-pins laa 167-490 m fra vores og rettes i KILDEFEJL (5 paaviseligt
    forkerte, Fisketorvet tvivlsom).

    FORUDSAETNING FOER refresh_retail.KAEDER: vores raekke 'føtex Big, Herlev' (Herlev Torv
    24B) er i virkeligheden føtex Herlev (kaeden og CVR: Herlev Bygade 9; DAR-punktet 41 m
    fra pinnen) og skal omdoebes til 'føtex Herlev'. Ellers parrer refresh_retail den paa
    NAVN med kaedens rigtige 'føtex Big, Herlev' (Herlev Hovedgade 25, 805 m vaek), og
    --apply skriver føtex Herlev ind som dublet. Med omdoebningen: 0 nye, 0 lukninger.

    FAELDER:
      * Tjek har 'føtex Outlet Øst' (Cityringen 6, Taastrup) - et non-food-outlet, som
        hverken er paa foetex.dk's liste eller i Sallings optaelling. Frasorteres.
      * foetex.dk's butikssider er tomme CMS-skaller; siden for en lukket butik bliver
        staaende (City Vest). En side beviser altsaa ikke at butikken er aaben.
      * Tjeks ADRESSE er kaedens egen (CVR er enig i de fleste tilfaelde), men 5 af dens
        KOORDINATER er paaviseligt forkerte - Sønderborg 485 m inde i bymidten, City Hc
        Ørstedsvej 392 m. Se KILDEFEJL; pinnene kan ikke bruges ukontrolleret.
      * CVR har 'FØTEX FOOD BLEGDAMSVEJ' (Blegdamsvej 118) som aktiv P-enhed, men den er
        hverken hos kaeden eller i Tjek - CVR halter; brug den ikke som kilde.
      * Tjek-navnene er 'føtex Food X'; vores maerke og navne er 'føtex food X'.
      * Gadeteksten har etage/lokale efter nummeret - se _salling_gade. 'Rødovre Centrum
        198 1m' og 'Benediktssgade 46' (sic) staar som kilden skriver; de matches paa
        naerhed og normaliseres af DAWA, hvis de nogensinde bliver nye.
    Forventet: føtex 102, føtex food 17."""
    egne = _salling_kaedeliste('foetex')
    egne_food = {s for s in egne if s.startswith('foetex-food-')}
    er_food = lambda s: re.match(r'føtex\s+food\b', s.get('name') or '', re.I)
    fx = _tjek('bdf5A', 'føtex', forventet=(85, 125),
               behold=lambda s: not er_food(s) and 'outlet' not in (s.get('name') or '').lower())
    ff = _tjek('bdf5A', 'føtex food', forventet=(10, 30), prefiks='føtex food', behold=er_food)
    _salling_vagt('føtex', fx, egne - egne_food)
    _salling_vagt('føtex food', ff, egne_food)
    for r in fx + ff:
        r['street'] = _salling_gade(r['street'])
    return _ret_kildefejl(fx + ff)


def bilka():
    """Bilka (Salling Group) fra eTilbudsavis/Tjek (forhandler 93f13), EFTERPROEVET mod
    kaedens egen butiksliste paa bilka.dk/kundeservice/info/find-din-bilka/ ved hver
    koersel. Samme opbygning og samme grund som foetex() - se den og SALLING_OVERSIGT.

    Kontrolleret 30-09-2026: bilka.dk lister 19 sider = 18 Bilka + 'a-z-hjoerring';
    Tjek har de samme 19, og Salling Group skriver '18 lavprisvarehuse og et A-Z varehus'
    (sallinggroup.com/kaeder-butikker; noegletal: Bilka 19 pr. 31-08-2026).
    Mod vores CSV: samme 18 varehuse. 14 parrede inden for 150 m; 4 Tjek-pins laa 157-287 m
    fra varehuset (vores pin staar ved BBR-butiksbygningen, Tjeks ikke) - se KILDEFEJL.

    FAELDER:
      * 'A-Z Hjørring' (A. F. Heidemannsvej 20) ligger under Bilka baade hos Tjek og paa
        bilka.dk, men er Sallings A-Z-varehus, ikke en Bilka. Tjek har tidligere kaldt
        det 'Bilka Hjørring' (se _tjek), og med det navn slap det igennem baade navne-
        filtret og taellevagten (19 mod 18) - derfor frasorteres det OGSAA paa adressen.
      * Tjek-navnene har centernavne med komma: 'Bilka One Stop, Fields', 'Bilka Waves,
        Hundige'. De beholdes; 'Bilka Waves, Hundige' er derfor IKKE navnelig med vores
        'Bilka Hundige', og uden KILDEFEJL-rettelsen blev den en falsk ny butik.
      * Bilka Randers: Tjek og CVR skriver Merkurvej 53, vores raekke Minervavej 6 -
        pinnene ligger 46 m fra hinanden, saa det er samme varehus; matchningen sker
        paa naerhed.
    Forventet: 18."""
    egne = {s for s in _salling_kaedeliste('bilka') if s.startswith('bilka-')}
    az = lambda s: re.search(r'a\.?\s*f\.?\s*heidemanns?\s*vej', s.get('street') or '', re.I)
    bk = _tjek('93f13', 'Bilka', forventet=(14, 24),
               behold=lambda s: (s.get('name') or '').strip().lower().startswith('bilka')
                                and not az(s))
    _salling_vagt('Bilka', bk, egne)
    for r in bk:
        r['street'] = _salling_gade(r['street'])
    return _ret_kildefejl(bk)


# ---- Profil_Optik (etape 2, 30-09-2026: bygget af en efterforsker, genkoert og godkendt af en skeptiker)
def _optik_gade(s):
    """Optikerkaedernes adressefelt -> 'vejnavn husnr[bogstav]'.

    Felterne har linjeskift ('Adelgade 25G\\nStore Torv\\n'), etage/doer ('Algade 28,
    st. th', 'Skelagervej 7. st. 6'), centernavn efter komma ('Ørbækvej 75,
    Rosengårdcentret'), intervaller ('Nørrebrogade 122-124', 'Farum Bytorv 55+57',
    'Torvegade 3C+3D') og bogstav med mellemrum eller smaat ('Algade 69 A', 'Vasevej
    109a'). dawa.split_street klarer de fleste, men IKKE '+' (intet husnummer) og
    ikke '7. st. 6' (den giver husnr 6). Foerste husnummer vinder, som i vores raekker."""
    s = _ren((s or '').strip().split('\n')[0])
    m = re.match(r'^(.*?[^\d\s])\s*(\d+)(?:\s?([A-Za-zÆØÅæøå])(?![A-Za-zÆØÅæøå.]))?', s)
    return f'{m.group(1).strip()} {m.group(2)}{(m.group(3) or "").upper()}' if m else s


# Profil Optik, maalt 30-09-2026: kaedens ADRESSE er rigtig (den staar ens i finderen,
# paa butikssiden og i JSON-LD'en, og CVR-P-enhederne under Synsam Group Denmark A/S
# staar paa den: 'Profil Optik Herning 12070' paa Bredgade 11, 'Nordborg 12310' paa
# Stationsvej 6, 'Vejle 12215' paa Torvegade 3C, 'Fields København' paa Arne Jacobsens
# Allé 12), men kaedens pin staar 167-289 m vaek - i fem tilfaelde 1-16 m fra en ANDEN
# adresse. Vores raekker staar praecis paa DAR-punktet for kaedens adresse (0 m).
# Koordinaterne er LAEST FRA udvalgsvarer_dk.csv. Uden dem ville refresh_retail melde
# seks koordinat-afvigelser hver uge, og et navneskifte hos kaeden ville give en
# dubletraekke (kaedens pin er over 150 m fra vores raekke).
# OBS: noeglen er kun (maerke, gade). Aabner Profil Optik en butik paa samme gade og
# nummer i en ANDEN by (fx 'Stationsvej 6', 'Bredgade 11'), faar den disse koordinater.
# (Kan flyttes ind i KILDEFEJL-literalen.)
KILDEFEJL.update({
    # Herning: kaedens pin er Bredgade 30H (2 m), 214 m fra Bredgade 11
    ('Profil Optik', 'bredgade 11'): {'lat': 56.136121, 'lon': 8.973872},
    # Fields: kaedens pin er Ørestads Boulevard 94 (16 m), 182 m fra Arne Jacobsens Allé 12
    ('Profil Optik', 'arne jacobsens alle 12'): {'lat': 55.630999, 'lon': 12.575893},
    # Nordborg: kaedens pin er Ridepladsen 1 (4 m), 289 m fra Stationsvej 6
    ('Profil Optik', 'stationsvej 6'): {'lat': 55.056786, 'lon': 9.742359},
    # Rosengårdcentret: kaedens pin ligger 271 m fra centrets adresse Ørbækvej 75
    ('Profil Optik', 'ørbækvej 75'): {'lat': 55.382488, 'lon': 10.428085},
    # Taastrup: kaedens pin er Taastrup Torv 8 (4 m), 210 m vaek. DAR har 62A, 62B og 62C,
    # men ikke 62; CVR-P-enheden 'Profil Optik Taastrup' staar paa 62A, vores raekke paa
    # 62C (5 m fra 62A)
    ('Profil Optik', 'taastrup hovedgade 62'): {'street': 'Taastrup Hovedgade 62C',
                                                'lat': 55.650163, 'lon': 12.301360},
    # Vejle: kaedens pin er Nørregade 5D (1 m), 167 m fra Torvegade 3C
    ('Profil Optik', 'torvegade 3c'): {'lat': 55.708498, 'lon': 9.532938},
})


def profiloptik():
    """Profil Optik. /find-butik er Next.js pages-router, og HELE butikslisten ligger i
    __NEXT_DATA__ under props.pageProps.filteredStores - ét kald, ingen noegle. Felter:
    storeNumber, name, address, zip, city, lat, lng, findable, bookable, slug.
    Kilde: https://www.profiloptik.dk/find-butik. robots.txt forbyder kun /search og
    ?page=/?filter=/?f=-parametre.

    Kontrolleret 30-09-2026: 114 poster = 113 danske + Torshavn. De samme 114 slugs
    staar i sitemap.xml (/optiker/<slug>; de 10 oevrige /optiker-sider er by-sider).
    Mod vores 113 raekker: 107 paa samme punkt (0 m) og 6 med samme navn og adresse,
    men kaedens pin 167-289 m vaek (se KILDEFEJL ovenfor). Derefter 113/113, 0 nye,
    0 mulige lukninger. CVR (branche 477410): 112 af de 113 har en aktiv P-enhed under
    Synsam Group Denmark A/S (CVR 31058724) - 109 med kaedens storeNumber i navnet
    ('Profil Optik Herning 12070') og 3 uden nummer paa samme adresse; Rosengårdcentret
    findes kun som 'Synsam Recycling Store - Rosengårdscenteret' paa Ørbækvej 75. Ti af
    P-enhederne staar paa en anden, aeldre adresse end kaedens (fx Faaborg: Mellemgade 3
    for Torvegade 14), saa CVR-adressen er ikke bedre end kaedens.
    Kaeden skriver selv '115 butikker' paa /lokale-optiker (markedsfoeringstekst).

    FAELDER:
      * 'Profil Optik Torshavn NLA' (Hoyviksvegur 67, 110 Torshavn) er med i listen.
        Kraev 4-cifret postnr og dansk koordinat (_dk_koord).
      * CVR har stadig en aktiv P-enhed 'Profil Optik Aakirkeby 12361' (Eskildsgade 3),
        men den er ikke i finderen eller sitemappet, butikssiden giver 404, og
        adressen drives i dag af Borre & Severin Optik. CVR halter; finderen er aktuel.
      * name har efterstillede mellemrum ('Profil Optik Kolding Storcenter ') - _ren.
      * address er ikke altid en DAR-adresse ('Farum Bytorv 55+57', 'Nørrebrogade
        122-124', 'Ørbækvej 75, Rosengårdcentret', 'Algade 28, st. th') - _optik_gade.
      * city er postdistriktet uden bydel og med mellemrum ('Odense ' for 5220,
        'Randers' for 8900). DAWA saetter det rigtige navn paa nye raekker.
      * Kaedens pin er forkert paa 6 butikker, adressen ikke - rettet i KILDEFEJL.
      * Holstebros to butikker hedder blot 'Profil Optik Nørregade'/'Grønsgade' hos
        kaeden, og 'Profil Optik Ros Torv' hedder hos os '... RO's Torv Roskilde'.
        De tre matches paa afstand (0 m); de oevrige 110 navne er ens.
      * Der er intet aabningsdato-felt; en butik, der endnu ikke er aabnet, kan kun
        kendes paa findable=false (frasorteret). bookable=false har kun Torshavn.
      * 'Profil Optik Sports' er en afdeling i de almindelige butikker, ikke butikker.
    Forventet: 113."""
    d = _next_data(_text('https://www.profiloptik.dk/find-butik', 90))
    L = next((x for x in _find_key(d, 'filteredStores') if isinstance(x, list)), None)
    if not L:
        raise RuntimeError('profiloptik: filteredStores findes ikke i __NEXT_DATA__ paa /find-butik')
    out = []
    for x in L:
        pn = str(x.get('zip') or '').strip()
        lat, lon = _dk_koord(x.get('lat'), x.get('lng'))
        if not re.fullmatch(r'\d{4}', pn) or lat is None or x.get('findable') is False:
            continue
        out.append({'brand': 'Profil Optik', 'name': _ren(x.get('name')),
                    'street': _optik_gade(x.get('address')), 'postnr': pn,
                    'by': _ren(x.get('city')), 'lat': lat, 'lon': lon})
    out = _ret_kildefejl(_uniq(out))
    if not 90 <= len(out) <= 140:
        raise RuntimeError(f'profiloptik: {len(out)} butikker (forventet 90-140) - '
                           f'behandles som en koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Nyt_Syn (etape 2, 30-09-2026: bygget af en efterforsker, genkoert og godkendt af en skeptiker)
# Kraever _optik_gade() fra Profil Optik-blokken.
# Nyt Syn Roskilde, maalt 30-09-2026: kaedens pin er Algade 42 (3 m), 433 m fra
# butikkens adresse Stændertorvet 6 (ogsaa CVR: SØREN FRID OPTIQUE ApS, P-enhed paa
# Stændertorvet 6); vores raekke staar paa DAR-punktet (0 m, LAEST FRA CSV'EN).
# Kaedens navn ('Nyt Syn Roskilde - Søren Frid Optique') er ikke vores, saa uden
# rettelsen ville refresh_retail melde en NY BUTIK + en MULIG LUKNING og skrive
# butikken ind to gange (simuleret 30-09-2026: 2 nye af 59 slipper under spaerren).
# (Kan flyttes ind i KILDEFEJL-literalen.)
KILDEFEJL.update({
    ('Nyt Syn', 'stændertorvet 6'): {'lat': 55.641012, 'lon': 12.080954},
})


def nytsyn():
    """Nyt Syn. Butiksfinderen (AngularJS-komponenten <store-finder> paa /optiker)
    henter hele listen fra kaedens eget API - stien staar i /bundles/scripts.js
    (storeFinderService.getStores). Ét kald, JSON, ingen noegle:
        https://www.nytsyn.dk/api/store/getstores?countryCode=DK
    robots.txt forbyder kun /episerver/ og '/TODO SEARCH PAGE/'.

    Kontrolleret 30-09-2026: 63 poster -> 60 butikker. 58 af vores 59 raekker paa samme
    punkt (0 m); Roskilde har kaedens pin 433 m vaek (KILDEFEJL ovenfor). Den 60.
    MANGLEDE hos os: Nyt Syn Brande, Torvet 2 (DAR: Torvet 2A-2D; pinnen staar paa 2C),
    7330 Brande. Den er ikke ny (Id 11135), men butiksoversigten linker 'Nyt Syn
    Brande' til Bramming-siden. Butikssiden har aabningstider, syv medarbejdere og CVR
    44648962 (Nyt Syn 7330 Brande ApS; P-enheden 'Nyt Syn Brande' paa Torvet 2A er
    aktiv siden 01-03-2024). countryCode=FO giver Torshavn, GL giver Sisimiut og
    Aasiaat; de kommer ikke med i DK-kaldet. Kaeden skriver selv 'mere end 60
    butikker' (60 danske + 3 i FO/GL).
    CVR (branche 477410) har 42 aktive P-enheder, hvor P-enheden eller ejerselskabet
    hedder 'Nyt Syn ...'. De fire adresser, API'et ikke har, er hovedkontoret
    (Skæringvej 98, Lystrup), Bogense (lukket), Langeskov Centret (lagt sammen med
    Kerteminde; Langeskov Handels side for Nyt Syn viser i dag butikken paa Langegade
    29 i Kerteminde) og Brandts Passage i Odense (butikssiden giver 404; ejerselskabet
    Nyt Syn Odense ApS driver i dag Folkebo). API'et er altsaa mere aktuelt end CVR.

    FAELDER:
      * Svaret har to GRUPPESIDER ('Randers butikkerne', 'Aarhus butikkerne') og en
        LUKKET butik ('Nyt Syn Bogense' - siden siger 'Nyt Syn Bogense er lukket').
        Alle tre har tomt Id og Position 0,0. Kraev Id og dansk koordinat.
      * Groenlands postnumre er 4-cifrede (3911 Sisimiut, 3950 Aasiaat i GL-kaldet),
        saa det er koordinattjekket (_dk_koord), ikke postnummeret, der holder dem ude.
      * CanReserveInStore er False paa fem AABNE butikker (Optikkens Hus, Holms
        Optik, Søborg, Slagelse, Brovst) - feltet siger intet om aaben/lukket.
      * De haandskrevne lister paa /optiker og /om-nyt-syn/butiksoversigt er
        foraeldede: de linker til Jyderup, Middelfart og Skagen (404) og til Bogense
        (lukket), og 'Nyt Syn Brande' peger paa Bramming-siden. Brug kun API'et.
      * StreetName har linjeskift og ekstra linjer ('Adelgade 25G\\nStore Torv\\n',
        'Skelagervej 7. st. 6') - _optik_gade. City kan have punktum ('København K.')
        og efterstillet mellemrum ('Vejle ').
      * Title er HTML-kodet ('Jesper&#39;s Optik') og ofte forretningens eget navn
        uden by ('Nyt Syn Theilgaard Optik' i Esbjerg, 'Nyt Syn Folkebo' i Odense M).
        Vores raekker har butiksoversigtens linktekster ('Nyt Syn Esbjerg'), og 16 af
        59 navne afviger - de matches paa afstand (alle 0 m).
      * Der er intet aabningsdato-felt; en butik, der endnu ikke er aabnet, kan ikke
        kendes i svaret.
    Forventet: 60."""
    L = _json('https://www.nytsyn.dk/api/store/getstores?countryCode=DK', 60)
    if not isinstance(L, list):
        raise RuntimeError(f'nytsyn: uventet svar fra /api/store/getstores: {str(L)[:200]}')
    out = []
    for x in L:
        c, p = x.get('Content') or {}, x.get('Position') or {}
        pn = str(c.get('Zip') or '').strip()
        lat, lon = _dk_koord(p.get('Lat'), p.get('Lng'))
        if (not str(x.get('Id') or '').strip() or lat is None
                or not re.fullmatch(r'\d{4}', pn) or (c.get('Country') or 'DK') != 'DK'):
            continue
        out.append({'brand': 'Nyt Syn', 'name': _ren(c.get('Title')),
                    'street': _optik_gade(c.get('StreetName')), 'postnr': pn,
                    'by': _ren(c.get('City')).rstrip('.').strip(), 'lat': lat, 'lon': lon})
    out = _ret_kildefejl(_uniq(out))
    if not 45 <= len(out) <= 80:
        raise RuntimeError(f'nytsyn: {len(out)} butikker (forventet 45-80) - '
                           f'behandles som en koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Fluegger (etape 2, 30-09-2026: bygget af en efterforsker, genkoert og godkendt af en skeptiker)
# ---------------------------------------------------------------- Nuxt 2-hjaelpere
_JS_TAL = re.compile(r'-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?')
_JS_NAVN = re.compile(r'[A-Za-z_$][\w$]*')


def _js_vaerdi(s, i, var):
    """Parse ÉN JS-literal fra s[i] -> (vaerdi, position efter den).

    Nuxt 2 skriver sin tilstand med devalue: noegler staar uden anfoerselstegn, og
    gentagne vaerdier er erstattet af parameternavne (a, b, aj, a$ ...). Navnene slaas
    op i var = {parameternavn: argument}. Kun det devalue faktisk udsender er med:
    strenge, tal, true/false/null, void 0, Array(n), objekter og lister."""
    while s[i] in ' \t\r\n':
        i += 1
    c = s[i]
    if c == '"':
        j = i + 1
        while s[j] != '"':
            j += 2 if s[j] == '\\' else 1
        return json.loads(s[i:j + 1]), j + 1
    if c in '{[':
        slut, ud, i = ('}' if c == '{' else ']'), ({} if c == '{' else []), i + 1
        while True:
            while s[i] in ' ,\t\r\n':
                i += 1
            if s[i] == slut:
                return ud, i + 1
            if c == '[':
                v, i = _js_vaerdi(s, i, var)
                ud.append(v)
                continue
            if s[i] == '"':
                k, i = _js_vaerdi(s, i, var)
            else:
                m = _JS_NAVN.match(s, i) or _JS_TAL.match(s, i)
                if not m:
                    raise ValueError(f'uventet noegle i Nuxt-data ved position {i}')
                k, i = m.group(0), m.end()
            ud[k], i = _js_vaerdi(s, s.index(':', i) + 1, var)
    m = _JS_TAL.match(s, i) if (c.isdigit() or c in '-.') else None
    if m:
        t = m.group(0)
        return (float(t) if re.search(r'[.eE]', t) else int(t)), m.end()
    m = _JS_NAVN.match(s, i)
    if not m:
        raise ValueError(f'uventet tegn {c!r} i Nuxt-data ved position {i}')
    w, i = m.group(0), m.end()
    if w in ('true', 'false', 'null'):
        return {'true': True, 'false': False, 'null': None}[w], i
    if w == 'void':                                  # void 0 = undefined
        return None, re.compile(r'\s*0').match(s, i).end()
    if w == 'Array':                                 # Array(3) = 3 tomme pladser
        m = re.compile(r'\((\d+)\)').match(s, i)
        return [None] * int(m.group(1)), m.end()
    return var.get(w), i


def _js_hop(s, i):
    """Spring ét JS-udtryk over -> positionen for det ',' eller ')' der afslutter det.
    Til de argumenter _js_vaerdi ikke kender (new Date(...), Object.create(null) ...);
    de bruges ikke af butikslisten, men maa ikke vaelte hele henteren."""
    d = 0
    while True:
        c = s[i]
        if c == '"':
            i += 1
            while s[i] != '"':
                i += 2 if s[i] == '\\' else 1
        elif c in '([{':
            d += 1
        elif c in ')]}':
            if d == 0:
                return i
            d -= 1
        elif c == ',' and d == 0:
            return i
        i += 1


def _nuxt2(h):
    """Nuxt 2: window.__NUXT__=(function(a,b,...){return {...}}(v1,v2,...)).
    -> (var, krop): var = {parameternavn: vaerdi}, krop = funktionskroppens tekst, som
    _js_vaerdi(krop, i, var) kan laese fra. (Nuxt 3 og Next.js har _next_data/_flight.)"""
    m = re.search(r'window\.__NUXT__\s*=\s*\(function\(([^)]*)\)\s*\{', h)
    if not m:
        raise ValueError('window.__NUXT__ (Nuxt 2) ikke fundet')
    start = m.end() - 1
    krop = _balanced(h, start)
    i = start + len(krop)
    if h[i] != '(':
        raise ValueError('uventet form paa window.__NUXT__')
    args, i = [], i + 1
    while True:
        while h[i] in ' \t\r\n':
            i += 1
        if h[i] == ')':
            break
        try:
            v, j = _js_vaerdi(h, i, {})
            while h[j] in ' \t\r\n':
                j += 1
            if h[j] not in ',)':
                raise ValueError
        except (ValueError, AttributeError, IndexError):
            v, j = None, _js_hop(h, i)
        args.append(v)
        i = j + 1 if h[j] == ',' else j
    return dict(zip([p.strip() for p in m.group(1).split(',')], args)), krop


def _gade_ren(s):
    """Kildens gadefelt -> 'vej husnr'. Klipper centernavn, etage, bydel og parentes
    fra, og skriver husbogstavet sammen med nummeret. Maalte eksempler:
      'Gudenåcentret,Gl.Stationsvej 5' -> 'Gl.Stationsvej 5'
      'Prøvestenscenteret, Birkedalsvej 12' -> 'Birkedalsvej 12'
      'Kalvøvej 3, stuen' / 'Hedegårdsvej 1,  Durup' -> 'Kalvøvej 3' / 'Hedegårdsvej 1'
      'Farum Hovedgade 83 st. th.' / 'Dronning Dagmars Vej 208 ST' -> uden etagen
      'Kindhestegade 6B (Dania)' -> 'Kindhestegade 6B'
      'hjørringvej 163 a' -> 'Hjørringvej 163A'
    Intervaller ('Roskildevej 254-258') bevares; dem klarer dawa.split_street."""
    s = ' '.join(re.sub(r'\([^)]*\)', ' ', _ren(s)).split())
    led = [p.strip() for p in s.split(',') if p.strip()]
    s = next((p for p in led if re.search(r'[^\W\d_]{2,}.*\d', p)), led[0] if led else '')
    s = re.sub(r'\s+(?:st|stuen|kl|kld|kælder)\.?(?:\s+(?:th|tv|mf)\.?)?$', '', s, flags=re.I)
    s = re.sub(r'(\d)\s+([A-Za-zÆØÅæøå])$', lambda m: m.group(1) + m.group(2).upper(), s)
    return s[:1].upper() + s[1:]


FLUEGGER_URL = 'https://www.flugger.dk/kontakt/butikker/?page=40'


def fluegger():
    """Flügger farver fra kaedens EGEN butiksliste: www.flugger.dk/kontakt/butikker/.

    Siden er Nuxt 2 og server-renderer listen i window.__NUXT__ (fetch ->
    "data-v-...:0" -> stores: id, name, openingHours, address.streetAddress/postalCode/
    city/country/latitude/longitude). Den viser 8 butikker pr. side, men ?page=N faar
    sidens egen kode til at hente ALLE butikker til og med side N (loadPrevious=true
    mod api.flugger.dk/stores/b2c). page=40 giver plads til 320; hasMoreResults skal
    vaere false, ellers er listen afkortet, og henteren fejler hoejt.

    Kontrolleret 30-09-2026: 102 poster, alle 'Denmark'. 101 er aabne og ligger alle
    0 m fra vores 101 raekker (vores pins ER kaedens). Den 102. er Strandvejen 6,
    Koebenhavn OE: uden aabningstider, koordinat, e-mail og telefon. Kaedens egen nyhed
    ('Flügger rykker ind paa Oesterbro med to nye butikker') siger at den aabner
    'senere paa efteraaret'; Jagtvej 219 aabnede 1. september. Raekken blev fjernet fra
    kortet 30-09-2026 (commit a5dd937) og holdes ude her.

    robots.txt: www.flugger.dk har 'User-agent: * / Allow: /'. api.flugger.dk har
    ingen robots.txt (404), men kaldes ikke direkte: POST /stores/b2c svarede 400 uden
    de headere sidens JavaScript saetter (X-Forwarded-Host, X-Catalog-Id), og dem
    efterligner vi ikke. Den server-renderede side er et almindeligt GET.

    FAELDER:
      * Tjek/eTilbudsavis er FORAELDET for Fluegger (lukkede butikker og malerfirmaer
        der ikke laengere er Fluegger) - brug ikke _tjek her.
      * En butik der endnu ikke er aabnet staar paa listen UDEN aabningstider (alle
        openFrom = null). Den frasorteres; naar kaeden laegger tider ind, kommer den
        selv med. Kun Strandvejen 6 manglede tider 30-09-2026.
      * devalue: navne og byer er ofte parameternavne (name:aj), ikke tekst. Laes med
        _nuxt2/_js_vaerdi - et regex paa "name" giver et variabelnavn.
      * streetAddress er raa tekst: 'Gudenåcentret,Gl.Stationsvej 5', 'Kalvøvej 3,
        stuen', 'Farum Hovedgade 83 st. th.', 'Hedegårdsvej 1,  Durup', 'hjørringvej
        163 a' - se _gade_ren. Kaeden skriver 'Gl. Kongevej 137' og 'Rønnedevej 6 A',
        hvor DAR har Gammel Kongevej 137B og 6A; DAR-normaliseringen retter det.
      * To af kaedens husnumre FINDES IKKE i DAR (slaaet op 30-09-2026): Koege
        'Københavnsvej 155' (vores 151, 40 m fra pinden) og Roedovre 'Erhvervsvej 25'
        (vores 23, 42 m). Vores raekker er rigtige; kaedens pin er den samme.
      * postnr/by er kaedens: 'Esbjerg' 6700 (DAR: 6715 Esbjerg N), 'Fakse' (Faxe),
        'Odense Sø', 'Aalborg Sv'.
      * Navne: 'Flügger farver <kaedens navn>'. Kaeden bruger bynavnet, saa to butikker
        i samme by (Fredericia, Koege, Roedovre, Silkeborg, Skive, Kbh. OE) faar
        ', <vej>' efter, og ', <vej nr>' naar de ogsaa deler vej (Frederiksberg C,
        Gl. Kongevej 137 og 148) - som i CSV'en.
      * Roedovre, Islevdalvej 122 (hverdage 06-16, lukket i weekenden) er kaedens nye
        butik 'maalrettet professionelle malere' (tidl. PP Professional Paint). Den staar
        paa kaedens B2C-liste og paa kortet og er ikke en fejl.
      * Kaedens 'Fakta om Flügger' siger 115 forretninger i Danmark; siden er fra
        omkring 2015 (naevner 125-aars jubilaeet og Kina). Butikslisten er sandheden.
    Forventet: 101 (102 poster minus Strandvejen 6, til den aabner)."""
    h = _text(FLUEGGER_URL, 120)
    var, krop = _nuxt2(h)
    i = krop.find('stores:[')
    if i < 0:
        raise RuntimeError('fluegger: "stores:[" findes ikke i window.__NUXT__')
    L, slut = _js_vaerdi(krop, i + len('stores:'), var)
    m = re.compile(r'hasMoreResults:([\w$]+)').search(krop, slut)
    mere = var.get(m.group(1), m.group(1)) if m else None
    if mere not in (False, 'false'):
        raise RuntimeError(f'fluegger: hasMoreResults={mere!r} - listen er afkortet ved '
                           f'{len(L)} butikker; haev page= i FLUEGGER_URL')
    out = []
    for x in L:
        a = x.get('address') or {}
        if (a.get('country') or 'Denmark').strip().lower() not in ('denmark', 'danmark', 'dk'):
            continue
        pn = str(a.get('postalCode') or '').strip()
        if not re.fullmatch(r'\d{4}', pn):
            continue
        dage = ((x.get('openingHours') or {}).get('weekdays') or {}).values()
        if not any((d or {}).get('openFrom') for d in dage):
            continue                    # ingen aabningstider = ikke aabnet endnu
        la, lo = _dk_koord(a.get('latitude'), a.get('longitude'))
        out.append({'brand': 'Flügger', 'name': _ren(x.get('name')),
                    'street': _gade_ren(a.get('streetAddress')), 'postnr': pn,
                    'by': _ren(a.get('city')), 'lat': la, 'lon': lo})
    vej = lambda r: re.sub(r'\s+\d.*$', '', r['street'])
    n_navn, n_vej = {}, {}
    for r in out:
        n_navn[r['name']] = n_navn.get(r['name'], 0) + 1
        n_vej[(r['name'], vej(r))] = n_vej.get((r['name'], vej(r)), 0) + 1
    for r in out:
        kerne = r['name']
        if n_navn[kerne] > 1:
            kerne += ', ' + (r['street'] if n_vej[(r['name'], vej(r))] > 1 else vej(r))
        r['name'] = 'Flügger farver ' + kerne
    if not 80 <= len(out) <= 130:
        raise RuntimeError(f'fluegger: {len(out)} butikker (forventet 80-130) - '
                           f'behandles som en koerselsfejl, ikke som lukninger/aabninger')
    return _ret_kildefejl(out)


# ---- Fri_BikeShop (etape 2, 30-09-2026: bygget af en efterforsker, genkoert og godkendt af en skeptiker)
def fribikeshop():
    """Fri BikeShop fra kaedens EGEN butiksliste: www.fribikeshop.dk/butikker/.

    Siden (Umbraco + Vue) har hele listen i sin indlejrede JSON under "stores" - to
    gange: foerst den fulde liste (guid, isDeleted, information.name/address/
    cvrNumber, openingHours, settings), senere en kort (name, address, link) som ogsaa
    staar paa forsiden. Vi bruger den fulde, fordi den har isDeleted.
    address: address/zipCode/city/latitude/longitude/region.

    Kontrolleret 30-09-2026: 97 butikker, ingen isDeleted, begge lister ens (samme 97
    guid, navne og adresser). Alle 97 ligger 0 m fra vores 97 raekker og har samme
    navn (vores pins ER kaedens). Kaeden siger selv 'tæt på 100 butikker' og 'over 90
    butikker'. Tjek er ikke brugt: kaedens egen liste er tilgaengelig.

    robots.txt (www.fribikeshop.dk) forbyder /umbraco, /sog, /soeg, /search, kurv/
    checkout m.m. og URL'er med ?f_/?s_ - /butikker/ er tilladt.

    FAELDER:
      * Sitemappet har 5 butikssider UDEN for listen, og de er IKKE butikker: Aabenraa
        (udtraadt af kaeden 30/9-2024), Mejdal (udtraadt 22/8-2025) og Bjerringbro
        (lukket 31/1-2023) staar som lukke-sider; Lynge er en foraeldreloes side (sidst
        rettet 5/5-2025, intet butiksobjekt); skagen/shop-in-shop er en varekategori.
        Brug derfor listen, ikke sitemappet.
      * /butikker/koebenhavn/amager (listens link) viderestilles til .../amagerbro/.
      * address er raa tekst: 'Prøvestenscenteret, Birkedalsvej 12', 'Dronning Dagmars
        Vej 208 ST', 'Kindhestegade 6B (Dania)', 'Tårnvej 229, 231', 'Ove Jensens Allé
        19 C' - se _gade_ren. Intervaller ('Roskildevej 254-258') bevares.
      * Frederiksberg: kaeden skriver 'Peter Bangs Vej 38', som IKKE findes i DAR
        (slaaet op 30-09-2026); vores 'Peter Bangs Vej 36' findes, 41 m fra pinden,
        og kaedens pin er identisk med vores. CVR har butikkens P-enhed (Fri Bikeshop
        Frederiksberg ApS) paa hjoernet, H.V. Nyholms Vej 2, som ogsaa er DAR-adressen
        naermest pinden (13 m).
      * city kan have efterstillet mellemrum ('Frederikssund ').
      * 'Aarhus, Frederiks Allé elcykler' (nr. 160) er en SELVSTAENDIG elcykelbutik
        over for 'Aarhus, Frederiks Allé' (nr. 139) - ikke en dublet.
      * information indeholder ejerens navn; det bruges ikke.
      * Listen har intet 'aabner snart'-felt. En butik uden aabningstider paa nogen
        ugedag frasorteres derfor som ikke aabnet endnu - samme regel som fluegger().
        30-09-2026 havde alle 97 tider, saa reglen fjerner ingen i dag.
      * Skagen: kaedens adresse og pin, Vestre Strandvej 4 (DAR: 4A), er ejernes
        saesonudlejning Skagen BikeRental (OSM: 'Skagen BikeRental', 2 m fra pinden).
        Samme butiksside siger 'Resten af aaret foregaar udlejning fra vores butik paa
        Fiskergangen'. eTilbudsavis, OSM (Fri BikeShop, check_date 2025-08-30) og CVR
        (FRI BIKESHOP SKAGEN ApS, Fiskergangen 10, 2007 til 6-1-2026) har butikken paa
        Fiskergangen 10, 291 m derfra. Ejerskiftet i januar 2026 (CVR 45994759, Skagen
        Bikerental ApS) goer det uafklaret, om butikken er flyttet. Bekraeft foer
        CSV'en rettes; ret den saa ogsaa i KILDEFEJL med koordinaten fra CSV'en.
      * CVR 30-09-2026: 89 af 97 har en aktiv P-enhed fra butikkens eget CVR-nr. inden
        for 150 m. De otte andre er ejerens bopael (Ringsted, Soeborg, Frederikshavn/
        Skagen: Kavallerivej 5 er et parcelhus), foraeldede CVR-adresser (Grenaa
        Noerregade 2, Viborg H.C. Andersens Vej 2; kaedens side, OSM og nettet siger
        Markedsgade 51 og Jegstrupvej 17), Randers C uden egen P-enhed, og Roedovre
        Roskildevej, hvis P-enhed paa nr. 254 ikke kunne slaas op i DAR. CVR halter:
        Mejdals P-enhed hedder stadig 'Fri Bikeshop Holstebro Aps Mejdal', selv om
        butikken udtraadte 22-8-2025.
    Forventet: 97."""
    h = _text('https://www.fribikeshop.dk/butikker/', 90)
    L = None
    for m in re.finditer(r'"stores"\s*:\s*\[', h):
        try:
            c = json.loads(_balanced(h, h.index('[', m.start()), '[', ']'))
        except ValueError:
            continue
        if c and isinstance(c[0], dict) and 'information' in c[0]:
            L = c
            break
    if L is None:
        raise RuntimeError('fribikeshop: "stores" med information findes ikke paa /butikker/')
    out = []
    for x in L:
        if x.get('isDeleted'):
            continue
        inf = x.get('information') or {}
        a = inf.get('address') or {}
        pn = str(a.get('zipCode') or '').strip()
        if not re.fullmatch(r'\d{4}', pn):
            continue
        oh = x.get('openingHours') or {}
        if not any(oh.get(d + 'Open') for d in ('monday', 'tuesday', 'wednesday', 'thursday',
                                                  'friday', 'saturday', 'sunday')):
            continue                    # ingen aabningstider = ikke aabnet endnu
        navn = _ren(inf.get('name'))
        if not navn.lower().startswith('fri bikeshop'):
            navn = ('Fri BikeShop ' + navn).strip()
        la, lo = _dk_koord(a.get('latitude'), a.get('longitude'))
        out.append({'brand': 'Fri BikeShop', 'name': navn,
                    'street': _gade_ren(a.get('address')), 'postnr': pn,
                    'by': _ren(a.get('city')), 'lat': la, 'lon': lo})
    if not 70 <= len(out) <= 130:
        raise RuntimeError(f'fribikeshop: {len(out)} butikker (forventet 70-130) - '
                           f'behandles som en koerselsfejl, ikke som lukninger/aabninger')
    return _ret_kildefejl(_uniq(out))


# ---- Maxi_Zoo (etape 2, 30-09-2026: bygget af en efterforsker, genkoert og godkendt af en skeptiker)
# ---------------------------------------------------------------- Maxi Zoo
# Tilfoejet 30-09-2026. refresh_retail.py: EJER['maxizoo'] = ['Maxi Zoo'] og 'maxizoo' i
# KAEDER; KATEGORI['Maxi Zoo'] = 'udvalgsvarer'. _maxizoo_gade_nr, _dato_i og _IKKE_BUTIK bruges
# ogsaa af skoringen().
_BOGSTAV = 'A-Za-zÆØÅæøå'
# Poster i en kaedes butiksliste, som ikke er butikker. Ingen af de to kilder har dem
# 30-09-2026 - vagten er til den dag kaeden laegger webshoppen eller lageret ind.
_IKKE_BUTIK = re.compile(r'(?i)\b(web-?shop|lager|centrallager|hovedkontor|kontor|administration)\b')


def _maxizoo_gade_nr(s):
    """Gade + husnummer ud af en adresselinje med centernavn, etage og intervaller.

    Kaedernes adressefelt er ikke en DAR-betegnelse: 'Spinderiet, Valby Torvegade 13',
    'Silkeborgvej (hjørnearkaden) 39', 'Amagerbrogade 34, st.th.', 'Stürups Plads
    1/Stengade', 'Kinavej 8 A+B', 'Langebro 40 B'. dawa.split_street klarer komma-led
    og etager, men ikke en parentes midt i vejnavnet, '/' eller 'A+B' - saa falder
    normaliseringen tavst tilbage til reverse-adressen, og kildens husnummer gaar tabt.
    -> 'Valby Torvegade 13', 'Silkeborgvej 39', 'Amagerbrogade 34', 'Stürups Plads 1',
       'Kinavej 8A', 'Langebro 40B'. Et led uden husnummer ('Kolding Storcenter')
    returneres som det er."""
    s = re.sub(r'\([^)]*\)', ' ', _ren(s))
    led = [' '.join(p.split()) for p in re.split(r'[,/]', s)]
    led = [p for p in led if p]
    # foerste led med et ord paa mindst to bogstaver efterfulgt af et husnummer;
    # etage-led ('st.th.', '1. 44', 'st.1') og centernavne uden tal springes over
    med_nr = [p for p in led if re.search(r'[%s]{2}.*\s\d' % _BOGSTAV, p)
              and not re.match(r'(?i)(st|stuen|kl|kld)\b', p)]
    g = (med_nr or led or [''])[0]
    g = re.sub(r'(\d)\s*-\s*(\d)', r'\1-\2', g)                            # '251 - 261'
    g = re.sub(r'(\d)\s+([%s])(?=$|[\s+-])' % _BOGSTAV, r'\1\2', g)        # '40 B' -> '40B'
    g = re.sub(r'(\d[%s]?)\+[%s]$' % (_BOGSTAV, _BOGSTAV), r'\1', g)      # '8A+B' -> '8A'
    return g


def _dato_i(tekst, idag):
    """'Åbner 2/10' / 'Lukker 31.12.26' -> datetime.date eller None. Uden aarstal
    vaelges den dato der ligger NAERMEST idag, hoejst et halvt aar frem eller
    tilbage: 'Åbner 5/1' set i december er januar naeste aar, og 'Åbner 2/10' set i
    januar er oktober i FJOR.

    FAELDE (fundet i review 30-09-2026): foerste udgave rykkede kun datoer, der laa
    over et halvt aar TILBAGE. Glemmer kaeden at fjerne '(Åbner 2/10)' efter
    aabningen, blev datoen fra 1. januar til 2/10 i det nye aar - butikken forsvandt
    fra listen og blev meldt som mulig lukning hver uge til oktober. Tilsvarende
    blev '(Lukker 31/12)' set i januar til 31/12 i det nye aar, og en lukket butik
    blev staaende. Et aarstal kan kun staa efter '/' eller '.' - '2/10-12/10' er et
    interval, ikke aar 2012."""
    import datetime as _dt
    m = re.search(r'(\d{1,2})\s*[/.]\s*(\d{1,2})(?:\s*[/.]\s*(\d{2,4}))?', tekst)
    if not m:
        return None
    dag, md = int(m.group(1)), int(m.group(2))
    try:
        if m.group(3):
            aar = int(m.group(3))
            return _dt.date(aar + 2000 if aar < 100 else aar, md, dag)
        d = _dt.date(idag.year, md, dag)
        if (idag - d).days > 183:
            d = _dt.date(idag.year + 1, md, dag)
        elif (d - idag).days > 183:
            d = _dt.date(idag.year - 1, md, dag)
    except ValueError:
        return None
    return d


def maxizoo():
    """Maxi Zoo (Fressnapf-koncernen). maxizoo.dk er en Shopify-butik; butiksfinderen
    paa /pages/butikker er en Stockist.co-widget (data-stockist-widget-tag
    "map_pqkjnry3" 30-09-2026), og widget.min.js henter HELE listen i ét kald:
        https://stockist.co/api/v1/<tag>/locations/all
    Kaeden vedligeholder selv listen i Stockist; hver post linker til kaedens egen
    butiksside (custom field 'Se butik' -> /pages/butikker/<slug>). Tagget laeses fra
    siden ved hver koersel: skifter kaeden kort, ville det gamle tag blive ved med at
    svare - med en foraeldet liste og uden fejl.
    robots.txt (30-09-2026): stockist.co har 'User-agent: * / Disallow:' (alt
    tilladt, kun ia_archiver er udelukket); maxizoo.dk forbyder kun Shopifys
    standardstier (cart, checkout, account, policies m.fl.). Ingen af dem naevner
    ClaudeBot.

    Efterproevet 30-09-2026: 88 poster = 86 butikker + 2 skabelonposter. De 86 er
    praecis de 86 butikssider i kaedens sitemap_metaobject_pages_1.xml (samme slugs),
    og de 85 aabne genfindes alle inden for 150 m af vores 85 raekker, alle under
    1 m og med samme navn. Kaeden skriver selv 'mere end 80 fysiske butikker'
    (/pages/about-us).
    Uafhaengigt (review 30-09-2026): CVR 10117224 (Maxi Zoo Denmark A/S) har 89
    aktive P-enheder = de 86 butikker (85 inden for 150 m; Kolding N's P-enhed staar
    paa Vejlevej 255A, 273 m fra pinnen) + administrationen i Ballerup + en dublet for
    Fields + 'Maxi Zoo Nykøbing Falster XXL', Eggertsvej 28 (start 1/9-2026). Den er
    ikke aabnet: kaedens side for Nykøbing F viser Guldborgsundcentret 40 med denne
    uges aabningstider, og hverken Stockist, sitemappet eller OSM har den. Ingen
    butiks-P-enhed er ophoert siden 2024 (kun filialkontoret Sletvej 2E, 30/4-2026).
    OSM har 70 Maxi Zoo-noder, alle inden for 326 m af en butik i listen.

    FAELDER:
      * To skabelonposter fra Stockist: navn 'Name', adresse 'Address Line 1',
        postnr 'Postal Code' og koordinat i Tjekkiet (49.70, 13.26). Kraev at navnet
        begynder med 'Maxi Zoo' OG en dansk koordinat.
      * Kommende butikker staar med aabningsdatoen i navnet: 'Maxi Zoo Fields
        (Åbner 2/10)' (Arne Jacobsens Allé 12; butikssiden viser lukket til fredag
        2/10-2026). De udelades til datoen; derefter tages de med, og parentesen
        fjernes fra navnet, hvis kaeden ikke selv har gjort det. En parentes uden
        dato ('Åbner snart') udelades, til kaeden retter navnet. 'Lukker <dato>'
        behandles spejlvendt. Datoen uden aarstal tolkes som den naermeste (se
        _dato_i): staar '(Åbner 2/10)' der stadig i januar, er Fields fortsat med.
        Staar den der endnu i april, ligger naeste 2/10 naermest, og butikken
        falder ud som mulig lukning - det kan ikke afgoeres uden aarstal.
      * Shopifys butiksvaelger (store-selector, click & collect) paa hver side har
        kun 84: Helsingør mangler (butikken har almindelige aabningstider) og Fields
        er ikke kommet med. Kontaktformularens butiksliste har 79. Ingen af dem er
        butiksregistret - brug Stockist.
      * postal_code og city er BYTTET om paa to poster (Frederiksberg Domus Vista:
        'Frederiksberg' / '2000', Rødovre Centrum: 'Rødovre' / '2610'). Postnummeret
        er det 4-cifrede tal i et af de to felter, byen det andet felt.
      * city er fritekst: 'Herlev BIG' (butiksnavnet), 'København Ø.' (punktum),
        'Århus C'/'Århus N' (DAR: Aarhus), 'Tåstrup' (DAR: Taastrup). Rettes ved
        DAWA-normaliseringen.
      * address_line_1 har centernavne i PARENTES midt i gaden ('Silkeborgvej
        (hjørnearkaden) 39', 'Frejasvej (Holbæk megacenter) 26') og foran et komma
        ('Vestamagercentret, Ugandavej 111') - se _maxizoo_gade_nr.
      * Widget-konfigurationen (api/v1/<tag>/widget.js) har max_results=100. Kommer
        svaret op paa 100, kan listen vaere klippet - saa fejler henteren hellere end
        at melde falske lukninger.
      * description er intern driftsinfo ('Hundevask ude af drift') - bruges ikke.
    Forventet: 85 (86 fra 2/10-2026, naar Fields har aabnet)."""
    import datetime as _dt
    idag = _dt.date.today()
    h = _text('https://www.maxizoo.dk/pages/butikker', 60)
    m = re.search(r'data-stockist-widget-tag="([A-Za-z0-9_]+)"', h)
    if not m:
        raise RuntimeError('Maxi Zoo: Stockist-widgetten findes ikke laengere paa /pages/butikker')
    d = _json(f'https://stockist.co/api/v1/{m.group(1)}/locations/all', 60)
    if not isinstance(d, list):
        raise RuntimeError(f'Maxi Zoo: uventet svar fra Stockist: {str(d)[:200]}')
    if len(d) >= 100:
        raise RuntimeError(f'Maxi Zoo: Stockist gav {len(d)} poster; widgetten har '
                           f'max_results=100 - kontrollér at listen ikke er klippet')
    out = []
    for x in d:
        navn = _ren(x.get('name'))
        if not navn.lower().startswith('maxi zoo') or _IKKE_BUTIK.search(navn):
            continue
        lat, lon = _dk_koord(x.get('latitude'), x.get('longitude'))
        if lat is None:
            continue
        m = re.search(r'\s*\(([^)]*)\)\s*$', navn)
        if m and re.search(r'(?i)åbn|kommer|snart', m.group(1)):
            dato = _dato_i(m.group(1), idag)
            if dato is None or dato > idag:
                continue                      # ikke aabnet endnu
            navn = navn[:m.start()].strip()
        elif m and re.search(r'(?i)lukke', m.group(1)):
            dato = _dato_i(m.group(1), idag)
            if dato is None or dato <= idag:
                continue                      # 'Lukket', eller lukkedatoen er naaet
            navn = navn[:m.start()].strip()
        pn, by = str(x.get('postal_code') or '').strip(), _ren(x.get('city'))
        if not re.fullmatch(r'\d{4}', pn) and re.fullmatch(r'\d{4}', by):
            pn, by = by, pn                   # byttet om i kilden
        if not re.fullmatch(r'\d{4}', pn):
            continue
        out.append({'brand': 'Maxi Zoo', 'name': navn,
                    'street': _maxizoo_gade_nr(x.get('address_line_1')),
                    'postnr': pn, 'by': by.rstrip('.'), 'lat': lat, 'lon': lon})
    return _ret_kildefejl(_uniq(out))


# ---- Skoringen (etape 2, 30-09-2026: bygget af en efterforsker, genkoert og godkendt af en skeptiker)
# ---------------------------------------------------------------- Skoringen
# Tilfoejet 30-09-2026. KRAEVER _maxizoo_gade_nr og _IKKE_BUTIK fra Maxi Zoo-blokken. refresh_retail.py:
# EJER['skoringen'] = ['Skoringen'] og 'skoringen' i KAEDER; KATEGORI['Skoringen'] = 'udvalgsvarer'.
# KILDEFEJL.update skal staa EFTER KILDEFEJL er defineret (fx i UDVALGSVARER-afsnittet).

# Skoringens pins i fem storcentre ligger 155-259 m fra DAR-punktet for kaedens EGEN
# adresse; vores fem raekker staar praecis paa adressepunktet (0 m, maalt 30-09-2026
# med dawa._q). CVR-P-enhederne har de samme adresser, og OSM-noderne for Kolding,
# Næstved og Rosengård ligger 51, 18 og 4 m fra vores punkt mod 248, 166 og 256 m fra
# kaedens. (De oevrige 77 Skoringen-raekker staar paa kaedens egen pin, under 6 m.)
# Uden disse meldte hver ugentlig koersel fem KOORD-AFVIGELSER. VAERDIERNE ER LAEST
# FRA CSV'EN.
KILDEFEJL.update({
    # Skoringen Korsør: naermeste adresse ved kaedens pin er Havnepladsen 2 (156 m vaek)
    ('Skoringen', 'havnearkaderne 13'): {'lat': 55.330488, 'lon': 11.139787},
    # Skoringen Kolding Storcenter: kaeden skriver kun centernavnet; centrets DAR-adresse
    # er Skovvangen 42. Kaedens pin ligger 247 m derfra (naermeste adresse Skovvangen 40)
    ('Skoringen', 'kolding storcenter'): {'street': 'Skovvangen 42', 'lat': 55.513908, 'lon': 9.460066},
    # Skoringen Næstved Storcenter: 'Næstved Storcenter 23' findes ikke i DAR, nr. 3 goer.
    # Kaedens pin ligger 155 m vaek (naermeste adresse Holsted Alle 1)
    ('Skoringen', 'næstved storcenter 23'): {'street': 'Næstved Storcenter 3', 'lat': 55.253270, 'lon': 11.780621},
    # Skoringen Rosengårdcentret: kaedens pin ligger 259 m fra Ørbækvej 75 (ved Ørbækvej 75B)
    ('Skoringen', 'ørbækvej 75'): {'lat': 55.382488, 'lon': 10.428085},
    # Skoringen Storcenter Nord (aabnet 27-08-2026): kaedens pin ligger 184 m fra
    # Finlandsgade 17 (naermeste adresse Åbogade 8)
    ('Skoringen', 'finlandsgade 17'): {'lat': 56.169353, 'lon': 10.188777},
})


def skoringen():
    """Skoringen (Skoringen Danmark, chainId 'SDK'). skoringen.dk er en Angular-app;
    butiksfinderen /find-butik henter hele kaedens liste - Danmark OG Norge - fra
    kaedens eget API i ét kald:
        https://api.skoringen.dk/api/stores
    (SPA_API_STORES_URL i sidens <script id="skoringen-app-state">; main-*.js kalder
    GET ${apiStoresUrl} og filtrerer paa chainId - intet andet filter i browseren).
    robots.txt (30-09-2026): api.skoringen.dk har ingen (404 = ingen begraensninger,
    RFC 9309 2.3.1.3); www.skoringen.dk forbyder kun /dk/, /no/, /campaigns*,
    /segments*, /globale-spots*, /highlighted-products* og /forfattere*. Ingen af
    dem naevner ClaudeBot.

    Efterproevet 30-09-2026: 154 poster = 82 'SDK' (countryId DK) + 72 'SNO' (Norge).
    De 82 er alle active/showOnWeb/isOpen og er samme 82 butikker som vores 82 raekker
    (81 med identisk navn; kaedens 'Skoringen, Slagelse Megacenter' er vores
    'Skoringen Slagelse, Megacenter' - refresh_retail ser bort fra kommaet); 77
    ligger inden for 6 m af vores punkt. De sidste fem er storcenterbutikker, hvor
    kaedens pin ligger 155-259 m fra DAR-punktet for dens egen adresse - de rettes i
    KILDEFEJL. Kaeden oplyser intet samlet butiksantal paa skoringen.dk (andre steder
    '160 butikker i Danmark og Norge'; API'et har 154).
    Listen er AKTUEL (review 30-09-2026): Storcenter Nord er med (CVR-P-enhed fra
    27-08-2026); de lukkede er ude - Hammel og Vanløse Kronen (active=false; Kronen
    Vanløses egen butiksliste har ikke Skoringen), Solrød Center 33, Holbæk Ahlgade
    66, Skælskør og Sorø (siderne 301-omdirigeres til /find-butik; Sorø-P-enheden
    ophoerte 31-07-2024). Frontenden (main-*.js, getApiStores) filtrerer KUN paa
    chainId; showOnWeb og showOnStoresOverview bruges ikke.

    FAELDER:
      * chainId 'SNO' er Skoringen Norge (norske postnumre er ogsaa 4-cifrede, saa
        et postnummer-tjek alene fanger dem ikke). Kun 'SDK' + countryId 'DK'.
      * Sitemappet har 84 butikssider (/find-butik/<slug>), men to af dem er LUKKEDE
        butikker, hvis sider stadig findes, med active=false i sidens app-state:
        Hammel (Østergade 30, id 2506) og Vanløse Kronen (Vanløse Torv 1, id 2211).
        API'et udelader dem; en sitemap-henter ville genindfoere dem hver uge.
        Tre slugs er desuden omdoebt (skoringen-roedovre-centrum ->
        skoringen-roedovre-roedovre-centrum, skoringen-naestved-storcenter ->
        skoringen-naestved-naestved-storcenter, skoringen-holbaek-city ->
        skoringen-holbaek-ahlgade-21), og Vejle Nørregades storeUrl ender paa '/',
        saa sidste led er tomt. Sammenlign aldrig paa slug.
      * Lukkede butikker 301-omdirigeres til /find-butik, mens deres P-enheder kan
        staa som AKTIVE i CVR i aarevis (Solrød Center 33, Holbæk Ahlgade 66 og
        Skælskør Algade 19 gjorde 30-09-2026). En slug der aldrig har fandtes, giver
        404. CVR er derfor ikke et lukketjek for Skoringen.
      * cvr-feltet i API'et er ikke til at stole paa: Hobro (Adelgade 23, aaben) har
        30998596, som ikke findes i CVR 2024-2026, og Nykøbing Mors' cvr (Smalbro Sko
        ApS) har kun en P-enhed i Thisted. Brug det ikke til noget.
      * Butikssidernes JSON-LD (Store) har ingen geo; koordinaten findes kun i
        API'et og i app-state. latitude/longitude er TEKST.
      * address2 er gadefeltet (= JSON-LD streetAddress). Det har centernavne i et
        komma-led ('Spinderiet, Valby Torvegade 13', 'Aalborgstorcenter,Hobrovej 452')
        og etager ('RO's Torv 1, st.1') - se _maxizoo_gade_nr. I centre er husnummeret ofte
        centerets INTERNE butiksnummer ('Fisketorvet ShoppingCenter 269', 'Frederiksberg
        Centret 1240', 'Glostrup Shoppingcenter 1021', 'City 2 - 345'); det er ikke
        DAR-adresser, og vores raekker har DAR-adressen (Kalvebod Brygge 59, Falkoner
        Alle 21, ...). Match derfor paa navn/koordinat, ikke paa gadetekst.
      * NY BUTIK i et storcenter kan faa en NABOADRESSE: med centrets interne nummer
        og en pin 150-260 m fra adressepunktet falder normaliseringen tilbage til
        reverse. Simuleret 30-09-2026 paa alle 82, som om de var nye: 71 fik praecis
        vores adresse, 11 en anden (fx 'Næstved Storcenter 23' -> 'Holsted Alle 1',
        'WAVES, Over Bølgen 15H' -> 'Hegnsgården 3', 'Frederiksberg Centret 1240' ->
        'Solbjerg Plads 4C', 'Brogade 17' -> 'Brogade 16B'). De tre butikker med de
        nyeste P-enheder (Storcenter Nord 27-08-2026, Slagelse Megacenter 16-08-2026,
        Holbæk Megacenter 31-12-2025) fik alle den rigtige. Efterse nye
        centerbutikker i ugens rapport.
      * address4 er IKKE et bedre alternativ: 'Exnergade' (stavefejl), 'Esbjerg
        Storcenter', '8000 Aarhus C' og tom for Kolding City.
      * city er postnummerets officielle navn ('Grenaa', 'Kongens Lyngby', 'Taastrup')
        og stemmer med vores 82; address3 er kaedens visningstekst ('8500 Grenå').
      * storeName er 'Skoringen, <sted>'; vores navne har intet komma efter
        'Skoringen' ('Skoringen København V, Fisketorvet').
      * openingFrom er 1753-01-01 (SQL Servers mindstedato) paa alle 154. En dato i
        fremtiden tolkes som en butik der ikke har aabnet endnu og udelades til da.
      * isOpen er IKKE 'aaben lige nu' (det er isOpenRightNow) - filtreres ikke.
      * SNEAX og Bagfocus er koncepter i Skoringen-butikkerne (isSneaxChain,
        isBagFocusChain), ikke egne butikker.
    Forventet: 82."""
    import datetime as _dt
    idag = _dt.date.today().isoformat()
    d = _json('https://api.skoringen.dk/api/stores', 60)
    if not isinstance(d, list):
        raise RuntimeError(f'Skoringen: uventet svar fra API: {str(d)[:200]}')
    out = []
    for x in d:
        if str(x.get('chainId') or '').upper() != 'SDK' or \
           str(x.get('countryId') or 'DK').upper() != 'DK':
            continue
        if x.get('active') is False or _IKKE_BUTIK.search(_ren(x.get('storeName'))):
            continue
        if str(x.get('openingFrom') or '')[:10] > idag:
            continue                          # ikke aabnet endnu
        pn = str(x.get('postalCode') or '').strip()
        if not re.fullmatch(r'\d{4}', pn):
            continue
        lat, lon = _dk_koord(x.get('latitude'), x.get('longitude'))
        navn = re.sub(r'^Skoringen\s*,\s*', 'Skoringen ', _ren(x.get('storeName')))
        by = _ren(x.get('city')) or _ren(re.sub(r'^\s*\d{4}\s+', '', x.get('address3') or ''))
        out.append({'brand': 'Skoringen', 'name': navn,
                    'street': _maxizoo_gade_nr(x.get('address2') or x.get('address4')),
                    'postnr': pn, 'by': by, 'lat': lat, 'lon': lon})
    return _ret_kildefejl(_uniq(out))


# ================================================================ ETAPE 3: TANKSTATIONER
# Tilfoejet 01-10-2026. Raekkerne har ogsaa 'lastbil' ('ja' = rent lastbilanlaeg), og
# refresh_retail matcher bil- og lastbilanlaeg hver for sig. shell_tank er kun til rapport.

# ---- UnoX (etape 3, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker)
# ---- Uno-X (etape 3, 01-10-2026; genkoert og rettet af skeptiker 01-10-2026)
# Kraever _robots_tilladt og _dk_postnr fra Normal-blokken (retail_sources.normal).

UNOX_URL = 'https://unoxmobility.dk/privat/find-station'
_UNOX_BRAENDSTOF = re.compile(r'blyfri|diesel|hvo|benzin', re.I)


def _unox_gade(s):
    """Uno-X' adressetekst -> 'Vej nr'.

    Truck-posterne er fastbreddefelter ('Lundvej 1' + 16 mellemrum), 'Balstrupvej 92 (GPS ADR)'
    har en intern note i parentes, 'Stenstrupvej 4, Doense' har landsbyen som ekstra komma-led,
    og '15 A' skrives '15A' som i DAR. Husnummer-intervaller ('Jagtvej 213-215', 'Møllegade
    14-22') bevares, fordi vores raekker skriver dem saadan."""
    s = re.sub(r'\s*\([^)]*\)', '', _ren(s))
    dele = [d.strip() for d in s.split(',') if d.strip()]
    med_nr = [d for d in dele if re.search(r'\d', d)]
    s = med_nr[0] if med_nr else (dele[0] if dele else '')
    return re.sub(r'(\d)\s+([A-Za-zÆØÅæøå])$', lambda m: m.group(1) + m.group(2).upper(), s)


def unox():
    """Uno-X (Uno-X Mobility Danmark A/S, CVR 33807910) fra kaedens EGEN stationsfinder:
    bilstationer (lastbil='') og Uno-X Truck-anlaeg (lastbil='ja').

    Kilde: unoxmobility.dk/privat/find-station. Siden er Next.js app-router; hele
    stationslisten (DK, NO og SE, 860 poster 01-10-2026) ligger i RSC-payloaden
    (self.__next_f.push) som "initialStations". /erhverv/find-station og kortet paa
    /erhverv/produkter/truckanlaeg (defaultFilter 'truck-dk') bruger SAMME liste - de to
    find-station-sider gav byte-identiske 860 poster, og 30-09 og 01-10 var ens.
    robots.txt: 'User-Agent: * / Allow: /' og ingen Claude-gruppe (laest 01-10-2026);
    _robots_tilladt tjekkes ved hver koersel. Ingen noegle, ingen WAF-udfordring, ét kald
    (~0,9 MB, under et sekund).

    Efterproevet 01-10-2026 mod tankstationer_dk.csv (Uno-X: 279 bil + 21 lastbil):
      * Bil: 279 i kilden = vores 279 = tallet kaeden selv skriver paa
        /privat/produkter/braendstof ('Tank Blyfri 95, Blyfri 100 og diesel paa 279 Uno-X
        stationer i Danmark'). Alle 279 parret, alle 0 m fra hinanden.
      * Lastbil: 81 Uno-X Truck-anlaeg i kilden mod vores 21 (de gamle YX-pins fra Go'ons
        partnerkort, som er praecis de 21). Alle 21 parret (efter KILDEFEJL hoejst 54 m);
        60 findes kun i kilden - 20 som eget truckspor ved en af vores Uno-X-bilstationer,
        40 som selvstaendige anlaeg. Kaeden oplyser intet antal for truck-nettet. CVR kan
        ikke efterproeve dem: selskabet har kun 3 P-enheder (hovedkontor, Rønne, 'Truck
        Ishøj 8034'). OSM har et Uno-X/YX-tankanlaeg inden for 150 m ved 32-33 af de 81.
        Skeptikerens efterproevning af de 60 nye: 47 har uafhaengig stoette (OSM-node
        25, BBR-tankbygning 325 eller dieseltank >= 20.000 l inden for 60 m 36, Uno-X'
        egne redaktionelle sider 8: Næstved-nyheden 13-04-2026, HVO-siden 'Ishøj, Køge,
        Roskilde, Randers og Horsens', truckladningssiden 'Nørresundby, Nyborg, Horsens,
        Vejen, Kolding, Padborg' + Køge); 13 har kun kaedens liste (Gilleleje, Rønne,
        Roskilde, Øm, Sorø, Holbæk, Tølløse, Kalundborg, Fakse, Padborg 3, Esbjerg N,
        Taulov, Aalborg) - OSM daekker truckoeer daarligt, og ubemandede dieselanlaeg
        staar ikke altid i BBR.

    FAELDER:
      * Truck-anlaeggene har brand=None (ikke 'Uno-X') og kendes paa truck=True +
        'Truckanlæg' i services. Deres products naevner ALDRIG diesel - kun AdBlue og
        Bio100 HVO, og 16 har en tom liste - saa braendstoflisten kan IKKE bruges som
        filter for lastbil. 'Tankning' i services foelger blot AdBlue og siger intet.
      * brand='El' (9) og 'El Truck' (2: 'Truck Køge EL', 'Truck Nyborg EL') er rene
        ladelokationer med active_tankning=False og hoerer ikke hjemme her (superladere-
        laget, hvis >=250 kW). De ligger paa samme adresse som truckanlaeggene i Køge og
        Nyborg, saa afstand kan ikke skille dem - flagene kan. (En tidligere optaelling
        paa 83 truckposter talte de to med.)
      * Tre TESTPOSTER med brand='Uno-X' og country='DK': 'Wayne Malmø' (svensk postnr
        21124), 'Wayne Herning' og 'Oberthur' (Rødovre) - opkaldt efter standerens og
        betalingsterminalens leverandoerer. De har fuelPointCount=0, products=None og ALLE
        tre koordinaten for Uno-X Albertslund (Roskildevej 117). Uden fuelPointCount-
        filteret giver de to falske stationer i Herning/Rødovre og en dublet i Albertslund.
      * 20 truckanlaeg har egen post (nr. 9xx/9xxx) men ligger 1-97 m fra en bilstation,
        fx 'Uno-X Truck Give 2' 1 m fra 'Give Diagonalvejen' og 'Uno-X Truck Nyborg' paa
        samme adresse som 'Nyborg, Storebæltsvej'. Det er selvstaendige lastbilspor (eget
        stationsnr., egen kortaftale) - IKKE dubletter; vores 'Uno-X Truck Purhus' og
        'Uno-X Truck Viborg' staar allerede saadan ved siden af bilstationen. Det samme
        gaelder truckcentre med flere maerker (Taastrup, Vejle DTC, Aarhus Vandvejen 5,
        Hirtshals, Sæby): ét anlaeg pr. maerke.
      * Kaedens truck-pins er ofte geokodede adresser ('Balstrupvej 92 (GPS ADR)'), ikke
        anlaeggets placering: Ringsted, Struer, Vejle og Aarhus ligger 70-149 m fra vores
        raekker, som staar ved BBR-tankbygningen/OSM-noden. Rettet i KILDEFEJL nedenfor;
        Ringsted (149 m) ville ellers glide over 150 m-graensen og give en falsk
        ny+lukket-melding. Pinnen for 'Uno-X Truck Hirtshals' er TEGN FOR TEGN den samme
        som Shells egen for 'SHELL CRT HIRTSHALS' (begge har geokodet Dalsagervej 3) - to
        anlaeg i Hirtshals Transportcenter, ikke en dublet. MEN validate.py regner samme
        koordinat under to maerker i tankstationer_dk.csv som en HAARD fejl (XDUP_HAARD),
        saa pinnen flyttes i KILDEFEJL til DAR-punktet for kaedens egen adresse.
        Sæby-pinnen er en geokodning af 'Trafikcenter Sæby (Syd) 1' og staar 9 m fra OK
        Sæby; Brande-pinnen staar 42 m fra OSM's 'OK Truck Diesel' og 111 m fra OSM's
        'Uno-X Truck'. Begge rettet i KILDEFEJL (se belaegget dér).
      * UAFKLAREDE PLACERINGER (ikke rettet, fordi intet belaeg peger paa et bestemt
        punkt): 'Uno-X Truck Korsør' staar paa DAR-punktet Storebæltsvej 44, 13 m fra OK
        Korsør; paa samme grund staar et andet tankanlaeg 110 m mod oest (BBR 325 fra
        2004, 75.000 l-tank, unavngiven OSM-node), som lige saa vel kan vaere OK's eget.
        'Uno-X Truck Køge' og vores 'Go'on Køge' (lastbil) skriver begge 'Centervej 2',
        som ikke findes i DAR, og BBR har kun ét anlaeg ved de to pins (Servicevej 1, 2020,
        fire dieseltanke paa 50-100.000 l; Circle K's og Shells truckanlaeg paa Centervej 4
        ligger 135-160 m derfra) - muligvis en faelles facilitet. 'Uno-X Truck Kolding 1'
        (Birkedam 14) er i OSM (2022) tagget 'OK Truck Diesel Kolding'.
      * Navnene er IKKE entydige: 'Frederiksværk', 'Skive', 'Kastrup', 'Korsør' og
        'Rødovre Roskildevej' er hver to forskellige bilstationer. Brug koordinaten.
      * Navne og adresser paa truck-posterne er polstret med mellemrum; byerne er
        kaedens stavning ('Århus C', 'Grenå', 'Fakse'), ikke DAR's postnummernavne. To
        bilnavne har dobbelt mellemrum hos kaeden ('Nykøbing F.  v/Rema', 'Odense C
        Næsbyvej'), og vores CSV har dem ordret; _ren samler dem.
      * Adresseteksterne findes ikke altid i DAR: 'Hanehovedvej 49', 'Nørregade 61' og
        'Markedsgade 23' (se KILDEFEJL), 'Trafikcenter Sæby 1' (DAR: Trafikcenter Sæby Syd),
        'Centervej 2' (Køge), 'Industribuen 19' og 'Bredgade 9' (kun med bogstav i DAR).
        De oevrige 30 adresseforskelle mod vores bilraekker er DAR-normaliseringer
        ('Ndr.' -> 'Nordre', husbogstaver) paa samme punkt (0 m).
    Navn: kaedens stationName som i vores raekker - bilstationer 'Fjerritslev',
    'Næstved Karrebækvej', truckanlaeg 'Uno-X Truck Vejle'.
    INTEGRATION: raekkerne har 'lastbil', som refresh_retail skriver i tankstationer_dk.csv's
    kolonne 7 (rebuild.py laeser den dér), og bil- og lastbilanlaeg matches hver for sig
    (noeglen 'maerke|lastbil'). De 60 manglende truckanlaeg blev tilfoejet én gang i haanden
    01-10-2026, fordi baade 10 %-spaerren pr. maerke og feedets 10 %-loft pr. lag ellers
    afviste dem; de ugentlige smaa tilgange tilfoejes automatisk.
    Forventet: 360 (279 bilstationer + 81 truckanlaeg, 01-10-2026)."""
    if not _robots_tilladt(UNOX_URL):
        raise RuntimeError('unox: robots.txt paa unoxmobility.dk forbyder nu /privat/find-station '
                           '- henter ikke')
    raw = _flight(_text(UNOX_URL, 60))
    poster = []
    for m in re.finditer(r'"initialStations"\s*:\s*', raw):
        arr = json.loads(_balanced(raw, raw.index('[', m.end()), '[', ']'))
        if len(arr) > len(poster):        # den foerste forekomst er en tom liste
            poster = arr
    if not poster:
        raise RuntimeError('unox: "initialStations" ikke fundet i find-station - siden er lagt om')
    out = []
    for x in poster:
        if x.get('country') != 'DK':
            continue
        pn = _dk_postnr(_ren(x.get('stationZipcode')))
        lat, lon = _dk_koord(x.get('latitude'), x.get('longitude'))
        if not pn or lat is None:
            continue                      # 'Wayne Malmø' (21124) og poster uden koordinat
        if not x.get('active_tankning') or (x.get('fuelPointCount') or 0) <= 0:
            continue                      # El, El Truck og testposterne
        tjenester = set(x.get('services') or [])
        if x.get('truck'):
            if 'Truckanlæg' not in tjenester:
                continue
            lastbil = 'ja'
        elif x.get('brand') == 'Uno-X' and any(_UNOX_BRAENDSTOF.search(p)
                                               for p in (x.get('products') or [])):
            lastbil = ''
        else:
            continue
        out.append({'brand': 'Uno-X', 'name': _ren(x.get('stationName')),
                    'street': _unox_gade(x.get('stationAddress')), 'postnr': pn,
                    'by': _ren(x.get('stationCity')), 'lat': lat, 'lon': lon,
                    'lastbil': lastbil})
    out = _ret_kildefejl(_uniq(out))
    n_bil = sum(1 for r in out if not r['lastbil'])
    n_lb = len(out) - n_bil
    # Hver delmaengde vagtes for sig: forsvinder truck-flaget eller 'Truckanlæg'-teksten,
    # falder 81 lastbilanlaeg ud, mens totalen stadig ser plausibel ud.
    if not 250 <= n_bil <= 320 or not 60 <= n_lb <= 110:
        raise RuntimeError(f'unox: {n_bil} bilstationer (forventet 250-320) og {n_lb} '
                           f'truckanlaeg (forventet 60-110) - behandles som en koerselsfejl, '
                           f'ikke som lukninger/aabninger')
    return out


# Kendte fejl hos Uno-X (01-10-2026). Noeglen er kaedens gadetekst EFTER _unox_gade; hver
# noegle rammer praecis de poster der staar i kommentaren (tjekket mod alle 360). Koordinater
# for anlaeg vi HAR er LAEST UD AF CSV'EN (vores raekke for samme anlaeg); for anlaeg vi endnu
# ikke har er det DAR-punktet for kaedens egen adresse (som Normal Haderslev).
KILDEFEJL.update({
    # --- Truckanlaeg vi har, hvor kaedens pin er forkert (70-149 m).
    # Uno-X Truck Ringsted: kaedens pin ('Balstrupvej 92 (GPS ADR)') staar 149 m fra vores
    # raekke og 91 m fra DAR-punktet; ingen BBR-tankbygning inden for 30 m af pinnen. Vores
    # raekke staar inden for 30 m af BBR-bygningen med anvendelse 325 (tankstation), hvis
    # husnummer er Balstrupvej 92.
    ('Uno-X', 'balstrupvej 92'): {'lat': 55.434421, 'lon': 11.812564},
    # Uno-X Truck Struer: kaedens pin staar 121 m fra vores raekke, 112 m fra DAR-punktet for
    # Fælledvej 27 og 83 m fra Fælledvej 12; vores raekke staar 15 m fra DAR-punktet.
    ('Uno-X', 'fælledvej 27'): {'lat': 56.474094, 'lon': 8.583884},
    # Uno-X Truck Vejle (DTC): OSM-noden 'Uno-X Truck' (node 13096870193, mellem Shell-,
    # Circle K-, OK- og IDS-oeerne) staar 5 m fra vores raekke og 81 m fra kaedens pin, som
    # ligger ved DTC Torvet 24; BBR-tankbygningen Dieselvej 30 er inden for 30 m af vores.
    ('Uno-X', 'dieselvej 30'): {'lat': 55.747684, 'lon': 9.588618},
    # Uno-X Truck Aarhus (Vandvejen 5, havnen): OSM-noden 'Uno X' (node 3544869522) staar
    # 0 m fra vores raekke og 70 m fra kaedens pin; BBR-tankbygningen er inden for 30 m af vores.
    ('Uno-X', 'vandvejen 5'): {'lat': 56.143101, 'lon': 10.230775},
    # --- Adressetekster der ikke passer til kaedens EGEN pin.
    # Uno-X Truck Tåstrup: kaeden skriver 'Letland Alle 3', men dens pin staar 2 m fra
    # DAR-punktet for Estland Alle 3 og 310 m fra DAR's Letland Alle 3, hvor der intet
    # tankanlaeg er. Pinnen er truckcentret (OSM: 'STC Letland Alle', 3 m), hvor ogsaa
    # Circle K's og Shells truckraekker staar (<= 4 m) - alle med Estland Alle 3.
    ('Uno-X', 'letland alle 3'): {'street': 'Estland Alle 3'},
    # Frederiksværk (bil, nr. 787) OG Uno-X Truck Frederiksværk (nr. 9513): Hanehovedvej
    # har intet nr. 49 (naermeste nummer 415 m vaek). Begge pins staar 2 m fra BBR-
    # tankbygningen Gl. Hundestedvej 3, som er vores bilraekkes adresse.
    ('Uno-X', 'hanehovedvej 49'): {'street': 'Gl. Hundestedvej 3'},
    # Frederiksværk (nr. 2417, den anden bilstation af samme navn): Nørregade har intet
    # nr. 61; vores raekke (0 m fra pinnen) er DAR-punktet Åsebro 1.
    ('Uno-X', 'nørregade 61'): {'street': 'Åsebro 1'},
    # Nykøbing F Markedsgade (nr. 1140): Markedsgade i 4800 slutter ved nr. 22; vores
    # raekke (0 m fra pinnen) er DAR-punktet Fejøgade 31, 5 m fra pinnen.
    ('Uno-X', 'markedsgade 23'): {'street': 'Fejøgade 31'},
    # Uno-X Truck Brabrand: DAR's Logistikparken 1 ligger 553 m fra kaedens pin uden nogen
    # tankbygning inden for 150 m; pinnen staar 16 m fra BBR-tankbygningen (325) med husnummer
    # Logistikparken 17F. (Circle K's truckanlaeg, Logistikparken 19, er 123 m derfra.)
    ('Uno-X', 'logistikparken 1'): {'street': 'Logistikparken 17F'},
    # --- Truckanlaeg vi endnu ikke har, hvor pinnen er grebet forkert.
    # Uno-X Truck Roskilde 2: kaedens pin staar 361 m fra DAR-punktet for dens egen adresse
    # Vestre Hedevej 26 (reverse: Vestre Hedevej 34). Ved DAR-punktet staar tre BBR-
    # tankbygninger (325) med husnummer Vestre Hedevej 26, 10-49 m derfra; ved pinnen ingen.
    # Uden posten faar raekken baade forkert punkt og adressen 'Vestre Hedevej 34'.
    ('Uno-X', 'vestre hedevej 26'): {'lat': 55.64291, 'lon': 12.135254},
    # --- Tilfoejet af skeptikeren 01-10-2026.
    # Uno-X Truck Brande: kaedens pin staar paa OK's truckoe (OSM 'OK Truck Diesel',
    # 42 m; BBR 70.000 l-tank paa Sjællandsvej 2D), 61 m fra DAR's Sjællandsvej 4 (Burger
    # King). Uno-X' anlaeg er paa 2A: OSM-noden 'Uno-X Truck' (node 5154120274, brand
    # Uno-X, fuel:HGV_diesel, redigeret 16-11-2025) staar 1 m fra DAR-punktet for
    # Sjællandsvej 2A, BBR-tankbygningen (325, 2016) 2 m og dens 40.000 l-dieseltank (2015)
    # 5 m derfra. OK Brande (2D) har sin egen 325-bygning (2020) og egne tanke (2019).
    ('Uno-X', 'sjællandsvej 4'): {'street': 'Sjællandsvej 2A', 'lat': 55.927251, 'lon': 9.158276},
    # Uno-X Truck Sæby: kaedens 'Trafikcenter Sæby 1' findes ikke i DAR, og pinnen er en
    # geokodning der staar 9 m fra OK Sæby (OK's egen adresse: Trafikcenter Sæby Syd 1).
    # Truckoeerne staar paa raekke 60-80 m mod oest: OSM 'STC Sæby' (Circle K, redigeret
    # 25-05-2025), 'OK Truck Diesel Sæby', 'IDS Sæby', 'Shell Truck Diesel' og 'Uno-X Diesel
    # Service' (node 1693505472, fuel:HGV_diesel). Koordinaten er den sidste; DAR-adressen
    # dér er Trafikcenter Sæby Syd 14 (14 m), som ogsaa er vores Circle K-truckraekkes.
    # DAR-PUNKTET for nr. 14 kan IKKE bruges: det er tegn for tegn Circle K-raekkens
    # koordinat, og samme koordinat under to maerker er en haard fejl i validate.py.
    ('Uno-X', 'trafikcenter sæby 1'): {'street': 'Trafikcenter Sæby Syd 14', 'lat': 57.313174, 'lon': 10.451035},
    # Uno-X Truck Hirtshals: kaedens pin er tegn for tegn vores SHELL CRT HIRTSHALS'
    # (57.576454, 9.985207) - begge er geokodninger af transportcentrets adresse
    # Dalsagervej 3, ikke en dublet (Shell, Circle K, Go'on og Uno-X har hver et anlaeg;
    # BBR har fire ens tankbygninger fra 2010 paa Dalsagervej 1/1D/1E/1F). Samme
    # koordinat under to maerker er en haard fejl i validate.py (XDUP_HAARD), og intet
    # belaeg peger paa en bestemt af de fire oeer, saa raekken faar DAR-punktet for
    # kaedens egen adresse (64 m fra pinnen, 64 m fra Shell, 76 m fra Circle K).
    ('Uno-X', 'dalsagervej 3'): {'lat': 57.576196, 'lon': 9.986172},
})


# ---- Circle_K (etape 3, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker)
# ---- Circle K og Ingo (etape 3, 01-10-2026: tanklagets hentere)
# Til retail_sources.py efter etape 2-blokken: bruger _robots_tilladt, _normal_gade_nr og
# _dk_postnr fra Normal-blokken. Saettes den i sources.py, skal den i stedet have:
#   from retail_sources import (_json, _text, _json_after, _ren, _dk_koord, _uniq, KILDEFEJL,
#                               _ret_kildefejl, _robots_tilladt, _normal_gade_nr, _dk_postnr)
# Raekkerne har 'lastbil' ('ja' for lastbilanlaeg), som tankstationer_dk.csv's kolonne Lastbil.
# INTEGRATION: refresh_retail koerer den som 'circlek_ingo' (EJER ['Circle K', 'Ingo']), matcher
# pr. (maerke, Lastbil) og skriver kolonnen Lastbil. Et maerkeskift paa samme anlaeg (Circle K
# -> Ingo: 17 anlaeg i 2023; Ingo -> Circle K: Herlev Hovedgade 56 i 2022) meldes som
# MÆRKESKIFT og tilfoejes ikke (refresh_retail, fra 02-10-2026): en 'ny' post inden for 50 m
# af en raekke med ejerens andet maerke, naar kilden ikke laengere har det gamle maerke dér.

CIRCLEK_SOEG_URL = 'https://www.circlek.dk/station-search'
# Circle K's offentlige pris-API (lovkravet om offentliggjorte braendstofpriser), dokumenteret
# paa ingo.dk/vores-lave-priser/brændstofpriser/api ('DK Fuel Prices API doc 2_1.pdf', 2026-03):
# GET med headeren X-App-Name: PRICES - en fast, offentlig vaerdi, ikke en noegle.
CIRCLEK_PRIS_URL = 'https://api.circlek.com/eu/prices/v1/fuel/countries/DK'
# Circle K's egne brand-koder (stamdatafeltet 'brand') -> (vores maerke, Lastbil).
# En ny kode faar henteren til at fejle, saa maerket bliver en beslutning, ikke et gaet.
CIRCLEK_BRAND = {'CIRCLEK': ('Circle K', ''), 'CKAUTOMAT': ('Circle K', ''),
                 'INGO': ('Ingo', ''), 'TRUCK': ('Circle K', 'ja')}
CIRCLEK_IKKE_BRAENDSTOF = {'EU_EV_CHARGER', 'EU_ADBLUE'}   # 'EL Ladestander', 'AdBlue pumpe'
CIRCLEK_PRIS_SLAEK = 5    # tilladt uenighed mellem stamdata og pris-API om bilstationerne
# Seneste koersels afvigelser, saa en rapport kan sige HVORFOR et anlaeg mangler: 'uden_pris'
# = bilstationer i stamdata, der ikke staar paa prislisten (udeladt), 'kun_pris' = prisanlaeg
# uden stamdata (ikke udsendt), 'pris_api' = antal prisanlaeg eller None hvis API'et ikke svarede.
CIRCLEK_SIDSTE = {}


def _ck_gade(s):
    """Circle K's gadetekst -> 'Vej nr'. Stednavnet efter kommaet ryger ('Storegade 12,
    Assentoft', 'Sydmotorvejen 383, Øst'), ogsaa efter skraastreg ('Tårnborgvej
    31/Kongebroen'); 'Kuldyssen 2.' mister punktummet, '35c' bliver '35C', og et interval
    ('Næstvedvej 36-38') bliver dets foerste nummer (_normal_gade_nr)."""
    g = _normal_gade_nr(_ren(s).split('/')[0])
    g = re.sub(r'(\d)\.$', r'\1', g)
    return re.sub(r'(\d)([a-zæøå])$', lambda m: m.group(1) + m.group(2).upper(), g)


def _ck_priser():
    """Pris-API'et -> {site-id: post} for anlaeg med mindst én literpris, eller None hvis det
    ikke svarer brugbart. Kun et efterproevnings-signal: uden det bruges stamdataene alene,
    og henteren fejler ikke. API'et giver 429 (Too Many Requests) efter faa kald i traek -
    kald det én gang pr. koersel."""
    try:
        if not _robots_tilladt(CIRCLEK_PRIS_URL):
            return None
        d = _json(CIRCLEK_PRIS_URL, 60, headers={'X-App-Name': 'PRICES'})
        ud = {str(s.get('id')): s for s in (d.get('sites') or [])
              if isinstance(s, dict) and s.get('fuelPrices')}
    except Exception:
        return None
    return ud if len(ud) >= 300 else None


def circlek_ingo():
    """Circle K og Ingo (Circle K Danmark A/S, CVR 28142412) fra Circle K's EGNE stamdata.

    Kilde: www.circlek.dk/station-search - siden har alle danske anlaeg indlejret som
    drupalSettings-JSON (ck_sim_search.station_results; samme data som
    sources.circlek_sites() laeser). Ét kald (1,75 MB): 443 anlaeg 01-10-2026, hvert med
    brand-kode, siteType, status, braendstofliste, adresse og koordinat. De samme 443 slugs
    staar i circlek.dk/stations og sitemaps/stations/sitemap.xml; ingo.dk/station-search
    har de samme 196 Ingo-anlaeg, felt for felt. robots.txt paa www.circlek.dk forbyder
    ingen af stierne og naevner ingen Claude-agent; api.circlek.com/robots.txt er 404.
    EFTERPROEVES ved hver koersel mod Circle K's offentlige pris-API (CIRCLEK_PRIS_URL),
    den lovpligtige prisliste pr. station: dens 402 anlaeg er praecis de 206 + 196
    bilstationer nedenfor (01-10-2026, alle med samme landspris, opdateret 30-09). Et
    bilanlaeg, der ikke staar paa prislisten, udelades som ikke aabent. Et prisanlaeg, som
    stamdataene mangler, udsendes IKKE: uden stamdata er der hverken siteType, braendstof-
    liste eller koordinat, og refresh_retail springer poster uden koordinat over. Begge
    slags staar i CIRCLEK_SIDSTE til rapporten. Er de to Circle K-kilder uenige om flere end
    CIRCLEK_PRIS_SLAEK, fejler henteren.

    De 443 (01-10-2026) efter Circle K's egen brand-kode:
      * CIRCLEK 206: 205 stationer + 'CIRCLE K BILLUND LUFTHAVN', en butik i terminalen
        ('DODO with Non COCO Fuel', ingen braendstof), som udelades. circlek.dk/om:
        '435 lokationer, hvoraf 205 er Circle K-stationer' (435 = 443 minus 8 EV).
      * CKAUTOMAT 9: 'CIRCLE K AUTOMAT VALBY LANGGADE' (benzin og diesel) kommer med som
        Circle K; de 8 andre har siteType 'EV' (ren ladelokation, superlader-laget).
      * INGO 196, alle med benzin og diesel. ingo.dk: 'ca 200 stationer i Danmark'.
      * TRUCK 32 -> Lastbil='ja'. Brugerens regel (10-09-2026): et lastbilanlaeg kommer
        kun med, hvis det har diesel OG AdBlue. 25 opfylder den; 6 har kun diesel
        (Vallensbækvej Brøndby, Vamdrup, Ole Larsen Transport, Åbenrå, Padborg Hermesvej,
        'ANDEL BALLERUP - TRUCK, HOME'), og 'TRUCK HOME, CONTINO' har ingen braendstof.
    Efterproevet 01-10-2026 mod tankstationer_dk.csv: alle 206 + 25 + 196 parret inden for
    150 m med samme navn (421 paa samme koordinat; CIRCLE K TRUCK VIBORG 100 m). Ingen nye,
    ingen mulige lukninger. Circle K Danmark A/S' aktive P-enheder i CVR (branche 473000):
    alle har en raekke herfra inden for 150 m, undtagen de 15 afgjorte i
    cvr_tjek.KENDTE_MANGLER og Fabrikvej 14, Viborg (225 m fra CIRCLE K TRUCK VIBORG).
    Miljoestyrelsens DMA (dma.mst.dk, 250 aktive anlaeg under CVR 28142412, revision
    01-10-2026): ogsaa her har alle en raekke inden for 150 m, undtagen KENDTE_MANGLER, en
    IMO-vaskehal (Agerøvej 1, Tilst), Circle K Terminal (Rørdalsvej 38), en forældet Shell-
    registrering (Lygten 51) og Transportcenter Nord (168 m fra TRUCKANLÆG FREDERIKSHAVN).

    FAELDER:
      * Navnet afgoer intet: 'CIRCLE K RECHARGE CITY' lyder som en ladehub, men er
        siteType 'ST' med miles 95, miles Diesel og HVO100 og SKAL med; 'CIRCLE K EV
        TAPPERNØJE VEST' er siteType 'EV'. Kriteriet er siteType + braendstoflisten.
      * Tom braendstofliste er IKKE det samme som 'EV': Billund Lufthavn og TRUCK HOME,
        CONTINO er siteType 'ST' uden braendstof, og tre EV-anlaeg har 'EL Ladestander' i
        listen. 'EL Ladestander' og AdBlue taeller ikke som braendstof.
      * Motorvejsanlaeggene Ejer Bavnehøj Ø+V, Karlslunde Ø+V, Skærup Ø og Tappernøje V
        blev OK i januar 2026 (Vejdirektoratets rastepladsudbud). Circle K har kun ladere
        tilbage paa tre af dem (siteType 'EV' her), men driver stadig Skærup V (616A) og
        Tappernøje Ø (383) - de er siteType 'ST' og SKAL med.
      * Lukkede anlaeg omdoebes '...-CL' og forsvinder fra listen (stationssiden siger
        'Station closed down'); status er 'Active' paa alle 443. financialStatus 'Initial'
        (2 EV-anlaeg) er endnu ikke aabnet og udelades ALTID - ogsaa naar pris-API'et ikke
        svarer, saa resultatet ikke afhaenger af om API'et var oppe.
      * HVO100 er diesel (EN 15940) og taeller som diesel i lastbilreglen: Circle K havde en
        ren HVO100-lastbilpumpe (Noerremarken, cvr_tjek.KENDTE_MANGLER).
      * Gadeteksten er ikke altid en DAR-adresse: 37 af de 427 er det ikke (Adressevask +
        DAR 01-10-2026) - 13 mangler eller har forkert husbogstav ('Fabrikvej 16' = 16A-D),
        24 findes slet ikke ('Hovedvej 55, Seggelund', 'Nordjyske Motorvej 318', 'Waves
        Storcenter 13 C', 'Letland Alle 42'). KILDEFEJL nedenfor retter de 10, hvor vores
        raekke har BBR-tankbygningens eller naermeste DAR-adresse. Resten skal gennem
        dawa.normalize_one(..., bygning='325'), hvis de nogensinde bliver nye. To Ingo-
        anlaeg hedder 'Åbenråvej 1' (Haderslev 6100, rigtig, og Sønderborg 6400, hvor DAR
        og BBR siger Dybbølgade 42A), saa noeglen (maerke, gade) kan ikke skelne dem.
        Kildens koordinat er pumpernes (median 12 m til DAR-adressen).
      * Pris-API'et har hverken koordinater eller lastbilanlaeg og giver 429 efter faa kald;
        det er kun en efterproevning, og et udfald falder tilbage til stamdataene.
    Navn: Circle K's eget anlaegsnavn med samlede mellemrum ('CIRCLE K SØNDERBRO,  AALBORG'
    -> 'CIRCLE K SØNDERBRO, AALBORG'), som i CSV'en.
    Forventet: Circle K 206 + 25 lastbil, Ingo 196 (01-10-2026)."""
    if not _robots_tilladt(CIRCLEK_SOEG_URL):
        raise RuntimeError('circlek_ingo: robots.txt paa www.circlek.dk forbyder nu '
                           '/station-search - henter ikke')
    h = _text(CIRCLEK_SOEG_URL, 90)
    try:
        sr = _json_after(h, 'station_results')
    except ValueError as e:
        raise RuntimeError(f'circlek_ingo: station_results ikke fundet paa {CIRCLEK_SOEG_URL} '
                           f'- siden er lagt om ({e})')
    if not isinstance(sr, dict) or len(sr) < 350:
        raise RuntimeError(f'circlek_ingo: {len(sr) if isinstance(sr, dict) else "?"} anlaeg i '
                           f'station_results (forventet ~440)')
    priser = _ck_priser()
    out, ukendte, uden_pris = [], [], []
    for sid, v in sr.items():
        s = v.get('/sites/{siteId}') or {}
        a = (v.get('/sites/{siteId}/addresses') or {}).get('PHYSICAL') or {}
        loc = v.get('/sites/{siteId}/location') or {}
        info = v.get('/sites/{siteId}/opening-info') or {}
        fuels = [str(f.get('name') or '').upper() for f in (v.get('/sites/{siteId}/fuels') or [])
                 if isinstance(f, dict)]
        braendstof = [f for f in fuels if f not in CIRCLEK_IKKE_BRAENDSTOF]
        if s.get('status') != 'Active' or info.get('hiddenInSim'):
            continue
        if s.get('siteType') != 'ST' or not braendstof:
            continue                     # ren ladelokation, lufthavnsbutik, Truck Home
        if (a.get('country') or 'DK').upper() != 'DK':
            continue
        kode = (s.get('brand') or '').upper()
        if kode not in CIRCLEK_BRAND:
            ukendte.append(f"{kode or '?'}: {s.get('name')}")
            continue
        maerke, lastbil = CIRCLEK_BRAND[kode]
        if s.get('financialStatus') == 'Initial':
            continue                     # oprettet, ikke aabnet (uanset pris-API)
        if lastbil:
            if 'EU_ADBLUE' not in fuels or not any('DIESEL' in f or 'HVO' in f for f in braendstof):
                continue                 # brugerens regel: lastbil kun med diesel OG AdBlue
        elif priser is not None and str(sid) not in priser:
            uden_pris.append(s.get('name'))
            continue                     # ikke paa Circle K's prisliste = ikke aaben
        pn = _dk_postnr(a.get('postalCode'))
        if not pn:
            continue
        lat, lon = _dk_koord(loc.get('lat'), loc.get('lng'))
        out.append({'brand': maerke, 'name': _ren(s.get('name')), 'street': _ck_gade(a.get('street')),
                    'postnr': pn, 'by': _ren(a.get('city')), 'lat': lat, 'lon': lon,
                    'lastbil': lastbil})
    if ukendte:
        raise RuntimeError(f"circlek_ingo: ukendt brand-kode i Circle K's stamdata "
                           f"({'; '.join(ukendte[:5])}) - tag stilling til maerket i CIRCLEK_BRAND")
    nye = [] if priser is None else [_ren(p.get('name')) for k, p in priser.items() if k not in sr]
    CIRCLEK_SIDSTE.clear()
    CIRCLEK_SIDSTE.update({'uden_pris': list(uden_pris), 'kun_pris': nye,
                           'pris_api': None if priser is None else len(priser)})
    if len(uden_pris) > CIRCLEK_PRIS_SLAEK or len(nye) > CIRCLEK_PRIS_SLAEK:
        raise RuntimeError(f'circlek_ingo: stamdata og pris-API er uenige: {len(uden_pris)} '
                           f'bilstationer uden priser (fx {uden_pris[:3]}) og {len(nye)} '
                           f'prisanlaeg uden stamdata (fx {nye[:3]}) - behandles som en '
                           f'koerselsfejl, ikke som lukninger/aabninger')
    # Prisanlaeg uden stamdata udsendes ikke (se docstring); de staar i CIRCLEK_SIDSTE.
    out = _ret_kildefejl(_uniq(out))
    n = lambda m, lb: sum(1 for r in out if r['brand'] == m and r['lastbil'] == lb)
    for m, lb, lo, hi in (('Circle K', '', 180, 240), ('Circle K', 'ja', 15, 40), ('Ingo', '', 170, 230)):
        if not lo <= n(m, lb) <= hi:
            raise RuntimeError(f'circlek_ingo: {n(m, lb)} {m}{" lastbil" if lb else ""} (forventet '
                               f'{lo}-{hi}) - behandles som en koerselsfejl, ikke som '
                               f'lukninger/aabninger')
    return out


# Circle K's gadetekst findes ikke i DAR (efterproevet 01-10-2026 mod DAR og BBR). Vaerdien
# er vores raekkes adresse, LAEST FRA tankstationer_dk.csv; i alle 10 er det BBR-tank-
# bygningens (325) adresse eller naermeste DAR-adresse til Circle K's egen koordinat, som
# vores raekke deler. Noeglen er kildens tekst EFTER _ck_gade og er entydig inden for
# maerket. (17 Ingo-raekker har stadig kildens ikke-eksisterende tekst i CSV'en; de faar
# foerst en post her, naar raekken er rettet - ellers er koden og dataene uenige.)
KILDEFEJL.update({
    # INGO SEGGELUND: 'Hovedvej 55, Seggelund'; BBR-tankbygningen 19 m fra koordinaten
    ('Ingo', 'hovedvej 55'): {'street': 'Seggelund Hovedvej 55'},
    # CIRCLE K LIND: 'Hovedgaden 2 A, Lind'; BBR-tankbygningen 7 m
    ('Circle K', 'hovedgaden 2a'): {'street': 'Lind Hovedgade 2A'},
    # CIRCLE K HELSINGØR: nr. 26 findes ikke; BBR-tankbygningen er nr. 24, 14 m
    ('Circle K', 'kongevejen 26'): {'street': 'Kongevejen 24'},
    # CIRCLE K LAURIDS SKAUSGADE, HADERSLEV: nr. 21 findes ikke; BBR-tankbygningen er nr. 23
    ('Circle K', 'laurids skaus gade 21'): {'street': 'Laurids Skaus Gade 23'},
    # CIRCLE K MOTORVEJSCENTER HIMMERLAND: motorvejens kilometrering; BBR-tankbygningen
    ('Circle K', 'nordjyske motorvej 318'): {'street': 'Himmerland Vest 2'},
    # INGO HUNDIGE, WAVES STORCENTER: centernavnet; naermeste DAR-adresse 26 m
    ('Ingo', 'waves storcenter 13c'): {'street': 'Over Bølgen 13'},
    # INGO KASTRUP, AMAGER LANDEVEJ: nr. 177 findes ikke; BBR-tankbygningen 2 m
    ('Ingo', 'amager landevej 177'): {'street': 'Magle Alle 1A'},
    # TRUCKANLÆG HERNING: 'Hi-Park 33' findes ikke; naermeste DAR-adresse 34 m
    ('Circle K', 'hi-park 33'): {'street': 'Transportbuen 2'},
    # TRUCKANLÆG HØJE TÅSTRUP: 'Letland Alle 42' findes ikke; naermeste DAR-adresse 2 m
    ('Circle K', 'letland alle 42'): {'street': 'Estland Alle 3'},
    # TRUCKANLÆG SÆBY: 'Sæby Syd 1' findes ikke; naermeste DAR-adresse 7 m
    ('Circle K', 'sæby syd 1'): {'street': 'Trafikcenter Sæby Syd 14'},
})


# ---- OIL (etape 3, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker)
# ---- OIL! (etape 3, 01-10-2026: kaedens lovpligtige pris-API + stationsfolderen; DAR-punkter via dawa.py)
# ---------------------------------------------------------------- OIL! tank & go
# Bruger _dk_koord, _json, _map, _normal_gade_nr, _raw, _ret_kildefejl, _robots_tilladt, _text
# og _uniq fra retail_sources. KRAEVER pypdf til stationsfolderen: weekly-refresh.yml
# installerer den (den manglede indtil 02-10-2026, saa OIL! fejlede paa hver GitHub-koersel,
# mens den lokale proeve gik fint). refresh_retail koerer den som 'oil' (EJER ['OIL!']).
import collections as _collections
import datetime as _datetime
import json
import re
import string as _string
import unicodedata as _unicodedata
import urllib.parse

OIL_API = 'https://apim-fuel-prices-prod.azure-api.net/Oil-FuelPrices/prices'
OIL_FINDER = 'https://www.oil-tankstationer.dk/tankstationer-find-din-station/'
OIL_DOWNLOADS = 'https://www.oil-tankstationer.dk/nyheder-info/downloads-i-et-overblik/'
OIL_MIN = 60              # API og folder havde hver 71 stationer 01-10-2026; faerre = kilde- eller parserfejl
OIL_MAX_UDEN_PUNKT = 3    # stationer uden DAR-punkt, foer henteren giver op
OIL_MAX_UENIGE = 6        # stationer kun i API'et eller kun i folderen, foer henteren giver op
OIL_API_MAX_ALDER = 14    # dage: et pris-API der ikke er opdateret i to uger, er ikke en levende liste
OIL_PAR_M = 250           # API- og folderpost er samme station, hvis punkterne ligger saa taet


def _oil_api_poster():
    """Kaedens lovpligtige pris-API -> [{'navn', 'gade', 'postnr', 'by', 'lat', 'lon'}].

    Ét kald uden parametre giver alle stationer med station_id, station_name, address, gps og
    updated. Dokumentationen ('Oil-API-Dokumentation-V3.pdf', linket fra kaedens prisside:
    'Ønsker du adgang til vores lovpligtige API løsning ...') siger 'offentlig via Azure API
    Management - ingen subscription key nødvendig'. GPS'en bruges KUN til at parre og skille
    lige gode adresser ad, aldrig som punkt: Herfølge ligger 19,7 km forkert, Skive 35,6 km,
    Sæby 178 km (55.73 for 57.33), Varde 1,8 km (01-10-2026)."""
    from retail_sources import _dk_koord, _json, _normal_gade_nr, _robots_tilladt
    if not _robots_tilladt(OIL_API):
        raise RuntimeError(f'OIL!: robots.txt forbyder nu {OIL_API}')
    d = _json(OIL_API, 60)
    if not isinstance(d, list) or len(d) < OIL_MIN:
        raise RuntimeError(f"OIL!: pris-API'et gav {len(d) if isinstance(d, list) else type(d).__name__} "
                           f"poster (forventet ~71)")
    datoer = [str(x.get('updated') or '')[:10] for x in d]
    nyeste = max((t for t in datoer if re.fullmatch(r'\d{4}-\d{2}-\d{2}', t)), default='')
    if not nyeste or (_datetime.date.today() - _datetime.date.fromisoformat(nyeste)).days > OIL_API_MAX_ALDER:
        raise RuntimeError(f"OIL!: pris-API'et er ikke opdateret siden {nyeste or '?'} - "
                           f"listen er ikke laengere levende")
    ud = []
    for x in d:
        # 'Bystævnevej 3, Bolbro, 5200 Odense V' · 'Apholmenvej 3  9900 Frederikshavn' (intet
        # komma) · 'Viborgvej 165, 8210 Århus V.' · 'Christian X´s vej 112' · 'Agerøvej 1 A'
        a = ' '.join(str(x.get('address') or '').replace('´', "'").replace('’', "'").split())
        m = re.search(r'(?:^|[\s,])(\d{4})\s+([^\d,][^,]*?)\.?$', a)
        gade, pn, by = (a[:m.start()].strip(' ,'), m.group(1), m.group(2).strip()) if m else (a, '', '')
        dele = [s.strip() for s in gade.split(',') if s.strip()]
        med_nr = [s for s in dele if re.search(r'[^\W\d_].*\s\d', s)]
        tal = re.findall(r'\d+(?:\.\d+)?', str(x.get('gps') or ''))
        la, lo = _dk_koord(*tal[:2]) if len(tal) >= 2 else (None, None)
        ud.append({'navn': ' '.join(str(x.get('station_name') or '').split()),
                   'gade': _normal_gade_nr(med_nr[0] if med_nr else gade),
                   'postnr': pn, 'by': by, 'lat': la, 'lon': lo})
    return ud


def _oil_folder_url():
    """Den aktuelle stationsfolder. Filnavnet skifter med hver udgave
    ('OIL-DK_Find-din-station_folder_2026-07.pdf'), saa linket laeses fra finder-siden
    ved hver koersel - og fra downloads-siden, hvis finderen holder op med at linke."""
    import html as _h
    from retail_sources import _robots_tilladt, _text
    for side in (OIL_FINDER, OIL_DOWNLOADS):
        if not _robots_tilladt(side):
            raise RuntimeError(f'OIL!: robots.txt forbyder nu {side}')
        h = _text(side, 60)
        links = {urllib.parse.urljoin(side, _h.unescape(u))
                 for u in re.findall(r'href="([^"]*find-din-station[^"]*\.pdf(?:\?[^"]*)?)"', h, re.I)}
        if links:
            # flere udgaver linket: den med det seneste aar-maaned i filnavnet
            return max(links, key=lambda u: (re.findall(r'(\d{4})-(\d{2})', u) or [('0', '0')])[-1])
    raise RuntimeError('OIL!: stationsfolderen (PDF) er hverken linket fra find-din-station '
                       'eller fra downloads-siden')


def _oil_pdf_tekst(b):
    try:
        import pypdf
    except ImportError:
        raise RuntimeError('OIL!: henteren kraever pypdf (pip install pypdf) til at laese '
                           'stationsfolderen') from None
    import io
    return '\n'.join((p.extract_text() or '') for p in pypdf.PdfReader(io.BytesIO(b)).pages)


def _oil_folder_poster(tekst):
    """Folderens tekst -> [(sted, gade, postnr, by, fodnote)].

    Hver station er tre linjer: stednavn, gade + husnr og 'DK-<postnr> <by>'. En stjerne
    efter byen henviser til en fodnote ('* Kun for OIL! firmakort kunder.'). Bryder
    tre-linje-moenstret (gade uden husnummer, sted med cifre), er layoutet aendret -
    saa fejler henteren hellere end at gaette."""
    linjer = [' '.join(l.split()) for l in tekst.splitlines()]
    linjer = [l for l in linjer if l]
    noter = {}
    for l in linjer:
        m = re.match(r'^(\*+)\s*(\S.*)$', l)
        if m:
            noter[m.group(1)] = m.group(2).rstrip('.')
    ud = []
    for i, l in enumerate(linjer):
        m = re.match(r'^DK-(\d{4})\s+(.*?)\s*(\*+)?$', l)
        if not m:
            continue
        sted, gade = (linjer[i - 2], linjer[i - 1]) if i >= 2 else ('', '')
        if not re.search(r'[^\W\d_].*\s\d', gade) or re.search(r'\d', sted) or sted.startswith('DK-'):
            raise RuntimeError(f'OIL!: folderens opbygning er aendret omkring {l!r} '
                               f'(sted {sted!r}, gade {gade!r})')
        ud.append((sted, gade, m.group(1), m.group(2).strip(), noter.get(m.group(3) or '', '')))
    return ud


def _oil_ord(s):
    """Vejnavn -> normaliserede ord: aeoeaa foer accenterne fjernes (ellers bliver 'Århus'
    til 'arhus'), forkortelser udskrevet som i dawa._FORK ('Ndr.' -> 'nordre')."""
    import dawa
    s = (s or '').lower().replace('æ', 'ae').replace('ø', 'oe').replace('å', 'aa')
    s = ''.join(c for c in _unicodedata.normalize('NFKD', s) if not _unicodedata.combining(c))
    fork = dict(dawa._FORK)
    return [fork.get(w, w) for w in re.findall(r'[a-z0-9]+', s)]


def _oil_et_tegn(x, y):
    """Hoejst én tastefejl mellem x og y (indsat, slettet, byttet eller ombyttet tegn)."""
    if x == y:
        return True
    if abs(len(x) - len(y)) > 1:
        return False
    if len(x) == len(y):
        d = [i for i in range(len(x)) if x[i] != y[i]]
        return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1
                               and x[d[0]] == y[d[1]] and x[d[1]] == y[d[0]])
    k, l = sorted((x, y), key=len)
    return any(k == l[:i] + l[i + 1:] for i in range(len(l)))


def _oil_samme_vej(a, b):
    """Er DAR-vejnavnet b en stavevariant af kildens a - ikke blot en vej der ligner?

    Godtager: samme bogstaver uden mellemrum/tegn ('Th. Brorsensvej' ~ 'Th. Brorsens Vej',
    'Nørre Allé' ~ 'Nørre Alle'), initialer ('Eli Christensens Vej' ~ 'E Christensens Vej')
    og én tastefejl i et ord paa mindst 5 tegn, hvis de tre foerste bogstaver er ens
    ('Sigrundsvej' ~ 'Sigrunsvej'). Afviser forskellige veje, som difflib >= 0,8 og
    dawa._ligner godtager: 'Torvegade'/'Storegade' (0,89), 'Østergade'/'Vestergade' (0,90),
    'Kirkevej'/'Birkevej' (0,88), 'Skolevej'/'Skovvej' (0,80)."""
    ta, tb = _oil_ord(a), _oil_ord(b)
    if not ta or not tb:
        return False
    if ''.join(ta) == ''.join(tb):
        return True
    if len(ta) != len(tb):
        return False

    def ord_ens(x, y):
        if x == y:
            return True
        k, l = sorted((x, y), key=len)
        if len(k) <= 2 and l.startswith(k):
            return True
        return len(k) >= 5 and x[:3] == y[:3] and _oil_et_tegn(x, y)
    return all(ord_ens(x, y) for x, y in zip(ta, tb))


def _oil_geokod(gade, pn):
    """Kildens adresse -> (DAR-post {vejnavn, husnr, postnr, postnrnavn, y, x}, metode).

    Ingen af kilderne har brugbare koordinater, saa stationen placeres paa DAR-adgangspunktet.
    I raekkefoelge:
      'dar'            vej + husnr + postnr findes eksakt i DAR
      'dar-vask'       Adressevasken kender adressen: eksakt/historisk ('Vestergade 1A' ->
                       'Hans Grams Gade 1A') eller en stavevariant af SAMME vej (_oil_samme_vej:
                       'Grundtvigs Allé' -> 'Grundtvigs Alle', 'Sigrundsvej' -> 'Sigrunsvej')
      'dar-vejnavn'    samme husnr i postnummeret paa en stavevariant af vejen
                       ('Eli Christensens Vej 1B' -> DAR 'E Christensens Vej 1B')
      'dar-familie'    husnummeret findes ikke, men familien goer ('Nørre Allé 12' -> 12A/12B):
                       familiens midtpunkt
      'dar-nabonummer' vejen findes, familien ikke ('Damhusvej 1B'): naermeste husnummer
                       paa vejen (hoejst 4 numre vaek)
    -> (None, grund) hvis intet holder. Et udfald i DAR/Adressevasken rejser DawaNede."""
    import dawa
    from retail_sources import _normal_gade_nr
    s = _normal_gade_nr((gade or '').replace('’', "'").replace('´', "'"))
    vej, nr = dawa.split_street(s)
    if not (vej and nr and re.fullmatch(r'\d{4}', pn or '')):
        return None, 'intet husnummer eller postnummer'
    hit = dawa._q(vejnavn=vej, husnr=nr, postnr=pn)
    if hit:
        return hit[0], 'dar'
    kat, a, kode, tekst = dawa.vask(f'{s}, {pn} {dawa.postnumre().get(pn, "")}'.strip())
    if kat is None:
        raise dawa.DawaNede(f'Adressevasken svarede ikke ({s}, {pn}): {tekst}')
    if a and a.get('vejnavn') and a.get('husnr') and \
            (kat == 'A' or (kat == 'B' and _oil_samme_vej(vej, a['vejnavn']))):
        hit = dawa._q(vejnavn=a['vejnavn'], husnr=a['husnr'], postnr=a.get('postnr') or pn)
        if hit:
            return hit[0], 'dar-vask'
    # husnummer-familien i postnummeret ('12', '12A' ... '12Z'); DAR kan ikke startsWith
    base = dawa._base(nr)
    dawa._postnumre_indlaes()
    pid = dawa._pn_nr.get(pn)
    if not (base and pid):
        return None, 'ukendt postnummer'
    fam = [base] + [base + c for c in _string.ascii_uppercase]
    noder = dawa._alle('DAR_Husnummer', '{' + f'status:{{in:{dawa.AKTIV}}}, postnummer:{{eq:"{pid}"}}, '
                       f'husnummertekst:{{in:{json.dumps(fam)}}}' + '}', dawa.HF)
    # Findes kildens vej i postnummeret, er det kun nummeret der er galt: hold dig til vejen.
    # Ellers kun en STAVEVARIANT af vejen - ikke 'den der ligner mest': med difflib >= 0,8
    # blev API'ets 'Torvegade 23, 3720' (Nexø har 3730) til 'Storegade 23, 3720 Aakirkeby',
    # 13 km fra stationen (testet 01-10-2026).
    paa_vejen = bool(dawa.on_street(vej, pn))
    veje = {}
    for x in dawa._mini(noder):
        if (x['vejnavn'] == vej) if paa_vejen else _oil_samme_vej(vej, x['vejnavn']):
            veje.setdefault(x['vejnavn'], []).append(x)
    if len(veje) > 1:
        return None, f'flertydigt vejnavn ({" / ".join(sorted(veje))})'
    if veje:
        vejnavn, xs = next(iter(veje.items()))
        eks = [x for x in xs if x['husnr'].upper() == nr.upper()]
        if eks:
            return eks[0], 'dar-vejnavn'
        midt = dict(xs[0], husnr=nr, y=sum(x['y'] for x in xs) / len(xs),
                    x=sum(x['x'] for x in xs) / len(xs))
        return midt, 'dar-familie'
    if paa_vejen:
        alle = dawa.on_street(vej, pn)
        tal = [(abs(int(dawa._base(c[1])) - int(base)), c) for c in alle if dawa._base(c[1])]
        if tal:
            d, c = min(tal, key=lambda t: (t[0], t[1][1]))
            if d <= 4:
                return {'vejnavn': c[0], 'husnr': c[1], 'postnr': c[2], 'postnrnavn': c[3],
                        'y': c[4], 'x': c[5]}, 'dar-nabonummer'
    return None, f'ikke i DAR ({tekst})'


def _oil_api_navn(n):
    """API'ets stationsnavn i CSV'ens stil: 'OIL! tank & go Vejle, Nord' -> 'Vejle (Nord)',
    'OIL! tank & go Horsens Centrum' -> 'Horsens (Centrum)'."""
    s = ' '.join(re.sub(r'^\s*OIL!?\s*tank\s*&\s*go\b', '', n or '', flags=re.I).split())
    m = re.match(r'^(.+?),\s*(.+)$', s) or re.match(r'^(.+?)\s+(Nord|Syd|Øst|Vest|Centrum|Midt)$', s)
    return f'{m.group(1)} ({m.group(2)})' if m else s


def oil():
    """OIL! tank & go ApS (CVR 36552816) fra kaedens EGNE lister: det lovpligtige pris-API
    (hvilke stationer der saelger braendstof i dag) og stationsfolderen (rene adresser).

    KILDER:
      * POPULATION: apim-fuel-prices-prod.azure-api.net/Oil-FuelPrices/prices - kaedens
        lovpligtige, aabne pris-API (dokumentation linket fra prissiden: 'Ønsker du adgang til
        vores lovpligtige API løsning ...'; 'ingen subscription key nødvendig'). Opdateres
        dagligt ('updated'), 71 stationer 01-10-2026. En station der lukker, holder op med at
        faa priser; en ny kommer med, saa snart den saelger braendstof.
      * ADRESSER: folderen 'OIL! Tankstationer i Danmark' (PDF), linket fra finder-siden og
        downloads-siden: /fileadmin/user_upload/dk/downloads-dk/OIL-DK_Find-din-station_folder_
        <aaaa-mm>.pdf ('Version 2 / 2026', oprettet 01-07-2026, 71 stationer). Har stednavn,
        gade, 'DK-<postnr> <by>' og fodnoten om firmakort - men er et oejebliksbillede, der
        kommer et par gange om aaret.
    Ingen af dem har brugbare koordinater: stationen placeres paa DAR-adgangspunktet for
    adressen (_oil_geokod), og 'geokode' paa hver raekke siger hvordan og fra hvilken kilde.
    API- og folderposter parres paa vej+husnr, saa paa DAR-punkt, saa paa API'ets GPS (begge
    inden for OIL_PAR_M) og til sidst paa postnummer, hvis der kun er én tilbage paa hver side.
    Af to adresser vinder den der findes mest direkte i DAR; er begge eksakte DAR-adresser og
    forskellige, den der ligger naermest API'ets GPS.
    Kun i API'et = ny station (navn fra API'et); den faar kun et punkt, naar adressen findes
    direkte i DAR ('dar'/'dar-vask') og API'ets GPS ikke ligger over 2 km derfra - ellers
    lat=None, saa refresh melder den uden at tilfoeje den. Kun i folderen = saelger ikke
    braendstof nu (lukket eller ikke aabnet) og udelades, saa vores raekke meldes som mulig
    lukning. Flere end OIL_MAX_UENIGE uenigheder i alt = fejl.

    ROBOTS (01-10-2026, laest efter RFC 9309, laengste match): www.oil-tankstationer.dk har
    'User-Agent: * / Allow: /' med bl.a. 'Disallow: /*?id=*' (TYPO3's 'non-realurl URLs').
    Finderens kort henter sine data fra /index.php?id=158&tx_oil_petrolstationlist[...]
    &type=89657201 - den rammes af '/*?id=*' og er FORBUDT og bruges ikke. Finder-siden,
    downloads-siden og /fileadmin/-PDF'en er tilladte. apim-fuel-prices-prod.azure-api.net
    svarer 404 paa robots.txt = ingen regler (RFC 9309 2.3.1.3). robots.txt tjekkes ved
    hver koersel for hver URL.

    EFTERPROEVET 01-10-2026: API'et og folderen har de samme 71 stationer (69 med samme vej
    og husnr; Sigrundsvej/Sigrunsvej og Industrivej 2/1 parres paa punktet). CVR 36552816 har
    73 aktive P-enheder (alle branche 473000) = de 71 + hovedkontoret (Andkærvej 26A, Vejle)
    + 'OIL! tank & go Hammelev' (Egemarken 1, start 10-04-2026; BBR's tankbygning dér har
    status 3 = sagsgrunddata, endnu ikke opfoert) - ingen af de to er i API'et eller
    folderen. Kaedens side /om-oil/oil-tank-go/ skriver '70 stationer i Danmark' (formentlig
    skrevet foer Kolding Syd aabnede 18-06-2026). Alle 71 genfindes inden for 150 m af vores
    71 OIL!-raekker (median 5 m), ingen lastbilraekker; 58 af 71 navne er identiske med vores.
    Seks par ligger 110-149 m fra hinanden. I fem af dem er det VORES pin (finderens gamle
    kortpin) der ligger skaevt: BBR-tankbygningen (325) staar ved DAR-punktet i Herning (0 m),
    Viborg (5 m), Rødekro (0-6 m) og Esbjerg V/Sædding Ringvej (31 m), og i Grindsted staar
    butiksbygningen paa Glentevej 3 14 m fra DAR-punktet, mens vores pin reverse-geokoder til
    Vestergade 68 (API'ets GPS ligger ved DAR-punktet i alle fem undtagen Rødekro). Hjørring
    (149 m) er uafgjort: ingen tankbygning ved nogen af punkterne.

    FAELDER:
      * API'ets GPS er ubrugelig som punkt (se _oil_api_poster), og dets tekst har fejl:
        'Nyborg' har Ringes adresse og omvendt, 'Torvegade 23, 3720 Nexø' (Nexø er 3730),
        'Sigrundsvej' (DAR: Sigrunsvej), 'Nordre Boulevard 203' (DAR: 203A). Derfor kommer
        navnet fra folderen og adressen fra den kilde DAR bekraefter.
      * Folderen har ogsaa fejl: Ølgod 'Industrivej 1' - API'et, CVR og vores raekke siger 2,
        og API'ets GPS ligger 20 m fra DAR-punktet for nr. 2 og 60 m fra nr. 1 (BBR: Industrivej
        2 er butiksbygningen fra 2020). Den eksakte adresse naermest GPS'en vinder.
      * Adresser der ikke er DAR-adresser: 'Eli Christensens Vej 1B' (DAR: E Christensens
        Vej), 'Nørre Allé 12' (kun 12A/12B; punktet er familiens midte, adressen kildens),
        'Damhusvej 1B' (findes ikke; punktet er Damhusvej 2, 52 m fra BBR-tankbygningen paa
        Vejlevej 307), 'Vordingborgvej 78 C-E' (-> 78C), Vojens 'Vestergade 1A' (omdoebt: Hans
        Grams Gade 1A).
      * En lignende vej er ikke samme vej: _oil_samme_vej godtager kun stavevarianter.
      * Randers NØ (Jomfruløkken 9, erhvervsomraade) har stjerne i folderen: 'Kun for OIL!
        firmakort kunder'. API'et har priser paa 95 E10, diesel og AdBlue der. Den returneres
        med 'kun_firmakort': True og lastbil='' - om den hoerer paa et offentligt kort, er en
        beslutning, ikke en teknisk fejl.
      * Navne: folderens stednavn ('Bolbro', 'Seden'), byen hvor den forlaenger stedet
        ('Aalborg' + 'Aalborg SV'). Gaar et navn igen (to i Vejle, Ribe, Horsens ...), bruges
        API'ets navn i CSV'ens stil ('Vejle (Syd)', 'Ribe (Centrum)'), saa navnene er entydige.
        API'ets navne bruges ikke alene: 'Nyborg' og 'Ringe' er byttet om dér.
      * Ingen af kilderne siger lastbil-only. En ny station kun i API'et faar lastbil='' -
        tjek den i haanden, foer den tilfoejes (refresh melder den som NY BUTIK).
      * Finderens detaljeside for Kolding (Syd) har 'Vonsildvej 105 A' og en pin 265 m nord for
        stationen; API, folder, CVR og BBR siger Peter Møllers Vej 1. Finderen er ikke kilde.
    Forventet: 71."""
    import dawa
    from retail_sources import _map, _normal_gade_nr, _raw, _ret_kildefejl, _robots_tilladt, _uniq
    api = _oil_api_poster()
    url = _oil_folder_url()
    if not _robots_tilladt(url):
        raise RuntimeError(f'OIL!: robots.txt forbyder nu {url}')
    folder = _oil_folder_poster(_oil_pdf_tekst(_raw(url, 60)))
    if len(folder) < OIL_MIN:
        raise RuntimeError(f'OIL!: folderen {url} gav kun {len(folder)} stationer '
                           f'(forventet ~71) - layoutet er formentlig aendret')
    gA = _map(lambda x: _oil_geokod(x['gade'], x['postnr']), api, 6)
    gF = _map(lambda p: _oil_geokod(p[1], p[2]), folder, 6)

    # Par API -> folder, én-til-én. (1) Samme vej + husnr, hvis noeglen er entydig i begge
    # lister (postnr ignoreres - API'et skriver 3720 for Nexø). (2) DAR-punkterne. (3) API'ets
    # GPS mod folderens DAR-punkt. Naermeste par foerst.
    def noegle(gade):
        vej, nr = dawa.split_street(_normal_gade_nr(gade))     # '78 C-E' -> '78C' i begge
        return (''.join(_oil_ord(vej)), nr.upper()) if vej and nr else None
    kA, kF = [noegle(x['gade']) for x in api], [noegle(p[1]) for p in folder]
    par = {i: kF.index(k) for i, k in enumerate(kA) if k and kA.count(k) == 1 and kF.count(k) == 1}

    def naermest(punkt):
        brugt = set(par.values())
        P = sorted((dawa.hav(*punkt(i), gF[j][0]['y'], gF[j][0]['x']), i, j)
                   for i in range(len(api)) if i not in par and punkt(i)
                   for j in range(len(folder)) if j not in brugt and gF[j][0])
        for d, i, j in P:
            if d <= OIL_PAR_M and i not in par and j not in brugt:
                par[i] = j
                brugt.add(j)
    naermest(lambda i: (gA[i][0]['y'], gA[i][0]['x']) if gA[i][0] else None)
    naermest(lambda i: (api[i]['lat'], api[i]['lon']) if api[i]['lat'] is not None else None)
    # (4) Én tilbage paa hver side i samme postnummer: samme station med tekstfejl i begge.
    rest_a = _collections.defaultdict(list)
    for i in range(len(api)):
        if i not in par:
            rest_a[api[i]['postnr']].append(i)
    rest_f = _collections.defaultdict(list)
    for j in range(len(folder)):
        if j not in par.values():
            rest_f[folder[j][2]].append(j)
    for pn, ii in rest_a.items():
        if len(ii) == 1 and len(rest_f.get(pn, [])) == 1:
            par[ii[0]] = rest_f[pn][0]
    kun_api = [api[i]['navn'] for i in range(len(api)) if i not in par]
    kun_folder = [f'{p[0]} ({p[1]})' for j, p in enumerate(folder) if j not in par.values()]
    if len(kun_api) + len(kun_folder) > OIL_MAX_UENIGE:
        raise RuntimeError(f"OIL!: pris-API'et og folderen er uenige om {len(kun_api) + len(kun_folder)} "
                           f"stationer (kun API: {kun_api[:4]}; kun folder: {kun_folder[:4]}) - "
                           f"en af kilderne er formentlig i stykker")

    navne = dawa.postnumre()
    rang = {'dar': 0, 'dar-vask': 1, 'dar-vejnavn': 2, 'dar-familie': 3, 'dar-nabonummer': 4}
    out = []
    for i, x in enumerate(api):
        j = par.get(i)
        kand = [(gA[i][0], gA[i][1], x['gade'], x['postnr'], 'api', 0)]
        if j is not None:
            kand.append((gF[j][0], gF[j][1], folder[j][1], folder[j][2], 'folder', 1))

        def vaerdi(k):
            h, metode, _, _, _, orden = k
            if not h:
                return (9, 0, orden)
            dg = dawa.hav(h['y'], h['x'], x['lat'], x['lon']) if x['lat'] is not None else 0
            return (rang.get(metode, 8), dg if metode == 'dar' else 0, orden)
        h, metode, gade, pn, kilde, _ = min(kand, key=vaerdi)
        if j is not None:
            sted, _, _, by, note = folder[j]
            if by.lower().startswith(sted.lower()) and len(by) > len(sted):
                sted = by                                   # 'Aalborg' + 'Aalborg SV'
        else:
            sted, by, note = _oil_api_navn(x['navn']), x['by'], ''   # ny station: kun i API'et
            # Kun API'ets tekst bag sig: placer den kun, naar adressen findes direkte i DAR og
            # API'ets GPS ikke modsiger den med over 2 km. 'Østergade 49C' med et forkert
            # postnr lander ellers paa naboens Østergade i en anden by ('dar-nabonummer').
            # En ny station uden punkt bliver en INFO-linje i refresh, ikke en ny raekke.
            dg = dawa.hav(h['y'], h['x'], x['lat'], x['lon']) if h and x['lat'] is not None else 0
            if h and (metode not in ('dar', 'dar-vask') or dg > 2000):
                h, metode = None, f'ikke placeret: kun i API\'et, {metode}, API-GPS {dg:.0f} m fra adressen'
        r = {'brand': 'OIL!', 'name': f'OIL! tank & go {sted}',
             'street': _normal_gade_nr(gade.replace('’', "'").replace('´', "'")), 'postnr': pn,
             'by': navne.get(pn) or by,
             'lat': None, 'lon': None, 'lastbil': '', 'kun_firmakort': 'firmakort' in note.lower(),
             'geokode': f'{metode} ({kilde})' if h else metode, '_api_navn': x['navn']}
        if h:
            if metode != 'dar-nabonummer':     # nabonummeret giver kun punktet, ikke adressen
                r['street'] = f"{h['vejnavn']} {h['husnr']}"   # familie: kildens nr
            r['postnr'] = str(h.get('postnr') or pn)
            r['by'] = h.get('postnrnavn') or r['by']
            r['lat'], r['lon'] = round(h['y'], 6), round(h['x'], 6)
        out.append(r)

    # API'et kan liste samme station to gange (to station_id'er): samme adresse = én raekke
    set_, ud = set(), []
    for r in out:
        k = (r['street'].lower(), r['postnr'])
        if k not in set_:
            set_.add(k)
            ud.append(r)
    # Entydige navne: et navn der gaar igen (folderens 'Vejle' x 2), faar API'ets navn i
    # CSV'ens stil; er det stadig ikke entydigt, vejnavnet i parentes.
    def med_vej(r):
        vej = re.sub(r'\s+\S*\d\S*$', '', r['street'])
        return f"{r['name']} ({vej})"
    for trin in (lambda r: f"OIL! tank & go {_oil_api_navn(r['_api_navn'])}", med_vej):
        tael = _collections.Counter(r['name'] for r in ud)
        for r in ud:
            if tael[r['name']] > 1:
                r['name'] = trin(r)
    for r in ud:
        del r['_api_navn']
    uden = [r for r in ud if r['lat'] is None]
    if len(uden) > OIL_MAX_UDEN_PUNKT:
        raise RuntimeError(f'OIL!: {len(uden)} af {len(ud)} adresser fandtes ikke i DAR '
                           f'(fx {uden[0]["street"]}, {uden[0]["postnr"]}: {uden[0]["geokode"]})')
    return _ret_kildefejl(_uniq(ud))


# ---- Shell (etape 3, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker)
# ---- Shell (etape 3, 01-10-2026: kaedens egen stationsliste, find.shell.com)
# Skrevet til retail_sources.py (hjaelperne er dér). I sources.py: tilfoej foerst
#   from retail_sources import _text, _dk_koord, _ren, _pages, _robots_tilladt, \
#       KILDEFEJL, _ret_kildefejl, _afst_m
# Navnet er shell_tank() og IKKE shell(): sources.shell() findes og bruges af
# reconcile.py (adresse-afstemning og logo-klassifikation), som venter dens format.
SHELL_LAND = 'https://find.shell.com/dk/fuel/locations/da_DK'
SHELL_FORVENTET = (195, 235)          # 01-10-2026: 214 (202 bil + 12 lastbil)
_SHELL_LASTBIL = {'adblue_truck', 'hgv_lane', 'truckport', 'high_speed_diesel_pump'}
# Et 'anlaeg' uden braendstofdata, der hedder sådan, er en butik/vask/cafe (Shell fører
# 'Express Butik Niels B' som eget anlaeg 24 m fra tankanlaegget).
_SHELL_IKKE_TANK = re.compile(r'\b(BUTIK|SHOP|KIOSK|CAF[EÉ]|VASK|WASH)', re.I)
SHELL_ANNEKS_M = 60      # anlaeg uden braendstofdata saa taet paa et tankanlaeg = anneks
SHELL_SOESTER_M = 30     # to anlaeg med forskellig vej/postnr saa taet = kopieret pin

# Kendte fejl i Shells EGNE koordinater. Noegle og format som KILDEFEJL; koordinaterne
# er LAEST FRA tankstationer_dk.csv 01-10-2026 og efterproevet mod DAR, BBR og HK's
# egne pins (hk-hornsyld.dk/find-tankstation, de tidligere HK Benzin-anlaeg).
# Fem af dem er samme fejl: Shell har givet et anlaeg et SOESTERANLAEGS koordinat.
# (Genkontrolleret af en skeptiker 01-10-2026: alle seks raekker staar 0-7 m fra
# DAR-punktet for Shells egen adresse og 4-38 m fra tankbygningen/-tanken; OSM og
# HK's pins er enige, Shells raa pins staar paa soesteranlaeggene.)
KILDEFEJL.update({
    # SHELL EXPRESS SUNDS: Shells punkt er SHELL EXPRESS LUNDs (12 m fra Lunds, 59 km
    # fra Sunds). Raekken staar 0 m fra DAR-punktet og 4 m fra BBR-tankbygningen (325).
    ('Shell', 'sunds hovedgade 24'): {'lat': 56.201863, 'lon': 9.017779},
    # SHELL EXPRESS FAABORG (Årre): Shells punkt er identisk med SHELL EXPRESS
    # KOLLEMORTENs (50 km vaek). Raekken: 0 m fra DAR, 13 m fra BBR-tankbygningen.
    ('Shell', 'faaborgvej 49'): {'lat': 55.586326, 'lon': 8.741098},
    # SHELL EXPRESS HOVEN: Shells punkt er SHELL EXPRESS STRUERs (begge 'Bredgade';
    # 72 km vaek). Raekken: 0 m fra DAR, 6 m fra HK's pin, 32 m fra en aktiv 40.000 l-
    # tank til mineralske olieprodukter (BBR teknisk anlaeg, 2001) paa Bredgade 10.
    ('Shell', 'bredgade 10'): {'lat': 55.850582, 'lon': 8.759696},
    # SHELL EXPRESS BARRIT: Shells punkt er SHELL EXPRESS HORNSYLDs (6,2 km vaek).
    # Raekken: 0 m fra DAR, 10 m fra HK's pin, 38 m fra BBR-tankbygningen (nr. 167).
    ('Shell', 'barrit langgade 169'): {'lat': 55.707292, 'lon': 9.903668},
    # SHELL HEDEHUSENE ROSKILDEVEJ: Shells punkt er HOVEDGADEN 482's (2 m derfra,
    # 1,2 km fra Roskildevej 335) - samme fejl som 08-09-2026 (REFRESH.md). Raekken:
    # 0 m fra DAR, 25 m fra BBR-tankbygningen.
    ('Shell', 'roskildevej 335'): {'lat': 55.650971, 'lon': 12.221417},
    # SHELL CRT KOLDING: Shells punkt ligger 172 m mod vest, 83 m fra Clevers ladehub
    # paa Kokholm 4A. Raekken: 7 m fra DAR-punktet for Kokholm 8 og 10 m fra en
    # 100.000 l DIESELtank (BBR teknisk anlaeg, indhold 13 = diesel, 2020) paa nr. 8.
    ('Shell', 'kokholm 8'): {'lat': 55.532769, 'lon': 9.475221},
})


def _shell_app(h):
    """find.shell.com er en Inertia-app: sidens data ligger i data-page="app"-JSON."""
    m = re.search(r'data-page="app"[^>]*>\s*(\{.*?\})\s*</script>', h, re.S)
    if not m:
        raise ValueError('data-page="app" ikke fundet')
    return json.loads(_html.unescape(m.group(1)))


def _shell_stort(s):
    """'RANDERS NV' -> 'Randers NV', 'GL. KØGE LANDEVEJ 168' -> 'Gl. Køge Landevej 168'.
    Kun tekst der staar HELT med versaler roeres; Shells blandede tekst er urort."""
    s = _ren(s).strip(' ,')
    if not s or s != s.upper():
        return s
    return re.sub(r'\b(Nv|Sv|Nø|Sø)\b', lambda m: m.group(1).upper(), s.title())


def _shell_vej(r):
    """Vejnavnet uden husnummer, til soester-vagten: 'Bredgade 10' -> 'bredgade'."""
    return re.sub(r'\s*\d.*$', '', (r.get('street') or '')).strip().lower()


def shell_tank():
    """Shell (DCC Energi driver Shell i DK) fra kaedens EGEN stationsfinder find.shell.com.

    Kilde: landesiden find.shell.com/dk/fuel/locations/da_DK -> 170 bysider
    (props.geographicListProps.locations, med 'count' pr. by) -> stationerne
    (props.stationListProps.locations: id, navn, adresse, logo_url) -> én stationsside
    pr. anlaeg (props.location: lat/lng, fuels, fuel_pricing, amenities, ev_charging,
    site_status, country_code). Siderne er Inertia-apps med data i data-page="app".
    01-10-2026: 216 anlaeg; bysidernes 'count' summer til 216 = antal unikke id'er
    (hoejst 5 pr. by, ingen bladring). DCC Energi skrev 02-03-2026, at HK-koebet
    giver '216 bemandede og ubemandede tankstationer'; siden er Hundige revet ned
    (BBR 04-03-2026), og et af de 21 HK-anlaeg staar endnu ikke i finderen.
    ~390 kald, ca. 1 min med 8 traade. robots.txt (find.shell.com) er tom - kun en
    kommentar - og tjekkes ved hver koersel. (Shells andre kort-vaerter,
    shellretaillocator/shellfleetlocator.geoapp.me, svarer 403 paa robots.txt og
    bruges IKKE; fleetlocatoren paa shell.dk/find-station er desuden Shell Card-
    accept, dvs. partnerstationer, ikke Shell-maerket.)

    VERIFIKATION 01-10-2026: 214 anlaeg mod vores 213 Shell-raekker (202 + 11 lastbil).
    Bil 202/202 og lastbil 11/12 matchet inden for 150 m (naermeste par, efter
    KILDEFEJL); kun kilden har Shell Truck Recharge City, Horsens (se FAELDER).
    Shells navne ER CSV'ens navne: 212 af de 213 raekker har et kildeanlaeg med samme
    navn, 210 af dem 0 m fra hinanden (Port of Aarhus 47 m, Padborg Nord 112 m). Den
    sidste er Express Butik Niels B (se nedenfor). Lastbil-markeringen er ens paa alle
    212. Listen er AKTUEL: den har Kildebjerg Nord/Syd og Tuelsø Syd (DCC fra
    1/1-2026) og de 20 konverterede HK-anlaeg, og ingen af de lukkede Shell-P-enheder
    i cvr_tjek.KENDTE_MANGLER (Hundige, Aarhus N, CRT Olievej, CRT Lejrvejen,
    Karrebaekvej -> Uno-X). OSM's 41 'Shell'-punkter uden kildeanlaeg (data 31-05-2026)
    er forældet OSM: 40 staar hoejst 57 m fra en raekke med et andet maerke (Uno-X 26,
    Ingo 8, Go'on 3, Circle K 2, OK 1), det sidste paa det nedrevne Hundige-anlaeg.
    NB: 210 af vores raekker har Shells EGNE koordinater, saa et 0 m-match beviser
    kun, at CSV'en kom herfra - ikke at punktet er rigtigt (se FAELDER).

    KATEGORI efter Shells STAMDATA, ikke efter navn eller afstand:
      * braendstof = 'fuels'. Kun naar 'fuels' er TOM, bruges noeglerne i
        'fuel_pricing.prices': SHELL EXPRESS ALLINGÅBRO og SKOVLUND (konverterede
        HK Benzin-anlaeg) har tom 'fuels', men live literpriser paa benzin og diesel.
        Omvendt maa priserne IKKE overtrumfe en udfyldt 'fuels': Shell CRT
        Svenstrup har fuels = diesel + HVO, men prislisten naevner ogsaa benzin -
        med foreningsmaengden blev lastbilanlaegget til en bilstation.
      * ren EV = logo destination-charging-ev, eller hverken benzin eller diesel men
        ladning (ladekoder eller 'ev_charging'). Rammer SHELL RECHARGE AALBORG ØST
        (300 kW, staar i superladere) og 'Express Butik Niels B' - butikken paa
        Niels Bohrs Allé 148, som Shell fører som eget anlaeg: ingen braendstof,
        ingen priser, kaffe/mad og 2 x 300 kW. Selve tankanlaegget dér er
        'EXPRESS NIELS B ODENSE' (24 m fra butikken); vores raekke har butikkens
        navn og punkt og matcher det paa afstand.
      * lastbil ('ja') = diesel uden benzin OG lastbil-tegn (adblue_truck, hgv_lane,
        truckport, high_speed_diesel_pump) eller CRT/TRUCK i navnet: de 9 Shell CRT
        (Commercial Road Transport), TRUCKSTOP - PORT OF AARHUS, Shell CRT Padborg
        Nord og Shell Truck Recharge City. hgv_lane ALENE er ikke nok - 96 bil-
        stationer har det.
      * INGEN braendstofdata (hverken 'fuels' eller prisnoegler) og ingen ladning:
        beholdes kun som bilstation, naar navnet ikke er en butik/vask/cafe OG der
        ikke staar et Shell-tankanlaeg paa samme vej og postnr inden for
        SHELL_ANNEKS_M (efter KILDEFEJL).
        Rammer i dag kun SHELL EXPRESS SUNDS (konverteret HK-anlaeg; logo
        conventional-fuel-site, BBR-tankbygning og CVR-P-enhed 'H.K Olie, Sunds' paa
        adressen). Uden de to vagter ville butikken paa Niels Bohrs Allé blive en
        'ny' bilstation 24 m fra tankanlaegget den dag, Shell fjerner dens ladedata.
        Kun gas/brint (LNG/CNG/H2, findes ikke i DK i dag) -> udeladt.
      * site_status skal vaere 'Active' (alle 216 er det; feltet kan altsaa ikke
        melde lukninger). open_status 'closed'/'unknown' er IKKE lukket - det er
        aabningstiden netop nu (SHELL NIBE aabner kl. 12).

    FAELDER
      * Shells koordinater er IKKE altid stationens: seks rettes i KILDEFEJL ovenfor,
        fem af dem med et soesteranlaegs punkt (Sunds/Lund, Faaborg/Kollemorten,
        Hoven/Struer, Barrit/Hornsyld, Hedehusene Roskildevej/Hovedgaden). Uden dem:
        6 falske 'nye' + 6 falske lukninger paa ren afstand, og 6 KOORD-AFVIGELSER
        (172 m - 72 km) i refresh_retail's navnematch hver uge. Soesterfejlen ramte 4
        af de 20 HK-konverteringer i 2026 - den kommer igen ved naeste konvertering.
        Derfor SOESTER-VAGTEN: to anlaeg inden for SHELL_SOESTER_M med forskelligt
        vejnavn eller postnr AFBRYDER koerslen (efter KILDEFEJL) med begge navne, saa
        en kopieret pin aldrig tilfoejes som en ny raekke oven i soesterens.
      * Flere Shell-pins er forkerte i BAADE kilden og CSV'en (raekkerne kom herfra),
        og de rettes derfor IKKE her - KILDEFEJL-koordinater skal kunne findes i CSV'en:
        SHELL EXPRESS RÅSTED, SHELL RYOMGÅRD, SHELL TØRRING og SHELL VORUP staar
        127-141 m VEST for anlaegget (DAR-punkt, BBR 325/tanke, CVR-P-enhed og OSM er
        enige; samme forskydning, ca. 0,0022 grader laengde). SHELL KILDEBJERG NORD
        staar paa den forkerte side af E20, 55 m fra Syd-anlaeggets tankbygning og
        209 m fra sit eget (Fynske Motorvej 532A); SYD staar ca. 75 m fra 531A.
        Rettes CSV'en, skal NORD ogsaa i KILDEFEJL (209 m > 150 m); de andre er under
        150 m og matcher uden.
      * Shells postnumre og bynavne er ofte skaeve ('ÅLBORG', 'TÅSTRUP', 'GIve', 6710
        for Hjerting) - adressen SKAL gennem dawa.normalize_one (DAR); koordinaten
        afgoer.
      * gaden kan have et lokalitetsled efter komma ('KØBENHAVNSVEJ 302, ØRSLEV',
        'VORDINGBORGVEJ 424,DALBY BORUP') - kun leddet foer kommaet er vej + nr.
      * Shell Truck Recharge City deler grund med CIRCLE K RECHARGE CITY (vores
        bil-raekke, Kai Lindbergs Vej 2A, 26 m): Shells lastbilpumpe er et eget anlaeg
        i Shells stamdata (diesel + GTL, adblue_truck, truckport) - ingen dublet.
        Recharge City's truckdieselanlaeg (aabnet 15-01-2024) har fire udbydere -
        Shell, OK, Circle K og IDS - og OSM har dem som fire pumper (hgv=designated);
        Shells staar 46 m fra Shells pin ved BBR-bygningen paa Kai Lindbergs Vej 2B.
        Shells 'Kai Lindbergs Vej 12' findes ikke i DAR.
      * ALLE by- og stationssider skal lykkes, og ingen byside maa vise faerre anlaeg
        end landesidens 'count' (det ville vaere bladring eller en afkortet side): en
        manglende side er manglende stationer og dermed falske lukninger, saa
        henteren afbryder hellere end at svare halvt.

    Forventet: 214 (202 bil + 12 lastbil)."""
    def _tjek(u):
        if not _robots_tilladt(u):
            raise RuntimeError(f'find.shell.com/robots.txt forbyder {u} (eller kunne ikke '
                               f'laeses) - stopper')
        return u

    top = _shell_app(_text(_tjek(SHELL_LAND)))
    byer = top['props']['geographicListProps']['locations']
    by_urls = [_tjek('https://find.shell.com' + b['link']) for b in byer]
    antal = {u: b.get('count') for u, b in zip(by_urls, byer)}
    sider = _pages(by_urls, lambda h, u: (u, _shell_app(h)['props']['stationListProps']['locations']))
    if {u for u, _ in sider} != set(by_urls):
        raise RuntimeError(f'Shell: {len(set(by_urls) - {u for u, _ in sider})} af '
                           f'{len(by_urls)} bysider uden data - AFBRYDER frem for at svare halvt')
    korte = [u for u, liste in sider if isinstance(antal.get(u), int) and len(liste) < antal[u]]
    if korte:
        raise RuntimeError(f'Shell: {len(korte)} bysider viser faerre anlaeg end landesidens '
                           f'count (fx {korte[0]}) - bladres der nu? AFBRYDER')
    stationer = {}
    for _, liste in sider:
        for x in liste:
            stationer.setdefault(str(x['id']), x)

    st_urls = {sid: _tjek('https://find.shell.com' + x['link']) for sid, x in stationer.items()}

    def _detalje(h, u):
        # En side UDEN location-data skal kaste, saa _pages proever den igen. Foer gav den
        # (u, None), som er sandt, saa der kom intet nyt forsoeg, og vagten nedenfor
        # afbroed hele Shell for én forbigaaende tom side (EXPRESS VIBY J, 01-10-2026;
        # siden svarede fint minutter efter).
        loc = _shell_app(h)['props'].get('location')
        if not loc:
            raise ValueError('stationssiden har ingen location-data')
        return u, loc
    detaljer = {u: d for u, d in _pages(list(st_urls.values()), _detalje)}
    mangler = [sid for sid, u in st_urls.items() if not detaljer.get(u)]
    if mangler:
        raise RuntimeError(f'Shell: {len(mangler)} stationssider uden data (fx id {mangler[0]}) '
                           f'- AFBRYDER frem for at svare halvt')

    out = []
    for sid, x in stationer.items():
        d = detaljer[st_urls[sid]]
        if (d.get('country_code') or 'DK').upper() != 'DK':
            continue
        if (d.get('site_status') or '').lower() != 'active':
            continue
        fuels = set(d.get('fuels') or []) or set((d.get('fuel_pricing') or {}).get('prices') or {})
        benzin = {f for f in fuels if 'gasoline' in f or 'unleaded' in f or '98' in f}
        diesel = {f for f in fuels if 'diesel' in f or 'hvo' in f or f == 'gtl'}
        el = {f for f in fuels if 'recharge' in f or 'electric' in f}
        logo = (x.get('logo_url') or '').rsplit('/', 1)[-1]
        if logo.startswith('destination-charging') or \
                (not (benzin or diesel) and (el or d.get('ev_charging'))):
            continue                                  # ren ladelokation (evt. med butik)
        if fuels and not (benzin or diesel):
            continue                                  # kun gas/brint: ikke dette lag
        navn = _ren(x.get('name') or d.get('name'))
        if not fuels and _SHELL_IKKE_TANK.search(navn):
            continue                                  # butik/vask/cafe som eget 'anlaeg'
        lastbil = bool(diesel and not benzin and
                       (_SHELL_LASTBIL & set(d.get('amenities') or [])
                        or re.search(r'\b(CRT|TRUCK)', navn, re.I)))
        # bysidens format: 'gade[, lokalitet]\npostnr\nby\nDK'
        dele = [p.strip() for p in (x.get('formatted_address') or '').split('\n')]
        pn = next((p for p in dele[1:] if re.fullmatch(r'\d{4}', p)), '')
        i = dele.index(pn) if pn else -1
        lat, lon = _dk_koord(d.get('lat'), d.get('lng'))
        out.append({'brand': 'Shell', 'name': navn,
                    'street': _shell_stort(dele[0].split(',')[0]),
                    'postnr': pn, 'by': _shell_stort(dele[i + 1]) if 0 < i < len(dele) - 1 else '',
                    'lat': lat, 'lon': lon, 'lastbil': 'ja' if lastbil else '',
                    '_uden_data': not fuels})
    lo, hi = SHELL_FORVENTET
    if not lo <= len(out) <= hi:
        raise RuntimeError(f'Shell: {len(out)} anlaeg, forventet {lo}-{hi} - AFBRYDER')
    out = _ret_kildefejl(out)

    # Anlaeg uden braendstofdata ved et Shell-tankanlaeg paa SAMME vej og postnr er et
    # anneks (butik/vask), ikke en station. Foerst EFTER KILDEFEJL, og kun paa samme
    # vej: Sunds' raa pin staar 12 m fra Lund (Silkeborgvej) - det er en kopieret pin,
    # som soester-vagten nedenfor skal melde, ikke et anneks der skal forsvinde.
    tank = [r for r in out if not r['_uden_data'] and r['lat'] is not None]
    out = [r for r in out if not (r['_uden_data'] and r['lat'] is not None and any(
        _afst_m(r['lat'], r['lon'], t['lat'], t['lon']) <= SHELL_ANNEKS_M
        and _shell_vej(r) == _shell_vej(t) and r['postnr'] == t['postnr'] for t in tank))]

    # SOESTER-VAGT: to anlaeg paa samme punkt med forskellig vej eller postnr er en
    # kopieret pin (fire af de 20 HK-konverteringer fik én i 2026). Den skal i KILDEFEJL
    # med raekkens efterproevede koordinat - ellers tilfoejer refresh_retail anlaegget
    # oven i soesteren med soesterens adresse.
    med = [r for r in out if r['lat'] is not None]
    soestre = []
    for j, a in enumerate(med):
        for b in med[j + 1:]:
            dd = _afst_m(a['lat'], a['lon'], b['lat'], b['lon'])
            if dd <= SHELL_SOESTER_M and (_shell_vej(a) != _shell_vej(b) or a['postnr'] != b['postnr']):
                soestre.append(f"{a['name']} ({a['street']}, {a['postnr']}) / "
                               f"{b['name']} ({b['street']}, {b['postnr']}) {dd:.0f} m")
    if soestre:
        raise RuntimeError(f'Shell: {len(soestre)} par af anlaeg har samme pin men forskellig '
                           f'adresse - kopieret koordinat i Shells data; ret i KILDEFEJL '
                           f'(efterproevet mod DAR/BBR) foer naeste koersel: ' + '; '.join(soestre))
    for r in out:
        r.pop('_uden_data', None)
    return out



# ---- Q8_F24 (etape 3, 01-10-2026: bygget af en efterforsker; skeptikeren blev afbrudt, saa
#      paastandene er efterproevet i hovedsessionen mod kaedens raadata, CVR, BBR, OSM og Wayback)
# ---- Q8 og F24. Kraever _robots_tilladt og _dk_postnr fra Normal-blokken.
Q8_F24_URLS = ('https://www.f24.dk/find-station/', 'https://www.q8.dk/find-station/')
# Rigtigt braendstof. FUEL_WITH_APP er en betalingsmaade, FUEL_AD_BLUE_* er AdBlue.
_Q8_BENZIN = ('FUEL_GO_EASY_95', 'FUEL_GO_EASY_98_EXTRA')
_Q8_LASTBIL = ('FUEL_GO_EASY_DIESEL_HIGH_SPEED', 'FUEL_AD_BLUE_TRUCK')


def _q8_f24_liste(url):
    """Den indlejrede "stations"-liste paa en find-station-side -> liste af dicts."""
    if not _robots_tilladt(url):
        raise RuntimeError(f'q8_f24: robots.txt forbyder nu {url} - henter ikke')
    h = _text(url, 90)
    m = re.search(r'"stations"\s*:\s*\[', h)
    if not m:
        raise RuntimeError(f'q8_f24: "stations" findes ikke paa {url} - siden er lavet om')
    return json.loads(_balanced(h, h.index('[', m.start()), '[', ']'))


def _q8_distrikt(sted):
    """'København Nv' -> 'København NV'. Kun de to-bogstavs postdistrikter staar med lille
    andet bogstav hos kaeden; 'Nykøbing Sj', 'Viby J' og 'Esbjerg Ø' er allerede rigtige."""
    return re.sub(r'\s(nv|sv|nø|sø)$', lambda m: ' ' + m.group(1).upper(), sted, flags=re.I)


def _q8_navn(navn):
    """Kaedens '<sted>, <gade>' i CSV'ens stil ('Ålborg SV, Scheelsmindevej 2')."""
    sted, _, gade = _ren(navn).partition(', ')
    sted = _q8_distrikt(sted)
    return f'{sted}, {gade}' if gade else sted


def _q8_gade(gade):
    """Gadedelen af kaedens navn -> 'Vej nr'.

    'Tårnvej 300/Tæbyvej' -> 'Tårnvej 300' og 'Holmegårdsvej/Højengen 1' -> 'Højengen 1'
    (hjoernegrunde: leddet MED husnummer), 'Silkeborgmotorvejen 242B (Nord)' ->
    'Silkeborgmotorvejen 242B', 'Esbjergmotorvejen 647 B' -> 'Esbjergmotorvejen 647B'.
    Intervaller ('Brostykkevej 104-108') beholdes; dawa.split_street klarer dem.
    Uden husnummer ('Motorvejen Nord', 'Slotsgade/Hovedvejen') kommer kun vejen med, og
    adressen afgoeres af koordinaten ved normaliseringen."""
    s = _ren(re.sub(r'\([^)]*\)', ' ', gade or ''))
    dele = [d.strip() for d in s.split('/') if d.strip()]
    med_nr = [d for d in dele if re.search(r'\d', d)]
    g = med_nr[0] if med_nr else (dele[0] if dele else '')
    return re.sub(r'(\d)\s+([A-Za-zÆØÅæøå])$', lambda m: m.group(1) + m.group(2).upper(), g)


def q8_f24():
    """Q8 og F24 (Q8 Danmark A/S, CVR 61082913) fra kaedens EGEN stationsliste.

    Kilde: www.f24.dk/find-station/ og www.q8.dk/find-station/. Begge sider (samme
    Optimizely-CMS) har HELE Q8+F24-listen indlejret i HTML'en som "stations": [...]
    med id, navn, gade, postnr, koordinat, network ('Q8'/'F24'), stationType
    ('MANNED'/'AUTOMATIC') og allServices (FUEL_GO_EASY_95, CAR_WASH, CHARGE_... ).
    Kortet viser netop den liste, naar der ikke er valgt filter;
    POST /station/GetStationsBasedOnFilter/ bruges kun ved filter/soegning.
    Maerket er network (= networkIcon q8.svg/f24.svg), det kunden ser.
    robots.txt paa begge vaerter: 'User-agent: * / Disallow: /soeg/' (01-10-2026).

    Efterproevet 01-10-2026 mod tankstationer_dk.csv, som da havde 105 Q8 og 143 F24:
      * Q8 103/103 og F24 140/140 genfundet paa 0 m (raekkerne kom fra denne liste i
        juli); ingen station i kaedens liste manglede hos os.
      * Fem raekker fandtes kun hos os og blev slettet 01-10-2026. Hovedsessionen
        efterproevede dem selv mod kaedens raadata, CVR, BBR, OSM og Wayback, fordi
        skeptiker-agenten blev afbrudt:
        - 'Q8 Frøslev Vest Motorvejscenter' og F24 'Frøslev Øst, Sønderjyske Motorvej 765'
          er Circle K: CVR har Circle K-P-enhederne 1031844718 (nr. 764) og 1031844696
          (nr. 765) fra 01-01-2026, og vores Circle K-raekker staar 15-18 m derfra. Q8's
          gamle P-enheder (1003139526, 1010068904) staar stadig som aktive - CVR halter -
          men deres adresser (Motorvejen 1 og 2, 6330) findes ikke i DAR, saa cvr_tjek's
          sikkerhedsnet melder dem ikke.
        - 'Q8 Vestervig' (Tygstrupvej 3A) var ikke Q8: den stod hverken i Q8's liste
          16-06-2026 (Wayback, 244 stationer) eller i dag, Q8 Danmark har ingen P-enhed i
          7752-7770, ingen P-enhed i branche 473000 ligger i 7770, og OSM-noden 3050985661
          har aldrig haft et maerke (versioner fra 2014 og 2017). BBR har en tankbygning
          (325, 30 m2, 2014) paa Tygstrupvej 1 med ukendt operatoer. Navnet var 'Q8 ...',
          ikke kaedens '<sted>, <gade>', saa raekken kom ikke fra kaedens liste.
        - 'Hillerød, Frejasvej 23D' og 'Kirke Hyllinge, Vintapperbuen 1A' er VASKEHALLER:
          kaedens liste giver dem kun CAR_WASH/WASH_WITH_APP, og CVR kalder Vintapperbuen-
          enheden 'F24 Vask' (P 1023807668). De filtreres fra her.
        'Q8 Kildebjerg Nord Motorvej' (nu Shell) var allerede slettet ved etape 3a.

    FAELDER:
      * De to sider er IKKE ens. www.q8.dk mangler F24 'Thisted, Thisted Kystvej 9' (ogsaa
        i sitemap.xml, og stationssiden giver 404 paa q8.dk men 200 paa f24.dk), og 12
        F24-anlaegs 150 kW-ladere. Det er vaertsnavnet, ikke backend-instansen: samme
        ARRAffinity gav begge svar (30-09 og 01-10-2026, 4 runder). f24.dk er den
        nyeste. Thisted er en aktiv station (CVR P 1013720904 siden 2006, OSM brand=F24
        5 m fra raekken). Derfor hentes BEGGE og flettes paa id med f24.dk's post
        foerst; en henter paa q8.dk alene havde meldt Thisted som lukket.
        Afviger siderne med mere end 10 stationer, er en af dem i stykker: AFBRYDER.
      * Listen har vaskehaller uden braendstof (se ovenfor). Kun FUEL_GO_EASY_*/
        FUEL_DIESEL_* taeller; FUEL_WITH_APP (betaling) og FUEL_AD_BLUE_* goer ikke.
        Ingen anlaeg er i dag rene ladeanlaeg eller rene lastbilanlaeg: alle 243 med
        braendstof har GoEasy 95. Uden benzin, men med high speed-diesel eller
        lastbil-AdBlue, ville et anlaeg blive Lastbil=ja.
      * temporaryHours er tom paa alle 245, og der er intet felt for planlagt/lukket;
        en lukket station forsvinder blot fra listen (Frøslev, se ovenfor).
      * Kaedens 'street' er smaat efter foerste ord ('Thisted kystvej 9', 'Midtjyske
        motorvej 135'); navnets gadedel er den samme tekst med rigtige versaler og bruges
        i stedet (ens uden versaler paa alle 245). city er upaalidelig: 2860 hedder
        'Herlev', 7400 'Søby v', 9382 'Vildmosen' - postnr/by tages fra koordinaten ved
        normaliseringen. Kaeden skriver ogsaa 'Hirtshalsmotovejen 74' (DAR:
        Hirtshalsmotorvejen) og 'Fåborgvej' (DAR: Faaborgvej).
      * Navn: kaedens eget ('<sted>, <gade>'). To-bogstavs postdistrikter skrives med
        versaler ('Ålborg SV'); refresh_retail sammenligner uden versaler. Kaeden kalder
        Dynamovej 2 (2860 Søborg) 'Herlev, Dynamovej 2'; vores raekke hedder 'Søborg, ...'.
      * Q8Truck (www.q8truck.com, Q8's lastbilkort) er et ANDET net: 48 danske anlaeg,
        hvoraf 29 er Q8/F24-anlaeggene herfra og 19 er lastbilanlaeg paa transportcentre
        og vognmandsgaarde. De er ikke med her - se q8truck().
    Forventet: 103 Q8 + 140 F24 (01-10-2026; 245 poster minus 2 vaskehaller)."""
    lister = [_q8_f24_liste(u) for u in Q8_F24_URLS]
    ids = [{str(x.get('id')) for x in l} for l in lister]
    if len(ids[0] ^ ids[1]) > 10:
        raise RuntimeError(f'q8_f24: f24.dk har {len(ids[0])} og q8.dk {len(ids[1])} stationer, '
                           f'{len(ids[0] ^ ids[1])} forskellige - en af listerne er i stykker')
    alle = {}
    for l in lister:                          # f24.dk foerst: dens post vinder
        for x in l:
            alle.setdefault(str(x.get('id')), x)
    out, ukendt = [], []
    for x in alle.values():
        brand = {'Q8': 'Q8', 'F24': 'F24'}.get((x.get('network') or '').strip())
        if not brand:
            ukendt.append(f"{x.get('network')!r}: {x.get('name')}")
            continue
        tags = {s.get('specificTag') for s in x.get('allServices') or [] if isinstance(s, dict)}
        braendstof = {t for t in tags if t and t.startswith('FUEL_')
                      and t != 'FUEL_WITH_APP' and 'AD_BLUE' not in t}
        if not braendstof:
            continue                          # vaskehal (eller ren lader)
        if (x.get('country') or 'Danmark').strip().lower() not in ('danmark', 'denmark', 'dk'):
            continue
        pn = _dk_postnr(x.get('postalCode'))
        lat, lon = _dk_koord(x.get('latitude'), x.get('longitude'))
        if not pn or lat is None:
            continue
        navn = _q8_navn(x.get('name'))
        gade = navn.partition(', ')[2] or _ren(x.get('street'))
        lastbil = '' if tags & set(_Q8_BENZIN) or not tags & set(_Q8_LASTBIL) else 'ja'
        out.append({'brand': brand, 'name': navn, 'street': _q8_gade(gade), 'postnr': pn,
                    'by': _q8_distrikt(_ren(x.get('city')).title()), 'lat': lat, 'lon': lon,
                    'lastbil': lastbil})
    if ukendt:
        raise RuntimeError(f'q8_f24: ukendt network paa {len(ukendt)} stationer (fx {ukendt[0]}) '
                           f'- nyt maerke? Tag stilling foer det kommer paa kortet')
    out = _uniq(out)
    n = {b: sum(1 for r in out if r['brand'] == b) for b in ('Q8', 'F24')}
    if not (85 <= n['Q8'] <= 120 and 120 <= n['F24'] <= 165):
        raise RuntimeError(f'q8_f24: {n} (forventet ~103 Q8 og ~140 F24) - behandles som en '
                           f'koerselsfejl, ikke som lukninger/aabninger')
    return out


def q8():
    """Kun Q8-anlaeggene fra q8_f24(). Forventet: 103."""
    return [r for r in q8_f24() if r['brand'] == 'Q8']


def f24():
    """Kun F24-anlaeggene fra q8_f24(). Forventet: 140."""
    return [r for r in q8_f24() if r['brand'] == 'F24']


Q8TRUCK_URL = 'https://www.q8truck.com/api/poi/locations'


def q8truck():
    """KANDIDATER til lastbillaget: Q8Truck-anlaeg i Danmark, der ikke er et Q8/F24-anlaeg.

    IKKE i den ugentlige koersel endnu - maerket skal afgoeres foerst (se nedenfor).

    Kilde: Q8Truck International B.V.'s stationsfinder (www.q8truck.com/da/stations,
    linket fra q8.dk/erhverv/q8truck/ som 'Kort over alle Q8Truck-anlaeg'). Next.js-appen
    kalder POST /api/poi/locations; {'query': {'country': 'DK', 'hasFueling': true}} giver
    alle danske anlaeg i ét kald (48 den 01-10-2026). robots.txt: 'User-Agent: * / Allow: /'
    og kun /preview-visual-editor forbudt.

    Navnet baerer nettet i parentes: '(Q8)', '(F24)', '(Q8Truck/Q8)' og '(Q8Truck/F24)' er
    de 29 Q8/F24-anlaeg, som q8_f24() allerede har som personbilanlaeg (kodeserie DK8xxx
    for de nyeste). '(Q8Truck)' og '(Q8Truck/Cargo Syd)' er de 19 rene lastbilanlaeg:
    produkter kun diesel/AdBlue/HVO100/LBG, ingen benzin.

    FAELDER:
      * MAERKET er uafklaret. Q8Truck er et kortnet ('+1.200 anlaeg i Europa'), og flere
        anlaeg ligger paa en vognmands eller en anden kaedes grund: 'Høje Tåstrup TC' 0-1 m
        fra SHELL CRT TAASTRUP og Uno-X Truck Tåstrup, 'Køge TC_E20' 17 m fra CIRCLE K
        TRUCK KØGE, 'Sæby Syd TC_E45' 50 m fra TRUCKANLÆG SÆBY, 'Vejle TC_E45' 48 m fra
        TRUCKANLÆG DTC VEJLE, 'Hirtshals TC' 40 m fra Go'on Hirtshals - Truck, 'Nørre
        Alslev TC' 50 m fra CIRCLE K TRUCK NØRRE ALSLEV. Kun 'Padborg (IDS Truck Center,
        Thorsvej 3)' er med sikkerhed Q8's eget (CVR P 1003139599: Q8 DANMARK A/S,
        Thorsvej 3, branche 468100, siden 1985) - 3 m fra vores F24 Padborg, Thorsvej 1.
      * Adressefeltet begynder ofte med vaertens firmanavn ('Kolding Lastvognscenter ApS
        Platinvej 55', 'K Hansen Transport A/S Park Alle 18'); kun koordinaten er brugbar.
    Navn: 'Q8Truck <sted>' ud fra '<sted> (Q8Truck) (DKnnnn)'.
    Forventet: 19 (01-10-2026)."""
    if not _robots_tilladt(Q8TRUCK_URL):
        raise RuntimeError('q8truck: robots.txt paa www.q8truck.com forbyder nu /api/ - henter ikke')
    d = _post_json(Q8TRUCK_URL, {'query': {'country': 'DK', 'hasFueling': True}}, 60,
                   headers={'Referer': 'https://www.q8truck.com/da/stations?mode=fueling'})
    out = []
    for x in (d or {}).get('results') or []:
        navn = _ren(x.get('name'))
        los = x.get('q8TruckLos') or {}
        if not x.get('isQ8TruckLocation') or not x.get('hasFueling'):
            continue
        if re.search(r'\((?:Q8Truck/)?(?:Q8|F24)\)', navn):
            continue                          # Q8/F24-anlaeg: kommer fra q8_f24()
        if (los.get('state') or 'Open') not in ('Open', 'TemporarilyClosed'):
            continue
        a = los.get('address') or {}
        if (a.get('country') or 'DK').upper() != 'DK':
            continue
        c = x.get('coordinates') or {}
        lat, lon = _dk_koord(c.get('latitude'), c.get('longitude'))
        if lat is None:
            continue
        sted = _ren(re.sub(r'\s*\(.*$', '', navn).replace('_', ' '))
        out.append({'brand': 'Q8', 'name': f'Q8Truck {sted}', 'street': _ren(a.get('street')),
                    'postnr': _dk_postnr(re.sub(r'^DK-', '', a.get('zipCode') or '')),
                    'by': _ren(a.get('city')), 'lat': lat, 'lon': lon, 'lastbil': 'ja'})
    if not 10 <= len(out) <= 35:
        raise RuntimeError(f'q8truck: {len(out)} anlaeg (forventet ~19) - koerselsfejl')
    return out


# ================================================================ ETAPE 3B: SPISESTEDER
# Tilfoejet 01-10-2026. Hver blok er bygget af en efterforsker og genkoert og efterproevet af
# en skeptiker, der ogsaa rettede koden (bl.a. 'aabner snart'-filtre og pin-vagter mod DAR).
# Carl's Jr.-blokken skal staa foerst: Subway, Halifax og Gasoline Grill bruger dens
# hjaelpere (_robots_krav, _vaert_crawl_delay, _dar_adressepunkt, _ikke_aaben_endnu).
# Starbucks, KFC og Cocks & Cows er kun til rapport (refresh_retail.KUN_RAPPORT).
# McDonald's og Joe & The Juice har ingen tilladt kaedekilde (Akamai/Vercel-blokering).


# ---- Carl's Jr. (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
# ================================================================ ETAPE 3: SPISESTEDER
# Carl's Jr., Subway, Halifax og Gasoline Grill - tilfoejet 01-10-2026.
# Kaedernes EGNE lister. robots.txt er laest i haanden (RFC 9309, laengste match) og tjekkes
# igen ved hver koersel med _robots_tilladt - for HVER url der hentes, ikke kun startsiden.
# Efterproevet 01-10-2026 (bygget, derefter genkoert og rettet af en skeptiker) mod
# fastfood_kaeder_dk.csv, Foedevarestyrelsens smiley-register (pub.fvst.dk/publikationer/
# Smileydata.xml, hentet samme dag), CVR og DAR - se den enkelte docstring.
#
# BEMAERK ved indkoblingen: spisestederne ligger i fastfood_kaeder_dk.csv, som hverken
# refresh_retail.FILER, EJER eller KATEGORI omfatter endnu. EJER-linjerne er:
#   'carlsjr': ["Carl's Jr."], 'subway': ['Subway'], 'halifax': ['Halifax'],
#   'gasolinegrill': ['Gasoline Grill']
# halifax() og gasolinegrill() slaar adresser op i DAR (som oil()) og kraever derfor
# Datafordeler-noeglen, ligesom normaliseringen i refresh_retail. carlsjr() bruger DAR til at
# kontrollere kaedens naale, men klarer sig uden (se docstring).

# ---------------------------------------------------------------- faelles hjaelpere
# Bruges af alle fire hentere. Indsaettes de enkeltvis, kommer disse med hver gang;
# en identisk gentagelse er harmloes.


def _vaert_crawl_delay(url, loft=30):
    """Sekunder fra vaertens 'Crawl-delay' (ikke en del af RFC 9309, men respekteres).
    Laeses af den robots.txt _robots_tilladt allerede har hentet - kald den foerst.
    Den strengeste linje gaelder, ogsaa en uden for en User-agent-gruppe (halifax.dk har
    'Crawl-delay: 10' foer Yoast-blokken). 0 hvis ingen."""
    p = urllib.parse.urlsplit(url)
    tekst = _ROBOTS.get(f'{p.scheme}://{p.netloc}') or ''
    tal = [float(x) for x in re.findall(r'(?im)^\s*crawl-delay\s*:\s*([\d.]+)', tekst)]
    return min(max(tal), loft) if tal else 0


def _robots_krav(navn, *urls):
    """Rejser RuntimeError hvis robots.txt forbyder EN af urls. robots.txt hentes én gang pr.
    vaert (_ROBOTS-cachen), saa det koster intet at tjekke hver side for sig."""
    for url in urls:
        if not _robots_tilladt(url):
            raise RuntimeError(f'{navn}: robots.txt forbyder nu {url} - henter ikke')


def _dar_adressepunkt(gade, pn):
    """Kaedens 'Vej nr' + postnr -> (lat, lon, postnrnavn) fra DAR, el. (None, None, '').
    Bruger oil()'s opslag (_oil_geokod: eksakt, Adressevask, stavevariant, husnummerfamilie).
    Et DAR-udfald rejser DawaNede - det maa ikke ligne 'findes ikke'."""
    hit, _ = _oil_geokod(gade, pn)
    if not hit:
        return None, None, ''
    return round(hit['y'], 6), round(hit['x'], 6), hit.get('postnrnavn') or ''


# Kort statustekst (et navn, et listekort, en aabningslinje) der siger 'ikke aabnet endnu'.
# _aabner_senere klarer 'åbner snart' og 'åbner den 5. november'; dette tager resten.
# Bruges KUN paa korte tekster: en hel restaurantside kan sige 'køkkenet åbner kl. 11'.
_IKKE_AABEN = re.compile(r'kommer snart|åbner snart|aabner snart|coming soon|opening soon'
                         r'|opens (?:on|in)\b|grand opening', re.I)


def _ikke_aaben_endnu(tekst):
    return bool(tekst) and (_aabner_senere(tekst) or bool(_IKKE_AABEN.search(_ren(tekst))))


# ---------------------------------------------------------------- Carl's Jr.
KILDEFEJL.update({
    # Carl's Jr Kolding Storcenter: kaedens koordinat (55.500952, 9.482216) ligger ved Kolding
    # Sygehus (DAR naermest: Sygehusvej 2), 1,9 km fra centret. Restauranten ligger paa Bilka
    # Torv / Blaa indgang i Kolding Storcenter (centrets egen butiksside koldingstorcenter.dk/
    # butikker/carls-jr, 01-10-2026) og har smiley 73161 ('Carl's Jr. Kolding 1953', Skovvangen
    # 42) - samme id som kaedens attributes.smileyscheme. Koordinaten er LAEST FRA CSV'EN
    # (raekken 'Carl's Jr Kolding Storcenter', Skovvangen 40 = DAR-punktet; Bilka-bygningen,
    # BBR 322 paa nr. 40, staar 73 m derfra). carlsjr()'s naalekontrol ville give samme punkt;
    # posten staar her som belaeg. Efterproevet 01-10-2026.
    ("Carl's Jr.", 'skovvangen 40-42'): {'lat': 55.511859, 'lon': 9.459589},
    # Carl's Jr Storcenter Nord: kaedens pin staar i centrets nordende (DAR naermest:
    # Helsingforsgade 19E), 229 m fra vores raekke paa DAR-punktet for Finlandsgade 17 - den
    # adresse kaeden, smiley 706423 og CVR-P-enheden 1022386790 bruger. Begge punkter er paa
    # centrets grund (BBR: butikscentret, anvendelse 324, ligger midt imellem). Ikke en grov
    # fejl, men uden rettelsen melder refresh_retail en KOORD-AFVIGELSE hver uge for det samme
    # sted. Koordinaten er LAEST FRA CSV'EN. Efterproevet 01-10-2026.
    ("Carl's Jr.", 'finlandsgade 17'): {'lat': 56.169353, 'lon': 10.188777},
})


# Usynlige tegn kaederne har i navnene (U+200B nulbreddemellemrum m.fl.). str.split() og
# dermed _ren() fjerner dem IKKE.
_USYNLIGE_TEGN = dict.fromkeys(map(ord, '​‌‍⁠﻿'))


def _carls_navn(s):
    return _ren((s or '').translate(_USYNLIGE_TEGN)).replace('’', "'").replace('´', "'")


CARLSJR_URL = 'https://carlsjr.dk/om-carls-jr/find-os/'
# Kaedens naal maa hoejst ligge saa langt fra DAR-punktet for kaedens EGEN adresse. Maalt
# 01-10-2026: 14 af 15 ligger 6-229 m derfra (store centre/Bilka-grunde); Kolding 1.871 m.
CARLSJR_MAX_NAAL_M = 500


def carlsjr():
    """Carl's Jr. (drives af Salling Group A/S, CVR 35954716) fra kaedens EGEN restaurantliste.

    Kilde: carlsjr.dk/om-carls-jr/find-os/ (Next.js app-router). Hele listen ligger server-
    renderet i RSC-payloaden under "initialStores" - samme opbygning som netto.dk (netto()):
    name, address{street, zip, city, country}, coordinates [lon, lat], sapSiteId,
    attributes.smileyscheme (= Foedevarestyrelsens smiley-id) og hours for de naeste 7 dage.
    robots.txt: 'User-agent: * / Allow: /' (01-10-2026).

    Efterproevet 01-10-2026: 15 restauranter = vores 15 = kaedens eget tal ('Salling Group
    driver alle 15 Carl's Jr. restauranter i Danmark', carlsjr.dk/om-carls-jr/). Smiley-
    registret har praecis 15 Carl's Jr.-restauranter under CVR 35954716 (+ kaedehovedkontoret,
    Søndergade 27) og ingen andre, og alle 15 CVR-P-enheder er aktive (9 deler Bilka-varehusets
    P-enhed). Horsens ('Carls Jr. Recharge City Horsens', P 1029623003, aktiv siden 11-09-2023)
    er endnu ikke smiley-kontrolleret, men staar paa listen med aabningstider alle 7 dage.
    13 kildepunkter ligger 6-139 m fra vores raekker; de to sidste rettes i KILDEFEJL (Kolding
    Storcenter 1,9 km vaek ved sygehuset, Storcenter Nord 229 m inde paa centrets grund).
    Navnene er CSV'ens ('Carl's Jr Vejle'), saa refresh_retail parrer paa navn.

    FAELDER:
      * 6 af 15 navne begynder med et usynligt U+200B ('\\u200bCarl's Jr Tilst'). _ren() fjerner
        det ikke, og saa er navnet aldrig lig CSV'ens - derfor _carls_navn().
      * coordinates er [lon, lat] (som Netto); _dk_koord vender et byttet par.
      * NAALENE ER IKKE ALTID RIGTIGE (Kolding: 1,9 km vaek). En ny restaurant tilfoejes
        automatisk med kaedens naal, saa hver naal kontrolleres mod DAR-punktet for kaedens
        egen adresse (_dar_adressepunkt; alle 15 adresser findes). Ligger den over
        CARLSJR_MAX_NAAL_M fra adressen (eller mangler den), bruges adressepunktet. Svarer
        DAR ikke, eller mangler Datafordeler-noeglen, beholdes naalene (KILDEFEJL retter
        stadig Kolding).
      * Gaden er kaedens stavning: 'Solkildealle 2' (DAR: Solkilde Alle 2), 'Skovvangen 40-42',
        'Karl Krøyers Vej 19-21', 'Storebæltsvej 7A' (smiley: 7 D). city er upraecis (5230
        'Odense', 8960 'Randers Sø') - postnr/by tages fra DAR ved normaliseringen.
      * Der er intet felt for 'aabner snart', og created/modified er tidspunktet siden blev
        bygget. En restaurant med aabningstider der ALLE er 'closed' de naeste 7 dage (ikke
        aabnet endnu eller midlertidigt lukket) udelades - refresh_retail melder den saa som
        mulig lukning i stedet for at tilfoeje den. En lukket restaurant forsvinder fra listen.
      * Sidefodens 'Carl's Jr. Danmark, Søndergade 27, 8000 Århus C' er hovedkontoret (fri
        tekst, ikke i initialStores).
    Forventet: 15."""
    import dawa
    _robots_krav('carlsjr', CARLSJR_URL)
    arr = _json_after(_flight(_text(CARLSJR_URL, 90)), 'initialStores', '[')
    out = []
    for x in arr:
        a = x.get('address') or {}
        if (x.get('brand') or 'carlsjr') != 'carlsjr' or (a.get('country') or 'DK') != 'DK':
            continue
        navn = _carls_navn(x.get('name'))
        if _ikke_aaben_endnu(navn):
            continue
        timer = [t for t in (x.get('hours') or []) if isinstance(t, dict)]
        if timer and all(t.get('closed') for t in timer):
            continue                                  # lukket hele ugen
        c = (x.get('coordinates') or []) + [None, None]
        lat, lon = _dk_koord(c[1], c[0])
        out.append({'brand': "Carl's Jr.", 'name': navn or "Carl's Jr",
                    'street': _ren(a.get('street')), 'postnr': _dk_postnr(a.get('zip')),
                    'by': _q8_distrikt(_ren(a.get('city'))), 'lat': lat, 'lon': lon})
    out = _ret_kildefejl(_uniq(out))
    for r in out:
        if _kfnoegle(r) in KILDEFEJL or not (r['street'] and r['postnr']):
            continue
        try:
            la, lo, _ = _dar_adressepunkt(r['street'], r['postnr'])
        except (dawa.DawaNede, dawa.NoegleMangler):
            break                                     # DAR nede/ingen noegle: behold naalene
        if la is not None and (r['lat'] is None or
                               _afst_m(r['lat'], r['lon'], la, lo) > CARLSJR_MAX_NAAL_M):
            r['lat'], r['lon'] = la, lo
    if not 10 <= len(out) <= 30:
        raise RuntimeError(f"carlsjr: {len(out)} restauranter (forventet ~15) - behandles som en "
                           f"koerselsfejl, ikke som lukninger/aabninger")
    return out


# ---- Subway (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
# ---------------------------------------------------------------- Subway
# Kraever de faelles hjaelpere fra Carl's Jr.-blokken (afsnittet 'faelles hjaelpere' oeverst
# i ETAPE 3: SPISESTEDER).
SUBWAY_URL = 'https://restaurants.subway.com/denmark'
# 'Butik 1051', 'Storcenter 1': Yext-linjen er en enhed, ikke en gade.
_SUBWAY_ENHED = re.compile(r'^(?:butik|storcenter|unit|shop)\b', re.I)
# Butikker hvis c_storeStatusType=false er FORAELDET (franchisenr. -> belaeg). Alle andre med
# false udelades (se docstring).
_SUBWAY_STATUS_FORAELDET = {
    # Subway Kolding Storcenter (S14 ApS, CVR 42425834, P 1027211166, aktiv siden 31-05-2021):
    # 'Store Closed'/'Disaster' i Yext, men 01-10-2026 viser subway.dk/butikker den som 'Åben
    # nu' (Skovvangen 42C, i dag 10-20), Kolding Storcenters butiksside har ugens
    # aabningstider (28/9-4/10), og smiley 995599 er aktiv (sidste kontrol 05-03-2024).
    '69031': 'Kolding Storcenter - flaget er foraeldet (efterproevet 01-10-2026)',
}


def _subway_side(h, u):
    """En Yext-restaurantside -> raekke-dict. Lukkede/udenlandske/ikke-aabne faar '_ude': True,
    saa subway() kan skelne dem fra sider der slet ikke blev hentet (_pages taeller dem ikke)."""
    m = re.search(r'<script class="js-hours-config" type="text/data">(.*?)</script>', h, re.S)
    if not m:
        raise ValueError(f'Yext-profilen mangler paa {u}')
    p = json.loads(m.group(1)).get('profile') or {}
    a = p.get('address') or {}
    if p.get('closed') or (a.get('countryCode') or 'DK') != 'DK':
        return {'_ude': True}
    if p.get('c_storeStatusType') is False and \
            str(p.get('c_franchiseNum') or '') not in _SUBWAY_STATUS_FORAELDET:
        return {'_ude': True}                         # 'Store Closed', ikke aabnet endnu o.l.
    fm = p.get('featuredMessage')
    if any(_ikke_aaben_endnu(t) for t in (p.get('name'), p.get('c_storeStatusTypeDesc'),
                                          fm.get('description') if isinstance(fm, dict) else fm)):
        return {'_ude': True}
    linje1 = _ren(a.get('line1'))
    gade = linje1.split(',')[0].strip()
    navn = f'Subway {gade}'
    if _SUBWAY_ENHED.match(gade):
        if a.get('extraDescription'):
            navn += f" ({_ren(a.get('extraDescription'))})"
        gade = _ren(a.get('line2')) or gade
    k = p.get('yextDisplayCoordinate') or p.get('geocodedCoordinate') or {}
    lat, lon = _dk_koord(k.get('lat'), k.get('long'))
    by = _ren(a.get('city'))
    return {'brand': 'Subway', 'name': navn, 'street': gade,
            'postnr': _dk_postnr(a.get('postalCode')),
            'by': {'Copenhagen': 'København'}.get(by, by), 'lat': lat, 'lon': lon}


def subway():
    """Subway fra kaedens EGEN restaurantfinder, restaurants.subway.com (Subway IP LLC, Yext).

    Kilde: restaurants.subway.com/denmark - en by-oversigt med antal pr. by
    ('data-count="(3)"'). Byer med én restaurant linker direkte til restaurantsiden, de andre
    (Aalborg, Copenhagen) til en byside med 'Teaser-title'-links. Hver restaurantside har hele
    Yext-profilen som JSON i <script class="js-hours-config">: address{line1, line2,
    extraDescription, postalCode, city}, closed, c_storeStatusType, yextDisplayCoordinate,
    c_franchiseNum. 1 + 2 + 15 sider. robots.txt: 'User-agent: *' uden regler (01-10-2026);
    hver side tjekkes alligevel.

    Efterproevet 01-10-2026: 15 restauranter = vores 15, alle 15 paa 0 m (CSV'en kom herfra).
    Uafhaengigt: www.subway.dk/butikker (den danske master-franchisetager Subcom Denmark ApS,
    CVR 45576523) viser de samme 15 som 'Åben nu'; CVR har 14 aktive restaurant-P-enheder under
    Subcom + S14 ApS (CVR 42425834) i Kolding; smiley-registret har praecis disse 15. Yext-
    naalene ligger 1-165 m fra DAR-punktet for butikkens adresse (Field's 165 m).

    HVORFOR IKKE www.subway.dk/butikker som kilde (ét kald, samme 15): dens punkter er
    upaalidelige ('Aalborg City' med Amager Centrets koordinat, Kolding 1 km vaek), Ishøj
    mangler postnummer, Vejle Banegårds CMS-beskrivelse er stadig 'Kommer snart!' (kortet
    siger 'Åben nu'), og robots.txt dér forbyder /api/ og /_next/. Den er en god
    KRYDSKONTROL af populationen, ikke en kilde til koordinater.

    FAELDER:
      * Stierne har ikke-ASCII ('denmark/ishøj/butik-1051', 'østeragade-16') og skal
        procent-kodes, ellers fejler urllib med UnicodeEncodeError.
      * line1 er ikke altid en gade: 'Butik 1051' (gaden staar i line2: 'Ishøj Store Torv 24')
        og 'Storcenter 1' (Lyngby; ingen line2). Navnet faar da centret i parentes som i CSV'en
        ('Subway Butik 1051 (Ishøj Bycenter)'). 'Reberbanegade 3, Amager Øst' -> 'Reberbanegade 3'.
      * city er engelsk/upraecis ('Copenhagen', 9200 'Aalborg', 8960 'Randers'); postnr/by
        tages fra DAR ved normaliseringen.
      * Yexts 'closed' er permanent lukning. c_storeStatusType=false ('Store Closed', evt. en
        butik der ikke er aabnet endnu) udelades OGSAA - ellers ville den ugentlige koersel
        tilfoeje en butik foer den aabner - undtagen franchisenumre i _SUBWAY_STATUS_FORAELDET:
        Kolding (S14 ApS, 69031) har haft 'Store Closed'/'Disaster' siden 2022, mens den er
        aaben (se dict'en). En udeladt eksisterende butik meldes som mulig lukning, slettes ikke.
      * Antallet tjekkes mod summen af by-oversigtens data-count; afviger det, er en side
        faldet ud, og henteren giver op i stedet for at melde falske lukninger.
    Forventet: 15."""
    _robots_krav('subway', SUBWAY_URL)
    kod = lambda u: urllib.parse.quote(urllib.parse.unquote(u), safe=':/')
    h = _text(SUBWAY_URL, 90)
    led = re.findall(r'class="Directory-listLink" href="([^"]+)"[^>]*data-count="\((\d+)\)"', h)
    if not led:
        raise RuntimeError(f'subway: ingen byer paa {SUBWAY_URL} - siden er lavet om')
    forventet = sum(int(n) for _, n in led)
    sider = []
    for href, n in led:
        u = urllib.parse.urljoin(SUBWAY_URL, _html.unescape(href))
        if int(n) == 1 and urllib.parse.urlsplit(u).path.count('/') >= 3:
            sider.append(u)
            continue
        _robots_krav('subway', kod(u))
        hb = _text(kod(u), 90)
        sider += [urllib.parse.urljoin(u, _html.unescape(x))
                  for x in re.findall(r'<a href="([^"]+)" class="Teaser-title"', hb)]
    sider = [kod(u) for u in dict.fromkeys(sider)]
    if len(sider) != forventet:
        raise RuntimeError(f'subway: {len(sider)} restaurantsider, men by-oversigten siger '
                           f'{forventet} - AFBRYDER')
    _robots_krav('subway', *sider)
    # _pages godtager op til 2 fejlede sider; her er hver side en restaurant, saa en
    # manglende side ville blive en falsk lukning. Derfor kraeves ALLE sider.
    raa = _pages(sider, _subway_side, workers=4)
    if len(raa) < forventet:
        raise RuntimeError(f'subway: kun {len(raa)} af {forventet} restaurantsider kunne hentes '
                           f'- AFBRYDER frem for at melde falske lukninger')
    out = _ret_kildefejl(_uniq([r for r in raa if not r.get('_ude')]))
    if not 10 <= len(out) <= 40:
        raise RuntimeError(f'subway: {len(out)} restauranter (forventet ~15) - behandles som en '
                           f'koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Halifax (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
# ---------------------------------------------------------------- Halifax
# Kraever de faelles hjaelpere fra Carl's Jr.-blokken (afsnittet 'faelles hjaelpere' oeverst
# i ETAPE 3: SPISESTEDER).
KILDEFEJL.update({
    # Halifax Lyngby: kaeden skriver kun 'Handelstorvet, 2800 Lyngby' (intet husnummer), saa
    # adressen kan ikke slaas op. DAR har netop én adresse paa Handelstorvet i 2800 (nr. 10);
    # vores raekke staar paa dens punkt. Smiley 1240534 'Halifax Burgers Lyngby',
    # 'Handelstorvet 0'; CVR-P-enheden 1022373206 siger 'Nørgaardsvej 1B' (DAR-punkt 46 m
    # derfra). Koordinaten er LAEST FRA CSV'EN. Efterproevet 01-10-2026.
    ('Halifax', 'handelstorvet'): {'street': 'Handelstorvet 10', 'postnr': '2800',
                                   'by': 'Kongens Lyngby', 'lat': 55.769676, 'lon': 12.505358},
})


HALIFAX_URL = 'https://halifax.dk/restauranter/'
HALIFAX_SIDER = ('https://halifax.dk/wp-json/wp/v2/pages?parent={}&per_page=100'
                 '&_fields=id,slug,link,title,content')
_HALIFAX_ADR = re.compile(r'<a href="https?://(?:maps\.app\.goo\.gl|goo\.gl|'
                          r'(?:www\.)?google\.[a-z]+/maps)[^"]*">'
                          r'\s*([^<]+?),\s*(\d{4})\s+([^<]+?)\s*</a>')


def halifax():
    """Halifax (Halifax A/S, CVR 29938008) fra kaedens EGEN restaurantliste.

    Kilde: halifax.dk/restauranter/ (WordPress/YOOtheme). Gitteret dér er listen: ét kort pr.
    restaurant med omraadet ('Amager') og gaden ('Amagerbro Torv 13'), men UDEN postnummer og
    koordinat. Postnummeret staar paa restaurantsiderne ('Skomagergade 38, 4000 Roskilde', et
    Google Maps-kortlink uden koordinat); de hentes i ét kald fra sidernes WordPress REST-API
    (/wp-json/wp/v2/pages?parent=<restauranter-sidens id>), med restaurantsiderne selv som
    reserve (ogsaa hvis robots.txt engang forbyder /wp-json/). Punktet er adressens DAR-punkt
    (_dar_adressepunkt); vores 11 raekker staar ogsaa paa DAR-punkterne.
    robots.txt: 'User-agent: * / Disallow:' (alt tilladt) og 'Crawl-delay: 10' - overholdt,
    ogsaa mellem robots.txt og foerste side. Hver url tjekkes mod robots.txt.

    Efterproevet 01-10-2026: 10 restauranter; vi har 11. Den 11., 'Halifax Nørrebro
    (Frederiksborggade)', Frederiksborggade 35, LUKKEDE 28-02-2026: siden omdirigeres (301) til
    København K, dens deaktiverede tekst (sidst rettet 27-02-2026) siger 'Halifax Nørrebro
    lukker den 28. februar ... farvel til den første Halifax nogensinde. Siden 2007 ...', og
    smiley-registret har nu 'Philly & Burgers Nørreport ApS' (CVR 46522788, stiftet 29-05-2026)
    paa adressen, kontrolleret 05-08 og 28-09-2026. Smiley-registret har praecis 10 Halifax-
    restauranter under CVR 29938008 - de samme 10 som gitteret; de matcher vores raekker paa 0 m.

    FAELDER:
      * Menuen oeverst paa alle sider har STADIG 'Halifax Nørrebro' (omdirigeret), og REST-API'et
        giver den som en publiceret side. Populationen tages derfor KUN fra gitteret.
      * Et kort der siger 'Åbner snart'/'Kommer snart' (ny restaurant) udelades; ellers ville
        den ugentlige koersel tilfoeje den foer den aabner.
      * Lyngby har ingen husnummer ('Handelstorvet, 2800 Lyngby') - rettes i KILDEFEJL til
        DAR's eneste adresse paa Handelstorvet (nr. 10). Kaedens bynavne er uensartede
        ('2100 København', '2300 københavn S', '1360 Indre By'); by tages fra DAR.
      * Crawl-delay 10: kaldene ligger 10 s fra hinanden (reserven yderligere 10 s pr. side).
      * Navnet er 'Halifax ' + kortets omraade, som i CSV'en ('Halifax Østerbro').
      * CVR duer ikke til aaben/lukket her: Halifax A/S har stadig aktive P-enheder for
        Frederiksborggade 35 (lukket 28-02-2026) og Jernbanegade 4, Odense (i dag Madklubben
        Odense ifoelge smiley-registret).
    Forventet: 10."""
    import http.client
    _robots_krav('halifax', HALIFAX_URL)
    pause = _vaert_crawl_delay(HALIFAX_URL)
    time.sleep(pause)                                 # robots.txt blev lige hentet
    h = _text(HALIFAX_URL, 90)
    kort = []
    for blok in re.split(r'class="[^"]*fs-load-more-item', h)[1:]:
        t = re.search(r'<h3[^>]*>\s*<a href="(https://halifax\.dk/restauranter/[^"/]+/)"[^>]*>'
                      r'(.*?)</a>', blok, re.S)
        g = re.search(r'<div class="el-content[^"]*">(.*?)</div>', blok, re.S)
        if not t:
            continue
        omraade = _ren(re.sub(r'<[^>]+>', ' ', t.group(2)))
        gade = _ren(re.sub(r'<[^>]+>', ' ', g.group(1))) if g else ''
        # Kortets egne tekster: titel, adresse og evt. etiketter ('Læs mere', 'Book bord' i dag)
        etiket = ' '.join(_ren(re.sub(r'<[^>]+>', ' ', x)) for x in re.findall(
            r'<(?:div|span)[^>]*class="[^"]*(?:el-meta|el-subtitle|fs-grid-meta|uk-label|uk-badge)'
            r'[^"]*"[^>]*>(.*?)</(?:div|span)>', blok, re.S))
        if _ikke_aaben_endnu(f'{omraade} {gade} {etiket}'):
            continue                                  # ikke aabnet endnu
        kort.append((t.group(1), omraade, gade))
    if not kort:
        raise RuntimeError(f'halifax: ingen restaurantkort paa {HALIFAX_URL} - siden er lavet om')
    pid = re.search(r'\bpage-id-(\d+)\b', h)
    adr = {}
    if pid and _robots_tilladt(HALIFAX_SIDER.format(pid.group(1))):
        time.sleep(pause)
        try:
            for s in _json(HALIFAX_SIDER.format(pid.group(1)), 60):
                m = _HALIFAX_ADR.search(((s.get('content') or {}).get('rendered')) or '')
                if m:
                    adr[s.get('link')] = m.groups()
        except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
            adr = {}                                  # URLError/timeout er OSError -> reserven
    out = []
    for link, omraade, gade in kort:
        if link not in adr:              # reserve: restaurantsiden selv
            _robots_krav('halifax', link)
            time.sleep(pause)
            m = _HALIFAX_ADR.search(_text(link, 60))
            if not m:
                raise RuntimeError(f'halifax: ingen adresse paa {link} - siden er lavet om')
            adr[link] = m.groups()
        g, pn, by = (_ren(x) for x in adr[link])
        out.append({'brand': 'Halifax', 'name': f'Halifax {omraade}', 'street': g or gade,
                    'postnr': _dk_postnr(pn), 'by': by, 'lat': None, 'lon': None})
    out = _ret_kildefejl(out)
    for r in out:
        if r['lat'] is None:
            r['lat'], r['lon'], navn = _dar_adressepunkt(r['street'], r['postnr'])
            r['by'] = navn or r['by']
    if not 7 <= len(out) <= 25:
        raise RuntimeError(f'halifax: {len(out)} restauranter (forventet ~10) - behandles som en '
                           f'koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Gasoline Grill (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
# ---------------------------------------------------------------- Gasoline Grill
# Kraever de faelles hjaelpere fra Carl's Jr.-blokken (afsnittet 'faelles hjaelpere' oeverst
# i ETAPE 3: SPISESTEDER).
GASOLINEGRILL_URL = 'https://www.gasolinegrill.com/locations'
_GG_STED = re.compile(r'^CPH\s+[A-ZÆØÅ]{1,2}$', re.I)          # 'CPH K', 'CPH V'
# Landeled i Maps-linkets destination ('..., 211 34 Malmö, Sweden'). Sverige og Tyskland er de
# vigtige: DK-boksen i _dk_koord daekker Skaane og Sydslesvig. Faeroeerne/Groenland fanges ogsaa
# af koordinaten og postnummeret (_dk_postnr).
_GG_UDLAND = {'sweden', 'sverige', 'germany', 'deutschland', 'tyskland', 'norway', 'norge',
              'united kingdom', 'uk', 'england', 'scotland', 'ireland', 'usa', 'united states',
              'finland', 'suomi', 'iceland', 'island', 'netherlands', 'nederland', 'the netherlands',
              'belgium', 'france', 'spain', 'españa', 'italy', 'italia', 'poland', 'polska',
              'switzerland', 'austria', 'österreich', 'estonia', 'latvia', 'lithuania', 'portugal',
              'faroe islands', 'færøerne', 'føroyar', 'greenland', 'grønland', 'kalaallit nunaat',
              'united arab emirates', 'canada', 'australia', 'japan', 'singapore'}


def _gg_titel(s):
    """'NIELS HEMMINGSENS GADE' -> 'Niels Hemmingsens Gade'; 'CPH' bevares."""
    return ' '.join(w if w.upper() == 'CPH' else w[:1].upper() + w[1:].lower() for w in s.split())


def _gg_naal(url):
    """Stedets naal fra et Google Maps-link: '!3d<lat>!4d<lon>' (sidste par) eller i et
    rutelink '!1d<lon>!2d<lat>'. ALDRIG '@lat,lon' - det er kortudsnittets midte, og den ligger
    op til 1 km fra stedet (Landgreven: '@55.682682,12.5082787,12z')."""
    p = re.findall(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', url)
    if p:
        return _dk_koord(*p[-1])
    p = re.findall(r'!1d(-?\d+\.\d+)!2d(-?\d+\.\d+)', url)
    if p:
        return _dk_koord(p[-1][1], p[-1][0])
    return None, None


def _gg_udland(dest):
    """Er Maps-destinationen i et andet land? Kun naar sidste komma-led ER et kendt land
    ('..., 211 34 Malmö, Sweden' -> ja; '..., 2770 Kastrup, Denmark' -> nej). Et bynavn uden
    postnummer ('..., Hellerup') eller ingen landeled ('Gasoline Grill - Carlsberg Byen',
    'Købmagergade 23, 1150 København') -> nej; saa afgoer naalen (_dk_koord og
    refresh_retail's DK-tjek)."""
    dele = [d.strip() for d in (dest or '').split(',') if d.strip()]
    return len(dele) >= 2 and dele[-1].lower() in _GG_UDLAND


def gasolinegrill():
    """Gasoline Grill (flere driftsselskaber, hovedkontor CVR 41644214) fra kaedens EGEN liste.

    Kilde: www.gasolinegrill.com/locations (Webflow CMS). Ét listeelement pr. restaurant:
    overskrift ('LANDGREVEN 10 – CPH K', 'BROENS GADEKØKKEN – STRANDGADE 95'), aabningstekst,
    et skjult/synligt 'Temporarily closed'-skilt og et Google Maps-link til stedet med dets
    naal. Ét kald. robots.txt: kun en Sitemap-linje, ingen regler (01-10-2026).

    Efterproevet 01-10-2026: 10 restauranter = vores 10; 9 naale ligger 0 m fra vores raekker
    (CSV'en kom herfra) og 2-30 m fra DAR-punktet for adressen. Købmagergade (aabnet april
    2025) har intet koordinat i linket og placeres paa DAR-punktet for Købmagergade 23, 1150 -
    ogsaa vores raekkes punkt. Smiley-registret har alle 10 (Tivoli-enheden under Tivoli A/S,
    lufthavnen under SSP) og derudover kun kaedens foodtruck og hovedkontor (Købmagergade 23)
    og en ekstra SSP-registrering i lufthavnen - ingen restauranter kaeden ikke lister.

    FAELDER:
      * Lufthavnen ('CPH AIRPORT – BETWEEN GATES B AND C') er AIRSIDE - efter security, kun
        for rejsende. Kaeden lister den som en almindelig restaurant, og CSV'en har den
        ('... (Terminal 2, between Gates B and C)'). Smiley har to SSP-enheder for Gasoline
        Grill i Lufthavnsboulevarden 14 ('Airsite Torvet T3' og 'SSP DK AFD. B662'); kaeden
        kun én.
      * Maps-linkene er af tre slags: rutelink med '!1d<lon>!2d<lat>', stedlink med
        '!3d<lat>!4d<lon>' (Carlsberg Byen, intet adressefelt) og et soegelink med daddr= og
        ingen koordinat (Købmagergade). '@lat,lon' er kortudsnittet, ikke stedet.
      * Adressen tages fra linkets destination ('Øster Allé 56, 2100 København' - rigtige
        versaler og postnummer), ellers fra overskriftens led med husnummer ('BRYGGERNES PLADS
        1' -> 'Bryggernes Plads 1', uden postnummer; normaliseringen udfylder det fra
        koordinaten). Lufthavnens destination er 'Lufthavnsboulevarden Terminal 2' - ingen
        DAR-adresse, men naalen er rigtig. Tivolis '1630' er Tivolis eget postnummer; DAR har
        Vesterbrogade 3 i 1620.
      * DK-boksen (_dk_koord) raekker ind i Skaane og Sydslesvig, saa et udenlandsk sted
        frasorteres paa destinationens landeled (_gg_udland).
      * Tivoli-restauranten ligger inde i haven (entré) og foelger Tivolis saesoner; kun
        restaurantsiden har 'Special dates'. Listen siger intet om det, og saesonlukning er
        ikke en lukning.
      * 'Temporarily closed' staar paa ALLE elementer, men er skjult med w-condition-invisible.
        Uden den klasse er restauranten midlertidigt lukket og udelades - saa melder
        refresh_retail den som mulig lukning, og den kommer igen naar skiltet fjernes.
      * Navne i CSV'ens stil 'Gasoline Grill - <sted>': overskriftens ikke-adresse-led
        ('Broens Gadekøkken', 'Tivoli Gardens', 'CPH Airport'), ellers vejnavnet
        ('Landgreven', 'Værnedamsvej'). CSV'en har haandskrevne varianter ('Landgreven (OG)',
        'Tivoli'); refresh_retail parrer dem paa naerhed.
    Forventet: 10."""
    _robots_krav('gasolinegrill', GASOLINEGRILL_URL)
    h = _text(GASOLINEGRILL_URL, 90)
    out = []
    for blok in re.split(r'<div role="listitem" class="locations-list_item w-dyn-item">', h)[1:]:
        o = re.search(r'class="heading-style-h5">(.*?)</div>', blok, re.S)
        if not o:
            continue
        skilt = re.search(r'<div class="tile_warning([^"]*)">', blok)
        if skilt and 'w-condition-invisible' not in skilt.group(1):
            continue                                  # midlertidigt lukket
        t = re.search(r'class="text-size-regular">(.*?)</div>', blok, re.S)
        tekst = _ren(re.sub(r'<[^>]+>', ' ', t.group(1))) if t else ''
        if _ikke_aaben_endnu(tekst) or _ikke_aaben_endnu(_ren(o.group(1))):
            continue                                  # ikke aabnet endnu
        m = re.search(r'href="(https?://(?:www\.)?google\.[a-z.]+/maps[^"]*)"', blok)
        link = _html.unescape(m.group(1)) if m else ''
        lat, lon = _gg_naal(link)
        dest = re.search(r'/maps/dir//([^/@?]+)', link) or re.search(r'[?&]daddr=([^&]+)', link)
        dest = urllib.parse.unquote_plus(dest.group(1)) if dest else ''
        if _gg_udland(dest):
            continue                                  # udenlandsk
        # 'Gasoline Grill, Landgreven 10, 1301 København, Denmark' -> ('Landgreven 10', '1301')
        dpn = re.search(r"(?:^|,)\s*([^,]*\d[^,]*?),\s*(\d{4})\s+([^,]+)", dest)
        led = [d.strip() for d in re.split(r'\s+[–—-]\s+', _ren(o.group(1))) if d.strip()]
        med_nr = [d for d in led if re.search(r'\d', d)]
        uden = [d for d in led if not re.search(r'\d', d) and not _GG_STED.match(d)]
        if dpn:
            gade = dpn.group(1).strip()               # linkets stavning ('Øster Allé 56')
        elif med_nr:                                  # 'ØSTER ALLE 56, ST.', 'KØBMAGERGADE 23, 1150'
            gade = _gg_titel(re.sub(r',?\s*(?:st\.?|\d{4})\s*$', '', med_nr[0], flags=re.I).strip())
        else:
            gade = ''
        sted = _gg_titel(uden[0]) if uden else re.sub(r'\s+\d.*$', '', gade)
        out.append({'brand': 'Gasoline Grill', 'name': f'Gasoline Grill - {sted}', 'street': gade,
                    'postnr': _dk_postnr(dpn.group(2)) if dpn else '',
                    'by': _ren(dpn.group(3)) if dpn else '', 'lat': lat, 'lon': lon})
    out = _ret_kildefejl(_uniq(out))
    for r in out:
        if r['lat'] is None and r['street'] and r['postnr']:
            r['lat'], r['lon'], by = _dar_adressepunkt(r['street'], r['postnr'])
            r['by'] = by or r['by']
    if not 7 <= len(out) <= 25:
        raise RuntimeError(f'gasolinegrill: {len(out)} restauranter (forventet ~10) - behandles som '
                           f'en koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Burger King (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
# ---- Burger King (etape 3 food, 01-10-2026: kaedens eget bestillings-API; genkoert og
# efterproevet af en skeptiker samme dag, som tilfoejede pin-vagten i _bk_dar)
# Kraever _robots_tilladt og _dk_postnr fra Normal-blokken.

BK_API = 'https://bk-dk-ordering-api-fd-hrcjbpbyehdgf8dc.z01.azurefd.net'
# radius i meter og top skal BEGGE med - mangler en af dem, svarer API'et med en tom liste.
BK_LISTE_URL = BK_API + '/api/v2/restaurants?latitude=56.0&longitude=11.0&radius=1000000&top=1000'
BK_ALLE_URL = BK_API + '/api/v2/support/restaurants'
# Pin-vagt (se _bk_dar): saa langt fra DAR-punktet for kaedens EGEN adresse maa pinnen ligge.
BK_PIN_M = 300


def _bk_adresse(s):
    """Burger Kings storeAddress -> (gade, postnr, by). Teksten er indtastet i haanden pr.
    restaurant og har mindst seks formater (01-10-2026):
      'Banegårdspladsen 10\\t8000\\tÅrhus C'         (tabulator-adskilt)
      'Sjællandsvej 4, 7330 Brande'                (komma)
      'Teknologisvinget 5, Aabybro 9440'           (by FOER postnr)
      'Kildeparken 10 8722 Hedensted Danmark'      (intet skilletegn, land til sidst)
      'Industriparken 11, Haverslev, 9610 Nørager' (landsby som ekstra led)
      'Lyngby Kulturcenter, Klampenborgvej 215 J, 2800 Lyngby' (centernavn foran)
      'Søndre Ringvej 41'                          (intet postnr - 11 af 61)
    '215 J' skrives '215J' som i DAR; intervaller ('Snaremosevej 180-182') bevares."""
    t = _ren((s or '').replace('\t', ', '))
    t = re.sub(r'[,\s]*\b(?:Danmark|Denmark)\s*$', '', t, flags=re.I)
    dele = [d.strip() for d in t.split(',') if d.strip()]
    pn = by = ''
    gader = []
    for i, d in enumerate(dele):
        if not pn:
            m = (re.fullmatch(r'(?P<pn>\d{4})(?:\s+(?P<by>\D.*))?', d)
                 or re.fullmatch(r'(?P<by>\D+?)\s+(?P<pn>\d{4})', d)
                 or re.fullmatch(r'(?P<gade>.*?\d+\s*[A-Za-z]?)\s+(?P<pn>\d{4})\s+(?P<by>\D.*)', d))
            if m and _dk_postnr(m.group('pn')):
                g = m.groupdict()
                pn, by = m.group('pn'), (g.get('by') or '').strip()
                if g.get('gade'):
                    gader.append(g['gade'])
                if not by and i + 1 < len(dele) and not re.search(r'\d', dele[i + 1]):
                    by = dele[i + 1]                  # tabulatorformatet: '8000', 'Århus C'
                continue
        if by and d == by:
            continue
        gader.append(d)
    med_nr = [g for g in gader
              if re.search(r'[^\W\d_].*\s\d+\s*[A-Za-z]?(?:\s*-\s*\d+\s*[A-Za-z]?)?$', g)]
    gade = med_nr[0] if med_nr else (gader[0] if gader else '')
    gade = re.sub(r'(\d)\s+([A-Za-zÆØÅæøå])$', lambda m: m.group(1) + m.group(2).upper(), gade)
    return gade, pn, by


def _bk_dar(rows):
    """DAR-efterbehandling (dawa.py mod Datafordeleren). Tre ting pr. restaurant:
      1. POSTNR der mangler i kildeteksten (11 af 61): kaedens EGEN adresse i DAR (vej +
         husnr, det punkt der ligger naermest kaedens koordinat, hoejst 1.000 m vaek);
         ellers det naermeste DAR-punkt til koordinaten (hoejst 300 m).
      2. PIN-VAGT: ligger kaedens koordinat over BK_PIN_M (300 m) fra DAR-punktet for
         kaedens EGEN adresse i samme postnr, er det pinnen der er forkert, og koordinaten
         erstattes af DAR-punktet. Maalt 01-10-2026: de fire kendte pin-fejl (Galten,
         Esbjerg Broen, Hjørring, Taastrup) ligger 465-3.111 m fra adressen; alle oevrige
         pins hoejst 193 m (Tilst, dernaest Nyborg 124 m) - et klart hul, saa vagten roerer
         ingen andre. Uden den arver en NY restaurant med samme slags fejl en forkert
         koordinat, og refresh_retail's normalisering giver den saa ogsaa adressen ved den
         forkerte pin (samme grund som Shell staar i KUN_RAPPORT). For de fire kendte
         goer KILDEFEJL det samme - den daekker ogsaa, naar DAR ikke svarer. Har KILDEFEJL
         sat koordinaten, roeres den ikke af vagten (den er efterproevet i haanden).
         Kaedens tekst er ikke altid en DAR-adresse ('Nyholmvej 3-6', 'Hannemanns alle
         30', 'Nordre Landevej 26'); saa findes intet punkt, og pinnen beholdes.
      3. BY saettes til DAR's postnummernavn ('Kbh V' -> 'København V', 'Århus C' ->
         'Aarhus C', 'Lyngby' -> 'Kongens Lyngby').
    Svarer DAR ikke (ingen noegle, udfald), beholdes kaedens tekst og pin, og postnr kan
    staa tomt: eksisterende raekker matches paa navn/koordinat, ikke postnr, og
    refresh_retail afviser selv nye raekker, naar adresseopslaget i DAR fejler."""
    try:
        import dawa
        navne = dawa.postnumre()
    except Exception:
        return rows

    def en(r):
        try:
            vej, nr = dawa.split_street(r['street'])
            # Uden postnr: hele landet (vej + husnr), saa postnr kan findes ved naermeste punkt.
            egne = (dawa._q(vejnavn=vej, husnr=nr, postnr=r['postnr'] or None)
                    if vej and nr else [])
            if not r['postnr']:
                kand = sorted((dawa.hav(r['lat'], r['lon'], h['y'], h['x']), h['postnr'])
                              for h in egne)
                if kand and kand[0][0] <= 1000:
                    r['postnr'] = kand[0][1]
                else:
                    rv = dawa.reverse_full(r['lat'], r['lon'])
                    if rv and dawa.hav(r['lat'], r['lon'], rv[4], rv[5]) <= 300:
                        r['postnr'] = rv[2]
            i_pn = [h for h in egne if r['postnr'] and h['postnr'] == r['postnr']]
            # En koordinat fra KILDEFEJL er haandefterproevet og vinder altid over vagten.
            if i_pn and 'lat' not in (KILDEFEJL.get(_kfnoegle(r)) or {}):
                d, h = min(((dawa.hav(r['lat'], r['lon'], h['y'], h['x']), h) for h in i_pn),
                           key=lambda t: t[0])
                if d > BK_PIN_M:
                    r['lat'], r['lon'] = round(h['y'], 6), round(h['x'], 6)
        except Exception:
            pass                                      # DAR-udfald for én raekke: behold kaedens
        if r['postnr'] in navne:
            r['by'] = navne[r['postnr']]
    _map(en, rows, 6)                                 # ~60 opslag; 6 traade som normalize_rows
    return rows


def burgerking():
    """Burger King fra kaedens EGET bestillings-API - det samme som burgerking.dk's
    restaurantkort kalder (Angular-app; APP_API_URL staar i main.*.js).

    Kilde: GET bk-dk-ordering-api-fd-hrcjbpbyehdgf8dc.z01.azurefd.net/api/v2/restaurants
    ?latitude=&longitude=&radius=&top= - praecis SPA'ens eget kald (fetchRestaurantsList).
    radius er i meter, og radius OG top skal begge med: med kun latitude/longitude svarer den
    200 med en tom liste. Ét kald fra midten af landet med radius 1.000 km giver alle
    restauranter med navn, adressetekst og koordinat. (Den bare URL uden parametre gav
    01-10-2026 ogsaa alle 61 med samme felter - REFRESH.md's 'død (404)' fra 08-09-2026 gaelder
    ikke laengere - men SPA'en bruger den ikke, saa den kan aendres uden varsel.)
    Vagt: /api/v2/support/restaurants (feedback-formularens liste: id, slug, navn) skal
    daekkes af kortlisten - de var id for id ens 01-10-2026 (61 = 61).
    robots.txt (01-10-2026): API-vaerten svarer 404 (= ingen regler, RFC 9309 2.3.1.3);
    burgerking.dk serverer SPA'ens index.html som robots.txt (ingen regler). Ingen noegle,
    ingen WAF-udfordring. _robots_tilladt tjekkes ved hver koersel.

    Efterproevet 01-10-2026 mod fastfood_kaeder_dk.csv (Burger King: 61 raekker):
    61 i kilden = vores 61, alle 61 navne er tegn for tegn vores. 57 par ligger 0 m fra
    hinanden; de sidste fire er kaedens egne pin-fejl (rettet i KILDEFEJL nedenfor og af
    pin-vagten i _bk_dar), saa henteren giver 61/61 paa 0 m, og postnr/by er vores for alle 61.
    Uafhaengigt: Foedevarestyrelsens smiley-register (pub.fvst.dk/publikationer/Smileydata.xml,
    opdateret 01-10-2026) har praecis 61 'Burger King'-registreringer, én pr. restaurant
    (Poppelstykket = 'Burger King Valby', Ellebjergvej 142); ingen BK-registrering mangler i
    listen. CVR: 'Burger King <by>'-P-enheder hos 34879699, Cresco Food 19033546, Mano Foods-
    selskaberne og HMSHost i lufthavnen. Svenstrup drives af Selch Svenstrup Drift ApS (CVR
    40812040; P 1025070077 staar paa kontoret, Prins Paris Alle 14, men smiley-registreringen
    hedder 'Burger King Svenstrup'). Mano Foods 18's Ankervej 8 i Nykøbing F er et vaerksted
    (BBR 223), ikke en manglende restaurant.

    FAELDER:
      * Fire pins ligger 465-3.111 m fra restaurantens EGEN adresse (Esbjerg Broen,
        Galten, Hjørring, Taastrup). Vores raekker staar 0 m fra DAR-punktet for kaedens
        egen adresse. Uden KILDEFEJL og pin-vagten bliver de til KOORD-AFVIGELSE hver uge
        (navnene er entydige), og en ren afstandsmatchning melder dem som 4 nye + 4 lukkede.
      * Tilst og Holstebro: kaedens pin - og dermed VORES raekke - staar formentlig ved en
        anden bygning end restauranten, men under vagtens 300 m (begge er drive-thru). Tilst:
        193 m nord for DAR-punktet for kaedens egen 'Blomstervej 2R', hvor BBR har en
        restaurantbygning (anvendelse 333, opfoert 2022) og OSM restauranten; BK's
        pressemeddelelse 01-11-2022 aabnede den paa 'Blomstervej 2R' i november 2022. Ved
        pinnen staar et butiks-/fitnesshus (2B). Holstebro: pinnen staar paa et
        butikshus fra 1973 (Nyholmvej 3A); CVR-P-enheden 'Burger King Holstebro' (siden
        01-08-2007) og en restaurantbygning (333, opfoert 2007) og OSM staar paa Nyholmvej 8,
        170 m vaek. Rettes vores raekke, skal KILDEFEJL rette pinnen med den NYE CSV-koordinat
        i samme aendring - ellers KOORD-AFVIGELSE hver uge.
      * isOpen er 'aaben NU' (SPA'en viser den ved dagens aabningstider), IKKE 'drives'.
        Den maa ikke bruges som filter - en natkoersel ville give 0 restauranter.
        showDetailsAsComingSoonPage = restauranten er annonceret men ikke aabnet (SPA'en
        viser en 'kommer snart'-side); de udelades. 0 af 61 01-10-2026.
      * Adresseteksten har mindst seks formater, og 11 af 61 mangler postnr (se
        _bk_adresse og _bk_dar). Lufthavnen hedder 'Københavns Lufthavn, Terminal 3,
        Landside 1. sal' - landside, dvs. offentligt tilgaengelig (rettet i KILDEFEJL).
      * Navnene har efterstillede mellemrum ('Roskilde  ', 'Copenhagen Fields ').
      * Slugs er ikke stabile noegler ('Copenhagen-Norreport', 'århus', 'roskilde  ').
    Navn: kaedens storeName som i vores raekker ('Copenhagen Nørreport', 'Kolding DT
    (Vejlevej)', 'Kastrup (Lufthavnen)').
    Forventet: 61 (01-10-2026)."""
    for u in (BK_LISTE_URL, BK_ALLE_URL):
        if not _robots_tilladt(u):
            raise RuntimeError(f'burgerking: robots.txt forbyder nu {u} - henter ikke')
    d = _json(BK_LISTE_URL, 60)
    if not isinstance(d, dict) or d.get('hasErrors') or not isinstance(d.get('data'), list):
        raise RuntimeError(f'burgerking: uventet svar fra restaurant-API: {str(d)[:200]}')
    poster = d['data']
    if len(poster) >= 1000:
        raise RuntimeError('burgerking: svaret ramte top=1000 - listen kan vaere afkortet')
    alle = (_json(BK_ALLE_URL, 60) or {}).get('data') or []
    mangler = {x.get('id') for x in alle} - {x.get('id') for x in poster}
    if not alle or len(mangler) > max(2, len(alle) // 10):
        raise RuntimeError(f'burgerking: kortlisten mangler {len(mangler)} af feedback-listens '
                           f'{len(alle)} restauranter - API\'et er lagt om')
    out = []
    for x in poster:
        if x.get('showDetailsAsComingSoonPage'):
            continue                                  # annonceret, ikke aabnet
        k = (x.get('storeLocation') or {}).get('coordinates') or {}
        lat, lon = _dk_koord(k.get('latitude'), k.get('longitude'))
        if lat is None:
            continue
        gade, pn, by = _bk_adresse(x.get('storeAddress'))
        out.append({'brand': 'Burger King', 'name': _ren(x.get('storeName')),
                    'street': gade, 'postnr': pn, 'by': by, 'lat': lat, 'lon': lon})
    out = _bk_dar(_ret_kildefejl(_uniq(out)))
    if not 45 <= len(out) <= 85:
        raise RuntimeError(f'burgerking: {len(out)} restauranter (forventet 45-85) - '
                           f'behandles som en koerselsfejl, ikke som lukninger/aabninger')
    return out


# Kendte fejl i Burger Kings egne data (01-10-2026). Noeglen er gadeteksten EFTER
# _bk_adresse. Koordinaterne er LAEST UD AF fastfood_kaeder_dk.csv (vores raekke for samme
# restaurant), og hver er 0 m fra DAR-punktet for kaedens EGEN adresse (dawa._q).
KILDEFEJL.update({
    # Esbjerg Broen (Broen Shopping, Exnersgade 18): kaedens pin staar 2.196 m mod nordvest
    # (DAR-reverse: Mågeparken 20).
    ('Burger King', 'exnersgade 18'): {'lat': 55.465456, 'lon': 8.458878},
    # Galten: kaedens pin staar 3.111 m mod nord (reverse: Wedelslundvej 10, 199 m).
    ('Burger King', 'erhvervsparken klank 2'): {'lat': 56.14675, 'lon': 9.91837},
    # Hjørring: kaedens pin staar 1.154 m mod vest (reverse: Vendiavej 4E).
    ('Burger King', 'frederikshavnsvej 86'): {'lat': 57.455267, 'lon': 10.014844},
    # Taastrup: kaedens pin staar 465 m mod syd ved Helgeshøj Alle 33 (reverse 52 m) -
    # samme fejl som validate.py v5 fandt i vores egen raekke i september.
    ('Burger King', 'helgeshøj alle 32b'): {'lat': 55.66125, 'lon': 12.283589},
    # --- Adressetekster der ikke er en DAR-adresse ved kaedens egen pin (pinnen er rigtig).
    # Kastrup (Lufthavnen): kaeden skriver 'Københavns Lufthavn, Terminal 3, Landside 1. sal'
    # (_bk_adresse giver 'Terminal 3'). DAR-punktet ved pinnen er Kastrup Tværvej E 2 (27 m) -
    # vores raekkes adresse. 'Landside' = foer sikkerhedskontrollen, dvs. aaben for alle.
    ('Burger King', 'terminal 3'): {'street': 'Kastrup Tværvej E 2', 'postnr': '2770'},
    # Rødovre: 'Jyllingevej 336C' findes ikke i DAR (heller ikke som 336; Jyllingevej i 2610
    # slutter ved nr. 322). Pinnen staar 10 m fra DAR's Islevdalvej 40, og CVR-P-enheden
    # 1023537814 (Mano Foods 9 ApS, BK-franchisetager, branche 561110; smiley 'Burger King
    # Jyllingevej') har samme tekst som kaeden, men er knyttet til DAR-adressen Islevdalvej 40.
    # (Vores raekke skrev 'Jyllingevej 322', 242 m fra sin egen koordinat; rettet 01-10-2026.)
    ('Burger King', 'jyllingevej 336c'): {'street': 'Islevdalvej 40', 'postnr': '2610'},
    # Vanløse: 'Jernbane Allé 44' findes ikke i 2720 (naermeste er nr. 42, 18 m; DAR har en
    # 'Jernbane Alle 44' i Taastrup). Pinnen staar 16 m fra Frode Jakobsens Plads 2, hvor CVR
    # har P-enheden 'Burger King Vanløse' (1023054422) - vores raekkes og smileys adresse.
    ('Burger King', 'jernbane allé 44'): {'street': 'Frode Jakobsens Plads 2', 'postnr': '2720'},
    # Tilst: kaedens pin (og tidligere vores) staar 193 m fra restauranten, paa en
    # butiks-/fitnessbygning (Blomstervej 2B). Ved DAR-punktet for kaedens egen adresse,
    # Blomstervej 2R, har BBR en restaurantbygning (333, opfoert 2022) 5 m vaek, og OSM's
    # BK-omrids staar 2 m vaek; BK's pressemeddelelse 01-11-2022 aabnede den paa 'Blomstervej
    # 2R'. Pin-vagten (BK_PIN_M = 300 m) griber ikke ved 193 m (01-10-2026).
    ('Burger King', 'blomstervej 2r'): {'lat': 56.181224, 'lon': 10.124981},
    # Holstebro: 'Nyholmvej 3-6' er ikke en DAR-adresse, og pinnen staar paa en butiksbygning
    # fra 1973 (Nyholmvej 3A). CVR P 1013500246 'Burger King Holstebro' (siden 01-08-2007)
    # er knyttet til DAR Nyholmvej 8, hvor BBR har en restaurantbygning (333, opfoert 2007,
    # 364 m2) 1 m fra OSM's BK-omrids; kaeden kalder den drive-thru (01-10-2026).
    ('Burger King', 'nyholmvej 3-6'): {'street': 'Nyholmvej 8', 'lat': 56.376383, 'lon': 8.619051},
})


# ---- Espresso House (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
# ---- Espresso House (etape 3 food, 01-10-2026: kaedens eget kaffebar-API, myespressohouse.com)
# Bygget af en efterforsker, genkoert og rettet af en skeptiker 01-10-2026 (se docstring).
# Kraever _robots_tilladt, _normal_gade_nr og _dk_postnr fra Normal-blokken. KILDEFEJL.update
# skal staa EFTER KILDEFEJL er defineret. refresh_retail.py: EJER['espressohouse'] =
# ['Espresso House'] og 'espressohouse' i KAEDER, naar fastfood_kaeder_dk.csv er med i FILER.
#
# Fire kaffebarer hvor kaedens pin ligger 151-163 m fra vores raekke for SAMME bar. Uden disse
# ville den foerste ugentlige koersel tilfoeje fire dubletter (kun-tilfoej) og melde vores fire
# raekker som mulige lukninger. KOORDINATERNE ER LAEST FRA fastfood_kaeder_dk.csv 01-10-2026.
# (Vores Espresso House-raekker er OSM-objekter; koordinaterne er OSM-kortlaeggernes.)
KILDEFEJL.update({
    # Rødovre Centrum: kaedens EGEN adresse er 'Rødovre Centrum 202' (= CVR-P-enhed 1022791946 og
    # smiley 715018); vores raekke staar 30 m fra DAR-punktet for 202, kaedens pin 163 m vaek.
    ('Espresso House', 'rødovre centrum 202'): {'lat': 55.67977, 'lon': 12.456719},
    # CPH Airport - Terminal EF: CVR-P-enheden 'Espresso House Airport Finger E' (1030322963) og
    # smiley 'Espresso House Gate E og F' (1430564) staar paa Terminalvej Airside 8, hvor vores
    # raekke staar (4 m fra DAR-punktet); kaedens tekst er 'Flyvervej 65' (et faelles lufthavns-
    # punkt), pinnen 156 m derfra. Samme bar: kaeden har ingen anden ved finger E.
    ('Espresso House', 'flyvervej 65'): {'street': 'Terminalvej Airside 8', 'lat': 55.62782, 'lon': 12.652519},
    # Plantorama Egå: smiley 'Espresso house - Plantorama Egå' (795363) og Plantoramas egne data
    # siger Grenåvej 517B; vores raekke staar 1 m fra vores Plantorama-raekke. Kaedens pin staar
    # 156 m mod nord paa DAR-punktet for 517E.
    ('Espresso House', 'grenåvej 517'): {'street': 'Grenåvej 517B', 'lat': 56.233174, 'lon': 10.294612},
    # Field's, Plan 1: smiley har baade 'Fields Plan 0' og 'Fields Plan 1'. Plan 0 matcher 23 m fra
    # 'Espresso House Fields'; Plan 1 ligger 151 m fra 'Espresso House Fields 1.' (OSM-kortlagt i
    # centret 40 m fra Plan 0). Kaedens pin for Plan 1 er blot centrets adressepunkt.
    ('Espresso House', "arne jacobsen's allé"): {'lat': 55.630121, 'lon': 12.577651},
    # Lalandia (Billund): DAR staver vejen 'Ellehammers Alle'. Med kaedens 'Allé' finder
    # adressevasken ikke kildens adresse og skriver det naermeste DAR-punkt, 'Firhøjevej 25'
    # (41 m) - afproevet med dawa.normalize_one_ex 01-10-2026. 'Ellehammers Alle 3' er Lalandia
    # Billund A/S' adresse i CVR (P 1010767160) og smiley ('Lalandia espresso house' og 'Baresso -
    # Plaza Take-away'). Kun gaden rettes; kaedens pin bevares.
    ('Espresso House', 'ellehammers allé 3'): {'street': 'Ellehammers Alle 3'},
})

ESPRESSOHOUSE_API = 'https://myespressohouse.com/beproud/api/CoffeeShop/v2'
# Selvbetjente kaffeautomater (Barista Station) og deres noter - ikke kaffebarer.
_EH_AUTOMAT = re.compile(r'barista\s*station|maskinen\s+finder\s+du', re.I)
# Kaedens egen lukkemarkering i irregularOpeningHours (Tivoli 23-12-2026: 'Sidste Åbningsdag').
_EH_SIDSTE = re.compile(r'sidste\s+(?:å|aa)bningsdag|lukker\s+permanent|lukket\s+permanent', re.I)
_EH_VEJ = re.compile(r'(?:vej|gade|all[eé]|plads|torv|boulevard|stræde|vænge|brygge|kaj)$', re.I)
# Barer kaeden STADIG lister, men som er lukket. Noegle: coffeeShopId. Hver post skal have belaeg.
_EH_LUKKET = {
    # Østerbrogade 72: CVR-P-enheden 1009077819 'Espresso House - Østerbrogade' OPHOERTE
    # 30-04-2025; ingen smiley-registrering under Espresso House paa adressen, men 'Wedogreens
    # Trianglen' (CVR 30506448, P 1032005957, startet 06-01-2026, smiley-kontrol 15-04-2026).
    # Kaeden har slaaet app-bestilling fra (preorderOnline=false, som ingen anden kaededrevet
    # bar) men glemt posten og find-us-siden (id 7146, fra 2016-serien).
    7146: 'Østerbrogade 72 - lukket 30-04-2025 (CVR), Wedogreens paa adressen',
}
# Sidste aabningsdag kaeden har meldt, hvis posten skulle forsvinde fra irregularOpeningHours.
# API'et viser KUN fremtidige datoer (laveste dato i hele svaret 01-10-2026 = i dag), saa en
# 'Sidste Åbningsdag' er vaek dagen efter - en regel om 'dato < i dag' kan aldrig slaa til.
_EH_SIDSTE_DAG = {
    7155: '2026-12-23',     # Tivoli, Vesterbrogade 3: irregularReason 'Sidste Åbningsdag' (laest 01-10-2026)
}
EH_VARSEL_DAGE = 7          # ugekoerslen (mandage) ser varslet hoejst 6 dage foer sidste dag


def _eh_gade(a1, a2):
    """Kaedens address1/address2 -> 'Vej nr'.

    address1 er gadefeltet, men kan have centernavn, etage, butiksnummer eller hele
    adressen ('Fields Shoppingcenter, Plan 0, Arne jacobsens Allé 12', 'Merkurvej 1D st.
    121', 'Helgeshøj Alle 32, 2630 Taastrup, Danmark', 'Skovvangen 41 6000 Kolding').
    address2 er oftest tom eller en NOTE ('Vores app kan ikke benyttes ...'); kun naar
    address1 er et rent centernavn uden tal, er address2 gaden ('Waves Shoppingcenter' |
    'Over Bølgen 10 F')."""
    a1 = _ren(a1).replace('’', "'")
    a2 = _ren(a2).replace('’', "'")
    if not re.search(r'\d', a1) and re.search(r'[^\W\d_].*\s\d', a2) and len(a2) <= 60:
        a1 = a2
    a1 = re.sub(r',?\s*(?<!\d)\d{4}\s+[^\d,]+(?:,\s*Danmark)?\s*$', '', a1)
    a1 = re.sub(r'\s+(?:opgang|indgang)\s+\S+\s*$', '', a1, flags=re.I)
    a1 = re.sub(r'\s+(?:st|stuen|kl)\.?\s*\d*\s*$', '', a1, flags=re.I)
    # 'Glostrup Shoppingcenter, Butik 19': centrets DAR-adresse ER butiksnummeret (CVR: nr. 19)
    a1 = re.sub(r'^([^\d,]+),\s*butik\s+(\d+[A-Za-z]?)$', r'\1 \2', a1, flags=re.I)
    g = _normal_gade_nr(a1)
    if not re.search(r'\d', g):
        # 'Fields Shoppingcenter, Plan 1, Arne Jacobsen's Allé' -> vejen, ikke centernavnet
        vej = [d.strip() for d in a1.split(',') if _EH_VEJ.search(d.strip())]
        g = vej[-1] if vej else g
    return g[:1].upper() + g[1:]


def espressohouse():
    """Espresso House (Espresso House Denmark A/S, CVR 10011663) fra kaedens EGET API:
        GET https://myespressohouse.com/beproud/api/CoffeeShop/v2
    Det er netop det kald espressohouse.com's 'Find us'-sider laver (useSWR i
    pages/find-us/[location]-*.js og [...slug]-*.js). Headeren Accept-Language skifter kun
    ugedagenes sprog - samme 483 poster paa da/en/sv. Ét kald, hele Norden + Tyskland.
    robots.txt (01-10-2026): myespressohouse.com svarer 404 = ingen begraensninger (RFC 9309
    2.3.1.3); espressohouse.com har 'User-agent: * / Allow: /'. Ingen naevner ClaudeBot.
    Tjekkes ved hver koersel med _robots_tilladt. (espressohouse.dk er et parkeret domaene.)

    Efterproevet 01-10-2026: 483 poster, 89 med country 'Denmark' = 63 kaffebarer + 26
    'Barista Station'. Hjemmesidens finder skjuler navne der staar mere end én gang (i praksis
    de 26 automater); sitemappet har 457 find-us-sider = 483 - 26. De 63: 54 kaedeejede (id
    71xx; 4 i Kastrup Lufthavn), 7 i Plantorama-varehuse og 2 i Lalandia (id 73xx). Heraf er
    ÉN lukket (Østerbrogade, se _EH_LUKKET) -> 62 raekker.
    KRYDSTJEK (skeptiker 01-10-2026): hver af de 62 har en smiley-registrering eller aktiv
    CVR-P-enhed paa adressen eller inden for 300 m (Rigshospitalet staar paa hospitalets
    Blegdamsvej 3A, 370 m; Lalandia Billund paa Ellehammers Alle 3, 86 m), undtagen Plantorama
    Aalborg, som Plantoramas egen side bekraefter ('Espresso House, som ligger midt i
    Plantorama Aalborg'; sidens skabelon lister de samme 7 Plantorama-barer). Kaeden HAR fjernet
    sine andre lukninger 2025-26 (CVR: Amagerbrogade 51, Bernstorffsgade 4, Søborg, Banegårds-
    pladsen 16, Viborg, Farum, Bernstorffsgade 16) og har den nyeste (The Mayor, P-enhed
    11-03-2026). Mod vores 63 raekker (naermeste par, 150 m) med KILDEFEJL: 58 matcher.
    NYE (tilfoejes af ugekoerslen): CPH Airport - Terminal 3 Torvet (airside; CVR P 1029940769,
    smiley 1405426), Plantorama Aalborg, Lalandia Billund (kaedens pin; Lalandia lister TO
    Espresso House i Billund - 'på Lalandia Plaza' og 'ved Adventure Tower' ved indgangen - og
    vores 'Espresso House Lalandia Billund' 246 m vaek er den anden; to OSM-objekter, to
    smiley-registreringer) og Lalandia Rødby (lalandia.dk, smiley 86674).
    KUN HOS OS (meldes som mulige lukninger): 'Espresso House Administration' (Vimmelskaftet 43
    = hovedkontoret; smiley 'Kontorvirksomhed') - slet; 'Espresso House Tivoli' (Bernstorffsgade
    1A) og 'Espresso House Vesterbrogade' (3B) er to raekker for kaedens ENE Tivoli-bar (én
    smiley/CVR-enhed, Vesterbrogade 3) - refresh_retail navnematcher 'Tivoli' og melder 3B;
    'Espresso House Københavns Lufthavn' staar paa lufthavnens faelles adressepunkter (30 m fra
    Lufthavnsboulevarden 6, 40 m fra Terminalvej Airside 30) - smiley og CVR har praecis fire
    Espresso House i lufthavnen, ligesom kaeden; slet den, naar T3 Torvet er tilfoejet;
    'Espresso House Lalandia Billund' og 'Lalandia Søndervig Espresso House' (smiley 1225327,
    lalandia.dk 'På Torvet') findes - behold dem; de meldes hver uge.

    FAELDER:
      * Listen er IKKE altid aktuel: Østerbrogade 72 lukkede 30-04-2025 (CVR) og staar der
        stadig, med aabningstider og egen find-us-side. Den udelades eksplicit via _EH_LUKKET.
        preorderOnline=false er IKKE et lukketegn: 02-10-2026 havde to aabne barer (Kolding
        Storcenter, Østerport) det slaaet fra med normale aabningstider, og en regel paa feltet
        meldte dem som mulige lukninger og ville have holdt en ny bar ude.
      * 'Barista Station' (id 7503xx) er selvbetjente kaffeautomater paa OK Plus-tanke,
        hospitaler og kontorer - ikke kaffebarer. Udelades paa navnet, noten 'Maskinen finder
        du ...' og dubletnavnet (talt blandt de DANSKE poster, ikke hele Norden).
      * Lukninger: 'Sidste Åbningsdag' i irregularOpeningHours (Tivoli 23-12-2026). API'et
        viser kun FREMTIDIGE datoer, saa varslet forsvinder dagen efter. Baren udelades fra
        EH_VARSEL_DAGE foer sidste dag (ugekoerslen ser det) og bagefter via _EH_SIDSTE_DAG.
        Alle syv ugedage 00:00-00:00 er kaedens egen 'Closed' (textClosed) - udelades.
      * country er en TEKST ('Denmark', 'Sweden', ...). Kraev desuden dansk postnr (4 cifre,
        ikke 39xx) og en koordinat i DK-boksen.
      * postalCode er '1050 København K', '2970  Hørsholm', kun '2770' (+ city) eller None -
        saa staar postnr og by i address1. Bynavnet er kaedens ('8000 Aarhus', '8000 Århus');
        DAR-normaliseringen af nye raekker retter det.
      * address1 kan vaere centerets butiksnummer eller en hospitalsopgang ('Lyngby Storcenter,
        Stuen 41', 'Juliane Maries Vej Opgang 4'). Match paa koordinat, ikke paa gadetekst.
      * Navnene er kaedens stednavne ('Rundetårn', 'Spinderiet', 'Scandic, The Mayor');
        navnet bliver 'Espresso House <stednavn>' uden komma, som vores raekker.
      * Lufthavnens fire (Terminal 2, Landside, Terminal 3 Torvet, Terminal EF) staar som
        almindelige kaffebarer; T3 Torvet og EF ligger efter sikkerhedskontrollen (airside).
      * CVR er IKKE en kontrolliste: P-enhederne hedder stadig 'baresso coffee' (seks), to er
        produktionskoekkener ('foodprep'), én er hovedkontoret, Næstved (Sct Mortens Gade 5D)
        er aktiv i CVR uden bar, og Plantorama/Lalandia-barerne har andre ejere.
    Forventet: 62."""
    import collections as _co, datetime as _dt
    if not _robots_tilladt(ESPRESSOHOUSE_API):
        raise RuntimeError('Espresso House: robots.txt paa myespressohouse.com forbyder nu API-stien')
    d = _json(ESPRESSOHOUSE_API, 60, headers={'Accept-Language': 'da'})
    alle = d.get('coffeeShops') if isinstance(d, dict) else None
    if not isinstance(alle, list) or not alle:
        raise RuntimeError(f'Espresso House: uventet svar fra API: {str(d)[:200]}')
    dk = [x for x in alle if _ren(x.get('country')).lower() in ('denmark', 'danmark')]
    idag = _dt.date.today()
    varsel = (idag + _dt.timedelta(days=EH_VARSEL_DAGE)).isoformat()
    antal = _co.Counter(_ren(x.get('coffeeShopName')).lower() for x in dk)
    out = []
    for x in dk:
        raa = _ren(x.get('coffeeShopName'))
        tekst = ' '.join(_ren(x.get(k)) for k in ('coffeeShopName', 'address1', 'address2'))
        if not raa or _EH_AUTOMAT.search(tekst) or antal[raa.lower()] > 1:
            continue
        if x.get('coffeeShopId') in _EH_LUKKET:
            continue
        oh = x.get('openingHours') or []
        if len(oh) >= 7 and all(str(o.get('openFrom'))[:5] == str(o.get('openTo'))[:5] == '00:00'
                                for o in oh):
            continue                          # 'Closed' alle ugens dage
        sidste = [str(i.get('irregularDay') or '')[:10] for i in (x.get('irregularOpeningHours') or [])
                  if _EH_SIDSTE.search(_ren(i.get('irregularReason')))]
        if x.get('coffeeShopId') in _EH_SIDSTE_DAG:
            sidste.append(_EH_SIDSTE_DAG[x['coffeeShopId']])
        if any(s and s < varsel for s in sidste):
            continue                          # kaedens egen sidste aabningsdag er naer eller passeret
        m = re.match(r'(\d{4})\b\s*(.*)$', _ren(x.get('postalCode'))) or \
            re.search(r'(?<!\d)(\d{4})\s+([^\d,]+)', _ren(x.get('address1')))
        pn = _dk_postnr(m.group(1)) if m else ''
        lat, lon = _dk_koord(x.get('latitude'), x.get('longitude'))
        if not pn or lat is None:
            continue
        by = re.sub(r',?\s*Danmark$', '', m.group(2).strip(' ,')).strip() or _ren(x.get('city'))
        navn = re.sub(r'\s*,\s*', ' ', raa.replace('’', "'"))
        out.append({'brand': 'Espresso House', 'name': f'Espresso House {navn}',
                    'street': _eh_gade(x.get('address1'), x.get('address2')),
                    'postnr': pn, 'by': by, 'lat': lat, 'lon': lon})
    out = _ret_kildefejl(_uniq(out))
    if not 45 <= len(out) <= 85:
        raise RuntimeError(f'Espresso House: API gav {len(out)} danske kaffebarer (forventet ~62) '
                           f'- behandles som en koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Sunset Boulevard (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
# ---- Sunset Boulevard (etape 3, 01-10-2026: kaedens bestillingssystem + Lalandias egen side;
#      revideret 01-10-2026: DAR-kontrol af kaedens pins, Skejby-anker, rettet docstring)
SUNSET_URL = ('https://p-bifrostbackend.sprinting.io/api/shops'
              '?tenantId=100&onlyActive=true&timeZone=Europe%2FCopenhagen')
SUNSET_LALANDIA_URL = 'https://www.lalandia.dk/da-dk/r%C3%B8dby/spis'
SUNSET_FORVENTET = (38, 60)       # 01-10-2026: 46 i bestillingssystemet + Lalandia = 47
# Kaedens pin flyttes til DAR-punktet for kaedens EGEN adresse (eksakt vej, husnr og postnr,
# ét hit), naar den ligger mere end dette derfra. Maalt 01-10-2026 paa de 46: 32 af de 33
# adresser DAR kan slaa op, staar i CSV'en paa netop DAR-punktet (0 m; Strøget: kaeden 25D,
# vi 25A); reglen retter de fem kendte pinfejl (177 m-7,2 km) og Viborg Sct. Mathias (170 m),
# flytter syv pins paa 101-144 m ind paa raekken (0 m) og flytter ingen pin vaek fra den.
# Den er sikringen for NYE restauranter: flere af de nyeste pins staar km forkert (Hammelev,
# aabnet 26-02-2026: 7,2 km), og uden kontrollen ville refresh_retail skrive en ny restaurant
# paa pinnens sted med reverse-adressen dér.
SUNSET_DAR_M = 100
# Kaedens pins, der staar forkert. Noeglen er kaedens eget restaurantnummer (shopNumber),
# fordi adresseteksten er fri tekst ('Esbjerg Storcenter Gl. Vardevej 230 Butik 29').
# KOORDINATERNE ER LAEST UD AF fastfood_kaeder_dk.csv (01-10-2026) og er DAR-adgangspunktet
# for kaedens EGEN adresse (0 m), undtagen storcentrene. Efterproevet i DAR og BBR 01-10-2026.
# Posterne her bruges uden DAR-opslag (de fem foerste ville DAR-kontrollen ogsaa rette).
SUNSET_PINFEJL = {
    # Greve: pinnen staar paa Rendebjergvej 19, 4030 Tune, 4,3 km vaek. Mosede Landevej 62 har
    # en BBR-restaurantbygning (anvendelse 333, 395 m2, opfoert 2020) 3 m fra adressepunktet.
    '12507': {'lat': 55.584644, 'lon': 12.258387},
    # Hammelev: pinnen staar ved Billundvej 5 i Vojens, 7,2 km vaek. Egemarken 11 har en
    # BBR-restaurantbygning (333, 388 m2, opfoert 2026) 3 m fra adressepunktet.
    '24552': {'lat': 55.244023, 'lon': 9.397372},
    # Tilst: pinnen staar ved Topkaervej 10, 8200 Aarhus N, 2,95 km vaek. Blomstervej 2P har en
    # BBR-restaurantbygning (333, 394 m2, 2019) 7 m fra adressepunktet.
    '12475': {'lat': 56.181372, 'lon': 10.124466},
    # Roulund: pinnen staar ved Drejebaenken 55, 386 m vest for Drejebaenken 3, der har en
    # BBR-restaurantbygning (333, 392 m2, 2023) 3 m fra adressepunktet. Ingen 333 ved pinnen.
    '14257': {'lat': 55.353858, 'lon': 10.420217},
    # Roedekro: pinnen staar paa Brunde Oest 18 (BBR 322, detailhandel), 177 m fra Kometvej 3A,
    # der har en BBR-restaurantbygning (333, 388 m2, 2018) 3 m fra adressepunktet.
    '11607': {'lat': 55.068323, 'lon': 9.360964},
    # Fire storcentre: pinnen peger paa et andet punkt i SAMME center (reverse: Oerbaekvej 75B,
    # Trekronervej 12, Arne Jacobsens Alle 4D, Gl Vardevej 230D) 158-231 m fra centrets
    # adressepunkt, hvor raekken staar. Ankeret holder ugekoerslens 150 m-match stabilt.
    '9943': {'lat': 55.382488, 'lon': 10.428085},     # Rosengaardcentret, 231 m
    '9973': {'lat': 56.448497, 'lon': 9.40556},       # Viborg Sct. Mathias Centret, 170 m
    '9924': {'lat': 55.630999, 'lon': 12.575893},     # Field's, 169 m
    '9955': {'lat': 55.508717, 'lon': 8.447385},      # Esbjerg Storcenter, 158 m
    # Skejby (Karl Krøyers Vej 15): pinnen staar 146 m fra raekken - 4 m fra graensen, og
    # navnet er ikke ens ('Aarhus - Skejby' / 'Skejby'), saa et lille ryk i pinnen gav en
    # dublet. DAR-kontrollen fanger den ikke: kaeden skriver 'Karl Krøyers vej' (lille v).
    '11495': {'lat': 56.20633, 'lon': 10.174254},
}
# Sunset i Lalandia Roedby drives af Lalandia A/S og staar IKKE (aktiv) i kaedens
# bestillingssystem ('LALANDIA A/S Sunset Rødby', inaktiv, koordinat 0,0); Lalandia skriver
# selv, at Sunset-appen ikke kan bruges dér. Restauranten bekraeftes paa Lalandias egen
# spiseside. Koordinaten er LAEST UD AF CSV'EN.
SUNSET_LALANDIA = {'brand': 'Sunset Boulevard', 'name': 'Rødby - Lalandia',
                   'street': 'Lalandia Centret 1', 'postnr': '4970', 'by': 'Rødby',
                   'lat': 54.666077, 'lon': 11.333418}
_SUNSET_LALANDIA_TEGN = re.compile(r'Sunset Boulevard\s+(?:(?!Sunset Boulevard).){0,300}?'
                                   r'(?:Åbent i dag|Holder lukket i dag|Se alle åbningstider)')
_SUNSET_IKKE_RESTAURANT = re.compile(r'(?i)\btest\b|sandkasse|food ?cost|hovedkontor|onlinepos')
# Fysiske kanaler i postens deliveryMethods (de AKTIVE kanaler; shopOptions.deliveryMethods er
# en skabelon med alle seks). Alle 46 restauranter har EAT_IN og TAKE_OUT 01-10-2026; en post
# med KUN levering er et ghost kitchen og hoerer ikke paa kortet.
_SUNSET_FYSISK = {'EAT_IN', 'TAKE_OUT', 'DRIVE_THROUGH', 'DRIVE_IN', 'PARKING_LOT'}


def _sunset_gade(s):
    """Kaedens adressetekst -> 'Vej nr'.

    'Kometvej 3A, Brunde' -> 'Kometvej 3A', 'Merkurvej 1A, st. 3' -> 'Merkurvej 1A',
    'Passagerterminalen 10 (efter check-in)' -> 'Passagerterminalen 10', 'Frederiksberggade
    25 D' -> 'Frederiksberggade 25D', 'Strevelinsvej 2B Erritsø' -> 'Strevelinsvej 2B',
    'Gl. Aarhusvej 3 Sdr. Borup' -> 'Gl. Aarhusvej 3', 'Chr. d. 8s vej 37 st. tv.' ->
    'Chr. d. 8s vej 37', '... Gl. Vardevej 230 Butik 29' -> '... Gl. Vardevej 230',
    'DREJEBÆNKEN 3' -> 'Drejebænken 3'. Centernavne foran vejen ('Esbjerg Storcenter Gl.
    Vardevej 230', 'Rosengårdscentret Grøngade 180') bliver staaende; DAR-normaliseringen i
    refresh_retail falder dér tilbage paa koordinaten."""
    s = _ren(re.sub(r'\([^)]*\)', ' ', s or ''))
    s = re.sub(r'\s+[Bb]utik\s+\d+\w*', '', s)
    s = _normal_gade_nr(s)
    s = re.sub(r'\s+(?:st|stuen)\.?(?:\s*(?:th|tv|mf)\.?)?$', '', s, flags=re.I)
    # efterhaengt bydel/landsby: 'Strevelinsvej 2B Erritsø', 'Gl. Aarhusvej 3 Sdr. Borup'
    s = re.sub(r'(\d[A-ZÆØÅ]?)(?:\s+[A-ZÆØÅ][a-zæøå]*\.?)+$', r'\1', s)
    if s.isupper():
        s = s.title()
    return s.strip(' ,')


def _sunset_dar_punkt(gade, pn):
    """DAR-adgangspunktet for kaedens egen adresse, naar DAR har den ENTYDIGT (eksakt vejnavn,
    husnr og postnr) -> (lat, lon) eller None. Rejser dawa.DawaNede ved udfald.
    Bevidst eksakt: 'Klosterparks alle 10' (Ringsted, CVR og smiley: nr. 6) og 'Rødovre Centrum
    141' slaas ikke op - en loesere soegning kunne flytte en rigtig pin til et forkert nummer."""
    import dawa
    vej, husnr = dawa.split_street(gade)
    if not (vej and husnr and pn):
        return None
    hits = dawa._q(vejnavn=vej, husnr=husnr, postnr=pn, per_side=2)
    if len(hits) != 1:
        return None
    return float(hits[0]['y']), float(hits[0]['x'])


def sunset_boulevard():
    """Sunset Boulevard (Danske Koncept Restauranter A/S, CVR 30241509, hovedkontor Nordager 26,
    Kolding; mange restauranter drives af franchiseselskaber med eget CVR, fx Lalandia A/S og
    Billund Lufthavn A/S) fra kaedens EGET bestillingssystem.

    Kilde: shop.sunset-boulevard.dk (kaedens webshop, Sprinting Software's 'Bifrost') kalder
    GET p-bifrostbackend.sprinting.io/api/shops?tenantId=100&onlyActive=true. Ét kald giver
    alle aktive restauranter med restaurantnummer, adresse, koordinat, status og operatoerens
    CVR (shopOptions.vat.cvr) - 47 poster 01-10-2026: 46 restauranter + en testbutik. Tenant
    100 er Danmark; Groenland (101), Faeroeerne (102) og Harrislee (104) er egne tenants.
    ROBOTS: p-bifrostbackend.sprinting.io/robots.txt er en tom fil (200, text/plain) - intet
    forbudt. www.sunset-boulevard.dk svarer derimod 454 med en JavaScript-proof-of-work
    ('Checking your browser', simply.com) paa ALT, ogsaa robots.txt; den omgaas ikke, og
    vaerten bruges ikke. (_robots_tilladt regner 454 som 'ingen robots.txt' = tilladt.)

    Efterproevet 01-10-2026 mod de 47 CSV-raekker, Foedevarestyrelsens smiley-register, CVR,
    DAR, BBR, Lalandias, Kolding Storcenters og Billund Lufthavns egne sider og pressen:
      * Smiley-registeret har praecis 47 Sunset-restauranter, én pr. CSV-raekke (inkl.
        Lalandia under Lalandia A/S, CVR 27084303, og Billund under Billund Lufthavn A/S).
      * Alle 46 aktive restauranter svarer til en raekke. 37 ligger inden for 150 m med
        kaedens egne pins (Skejby 146 m - ankret); de 9 oevrige er SUNSET_PINFEJL (fem pins
        177 m-7,2 km forkert, bekraeftet af BBR-restaurantbygninger paa kaedens egne
        adresser, og fire storcentre). Efter rettelserne er det stoerste par 117 m (Rødovre).
      * 'Rødby - Lalandia' findes kun paa Lalandias side (se SUNSET_LALANDIA): Lalandia
        A/S driver den, aabningstider 02-04/10-2026, lukket hverdage uden for ferier.
      * Kolding Storcenter er aktiv, men webshoppen skriver 'lukket grundet renovering'
        (temporarilyClosedOptions) - den er med; centrets egen side har den aaben med
        normale tider (uge 40). Billund Lufthavn staar som 'Passagerterminalen 10 (efter
        check-in)', altsaa airside (lufthavnens side: ca. 250 pladser, efter sikkerheds-
        kontrollen), og er skjult i webshop og app; kaeden lister den som en almindelig,
        aktiv restaurant, og vi har den.
      * Hammelev (Egemarken 11) aabnede 26-02-2026 som kaedens restaurant nr. 47.
    FAELDER:
      * Koordinaten er [lon, lat] (GeoJSON-raekkefoelge), og et par poster har den som
        tekst ('12.5648168'). _dk_koord retter begge.
      * Kaedens pins kan staa km forkert, ogsaa paa de nyeste restauranter - se SUNSET_DAR_M.
        Pins mere end SUNSET_DAR_M fra DAR-punktet for kaedens egen adresse flyttes dertil;
        svarer DAR ikke, fejler henteren hoejt i stedet for at sende ukontrollerede pins
        videre til den automatiske tilfoejelse.
      * Uden onlyActive (og med onlyActive=true) kommer kun de aktive; onlyActive=false giver
        79 poster: 32 inaktive ekstra - lukkede (Klostertorvet, Hovedbanegaarden, Esbjerg
        Kongensgade, Lyngby Kulturhus (i dag Jagger) og Koebmagergade 43 (i dag Otto Pizza,
        samme koncern som Jagger), og de fire Grab'nGo-forsoeg Toender, Lemvig, Svendborg
        Nyborgvej 2A og Varde Vestre Landevej 82, lukket 2024-25 ifoelge pressen), test- og
        driftsposter og Thorshavn med postnr '100'. De fire Grab'nGo-steder har stadig aktive
        P-enheder i CVR (CVR halter), men ingen smiley-registrering. onlyActive=true skrives
        eksplicit, saa en aendret standard ikke slipper de lukkede ind.
      * En aktiv testbutik ('Test-Sprinting Software', koordinat 0,0, by 'TEST') - den
        frafiltreres paa navn og koordinat. En post med kun 'DELIVERY' i deliveryMethods
        (ghost kitchen) springes over; der er ingen 01-10-2026.
      * Navnet: shopNameAlias er kaedens korte stednavn ('Greve', 'Aarhus, Skejby'). Vores
        stil er '<By>' eller '<By> - <Sted>', saa ', ' bliver ' - ' (32 af 47 er ens med
        vores efter refresh_retails navnenormalisering; 'Aarhus - Skejby' hedder hos os
        'Skejby'). De parres paa afstand. Gaden er fri tekst - se _sunset_gade -, og zip kan
        vaere '5220 ' eller '1561' (Havneholmen; DAR og CVR siger ogsaa 1561, CSV'en 1560).
        Kaedens husnummer er ikke altid det registrerede (Ringsted 'Klosterparks alle 10',
        CVR og smiley nr. 6; Strøget '25 D', CVR og smiley 25A) - vores raekker er rigtige.
    Forventet: 47 (46 + Lalandia)."""
    import dawa
    if not _robots_tilladt(SUNSET_URL):
        raise RuntimeError('sunset_boulevard: robots.txt paa p-bifrostbackend.sprinting.io '
                           'forbyder nu /api/shops - henter ikke')
    data = _json(SUNSET_URL, 90, headers={'Accept': 'application/json'})
    if not isinstance(data, list):
        raise RuntimeError(f'sunset_boulevard: uventet svar: {str(data)[:200]}')
    poster = []
    for x in data:
        a = x.get('shopAddress') or {}
        navn_raa = _ren(x.get('shopName'))
        if not x.get('shopIsActive') or _SUNSET_IKKE_RESTAURANT.search(navn_raa):
            continue
        if (a.get('country') or 'DK').strip().upper() != 'DK':
            continue
        kanaler = {str(m).upper() for m in (x.get('deliveryMethods') or []) if isinstance(m, str)}
        if kanaler and not kanaler & _SUNSET_FYSISK:      # kun levering: ghost kitchen
            continue
        k = x.get('shopCoordinates') or [None, None]
        lat, lon = _dk_koord(k[1], k[0]) if len(k) == 2 else (None, None)
        pn = _dk_postnr(a.get('zip'))
        if lat is None or not pn:
            continue
        sted = _ren(x.get('shopNameAlias')) or re.sub(r'^Sunset Boulevard[,\s]*', '', navn_raa)
        poster.append((str(x.get('shopNumber')).strip(),
                       {'brand': 'Sunset Boulevard', 'name': sted.replace(', ', ' - '),
                        'street': _sunset_gade(a.get('street')), 'postnr': pn,
                        'by': _ren(a.get('city')), 'lat': lat, 'lon': lon}))

    def kontroller(p):
        nr, r = p
        rettet = SUNSET_PINFEJL.get(nr)
        if rettet:
            r['lat'], r['lon'] = rettet['lat'], rettet['lon']
            return r
        try:
            punkt = _sunset_dar_punkt(r['street'], r['postnr'])
        except Exception as e:      # dawa.DawaNede, NoegleMangler, netfejl
            raise RuntimeError(f'sunset_boulevard: DAR svarede ikke ved pin-kontrollen '
                               f'({type(e).__name__}: {dawa._skrub(e)[:120]}) - sender ikke '
                               f'ukontrollerede pins videre') from None
        if punkt and _afst_m(r['lat'], r['lon'], *punkt) > SUNSET_DAR_M:
            r['lat'], r['lon'] = round(punkt[0], 6), round(punkt[1], 6)
        return r
    out = _map(kontroller, poster, workers=8)
    # Lalandia: kun hvis Lalandias egen spiseside stadig har restauranten MED aabningstider.
    # Navnet alene duer ikke: siden skriver ogsaa 'Sunset Boulevard App ... kan ikke benyttes'.
    # Et udfald her koster kun én 'MULIG LUKNING'-linje i rapporten, saa det faelder ikke
    # hele kaeden.
    try:
        if _robots_tilladt(SUNSET_LALANDIA_URL) and _SUNSET_LALANDIA_TEGN.search(
                _ren(re.sub(r'<[^>]+>', ' ', _text(SUNSET_LALANDIA_URL, 60)))):
            out.append(dict(SUNSET_LALANDIA))
    except Exception:
        pass
    out = _uniq(out)
    lo, hi = SUNSET_FORVENTET
    if not lo <= len(out) <= hi:
        raise RuntimeError(f'sunset_boulevard: {len(out)} restauranter (forventet ~47) - '
                           f'behandles som en koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Jagger (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
# ---- Jagger (etape 3, 01-10-2026: kaedens HeapsGo-webshop; revideret 01-10-2026: kun
#      noeglehovedet sendes, robots-tjek foer genlaesning af noeglen, efterproevning i docstring)
JAGGER_URL = ('https://drinks.heapsapp.com/api/v0/venues-list-all/default'
              '?latitude=55.68&longitude=12.57')
JAGGER_WEBSHOP = 'https://jagger.heapsgo.com/'
# Webshoppens OFFENTLIGE klientnoegle: den staar i jagger.heapsgo.com/app-*.js og sendes af
# enhver browser, der aabner webshoppen (samme slags som LIDL_KEY). Ingen tilmelding. Skifter
# den, laeses den igen fra webshoppens bundle (se _jagger_noegle).
JAGGER_NOEGLE = '37e6443f-1fea-4559-b286-ca0f86d688ae'
JAGGER_FORVENTET = (12, 30)       # 01-10-2026: 18


def _jagger_noegle():
    """Laes X-Drinks-Api-Key ud af webshoppens app-bundle -> noeglen el. None."""
    try:
        if not _robots_tilladt(JAGGER_WEBSHOP):
            return None
        h = _text(JAGGER_WEBSHOP, 60)
        for js in re.findall(r'src="(/app-[0-9a-f]+\.js)"', h):
            m = re.search(r'"X-Drinks-Api-Key"\s*:\s*"([0-9a-f-]{20,})"',
                          _text(urllib.parse.urljoin(JAGGER_WEBSHOP, js), 60))
            if m:
                return m.group(1)
    except Exception:
        return None
    return None


def _jagger_adresse(s):
    """'Rødovre Centrum 1M, st. 43, 2610 Rødovre' -> ('Rødovre Centrum 1M', '2610', 'Rødovre').
    Kaeden skriver ogsaa uden komma ('Falkoner Allé 21  2000 Frederiksberg'), med smaat
    husbogstav ('Sluseholmen 12a') og forkortet ('Göteborg Pl. 19', 'H.C Andersens Boulevard')."""
    s = _ren(s)
    m = re.search(r'[,\s]\s*(\d{4})\s+([^,\d]*)$', s)
    if not m:
        return _normal_gade_nr(s), '', ''
    gade = _normal_gade_nr(s[:m.start()].strip(' ,'))
    gade = re.sub(r'(\d)([a-zæøå])$', lambda k: k.group(1) + k.group(2).upper(), gade)
    return gade, m.group(1), m.group(2).strip()


def jagger():
    """Jagger (Jagger Copenhagen ApS / Jagger Junk ApS, CVR 37319627, 'BUZZ CPH' med OTTO og
    RITTA) fra kaedens EGEN webshop.

    Kilde: jagger.heapsgo.com - Jaggers webshop paa HeapsGo-platformen (samme platform som
    kaedens app 'BUZZ CPH', Android-pakke com.heapsgo.jagger.android) - kalder GET
    drinks.heapsapp.com/api/v0/venues-list-all/default?latitude=..&longitude=.. med
    webshoppens offentlige klientnoegle (X-Drinks-Api-Key, se JAGGER_NOEGLE; andre hoveder
    behoeves ikke). Ét kald giver ALLE restauranter (links: kun 'all', ingen sider) med navn,
    adresse, koordinat, landekode og is_open/open_for_orders; latitude/longitude styrer kun
    sorteringen. Jagger Norway (Oslo) er en anden organisation og kommer ikke med.
    ROBOTS: drinks.heapsapp.com/robots.txt er 'User-agent: *' uden regler, og
    jagger.heapsgo.com siger 'Allow: /'. www.jagger.dk og alle *.jagger.dk (wildcard-DNS til
    simply.com) svarer 454 med en JavaScript-proof-of-work - den omgaas ikke.

    Efterproevet 01-10-2026 mod de 18 CSV-raekker, DAR, kaedens karriereside
    (careers.buzzcph.com/en/locations: 18 danske + 2 i Oslo), CVR og Foedevarestyrelsens
    smiley-register (18 Jagger-restauranter under CVR 37319627 + hovedkontor + et eksternt
    koekken i Roedekro, der ikke er en restaurant):
      * 18/18 parret inden for 150 m (stoerst: Indre By 112 m, FRB. Centret 83 m,
        Roedovre 75 m); 17 navne er ordret som vores ('Jagger Rødovre Centrum' hedder hos
        os 'Jagger Rødovre'). Ingen mangler og ingen ekstra. Kaedens pins staar hoejst 42 m
        fra DAR-punktet for dens egen adresse, hvor DAR kan slaa den op (13 af 18).
      * Vores 'Jagger Indre By' staar paa Koebmagergade 43, som er Otto Pizza (CVR P
        1022924695, smiley 'Otto Pizza'). Jagger er Koebmagergade 29: webshoppen, CVR P
        1032714540 og smiley 1593025 'Jagger - KMG 29'; kaedens pin staar 1 m fra
        DAR-punktet for nr. 29. Ogsaa 'Jagger Strandlodsvej' staar paa 15D, som er Pizza
        Ottos enhed (CVR) - Jagger er 15A ifoelge kaeden (pin 1 m fra DAR 15A), 15E ifoelge
        CVR og smiley; 'Jagger Søborg' staar paa nr. 35, 2870 - CVR og smiley siger 35A,
        2860 Søborg; 'Jagger Rødovre' paa 1R (Sunset Boulevards nummer) - Jagger er 1M.
        Ugekoerslen ser det ikke (parret paa navn/afstand); ret dem i CSV'en.
    FAELDER:
      * Uden X-Drinks-Api-Key svarer API'et 400 'Api key or api name missing', med en forkert
        noegle 400 'Invalid api key format'. Noeglen laeses igen fra webshoppens app-*.js,
        hvis den gamle afvises (400/401/403).
      * address er fri tekst og ikke altid en DAR-adresse: 'H.C Andersens Boulevard 12',
        'Göteborg Pl. 19', 'Søborg Hovedgade 35, 2860 Søborg' (DAR: 35 er 2870 Dyssegård,
        35A-D er 2860), 'Rødovre Centrum 1M, st. 43' (karrieresiden: '1 R, 1, 202').
      * dawa._loose fjerner 'é' i stedet for at goere det til 'e', saa 'Falkoner Allé 84'
        ikke genkendes som DAR's 'Falkoner Alle' og normaliseres til nabonummeret 86. Det
        rammer kun NYE raekker (eksisterende matches paa afstand).
      * Platformen baerer ogsaa OTTO og RITTA (samme CVR, ofte paa naboadressen); kun
        titler, der begynder med 'Jagger', tages med. Et rent leveringskoekken (kun
        'courier' i shop_collection_methods) springes over; der er ingen 01-10-2026.
    Forventet: 18."""
    if not _robots_tilladt(JAGGER_URL):
        raise RuntimeError('jagger: robots.txt paa drinks.heapsapp.com forbyder nu /api/ - henter ikke')

    def hent(noegle):
        return _json(JAGGER_URL, 60, headers={'Accept': 'application/json',
                                              'X-Drinks-Api-Key': noegle})
    try:
        d = hent(JAGGER_NOEGLE)
    except urllib.error.HTTPError as e:
        if e.code not in (400, 401, 403):
            raise
        ny = _jagger_noegle()
        if not ny or ny == JAGGER_NOEGLE:
            raise RuntimeError(f'jagger: API\'et afviste klientnoeglen (HTTP {e.code}), og '
                               f'webshoppens bundle har ingen ny')
        d = hent(ny)
    poster = ((d or {}).get('venues') or {}).get('items')
    if not isinstance(poster, list):
        raise RuntimeError(f'jagger: uventet svar: {str(d)[:200]}')
    out = []
    for x in poster:
        navn = _ren(x.get('title'))
        if (x.get('country_alpha_3_code') or '').upper() != 'DNK' or not navn.lower().startswith('jagger'):
            continue
        # Alle 18 har 'pickup' og 'eat-in' 01-10-2026; kun 'courier' = rent leveringskoekken.
        metoder = {str(m).lower() for m in (x.get('shop_collection_methods') or [])}
        if metoder and not metoder & {'pickup', 'eat-in'}:
            continue
        lat, lon = _dk_koord(x.get('latitude'), x.get('longitude'))
        gade, pn, by = _jagger_adresse(x.get('address'))
        if lat is None:
            continue
        out.append({'brand': 'Jagger', 'name': navn, 'street': gade, 'postnr': _dk_postnr(pn),
                    'by': by, 'lat': lat, 'lon': lon})
    out = _uniq(out)
    lo, hi = JAGGER_FORVENTET
    if not lo <= len(out) <= hi:
        raise RuntimeError(f'jagger: {len(out)} restauranter (forventet ~18) - behandles som en '
                           f'koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Domino's Pizza (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
# ================================================================ ETAPE 3b: SPISESTEDER, SMAA KAEDER
# ---- Domino's, MAX, Five Guys, KFC og Cocks & Cows (etape 3b, 01-10-2026: bygget af en
#      efterforsker, genkoert og efterproevet af en skeptiker samme dag; kaedernes egne lister,
#      robots.txt laest i haanden, efterproevet mod fastfood_kaeder_dk.csv, CVR (Datafordeleren),
#      Foedevarestyrelsens smiley-register (pub.fvst.dk/publikationer/Smileydata.xml), OSM og presse).
#      Alle fem returnerer maerket som i CSV'en: "Domino's Pizza", 'Max Burgers', 'Five Guys',
#      'KFC', 'Cocks & Cows'. kfc og cocks_cows er KUN til rapport (refresh_retail.KUN_RAPPORT):
#      KFC's population er en kontaktformular og adresserne CVR's/DAR's, og Cocks & Cows' gitter
#      vedligeholdes ikke (lufthavnens kort stod der 9 maaneder efter lukningen). Kraever
#      _robots_tilladt, _dk_postnr, _aabner_senere, _normal_gade_nr og _oil_geokod ovenfor.

DOMINOS_URL = 'https://www.dominos.dk/butikker'
DOMINOS_FORVENTET = (3, 25)          # 01-10-2026: 6 (kaeden genaabnede i DK i 2025-26)
# 'Kommer snart' / 'Coming soon' uden ordet 'åbner' fanges ikke af _aabner_senere.
_DOMINOS_SENERE = re.compile(r'(?i)\b(?:snart|coming soon)\b')


def dominos():
    """Domino's Pizza fra kaedens EGEN butiksliste (www.dominos.dk/butikker).

    Kilde: siden er server-renderet React. Hele butikslisten ligger i den indlejrede
    app-state som "shops": [...] med ID, Area, Address, Zip, City, Latitude, Longitude,
    IsHidden, Disabled og NotificationText; /butikker viser de samme 6 som synlig tekst, og
    forsiden har samme liste. Ét kald. api.dominos.dk bruges ikke.
    robots.txt: www.dominos.dk/robots.txt svarer 404 (01-10-2026) = ingen regler (RFC 9309
    2.3.1.3); api.dominos.dk ligeledes 404.

    Efterproevet 01-10-2026 mod fastfood_kaeder_dk.csv (6 Domino's-raekker): 6/6 genfundet
    paa 0 m (raekkerne kom fra denne liste), ingen mangler. CVR har praecis 6 aktive
    P-enheder under kaedens tre franchisetagere - IndDk ApS (44962233: Hvidovre, Rødovre
    Port), Trio NVN ApS (45303071: Amagerbrogade, Slagelse) og T&M ApS (45060039: Roskilde,
    Greve) - og alle 6 adresser har en smiley-registrering (Roskilde under 'T&M ApS').
    Kaeden oplyser intet samlet antal.

    FAELDER:
      * Filtrér IKKE paa Status/StoreStatus: de ligner 'aaben lige nu' (1 for alle kl. 14,
        ved siden af StoreClosesIn i sekunder), og saa ville en koersel om natten melde alle
        butikker lukket. Kun IsHidden og Disabled (betydningen er ikke dokumenteret, men en
        skjult/deaktiveret butik skal ikke tilfoejes automatisk; det giver hoejst en 'mulig
        lukning' til gennemsyn) og en NotificationText som 'Åbner den ...' (_aabner_senere)
        eller 'Kommer snart' / 'Coming soon' holder en butik ude.
      * Kun levering (AcceptsPickup false, AcceptsDelivery true) er et leveringskoekken, ikke
        et spisested, og springes over. 01-10-2026 tager alle 6 imod afhentning og levering.
      * Kaeden skriver 'Over bølgen 37'; DAR, CVR og smiley siger 'Over Bølgen 37A' (Greve
        Waves). Koordinaten er rigtig (11 m fra DAR-punktet for 37A), og raekken matches paa
        den. Ligeledes 'Sdr. Stationsvej' (DAR: 'Sdr.Stationsvej').
      * Butiks-ID 1 findes ikke (listen har ID 2-7); det er ikke en fejl.
      * Navnet er "Domino's <Area>" som i CSV'en ("Domino's Greve Waves").
    Forventet: 6."""
    if not _robots_tilladt(DOMINOS_URL):
        raise RuntimeError(f'dominos: robots.txt forbyder nu {DOMINOS_URL} - henter ikke')
    h = _text(DOMINOS_URL, 60)
    m = re.search(r'"shops"\s*:\s*\[', h)
    if not m:
        raise RuntimeError('dominos: "shops" findes ikke paa /butikker - siden er lavet om')
    out = []
    for s in json.loads(_balanced(h, h.index('[', m.start()), '[', ']')):
        note = _ren(s.get('NotificationText'))
        if s.get('IsHidden') or s.get('Disabled') or _aabner_senere(note) or _DOMINOS_SENERE.search(note):
            continue
        if s.get('AcceptsPickup') is False and s.get('AcceptsDelivery'):
            continue                          # kun levering - ikke et spisested
        pn = _dk_postnr(s.get('Zip'))
        lat, lon = _dk_koord(s.get('Latitude'), s.get('Longitude'))
        omraade = _ren(s.get('Area'))
        if not pn or lat is None or not omraade:
            continue
        out.append({'brand': "Domino's Pizza", 'name': f"Domino's {omraade}",
                    'street': _ren(s.get('Address')), 'postnr': pn, 'by': _ren(s.get('City')),
                    'lat': lat, 'lon': lon})
    out = _uniq(out)
    lo, hi = DOMINOS_FORVENTET
    if not lo <= len(out) <= hi:
        raise RuntimeError(f'dominos: {len(out)} butikker (forventet {lo}-{hi}) - behandles som '
                           f'en koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Max Burgers (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
MAX_URL = 'https://www.max.dk/find-max/restauranter/'
MAX_FORVENTET = (4, 20)              # 01-10-2026: 6


def _max_navn(navn, gade):
    """Kaedens restaurantnavn i CSV'ens stil: 'Gammeltorv København | MAX.' -> 'Gammeltorv
    København', 'MAX Hovedbanegården, Banegårdspladsen 6.' -> 'MAX Hovedbanegården',
    'Ringsted ' -> 'Ringsted'. En hale der blot er gadeadressen skaeres af."""
    s = re.sub(r'\s*\|\s*MAX\.?\s*$', '', _ren(navn), flags=re.I).strip(' .')
    g = _ren(gade).strip(' .')
    if g and s.lower().endswith(', ' + g.lower()):
        s = s[:-(len(g) + 2)].strip(' ,')
    return s or g


def max_burgers():
    """MAX Burgers (WE LOVE BURGERS A/S, CVR 34613052) fra kaedens EGEN restaurantliste.

    Kilde: www.max.dk/find-max/restauranter/ (Episerver). Listen er indlejret i HTML'en som
    data-props paa <div data-app="RestaurantList"> (HTML-escapet JSON): countryId 'da' og
    restaurants med name, streetAddress, postalCode ('1457 København'), latitude, longitude,
    link, hasDriveIn og openingHours. Ét kald.
    robots.txt: www.max.dk/robots.txt omdirigerer (301) til /robots.txt/: 'User-agent: * /
    Allow: / / Disallow: /episerver/*' (01-10-2026).

    Efterproevet 01-10-2026 mod fastfood_kaeder_dk.csv (6 MAX-raekker): 6/6 genfundet paa
    0 m, ingen mangler. CVR: WE LOVE BURGERS A/S har praecis 6 restaurant-P-enheder (plus
    selskabets egen P-enhed paa Gammeltorv 4), og alle 6 har en smiley-registrering.
    Kaedens 'MAX har {0} restauranter i {1}' regnes i browseren af samme liste - intet
    uafhaengigt antal.

    FAELDER:
      * Brug IKKE sitemap'et: det har en 7. restaurantside, /copenhagen-5---dybbolsbro/,
        uden adresse og med 'Midlertidigt lukket' - en tom pladsholder ved siden af den
        rigtige Kaktus-side (/copenhagen-cactus/). Listen har kun de 6.
      * postalCode er 'postnr by' i ét felt, og kaedens postnummer er ikke altid DAR's:
        Hovedbanegården staar som 1577, DAR, CVR og smiley siger Banegårdspladsen 6, 1570.
        Koordinaten er rigtig (0 m), og normaliseringen tager postnr fra DAR.
      * Kaeden skriver 'Klosterparks Allé 20' (DAR: 'Klosterparks Alle').
      * Navnene er uensartede hos kaeden; _max_navn giver CSV'ens navn for 4 af 6. Vores
        'BIG Shopping, Herlev' og 'Copenhagen, Kaktus (Dybbølsbro)' er haandrettede og
        matches paa naerhed (0 m).
      * En restaurant uden aabningstider springes over (ligner en pladsholder/ikke aabnet).
    Forventet: 6."""
    if not _robots_tilladt(MAX_URL):
        raise RuntimeError(f'max_burgers: robots.txt forbyder nu {MAX_URL} - henter ikke')
    h = _text(MAX_URL, 60)
    tag = re.search(r'<[^>]*data-app="RestaurantList"[^>]*>', h)
    m = re.search(r'data-props="([^"]*)"', tag.group(0)) if tag else None
    if not m:
        raise RuntimeError('max_burgers: RestaurantList findes ikke paa siden - siden er lavet om')
    d = json.loads(_html.unescape(m.group(1)))
    if (d.get('countryId') or '').lower() != 'da':
        raise RuntimeError(f"max_burgers: countryId er {d.get('countryId')!r}, ikke 'da'")
    out = []
    for r in d.get('restaurants') or []:
        mm = re.match(r'\s*(\d{4})\s*(.*)$', _ren(r.get('postalCode')))
        pn = _dk_postnr(mm.group(1)) if mm else ''
        lat, lon = _dk_koord(r.get('latitude'), r.get('longitude'))
        if not pn or lat is None or not r.get('openingHours') or _aabner_senere(r.get('name') or ''):
            continue
        out.append({'brand': 'Max Burgers', 'name': _max_navn(r.get('name'), r.get('streetAddress')),
                    'street': _ren(r.get('streetAddress')), 'postnr': pn,
                    'by': _ren(mm.group(2)) or _ren(r.get('city')), 'lat': lat, 'lon': lon})
    out = _uniq(out)
    lo, hi = MAX_FORVENTET
    if not lo <= len(out) <= hi:
        raise RuntimeError(f'max_burgers: {len(out)} restauranter (forventet {lo}-{hi}) - '
                           f'behandles som en koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Five Guys (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; godkendt)
FIVEGUYS_ROD = 'https://restaurants.fiveguys.dk/'
FIVEGUYS_FORVENTET = (1, 15)         # 01-10-2026: 2
_FG_DAGE = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
# Et komma-led der kun er et vejtype-ord + husnummer, hoerer til leddet foer det.
_FG_VEJHALE = re.compile(r'(?i)(?:all[eé]|vej|gade|plads|boulevard|torv|stræde|brygge|vænge|'
                         r'park|have|kaj)\s+\d+\s*[A-Za-zÆØÅæøå]?')


def _fg_dokument(url):
    """Yext Pages: sidens data ligger som pageProps: JSON.parse(decodeURIComponent("..."))."""
    if not _robots_tilladt(url):
        raise RuntimeError(f'fiveguys: robots.txt forbyder nu {url} - henter ikke')
    m = re.search(r'pageProps:\s*JSON\.parse\(decodeURIComponent\("(.*?)"\)\)', _text(url, 60), re.S)
    if not m:
        raise RuntimeError(f'fiveguys: pageProps findes ikke paa {url} - siden er lavet om')
    return json.loads(urllib.parse.unquote(m.group(1))).get('document') or {}


def _fg_gade(line1):
    """'1-503, Arne Jacobsens, Allé 12' -> 'Arne Jacobsens Allé 12'; lejemaalet ('1-503')
    fjernes, og kommaet midt i vejnavnet lukkes. 'Kalvebod Brygge 59' er uaendret."""
    dele = [d.strip() for d in _ren(line1).split(',') if d.strip()]
    dele = [d for d in dele if not re.fullmatch(r'[\d\s\-–/.]+', d)]
    led = []
    for d in dele:
        if led and _FG_VEJHALE.fullmatch(d) and not re.search(r'\d', led[-1]):
            led[-1] = f'{led[-1]} {d}'
        else:
            led.append(d)
    med_nr = [d for d in led if re.search(r'[^\W\d_].*\s\d', d)]
    return med_nr[0] if med_nr else (led[0] if led else '')


def fiveguys():
    """Five Guys fra kaedens EGEN restaurantfinder (restaurants.fiveguys.dk, Yext Pages).

    Kilde: forsiden er Yext-mappen 'All Locations' (document.dm_directoryChildren = byerne,
    hver med slug og dm_baseEntityCount); hver byside (/copenhagen) har restauranterne i
    document.dm_directoryChildren med address {line1, line2, city, postalCode, countryCode},
    geomodifier, hours, slug og yextDisplayCoordinate. Data staar URL-kodet i
    'pageProps: JSON.parse(decodeURIComponent("..."))'. 1 + antal byer kald (2 i dag).
    robots.txt: 'User-agent: * / Disallow: /directory' - forsiden og bysiderne er tilladte
    (01-10-2026). www.fiveguys.dk (WordPress) har ingen restaurantliste.

    Efterproevet 01-10-2026: kaeden har 2 restauranter (dm_baseEntityCount 2):
      * Field's: samme restaurant som vores raekke, men kaedens punkt ligger 263 m fra den.
        Vores raekke staar paa DAR-punktet for centrets adresse (Arne Jacobsens Allé 12, midt
        paa vestsiden); restauranten ligger ved hovedindgangen under Nordisk Film Biografer
        med egen indgang udefra (presse ved aabningen 29-06-2026), og kaedens punkt
        reverse-geokoder til Ørestads Boulevard 102C ved hovedindgangen. Vores koordinat skal
        rettes til kaedens; indtil da melder refresh_retail en KOORD-AFVIGELSE (navnematch).
      * Fisketorvet, Kalvebod Brygge 59, Kajen Food Hall plan 1, MANGLER hos os: aabnede
        03-08-2026 (Westfield/presse), smiley 1588245 'Five Guys Fisketorvet' (kontrolleret
        02-09-2026), CVR 45805492 'FG Fisketorvet ApS'.

    FAELDER:
      * line1 er rodet: '1-503, Arne Jacobsens, Allé 12' (lejemaal + komma midt i
        vejnavnet) - se _fg_gade. city er engelsk ('Copenhagen'); normaliseringen tager
        postnr/by fra DAR.
      * CVR hjaelper ikke med adresserne: begge selskaber (FG Fields ApS, FG Fisketorvet ApS)
        og deres P-enheder staar paa kontoradressen Kalvebod Brygge 39.
      * Fisketorvets Yext-punkt ligger 139 m fra DAR-punktet for Kalvebod Brygge 59 (stort
        center); kaedens punkt bruges.
      * En restaurant uden aabningstider er 'coming soon' (_site.c_comingSoonOpenHours er
        'opening') og springes over.
      * Antallet af restauranter paa bysiderne skal stemme med forsidens dm_baseEntityCount,
        ellers AFBRYDES der.
      * Navn: 'Five Guys ' + geomodifier uden bynavnet ("Field's Copenhagen" -> "Five Guys
        Field's", som i CSV'en).
    Forventet: 2."""
    rod = _fg_dokument(FIVEGUYS_ROD)
    byer = [b for b in rod.get('dm_directoryChildren') or [] if b.get('slug')]
    if not byer:
        raise RuntimeError('fiveguys: forsiden har ingen byer (dm_directoryChildren) - siden er lavet om')
    oplyst = sum(int(b.get('dm_baseEntityCount') or 0) for b in byer)
    alle = []
    for b in byer:
        alle += _fg_dokument(urllib.parse.urljoin(FIVEGUYS_ROD, urllib.parse.quote(b['slug'])))\
            .get('dm_directoryChildren') or []
    if len(alle) != oplyst:
        raise RuntimeError(f'fiveguys: bysiderne har {len(alle)} restauranter, forsiden siger '
                           f'{oplyst} - en side er i stykker')
    out = []
    for x in alle:
        a = x.get('address') or {}
        if (a.get('countryCode') or 'DK').upper() != 'DK':
            continue
        if not any(((x.get('hours') or {}).get(d) or {}).get('openIntervals') for d in _FG_DAGE):
            continue                       # coming soon
        c = x.get('yextDisplayCoordinate') or {}
        lat, lon = _dk_koord(c.get('latitude'), c.get('longitude'))
        pn = _dk_postnr(a.get('postalCode'))
        if lat is None or not pn:
            continue
        by = _ren(a.get('city'))
        sted = _ren(x.get('geomodifier'))
        if by and sted.lower().endswith(' ' + by.lower()):
            sted = sted[:-(len(by) + 1)].strip()
        out.append({'brand': 'Five Guys', 'name': f'Five Guys {sted}'.strip(),
                    'street': _fg_gade(a.get('line1')), 'postnr': pn,
                    'by': {'copenhagen': 'København'}.get(by.lower(), by), 'lat': lat, 'lon': lon})
    out = _uniq(out)
    lo, hi = FIVEGUYS_FORVENTET
    if not lo <= len(out) <= hi:
        raise RuntimeError(f'fiveguys: {len(out)} restauranter (forventet {lo}-{hi}) - '
                           f'behandles som en koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Starbucks (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; kun rapport)
# ---- Starbucks (etape 3, 01-10-2026: Starbucks' egen globale butiksfinder; revideret 01-10-2026:
#      et svar, der ikke er en liste, er en fejl - ikke et tomt omraade; KUN_RAPPORT, se docstring)
STARBUCKS_URL = 'https://www.starbucks.com/apiproxy/v1/locations?lat=%s&lng=%s'
STARBUCKS_FORVENTET = (12, 25)    # 01-10-2026: 17
# API'et svarer med butikkerne inden for 25 miles (40,2 km) af punktet. De 30 punkter er
# valgt (graadig maengdedaekning, 01-10-2026), saa ALLE 3.113 forskellige butikskoordinater i
# de fem CSV'er - dvs. hele det beboede Danmark inkl. Bornholm, Laesoe og Anholt - ligger
# hoejst 36 km fra et punkt. Kaldene gaar ét ad gangen med STARBUCKS_PAUSE imellem: fire
# parallelle traade udloeste 01-10-2026 Akamais 'Access Denied' (403) efter ca. 30 kald.
_SB_GITTER = [(54.8, 11.6), (54.9, 9.2), (54.9, 10.25), (55.0, 12.35), (55.0, 14.75),
              (55.1, 9.2), (55.2, 10.7), (55.3, 8.9), (55.3, 11.75), (55.4, 8.0),
              (55.4, 9.35), (55.5, 9.95), (55.7, 8.75), (55.7, 11.3), (55.8, 12.2),
              (55.9, 10.55), (55.9, 12.65), (56.0, 8.6), (56.0, 9.65), (56.3, 8.0),
              (56.3, 9.8), (56.4, 8.75), (56.4, 11.45), (56.5, 10.4), (56.7, 9.8),
              (56.7, 10.1), (56.8, 8.6), (56.9, 9.2), (57.3, 10.1), (57.5, 10.7)]
STARBUCKS_PAUSE = 2.0             # sekunder mellem kaldene
# Starbucks' pins, der staar forkert. Noeglen er Starbucks' storeNumber. KOORDINATERNE (og
# gaden) ER LAEST UD AF fastfood_kaeder_dk.csv (01-10-2026). Efterproevet i DAR 01-10-2026.
STARBUCKS_PINFEJL = {
    # 'Copenhagen Fisketorvet Fotex' (i foetex, Fisketorvet): pinnen staar paa Blytsvej 11,
    # 2000 Frederiksberg, 3,4 km fra centret. Raekken staar 75 m fra DAR-punktet for
    # Havneholmen 3 (DAR-postnr 1561) og 55 m fra vores foetex Fisketorvet.
    '25903-242948': {'street': 'Havneholmen 3', 'postnr': '1560', 'lat': 55.661794, 'lon': 12.560741},
    # 'Bilka Skalborg': pinnen staar paa den anden side af Hobrovej (reverse: Hobrovej 465E),
    # 219 m fra DAR-punktet for Bilkas Hobrovej 450; raekken staar 2 m fra det.
    '23109-224384': {'lat': 57.004707, 'lon': 9.87618},
    # 'Odense Rosengaardcenter': pinnen giver Goertlervej 6 i centret, 154 m fra raekken
    # (Oerbaekvej 75C; DAR-punktet 35 m derfra). Samme center - raekken er ankeret.
    '83408-313034': {'street': 'Ørbækvej 75C', 'lat': 55.383018, 'lon': 10.427913},
}


def _starbucks_gade(a):
    """Starbucks' adresselinje -> 'Vej nr' (stadig i Starbucks' ASCII-stavning).
    'Vesterbrogade 1e, 1550 Copenhaguen' -> 'Vesterbrogade 1e', 'Oerbaekvej 75 5220 Odense'
    -> 'Oerbaekvej 75', 'Vestergade 21 Fyn' -> 'Vestergade 21'."""
    s = _ren(a.get('streetAddressLine1'))
    s = re.sub(r',?\s*\d{4}\s+[^\d,]+$', '', s)
    s = re.sub(r'(\d\s?[A-Za-z]?)\s+[A-Z][a-z]+$', r'\1', s)
    return s.strip(' ,')


def starbucks():
    """Starbucks i Danmark (Salling Group som licenstager, 'DANSK'; Koebenhavns Hovedbanegaard
    drives af SSP) fra Starbucks' EGEN butiksfinder.

    Kilde: www.starbucks.com/store-locator kalder GET /apiproxy/v1/locations?lat=..&lng=..
    (kraever 'X-Requested-With: XMLHttpRequest', ellers 400) og faar butikkerne inden for
    25 miles af punktet med storeNumber, navn, adresse, koordinat og licenstager
    (marketBusinessUnitCode). Der er ingen landeliste, saa Danmark daekkes af _SB_GITTER.
    starbucks.dk er en parkeret domaene uden indhold. ROBOTS: www.starbucks.com/robots.txt
    er 'User-agent: * / Disallow:' (kun MJ12bot har Crawl-Delay) - intet forbudt.

    Efterproevet 01-10-2026 mod de 17 CSV-raekker og DAR:
      * 17 danske butikker = vores 17. Med Starbucks' egne pins parres 14 inden for 150 m;
        de tre oevrige er STARBUCKS_PINFEJL (Fisketorvet 3,4 km, Skalborg 220 m paa den
        forkerte side af Hobrovej, Rosengaardcentret 154 m). Ingen mangler, ingen ekstra.
      * Navnene laves af DAR-adressen ('Starbucks <vej>'), som i CSV'en: 16 af 17 bliver
        ordret som vores; Frederiksberg Centret bliver 'Starbucks Falkoner Alle' (vores:
        'Starbucks Solbjergvej', 103 m - samme center, parres paa afstand).
    FAELDER:
      * Akamai foran www.starbucks.com: fire parallelle traade gav 01-10-2026 'Access
        Denied' (403) efter ca. 30 kald, og hele vaerten - ogsaa robots.txt - var blokeret i
        ca. 11 minutter. Derfor ét kald ad gangen, STARBUCKS_PAUSE imellem, 30 punkter i
        stedet for et fuldt gitter, og stop ved foerste 403/429. Under en blokering giver
        robots.txt 403, og _robots_tilladt siger nej - henteren stopper saa allerede dér.
        Ugekoerslen koerer fra GitHub Actions; blokerer Akamai den IP, fejler henteren hoejt
        (HENTER FEJLEDE), og laget staar uovervaaget den uge.
      * Navne og adresser er paa engelsk/ASCII ('Copenhaguen Fiolstraede', 'Over Boelgen 1',
        'Norregade 6', 'Radhuspladsen Absalons Gaard', 'Salling Department Store Algade').
        ø er skrevet baade 'oe' og 'o', å baade 'aa' og 'a', saa stavningen kan ikke
        regnes tilbage. Adressen laegges derfor gennem dawa.normalize_one_ex (DAR) her,
        og navnet tages af DAR-vejnavnet. Svarer DAR ikke, fejler henteren hoejt.
      * Svaret kan omfatte Tyskland (Kiel) og Sverige: kun countryCode 'DK' tages med.
      * Starbucks' pins kan staa km forkert (Fisketorvet: Frederiksberg) - se ovenfor. Og
        adresseteksten er ikke altid butikkens ('Norregade 6' for butikken paa Nørregade
        23/25 i Vejle, 'Salling Department Store Sondergade 27'), saa en pin kan IKKE
        efterproeves mod teksten som hos Sunset. En ny butik med forkert pin ville faa navn
        og adresse fra reverse-opslaget ved pinnen (Fisketorvet-pinnen gav 'Blytsvej').
        Koer derfor henteren som KUN_RAPPORT i refresh_retail: nye butikker meldes og
        laegges ind i haanden; lukninger meldes som for alle andre.
    Efterproevet ogsaa mod Foedevarestyrelsens smiley-register 01-10-2026: 16 Starbucks under
    Salling Group (CVR 35954716, inkl. 'Industriens Hus' = Vesterbrogade 1E) + 'SSP DK AFD.
    225 Starbucks' (Banegaardspladsen 7) = 17 = finderens 16 'DANSK' + 1 'SSP_LTD'. CVR har
    to foraeldede P-enheder ('Starbucks Axeltowers', 'Starbucks' Nordre Fasanvej 25) uden
    smiley-registrering - dér er i dag hhv. Joe & The Juice og foetex.
    Forventet: 17."""
    import dawa
    url0 = STARBUCKS_URL % _SB_GITTER[0]
    if not _robots_tilladt(url0):
        raise RuntimeError('starbucks: robots.txt paa www.starbucks.com kunne ikke laeses (403 = '
                           'Akamai-blokering) eller forbyder nu /apiproxy/ - henter ikke')
    hdr = {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
    svar = []
    for i, p in enumerate(_SB_GITTER):
        if i:
            time.sleep(STARBUCKS_PAUSE)
        for forsoeg in (1, 2):
            try:
                svar.append(_json(STARBUCKS_URL % p, 60, headers=hdr))
                break
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):      # Akamai: stop med det samme, proev ikke igen
                    raise RuntimeError(f'starbucks: www.starbucks.com svarede {e.code} ved punkt '
                                       f'{i + 1} af {len(_SB_GITTER)} - blokeret/begraenset, '
                                       f'AFBRYDER frem for at svare med et hul i landet')
                if forsoeg == 2:
                    raise
            except (OSError, ValueError):     # URLError, socket.timeout (3.9), afbrudt svar
                if forsoeg == 2:
                    raise
            time.sleep(5)
    butikker = {}
    for i, liste in enumerate(svar):
        # Et omraade uden butikker er en tom liste. Alt andet (en fejl-dict, en tom side fra
        # Akamai) er et HUL i daekningen, som ellers blev til falske 'MULIG LUKNING'-linjer.
        if not isinstance(liste, list):
            raise RuntimeError(f'starbucks: uventet svar ved punkt {i + 1} af {len(_SB_GITTER)}: '
                               f'{str(liste)[:150]}')
        for x in liste:
            s = (x or {}).get('store') or {}
            if (s.get('address') or {}).get('countryCode') == 'DK' and s.get('storeNumber'):
                butikker[s['storeNumber']] = s
    out = []
    for nr, s in sorted(butikker.items()):
        a = s.get('address') or {}
        c = s.get('coordinates') or {}
        lat, lon = _dk_koord(c.get('latitude'), c.get('longitude'))
        if lat is None:
            continue
        r = {'street': _starbucks_gade(a), 'postnr': _dk_postnr(a.get('postalCode')),
             'by': _ren(a.get('city')), 'lat': lat, 'lon': lon}
        r.update(STARBUCKS_PINFEJL.get(nr, {}))
        adr, pn, by, status = dawa.normalize_one_ex(r['street'], r['postnr'], r['by'],
                                                    r['lat'], r['lon'])
        if status == 'dawa-nede':
            raise RuntimeError('starbucks: DAR svarede ikke - navnene kan ikke laves (proev igen)')
        if status == 'ok':
            r['street'] = re.sub(r',\s*\d{4}\b.*$', '', adr).strip()
            r['postnr'], r['by'] = pn, by
        vej = dawa.split_street(r['street'])[0] or _ren(s.get('name'))
        out.append({'brand': 'Starbucks', 'name': f'Starbucks {vej}', **r})
    out = _uniq(out)
    lo, hi = STARBUCKS_FORVENTET
    if not lo <= len(out) <= hi:
        raise RuntimeError(f'starbucks: {len(out)} danske butikker (forventet ~17) - behandles '
                           f'som en koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- KFC (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; kun rapport)
KFC_KONTAKT = 'https://kfc.dk/kontakta-os/'
KFC_CVR = 30173716                   # NSP Gallus AB A/S, KFC's franchisetager i Danmark
KFC_FORVENTET = (1, 15)              # 01-10-2026: 2


def kfc():
    """KFC: kaedens EGEN restaurantliste fra kfc.dk, adresserne fra kaedens P-enheder i CVR.

    Kilde 1 (hvilke restauranter): kontaktformularen paa kfc.dk/kontakta-os/ har et
    'Restaurant'-felt (Gravity Forms <select>) med kaedens restauranter: 'København, Fields'
    og 'København, Rådhuspladsen' (01-10-2026) plus 'Andet'. Det er den eneste liste paa
    kfc.dk; sitemap'et har kun forside, allergener og kontakt.
    Kilde 2 (hvor): restauranterne er P-enheder under NSP Gallus AB A/S (CVR 30173716) med
    navnet 'KFC <sted>': P 1032048087 'KFC Fields' (Arne Jacobsens Allé 12, 2300) og
    P 1032256755 'KFC Rådhuspladsen' (Rådhuspladsen 55, 1550). Adressen slaas op i DAR.
    robots.txt: kfc.dk forbyder kun /wp-admin/. 'Bestil online' (order.kfc.nu, og
    kfc.futureordering.com, samme platform) har 'Allow: /$' og 'Disallow: /' - kun
    forsiden; restaurant-API'et bag bestillingen maa IKKE bruges (01-10-2026).

    Efterproevet 01-10-2026: Fields er genfundet (DAR-punktet 126 m fra vores raekke, Field's
    er et stort center). Rådhuspladsen MANGLER hos os: genaabnet 04-08-2026 (presse; job-
    opslag 'KFC Rådhuspladsen åbner'), smiley 1588285 kontrolleret 04-08 og 11-08-2026.

    FAELDER:
      * CVR er kun adressebog, ikke populationen: CVR har ogsaa P 1032256763 'KFC Rødovre'
        (Tårnvej 3, 2610), som ikke er aabnet (ikke i formularen, ingen smiley; pressen
        kalder den 'planlagt'). Den kommer med, naar kaeden saetter den i formularen.
      * Et sted i formularen uden P-enhed 'KFC <sted>' gives uden koordinat (refresh_retail
        melder det som INFO); find adressen i CVR/smiley og ret navnet her.
      * Navnet bygges som CSV'ens 'København S, Fields': DAR's postnummernavn + stedet.
      * Rådhuspladsen 55 er ogsaa Burger King-raekkens adresse (smiley 115685, Nordic Service
        Partners A/S, CVR 19033546 - samme koncern som KFC's NSP Gallus); KFC-punktet ligger
        4 m fra Burger King-raekken. To restauranter i samme hus, ikke en dublet.
      * Kraever Datafordeler-noeglen (CVR og DAR), som resten af den ugentlige koersel.
    Forventet: 2."""
    from cvr_tjek import _sider       # CVR via Datafordeleren (samme noegle som DAR)
    if not _robots_tilladt(KFC_KONTAKT):
        raise RuntimeError(f'kfc: robots.txt forbyder nu {KFC_KONTAKT} - henter ikke')
    m = re.search(r'>\s*Restaurant\s*<.*?<select[^>]*>(.*?)</select>', _text(KFC_KONTAKT, 60), re.S)
    if not m:
        raise RuntimeError('kfc: Restaurant-feltet findes ikke i kontaktformularen - siden er lavet om')
    steder = [v for v in (_ren(_html.unescape(x)) for x in
                          re.findall(r"<option[^>]*value=['\"]([^'\"]*)['\"]", m.group(1)))
              if v and v.lower() not in ('andet', 'annat', 'other')]
    pe = _sider('CVR_Produktionsenhed', f'{{tilknyttetVirksomhedsCVRNummer:{{eq:{KFC_CVR}}}}}',
                'id status produktionsenhedOphoersdato')
    ids = json.dumps([x['id'] for x in pe if x['status'] == 'aktiv' and not x['produktionsenhedOphoersdato']])
    navn = {r['CVREnhedsId']: r['vaerdi'] for r in
            _sider('CVR_Navn', f'{{CVREnhedsId:{{in:{ids}}}}}', 'CVREnhedsId vaerdi')}
    def nk(s):                        # "Field's" og 'Fields' giver samme noegle
        return re.sub(r'[^a-z0-9æøå]', '', (s or '').lower())
    pr_sted = {}
    for r in _sider('CVR_Adressering', f'{{CVREnhedsId:{{in:{ids}}}}}',
                    'CVREnhedsId AdresseringAnvendelse CVRAdresse_vejnavn CVRAdresse_husnummerFra '
                    'CVRAdresse_postnummer'):
        mm = re.match(r'(?i)\s*kfc\s+(.+?)\s*$', navn.get(r['CVREnhedsId']) or '')
        if mm and r['AdresseringAnvendelse'] == 'beliggenhedsadresse' and r['CVRAdresse_vejnavn']:
            pr_sted[nk(mm.group(1))] = (f"{r['CVRAdresse_vejnavn']} {r['CVRAdresse_husnummerFra'] or ''}".strip(),
                                        str(r['CVRAdresse_postnummer'] or ''))
    out, byer = [], [nk(s.rpartition(',')[0]) for s in steder]
    for s in steder:
        by, _, sted = (x.strip() for x in s.rpartition(','))
        # 'København, Fields' -> P-enheden 'KFC Fields'; ellers bynavnet, men kun naar byen kun
        # har den ene restaurant i formularen ('Rødovre, X' -> 'KFC Rødovre').
        gade, pn = pr_sted.get(nk(sted)) or (pr_sted.get(nk(by)) if byer.count(nk(by)) == 1 else None) \
            or ('', '')
        hit = _oil_geokod(gade, pn)[0] if gade else None
        if not hit:
            out.append({'brand': 'KFC', 'name': s, 'street': gade, 'postnr': pn, 'by': by,
                        'lat': None, 'lon': None})
            continue
        out.append({'brand': 'KFC', 'name': f"{hit['postnrnavn']}, {sted}" if by else s,
                    'street': f"{hit['vejnavn']} {hit['husnr']}", 'postnr': hit['postnr'],
                    'by': hit['postnrnavn'], 'lat': round(hit['y'], 6), 'lon': round(hit['x'], 6)})
    lo, hi = KFC_FORVENTET
    if not lo <= len(out) <= hi:
        raise RuntimeError(f'kfc: {len(out)} restauranter (forventet {lo}-{hi}) - behandles som '
                           f'en koerselsfejl, ikke som lukninger/aabninger')
    return out


# ---- Cocks & Cows (etape 3b, 01-10-2026: bygget af en efterforsker, genkoert og efterproevet af en skeptiker; kun rapport)
CC_URL = 'https://cocksandcows.dk/restaurants/'
CC_FORVENTET = (3, 12)               # 01-10-2026: 5
CC_PAUSE = 10                        # robots.txt: 'Crawl-delay: 10' (mellem robots.txt og siden)
CC_SAESON = {'tisvilde'}             # saesonrestauranter: aabningstekst holder dem ikke ude
# Kort i gitteret, som kaeden har afmeldt alle andre steder. Springes KUN over, saa laenge
# siden ikke har en adresse for kortet; faar det en igen, er restauranten med igen. Noeglen er
# kortets titel i lowercase; hver post skal have belaeg.
CC_UDGAAET = {
    # Lufthavnen (Terminal 2, airside) er lukket: menupunkterne var aktive 14-12-2025 og
    # udkommenteret 10-02-2026 (Wayback), /restaurants/cph-airport/ giver 404 (01-10-2026) og
    # er ude af page-sitemap.xml, ingen smiley-kontrol siden 27-10-2025 (de to foregaaende kom
    # med 10 og 6 maaneders mellemrum; smiley 758198), og RestaurantGuru: 'The spot is
    # permanently closed' (seneste anmeldelser ca. 01-2026). CVR P 1023723405 (Cock's & Cows
    # CPH Airport ApS) er stadig aktiv - CVR halter. Kun kortet uden adresse staar tilbage.
    'københavns lufthavn': 'lukket ca. 01-2026; kaeden har fjernet den alle andre steder',
}
_CC_ADR = re.compile(r'^(.+?\d+\s*[A-Za-zÆØÅæøå]?)\s*,\s*(\d{4})\s+(.+)$')
# Kaeden skriver statustekster paa baade dansk og engelsk ('Back next summer', 'Opens 1st
# may', 'Åbner den 1. maj'); _aabner_senere kender kun 'åbner'.
_CC_IKKE_AABEN = re.compile(r'(?i)\b(?:opens|opening|coming soon|back next|snart|genåbner|'
                            r'lukket|closed)\b')


def _cc_ikke_aaben(tekst):
    t = _ren(tekst)
    return bool(t) and (_aabner_senere(t) or bool(_CC_IKKE_AABEN.search(t)))


def _cc_punkt(gade, pn, by):
    """Kaedens adresse -> DAR-post via _oil_geokod. Tivoli Food Hall staar med Tivolis
    firmapostnummer 1630, som ikke er et adressepostnummer i DAR ('ukendt postnummer');
    saa slaas vej + husnummer op i hele landet, og hittet hvis postnummernavn begynder med
    kaedens bynavn vinder, hvis det er entydigt (Vesterbrogade 3 -> 1620 København V)."""
    import dawa
    hit, grund = _oil_geokod(gade, pn)
    if hit or grund != 'ukendt postnummer':
        return hit
    vej, nr = dawa.split_street(_normal_gade_nr(gade))
    kand = [x for x in dawa._q(vejnavn=vej, husnr=nr)
            if (x.get('postnrnavn') or '').lower().startswith((by or '').lower())]
    return kand[0] if len({x['postnr'] for x in kand}) == 1 else None


def cocks_cows():
    """Cocks & Cows (Cocks & Cows ApS, CVR 32439292) fra kaedens EGEN restaurantliste.

    Kilde: cocksandcows.dk/restaurants/ (WordPress/YOOtheme). Restauranterne er gitteret i
    <main>: ét el-item pr. restaurant med titel (h3.el-title), adresse eller statustekst
    (div.el-meta) og link. Kort uden adresse faar den fra off-canvas-menuerne paa samme side
    ('Menu', 'Book bord', 'Drop in venues'); HTML-kommentarer fjernes foerst, for det er
    saadan kaeden afmelder en restaurant. Kaedens adresser har ingen koordinat, saa punktet er
    DAR-adgangspunktet (_cc_punkt). Ét kald til kaeden.
    robots.txt: 'User-agent: * / Disallow: /wp-admin/ / Allow: /wp-admin/admin-ajax.php /
    Crawl-delay: 10' (01-10-2026) - derfor CC_PAUSE mellem robots.txt og siden.

    Efterproevet 01-10-2026 mod fastfood_kaeder_dk.csv (7 raekker): 5 genfundet paa 0 m
    (Gammel Strand, Lyngby, SP34, Tivoli Food Hall, Tisvilde); alle 5 er aktive P-enheder i
    CVR, og Tivoli Food Hall staar ogsaa paa tivoli.dk's egen Food Hall-side. To af vores
    raekker er IKKE aabne Cocks & Cows-restauranter og meldes som mulige lukninger:
      * 'Cocks & Cows CPH Airport (Terminal 2)': lukket ca. 01-2026 (se CC_UDGAAET).
      * 'Cocks & Cows Camping Bar Kødbyen' (Kødboderne 9): minigolfbaren 'Camping Kødbyen'
        (maerket Camping, camping.bar, med Boltens Gård, Aaen og Malmö; CVR P 1022722707
        'Camping Kødbyen' under Cocks & Cows ApS). Kaeden naevner den kun i 'Book bord'-
        menuen ('Minigolf & Burgers'), ikke i restaurantgitteret.

    FAELDER:
      * Gitteret vedligeholdes daarligt: lufthavnens kort stod der stadig 9 maaneder efter
        lukningen, og Tisvilde har staaet som 'Back next summer' siden mindst 11-2025, ogsaa
        i maj 2026, men var aaben i juli (smiley 03-07-2026). Et kort er derfor kun med, naar
        siden har en adresse for det (paa kortet eller i en aktiv menu). Et kort uden adresse
        gives uden koordinat (refresh_retail melder det som INFO) - medmindre det staar i
        CC_UDGAAET. Brug aldrig en haandskrevet adresse til at holde et kort i live: det
        skjulte lufthavnens lukning i den foerste udgave af denne henter.
      * Statustekster paa dansk og engelsk ('Opens 1st may', 'Coming soon', 'Åbner den 1.
        maj', 'Midlertidigt lukket') paa kortet eller i menuerne holder en restaurant ude,
        undtagen saesonrestauranter (CC_SAESON).
      * Tivoli Food Hall staar med firmapostnummeret 1630 (DAR: Vesterbrogade 3, 1620).
      * Menuerne har forskellige titler for samme sted ('København V (SP34)' / 'København K
        (SP34)'); gitteret er populationen, menuerne kun adressebog og status.
      * Navn: 'Cocks & Cows ' + stedet i parentes ('SP34'), gaden for en ren bydel
        ('København K' -> 'Gammel Strand') eller titlen. CSV'ens 'Gammel Strand (flagship)'
        og 'Tisvilde (seasonal)' er haandrettede (matches paa naerhed, 0 m).
    Forventet: 5."""
    if not _robots_tilladt(CC_URL):
        raise RuntimeError(f'cocks_cows: robots.txt forbyder nu {CC_URL} - henter ikke')
    time.sleep(CC_PAUSE)
    h = _text(CC_URL, 60)
    i0, i1 = h.find('<main'), h.find('</main>')
    if i0 < 0 or i1 < i0:
        raise RuntimeError('cocks_cows: <main> findes ikke paa /restaurants/ - siden er lavet om')
    aktiv = re.sub(r'<!--.*?-->', ' ', h, flags=re.S)     # udkommenteret = afmeldt af kaeden
    menu, status = {}, {}
    for t, a in re.findall(r'<div class="by">(.*?)<br\s*/?>\s*<span class="by adresse">(.*?)</span>',
                           aktiv, re.S):
        menu.setdefault(_ren(re.sub(r'<[^>]+>', ' ', t)).lower(), _ren(a))
    for t, b in re.findall(r'<div class="by">((?:(?!<div class="by">).)*?)<br(?:(?!<div class="by">).)*?'
                           r'<div class="offcanvas_badge[^"]*">(.*?)</div>', aktiv, re.S):
        status.setdefault(_ren(re.sub(r'<[^>]+>', ' ', t)).lower(), []).append(
            _ren(re.sub(r'<[^>]+>', ' ', b)))
    out = []
    for blk in re.split(r'<div class="el-item', h[i0:i1])[1:]:
        t = re.search(r'<h3 class="el-title[^"]*">(.*?)</h3>', blk, re.S)
        if not t:
            continue
        titel = _ren(re.sub(r'<[^>]+>', ' ', t.group(1)))
        meta = re.search(r'<div class="el-meta[^"]*">(.*?)</div>', blk, re.S)
        meta = _ren(re.sub(r'<[^>]+>', ' ', meta.group(1))) if meta else ''
        href = re.search(r'href="([^"]+)"', blk[:t.start()])
        nogle = titel.lower()
        # Kun restaurantkort: et link til /restaurants/, en adresse paa kortet eller et menunavn.
        if not ((href and '/restaurants/' in href.group(1)) or _CC_ADR.match(meta) or nogle in menu):
            continue
        adr = meta if _CC_ADR.match(meta) else menu.get(nogle, '')
        if not adr and nogle in CC_UDGAAET:
            continue                       # afmeldt af kaeden; kun kortet staar tilbage
        if nogle not in CC_SAESON and (_cc_ikke_aaben('' if _CC_ADR.match(meta) else meta)
                                       or any(_cc_ikke_aaben(b) for b in status.get(nogle, []))):
            continue
        m = _CC_ADR.match(adr)
        gade, pn, by = (_ren(m.group(1)), m.group(2), _ren(m.group(3))) if m else ('', '', '')
        p = re.search(r'\(([^)]+)\)', titel)
        sted = p.group(1) if p else (re.sub(r'\s+\d.*$', '', gade) if gade and
                                     re.fullmatch(r'(?i)københavn\s+[a-zø]{1,2}', titel) else titel)
        # Et nyt kort uden adresse nogen steder gives uden koordinat (refresh_retail melder det
        # som INFO); find da ud af, om det er en ny eller en afmeldt restaurant.
        hit = _cc_punkt(gade, pn, by) if gade else None
        out.append({'brand': 'Cocks & Cows', 'name': f'Cocks & Cows {sted}', 'street': gade,
                    'postnr': hit['postnr'] if hit else pn, 'by': hit['postnrnavn'] if hit else by,
                    'lat': round(hit['y'], 6) if hit else None, 'lon': round(hit['x'], 6) if hit else None})
    out = _uniq(out)
    lo, hi = CC_FORVENTET
    if not lo <= len(out) <= hi:
        raise RuntimeError(f'cocks_cows: {len(out)} restauranter (forventet {lo}-{hi}) - '
                           f'behandles som en koerselsfejl, ikke som lukninger/aabninger')
    return out

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
