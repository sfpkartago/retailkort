#!/usr/bin/env python3
"""
validate.py — kvalitetskontrol af de tre datasæt (v3, præcis).
Kør: python3 validate.py

Skiller HÅRDE FEJL (lav falsk-positiv-rate) fra en TJEK-liste (mulige, kræver
manuelt/web-eftersyn). Den dybe koordinat-forskydnings-jagt ligger i det
multi-agent-workflow der byggede datasættet — denne validator holder det rent
mellem de kørsler.

HÅRDE FEJL:
  - ugyldigt postnr (findes ikke i DAR - Danmarks Adresseregister)
  - koordinat uden for DK / (0,0) / ombyttet lat-lon / ikke-numerisk
  - samme koordinat delt af to FORSKELLIGE mærker (kryds-mærke-dublet)
  - nær-dublet: samme mærke, samme adresse OG samme navn < 30 m
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

v5.0 (29-09-2026): DAWA lukker 1. oktober 2026. Reverse og postnumre går nu mod DAR
via dawa.py (Datafordeleren; kræver DATAFORDELER_API_KEY), og adresse-eksistens mod
Klimadatastyrelsens Adressevask. Vasken svarer KUN ved præcis ét match, så DAWA's
kategorier oversættes i dawa.vask(): 1000/800/700 = A, 900 = B (vejnavn rettet),
negative koder = C (findes ikke). Der er ikke længere et "bedste bud" ved C - i
stedet vises vaskens egen grund ("Husnummer eksisterer ikke på vejen"). Afstanden
fra rækkens koordinat til dens egen adresse måles nu med ét id-opslag i
Adressevælgeren i stedet for at hente hele vejen.
"""
import csv, os, math, re, json, time, urllib.request, urllib.parse, concurrent.futures, unicodedata
from collections import defaultdict
from dawa import reverse_full, postnumre, vask, adresse_punkt, lookup, DawaNede, _ligner as ligner
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
    """-> (postnr, by, vejnavn, lat, lon). Alle None = opslaget fejlede (udfald).
    'INGEN' i foerste felt = ingen dansk adresse inden for 3,3 km af koordinaten -
    en datafejl, ikke et udfald (DAWA fandt altid en adresse, DAR-udgaven stopper)."""
    try: j=reverse_full(lat,lon)
    except DawaNede: return None,None,None,None,None
    if j is None: return 'INGEN',None,None,None,None
    return str(j[2]),j[3],j[0],float(j[4]),float(j[5])

# Maa IKKE falde tilbage til en tom maengde: saa blev hver eneste raekke en haard
# 'ugyldigt postnr'-fejl, hvis opslaget fejlede. postnumre() rejser i stedet.
VALIDPN=set(postnumre())
assert len(VALIDPN) > 500, f'kun {len(VALIDPN)} postnumre fra DAR'
# Kryds-maerke samme koordinat er en HAARD fejl for braendstof og ladere: to maerker
# kan ikke drive samme pumpe eller lader, saa det betyder dublet eller forkert
# brand-attribution. For DETAILHANDEL er det derimod normalt — et butikscenter har
# mange butikker paa samme adresse, og flere kaeder oplyser centrets koordinat frem
# for butikkens egen. Rosengaardcentret gav saaledes Apotek + Synoptik + Matas +
# Sport 24 paa samme punkt. Der er det et tjek-punkt, ikke en fejl.
XDUP_HAARD = {'tankstationer_dk.csv', 'superladere_dk.csv'}

# fn, mærke,navn,postnr,adr,lat,lon,kW(-1)
LAYERS=[('tankstationer_dk.csv',0,1,3,2,5,6,-1),('superladere_dk.csv',0,1,3,2,8,9,5),
        ('fastfood_kaeder_dk.csv',0,1,3,2,5,6,-1),('dagligvarer_dk.csv',0,1,3,2,5,6,-1),
        ('udvalgsvarer_dk.csv',0,1,3,2,5,6,-1),('pladskraevende_dk.csv',0,1,3,2,5,6,-1)]
import datetime as _dt
report=[]
def W(m): report.append(m); print(m)
# Rapporten bar ingen dato. Faldt koerslen ud i Action'en, blev den gamle fil
# liggende og saa fuldstaendig ud som en frisk, ren kontrol.
W(f"Kvalitetskontrol koert {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')} "
  f"(validate.py v5.0)")
UDEBLEV = []   # (fil, antal, i alt) for koersler hvor DAWA ikke svarede

