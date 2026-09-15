#!/usr/bin/env python3
"""
refresh_data.py — hent friske data fra kildernes officielle API'er.

Adresser normaliseres mod DAWA ud fra koordinaten (se dawa.py): kildernes egne
postnr/by-felter er upålidelige, koordinaten er det ikke.

Kør:  python3 refresh_data.py
Opdaterer tankstationer_dk.csv (OK) og superladere_dk.csv (Tesla) IN-PLACE
fra de to reneste offentlige API'er. Se REFRESH.md for de øvrige kilder.

Datasættet er et øjebliksbillede; kør dette (og evt. workflow-scripts, se
REFRESH.md) for at friske det op.
"""
import csv, json, os, sys, urllib.request
from dawa import normalize_rows

OUT = os.path.dirname(os.path.abspath(__file__))
# Faste minima. De var saat saa lavt (600/25 mod faktisk 690/34) at et tab paa
# 9 Tesla-anlaeg — 26 % af maerket — slap under BEGGE vagter: ogsaa Action'ens
# 2 %-spaerre maaler paa hele charge-laget (784 raekker), hvor Tesla kun fylder 34.
OK_FLOOR = 660       # forventet ~690
TESLA_FLOOR = 30     # forventet ~34
# ... og et relativt loft oveni: falder et maerke mere end dette i forhold til
# den CSV vi allerede har, afbrydes der uanset de faste minima.
MAX_FALD = 0.05

def get(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())

def read(fn):
    with open(os.path.join(OUT, fn), encoding='utf-8-sig') as f:
        r = list(csv.reader(f)); return r[0], r[1:]

