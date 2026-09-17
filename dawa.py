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

Reglen i v2:
  1. reverse(lat,lon) giver den nærmeste adgangsadresse — den er sandhedsvidne.
  2. Er kildens vejnavn den SAMME vej som reverse's (uanset stavemåde): behold
     kildens husnr hvis det findes på vejen, ellers tag det nærmeste husnr.
  3. Er det en ANDEN vej: slå kildens adresse op i hele landet og tag den kandidat
     der ligger nærmest koordinaten — men kun hvis den er lige så tæt på som
     reverse's eget punkt (+ slæk). Ellers vinder reverse.
  4. Postnr/by følger den adresse der blev valgt.

Brug:
    from dawa import normalize_rows
    normalize_rows(rows, adr=2, postnr=3, by=4, lat=8, lon=9)   # in-place
"""
import json, math, re, time, urllib.request, urllib.parse, concurrent.futures

UA = {'User-Agent': 'kartago-dawa/2.2'}
BASE = 'https://api.dataforsyningen.dk/adgangsadresser'
# Et anlægs EGEN adresse ligger inden for et par hundrede meter af anlægget — et
# stort motorvejs- eller centeranlæg kan strække sig så langt. Ligger kildens adresse
# længere væk, beskriver kilden et ANDET sted (Tesla Odense: 444 m, det gamle anlæg;
# Tesla Ikast: 1.813 m). Grænsen er derfor sat på anlægs-udstrækning, ikke på et
# enkelt datapunkt. Hobrovej 452 (Aalborg Storcenter, 289 m) er inden for — rækken
# ender dog på 452C, fordi det er det nærmeste husnummer på vejen (35 m).
SLACK_M = 150     # ud over reverse's eget punkt
FLOOR_M = 300     # ... men altid mindst så meget
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
        except Exception:
            if i + 1 < tries:
                time.sleep(1.5 * (i + 1))
    raise DawaNede(url)


def _q(**kw):
    return _get(BASE + '?' + urllib.parse.urlencode({**kw, 'struktur': 'mini'}))


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
    j = _get(BASE + '/reverse?' + urllib.parse.urlencode({'x': lon, 'y': lat, 'struktur': 'mini'}))
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


def normalize_one(adr, postnr, by, lat, lon):
    """-> (adresse, postnr, by). Koordinaten afgør; se modulets docstring."""
    return normalize_one_ex(adr, postnr, by, lat, lon)[:3]


def normalize_one_ex(adr, postnr, by, lat, lon):
    """Som normalize_one, men returnerer også om DAWA svarede.
    -> (adresse, postnr, by, status) hvor status er
       'ok' | 'dawa-nede' | 'ingen-koordinat'

    v2.2: normalize_rows kaldte tidligere reverse_full EN GANG MERE for at afgøre
    om DAWA svarede. Lykkedes det andet kald hvor det første fejlede, blev rækken
    talt som normaliseret (skipped=0) selvom den stod med kildens rå postnr — så
    refresh_data.py's afbryd-vagt fyrede ikke. Nu afgøres det i samme kald."""
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return adr, postnr, by, 'ingen-koordinat'
    try:
        return _normaliser(adr, postnr, by, la, lo)
    except DawaNede:
        return adr, postnr, by, 'dawa-nede'         # rør ikke rækken


def _normaliser(adr, postnr, by, la, lo):
    rv = reverse_full(la, lo)
    if not rv:
        return adr, postnr, by, 'dawa-nede'         # rør ikke rækken
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
        if husnr and lookup(rvej, husnr, rpostnr):
            # v2.2: husnummeret FINDES, men det er ikke nok — det kan tilhøre et ANDET
            # anlæg længere nede ad vejen. OK Vordingborg stod med "Højgaardsvej 13",
            # som er IONITY's adresse 308 m væk; anlægget er nr. 3A. Undtagelsen er
            # samme adressefamilie (75 vs 75A, 97 vs 97E) — dér er bogstavet blot en
            # underadresse på samme grund, og kildens tal er det mest genkendelige.
            hit = [c for c in street if str(c[1]).lower() == husnr.lower()]
            d_src = hav(la, lo, hit[0][4], hit[0][5]) if hit else None
            if (d_src is None or _same_family(husnr, rhusnr)
                    or d_src <= max(d_rev + SLACK_M, FLOOR_M)):
                return done(f"{rvej} {husnr}, {rpostnr} {rby}", rpostnr, rby)
        d, c = _nearest(street, la, lo)
        if c:
            return done(f"{c[0]} {c[1]}, {c[2]} {c[3]}", c[2], c[3])
        return done(f"{rvej} {rhusnr}".strip() + f", {rpostnr} {rby}", rpostnr, rby)

    # 3) ANDEN vej end reverse -> kildens adresse skal bevise sig mod koordinaten
    gate = max(d_rev + SLACK_M, FLOOR_M)
    cands = []
    if husnr:
        # hele landet: kildens postnr kan være forkert, og vejnavnet kan findes
        # flere steder (Tesla Herning sendte 'Merkurvej 1' — det findes i Silkeborg)
        j = _q(vejnavn=vej, husnr=husnr, per_side=20)
        cands += [_rec(x) for x in (j or [])]
    # ALTID også hele vejen i reverse's postnr. v2.0 sprang dette over når det
    # landsdækkende opslag gav et hit langt væk, så 'Merkurvej 1' i Silkeborg
    # blokerede for Merkurvej 1A i Herning.
    cands += on_street(vej, rpostnr)
    d, c = _nearest(cands, la, lo)
    if c and d <= gate:
        return done(f"{c[0]} {c[1]}, {c[2]} {c[3]}", c[2], c[3])

    # 4) kilden kunne ikke bevises -> reverse vinder
    return done(f"{rvej} {rhusnr}".strip() + f", {rpostnr} {rby}", rpostnr, rby)


def normalize_rows(rows, adr, postnr, by, lat, lon, workers=10):
    """Normalisér CSV-rækker in-place. -> (antal ændrede, antal ikke-normaliserede)

    skipped tæller rækker hvor DAWA ikke svarede ELLER koordinaten manglede — begge
    betyder at rækken står med kildens rå adresse og altså ikke er verificeret."""
    def work(r):
        return r, normalize_one_ex(r[adr], r[postnr], r[by], r[lat], r[lon])
    changed = skipped = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for r, (a, p, b, status) in ex.map(work, rows):
            if status != 'ok':
                skipped += 1
                continue
            if (r[adr], str(r[postnr]), r[by]) != (a, p, b):
                changed += 1
            r[adr], r[postnr], r[by] = a, p, b
    return changed, skipped
