#!/usr/bin/env python3
"""
kaede_register_tjek.py — de spaerrede kaeder holdt op mod offentlige registre (trin 4, 18-11-2026).

RAPPORTERER kun; den aendrer ingen data. Skriver kaede_register_report.txt.

Hvorfor: McDonald's, Joe & The Juice, Louis Nielsen, H&M, Deichmann og Zara spaerrer for automatisk hentning af
deres egne butikslister (robots.txt, Akamai, Cloudflare). Deres raekker har derfor ingen ugentlig kilde. To
offentlige registre kan i stedet melde, naar en forretning aabner eller lukker:
  * Fødevarestyrelsens smiley-register (pub.fvst.dk/publikationer/Smileydata.xml, frie data efter vilkaarene for
    videreanvendelse af offentlige data): hver restaurant er registreret med navn, adresse og P-nummer. 18-11-2026:
    122 McDonald's-restauranter (= vores 122) og 80 Joe & The Juice.
  * CVR (Datafordeleren): butikkernes P-enheder, enten under kaedens eget CVR-nummer (H&M, Deichmann, Zara) eller
    fundet paa branche og navn (Louis Nielsen: hver butik har sit eget ApS i branche 477410).

Registrene halter (CVR mest), saa listerne er KANDIDATER til efterproevning, ikke sandheder - jf. cvr_tjek.py. En
forretning og en raekke regnes som det samme sted, naar de ligger inden for NAER_M eller har samme adresse; CVR
skriver ofte centerets faelles adresse (Field's: Arne Jacobsens Allé 12), saa NAER_M er stoerre end i cvr_tjek.

IKKE MED (18-11-2026): Sport 24 og Ecco. Deres franchisebutikker staar i CVR under ejernes egne navne ('KH Sport
ApS', 'JAP 2 ApS', 'Jens E 4690 ApS'), og for ca. halvdelen af de raekker, CVR ikke kunne parre, er der slet ingen
sports- eller skobutik paa adressen i CVR; et ugentligt tjek ville mest give falske alarmer. Sport 24 hentes i stedet
fra Tjek, som kaeden selv fodrer (retail_sources.sport24_tjek, 18-11-2026).

Koer:  python3 kaede_register_tjek.py
"""
import concurrent.futures, csv, io, json, os, re, sys, time
import xml.etree.ElementTree as ET

import dawa
import cvr_tjek as C
import retail_sources as RS

OUT = os.path.dirname(os.path.abspath(__file__))
RAPPORT = 'kaede_register_report.txt'
SMILEY_URL = 'https://pub.fvst.dk/publikationer/Smileydata.xml'
NAER_M = 250
FAST, UDV = 'fastfood_kaeder_dk.csv', 'udvalgsvarer_dk.csv'

# kilde 'smiley': navn = regex paa 'Virksomhed'; kun detailforretninger med servering (ikke kaedens hovedkontor og
# lager). kilde 'cvr': ejere = CVR-numre, hvis P-enheder hentes; eller branche + navn (alle P-enheder i branchen med
# navnet). ikke = regex paa P-enhedens/forretningens navn, der udelukker kontorer, lagre, soestermaerker og
# shop-in-shops (brugerens regel 17-11-2026: en butik inde i en anden kaedes butik taeller ikke).
# forventet = (min, max) forretninger i registret; uden for det er en koerselsfejl, ikke aabninger/lukninger.
KAEDER = {
    "McDonald's": dict(kilde='smiley', fil=FAST, navn=r"mc\s*donald", ikke=None, forventet=(100, 150)),
    'Joe & The Juice': dict(kilde='smiley', fil=FAST, navn=r'joe\s*(?:&|and)\s*the\s*juice',
                            ikke=r'magasin|illum|salling', forventet=(60, 110)),
    'Louis Nielsen': dict(kilde='cvr', fil=UDV, branche='477410', navn=r'louis\s*nielsen',
                          ikke=r'kontor|lager|administration', forventet=(60, 110)),
    'H&M': dict(kilde='cvr', fil=UDV, ejere=[33345828], navn=r'h\s*&\s*m|hennes',
                ikke=r'\bhome\b|kontor|lager|weekday|monki|arket|other stories|\bcos\b', forventet=(40, 95)),
    'H&M HOME': dict(kilde='cvr', fil=UDV, ejere=[33345828], navn=r'\bhome\b', ikke=r'kontor|lager',
                     forventet=(1, 12)),
    'Deichmann': dict(kilde='cvr', fil=UDV, ejere=[27278388], navn=None,
                      ikke=r'kontor|lager|distribution|administration', forventet=(15, 45)),
    'Zara': dict(kilde='cvr', fil=UDV, ejere=[24209717], navn=r'\bzara\b', ikke=r'kontor|lager', forventet=(2, 12)),
}

