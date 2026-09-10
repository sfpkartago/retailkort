#!/usr/bin/env python3
"""
validate.py — kvalitetskontrol af de tre datasæt (v3, præcis).
Kør: python3 validate.py

Skiller HÅRDE FEJL (lav falsk-positiv-rate) fra en TJEK-liste (mulige, kræver
manuelt/web-eftersyn). Den dybe koordinat-forskydnings-jagt ligger i det
multi-agent-workflow der byggede datasættet — denne validator holder det rent
mellem de kørsler.

HÅRDE FEJL:
  - ugyldigt postnr (findes ikke i DAWA)
  - koordinat uden for DK / (0,0) / ombyttet lat-lon / ikke-numerisk
  - samme koordinat delt af to FORSKELLIGE mærker (kryds-mærke-dublet)
  - nær-dublet: samme mærke < 30 m
  - manglende mærke / koordinat / postnr
  - superlader < 250 kW eller > 500 kW
TJEK (mulige — kan være postnummergrænse/hjørne/legitimt):
  - koordinatens postnr (reverse) != rækkens postnr, og > 150 m fra grænsen
  - koordinaten ligger på en ANDEN vej end adressen, > 300 m
INFO: kategori-nøgleord, manglende husnr (ofte legitimt), sammensat By.

v4 (2026-09-08) tilføjer to tjek, fordi v3 gav "0 hårde fejl" mens 74 rækker havde
en adresse DAWA ikke har, og mens Burger King Taastrups koordinat lå 465 m fra
rækkens egen adresse:
  ADRESSE-EKSISTENS  — findes vej+husnr overhovedet? (DAWA datavask, kategori A/B/C)
  ADRESSE vs KOORDINAT — hvor langt er der fra rækkens koordinat til dens EGEN adresse?
Se de to afsnit nederst for hvorfor kun det første kan være en hård fejl.
Alt skrives til validation_report.txt.
"""
import csv, os, math, re, json, urllib.request, urllib.parse, concurrent.futures
from collections import defaultdict
OUT=os.path.dirname(os.path.abspath(__file__))
UA={'User-Agent':'kartago-validate/3.0'}
def get(u):
    try: return json.loads(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=20).read())
    except Exception: return None
def read(fn):
    with open(os.path.join(OUT,fn),encoding='utf-8-sig') as f:
        r=list(csv.reader(f)); return r[0],r[1:]
def hav(a,b,c,d):
    R=6371000;r=math.pi/180;x=(c-a)*r;y=(d-b)*r
    return 2*R*math.asin(math.sqrt(math.sin(x/2)**2+math.cos(a*r)*math.cos(c*r)*math.sin(y/2)**2))
def loose(s):
    s=(s or '').lower().replace('æ','a').replace('ø','o').replace('å','a').replace('ae','a').replace('oe','o').replace('aa','a')
    return re.sub(r'[^a-z0-9]','',s)
def street(adr):
    sp=adr.rsplit(',',1)[0].strip() if ',' in adr else adr.strip()
    return re.sub(r'\s+\d+[A-Za-z]?$','',sp).strip()
def rev(lat,lon):
    j=get("https://api.dataforsyningen.dk/adgangsadresser/reverse?"+urllib.parse.urlencode({'x':lon,'y':lat,'struktur':'mini'}))
    if j: return str(j.get('postnr')),j.get('postnrnavn'),j.get('vejnavn'),float(j.get('y')),float(j.get('x'))
    return None,None,None,None,None

VALIDPN=set(str(p['nr']) for p in (get("https://api.dataforsyningen.dk/postnumre?struktur=mini") or []))
# fn, mærke,navn,postnr,adr,lat,lon,kW(-1)
LAYERS=[('tankstationer_dk.csv',0,1,3,2,5,6,-1),('superladere_dk.csv',0,1,3,2,8,9,5),
        ('fastfood_kaeder_dk.csv',0,1,3,2,5,6,-1),('dagligvarer_dk.csv',0,1,3,2,5,6,-1)]