def write(fn, head, rows):
    """Skriv CSV'en — men kun hvis ALLE raekker har praecis headerens bredde.

    refresh_ok() byggede 7 felter til en 8-kolonners fil og refresh_tesla() 10 til
    en 11-kolonners; Lastbil-kolonnen manglede. Resultatet var en ujaevn CSV efter
    hver ugentlig koersel, og rebuild.py laeser Lastbil paa indeks 7 hhv. 10. Fejlen
    naaede aldrig at fyre, fordi Action'en endnu ikke har koert — vagten her sikrer
    at den heller ikke kan komme igen."""
    afvig = {len(r) for r in rows} - {len(head)}
    if afvig:
        raise RuntimeError(f'{fn}: raekkebredder {sorted(afvig)} passer ikke til '
                           f'headerens {len(head)} kolonner — AFBRYDER foer skrivning')
    with open(os.path.join(OUT, fn), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(head); w.writerows(rows)

def _maerke_vagt(fn, maerke, antal):
    """Afbryd hvis et maerke falder mere end MAX_FALD i forhold til den CSV vi har.

    De faste minima alene daekker ikke: TESLA_FLOOR var 25 mod faktisk 34, saa et
    tab paa 9 anlaeg (26 % af maerket) laa under baade gulvet og Action'ens
    2 %-spaerre, fordi den maaler paa hele laget."""
    try:
        _, cur = read(fn)
    except FileNotFoundError:
        return
    haves = sum(1 for r in cur if r and r[0] == maerke)
    if haves and antal < haves * (1 - MAX_FALD):
        raise RuntimeError(f'{maerke} faldt {haves} -> {antal} '
                           f'({100*(haves-antal)/haves:.0f} %) — AFBRYDER før skrivning')


def adr(g, p, b): return f"{g}, {p} {b}".strip().strip(',')
def rnd(v):
    try: return round(float(v), 6)
    except: return None

# ---------- OK (tankstationer) — officielt pris-API ----------
def refresh_ok():
    d = get('https://mobility-prices.ok.dk/api/v1/fuel-prices')
    rows = []
    for s in d.get('items', []):
        g = f"{(s.get('street') or '').strip()} {(s.get('house_number') or '').strip()}".strip()
        p = str(s.get('postal_code') or '').strip(); b = (s.get('city') or '').strip()
        c = s.get('coordinates') or {}
        # Sidste felt er Lastbil-kolonnen. Uden den blev raekkerne 7 brede i en
        # 8-kolonners fil, og CSV'en blev ujaevn ved hver ugentlig koersel —
        # rebuild.py laeser Lastbil paa indeks 7 og ville faa IndexError.
        rows.append(['OK', f'OK {b}', adr(g, p, b), p, b,
                     rnd(c.get('latitude')), rnd(c.get('longitude')), ''])
    # Antals-tjekket SKAL ligge før write() — lå det i __main__, var CSV'en allerede
    # overskrevet med et trunkeret datasæt når afbrydelsen kom (målt: 2149 -> 1652).
    if len(rows) < OK_FLOOR:
        raise RuntimeError(f'OK returnerede kun {len(rows)} stationer (forventet ~690) — '
                           'AFBRYDER før skrivning')
    _maerke_vagt('tankstationer_dk.csv', 'OK', len(rows))
    ch, skipped = normalize_rows(rows, adr=2, postnr=3, by=4, lat=5, lon=6)
    if skipped:
        raise RuntimeError(f'DAWA svarede ikke for {skipped} af {len(rows)} OK-rækker — '
                           'AFBRYDER frem for at skrive kildens forkerte postnumre')
    head, cur = read('tankstationer_dk.csv')
    kept = [r for r in cur if r[0] != 'OK']
    allrows = kept + rows
    allrows.sort(key=lambda x: (x[0], str(x[3])))
    write('tankstationer_dk.csv', head, allrows)
    return len(rows), len(allrows)

# ---------- Tesla (superladere) — supercharge.info ----------
def refresh_tesla():
    d = get('https://supercharge.info/service/supercharge/allSites')
    rows = []
    for s in d:
        a = s.get('address') or {}
        if a.get('country') != 'Denmark' or s.get('status') != 'OPEN' or (s.get('powerKilowatt') or 0) < 250:
            continue
        g = s.get('gps') or {}
        lat = g.get('latitude'); lng = g.get('longitude')
        street = a.get('street', '') or ''
        rows.append(['Tesla', 'Tesla Supercharger ' + (s.get('name') or '').replace(', Denmark', '').strip(),
                     adr(street, str(a.get('zip', '') or ''), a.get('city', '') or ''),
                     str(a.get('zip', '') or ''), a.get('city', '') or '',
                     s.get('powerKilowatt'), 'CCS+Tesla', s.get('stallCount') or '',
                     rnd(lat), rnd(lng), ''])          # sidste felt = Lastbil-kolonnen
    _maerke_vagt('superladere_dk.csv', 'Tesla', len(rows))
    if len(rows) < TESLA_FLOOR:
        raise RuntimeError(f'Tesla returnerede kun {len(rows)} anlæg (forventet ~34) — '
                           'AFBRYDER før skrivning')
    ch, skipped = normalize_rows(rows, adr=2, postnr=3, by=4, lat=8, lon=9)
    if skipped:
        raise RuntimeError(f'DAWA svarede ikke for {skipped} af {len(rows)} Tesla-rækker — '
                           'AFBRYDER frem for at skrive kildens forkerte postnumre')
    head, cur = read('superladere_dk.csv')
    kept = [r for r in cur if r[0] != 'Tesla']
    allrows = kept + rows
    allrows.sort(key=lambda x: (x[0], str(x[3])))
    write('superladere_dk.csv', head, allrows)
    return len(rows), len(allrows)

if __name__ == '__main__':
    # Fail-fast: en kilde der fejler halvvejs maa IKKE efterlade et delvist datasaet
    # som sanity-gaten kan slippe igennem. Bedre at jobbet doer og det gamle,
    # gode feed bliver liggende. Selve antals- og DAWA-vagterne ligger INDE i
    # refresh_ok/refresh_tesla, foer write() — ellers er CSV'en allerede overskrevet
    # naar afbrydelsen kommer.
    print('Henter friske data fra officielle API\'er ...')
    fejl = []
    try:
        n, t = refresh_ok(); print(f'  OK tankstationer:  {n}  (tank i alt: {t})')
    except Exception as e:
        fejl.append(f'OK: {e}')
    try:
        n, t = refresh_tesla(); print(f'  Tesla superladere: {n}  (superladere i alt: {t})')
    except Exception as e:
        fejl.append(f'Tesla: {e}')
    if fejl:
        sys.exit('AFBRYDER:\n  - ' + '\n  - '.join(fejl))
    print('Færdig. Bemærk: kort_soeg.html/xlsx skal genopbygges bagefter '
          '(se REFRESH.md). Øvrige mærker friskes via workflow-scripts (se REFRESH.md).')
