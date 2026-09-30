#!/usr/bin/env python3
"""
cvr_tjek.py — tankstationernes adresser holdt op mod CVR (Virks data via Datafordeleren).

RAPPORTERER kun; den aendrer ingen data. Skriver cvr_report.txt.

Hvorfor: CVR er det officielle register over, hvor en virksomhed driver noget. Hver
tankstation er en produktionsenhed (P-enhed) med en beliggenhedsadresse. Holdt op mod
tanklaget 30-09-2026 fandt den fejl, som hverken kilderne, DAR eller BBR kunne se:
OK's API skriver 'Gammel Stillingvej 4' for OK Harlev J, CVR har stationen som
'Harlev Benzin', Gammel Stillingvej 431 (Brugsforeningen TRYG).

CVR er godt til ADRESSER, ikke til aabent/lukket: den halter begge veje (Brugsen
Virklund stod som aktiv en uge efter lukningen, SuperBrugsen Virklund fem maaneder
foer aabningen). Derfor sammenligner scriptet kun adresser paa stationer vi har.

Metode:
  1. Alle aktive P-enheder med branche 473000 (detailhandel med motorbraendstof) plus
     OK a.m.b.a.'s egne (CVR 39170418; de staar under engroshandel, 468100).
  2. Deres beliggenhedsadresse slaas op i DAR for at faa et punkt.
  3. For hver raekke i tankstationer_dk.csv: P-enheder fra SAMME kaede inden for
     NAER_M. Samme kaede afgoeres af P-enhedens navn, naar det naevner et maerke
     (Circle K ejer ogsaa Ingo, Q8 ogsaa F24), ellers af ejeren.
  4. Rapporter raekker, hvor ingen af dem har samme vej (stavevarianter som Gl./Gammel
     og Allé/Alle godtages, se dawa._ligner) og samme husnummer uden bogstav (CVR har
     intet felt for husbogstav).

Koer:  python3 cvr_tjek.py
"""
import concurrent.futures, csv, json, os, re, sys, time
import dawa

OUT = os.path.dirname(os.path.abspath(__file__))
CVR_URL = 'https://graphql.datafordeler.dk/CVR/v2'
NAER_M = 80
OK_AMBA = 39170418
BRAENDSTOF = '473000'
# Ejere hvis P-enheder ikke altid naevner maerket i navnet (fx OK: '393 - Albertslund').
EJER_MAERKE = {28142412: {'Circle K', 'Ingo'}, 61082913: {'Q8', 'F24'}, 36552816: {'OIL!'},
               36563028: {'Shell'}, 13256772: {'OK'}, OK_AMBA: {'OK'}}
# Maerkenavne som de staar i P-enhedernes navne.
NAVNE_MAERKE = [(re.compile(r'circle\s*k', re.I), 'Circle K'), (re.compile(r'\bingo\b', re.I), 'Ingo'),
                (re.compile(r'\bf24\b', re.I), 'F24'), (re.compile(r'\bq\s?8\b', re.I), 'Q8'),
                (re.compile(r'\bshell\b', re.I), 'Shell'), (re.compile(r'\boil!', re.I), 'OIL!'),
                (re.compile(r'\bok\b', re.I), 'OK'), (re.compile(r'uno-?x', re.I), 'Uno-X'),
                (re.compile(r"go'?on", re.I), "Go'on"), (re.compile(r'\byx\b', re.I), 'YX')]


# Afgjorte tilfaelde, hvor raekken er rigtig og CVR ikke: (maerke, raekkens gadetekst i
# lowercase) -> grund med belaeg. Saa melder rapporten dem ikke igen hver uge.
KENDTE = {
    ('F24', 'grenåvej 740f'): 'CVR har Grenåvej 742, som ikke findes i DAR; BBR-tankbygningen er 740F (30-09-2026)',
}


def _nu():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _q(query):
    return dawa._gql(query, base=CVR_URL)


def _sider(entitet, where, felter):
    ud, after = [], None
    for _ in range(100):
        a = f', after:{json.dumps(after)}' if after else ''
        d = _q(f'{{ {entitet}(first:1000{a}, virkningstid:"{_nu()}", where:{where}) '
               f'{{ pageInfo{{hasNextPage endCursor}} nodes {{ {felter} }} }} }}')[entitet]
        ud += d['nodes']
        if not d['pageInfo']['hasNextPage']:
            return ud
        after = d['pageInfo']['endCursor']
    raise dawa.DawaNede(f'{entitet}: over 100 sider')


