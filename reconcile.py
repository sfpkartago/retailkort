#!/usr/bin/env python3
"""
reconcile.py — afstem et CSV-lag mod en frisk kilde UDEN at smide hånd-QA væk.

Wholesale-erstatning (som refresh_data.py gør for OK/Tesla) overskriver de
DAWA-normaliserede adresser med kildens rå tekst. For de øvrige mærker gør vi
det modsatte: match på koordinat-nærhed og rapportér kun TILGANG og AFGANG.
Uændrede rækker røres ikke.

Vagt mod tvær-mærke-dubletter: en kandidat kan vise sig at være et anlæg vi
allerede har under et ANDET mærke (roaming-skygge, white-label). report() flagger
derfor naboer på tværs af alle mærker. Den AFVISER ikke automatisk — 2026-09-08
blev Clever "Veri Centret" fejlagtigt afvist på afstand alene, men er et
selvstændigt Clever-anlæg 40 m fra Eviny's. Flag = "slå op i OSM og på operatørens
hardware-id'er", ikke "slet".

Kør:  python3 reconcile.py            # rapport for alle tilgængelige kilder
"""
import csv, math, os, re, sys
from collections import defaultdict
import sources

OUT = os.path.dirname(os.path.abspath(__file__))
LAYERS = {  # fil -> (mærke-idx, navn, adresse, postnr, by, lat, lon)
    'tankstationer_dk.csv':  dict(m=0, n=1, a=2, p=3, b=4, lat=5, lon=6),
    'superladere_dk.csv':    dict(m=0, n=1, a=2, p=3, b=4, lat=8, lon=9),
    'fastfood_kaeder_dk.csv':dict(m=0, n=1, a=2, p=3, b=4, lat=5, lon=6),
}

def read(fn):
    with open(os.path.join(OUT, fn), encoding='utf-8-sig') as f:
        r = list(csv.reader(f)); return r[0], r[1:]

def hav(a, b, c, d):
    R = 6371000.0; r = math.pi / 180
    x = (c - a) * r; y = (d - b) * r
    return 2 * R * math.asin(math.sqrt(math.sin(x/2)**2 + math.cos(a*r)*math.cos(c*r)*math.sin(y/2)**2))

def match(csv_rows, src_rows, ix, radius=200):
    """Grådigt nærmeste-par-match inden for `radius` meter."""
    pairs = []
    for i, s in enumerate(src_rows):
        if s.get('lat') is None: continue
        for j, r in enumerate(csv_rows):
            try: la, lo = float(r[ix['lat']]), float(r[ix['lon']])
            except (ValueError, IndexError): continue
            d = hav(s['lat'], s['lon'], la, lo)
            if d <= radius: pairs.append((d, i, j))
    pairs.sort()
    si, cj = {}, {}
    for d, i, j in pairs:
        if i in si or j in cj: continue
        si[i] = (j, d); cj[j] = (i, d)
    new  = [s for i, s in enumerate(src_rows) if i not in si and s.get('lat') is not None]
    gone = [r for j, r in enumerate(csv_rows) if j not in cj]
    moved = [(src_rows[i], csv_rows[j], d) for i, (j, d) in si.items() if d > 60]
    return si, new, gone, moved

def cross_brand(fn, s, ix, radius=250):
    """Naboer under et ANDET mærke — mulige roaming-skygger. Flag, ikke dom."""
    _, rows = read(fn)
    out = []
    for r in rows:
        if r[ix['m']] == s['brand']:
            continue
        try:
            d = hav(s['lat'], s['lon'], float(r[ix['lat']]), float(r[ix['lon']]))
        except (ValueError, IndexError):
            continue
        if d <= radius:
            out.append((d, r))
    return sorted(out)


def report(label, fn, brands, src_rows, radius=200):
    ix = LAYERS[fn]
    _, rows = read(fn)
    csv_rows = [r for r in rows if r[ix['m']] in brands]
    src = [s for s in src_rows if s['brand'] in brands]
    si, new, gone, moved = match(csv_rows, src, ix, radius)
    print(f"\n{'='*74}\n{label}  —  kilde: {len(src)}   datasæt: {len(csv_rows)}   "
          f"matchet: {len(si)}   TILGANG: {len(new)}   AFGANG: {len(gone)}")
    for s in sorted(new, key=lambda x: (x['brand'], x['name'])):
        extra = f"  [{s.get('kw')} kW · {s.get('count')} ladere]" if s.get('kw') else ''
        print(f"  + NY    {s['brand']:9} {s['name'][:38]:40} {s.get('street','')[:34]:36}"
              f"({s['lat']},{s['lon']}){extra}")
        for d, r in cross_brand(fn, s, ix)[:3]:
            print(f"          ⚠ {int(d):4} m fra {r[ix['m']]} \"{r[ix['n']][:34]}\" — "
                  f"tjek OSM + operatørens hardware-id'er før du afviser")
    for r in sorted(gone, key=lambda x: (x[ix['m']], x[ix['n']])):
        print(f"  - VÆK   {r[ix['m']]:9} {r[ix['n']][:38]:40} {r[ix['a']][:44]}")
    if moved:
        print(f"  ~ flyttet >60 m: {len(moved)}")
        for s, r, d in sorted(moved, key=lambda t: -t[2])[:12]:
            print(f"      {int(d):5} m  {r[ix['n']][:34]:36} -> {s['name'][:34]}")
    return new, gone, moved

