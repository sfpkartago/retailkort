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
      * 165 parret inden for 150 m efter KILDEFEJL. Lyngby Storcenter (183 m, samme
        butik, uafklaret) meldes som KOORD-AFVIGELSE, fordi navnene er ens.
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
