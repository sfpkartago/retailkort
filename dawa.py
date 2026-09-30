#!/usr/bin/env python3
"""
dawa.py — adressenormalisering mod DAWA (Danmarks Adresseregister).

Baggrund: kildernes egne adressefelter er upålidelige (supercharge.info sendte fx
"Hobrovej 452, 9300 Aalborg" for et anlæg i 9200 Aalborg SV). Koordinaten er
derimod næsten altid rigtig — den er det anlægget faktisk står på.

VIGTIGT (rettet 2026-09-08, v2): v1 havde et fallback i lookup() der returnerede
(DAWA's vejnavn, KILDENS husnr) når husnummeret ikke fandtes. Et miss så altså ud
som et hit, så normalize_one beholdt kildens tekst og sprang både stavekontrollen
og reverse over. Resultat: 74 af 724 normaliserede rækker fik en adresse DAWA ikke
har, og tre rækker blev direkte forkerte:
  · Tesla Ikast   "Uhregårds Alle 6"  — 1.813 m fra rækkens egen koordinat
  · Tesla Odense  "Ørbækvej 75, 5230" — findes ikke (Ørbækvej 75 er 5220)
  · Tesla Kliplev husnr "12"          — det fjerneste punkt på vejen
v2 verificerer i stedet enhver kandidat mod rækkens koordinat. ÉN undtagelse (v2.2):
er kildens husnummer samme adressefamilie som reverse's (75 vs 75A, 97 vs 97E), beholdes
kildens tal uden afstandstjek — bogstavet er dér blot en underadresse på samme grund,
og kildens tal er det mest genkendelige. Alle andre veje/husnumre skal bevise sig.

Reglen (v2, skærpet i v3.1):
  1. reverse(lat,lon) giver den nærmeste adgangsadresse — den er sandhedsvidne.
  2. Er kildens vejnavn den SAMME vej som reverse's (uanset stavemåde): behold
     kildens husnr hvis det findes på vejen, ellers (v3.1) BBR-bygningens adresse
     hvis kalderen har bedt om det, ellers det nærmeste husnr.
  3. Er det en ANDEN vej: (a) kildens EGEN adresse, hvis den findes inden for
     grænsen; (b) BBR-bygningen på koordinaten, hvis kalderen har bedt om det;
     (c) et nummer i kildens familie (1 -> 1A), men kun omtrent lige så tæt på som
     reverse; (d) ellers vinder reverse. Til og med v3.0 konkurrerede ALLE numre på
     kildens vej på afstand, så nabonummeret vandt over kildens eget (se trin 3).
  4. Postnr/by følger den adresse der blev valgt.

Brug:
    from dawa import normalize_rows
    normalize_rows(rows, adr=2, postnr=3, by=4, lat=8, lon=9)   # in-place
    normalize_rows(rows, ..., bygning='325')   # tankstationer: BBR-bygningen som reserve

v3.0 (29-09-2026): DAWA LUKKER 1. oktober 2026 kl. 10 "i sin helhed"
(Klimadatastyrelsen). Modulet hedder stadig dawa.py, fordi otte filer importerer
det, men de to grundfunktioner er skiftet ud:
  * _q (adgangsadresser pr. vejnavn/husnr/postnr) og reverse_full (nærmeste
    adgangsadresse til en koordinat) går nu mod Danmarks Adresseregister (DAR) via
    Datafordelerens GraphQL (graphql.datafordeler.dk/DAR/v2). Det kræver en
    API-nøgle: miljøvariablen DATAFORDELER_API_KEY eller filen ~/.datafordeler-key.
  * vask() erstatter DAWA's datavask med Klimadatastyrelsens Adressevask
    (adressevaelger.dk/vask). Den svarer KUN ved præcis ét match; DAWA's kategori
    A/B/C findes ikke længere og oversættes her (se vask()).
Begge returnerer samme poster som DAWA's 'mini'-format, så al logikken nedenfor -
v2's regler og de fælder de lukker - er uændret. Omvendt geokodning findes ikke
som færdig tjeneste længere: den bygges af en geografisk søgning på DAR_Adressepunkt
i en boks omkring punktet, der udvides til der er et husnummer. DAR giver
koordinater i ETRS89/UTM32 (EPSG:25832); de omregnes til WGS84 her.

FÆLDER i DAR (målt 29-09-2026):
  * Alle forespørgsler SKAL have virkningstid/registreringstid (eller et id) -
    ellers afvises de (DAF-GQL-0009). Med "nu" som tid kommer kun den aktuelle
    version, så historiske rækker ikke skal sorteres fra i hånden.
  * vejnavn matches eksakt og med forskel på store/små bogstaver - PRÆCIS som
    DAWA's vejnavn-parameter (målt: 'silkeborgvej' gav 0 i begge). husnummertekst
    har store bogstaver; DAWA var ligeglad med store/små i husnr, så vi sender upper().
  * DAWA's status 1 (gældende) og 3 (foreløbig) hedder i DAR "3" og "2".
  * En ny API-nøgle giver ~30 % tilfældige 401 den første time (DAF-AUTH-0005),
    mens den spredes til Datafordelerens servere - derfor genforsøg på 401.
"""
import http.client, json, math, os, re, threading, time, urllib.request, urllib.parse, concurrent.futures

UA = {'User-Agent': 'kartago-dawa/3.1 (+https://github.com/sfpkartago/retailkort)'}
DAR_URL = 'https://graphql.datafordeler.dk/DAR/v2'
AV_URL = 'https://adressevaelger.dk'
# Adressevælgeren kræver et token på mindst 10 tegn, men har endnu ingen brugerstyring;
# KDS anbefaler selv dette. Brugerstyring ventes ultimo 2026/primo 2027.
AV_TOKEN = os.environ.get('ADRESSEVAELGER_TOKEN', 'adressevaelger123')
# Et anlægs EGEN adresse ligger inden for et par hundrede meter af anlægget — et
# stort motorvejs- eller centeranlæg kan strække sig så langt. Ligger kildens adresse
# længere væk, beskriver kilden et ANDET sted (Tesla Odense: 444 m, det gamle anlæg;
# Tesla Ikast: 1.813 m). Grænsen er derfor sat på anlægs-udstrækning, ikke på et
# enkelt datapunkt. Hobrovej 452 (Aalborg Storcenter, 289 m) er inden for. (Til og med
# v3.0 endte rækken på 452C, det nærmeste nummer på vejen; fra v3.1 vinder kildens
# eget nummer, når det findes inden for grænsen - se trin 3 i _normaliser.)
SLACK_M = 150     # ud over reverse's eget punkt
FLOOR_M = 300     # ... men altid mindst så meget
# v3.1: BBR-bygningen (fx anvendelse 325 = tankstation) skal staa praktisk talt paa
# koordinaten. Maalt 30-09-2026: paa de OK-stationer hvor kildens adresse ikke fandtes,
# stod stationens egen bygning 1-3 m fra OK's koordinat. En stoerre radius risikerer
# at ramme en konkurrents bygning paa den anden side af vejen, naar en ubemandet
# OK-automat (fx Albertslund) slet ingen bygning har.
BYGNING_M = 30
BBR_URL = 'https://graphql.datafordeler.dk/BBR/v2'
_cache = {}