# Postnummerets officielle bynavn — By-kolonnen holdes op mod det.
try:
    POSTNR = postnumre()
except Exception:
    POSTNR = {}
if not POSTNR:
    print("  ⚠ kunne ikke hente postnummerregistret — By-tjekket springes over")
FEJL=CHK=0
for fn,mc,nc,pc,ac,latc,lonc,kwc in LAYERS:
    h,rows=read(fn); W(f"\n===== {fn} ({len(rows)} rækker) =====")
    # netværk: reverse pr. række
    def work(r):
        try: la=float(r[latc]); lo=float(r[lonc])
        except: return (r,None)
        return (r,rev(la,lo))
    rmap={}
    # 24 traade: DAR-reverse gav 41/s ved 15 og 57/s ved 30 (maalt 29-09-2026).
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as ex:
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
    xdup_alle=[(k,v) for k,v in bycoord.items() if len(v)>1]
    xdup = xdup_alle if fn in XDUP_HAARD else []
    xdup_tjek = [] if fn in XDUP_HAARD else xdup_alle
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
        for (kla,klo,kadr,knavn) in seen[r[mc]]:
            if abs(kla-la)<0.0004 and abs(klo-lo)<0.0004 and hav(la,lo,kla,klo)<30:
                # v4.1: samme adresse er ikke nok. Noerreport har TRE 7-Eleven-kiosker
                # (Perron, 3 Syd, 4 Nord) og Koebenhavn H tre Minibarer — de faar alle
                # samme gadeadresse af DAWA, men er forskellige udsalgssteder. Kun naar
                # ogsaa NAVNET er ens, er det en dublet.
                samme_navn = (r[nc] or '').strip().lower() == (knavn or '').strip().lower()
                (ndup if (_adr(r)==kadr and samme_navn) else ndup_andet).append(r); break
        seen[r[mc]].append((la,lo,_adr(r),r[nc]))
    # v4.1: to maerker der kun adskiller sig ved versaler, bindestreg, apostrof eller
    # mellemrum er naesten altid samme kaede skrevet to gange ("Andersen biler" /
    # "Andersen Biler"). De splitter signaturforklaringen og maerkefilteret.
    def _mk(s):
        return re.sub(r'[^a-z0-9]', '',
                      unicodedata.normalize('NFKD', (s or '').lower())
                      .encode('ascii', 'ignore').decode())
    _mgrp = defaultdict(set)
    for r in rows:
        _mgrp[_mk(r[mc])].add(r[mc])
    mvar = [sorted(v) for v in _mgrp.values() if len(v) > 1]
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
    if xdup_tjek:
        W(f"    [TJEK] flere mærker på samme koordinat (butikscenter?): {len(xdup_tjek)}")
        for k,v in xdup_tjek[:8]: W(f"       · {k} = {sorted(v)}")
        CHK += len(xdup_tjek)
    W(f"    nær-dublet <30m samme mærke, adresse OG navn: {len(ndup)}"); [W(f"       ✗ {r[mc]} | {r[ac]}") for r in ndup[:10]]
    if ndup_andet:
        W(f"    [TJEK] <30m samme mærke, ANDEN adresse (flere udsalgssteder samme sted?): {len(ndup_andet)}")
        for r in ndup_andet[:8]: W(f"       · {r[mc]} | {r[nc][:30]} | {r[ac]}")
        CHK += len(ndup_andet)
    W(f"    manglende felter: {len(miss)}")
    if mvar:
        W(f"    [TJEK] mærker der kun adskiller sig ved tegnsætning/versaler: {len(mvar)}")
        for v in mvar[:8]: W(f"       · {v}")
        CHK += len(mvar);               [W(f"       ✗ {r[mc]} | {r[nc]}") for r in miss[:10]]
    if kwc!=-1: W(f"    effekt <250 el. >500 kW: {len(kwbad)}"); [W(f"       ✗ {r[mc]} | {r[nc]} = {kw} kW") for r,kw in kwbad[:10]]
    # TJEK-liste (mulige)
    pnmis=[]; disp=[]
    # v4.1: raekker hvor reverse-kaldet ikke svarede blev foer sprunget over TAVST.
    # Faldt DAWA ud for halvdelen af raekkerne, blev TJEK-tallene for postnr og
    # forskudt vej kunstigt lave — en koerselsfejl saa ud som rene data.
    fase1_udeblev=[r for r in rows
                   if (lambda v: not v or not v[0])(rmap.get(id(r)))
                   and str(r[latc]).strip() and str(r[lonc]).strip()]
    ingen_adr=[r for r in rows if (rmap.get(id(r)) or [None])[0]=='INGEN']
    for r in rows:
        rv=rmap.get(id(r))
        if not rv or not rv[0] or rv[0]=='INGEN': continue
        rpn,rby,rvej,ry,rx=rv
        try: la=float(r[latc]); lo=float(r[lonc])
        except: continue
        d=hav(la,lo,ry,rx) if ry else 0
        # v4.1: betingelsen d>150 slog tjekket FRA i netop de tilfaelde hvor det
        # betyder noget — er postnummeret forkert og koordinatet rigtigt, ligger
        # koordinatet 0-35 m fra den rigtige adresse, og fejlen slap igennem.
        if rpn!=str(r[pc]).strip(): pnmis.append((r,f"koord i {rpn} {rby}, {int(d)}m"))
        if rvej and loose(rvej)!=loose(street(r[ac])) and d>300:
            disp.append((r,f"koord på '{rvej}' (adresse: '{street(r[ac])}'), {int(d)}m"))
    # v4.1: By-kolonnen blev aldrig tjekket af nogen kontrol. 201 raekker havde et
    # andet bynavn end postnummerets officielle — de fleste harmloese varianter
    # (Nykoebing Mors / Nykoebing M), men nogle var en ANDEN bys navn: Let-Koeb paa
    # Omoe stod som Skaelskoer, og en butik i Glamsbjerg stod som OErsted.
    byfejl=[]
    for r in rows:
        o=POSTNR.get(str(r[pc]).strip())
        if o and len(r)>4 and r[4].strip()!=o:
            byfejl.append((r,f"By='{r[4]}' men {r[pc]} hedder '{o}'"))
    CHK+=len(pnmis)+len(disp)+len(byfejl)+len(ingen_adr)
    if ingen_adr:
        W(f"    [TJEK] ingen dansk adresse inden for 3 km af koordinaten: {len(ingen_adr)}")
        for r in ingen_adr[:10]: W(f"       · {r[mc]} | {r[nc][:30]} | {r[latc]},{r[lonc]}")
    if fase1_udeblev:
        W(f"    ⚠ KØRSELSFEJL: reverse-opslaget (DAR) svarede ikke for {len(fase1_udeblev)} af "
          f"{len(rows)} rækker ({100*len(fase1_udeblev)/len(rows):.0f} %) — postnr- og "
          f"vej-tjekket er IKKE kørt for dem. Det er ikke en datafejl; kør igen.")
        UDEBLEV.append((fn + ' (reverse)', len(fase1_udeblev), len(rows)))
    W(f"  [TJEK — mulige, kan være grænse/hjørne/legitimt: {len(pnmis)+len(disp)+len(byfejl)}]")
    if byfejl:
        W(f"    By passer ikke til postnummeret: {len(byfejl)}")
        [W(f"       · {r[mc]} | {r[nc][:30]} | {m}") for r, m in byfejl[:12]]
    W(f"    koord i andet postnr: {len(pnmis)}");   [W(f"       · {r[mc]} | {r[ac]} | {m}") for r,m in pnmis[:15]]
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


