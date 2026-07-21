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
LAYERS=[('tankstationer_dk.csv',0,1,3,2,5,6,-1),('superladere_dk.csv',0,1,3,2,8,9,5),('fastfood_kaeder_dk.csv',0,1,3,2,5,6,-1)]
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
    seen=defaultdict(list); ndup=[]
    for r in rows:
        try: la=float(r[latc]); lo=float(r[lonc])
        except: continue
        for (kla,klo) in seen[r[mc]]:
            if abs(kla-la)<0.0004 and abs(klo-lo)<0.0004 and hav(la,lo,kla,klo)<30: ndup.append(r); break
        seen[r[mc]].append((la,lo))
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
    W(f"    nær-dublet <30m samme mærke: {len(ndup)}");    [W(f"       ✗ {r[mc]} | {r[ac]}") for r in ndup[:10]]
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

W(f"\n================  HÅRDE FEJL i alt: {FEJL}  |  TJEK-punkter: {CHK}  ================")
open(os.path.join(OUT,'validation_report.txt'),'w',encoding='utf-8').write("\n".join(report))
print("\n(Rapport gemt i validation_report.txt)")