class DawaNede(Exception):
    """DAWA svarede ikke — til forskel fra "DAWA svarede, men fandt intet".

    v2.3: _get returnerede foer None i BEGGE tilfaelde. normalize_one_ex afgjorde
    kun 'dawa-nede' paa reverse-kaldet, saa faldt SOEGE-endpointet ud mens reverse
    svarede, gik trin 2-4 igennem paa reverse-adressen alene og satte status 'ok'.
    Maalt med fejlinjektion paa 40 OK-raekker: 8 af dem fik en ANDEN adresse
    ("Karlslunde Landevej 16" -> "Snedkergangen 16"), og skipped var 0 — saa
    refresh_data.py's "AFBRYDER frem for at skrive kildens forkerte postnumre"
    fyrede ikke. Det er praecis den faelde v2 skulle lukke: et miss saa ud som et hit."""


def _get(url, tries=3):
    """Retry: et enkelt tabt DAWA-kald efterlod ellers tavst en række uden postnr/by.

    -> svaret, eller None hvis DAWA svarede med intet. Rejser DawaNede hvis
    forbindelsen fejlede hver gang; den skelnen er hele pointen (se DawaNede)."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # v3.0: 400/404 er et SVAR ("ugyldigt input"/"findes ikke"), ikke et udfald.
            # Adressevaelgeren giver 400 ved vejnavne over 40 tegn og 404 for en nedlagt
            # adresse-id; som DawaNede blev det til en falsk KOERSELSFEJL hver uge og tre
            # spildte genforsoeg (fundet i review 29-09-2026). 401/403/429/5xx er udfald.
            if e.code in (400, 404):
                return None
            if i + 1 < tries:
                time.sleep(1.5 * (i + 1))
        except Exception:
            if i + 1 < tries:
                time.sleep(1.5 * (i + 1))
    raise DawaNede(_skrub(url))


# ------------------------------------------------------------------ DAR-backend
class NoegleMangler(RuntimeError):
    """Ingen Datafordeler-nøgle. Med vilje IKKE en DawaNede: den må ikke blive til
    tavse 'dawa-nede'-rækker - kørslen skal stoppe med en besked der siger hvorfor."""


def _noegle():
    k = os.environ.get('DATAFORDELER_API_KEY', '').strip()
    if not k:
        p = os.path.expanduser('~/.datafordeler-key')
        if os.path.exists(p):
            k = open(p, encoding='utf-8').read().strip()
    if not k:
        raise NoegleMangler('ingen Datafordeler-API-nøgle: sæt DATAFORDELER_API_KEY '
                            '(GitHub-secret i Actionen) eller læg den i ~/.datafordeler-key')
    return k


def _skrub(s):
    try:
        return str(s).replace(_noegle(), '<NØGLE>')
    except NoegleMangler:
        return str(s)


def _gql(query, tries=6, base=None):
    """-> data-delen af svaret. Rejser DawaNede hvis DAR ikke svarede brugbart.
    base: et andet register paa Datafordeleren (BBR_URL); samme noegle, samme fejlhaandtering."""
    url = (base or DAR_URL) + '?apikey=' + urllib.parse.quote(_noegle())
    body = json.dumps({'query': query}).encode()
    sidst = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers={**UA, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=40) as r:
                j = json.loads(r.read())
        except urllib.error.HTTPError as e:
            sidst = f'HTTP {e.code}: {_skrub(e.read()[:300])}'
            # 401: nøglen kan være ved at blive spredt; 429/5xx: prøv igen
            if e.code in (401, 429) or e.code >= 500:
                time.sleep(min(2 * (i + 1), 12)); continue
            raise DawaNede(f'DAR afviste forespørgslen: {sidst}')
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, http.client.HTTPException) as e:
            # HTTPException: et afkortet svar (IncompleteRead) eller BadStatusLine er
            # hverken OSError eller URLError. Uden den crashede ét afbrudt DAR-svar hele
            # koerslen i stedet for at blive gentaget (fundet i review 29-09-2026;
            # den gamle _get fangede alt).
            sidst = _skrub(e); time.sleep(min(2 * (i + 1), 12)); continue
        if j.get('errors'):
            raise DawaNede('DAR svarede med fejl: ' + _skrub(json.dumps(j['errors'], ensure_ascii=False))[:400])
        return j['data']
    raise DawaNede(f'DAR svarede ikke efter {tries} forsøg: {sidst}')


def _tid():
    nu = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    return f'virkningstid:"{nu}", registreringstid:"{nu}"'


def _alle(entitet, where, felter):
    """Alle sider af en DAR-forespørgsel. where er en GraphQL-literal."""
    ud, after = [], None
    for _ in range(60):
        a = f', after:{json.dumps(after)}' if after else ''
        d = _gql(f'{{ {entitet}(first:1000{a}, {_tid()}, where:{where}){{ '
                 f'pageInfo{{hasNextPage endCursor}} nodes{{ {felter} }} }} }}')[entitet]
        ud += d['nodes']
        if not d['pageInfo']['hasNextPage']:
            return ud
        after = d['pageInfo']['endCursor']
    raise DawaNede(f'{entitet}: over 60 sider - forespørgslen er for bred')


def _bidder(xs, n=100):
    xs = list(xs)
    return [xs[i:i + n] for i in range(0, len(xs), n)]


AKTIV = '["2","3"]'        # DAR: 2 = foreløbig, 3 = gældende (DAWA's 3 og 1)
_laas = threading.Lock()
_pn = {}                   # postnummer-id -> (postnr, navn)
_pn_nr = {}                # postnr -> postnummer-id
_vejnavn = {}              # navngivenvej-id -> vejnavn
_vej_ids = {}              # vejnavn (eksakt) -> [navngivenvej-id]


def _postnumre_indlaes():
    with _laas:
        if _pn:
            return
        rows = _alle('DAR_Postnummer', f'{{status:{{in:{AKTIV}}}}}', 'id_lokalId postnr navn')
        if len(rows) < 500:     # Danmark har ~1.100 postnumre; et halvt svar er en fejl
            raise DawaNede(f'DAR gav kun {len(rows)} postnumre')
        for r in rows:
            _pn[r['id_lokalId']] = (r['postnr'], r['navn'])
            _pn_nr[r['postnr']] = r['id_lokalId']


def postnumre():
    """-> {postnr: navn} for alle aktive postnumre (erstatter DAWA's /postnumre)."""
    _postnumre_indlaes()
    return {nr: navn for nr, navn in _pn.values()}


def _vej(vejnavn):
    if vejnavn not in _vej_ids:
        rows = _alle('DAR_NavngivenVej',
                     f'{{vejnavn:{{eq:{json.dumps(vejnavn, ensure_ascii=False)}}}, status:{{in:{AKTIV}}}}}',
                     'id_lokalId vejnavn')
        for r in rows:
            _vejnavn[r['id_lokalId']] = r['vejnavn']
        _vej_ids[vejnavn] = [r['id_lokalId'] for r in rows]
    return _vej_ids[vejnavn]


def _vejnavne(ids):
    mangler = [i for i in set(ids) if i and i not in _vejnavn]
    for b in _bidder(mangler):
        for r in _alle('DAR_NavngivenVej', f'{{id_lokalId:{{in:{json.dumps(b)}}}}}', 'id_lokalId vejnavn'):
            _vejnavn[r['id_lokalId']] = r['vejnavn']
    return _vejnavn


_WKT = re.compile(r'POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)')


def _xy(wkt):
    m = _WKT.match(wkt or '')
    return (float(m.group(1)), float(m.group(2))) if m else None


def _punkter(ids):
    """adressepunkt-id -> (E, N) i UTM32."""
    ud = {}
    for b in _bidder(set(i for i in ids if i)):
        for r in _alle('DAR_Adressepunkt', f'{{id_lokalId:{{in:{json.dumps(b)}}}}}', 'id_lokalId position{wkt}'):
            xy = _xy((r.get('position') or {}).get('wkt'))
            if xy:
                ud[r['id_lokalId']] = xy
    return ud


HF = 'id_lokalId husnummertekst adgangspunkt navngivenVej postnummer status'


def _mini(noder, punkter=None):
    """DAR-husnumre -> DAWA-'mini'-poster {vejnavn, husnr, postnr, postnrnavn, y, x}.
    Et husnummer uden adgangspunkt eller postnummer kan ikke bruges og springes over."""
    _postnumre_indlaes()
    vn = _vejnavne(n['navngivenVej'] for n in noder)
    pts = punkter if punkter is not None else _punkter(n['adgangspunkt'] for n in noder)
    ud = []
    for n in noder:
        xy, pn = pts.get(n['adgangspunkt']), _pn.get(n['postnummer'])
        if not xy or not pn or not n.get('husnummertekst'):
            continue
        lat, lon = utm32_til_wgs84(*xy)
        ud.append({'id': n['id_lokalId'], 'vejnavn': vn.get(n['navngivenVej']),
                   'husnr': n['husnummertekst'], 'postnr': pn[0], 'postnrnavn': pn[1],
                   'y': lat, 'x': lon, '_E': xy[0], '_N': xy[1]})
    return ud


def _husnr_noegle(p):
    m = re.match(r'^(\d+)\s*(.*)$', str(p.get('husnr') or ''))
    return (p.get('postnr') or '', p.get('vejnavn') or '',
            int(m.group(1)) if m else 10**9, (m.group(2) if m else str(p.get('husnr'))).upper())


def _q(vejnavn=None, husnr=None, postnr=None, per_side=200, side=1, struktur=None, **ukendt):
    """Som DAWA's /adgangsadresser?vejnavn=&husnr=&postnr=&per_side=&side=&struktur=mini."""
    if ukendt:
        raise TypeError(f'_q: parametre DAR-udgaven ikke understøtter: {sorted(ukendt)}')
    if not vejnavn:
        return []
    ids = _vej(vejnavn)
    if not ids:
        return []
    w = [f'status:{{in:{AKTIV}}}']
    if postnr:
        _postnumre_indlaes()
        pid = _pn_nr.get(str(postnr).strip())
        if not pid:
            return []
        w.append(f'postnummer:{{eq:"{pid}"}}')
    if husnr:
        w.append(f'husnummertekst:{{eq:{json.dumps(str(husnr).strip().upper(), ensure_ascii=False)}}}')
    noder = []
    for b in _bidder(ids):
        noder += _alle('DAR_Husnummer', '{' + ', '.join(w + [f'navngivenVej:{{in:{json.dumps(b)}}}']) + '}', HF)
    rows = sorted(_mini(noder), key=_husnr_noegle)
    a = (int(side) - 1) * int(per_side)
    return rows[a:a + int(per_side)]


def wgs84_til_utm32(lat, lon):
    """WGS84 -> ETRS89/UTM zone 32N (EPSG:25832). Krüger-række, 3 led."""
    a, f = 6378137.0, 1 / 298.257222101
    k0, E0, lon0 = 0.9996, 500000.0, math.radians(9.0)
    n = f / (2 - f)
    A = a / (1 + n) * (1 + n**2 / 4 + n**4 / 64)
    al = (n / 2 - 2 * n**2 / 3 + 5 * n**3 / 16, 13 * n**2 / 48 - 3 * n**3 / 5, 61 * n**3 / 240)
    phi, lam = math.radians(lat), math.radians(lon) - lon0
    c = 2 * math.sqrt(n) / (1 + n)
    t = math.sinh(math.atanh(math.sin(phi)) - c * math.atanh(c * math.sin(phi)))
    xp = math.atan2(t, math.cos(lam))
    ep = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    E = E0 + k0 * A * (ep + sum(al[j] * math.cos(2 * (j + 1) * xp) * math.sinh(2 * (j + 1) * ep) for j in range(3)))
    N = k0 * A * (xp + sum(al[j] * math.sin(2 * (j + 1) * xp) * math.cosh(2 * (j + 1) * ep) for j in range(3)))
    return E, N


def utm32_til_wgs84(E, N):
    """ETRS89/UTM zone 32N -> (lat, lon). Kontrolleret mod DAWA's WGS84: 0,00 m."""
    a, f = 6378137.0, 1 / 298.257222101
    k0, E0, lon0 = 0.9996, 500000.0, math.radians(9.0)
    n = f / (2 - f)
    A = a / (1 + n) * (1 + n**2 / 4 + n**4 / 64)
    b = (n / 2 - 2 * n**2 / 3 + 37 * n**3 / 96, n**2 / 48 + n**3 / 15, 17 * n**3 / 480)
    d = (2 * n - 2 * n**2 / 3 - 2 * n**3, 7 * n**2 / 3 - 8 * n**3 / 5, 56 * n**3 / 15)
    xi, eta = N / (k0 * A), (E - E0) / (k0 * A)
    xp = xi - sum(b[j] * math.sin(2 * (j + 1) * xi) * math.cosh(2 * (j + 1) * eta) for j in range(3))
    ep = eta - sum(b[j] * math.cos(2 * (j + 1) * xi) * math.sinh(2 * (j + 1) * eta) for j in range(3))
    chi = math.asin(math.sin(xp) / math.cosh(ep))
    lat = chi + sum(d[j] * math.sin(2 * (j + 1) * chi) for j in range(3))
    return math.degrees(lat), math.degrees(lon0 + math.atan2(math.sinh(ep), math.cos(xp)))


def _reverse_dar(lat, lon):
    """Nærmeste aktive adgangsadresse -> mini-post el. None.
    Boksen udvides (40 m, 120, 360, 1080, 3240 m halv bredde) til der er et husnummer.
    Findes det nærmeste længere væk end boksens halve bredde, kan et nærmere ligge i
    et hjørne uden for boksen - så søges igen med en boks der dækker den radius."""
    E, N = wgs84_til_utm32(float(lat), float(lon))
    d = 40.0
    while d <= 3300:
        wkt = f'POLYGON(({E-d} {N-d},{E+d} {N-d},{E+d} {N+d},{E-d} {N+d},{E-d} {N-d}))'
        pts = _alle('DAR_Adressepunkt', f'{{position:{{intersects:{{wkt:"{wkt}", crs:25832}}}}}}',
                    'id_lokalId position{wkt}')
        pos = {p['id_lokalId']: _xy((p.get('position') or {}).get('wkt')) for p in pts}
        pos = {k: v for k, v in pos.items() if v}
        noder = []
        for b in _bidder(pos):
            noder += _alle('DAR_Husnummer', f'{{adgangspunkt:{{in:{json.dumps(b)}}}, status:{{in:{AKTIV}}}}}', HF)
        if noder:
            afst = lambda n: math.hypot(pos[n['adgangspunkt']][0] - E, pos[n['adgangspunkt']][1] - N)
            noder.sort(key=lambda n: (afst(n), n['id_lokalId']))
            # _mini springer husnumre uden husnummertekst/postnummer over. DAR har aktive
            # husnumre uden tekst; tog vi kun noder[0], blev et hit 3-20 m vaek til
            # 'ingen adresse' (fundet i review 29-09-2026). Tag derfor det naermeste
            # BRUGBARE husnummer inden for boksens radius - _mini bevarer raekkefoelgen.
            inden = [n for n in noder if afst(n) <= d]
            m = _mini(inden, pos) if inden else []
            if m:
                return m[0]
            r = afst(noder[0])
            if r > d:
                d = r * 1.001
                continue
            d *= 3
            continue
        d *= 3
    return None


def vask(betegnelse):
    """Klimadatastyrelsens Adressevask -> (kategori, adresse-dict el. None, kode, tekst).

    Erstatter DAWA's datavask. Oversættelse til DAWA's kategorier:
      1000 eksakt (også når input er en HISTORISK betegnelse; svaret er den aktuelle),
      800/700 første/sidste husnummer i et interval                      -> 'A'
      900 vejnavnet tilnærmet (stavevariant), eksakt husnr og postnr    -> 'B'
      negative koder: findes ikke / flertydigt / postnr mangler         -> 'C'
    FORSKEL fra DAWA: ved 'C' er der INGEN "bedste bud" - vasken svarer kun ved
    præcis ét match. Og en NEDLAGT adresse (fx Industrivej 1B, Frederiksværk) gav
    i DAWA et hit med status 2; vasken afviser den (-700). Det er en forbedring.
    kategori None = tjenesten svarede ikke (ikke det samme som en dårlig adresse)."""
    try:
        j = _get(AV_URL + '/vask/?' + urllib.parse.urlencode({'token': AV_TOKEN, 'adresse': betegnelse}))
    except DawaNede:
        return None, None, None, 'tjenesten svarede ikke'
    if j is None:
        # 400/404: vasken afviste selve inputtet (fx for langt). Det er et svar, ikke et
        # udfald - et nyt forsoeg giver det samme. Ikke bekraeftet = 'C'.
        return 'C', None, None, 'Adressevasken afviste inputtet (HTTP 400/404)'
    vs = j.get('vaskestatus') or {}
    kode, tekst = vs.get('kode'), vs.get('tekst') or ''
    if kode is None:
        return None, None, None, 'uventet svar fra Adressevask'
    kat = 'A' if kode in (1000, 800, 700) else 'B' if kode == 900 else 'C'
    r = (j or {}).get('vaskeresultat') or {}
    a = None
    if kode > 0 and r and (str(r.get('status')) not in ('2', '3') or r.get('virkningtil')):
        # Vasken kan svare 1000 med en NEDLAGT (4) eller henlagt (5) adresseversion,
        # eller en version med virkningtil. Dens id giver 404 i opslaget, og afstands-
        # tjekket forsvandt tavst for ~97 raekker - bl.a. Clever Herning Centret, 301 m
        # fra adressen (review 29-09-2026). Slaa husnummeret op direkte i stedet; findes
        # det ikke, er adressen ikke bekraeftet ('C').
        try:
            h = _husnummer_opslag(betegnelse)
        except DawaNede:
            return None, None, kode, 'husnummer-opslaget svarede ikke'
        if h and h[0] == 'A':
            return 'A', h[1], kode, f'{tekst} (vaskens version var ikke aktuel; husnummeret findes)'
        return 'C', (h[1] if h and _ligner(split_street(betegnelse)[0], h[1].get('vejnavn')) else None), \
            kode, f'vasken fandt kun en ikke-aktuel adresseversion (status {r.get("status")})'
    if r.get('adressebetegnelse'):
        vej, hn = split_street(r['adressebetegnelse'])
        m = re.search(r',\s*(\d{4})\s+([^,]+)$', r['adressebetegnelse'])
        a = {'vejnavn': vej, 'husnr': hn, 'postnr': m.group(1) if m else None,
             'postnrnavn': m.group(2).strip() if m else None,
             'betegnelse': r['adressebetegnelse'], 'id': r.get('adresse_id_lokalid'),
             'slags': 'adresse', 'status': r.get('status'), 'kode': kode,
             'historisk': ((j.get('vaskeresultat_historisk') or {}).get('adressebetegnelse'))}
    elif kode in (-500, -600):
        # "Sidedør/Etage findes ikke på adresse på husnummer": vasken arbejder paa
        # ENHEDER (etage/doer), DAWA's datavask paa HUSNUMRE. Har et husnummer kun
        # adresser med etage ("st."), afviser vasken input uden etage - selv om
        # husnummeret findes. Maalt 29-09-2026: 11 af 600 raekker faldt fra A til C
        # alene af den grund. Slaa husnummeret op direkte i stedet.
        # Et UDFALD i opslaget maa ikke blive til 'C': for OK/Tesla er C en HAARD fejl.
        # Returnér None, saa validate.py genforsoeger og til sidst melder KOERSELSFEJL.
        try:
            h = _husnummer_opslag(betegnelse)
        except DawaNede:
            return None, None, kode, 'husnummer-opslaget svarede ikke'
        if h:
            kat, a, tekst = h[0], h[1], f'{tekst} - husnummeret findes'
    elif kode < 0:
        # DAWA gav ved kategori C et "bedste bud", og validate.py regnede C med SAMME
        # husnr og postnr som en stavevariant af vejnavnet ("Frederik d. 7's gade 40")
        # - INFO, ikke et tjek-punkt. Vasken giver intet bud, saa 105 harmloese
        # stavevarianter blev til tjek-punkter (maalt 29-09-2026). Adressevaelgerens
        # FONETISKE vejnavnssoegning med eksakt husnr+postnr genskaber buddet.
        # Er buddet et EKSAKT match paa vejnavn, husnr og postnr, findes adressen - saa
        # tog vasken fejl: 'Kastrup Tvaervej E 2' gav -1000 "Tekst kan ikke genkendes",
        # fordi bogstavet i vejnavnet forvirrer den (7 raekker, maalt 29-09-2026).
        # Ellers forbliver kategorien 'C' - det er kun et bud. Ogsaa her: et udfald maa
        # ikke blive til et C UDEN bud, for saa bliver en stavevariant en haard fejl for
        # OK/Tesla.
        try:
            h = _husnummer_opslag(betegnelse)
        except DawaNede:
            return None, None, kode, 'husnummer-opslaget svarede ikke'
        if h and h[0] == 'A':
            kat, a, tekst = 'A', h[1], f'{tekst} - men husnummeret findes'
        elif h and _ligner(split_street(betegnelse)[0], h[1].get('vejnavn')):
            # Kun et bud paa en vej der LIGNER inputtets. Den fonetiske soegning gav
            # 'Thorningvej 2' for 'Torvet 2, 8620' (findes ikke), og validate.py
            # regnede det som en stavevariant - saa forsvandt et tjek-punkt, og for
            # OK/Tesla ville en haard fejl vaere skjult (review 29-09-2026).
            a = h[1]
    return kat, a, kode, tekst


_FORK = (('gl', 'gammel'), ('ndr', 'nordre'), ('sdr', 'sondre'), ('nr', 'norre'), ('st', 'store'),
         ('ll', 'lille'), ('kgs', 'kongens'), ('chr', 'christian'), ('fr', 'frederik'),
         ('skt', 'sankt'), ('sct', 'sankt'), ('blvd', 'boulevard'), ('pl', 'plads'), ('alle', 'alle'))


def _ligner(a, b, graense=0.8):
    """Er to vejnavne stavevarianter af hinanden ('Ndr. Fasanvej'/'Nordre Fasanvej',
    'Romalt Blvd.'/'Romalt Boulevard') - ikke to forskellige veje ('Torvet'/'Thorningvej')?"""
    import difflib, unicodedata
    def n(s):
        s = unicodedata.normalize('NFKD', (s or '').lower())
        s = ''.join(c for c in s if not unicodedata.combining(c))
        s = s.replace('æ', 'ae').replace('ø', 'oe').replace('å', 'aa')
        ord_ = re.findall(r'[a-z0-9]+', s)
        fork = dict(_FORK)
        return ''.join(fork.get(w, w) for w in ord_)
    x, y = n(a), n(b)
    return bool(x and y) and (x == y or difflib.SequenceMatcher(None, x, y).ratio() >= graense)


def _husnummer_opslag(betegnelse):
    """Adressevaelgerens husnummer-soegning med vejnavn/husnummer/postnummer.
    -> ('A'|'B', adresse-dict) hvis PRAECIS ét husnummer matcher husnr og postnr, el. None.
    Rejser DawaNede hvis Adressevaelgeren ikke svarede - kalderen skal kunne se forskel."""
    vej, hn = split_street(betegnelse)
    m = re.search(r'(?:^|,)\s*(\d{4})\b', betegnelse)
    # Adressevaelgeren afviser vejnavne over 40 og husnumre over 4 tegn med 400.
    if not (vej and hn and m) or len(vej) > 40 or len(hn) > 4:
        return None
    j = _get(AV_URL + '/husnumre/soeg?' + urllib.parse.urlencode(
        {'token': AV_TOKEN, 'maksimum': 5, 'vejnavn': vej, 'husnummer': hn, 'postnummer': m.group(1)}))
    fund = [f for f in (j or {}).get('fund') or [] if f.get('type') == 'husnummer'
            and str(f.get('husnummer', '')).lower() == hn.lower()
            and re.search(r',\s*' + m.group(1) + r'\b', f.get('titel') or '')]
    # Soegningen er FONETISK og giver ogsaa veje der blot lyder ens: 'Store Torv 17'
    # gav baade Store Torv 17 og Store Torvegade 17 (maalt 29-09-2026). Krav om
    # praecis ét traef afviste saa et husnummer der findes. Et EKSAKT vejnavn vinder.
    eksakt = [f for f in fund if (f.get('vejnavn') or '').lower() == vej.lower()]
    if len(eksakt) == 1:
        f = eksakt[0]
    elif len(fund) == 1:
        f = fund[0]
    else:
        return None
    mm = re.search(r',\s*(\d{4})\s+([^,]+)$', f.get('titel') or '')
    a = {'vejnavn': f.get('vejnavn'), 'husnr': f.get('husnummer'),
         'postnr': mm.group(1) if mm else m.group(1), 'postnrnavn': mm.group(2).strip() if mm else None,
         'betegnelse': f.get('titel'), 'id': f.get('id'), 'slags': 'husnummer', 'status': None,
         'historisk': None}
    return ('A' if (f.get('vejnavn') or '').lower() == vej.lower() else 'B'), a


def adresse_punkt(adresse_id, slags='adresse'):
    """Adressevælgerens id-opslag -> (lat, lon) for adgangspunktet el. None.
    slags = 'adresse' (id fra vask) eller 'husnummer' (id fra husnummer-søgning).
    Ét kald i stedet for at hente hele vejen og lede efter husnummeret."""
    if not adresse_id:
        return None
    key = ('pkt', slags, adresse_id)
    if key in _cache:
        return _cache[key]
    try:
        if slags == 'husnummer':
            j = _get(f'{AV_URL}/husnumre/{urllib.parse.quote(adresse_id)}?token={AV_TOKEN}')
            h = (j or {}).get('husnummer') or {}
        else:
            j = _get(f'{AV_URL}/adresser/{urllib.parse.quote(adresse_id)}?token={AV_TOKEN}')
            h = ((j or {}).get('adresse') or {}).get('husnummer') or {}
    except DawaNede:
        return None
    k = (h.get('adgangspunkt') or {}).get('koordinater') or {}
    if k.get('x') is None or k.get('y') is None:
        return None
    v = utm32_til_wgs84(float(k['x']), float(k['y']))
    _cache[key] = v
    return v


def hav(lat1, lon1, lat2, lon2):
    R = 6371000.0
    r = math.pi / 180
    x = (lat2 - lat1) * r
    y = (lon2 - lon1) * r
    return 2 * R * math.asin(math.sqrt(
        math.sin(x / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin(y / 2) ** 2))


def _rec(j):
    """DAWA-mini -> (vejnavn, husnr, postnr, by, lat, lon)"""
    return (j.get('vejnavn'), j.get('husnr'), str(j.get('postnr')), j.get('postnrnavn'),
            float(j['y']), float(j['x']))


def reverse(lat, lon):
    """Nærmeste adgangsadresse til koordinaten. -> (vejnavn, husnr, postnr, by) el. None."""
    r = reverse_full(lat, lon)
    return r[:4] if r else None


def reverse_full(lat, lon):
    """Som reverse(), men med adressens egne koordinater. -> 6-tuple el. None."""
    key = ('rev', round(float(lat), 6), round(float(lon), 6))
    if key in _cache:
        return _cache[key]
    j = _reverse_dar(lat, lon)
    v = _rec(j) if j else None
    if v:
        _cache[key] = v          # cache ikke fejl — næste kald skal have en ny chance
    return v


def on_street(vejnavn, postnr=None, per_side=1000, max_sider=6):
    """ALLE adgangsadresser på en vej (evt. afgrænset til ét postnr). -> liste af 6-tupler.

    v2.2: paginerer. v2.1 hentede kun per_side=200, og DAWA sorterer stigende efter
    husnummer — så "nærmeste husnr på vejen" blev valgt blandt de 200 LAVESTE.
    På Søndergade i 9900 (387 adresser) gav det Søndergade 121 (1.295 m) i stedet for
    250A (15 m)."""
    if not vejnavn:
        return []
    key = ('street', vejnavn.lower(), postnr)
    if key in _cache:
        return _cache[key]
    out, side = [], 1
    while side <= max_sider:
        kw = {'vejnavn': vejnavn, 'per_side': per_side, 'side': side}
        if postnr:
            kw['postnr'] = postnr
        j = _q(**kw)
        if not j:
            break
        out += [_rec(x) for x in j]
        if len(j) < per_side:
            break
        side += 1
    if out:
        _cache[key] = out
    return out


def lookup(vejnavn, husnr, postnr):
    """Findes vej+husnr i postnummeret? -> (vejnavn, husnr) el. None.

    v2: INGEN fallback. Returnerer None hvis husnummeret ikke findes — så kalderen
    kan se forskel på et verificeret hit og et gæt. Det var netop den forskel v1
    slørede."""
    if not (vejnavn and husnr and postnr):
        return None
    key = ('fwd', vejnavn.lower(), husnr.lower(), postnr)
    if key in _cache:
        return _cache[key]
    j = _q(vejnavn=vejnavn, husnr=husnr, postnr=postnr, per_side=1)
    v = (j[0].get('vejnavn'), j[0].get('husnr')) if j else None
    if v:
        _cache[key] = v
    return v


def _loose(s):
    s = (s or '').lower()
    for a, b in (('æ', 'ae'), ('ø', 'oe'), ('å', 'aa')):
        s = s.replace(a, b)
    return re.sub(r'[^a-z0-9]', '', s)


# Etage- og lokaleangivelser der kan staa efter husnummeret. Dansk adressepraksis:
# "st." (stuen), "kl."/"kld." (kaelder), "1."/"2." (etage), "th"/"tv"/"mf" (doer).
_ETAGE = re.compile(r'^(?:st|stuen|kl|kld|kaelder|kælder|\d{1,2})\.?\s*'
                    r'(?:th|tv|mf|mfl|[a-zæøå]{1,3})?\.?$', re.I)


def _husnr_i(seg):
    """-> (vej, husnr) hvis segmentet ender paa et husnummer, ellers None."""
    s = re.sub(r'[\s,-]+$', '', (seg or '').strip())
    m = re.match(r'^(.*?)[\s,]+(\d+)\s*-\s*\d*\s*([A-Za-zÆØÅæøå]?)$', s)
    if m:
        return m.group(1).strip(), (m.group(2) + m.group(3)).strip()
    m = re.match(r'^(.*?)[\s,]+(\d+\s*[A-Za-zÆØÅæøå]?)$', s)
    return (m.group(1).strip(), m.group(2).replace(' ', '')) if m else None


def split_street(adr):
    """'Hobrovej 452, 9200 Aalborg SV' -> ('Hobrovej', '452')

    Håndterer også OK-API'ets efterhængte bindestreg ('Bredgade 2-' -> '2') og
    husnummer-intervaller ('Kystvejen 10-12' -> '10').

    v2.4: kildernes adresser har ofte en etage- eller lokaleangivelse efter
    husnummeret ("Lyngbyvej 38, st."), eller et center-/bydelsnavn som ekstra led
    ("Ishøj Nørregade 12, Ishøj Bycenter"). v2.3 fjernede kun det SIDSTE komma-led
    (postnr+by), saa "Frederiksberggade 1A st." blev hele vejnavnet og husnummeret
    tomt — 462 af 7.832 retailraekker. Uden husnummer falder normalize_one_ex
    igennem til reverse-adressen, saa kildens eget husnummer gaar tabt i stilhed.
    Nu proeves hvert komma-led fra venstre, og etage-led springes over."""
    s = (adr or '').strip()
    # fjern postnr+by til sidst ("..., 9200 Aalborg SV")
    s = re.sub(r',\s*\d{4}\b[^,]*$', '', s).strip()
    led = [p.strip() for p in s.split(',') if p.strip()]
    for i, seg in enumerate(led):
        # et led der KUN er en etageangivelse er ikke en adresse
        if _ETAGE.match(seg):
            continue
        h = _husnr_i(seg)
        if h:
            return h
        # "Thorshavnsgade 28 st. tv." — husnummeret staar inde i leddet
        u = re.sub(r'\s+(?:st|stuen|kl|kld|kælder)\.?(?:\s+(?:th|tv|mf)\.?)?$', '', seg, flags=re.I)
        u = re.sub(r'\s+\d{1,2}\.(?:\s+(?:th|tv|mf)\.?)?$', '', u)
        if u != seg:
            h = _husnr_i(u)
            if h:
                return h
    return (led[0] if led else s, '')


def _nearest(cands, lat, lon):
    return min(((hav(lat, lon, c[4], c[5]), c) for c in cands), default=(None, None))


def _base(husnr):
    """'75A' -> '75'. Bruges til at se om to husnumre er samme adressefamilie/grund."""
    m = re.match(r'^(\d+)', (husnr or '').strip())
    return m.group(1) if m else ''


def _same_family(a, b):
    """75 vs 75A, 1B vs 1E, 97 vs 97E = samme grund. 13 vs 3A = ikke."""
    ba, bb = _base(a), _base(b)
    return bool(ba) and ba == bb


def _bbr_bygning(lat, lon, anvendelse):
    """Adressen paa den naermeste BBR-bygning med den anvendelse (fx '325' =
    tankstation) inden for BYGNING_M af koordinaten -> 6-tupel som reverse_full, el.
    None. Rejser DawaNede ved udfald - et BBR-udfald maa ikke ligne 'ingen bygning'.

    BBR er det officielle bygningsregister: bygningen peger selv paa sit husnummer i
    DAR. Maalt 30-09-2026 paa de 53 OK/Tesla-raekker der fik ny adresse med v3.1:
    hvor der stod en tankstationsbygning, havde v3.0 bygningens adresse i 0 tilfaelde
    og v3.1 i 34. 12 af dem kan kun BBR afgoere, fx Kastrup: OK skrev 'Løjtegårdsvej
    1', som ikke findes; adressen ved koordinaten er Spentrup Alle 5, bygningens er
    Amager Landevej 196."""
    key = ('bbr', anvendelse, round(float(lat), 6), round(float(lon), 6))
    if key in _cache:
        return _cache[key]
    E, N = wgs84_til_utm32(lat, lon)
    d = BYGNING_M
    wkt = f'POLYGON(({E-d} {N-d},{E+d} {N-d},{E+d} {N+d},{E-d} {N+d},{E-d} {N-d}))'
    noder = _gql(f'{{ BBR_Bygning(first:100, {_tid()}, where:{{byg404Koordinat:{{intersects:'
                 f'{{wkt:"{wkt}", crs:25832}}}}, byg021BygningensAnvendelse:{{eq:"{anvendelse}"}}}}) '
                 f'{{ nodes {{ husnummer status byg404Koordinat{{wkt}} }} }} }}', base=BBR_URL)['BBR_Bygning']['nodes']
    kand = []
    for b in noder:
        xy = _xy((b.get('byg404Koordinat') or {}).get('wkt'))
        # 6 = opført, 7 = gældende. Nedrevne (10), fejlregistrerede (11) og henlagte
        # (14) bygninger staar stadig i registret.
        if not xy or not b.get('husnummer') or str(b.get('status')) not in ('6', '7'):
            continue
        dd = hav(lat, lon, *utm32_til_wgs84(*xy))
        if dd <= BYGNING_M:
            kand.append((dd, b['husnummer']))
    v = None
    for dd, hid in sorted(kand):
        m = _mini(_alle('DAR_Husnummer', f'{{id_lokalId:{{in:{json.dumps([hid])}}}, status:{{in:{AKTIV}}}}}', HF))
        if m:
            v = _rec(m[0])
            break
    _cache[key] = v
    return v


def normalize_one(adr, postnr, by, lat, lon, bygning=None):
    """-> (adresse, postnr, by). Koordinaten afgør; se modulets docstring."""
    return normalize_one_ex(adr, postnr, by, lat, lon, bygning)[:3]


def normalize_one_ex(adr, postnr, by, lat, lon, bygning=None):
    """Som normalize_one, men returnerer også om DAWA svarede.
    -> (adresse, postnr, by, status) hvor status er
       'ok' | 'dawa-nede' | 'ingen-koordinat' | 'ingen-adresse' (intet inden for 3,3 km)

    v2.2: normalize_rows kaldte tidligere reverse_full EN GANG MERE for at afgøre
    om DAWA svarede. Lykkedes det andet kald hvor det første fejlede, blev rækken
    talt som normaliseret (skipped=0) selvom den stod med kildens rå postnr — så
    refresh_data.py's afbryd-vagt fyrede ikke. Nu afgøres det i samme kald.

    bygning: en BBR-anvendelseskode ('325' = tankstation). Kan kildens adresse ikke
    bevises, bruges den bygnings adresse der staar paa koordinaten, foer reverse."""
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return adr, postnr, by, 'ingen-koordinat'
    try:
        return _normaliser(adr, postnr, by, la, lo, bygning)
    except DawaNede:
        return adr, postnr, by, 'dawa-nede'         # rør ikke rækken


def _normaliser(adr, postnr, by, la, lo, bygning=None):
    rv = reverse_full(la, lo)
    if not rv:
        # v3.0: med DAWA betød None altid "DAWA svarede ikke" - DAWA fandt ALTID en
        # adresse, også 68 km ude i havet. DAR-udgaven rejser DawaNede ved udfald og
        # giver None når der ingen adresse er inden for 3,3 km. Det er en dansk
        # kildefejl eller en udenlandsk koordinat, ikke et udfald - og de to maa ikke
        # blandes: et 'dawa-nede' faar refresh_retail til at afvise ALLE kaedens nye.
        return adr, postnr, by, 'ingen-adresse'     # rør ikke rækken
    rvej, rhusnr, rpostnr, rby, ry, rx = rv
    d_rev = hav(la, lo, ry, rx)
    vej, husnr = split_street(adr or '')

    def done(a, p, b):
        return a, p, b, 'ok'

    # 1) ingen brugbar kildeadresse -> brug reverse
    if not _loose(vej):
        return done(f"{rvej} {rhusnr}".strip() + f", {rpostnr} {rby}", rpostnr, rby)

    # 2) samme vej som reverse (blot anden stavemåde) -> kanoniser vejen,
    #    behold kildens husnr hvis det findes, ellers tag det nærmeste
    if _loose(vej) == _loose(rvej):
        street = on_street(rvej, rpostnr)
        lk = lookup(rvej, husnr, rpostnr) if husnr else None
        if lk:
            # v2.2: husnummeret FINDES, men det er ikke nok — det kan tilhøre et ANDET
            # anlæg længere nede ad vejen. OK Vordingborg stod med "Højgaardsvej 13",
            # som er IONITY's adresse 308 m væk; anlægget er nr. 3A. Undtagelsen er
            # samme adressefamilie (75 vs 75A, 97 vs 97E) — dér er bogstavet blot en
            # underadresse på samme grund, og kildens tal er det mest genkendelige.
            hit = [c for c in street if str(c[1]).lower() == husnr.lower()]
            d_src = hav(la, lo, hit[0][4], hit[0][5]) if hit else None
            if (d_src is None or _same_family(husnr, rhusnr)
                    or d_src <= max(d_rev + SLACK_M, FLOOR_M)):
                # v3.1: DAR's skrivemåde ('Vindinggård Center 1Z'), ikke kildens '1z'
                return done(f"{rvej} {lk[1]}, {rpostnr} {rby}", rpostnr, rby)
        if bygning:
            # v3.1: kildens nummer findes ikke (eller tilhører et andet anlæg). Før
            # vejens nærmeste nummer: bygningen på koordinaten. Målt 30-09-2026 på 10
            # OK-stationer, fx Allingåbro: OK skrev 'Hovedgaden 78', vejens nærmeste
            # var 107B, tankstationsbygningen i BBR er Hovedgaden 80.
            c = _bbr_bygning(la, lo, bygning)
            if c:
                return done(f"{c[0]} {c[1]}, {c[2]} {c[3]}", c[2], c[3])
        d, c = _nearest(street, la, lo)
        if c:
            return done(f"{c[0]} {c[1]}, {c[2]} {c[3]}", c[2], c[3])
        return done(f"{rvej} {rhusnr}".strip() + f", {rpostnr} {rby}", rpostnr, rby)

    # 3) ANDEN vej end reverse -> kildens adresse skal bevise sig mod koordinaten.
    #
    # v3.1 (30-09-2026): i denne rækkefølge - (a) kildens EGEN adresse, (b) BBR-
    # bygningen på koordinaten, (c) et bogstav-nummer i kildens familie tæt på,
    # (d) reverse. v2.x-v3.0 lod ALLE numre på kildens vej konkurrere på afstand,
    # så vejens nærmeste nummer vandt over kildens eget, og når kildens nummer slet
    # ikke fandtes, vandt et hvilket som helst nummer inden for 300 m. OK's API skrev
    # 30-09-2026 'Læhegnet 35' og 'Hyrdehøj Bygade 30' (ingen af dem findes i DAR);
    # rækkerne fik Læhegnet 71 og Hyrdehøj Bygade 248B, 281 og 282 m fra stationerne.
    # Målt på alle 691 OK- og 35 Tesla-rækker gav reglen 36 andre adresser end
    # kildens eller koordinatens; hvor der stod en BBR-tankstationsbygning, var v3.0's
    # adresse bygningens i 0 af 25 tilfælde (fx 'Storegade 8' for OK Broager, hvis
    # egen adresse Storegade 10 findes 52 m fra stationen).
    gate = max(d_rev + SLACK_M, FLOOR_M)
    if husnr:
        # hele landet: kildens postnr kan være forkert, og vejnavnet kan findes
        # flere steder (Tesla Herning sendte 'Merkurvej 1' — det findes i Silkeborg)
        # v3.0: per_side=1000, ikke 20. Med DAWA var 20 en paginering af DAWA's svar;
        # DAR-udgaven sorterer anderledes (postnr), saa kildens rigtige adresse faldt
        # uden for top 20: 'Engvej 1, 4500' blev til 'Vidjevej 4, 4581 Roervig'
        # (review 29-09-2026). _q henter alligevel alle traef - klipningen sparede intet.
        j = _q(vejnavn=vej, husnr=husnr, per_side=1000)
        d, c = _nearest([_rec(x) for x in (j or [])], la, lo)
        if c and d <= gate:
            return done(f"{c[0]} {c[1]}, {c[2]} {c[3]}", c[2], c[3])       # (a)
    if bygning:
        c = _bbr_bygning(la, lo, bygning)
        if c:
            return done(f"{c[0]} {c[1]}, {c[2]} {c[3]}", c[2], c[3])       # (b)
    # Hele vejen i reverse's postnr. v2.0 sprang dette over når det landsdækkende
    # opslag gav et hit langt væk, så 'Merkurvej 1' i Silkeborg blokerede for
    # Merkurvej 1A i Herning. Med et husnummer tæller kun kildens egen familie, og
    # kun omtrent lige så tæt på som reverse: 'Bredballe Byvej 7Z' findes ikke, og
    # familiens '7' lå 243 m væk, mens stationen (BBR: Bredballe Center 7Z) lå 1 m fra
    # reverse. Uden husnummer får kilden vejens nærmeste nummer inden for porten.
    street = on_street(vej, rpostnr)
    graense = gate
    if husnr:
        street = [c for c in street if _same_family(husnr, c[1])]
        graense = d_rev + SLACK_M
    d, c = _nearest(street, la, lo)
    if c and d <= graense:
        return done(f"{c[0]} {c[1]}, {c[2]} {c[3]}", c[2], c[3])           # (c)

    # 4) kilden kunne ikke bevises -> reverse vinder                          (d)
    return done(f"{rvej} {rhusnr}".strip() + f", {rpostnr} {rby}", rpostnr, rby)


def normalize_rows(rows, adr, postnr, by, lat, lon, workers=10, status_ud=None, bygning=None):
    """Normalisér CSV-rækker in-place. -> (antal ændrede, antal ikke-normaliserede)

    skipped tæller rækker hvor DAWA ikke svarede ELLER koordinaten manglede — begge
    betyder at rækken står med kildens rå adresse og altså ikke er verificeret.
    status_ud: en liste der, hvis den gives, fyldes med hver rækkes status i samme
    rækkefølge (se normalize_one_ex) - så kalderen kan skelne udfald fra
    'ingen-adresse'. bygning: BBR-anvendelseskode, se normalize_one_ex."""
    def work(r):
        return r, normalize_one_ex(r[adr], r[postnr], r[by], r[lat], r[lon], bygning)
    changed = skipped = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for r, (a, p, b, status) in ex.map(work, rows):
            if status_ud is not None:
                status_ud.append(status)
            if status != 'ok':
                skipped += 1
                continue
            if (r[adr], str(r[postnr]), r[by]) != (a, p, b):
                changed += 1
            r[adr], r[postnr], r[by] = a, p, b
    return changed, skipped