# Afgjorte tilfaelde: (kaede, P-nummer) for en forretning i registret, eller (kaede, vores Navn) for en raekke ->
# grund med dato og belaeg. Saa melder rapporten dem ikke igen hver uge.
KENDTE = {
    ('Louis Nielsen', '1023638548'):
        "P-enheden 'Louis Nielsen Nakskov ApS' staar paa Indkildevej 2A, 9210 Aalborg SØ uden butik hos os; butikken i "
        "Nakskov (Nygade 15) har baade sin egen P-enhed og sin raekke (18-11-2026)",
    ('H&M', '1003040150'):
        "'400-440-451-988 H & M HENNES & MAURITZ A/S' paa Ventrupparken 7, 2670 Greve er H&M's tidligere lager- og "
        "logistikcenter (19.000 m2, udbudt til leje gennem EDC Poul Erik Bech, poulerikbech.dk); CVR har kun denne "
        "enhed paa adressen - ingen butik (18-11-2026)",
    ('H&M', '1008504209'):
        "'829 H & M HENNES & MAURITZ A/S Næstved Storcenter' staar i CVR paa Holsted Alle 1, som er Holsted Kirkes "
        "adresse (sognet og kirken har deres enheder dér); butikken ligger i Næstved Storcenter (centrets egen side "
        "naestvedstorcenter.dk/butikker/hm) og er vores raekke 'H&M Næstved', Næstved Storcenter 7 (18-11-2026)",
    ('H&M', 'H&M Næstved'):
        "samme butik som P 1008504209 '829 ... Næstved Storcenter'; CVR-adressen (Holsted Alle 1) er kirkens "
        "(18-11-2026)",
    ('Deichmann', '1020056238'):
        "'Deichmann Sko - Slagelse' staar i CVR paa Jernbanegade 10, 4200 Slagelse, som ikke findes i DAR (geokodet til "
        "nr. 11, 269 m fra centret); butikken ligger i VestsjællandsCentret (centrets egen side vestsjaellandscentret.dk/"
        "butikker/deichmann) og er vores raekke 'Deichmann Slagelse', Vestsjællandscentret 10A (18-11-2026)",
    ('Deichmann', 'Deichmann Slagelse'):
        "samme butik som P 1020056238 'Deichmann Sko - Slagelse'; CVR-adressen Jernbanegade 10 findes ikke i DAR "
        "(18-11-2026)",
    ('Deichmann', '1011480167'):
        "'DEICHMANN-SKO ApS' paa Vesterbrogade 6D, 1620 København V er selskabets egen adresse i en kontorbygning "
        "(brancheforeninger og Advokaterne Eiland har ogsaa adresse dér i CVR) - ingen butik (18-11-2026)",
}