SOURCES = [
    ("CLEVER (superladere >=250 kW)", 'superladere_dk.csv',   {'Clever'},            'clever'),
    ("IONITY (superladere)",          'superladere_dk.csv',   {'Ionity'},            'ionity'),
    ("OK (superladere)",              'superladere_dk.csv',   {'OK'},                'ok_chargers'),
    ("GO'ON + LAVPRIS (tank)",        'tankstationer_dk.csv', {"Go'on", 'Lavpris'},  'goon'),
]

def _akey(street, pn):
    t = (street or '').lower()
    for a, b in (('æ', 'ae'), ('ø', 'oe'), ('å', 'aa')):
        t = t.replace(a, b)
    return (re.sub(r'[^a-z0-9]', '', t), str(pn).strip())


def shell_addr_report():
    """Shell's by-sider har ingen koordinater, så vi matcher på vej+postnr.
    Bemærk: Shells egne postnumre er ofte forkerte (DAWA gav datasættet ret i
    5 af 6 uenigheder 2026-09-08), så en 'afvigelse' her er typisk Shells fejl —
    tjek ALTID mod DAWA før du retter noget i datasættet."""
    src = [x for x in sources.shell() if x.get('kind') != 'destination-charging-ev.png']
    ix = LAYERS['tankstationer_dk.csv']
    _, rows = read('tankstationer_dk.csv')
    csv_rows = [r for r in rows if r[ix['m']] == 'Shell']
    ck = {_akey(r[ix['a']].rsplit(',', 1)[0] if ',' in r[ix['a']] else r[ix['a']], r[ix['p']]): r
          for r in csv_rows}
    sk = {_akey(x['street'], x['postnr']): x for x in src}
    new = [x for k, x in sk.items() if k not in ck]
    gone = [r for k, r in ck.items() if k not in sk]
    print(f"\n{'=' * 74}\nSHELL (tank, matchet på adresse)  —  kilde: {len(src)}   "
          f"datasæt: {len(csv_rows)}   afviger: {len(new)} / {len(gone)}")
    for x in sorted(new, key=lambda y: y['street']):
        print(f"  ? KILDE  {x['name'][:34]:36} {x['street'][:30]:32} {x['postnr']} {x['by']}")
    for r in sorted(gone, key=lambda y: y[ix['a']]):
        print(f"  ? DATASÆT {r[ix['n']][:34]:36} {r[ix['a']][:46]}")
    if new or gone:
        print("     (afvigelser er oftest Shells egne forkerte postnumre — verificér mod DAWA)")


if __name__ == '__main__':
    # Én død kilde må ikke vælte hele afstemningen — v1 lod exceptionen boble op,
    # så en enkelt ødelagt JSON afbrød rapporten for alle de øvrige mærker.
    fejlede = []
    for label, fn, brands, fname in SOURCES:
        print(f"\nHenter {fname} ...")
        try:
            report(label, fn, brands, getattr(sources, fname)())
        except Exception as e:
            fejlede.append(f"{fname}: {type(e).__name__}: {e}")
            print(f"  KILDE-FEJL ({fname}): {type(e).__name__}: {e}")

    # Shell har ingen koordinater i listen -> afstemmes på adresse, ikke afstand.
    try:
        print("\nHenter shell ...")
        shell_addr_report()
    except Exception as e:
        fejlede.append(f"shell: {type(e).__name__}: {e}")
        print(f"  KILDE-FEJL (shell): {type(e).__name__}: {e}")

    if fejlede:
        print("\n" + "=" * 74)
        print(f"ADVARSEL: {len(fejlede)} kilde(r) kunne ikke afstemmes:")
        for f in fejlede:
            print(f"  ✗ {f}")
        sys.exit(1)          # så CI kan se det; trinnet er continue-on-error