report=[]
def W(m): report.append(m); print(m)
FEJL=CHK=0
for fn,mc,nc,pc,ac,latc,lonc,kwc in LAYERS:
    h,rows=read(fn); W(f"\n===== {fn} ({len(rows)} rækker) =====")
    # netværk: reverse pr. række
    def work(r):
        try: la=float(r[latc]); lo=float(r[lonc])
        except: return (r,None)
        return (r,rev(la,lo))
    rmap={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
        for r,rv in ex.map(work,rows): rmap[id(r)]=rv
    # HÅRDE FEJL
    invpn=[r for r in rows if str(r[pc]).strip() not in VALIDPN]
    geo=[]
    for r in rows:
        try: la=float(r[latc]); lo=float(r[lonc])
        except: geo.append((r,'ikke-numerisk')); continue
        if not(54.4<la<57.9 and 8.0<lo<15.4): geo.append((r,f'uden for DK ({la},{lo})'))
        elif la<lo: geo.append((r,f'ombyttet lat/lon ({la},{lo})'))
    bycoord=defaultdict(set)
    for r in rows:
        try: bycoord[(round(float(r[latc]),6),round(float(r[lonc]),6))].add(r[mc])
        except: pass
    xdup=[(k,v) for k,v in bycoord.items() if len(v)>1]
    # Naer-dublet: samme maerke under 30 m OG SAMME ADRESSE. Kravet om samme adresse
    # kom til 2026-09-10: lufthavne og banegaarde har reelt flere udsalgssteder af
    # samme kaede inden for 30 m (Lagkagehuset har 6 i CPH med hver sin adresse i
    # kaedens egen kilde, 7-Eleven flere paa Aarhus H). Uden adressekravet blev de
    # meldt som haarde fejl. Samme maerke + samme adresse + under 30 m er derimod
    # naesten altid en dublet — typisk et OSM-punkt der findes baade som node og
    # som bygnings-way.
    def _adr(r):
        return re.sub(r'\s+',' ',(r[ac] or '')).strip().lower()
    seen=defaultdict(list); ndup=[]; ndup_andet=[]
    for r in rows:
        try: la=float(r[latc]); lo=float(r[lonc])
        except: continue
        for (kla,klo,kadr) in seen[r[mc]]:
            if abs(kla-la)<0.0004 and abs(klo-lo)<0.0004 and hav(la,lo,kla,klo)<30:
                (ndup if _adr(r)==kadr else ndup_andet).append(r); break
        seen[r[mc]].append((la,lo,_adr(r)))
    miss=[r for r in rows if not r[mc].strip() or not str(r[latc]).strip() or not re.search(r'\b\d{4}\b',r[ac])]
    kwbad=[]
    if kwc!=-1:
        for r in rows:
            try: kw=float(r[kwc]); kwbad.append((r,kw)) if (kw<250 or kw>500) else None
            except: kwbad.append((r,'?'))
    nfejl=len(invpn)+len(geo)+len(xdup)+len(ndup)+len(miss)+len(kwbad); FEJL+=nfejl
    W(f"  [HÅRDE FEJL i alt: {nfejl}]")
    W(f"    ugyldigt postnr: {len(invpn)}");        [W(f"       ✗ {r[mc]} | {r[ac]}") for r in invpn[:10]]
    W(f"    geometri (uden for DK/ombyttet): {len(geo)}"); [W(f"       ✗ {r[mc]} | {r[nc]} | {m}") for r,m in geo[:10]]
    W(f"    kryds-mærke samme koordinat: {len(xdup)}");    [W(f"       ✗ {k} = {sorted(v)}") for k,v in xdup[:10]]
    W(f"    nær-dublet <30m samme mærke OG adresse: {len(ndup)}"); [W(f"       ✗ {r[mc]} | {r[ac]}") for r in ndup[:10]]
    if ndup_andet:
        W(f"    [TJEK] <30m samme mærke, ANDEN adresse (flere udsalgssteder samme sted?): {len(ndup_andet)}")
        for r in ndup_andet[:8]: W(f"       · {r[mc]} | {r[nc][:30]} | {r[ac]}")
        CHK += len(ndup_andet)
    W(f"    manglende felter: {len(miss)}");               [W(f"       ✗ {r[mc]} | {r[nc]}") for r in miss[:10]]
    if kwc!=-1: W(f"    effekt <250 el. >500 kW: {len(kwbad)}"); [W(f"       ✗ {r[mc]} | {r[nc]} = {kw} kW") for r,kw in kwbad[:10]]
    # TJEK-liste (mulige)
    pnmis=[]; disp=[]
    for r in rows:
        rv=rmap.get(id(r))
        if not rv or not rv[0]: continue
        rpn,rby,rvej,ry,rx=rv
        try: la=float(r[latc]); lo=float(r[lonc])
        except: continue
        d=hav(la,lo,ry,rx) if ry else 0
        if rpn!=str(r[pc]).strip() and d>150: pnmis.append((r,f"koord i {rpn} {rby}, {int(d)}m"))
        if rvej and loose(rvej)!=loose(street(r[ac])) and d>300:
            disp.append((r,f"koord på '{rvej}' (adresse: '{street(r[ac])}'), {int(d)}m"))
    CHK+=len(pnmis)+len(disp)
    W(f"  [TJEK — mulige, kan være grænse/hjørne/legitimt: {len(pnmis)+len(disp)}]")
    W(f"    koord i andet postnr (>150m): {len(pnmis)}");   [W(f"       · {r[mc]} | {r[ac]} | {m}") for r,m in pnmis[:15]]
    W(f"    koord på anden vej (>300m): {len(disp)}");       [W(f"       · {r[mc]} | {r[nc]} | {m}") for r,m in disp[:15]]
    # INFO
    nohus=[r for r in rows if not re.search(r'\d',r[ac].rsplit(',',1)[0])]
    cby=[r for r in rows if ',' in r[4]]
    W(f"  [INFO] uden husnr (ofte legitimt: motorvej/center/hjørne): {len(nohus)} | sammensat By: {len(cby)}")

# =====================================================================
# v4: ADRESSE-EKSISTENS + ADRESSE vs KOORDINAT
# =====================================================================
# Hvorfor datavask og ikke et almindeligt /adgangsadresser-opslag: DAWA's
# vejnavn-parameter kræver eksakt match, så "Helgeshøj Allé" (adressen staves
# "Alle"), "Gl. Hovedvej" (staves "Gl.Hovedvej") og "Nr. Virumvej" (staves
# "Nr Viumvej") gav 250 FALSKE fejl. datavask matcher fuzzy og svarer med en
# kategori: A = entydigt match, B = match efter rettelse, C = usikkert.
#
# Adressefelterne skal renses først, ellers drukner tjekket i parse-støj:
# "Næstvedvej 32, Bårse Runddel, 4720 Præstø" og "Kongensgade 51-53" er begge
# gyldige adresser, men gav kategori C rå. Efter rensning: A.
DV = "https://api.dataforsyningen.dk/datavask/adgangsadresser?"


def betegnelse(adr, postnr, by):
    """-> (betegnelse, vej, husnr) el. (None, tekst, '') hvis der ikke er noget husnr.
    Kaster mellem-segmenter (lokalitet/terminal/etage) og parentes-suffikser væk og
    tager første tal i et husnummer-interval."""
    segs = [x.strip() for x in (adr or '').split(',') if x.strip()]
    head = next((x for x in segs if re.search(r'\d', x)), segs[0] if segs else '')
    head = re.sub(r'\s*\([^)]*\)', '', head)
    m = re.match(r"^(.*?)[\s,]+(\d+)\s*(?:-\s*\d+)?\s*([A-Za-zÆØÅæøå]?)\s*$", head)
    if not m:
        return None, head, ''
    vej = m.group(1).strip(); hn = (m.group(2) + m.group(3)).strip()
    return f"{vej} {hn}, {postnr} {by}".strip(), vej, hn


def datavask(bet):
    j = get(DV + urllib.parse.urlencode({'betegnelse': bet}))
    if not j:
        return None, None
    res = j.get('resultater') or []
    return j.get('kategori'), ((res[0].get('adresse') or {}) if res else None)


_street = {}
def street_pts(vej, pn):
    """Alle adresser på en vej i et postnr, med koordinater. Cachet pr. (vej, postnr),
    og pagineret — DAWA returnerer default kun 200, sorteret efter husnummer."""
    k = ((vej or '').lower(), str(pn))
    if k in _street:
        return _street[k]
    out, side = [], 1
    while side <= 6:
        j = get("https://api.dataforsyningen.dk/adgangsadresser?" + urllib.parse.urlencode(
            {'vejnavn': vej, 'postnr': pn, 'per_side': 1000, 'side': side, 'struktur': 'mini'}))
        if not j:
            break
        out += j
        if len(j) < 1000:
            break
        side += 1
    _street[k] = out
    return out


# refresh_data.py normaliserer KUN disse mærke/lag-par mod DAWA og garanterer derfor
# at adressen findes. En uafklaret adresse dér er en HÅRD FEJL. For de øvrige mærker
# er det et kendt gap (se REFRESH_LOG.md) og havner på tjek-listen.
GARANTERET = {('tankstationer_dk.csv', 'OK'), ('superladere_dk.csv', 'Tesla')}
AFSTAND_TJEK_M = 250

W("\n" + "=" * 70)
W("ADRESSE-EKSISTENS (DAWA datavask) + ADRESSE vs KOORDINAT")
adr_fejl = 0
alle_afstande = []
for fn, mc, nc, pc, ac, latc, lonc, kwc in LAYERS:
    h, rows = read(fn)

    def job(r):
        bet, vej, hn = betegnelse(r[ac], str(r[pc]).strip(), r[4])
        if bet is None:
            return r, 'INGEN_HUSNR', None, vej, hn
        k, a = datavask(bet)
        return r, (k or 'INTET-SVAR'), a, vej, hn

    ud = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
        ud = list(ex.map(job, rows))

    cnt = defaultdict(int)
    review, staves, ingen, langt = [], [], [], []
    for r, k, a, vej, hn in ud:
        cnt[k] += 1
        if k == 'INGEN_HUSNR':
            ingen.append(r); continue
        akt = (a or {}).get('husnr')
        if k in ('A', 'B'):
            pass
        elif akt and hn and akt.lower() == hn.lower() and str((a or {}).get('postnr')) == str(r[pc]).strip():
            # kategori C, men DAWA's bedste match har SAMME husnr og postnr —
            # det er en stavevariant af vejnavnet, ikke en manglende adresse
            # ("Frederik d. 7's gade 40" -> "Fr. d. 7's Gade 40").
            staves.append((r, a)); continue
        else:
            review.append((r, k, a)); continue
        # A/B: mål afstanden fra rækkens koordinat til dens EGEN adresse
        if not a:
            continue
        pts = street_pts(a.get('vejnavn'), a.get('postnr'))
        hit = [p for p in pts if str(p.get('husnr', '')).lower() == str(a.get('husnr', '')).lower()]
        if not hit:
            continue
        try:
            d = hav(float(r[latc]), float(r[lonc]), float(hit[0]['y']), float(hit[0]['x']))
        except (ValueError, TypeError, KeyError):
            continue
        alle_afstande.append(d)
        if d > AFSTAND_TJEK_M:
            langt.append((d, r, a))

    W(f"\n  {fn}: " + " ".join(f"{k}={cnt[k]}" for k in sorted(cnt)))
    gar = [(r, k, a) for r, k, a in review if (fn, r[mc]) in GARANTERET]
    gar += [(r, 'INGEN_HUSNR', None) for r in ingen if (fn, r[mc]) in GARANTERET]
    adr_fejl += len(gar)
    W(f"    [HÅRD FEJL] uafklaret adresse i et GARANTERET lag (OK-tank/Tesla): {len(gar)}")
    for r, k, a in gar[:15]:
        W(f"       ✗ {r[mc]} | {r[nc][:30]} | {r[ac]} ({k})")
    ovr = [(r, k, a) for r, k, a in review if (fn, r[mc]) not in GARANTERET]
    W(f"    [TJEK] husnummer DAWA ikke kan bekræfte: {len(ovr)}")
    for r, k, a in ovr[:12]:
        best = f"{(a or {}).get('vejnavn')} {(a or {}).get('husnr')}" if a else '-'
        W(f"       · {r[mc]:14} {r[nc][:28]:30} {r[ac][:40]:42} DAWA's bedste: {best}")
    ovi = [r for r in ingen if (fn, r[mc]) not in GARANTERET]
    W(f"    [TJEK] intet husnummer i adressefeltet: {len(ovi)}")
    for r in ovi[:8]:
        W(f"       · {r[mc]:14} {r[nc][:28]:30} {r[ac][:44]}")
    W(f"    [TJEK] adresse mere end {AFSTAND_TJEK_M} m fra rækkens koordinat: {len(langt)}")
    for d, r, a in sorted(langt, reverse=True)[:15]:
        W(f"       · {int(d):4} m  {r[mc]:14} {r[nc][:28]:30} {r[ac][:44]}")
    W(f"    [INFO] kategori C men samme husnr (stavevariant af vejnavnet): {len(staves)}")
    CHK += len(ovr) + len(ovi) + len(langt)
FEJL += adr_fejl

if alle_afstande:
    alle_afstande.sort()
    p = lambda q: alle_afstande[min(len(alle_afstande) - 1, int(len(alle_afstande) * q))]
    W(f"\n  [INFO] afstand adresse->koordinat, {len(alle_afstande)} målte rækker: "
      f"median {p(.5):.0f} m · p90 {p(.90):.0f} · p99 {p(.99):.0f} · max {alle_afstande[-1]:.0f}")
W("""
  Hvorfor afstanden IKKE er en hård fejl: de to fjerneste rækker (Shell Express
  Hviding 449 m, Norlys Samkørselsplads Ejby 428 m) er verificeret KORREKTE — store
  grunde hvor DAWA's adressepunkt ligger langt fra selve anlægget. Og forholdet
  "egen adresse / nærmeste adresse" kan ikke skelne: Shell Hviding har 25x, mens
  Burger King Taastrups ÆGTE fejl havde 8,9x. Listen er derfor til gennemgang.
  Fejlen den ville have fanget: BK Taastrup laa 465 m fra Helgeshøj Alle 32B og var
  usynlig for v3, fordi forskydnings-tjekket kun slaar til naar reverse-VEJNAVNET
  afviger — og der var begge "Helgeshøj Alle".

  Kategori-renhed (saelger tank-raekken braendstof?) ligger i reconcile.py, ikke her:
  samplacering paa tvaers af lagene er normal — 213 par ligger inden for 150 m, fordi
  Uno-X og Circle K saelger baade braendstof og stroem samme sted. Kun operatoerens
  egen braendstofliste kan afgoere det, og den kraever netadgang.""")

W(f"\n================  HÅRDE FEJL i alt: {FEJL}  |  TJEK-punkter: {CHK}  ================")
open(os.path.join(OUT,'validation_report.txt'),'w',encoding='utf-8').write("\n".join(report))
print("\n(Rapport gemt i validation_report.txt)")