# ---------------------------------------------------------------- kilderne
def smiley_poster(xml, navn_rx, ikke_rx=None):
    """Smiley-registrets XML -> [{navn, gade, postnr, by, pnr}] for kaedens detailforretninger med servering."""
    ud = []
    for r in ET.parse(io.BytesIO(xml) if isinstance(xml, bytes) else io.StringIO(xml)).getroot():
        f = lambda t: ((r.find(t).text or '') if r.find(t) is not None else '').strip()
        navn = f('Virksomhed')
        if not re.search(navn_rx, navn, re.I) or (ikke_rx and re.search(ikke_rx, navn, re.I)):
            continue
        if f('Virksomhedstype') != 'Detail' or not f('FVST_branche').startswith('Serveringsvirksomhed'):
            continue
        ud.append({'navn': navn, 'gade': f('Adresse'), 'postnr': f('Postnummer'), 'by': f('By'),
                   'pnr': f('P_nummer')})
    return ud


def _p_enheder(where):
    return C._sider('CVR_Produktionsenhed', where, 'id pNummer status produktionsenhedOphoersdato '
                                                   'tilknyttetVirksomhedsCVRNummer')


def cvr_poster(cfg):
    """Kaedens aktive P-enheder i CVR -> [{navn, gade, postnr, by, pnr}] efter navn/ikke-filtrene."""
    if cfg.get('ejere'):
        pe = [x for e in cfg['ejere'] for x in _p_enheder(f'{{tilknyttetVirksomhedsCVRNummer:{{eq:{e}}}}}')]
    else:
        ids = sorted({n['CVREnhedsId'] for n in C._sider('CVR_Branche', f'{{vaerdi:{{eq:"{cfg["branche"]}"}}}}',
                                                          'CVREnhedsId')})
        navn = {}
        for i in range(0, len(ids), 100):
            for r in C._sider('CVR_Navn', f'{{CVREnhedsId:{{in:{json.dumps(ids[i:i + 100])}}}}}', 'CVREnhedsId vaerdi'):
                navn[r['CVREnhedsId']] = r['vaerdi']
        hit = [i for i, n in navn.items() if re.search(cfg['navn'], n or '', re.I)]
        pe = [x for i in range(0, len(hit), 100) for x in _p_enheder(f'{{id:{{in:{json.dumps(hit[i:i + 100])}}}}}')]
    pe = {x['id']: x for x in pe if x['status'] == 'aktiv' and not x['produktionsenhedOphoersdato']}
    ids, navn, adr = list(pe), {}, {}
    for i in range(0, len(ids), 100):
        b = json.dumps(ids[i:i + 100])
        for r in C._sider('CVR_Navn', f'{{CVREnhedsId:{{in:{b}}}}}', 'CVREnhedsId vaerdi'):
            navn[r['CVREnhedsId']] = r['vaerdi']
        for r in C._sider('CVR_Adressering', f'{{CVREnhedsId:{{in:{b}}}}}', 'CVREnhedsId AdresseringAnvendelse '
                          'CVRAdresse_vejnavn CVRAdresse_husnummerFra CVRAdresse_postnummer CVRAdresse_postdistrikt'):
            if r['AdresseringAnvendelse'] == 'beliggenhedsadresse' and r['CVRAdresse_vejnavn']:
                adr[r['CVREnhedsId']] = r
    ud = []
    for i in ids:
        n, a = navn.get(i, ''), adr.get(i)
        if (cfg.get('navn') and not re.search(cfg['navn'], n, re.I)) or (cfg.get('ikke') and re.search(cfg['ikke'], n, re.I)):
            continue
        ud.append({'navn': n, 'gade': f"{a['CVRAdresse_vejnavn']} {a['CVRAdresse_husnummerFra'] or ''}".strip() if a else '',
                   'postnr': str(a['CVRAdresse_postnummer'] or '') if a else '',
                   'by': (a.get('CVRAdresse_postdistrikt') or '') if a else '', 'pnr': str(pe[i]['pNummer'])})
    return ud


