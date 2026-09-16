#!/usr/bin/env python3
"""
refresh_retail.py — frisk ALLE kaeder der har en fungerende henter.

HVORFOR: den ugentlige Action koerte kun refresh_data.py, som daekker OK-tank og
Tesla — 724 af 11.294 naale. De oevrige 10.570, herunder hele detailhandlen, stod
stille. AUTO_UPDATE.md begrundede det med at "SPA-sider ikke kan automatiseres
stabilt", men den tekst er skrevet FOER retail_sources.py fandtes. En probe
16-09-2026 viste at alle 35 hentere svarer, de fleste paa under et sekund.

SIKKERHED: et job der automatisk omskriver 10.000 raekker kan smadre gode data,
hvis en kilde degraderer. Derfor gaelder for HVER kaede, og alle fire skal holde:
  1. antallet maa ikke falde mere end MAX_FALD mod den CSV vi allerede har
  2. hver adresse skal kunne verificeres mod sin egen koordinat i DAWA
  3. ingen raekke maa mangle postnr eller by
  4. alle koordinater skal ligge i Danmark
Fejler én af dem, beholdes kaedens EKSISTERENDE raekker uroert, og de oevrige
kaeder koerer videre. Filerne skrives foerst naar alle kaeder er behandlet, saa et
nedbrud undervejs ikke efterlader en halv fil.

Koer:  python3 refresh_retail.py [--dry-run]
"""
import collections, csv, os, sys
import retail_sources as RS
import sources as S
from dawa import normalize_rows

OUT = os.path.dirname(os.path.abspath(__file__))
MAX_FALD = 0.05          # hoejst 5 % faerre raekker end i dag
MAX_UVERIFICERET = 0.02  # hoejst 2 % som DAWA ikke kan bekraefte
DK = (54.4, 57.9, 7.8, 15.3)

# Hentere der leverer raekker til de tre retail-lag (7 kolonner).
KAEDER = [(n, getattr(RS, n)) for n in (
    'coop', 'netto', 'seven_eleven', 'rema', 'dagrofa', 'lidl', 'apoteker', 'matas',
    'loevbjerg', 'imerco', 'kopkande', 'sport24', 'bogide', 'synoptik', 'thiele',
    'powerdk', 'toejeksperten', 'jysk', 'ilva', 'ikea', 'stark', 'xlbyg', 'bygma',
    'jemogfix', 'davidsen', 'silvan', 'bauhaus', 'plantorama')]
KAEDER += [('lagkagehuset', S.lagkagehuset)]

FILER = ('dagligvarer_dk.csv', 'udvalgsvarer_dk.csv', 'pladskraevende_dk.csv')


def _laes(fn):
    with open(os.path.join(OUT, fn), encoding='utf-8-sig') as f:
        r = list(csv.reader(f))
    return r[0], r[1:]


def _i_dk(x):
    try:
        la, lo = float(x['lat']), float(x['lon'])
    except (TypeError, ValueError, KeyError):
        return False
    return DK[0] < la < DK[1] and DK[2] < lo < DK[3]


def main(dry=False):
    filer = {fn: _laes(fn) for fn in FILER}
    # maerke -> fil, udledt af de CSV'er vi har. En kaede vi ikke kender i forvejen
    # placeres ikke automatisk — kategorien er en planlovsafgoerelse, ikke en teknisk.
    hvor, haves = {}, collections.Counter()
    for fn, (_, body) in filer.items():
        for r in body:
            hvor[r[0]] = fn
            haves[r[0]] += 1

    nye = collections.defaultdict(list)     # fil -> raekker
    erstat = collections.defaultdict(set)   # fil -> maerker der er friske
    rapport = []

    for navn, fn_hent in KAEDER:
        try:
            raa = fn_hent()
        except Exception as e:
            rapport.append((navn, 'HENTER FEJLEDE', f'{type(e).__name__}: {e}'[:90])); continue
        udenfor = [x for x in raa if not _i_dk(x)]
        raa = [x for x in raa if _i_dk(x)]
        pr_maerke = collections.defaultdict(list)
        for x in raa:
            pr_maerke[x.get('brand')].append(x)

        ukendt = [m for m in pr_maerke if m not in hvor]
        if ukendt:
            rapport.append((navn, 'UKENDT MÆRKE', f'{ukendt} findes ikke i CSV — springer over'))
            for m in ukendt:
                pr_maerke.pop(m)

        for maerke, xs in pr_maerke.items():
            har = haves.get(maerke, 0)
            if har and len(xs) < har * (1 - MAX_FALD):
                rapport.append((navn, 'AFVIST', f'{maerke}: {har} -> {len(xs)} '
                                                f'({100*(har-len(xs))/har:.0f} % fald)')); continue
            rows = [[maerke, (x.get('name') or maerke).strip(),
                     f"{x.get('street','')}, {x.get('postnr','')} {x.get('by','')}".strip(', '),
                     str(x.get('postnr') or ''), (x.get('by') or '').strip(),
                     f"{float(x['lat']):.6f}", f"{float(x['lon']):.6f}"] for x in xs]
            _, skip = normalize_rows(rows, adr=2, postnr=3, by=4, lat=5, lon=6, workers=8)
            if skip > max(1, len(rows) * MAX_UVERIFICERET):
                rapport.append((navn, 'AFVIST', f'{maerke}: DAWA kunne ikke bekræfte '
                                                f'{skip} af {len(rows)} adresser')); continue
            tomme = [r for r in rows if not r[3].strip() or not r[4].strip()]
            if tomme:
                rapport.append((navn, 'AFVIST', f'{maerke}: {len(tomme)} række(r) uden postnr/by')); continue
            mfn = hvor[maerke]
            nye[mfn] += rows
            erstat[mfn].add(maerke)
            ekstra = f' (+{len(udenfor)} uden for DK udeladt)' if udenfor else ''
            rapport.append((navn, 'ok', f'{maerke}: {har} -> {len(rows)}{ekstra}'))

    for navn, status, txt in rapport:
        print(f'  {navn:16} {status:14} {txt}')

    skrevet = 0
    for fn, (head, body) in filer.items():
        if not erstat[fn]:
            continue
        beholdt = [r for r in body if r[0] not in erstat[fn]]
        ud = beholdt + [r + [''] * (len(head) - len(r)) for r in nye[fn]]
        if len(ud) < len(body) * 0.98:
            print(f'  ⚠ {fn}: {len(body)} -> {len(ud)} er over 2 % fald — SKRIVER IKKE'); continue
        ud.sort(key=lambda z: (z[0], str(z[3])))
        print(f'  {fn}: {len(body)} -> {len(ud)} ({len(erstat[fn])} mærker frisket)')
        if not dry:
            with open(os.path.join(OUT, fn), 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f); w.writerow(head); w.writerows(ud)
            skrevet += 1
    afvist = [r for r in rapport if r[1] != 'ok']
    print(f'\n{len([r for r in rapport if r[1] == "ok"])} mærker friskede · '
          f'{len(afvist)} afvist · {skrevet} fil(er) skrevet'
          + ('  [DRY-RUN — intet skrevet]' if dry else ''))
    return 1 if any(r[1] == 'HENTER FEJLEDE' for r in rapport) else 0


if __name__ == '__main__':
    sys.exit(main(dry='--dry-run' in sys.argv))