def datavask(bet, tries=5):
    """-> (kategori, adresse, vaskens tekst). kategori None = vasken svarede IKKE
    (ikke det samme som at adressen er daarlig). 10.000 kald med 15 traade udtoemte
    DAWA 2026-09-10, og de to sidst behandlede filer fik 2.499 falske 'kan ikke
    bekraeftes' - derfor genforsoeg og faa traade."""
    for i in range(tries):
        k, a, kode, tekst = vask(bet)
        if k:
            return k, a, tekst
        time.sleep(1.0 * (i + 1))
    return None, None, None




# refresh_data.py normaliserer KUN disse mærke/lag-par mod DAWA og garanterer derfor
# at adressen findes. En uafklaret adresse dér er en HÅRD FEJL. For de øvrige mærker
# er det et kendt gap (se REFRESH_LOG.md) og havner på tjek-listen.
GARANTERET = {('tankstationer_dk.csv', 'OK'), ('superladere_dk.csv', 'Tesla')}
AFSTAND_TJEK_M = 250

W("\n" + "=" * 70)
W("ADRESSE-EKSISTENS (Adressevask) + ADRESSE vs KOORDINAT")
adr_fejl = 0
alle_afstande = []
for fn, mc, nc, pc, ac, latc, lonc, kwc in LAYERS:
    h, rows = read(fn)

    def job(r):
        bet, vej, hn = betegnelse(r[ac], str(r[pc]).strip(), r[4])
        if bet is None:
            return r, 'INGEN_HUSNR', None, vej, hn, None, None, False
        k, a, tekst = datavask(bet)
        pt, gammel = None, False
        if a and k in ('A', 'B'):
            # Afstanden maales HER, i traaden. v5.0's foerste udgave slog adgangspunktet
            # op i hovedloekken, én raekke ad gangen: ~10.000 kald i serie gav 26,5 min
            # og sprang Action'ens 25-minutters loft.
            pt = adresse_punkt(a.get('id'), a.get('slags', 'adresse'))
            # FORAELDET BETEGNELSE: vasken svarede med et husnummer der IKKE staar i vores
            # adresse, OG vores husnummer findes ikke i DAR i dag. Begge dele skal holde:
            #  - "Gudrunsvej 7 st. 129" -> vasken siger 7; betegnelse() tager fejlagtigt
            #    129 som husnr, men 7 STAAR i adressen -> ikke foraeldet.
            #  - "Sluseholmen 17" -> vasken svarer (forkert) 19 med kode 1000, men 17
            #    findes i DAR -> ikke foraeldet.
            #  - "Vestergade 29, 7100" -> vasken siger 29B, og 29 findes ikke i DAR ->
            #    foraeldet (DAWA's egen kopi godkendte den stadig, maalt 29-09-2026).
            ah = str(a.get('husnr') or '')
            m_ah = re.search(r'(?<![0-9A-Za-zÆØÅæøå])' + re.escape(ah) + r'(?![0-9A-Za-zÆØÅæøå])',
                             r[ac], re.I) if ah else None
            samme_hn = bool(m_ah)
            # Staar vaskens husnummer i vores tekst LIGE EFTER et vejnavn der ligner vaskens,
            # er det samme adresse - uanset hvad betegnelse() fik ud af resten. Den tager
            # 'Gudrunsvej 7 st. 129' som vej 'Gudrunsvej 7 st.' + husnr '129', og saa lignede
            # det et nyt vejnavn (fanget i den fulde koersel 29-09-2026).
            # Kun det SIDSTE komma-led foran husnummeret: 'Metropol, Oestergade 30 st. 26'.
            samme_adr = bool(m_ah) and ligner(r[ac][:m_ah.start()].split(',')[-1].strip(), a.get('vejnavn'))
            # OGSAA omdoebte veje: kode 1000 = eksakt match paa en betegnelse. Svarer
            # vasken med et ANDET vejnavn ('Markedsgade 23, 4800' -> 'Fejoegade 31'), var
            # inputtet en historisk betegnelse - hvis det ikke findes i DAR under sit EGET
            # navn. Kun for kode 1000: 900 er stavevarianter (bstav), 800/700 intervaller.
            ny_vej = a.get('kode') == 1000 and not ligner(a.get('vejnavn'), vej)
            if hn and not samme_adr and (ny_vej or not samme_hn):
                try:
                    gammel = not lookup(vej if ny_vej else a.get('vejnavn'), hn, a.get('postnr'))
                except DawaNede:
                    gammel = False      # kan ikke afgoeres - meld det ikke
        return r, (k or 'VASK-SVAREDE-IKKE'), a, vej, hn, tekst, pt, gammel

    ud = []
    # 16 traade: Adressevaelgeren gav 23/s ved 8, 33/s ved 16 og brød sammen ved 32
    # (6/s, maalt 29-09-2026). DAWA taalte kun 8 (udtoemt ved 15, 2026-09-10).
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        ud = list(ex.map(job, rows))

    cnt = defaultdict(int)
    review, staves, ingen, langt, udeblev, bstav = [], [], [], [], [], []
    foraeldet, umaalt = [], []
    grund = {}
    for r, k, a, vej, hn, tekst, pt, gammel in ud:
        cnt[k] += 1
        grund[id(r)] = tekst
        if k == 'VASK-SVAREDE-IKKE':
            udeblev.append(r); continue
        if k == 'INGEN_HUSNR':
            ingen.append(r); continue
        akt = (a or {}).get('husnr')
        if k == 'B' and a and (a.get('vejnavn') or '').lower() != (vej or '').lower():
            # v4.1: B betyder "match efter rettelse" — DAWA har aendret vejnavnet for
            # at faa adressen til at passe. Raekken blev foer godkendt tavst sammen med
            # A, saa 154 forkert stavede vejnavne laa usynlige. Nu meldes de, for det
            # er CSV'ens streng brugeren soeger paa.
            bstav.append((r, a))
        # v5.0: foraeldet betegnelse - se job() for reglen og de tre maalte tilfaelde.
        if gammel:
            foraeldet.append((r, a))
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
        if not pt:
            # v5.0: blev foer sprunget over TAVST - saa forsvandt raekken fra
            # afstandstjekket uden at nogen vidste det (review 29-09-2026).
            umaalt.append(r)
            continue
        try:
            d = hav(float(r[latc]), float(r[lonc]), pt[0], pt[1])
        except (ValueError, TypeError):
            continue
        alle_afstande.append(d)
        if d > AFSTAND_TJEK_M:
            langt.append((d, r, a))

    W(f"\n  {fn}: " + " ".join(f"{k}={cnt[k]}" for k in sorted(cnt)))
    if udeblev:
        W(f"    ⚠ KØRSELSFEJL: Adressevasken svarede ikke for {len(udeblev)} af {len(rows)} rækker "
          f"({100*len(udeblev)/len(rows):.0f} %) — adresse-eksistens er IKKE tjekket for dem.")
        W(f"      Det er ikke en datafejl. Kør igen, evt. med faerre traade "
          f"(ret workers i job-poolen) hvis den bliver ved.")
        UDEBLEV.append((fn, len(udeblev), len(rows)))
    gar = [(r, k, a) for r, k, a in review if (fn, r[mc]) in GARANTERET]
    gar += [(r, 'INGEN_HUSNR', None) for r in ingen if (fn, r[mc]) in GARANTERET]
    adr_fejl += len(gar)
    W(f"    [HÅRD FEJL] uafklaret adresse i et GARANTERET lag (OK-tank/Tesla): {len(gar)}")
    for r, k, a in gar[:15]:
        W(f"       ✗ {r[mc]} | {r[nc][:30]} | {r[ac]} ({k})")
    ovr = [(r, k, a) for r, k, a in review if (fn, r[mc]) not in GARANTERET]
    W(f"    [TJEK] husnummer Adressevasken ikke kan bekræfte: {len(ovr)}")
    for r, k, a in ovr[:12]:
        W(f"       · {r[mc]:14} {r[nc][:28]:30} {r[ac][:40]:42} {grund.get(id(r)) or '-'}")
    ovi = [r for r in ingen if (fn, r[mc]) not in GARANTERET]
    W(f"    [TJEK] intet husnummer i adressefeltet: {len(ovi)}")
    for r in ovi[:8]:
        W(f"       · {r[mc]:14} {r[nc][:28]:30} {r[ac][:44]}")
    W(f"    [TJEK] adresse mere end {AFSTAND_TJEK_M} m fra rækkens koordinat: {len(langt)}")
    for d, r, a in sorted(langt, reverse=True)[:15]:
        W(f"       · {int(d):4} m  {r[mc]:14} {r[nc][:28]:30} {r[ac][:44]}")
    if bstav:
        W(f"    [TJEK] Adressevasken rettede vejnavnet for at finde adressen (kategori B): {len(bstav)}")
        for r, a in bstav[:12]:
            W(f"       · {r[mc]:14} {r[ac][:42]:44} -> {a.get('vejnavn')} {a.get('husnr')}")
        CHK += len(bstav)
    if foraeldet:
        W(f"    [TJEK] adressen findes kun under et NYT nummer/navn (foraeldet betegnelse): {len(foraeldet)}")
        for r, a in foraeldet[:12]:
            W(f"       · {r[mc]:14} {r[ac][:42]:44} -> hedder nu {a.get('betegnelse')}")
        CHK += len(foraeldet)
    if umaalt:
        W(f"    [INFO] adressen er bekræftet, men dens punkt kunne ikke slås op - afstand ikke målt: {len(umaalt)}")
        for r in umaalt[:5]:
            W(f"       · {r[mc]:14} {r[ac][:44]}")
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

if UDEBLEV:
    W("\n  ⚠ ADRESSE-EKSISTENS ER UFULDSTAENDIG i denne koersel:")
    for fn, n, tot in UDEBLEV:
        W(f"      {fn}: {n} af {tot} raekker ikke tjekket (opslaget svarede ikke)")
    W("      Tallene for 'husnummer Adressevasken ikke kan bekraefte' er derfor ikke daekkende.")

W(f"\n================  HÅRDE FEJL i alt: {FEJL}  |  TJEK-punkter: {CHK}  ================")
open(os.path.join(OUT,'validation_report.txt'),'w',encoding='utf-8').write("\n".join(report))
print("\n(Rapport gemt i validation_report.txt)")