def p_enheder():
    """-> liste af {pnr, ejer, navn, vej, husnr, postnr, lat, lon} for aktive P-enheder."""
    ids = sorted({n['CVREnhedsId'] for n in _sider('CVR_Branche', f'{{vaerdi:{{eq:"{BRAENDSTOF}"}}}}', 'CVREnhedsId')})
    pe = []
    for i in range(0, len(ids), 100):
        pe += _sider('CVR_Produktionsenhed', f'{{id:{{in:{json.dumps(ids[i:i + 100])}}}}}',
                     'id pNummer status produktionsenhedOphoersdato tilknyttetVirksomhedsCVRNummer')
    pe += _sider('CVR_Produktionsenhed', f'{{tilknyttetVirksomhedsCVRNummer:{{eq:{OK_AMBA}}}}}',
                 'id pNummer status produktionsenhedOphoersdato tilknyttetVirksomhedsCVRNummer')
    pe = {x['id']: x for x in pe if x['status'] == 'aktiv' and not x['produktionsenhedOphoersdato']}
    ids = list(pe)
    navn, adr = {}, {}
    for i in range(0, len(ids), 100):
        b = json.dumps(ids[i:i + 100])
        for r in _sider('CVR_Navn', f'{{CVREnhedsId:{{in:{b}}}}}', 'CVREnhedsId vaerdi'):
            navn[r['CVREnhedsId']] = r['vaerdi']
        for r in _sider('CVR_Adressering', f'{{CVREnhedsId:{{in:{b}}}}}',
                        'CVREnhedsId AdresseringAnvendelse CVRAdresse_vejnavn CVRAdresse_husnummerFra CVRAdresse_postnummer'):
            if r['AdresseringAnvendelse'] == 'beliggenhedsadresse' and r['CVRAdresse_vejnavn']:
                adr[r['CVREnhedsId']] = (r['CVRAdresse_vejnavn'], str(r['CVRAdresse_husnummerFra'] or ''),
                                         str(r['CVRAdresse_postnummer'] or ''))

    def geo(i):
        a = adr.get(i)
        if not a:
            return None
        # CVR har intet husbogstav: '2' kan i DAR kun findes som 2A. Tag da familiens
        # foerste - men ALDRIG et andet nummer; saa springes P-enheden over.
        j = dawa._q(vejnavn=a[0], husnr=a[1], postnr=a[2], per_side=1) or \
            dawa._q(vejnavn=a[0], postnr=a[2], per_side=1000)
        hit = [x for x in j if dawa._base(x['husnr']) == dawa._base(a[1])]
        if not hit:
            return None
        x = pe[i]
        return {'pnr': x['pNummer'], 'ejer': x['tilknyttetVirksomhedsCVRNummer'], 'navn': navn.get(i, ''),
                'vej': a[0], 'husnr': a[1], 'postnr': a[2], 'lat': hit[0]['y'], 'lon': hit[0]['x']}
    with concurrent.futures.ThreadPoolExecutor(12) as ex:
        return [g for g in ex.map(geo, ids) if g]


def maerker_for(p):
    # En vaskehal ('426 - Grenå - Vask') er ikke tankstationen, selv om den staar ved siden af.
    if re.search(r'\bvask\b|bilvask|vaskehal', p['navn'], re.I):
        return set()
    fundet = {m for rx, m in NAVNE_MAERKE if rx.search(p['navn'])}
    return fundet or EJER_MAERKE.get(p['ejer'], set())


def samme_adresse(adresse, p):
    vej, husnr = dawa.split_street(adresse)
    if not (dawa._loose(vej) == dawa._loose(p['vej']) or dawa._ligner(vej, p['vej'])):
        return False
    # Et interval ('Buddingevej 81-83') daekker P-enhedens nummer, hvis det ligger i det.
    m = re.search(r'\b(\d+)\s*[A-Za-z]?\s*-\s*(\d+)', adresse.split(',')[0])
    n = dawa._base(p['husnr'])
    if m and n and int(m.group(1)) <= int(n) <= int(m.group(2)):
        return True
    return dawa._base(husnr) == n


def main():
    rapport = os.path.join(OUT, 'cvr_report.txt')
    # Advarslen skrives foerst og overskrives til sidst: doer scriptet undervejs, maa den
    # gamle rapport ikke blive liggende og ligne en ren kontrol.
    open(rapport, 'w', encoding='utf-8').write('CVR-TJEKKET BLEV IKKE FÆRDIGT — ingen rapport for denne kørsel\n')
    pe = p_enheder()
    if len(pe) < 600:
        raise RuntimeError(f'CVR gav kun {len(pe)} tankstations-P-enheder (forventet ~1.200)')
    with open(os.path.join(OUT, 'tankstationer_dk.csv'), encoding='utf-8-sig') as f:
        raekker = list(csv.reader(f))[1:]
    daekket, afvig = 0, []
    for r in raekker:
        la, lo = float(r[5]), float(r[6])
        naer = sorted(((dawa.hav(la, lo, p['lat'], p['lon']), p) for p in pe
                       if abs(p['lat'] - la) < 0.002 and abs(p['lon'] - lo) < 0.004), key=lambda t: t[0])
        naer = [(d, p) for d, p in naer if d <= NAER_M and r[0] in maerker_for(p)]
        if not naer:
            continue
        daekket += 1
        if (r[0], ' '.join(r[2].split(',')[0].lower().split())) in KENDTE:
            continue
        if not any(samme_adresse(r[2], p) for _, p in naer):
            d, p = naer[0]
            afvig.append((r[0], r[1], r[2], f"{p['vej']} {p['husnr']}, {p['postnr']}", round(d), p['navn'], p['pnr']))
    linjer = [f'CVR-tjek af tanklaget koert {time.strftime("%Y-%m-%d %H:%M")} (cvr_tjek.py)',
              f'{len(pe)} aktive P-enheder (branche {BRAENDSTOF} + OK a.m.b.a.) med DAR-punkt.',
              f'{daekket} af {len(raekker)} raekker har en P-enhed fra samme kaede inden for {NAER_M} m; '
              f'{len(afvig)} af dem har en anden adresse end P-enheden.',
              'Rapporten er vejledende: en P-enhed kan staa paa et nabonummer (fx vaskehallen), og',
              'OK-raekker rettes i refresh_data.OK_KILDEFEJL, ikke i CSV\'en.', '']
    for a in sorted(afvig):
        linjer.append(f'  {a[0]:9} {a[1][:30]:30} raekke: {a[2].split(",")[0][:30]:30} '
                      f'CVR: {a[3][:34]:34} {a[4]:3} m  ({a[5][:32]}, P {a[6]})')
    open(rapport, 'w', encoding='utf-8').write('\n'.join(linjer) + '\n')
    print('\n'.join(linjer[:3]))
    print(f'(rapport gemt i cvr_report.txt: {len(afvig)} afvigelser)')


if __name__ == '__main__':
    sys.exit(main())
