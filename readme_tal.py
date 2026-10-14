#!/usr/bin/env python3
"""
readme_tal.py — tallene i README.md, regnet ud af CSV'erne. Kaldes af rebuild.py.

Et tal i README'en, der afhaenger af data, staar mellem to markoerer:

    ... 852<!--/n--> ladeanlaeg       (inde i en linje: '<!--n:lade-->852<!--/n-->')
    <!--n:lade_maerker-->             (en blok: markoererne paa hver sin linje)
    Clever 165, Norlys 162, ...
    <!--/n-->

rebuild.py skriver dem igen ved hver genopbygning, og tests/test_data.py fejler, hvis
README'en ikke passer til data. Hvorfor: 13-10-2026 stod README'en med tal skrevet i haanden,
og fire af dem var gledet fra data uden at noget sagde fra - 540 + 19 apoteker (data: 544 + 20),
563 pladskraevende maerker (561), 3.536 punkter ved aabning (3.578) og 'hentere for 27 kaeder'
(75 ugentlige kilder). Den ugentlige Action committede heller ikke README.md.

Regler (haandhaeves af udfyld()):
  * en ukendt noegle, en manglende slutmarkoer eller en noegle, README'en ikke har, er en fejl;
  * en markoer inde i en linje maa ikke staa forrest i linjen: CommonMark laeser en linje,
    der begynder med '<!--', som en HTML-blok, og saa vises resten af linjen uformateret.
"""
import csv, os, re, textwrap
from collections import Counter

OUT = os.path.dirname(os.path.abspath(__file__))
README = os.path.join(OUT, 'README.md')
MARKOER = re.compile(r'<!--n:([a-z0-9_]+)-->(.*?)<!--/n-->', re.S)

# Lag -> CSV. Kolonne 0 er maerket i alle seks; Lastbil er kolonne 10 (lader) og 7 (tank).
FILER = {'daglig': 'dagligvarer_dk.csv', 'udvalg': 'udvalgsvarer_dk.csv',
         'plads': 'pladskraevende_dk.csv', 'tank': 'tankstationer_dk.csv',
         'lade': 'superladere_dk.csv', 'food': 'fastfood_kaeder_dk.csv'}
LADE_LASTBIL_I, TANK_LASTBIL_I = 10, 7
LADE_KW_I = 5
# Effekt pr. udtag, som laget er defineret (README, 'Regel'): 250-600 kW til personbil
# (ét CCS-udtag giver hoejst 600 kW), op til 1.200 kW til lastbil (MCS).
LADE_KW = {'bil': (250, 600), 'lastbil': (250, 1200)}
# refresh_data.py erstatter Tesla-raekkerne fra supercharge.info hver uge (ikke en
# refresh_retail-henter, saa den staar ikke i EJER). (maerke, halvdel) -> kilden.
ERSTATTES_UGENTLIGT = {('Tesla', 'bil'): 'supercharge.info'}
MAERKER_VIST = 22            # retail-lagenes lister: de 22 stoerste, resten som '+ N maerker mere'
BREDDE = 80


def laes(fn):
    with open(os.path.join(OUT, fn), encoding='utf-8-sig', newline='') as f:
        r = list(csv.reader(f))
    return r[0], r[1:]


def _ja(r, i):
    return len(r) > i and (r[i] or '').strip().lower() == 'ja'


def dk(n):
    """11466 -> '11.466' (dansk tusindtalsseparator)."""
    return f'{n:,}'.replace(',', '.')