def geokod(poster, workers=8):
    """Tilfoej lat/lon fra DAR (kildens gade + postnr; CVR har intet husbogstav, se _dar_adressepunkt)."""
    def en(p):
        gade = RS._vej_nr(RS._gade_ren(p['gade'])) if p['gade'] else ''
        la, lo, _ = RS._dar_adressepunkt(gade, p['postnr']) if gade and p['postnr'] else (None, None, '')
        return dict(p, lat=la, lon=lo)
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(en, poster))


# ---------------------------------------------------------------- sammenligningen
def _adr_noegle(gade, postnr):
    s = (gade or '').lower().replace('allé', 'alle')
    s = re.sub(r'\bgl\.?\s', 'gammel ', s)
    m = re.match(r'(.*?\d+)', s)               # uden husbogstav: CVR har det ikke
    s = re.sub(r'[^0-9a-zæøåäöü]', '', m.group(1) if m else s)
    return (s, str(postnr or '').strip()) if s and postnr else None


def sammenlign(kaede, raekker, poster, kendte=None):
    """raekker: vores (Navn, Adresse, Postnr, lat, lon); poster: registrets med lat/lon.
    -> (nye, lukkede, uden_punkt, kendt_linjer)."""
    kendte = KENDTE if kendte is None else kendte
    med = [p for p in poster if p.get('lat') is not None]
    uden_punkt = [p for p in poster if p.get('lat') is None]
    reg_adr = {_adr_noegle(p['gade'], p['postnr']) for p in med} - {None}
    vore_adr = {_adr_noegle(r[1].split(',')[0], r[2]) for r in raekker} - {None}
    nye, lukkede, kendt = [], [], []
    for p in med:
        if (kaede, p['pnr']) in kendte:
            kendt.append(f"{p['navn'][:34]} (P {p['pnr']}) — {kendte[(kaede, p['pnr'])]}")
            continue
        d = min((dawa.hav(p['lat'], p['lon'], r[3], r[4]) for r in raekker), default=9e9)
        if d > NAER_M and _adr_noegle(p['gade'], p['postnr']) not in vore_adr:
            nye.append((p, round(d)))
    for r in raekker:
        if (kaede, r[0]) in kendte:
            kendt.append(f'{r[0][:34]} — {kendte[(kaede, r[0])]}')
            continue
        d = min((dawa.hav(r[3], r[4], p['lat'], p['lon']) for p in med), default=9e9)
        if d > NAER_M and _adr_noegle(r[1].split(',')[0], r[2]) not in reg_adr:
            lukkede.append((r, round(d)))
    return nye, lukkede, uden_punkt, kendt


def vore_raekker(kaede, fil):
    with open(os.path.join(OUT, fil), encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))[1:]
    return [(r[1], r[2], r[3], float(r[5]), float(r[6])) for r in rows if r[0] == kaede]


# ---------------------------------------------------------------- koersel
def _fund_kaede(kaede, kilde, fil, nye, lukkede):
    """Kaedens fund som data til ugentlig_gennemgang.py (--fund): registrets forretninger uden raekke hos os og vores
    raekker uden forretning i registret, med afstand til det naermeste i den anden ende."""
    return {'kilde': kilde, 'fil': fil,
            'nye': [{'navn': p['navn'], 'gade': p['gade'], 'postnr': p['postnr'], 'by': p.get('by', ''),
                     'pnr': p['pnr'], 'lat': p['lat'], 'lon': p['lon'], 'afstand': d} for p, d in nye],
            'lukkede': [{'maerke': kaede, 'navn': r[0], 'adresse': r[1], 'postnr': r[2], 'lat': r[3], 'lon': r[4],
                         'afstand': d} for r, d in lukkede]}


