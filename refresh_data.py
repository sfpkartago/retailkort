#!/usr/bin/env python3
"""
refresh_data.py — hent friske data fra kildernes officielle API'er.

Kør:  python3 refresh_data.py
Opdaterer tankstationer_dk.csv (OK) og superladere_dk.csv (Tesla) IN-PLACE
fra de to reneste offentlige API'er. Se REFRESH.md for de øvrige kilder.

Datasættet er et øjebliksbillede; kør dette (og evt. workflow-scripts, se
REFRESH.md) for at friske det op.
"""
import csv, json, os, sys, urllib.request

OUT = os.path.dirname(os.path.abspath(__file__))

def get(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())

def read(fn):
    with open(os.path.join(OUT, fn), encoding='utf-8-sig') as f:
        r = list(csv.reader(f)); return r[0], r[1:]

def write(fn, head, rows):
    with open(os.path.join(OUT, fn), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(head); w.writerows(rows)

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
        rows.append(['OK', f'OK {b}', adr(g, p, b), p, b, rnd(c.get('latitude')), rnd(c.get('longitude'))])
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
                     s.get('powerKilowatt'), 'CCS+Tesla', s.get('stallCount') or '', rnd(lat), rnd(lng)])
    head, cur = read('superladere_dk.csv')
    kept = [r for r in cur if r[0] != 'Tesla']
    allrows = kept + rows
    allrows.sort(key=lambda x: (x[0], str(x[3])))
    write('superladere_dk.csv', head, allrows)
    return len(rows), len(allrows)

if __name__ == '__main__':
    print('Henter friske data fra officielle API\'er ...')
    try:
        n, t = refresh_ok(); print(f'  OK tankstationer:  {n}  (tank i alt: {t})')
    except Exception as e:
        print(f'  OK FEJL: {e}')
    try:
        n, t = refresh_tesla(); print(f'  Tesla superladere: {n}  (superladere i alt: {t})')
    except Exception as e:
        print(f'  Tesla FEJL: {e}')
    print('Færdig. Bemærk: kort_soeg.html/xlsx skal genopbygges bagefter '
          '(se REFRESH.md). Øvrige mærker friskes via workflow-scripts (se REFRESH.md).')