def _og(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ', '.join(xs[:-1]) + ' og ' + xs[-1]


def _ombryd(s):
    """Ombryd ved ', ', saa et maerke og dets tal aldrig skilles."""
    linjer, cur = [], ''
    for i, del_ in enumerate(s.split(', ')):
        led = del_ if i == 0 else ', ' + del_
        if cur and len(cur) + len(led) > BREDDE:
            linjer.append(cur + ','); cur = del_
        else:
            cur += led
    return '\n'.join(linjer + [cur])


def maerkeliste(rows, maks=None, punktum=True):
    """'Clever 165, Norlys 162, ...' - flest foerst, ved lige antal alfabetisk (som CSV'ernes
    sortering), og med '(+ N maerker mere)', hvis listen er klippet."""
    par = sorted(Counter(r[0] for r in rows).items(), key=lambda kv: (-kv[1], kv[0]))
    vis = par[:maks] if maks else par
    s = ', '.join(f'{b} {n}' for b, n in vis)
    rest = len(par) - len(vis)
    if rest:
        s += f' (+ {rest} {"mærke" if rest == 1 else "mærker"} mere)'
    elif punktum:
        s += '.'
    return s


def _slukket():
    """Lagene, der starter slukket paa kortet (SLUKKET i kort_soeg.html)."""
    with open(os.path.join(OUT, 'kort_soeg.html'), encoding='utf-8') as f:
        h = f.read()
    m = re.search(r"const SLUKKET=new Set\(\[([^\]]*)\]\)", h)
    if not m:
        raise ValueError("kort_soeg.html: fandt ikke 'const SLUKKET=new Set([...])'")
    return set(re.findall(r"'([a-z]+)'", m.group(1)))


def lade_daekning(lade):
    """Hvor mange laderaekker holdes hver uge op mod en kilde? Regnet af refresh_retail's egne
    registre (EJER, LADE_KAEDER, KUN_RAPPORT, EN_HALVDEL, KENDT_UDEN_KILDE), saa teksten
    foelger med, naar en henter kobles paa eller en KENDT-post fjernes."""
    import refresh_retail as R
    klasse = {}                                     # (maerke, halvdel) -> 'auto' / 'rapport'
    for k in sorted(R.LADE_KAEDER):
        for b in R.EJER.get(k, ()):
            for h in ('bil', 'lastbil'):
                if (k in R.EN_HALVDEL and R.EN_HALVDEL[k] != h) or (k, b, h) in R.HALVDEL_IKKE_I_KILDEN:
                    continue
                if klasse.get((b, h)) != 'auto':    # en automatisk kilde vinder over en rapport
                    klasse[(b, h)] = 'rapport' if k in R.KUN_RAPPORT else 'auto'
    for bh in ERSTATTES_UGENTLIGT:
        klasse[bh] = 'auto'
    halv = lambda r: 'lastbil' if _ja(r, LADE_LASTBIL_I) else 'bil'
    pr = {'auto': Counter(), 'rapport': Counter(), 'kendt': Counter(), 'uden': Counter()}
    for r in lade:
        bh = (r[0], halv(r))
        if bh not in klasse:
            pr['uden'][bh] += 1
        elif (r[0], r[1]) in R.KENDT_UDEN_KILDE:
            pr['kendt'][r[0]] += 1
        else:
            pr[klasse[bh]][bh] += 1
    alle = Counter((r[0], halv(r)) for r in lade)
    # Et maerke vises med '(bil)'/'(lastbil)', naar dets to halvdele hoerer til hver sin gruppe.
    gruppe = {bh: k for k in ('auto', 'rapport', 'uden') for bh in pr[k]}

    def navn(bh):
        b, h = bh
        anden = (b, 'lastbil' if h == 'bil' else 'bil')
        delt = alle[anden] and gruppe.get(anden, 'kendt') != gruppe.get(bh, 'kendt')
        return f'{b} ({h})' if delt else b

    def raekkefoelge(c):
        samlet, via = Counter(), {}
        for bh, n in c.items():
            samlet[navn(bh)] += n
            if bh in ERSTATTES_UGENTLIGT:
                via[navn(bh)] = ERSTATTES_UGENTLIGT[bh]
        return [b + (f' via {via[b]}' if b in via else '')
                for b, _ in sorted(samlet.items(), key=lambda kv: (-kv[1], kv[0]))]

    n = {k: sum(v.values()) for k, v in pr.items()}
    daekket = n['auto'] + n['rapport'] + n['kendt']
    s = (f"{dk(daekket)} af {dk(len(lade))} rækker holdes hver uge op mod en kilde: "
         f"{dk(n['auto'])} med automatisk tilføjelse fra operatørens egen liste "
         f"({_og(raekkefoelge(pr['auto']))}) og {dk(n['rapport'])} kun til rapport "
         f"({_og(raekkefoelge(pr['rapport']))}).")
    if n['kendt']:
        kendt = sorted(pr['kendt'].items(), key=lambda kv: (-kv[1], kv[0]))
        s += (f" {dk(n['kendt'])} af dem står som KENDT med belæg og kan ikke melde en lukning "
              f"({', '.join(f'{b} {m}' for b, m in kendt)}).")
    if n['uden']:
        uden = Counter()
        for bh, m in pr['uden'].items():
            uden[navn(bh)] += m
        s += (f" Ikke overvåget ({dk(n['uden'])}): "
              + ', '.join(f'{b} {m}' for b, m in sorted(uden.items(), key=lambda kv: (-kv[1], kv[0])))
              + '.')
    return textwrap.fill(s, width=100, break_long_words=False, break_on_hyphens=False)


def beregn(opdateret=None):
    """-> {noegle: tekst} for alle markoerer. opdateret: datoteksten ('13. oktober 2026'),
    som rebuild.py regner ud af kildefilernes datoer; None = behold README'ens."""
    d = {k: laes(fn)[1] for k, fn in FILER.items()}
    lade_bil = [r for r in d['lade'] if not _ja(r, LADE_LASTBIL_I)]
    lade_lastbil = [r for r in d['lade'] if _ja(r, LADE_LASTBIL_I)]
    tank_bil = [r for r in d['tank'] if not _ja(r, TANK_LASTBIL_I)]
    tank_lastbil = [r for r in d['tank'] if _ja(r, TANK_LASTBIL_I)]
    lag = {'tank': len(tank_bil), 'tanktruck': len(tank_lastbil), 'charge': len(lade_bil),
           'truck': len(lade_lastbil), 'food': len(d['food']), 'daglig': len(d['daglig']),
           'udvalg': len(d['udvalg']), 'plads': len(d['plads'])}
    c = {k: Counter(r[0] for r in rows) for k, rows in d.items()}

    def i_interval(r):
        lo, hi = LADE_KW['lastbil' if _ja(r, LADE_LASTBIL_I) else 'bil']
        try:
            return lo <= float(r[LADE_KW_I]) <= hi
        except ValueError:
            return False
    n_ok = sum(1 for r in d['lade'] if i_interval(r))
    import refresh_retail as R
    t = {
        'punkter': dk(sum(len(v) for v in d.values())),
        'daglig': dk(len(d['daglig'])), 'udvalg': dk(len(d['udvalg'])), 'plads': dk(len(d['plads'])),
        'tank': dk(len(d['tank'])), 'lade': dk(len(d['lade'])), 'food': dk(len(d['food'])),
        'tank_bil': dk(len(tank_bil)), 'tank_lastbil': dk(len(tank_lastbil)),
        'lade_bil': dk(len(lade_bil)), 'lade_lastbil': dk(len(lade_lastbil)),
        'lade_maerker': _ombryd(maerkeliste(lade_bil)),
        'lade_lastbil_maerker': maerkeliste(lade_lastbil, punktum=False),
        'food_maerker': _ombryd(maerkeliste(d['food'])),
        'tank_maerker': _ombryd(maerkeliste(tank_bil)),
        'tank_lastbil_maerker': maerkeliste(tank_lastbil, punktum=False),
        'daglig_maerker': _ombryd(maerkeliste(d['daglig'], MAERKER_VIST)),
        'udvalg_maerker': _ombryd(maerkeliste(d['udvalg'], MAERKER_VIST)),
        'plads_maerker': _ombryd(maerkeliste(d['plads'], MAERKER_VIST)),
        'lade_i_interval': (f"alle {dk(len(d['lade']))} rækker" if n_ok == len(d['lade'])
                            else f"{dk(n_ok)} af {dk(len(d['lade']))} rækker"),
        'lade_daekning': lade_daekning(d['lade']),
        'apotek': dk(c['daglig']['Apotek']), 'apoteksudsalg': dk(c['daglig']['Apoteksudsalg']),
        'ikea_bestil': dk(c['udvalg']['IKEA bestillingssted']),
        'ikea_alle': dk(c['udvalg']['IKEA'] + c['udvalg']['IKEA bestillingssted']),
        'louis_nielsen': dk(c['udvalg']['Louis Nielsen']),
        'plads_antal_maerker': dk(len(c['plads'])),
        'generiske': dk(c['plads']['Bilforhandler'] + c['plads']['Havecenter']),
        'hk_benzin': dk(c['tank']['HK Benzin']),
        'start_punkter': dk(sum(n for k, n in lag.items() if k not in _slukket())),
        'kilder': dk(len(R.KAEDER)),
    }
    if opdateret:
        t['opdateret'] = opdateret
    return t


def udfyld(tekst, t):
    """Skriv tallene ind mellem markoererne. Rejser ValueError ved en ukendt noegle, en
    noegle i t, som teksten ikke har (undtagen 'opdateret'), en manglende slutmarkoer eller en
    linje-markoer forrest i en linje."""
    if tekst.count('<!--n:') != tekst.count('<!--/n-->'):
        raise ValueError('README.md: start- og slutmarkoerer passer ikke sammen')
    set_ = set()

    def ny(m):
        k, gammel = m.group(1), m.group(2)
        if k == 'opdateret' and k not in t:
            return m.group(0)
        if k not in t:
            raise ValueError(f'README.md: ukendt noegle <!--n:{k}-->')
        set_.add(k)
        blok = gammel.startswith('\n')
        if not blok and (m.start() == 0 or tekst[m.start() - 1] == '\n'):
            raise ValueError(f'README.md: <!--n:{k}--> staar forrest i en linje - CommonMark '
                             'viser saa linjen som raa HTML; saet tekst foran eller lav en blok')
        v = t[k]
        if '\n' in v and not blok:
            raise ValueError(f'README.md: <!--n:{k}--> giver flere linjer og skal vaere en blok')
        # En ombrudt linje, der begynder med '- ', '1. ', '# ' osv., bliver til en liste eller en
        # overskrift i Markdown og river teksten i stykker.
        for linje in v.split('\n') if blok else ():
            if re.match(r'\s*(?:[-*+>#]|\d+[.)])(?:\s|$)', linje):
                raise ValueError(f'README.md: <!--n:{k}--> har en linje, Markdown laeser som '
                                 f'liste/overskrift: {linje[:40]!r}')
        return f'<!--n:{k}-->' + ('\n' + v + '\n' if blok else v) + '<!--/n-->'
    ud = MARKOER.sub(ny, tekst)
    mangler = set(t) - set_ - {'opdateret'}
    if mangler:
        raise ValueError('README.md mangler markoerer for: ' + ', '.join(sorted(mangler)))
    return ud


def skriv(opdateret=None):
    """Opdater README.md. -> True hvis filen blev aendret."""
    with open(README, encoding='utf-8', newline='') as f:
        gammel = f.read()
    ny = udfyld(gammel, beregn(opdateret))
    if ny != gammel:
        with open(README, 'w', encoding='utf-8', newline='') as f:
            f.write(ny)
    return ny != gammel


if __name__ == '__main__':
    print('README.md opdateret' if skriv() else 'README.md var allerede opdateret')