def main(fund_fil=None):
    dawa.tag_dar_laas('kaede_register_tjek.py')     # én DAR-tung koersel ad gangen (se dawa)
    fund, fejlede = {}, []
    rapport = os.path.join(OUT, RAPPORT)
    open(rapport, 'w', encoding='utf-8').write('KÆDE-REGISTERTJEKKET BLEV IKKE FÆRDIGT — ingen rapport for denne kørsel\n')
    smiley = None
    linjer, fejl, n_ny, n_luk = [], 0, 0, 0
    for kaede, cfg in KAEDER.items():
        try:
            if cfg['kilde'] == 'smiley':
                if smiley is None:
                    if not RS._robots_tilladt(SMILEY_URL):
                        raise RuntimeError('robots.txt paa pub.fvst.dk forbyder nu smiley-dataene - henter ikke')
                    smiley = RS._raw(SMILEY_URL, 300)
                poster = smiley_poster(smiley, cfg['navn'], cfg.get('ikke'))
                kilde = 'smiley-registret'
            else:
                poster = cvr_poster(cfg)
                kilde = 'CVR'
            lo, hi = cfg['forventet']
            if not lo <= len(poster) <= hi:
                raise RuntimeError(f'{len(poster)} forretninger i {kilde} (forventet {lo}-{hi}) - registret eller '
                                   f'filteret er aendret; behandles som en koerselsfejl')
            poster = geokod(poster)
        except Exception as e:
            linjer += [f'{kaede}: FEJL — {type(e).__name__}: {dawa._skrub(e)[:200]}', '']
            fejl += 1
            fejlede.append(kaede)
            continue
        raekker = vore_raekker(kaede, cfg['fil'])
        nye, lukkede, uden_punkt, kendt = sammenlign(kaede, raekker, poster)
        n_ny += len(nye); n_luk += len(lukkede)
        fund[kaede] = _fund_kaede(kaede, kilde, cfg['fil'], nye, lukkede)
        linjer.append(f'{kaede}: {len(raekker)} rækker hos os, {len(poster)} forretninger i {kilde} '
                      f'({len(uden_punkt)} uden DAR-punkt); {len(nye)} mulige nye, {len(lukkede)} mulige lukninger')
        for p, d in sorted(nye, key=lambda t: t[0]['postnr']):
            linjer.append(f"  MULIG NY BUTIK  {p['navn'][:36]:36} {p['gade'][:30]}, {p['postnr']} {p['by'][:14]}"
                          f"  (P {p['pnr']}; nærmeste række {d} m)")
        for r, d in sorted(lukkede, key=lambda t: t[0][2]):
            linjer.append(f'  MULIG LUKNING   {r[0][:36]:36} {r[1][:46]}  (nærmeste forretning i {kilde} {d} m)')
        for k in kendt:
            linjer.append(f'  KENDT           {k}'[:200])
        for p in uden_punkt:
            linjer.append(f"  UDEN PUNKT      {p['navn'][:36]:36} {p['gade'][:30]}, {p['postnr']} (P {p['pnr']}) — "
                          f"adressen findes ikke i DAR; ikke vurderet")
        linjer.append('')
    hoved = [f'Kæde-registertjek kørt {time.strftime("%Y-%m-%d %H:%M")} (kaede_register_tjek.py)',
             f'Spærrede kæder holdt op mod smiley-registret og CVR; samme sted = inden for {NAER_M} m eller samme '
             f'adresse.',
             f'{n_ny} mulige nye butikker · {n_luk} mulige lukninger · {fejl} kæde(r) fejlede. KANDIDATER til '
             f'efterprøvning - intet rettes automatisk; afgjorte står i KENDTE.', '']
    open(rapport, 'w', encoding='utf-8').write('\n'.join(hoved + linjer) + '\n')
    print('\n'.join(hoved + linjer))
    if fund_fil:
        with open(fund_fil, 'w', encoding='utf-8') as f:
            json.dump({'koersel': time.strftime('%Y-%m-%d %H:%M'), 'kaeder': fund, 'fejlede': fejlede}, f,
                      ensure_ascii=False, indent=1)
    return 2 if fejl else 0


if __name__ == '__main__':
    sys.exit(main(fund_fil=sys.argv[sys.argv.index('--fund') + 1] if '--fund' in sys.argv else None))
