#!/usr/bin/env python3
"""Ugentlig gennemgang (18-11-2026, brugerens valg): ugens mulige lukninger og registertjekkets fund, slaaet op i CVR
og sorteret til godkendelse.

Botten SLETTER ALDRIG selv (brugerens valg 18-11-2026). Den skriver en liste med beviser (ugentlig_gennemgang.txt) og
et faerdigt rettelsesforslag (ugentlig_gennemgang_forslag.json, i anvend.py's format) for de fund, der har to
positive kilder. Brugeren skriver «godkend» (eller «godkend 1, 3»), og forslaget anvendes i haanden med de
saedvanlige kontroller (NABO-tjek, rebuild, tests, validate) foer push.

Fundene kommer fra de to trin foer i workflowet:
  * retail_refresh_fund.json (refresh_retail.py --fund): MULIG LUKNING = kaedens egen liste har ikke laengere
    raekken; NY BUTIK = kaedens liste har en butik, vi ikke havde (tilfoejet i samme koersel). De nye bruges til at
    se flytninger.
  * kaede_register_fund.json (kaede_register_tjek.py --fund): de spaerrede kaeder mod smiley-registret og CVR.

Sortering efter reglen om to positive kilder (fravaer er ikke en kilde):
  KLAR      CVR viser kaedens P-enhed paa adressen som ophoert, OG enten har kaedens egen liste en ny butik inden
            for FLYT_M (flytning), eller en anden forretning i samme branchegruppe er registreret paa adressen efter
            ophoeret (kun paa adresser med hoejst SMAA_ADR aktive enheder - i et center siger en ny lejer intet).
            Branchegruppen er DB25-afdelingen (to cifre); bilhandlens koder (BIL_BRANCHER) er desuden én gruppe.
  UENIGE    CVR har en AKTIV enhed med kaedens navn paa adressen: kilderne siger noget forskelligt.
  MANGLER   alt andet: kun én kilde (fx ophoert i CVR, men intet andet), eller ingen (CVR har intet paa adressen,
            adressen findes ikke i DAR, eller fundet er en lader, som CVR ikke kender). Registrets mulige nye
            butikker staar altid her: CVR eller smiley er én kilde, og den anden (fx centrets side) findes i haanden.
Hvert fund faar antal uger paa listen fra gennemgang_historik.json (committes hver uge).

Koer:  python3 ugentlig_gennemgang.py      (efter refresh_retail.py --fund og kaede_register_tjek.py --fund)
"""
import concurrent.futures, csv, datetime, json, os, re, sys, time, unicodedata, zlib

import cvr_tjek as C
import dawa
import retail_sources as RS

OUT = os.path.dirname(os.path.abspath(__file__))
RETAIL_FUND = 'retail_refresh_fund.json'
REGISTER_FUND = 'kaede_register_fund.json'
RAPPORT = 'ugentlig_gennemgang.txt'
FORSLAG = 'ugentlig_gennemgang_forslag.json'
HISTORIK = 'gennemgang_historik.json'

FLYT_M = 3000          # kaedens nye butik saa taet paa en lukket = en flytning
SMAA_ADR = 3           # en ny lejer taeller kun paa en adresse med hoejst saa mange aktive P-enheder
NY_LEJER_FOER = 90     # dage: en ny lejer maa vaere startet saa laenge foer ophoeret (overlap ved flytning)
TILBAGE_MDR = (0, 6, 12)   # CVR slaas op paa adressen nu og for 6 og 12 maaneder siden
GAMMEL_FUND_TIMER = 36     # en fundfil, der er aeldre, er fra en tidligere koersel og bruges ikke
GLEM_UGER = 8              # et fund, der ikke er set i saa mange uger, slettes af historikken
DELE = 4                   # raekker uden egen kilde: en fjerdedel slaas op i CVR hver uge (alle hver 4. uge)
# 23-11-2026 ramte trinnet GitHubs graense paa 15 min, og ugens liste blev aldrig skrevet: 234 adresser i den rullende
# kontrol a ca. 2,4 s (maalt lokalt; langsommere paa GitHub) slaaet op en ad gangen. Adresserne slaas nu op parallelt
# (dawa og CVR-opslaget taaler traade, se cvr_tjek), ugens fund foerst, og naar TIDSBUDGET_S er brugt, startes ikke
# flere: listen skrives altid, og det, der ikke blev naaet, meldes under FEJL.
TRAADE = 6
TIDSBUDGET_S = 11 * 60
# DB25 (CVR fra 01-01-2025) spreder bilhandlen over flere afdelinger: 46.71 engroshandel med motorkoeretoejer (mange
# brugtvognsforhandlere staar dér, fx Viborg Autohandel og AutoMUS), 47.81 detailhandel, 47.92 agentsalg (Bil & Co,
# Aunsbjerg), 95.31 reparation, 77.11 leasing og motorcyklernes 46.73/47.83/95.32. To cifre alene ser derfor 46, 47
# og 95 som tre brancher; oprydningen 19-11-2026 fandt Viborg Autohandel under «intet i branchen» af den grund.
BIL_BRANCHER = ('4671', '4673', '4781', '4783', '4792', '9531', '9532', '7711')
# Selskabsformer taeller ikke som ord i et navn ('Bilhuset A/S - Kolding' har kun ét ord, 'bilhuset').
SELSKABSFORM = {'as', 'aps', 'ivs', 'is', 'ks', 'amba', 'fmba', 'smba'}

# Ord, der ikke kendetegner en bestemt forretning (forretningens by og vej taeller heller ikke): 'Skive Bilhus' er
# ikke 'LS Autoteknik' i Skive, fordi de begge er biler i Skive.
GENERISK = {'aps', 'as', 'ivs', 'og', 'the', 'biler', 'bil', 'bilhus', 'bilhuset', 'auto', 'autohus', 'autohuset',
            'automobiler', 'autocenter', 'autoservice', 'bilcenter', 'center', 'centret', 'centeret', 'motor',
            'motors', 'vaerksted', 'pladevaerksted', 'autovaerksted', 'planteskole', 'planteskolen', 'havecenter',
            'havecentret', 'garden', 'gardencenter', 'camping', 'caravan', 'marine', 'baad', 'baade', 'service',
            'handel', 'co', 'group', 'gruppen', 'danmark', 'dk', 'holding', 'ejendomme', 'ejendom', 'salg', 'afd',
            'afdeling', 'filial', 'brugtbiler', 'brugtvogne', 'vogne', 'import', 'leasing', 'udlejning', 'teknik',
            'autoteknik', 'biludlejning', 'forhandler', 'bilforhandler'}
# Forretninger, hvis enheder i CVR hedder noget helt andet end maerket: ECCO's butikker hedder 'KRM <sted>', og
# oprydningen 18-11-2026 fandt fire forkortelser ('A&M Biler Glostrup' = Andersen & Martini osv.). 19-11-2026 kom
# fire til, hver med belaeg: RK Biler er R.Koch Automobiler ApS (Bilbasens side for R.Koch: «Hos RK Biler»,
# rkbiler.dk; holdingselskabet paa adressen er ikke forretningen), BoConcept Ishoej drives af BC Commercial A/S
# (moderselskab BoConcept A/S), og CVR staver «STAVRBYSKOV HAVECENTER» og «Storstrøm Camping Service» (uden genitiv-s).
NAVN_ALIAS = {'Ecco': r'\bkrm\b', 'Andersen & Martini': r'\ba\s*&\s*m\b', 'Auto Group Nordvest': r'\bagn\b',
              'OHA Biler': r'\bole\s+hansen\s+automobiler\b', 'Kai Dige Bach': r'\bkdb\b',
              'RK Biler': r'\br\.?\s*koch\s+automobiler\b', 'BoConcept': r'\bbc\s+commercial\b',
              'Staurbyskov Havecenter': r'\bstavrbyskov\b',
              'Storstrøms Camping Service': r'\bstorstr(?:ø|oe)m\s+camping\b'}

FIL_PRAEFIKS = {'dagligvarer_dk.csv': 'daglig', 'udvalgsvarer_dk.csv': 'udvalg', 'pladskraevende_dk.csv': 'plads',
                'fastfood_kaeder_dk.csv': 'food', 'tankstationer_dk.csv': 'tank', 'superladere_dk.csv': 'lade'}

# Kaeder, hvis enheder i CVR hedder noget andet end maerket i vores data. Ellers bygges moenstret af maerkets ord.
MAERKE_NAVN = {
    'Coop 365discount': r'365\s*discount',
    'Apoteksudsalg': r'apotek',
    'Apotek': r'apotek',
    'Gasoline Grill': r'gasoline',
    'Sunset Boulevard': r'sunset',
    'H&M': r'\bh\s*&\s*m\b|hennes',
    "McDonald's": r'mc\s*donald',
    'Joe & The Juice': r'joe\s*(?:&|and)?\s*the\s*juice',
}


# ---------------------------------------------------------------- rene hjaelpere (testes uden net)
def maerke_rx(maerke):
    """Maerket -> moenster for kaedens navn i CVR ('Let-Køb' matcher 'LETKØB Bedsted', '7-Eleven' '7-ELEVEN ...')."""
    if maerke in MAERKE_NAVN:
        return re.compile(MAERKE_NAVN[maerke], re.I)
    ord_ = re.findall(r'[0-9a-zæøåäöüé]+', maerke.lower())
    return re.compile(r'\b' + r'\W*'.join(map(re.escape, ord_)) + r'\b', re.I) if ord_ else re.compile(r'(?!)')


def adr_dele(adresse, postnr):
    """'Ryvangs Allé 87, 2900 Hellerup' -> ('Ryvangs Allé', '87', '2900'); None, hvis der ikke er et husnummer."""
    s = re.sub(r',?\s*\d{4}\s+[^,\d][^,]*$', '', adresse or '').strip()
    s = RS._vej_nr(s)
    m = re.match(r'^(.*\S)\s+(\d+[A-Za-zÆØÅ]?)$', s)
    if not m or not re.fullmatch(r'\d{4}', str(postnr or '')):
        return None
    return m.group(1), m.group(2).upper(), str(postnr)


def _navne_toks(s):
    """Navnets ord med smaa bogstaver og æøå foldet; en raekke enkeltbogstaver laegges sammen ('M.K.' og 'F S' bliver
    'mk' og 'fs', saa 'MK Biler' genkender 'M.K. Biler v/Max Ørskov Kristensen')."""
    s = unicodedata.normalize('NFKD', (s or '').lower().replace('æ', 'ae').replace('ø', 'oe').replace('å', 'aa'))
    ud, run = [], ''
    for o in re.findall(r'[a-z0-9]+', s.encode('ascii', 'ignore').decode()):
        if len(o) == 1 and o.isalpha():
            run += o
            continue
        if run:
            ud.append(run)
            run = ''
        ud.append(o)
    if run:
        ud.append(run)
    return [o for o in ud if len(o) > 1]


def navne_hit(raekke, vej=''):
    """Vores raekke (Maerke, Navn, Adresse, Postnr, By, ...) -> navn -> bool for CVR-enheder med forretningens navn.
    Kendetegnende ord (ikke GENERISK, ikke byen, ikke vejen) skal gaa igen - som ord eller, fra 4 tegn, inde i det
    sammenskrevne navn ('Hobbyhaven' = 'HOBBY-HAVEN ApS'). Har navnet ingen kendetegnende ord ('Skive Bilhus'), skal
    alle dets ord gaa igen."""
    maerke, navn = raekke[0], raekke[1]
    by = raekke[4] if len(raekke) > 4 else ''
    alias = NAVN_ALIAS.get(maerke)
    alle = list(dict.fromkeys(_navne_toks(navn) + _navne_toks(maerke)))
    sted = set(_navne_toks(by)) | set(_navne_toks(vej))
    saer = [t for t in alle if t not in GENERISK and t not in sted and not t.isdigit()]
    rest = [t for t in alle if not t.isdigit()]

    # Selskabsformen er ikke en del af navnet ('Skive Bilhus ApS' = 'SKIVE BILHUS A/S'). Uden kendetegnende ord kan
    # byen desuden vaere en afdelingsbetegnelse: 'Bil & Co. A/S - Haderslev' er 'BIL & CO. A/S' i CVR (oprydningen
    # 19-11-2026 fandt den under «intet i branchen»). Saa er de andre ord nok - men kun naar der er mindst to,
    # ellers er 'Skive Bilhus' bare 'Bilhus'.
    ord_ = [t for t in rest if t not in SELSKABSFORM]
    uden_sted = [t for t in ord_ if t not in sted]

    def hit(cvr_navn):
        if alias and re.search(alias, cvr_navn or '', re.I):
            return True
        nt = _navne_toks(cvr_navn)
        if saer:
            samlet = ''.join(nt)
            return any(t in nt or (len(t) >= 4 and t in samlet) for t in saer)
        if ord_ and all(t in nt for t in ord_):
            return True
        return len(uden_sted) >= 2 and all(t in nt for t in uden_sted)
    return hit


def _grupper(brancher):
    """Branchekoder -> grupperne til «ny forretning i samme branche»: DB25-afdelingen (to cifre) og 'bil' for
    bilhandlens koder (BIL_BRANCHER). En bilforhandler, der afloeses af en brugtvognshandel (46.71) eller et vaerksted
    (95.31), har saa en afloeser i samme branche; en dagligvarebutik, der afloeses af et vaerksted, har ikke."""
    g = set()
    for b in brancher or ():
        g.add(b[:2])
        if b.startswith(BIL_BRANCHER):
            g.add('bil')
    return g


def _egen(e, hit):
    """Er CVR-enheden forretningens egen? P-enhedens navn ELLER navnet paa selskabet bag den ('firma', se
    enheder_paa_adresse). En P-enheds navn kan halte efter selskabets: Havlykke Biler ApS' eneste enhed, Vejlevej 16B,
    hed stadig «Sand & Sten ApS» 19-11-2026, saa den rullende kontrol saa ikke, at forretningen var der."""
    return bool(hit(e.get('navn') or '') or hit(e.get('firma') or ''))


def _vis(e, hit):
    """«enhedens navn» - plus selskabets navn, naar det var det, der genkendte enheden."""
    s = f"«{e.get('navn') or ''}»"
    if e.get('firma') and not hit(e.get('navn') or '') and hit(e['firma']):
        s += f" (selskabet «{e['firma']}»)"
    return s


def uge_udvalg(raekker, uge):
    """Den fjerdedel af raekkerne [(fil, raekke)], der slaas op i uge 'uge' - fast pr. raekke (crc32 af fil, navn og
    adresse), saa hver raekke kommer med netop én gang paa DELE uger i traek."""
    return [(fn, r) for fn, r in raekker
            if zlib.crc32(f'{fn}|{r[1]}|{r[2]}'.encode('utf-8')) % DELE == uge % DELE]


def _dato(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def vurder(fund, enheder, nye_samme, idag=None, hit=None):
    """Et fund (dict med maerke, fil, navn, adresse, lat, lon) -> (kategori, belaeg, forslag).

    enheder: CVR-enhederne paa adressen (se enheder_paa_adresse) - None, hvis adressen ikke findes i DAR.
    nye_samme: kaedens nye butikker fra samme koersel (dicts med navn, adresse, lat, lon) - kun fra kaedens EGEN
    liste; registrets fund er samme kilde som CVR og kan ikke vaere den anden kilde.
    forslag er 'SLET' for KLAR, ellers None. Funktionen er ren, saa den kan testes uden net.

    CVR's positive tegn paa, at butikken ikke er der mere: kaedens P-enhed er ophoert (en ophoersdato, der er
    passeret), har en kommende ophoersdato (Matas Vestamager 18-11-2026: aktiv, men ophoer 11-12-2026), eller staar
    stadig som aktiv, men ikke laengere paa adressen (flyttet). En aktiv enhed uden ophoersdato paa adressen i dag
    betyder, at CVR og kilden er uenige.

    hit: navn -> bool for 'kaedens' enheder (standard: maerkets moenster, maerke_rx); den rullende CVR-kontrol af
    raekker uden egen kilde bruger navne_hit (forretningens eget navn)."""
    idag = idag or datetime.date.today()
    if fund.get('fil') == 'superladere_dk.csv':
        return 'MANGLER', ['Ladere står ikke i CVR; kun kildens fravær taler for en lukning'], None
    if enheder is None:
        return 'MANGLER', ['Adressen findes ikke i DAR, så CVR kan ikke slås op på den'], None
    hit = hit or maerke_rx(fund['maerke']).search
    egne = [e for e in enheder if e.get('type') == 'P' and _egen(e, hit)]
    aktive = [e for e in egne if e.get('status') == 'aktiv' and e.get('nu') and not _dato(e.get('ophoer'))]
    if aktive:
        return 'UENIGE', [f"CVR: P {e['pnr']} {_vis(e, hit)} er aktiv på adressen"
                          + (f" (siden {e['start']})" if e.get('start') else '') for e in aktive][:3], None
    ophoerte = [e for e in egne if _dato(e.get('ophoer')) and _dato(e['ophoer']) <= idag]
    lukker = [e for e in egne if _dato(e.get('ophoer')) and _dato(e['ophoer']) > idag]
    flyttede = [e for e in egne if e.get('status') == 'aktiv' and not e.get('nu') and not _dato(e.get('ophoer'))]
    belaeg = ([f"CVR: P {e['pnr']} {_vis(e, hit)} ophørte {e['ophoer'][:10]}" for e in ophoerte]
              + [f"CVR: P {e['pnr']} {_vis(e, hit)} lukker: ophørsdato {e['ophoer'][:10]}" for e in lukker]
              + [f"CVR: P {e['pnr']} {_vis(e, hit)} stod på adressen for 6-12 måneder siden og er stadig aktiv, men "
                 f"nu registreret et andet sted" for e in flyttede])[:3]
    if not belaeg:
        return 'MANGLER', ['CVR har ingen enhed med kædens navn på adressen (hverken nu eller for 6 og 12 måneder '
                           'siden)'], None
    andet = []
    for n in nye_samme:
        if fund.get('lat') is None or n.get('lat') is None:
            continue
        d = dawa.hav(fund['lat'], fund['lon'], n['lat'], n['lon'])
        if d <= FLYT_M:
            andet.append(f"Kædens egen liste har nu «{n['navn']}», {n['adresse']} ({round(d)} m herfra), som samme "
                         f"kørsel fandt som ny butik - en flytning")
    if ophoerte:
        sidst = max(ophoerte, key=lambda e: _dato(e['ophoer']))
        slut = _dato(sidst['ophoer'])
        aktive_nu = [e for e in enheder if e.get('type') == 'P' and e.get('status') == 'aktiv' and e.get('nu')]
        if len(aktive_nu) <= SMAA_ADR:
            gruppe = _grupper(sidst.get('brancher'))
            for e in aktive_nu:
                start = _dato(e.get('start'))
                if (not _egen(e, hit) and start and start >= slut - datetime.timedelta(NY_LEJER_FOER)
                        and gruppe & _grupper(e.get('brancher'))):
                    andet.append(f"CVR: «{e['navn']}» (P {e['pnr']}, branche {', '.join(e['brancher'])}) er "
                                 f"registreret på adressen fra {start.isoformat()} - en ny forretning i samme branche")
    if andet and (ophoerte or flyttede):
        return 'KLAR', belaeg + andet[:2], 'SLET'
    if lukker and not ophoerte:
        return 'MANGLER', belaeg + andet[:1] + ['Butikken står til at lukke; slet rækken, når datoen er passeret, og '
                                                'en kilde mere bekræfter det'], None
    return 'MANGLER', belaeg + ['Mangler en kilde mere: kædens nye adresse eller en ny forretning på adressen'], None


def noegle(f):
    """Fundets faste noegle i historikken."""
    if f.get('pnr'):
        return f"{f['kilde']}|P{f['pnr']}"
    return f"{f['kilde']}|{f.get('fil', '')}|{f['maerke']}|{f['navn']}|{f['adresse']}"


def opdater_historik(historik, noegler, idag):
    """-> ny historik: {noegle: {'foerst': dato, 'sidst': dato}}. Et fund, der ikke er set i GLEM_UGER, glemmes;
    kommer det igen, starter det forfra."""
    ny = {}
    for k, v in historik.items():
        if k not in noegler and (idag - _dato(v['sidst'])).days < 7 * GLEM_UGER:
            ny[k] = v
    for k in noegler:
        ny[k] = {'foerst': historik.get(k, {}).get('foerst', idag.isoformat()), 'sidst': idag.isoformat()}
        if k in historik and (idag - _dato(historik[k]['sidst'])).days > 14:
            ny[k]['foerst'] = idag.isoformat()      # vaek i mere end to uger: et nyt fund
    return ny


def uger(historik, k, idag):
    return (idag - _dato(historik[k]['foerst'])).days // 7 + 1


def forslag_post(nr, f, belaeg):
    """KLAR -> en post i anvend.py's format. 'fra' er raekkens felter, saa anvend.py finder netop den raekke."""
    pr = FIL_PRAEFIKS.get(f['fil'], 'plads')
    return {'nr': nr, 'handling': 'fjern', 'id': f"{pr}:{f['navn']}", 'fil': f['fil'],
            'fra': {'Mærke': f['maerke'], 'Navn': f['navn'], 'Adresse': f['adresse']},
            'kilder': f"Ugentlig gennemgang {time.strftime('%d-%m-%Y')}: " + '; '.join(belaeg) + '.'}


# ---------------------------------------------------------------- CVR paa en adresse (net)
def _sider(entitet, where, felter, tid):
    ud, after = [], None
    for _ in range(20):
        a = f', after:{json.dumps(after)}' if after else ''
        d = C._q(f'{{ {entitet}(first:1000{a}, virkningstid:"{tid}", where:{where}) '
                 f'{{ pageInfo{{hasNextPage endCursor}} nodes {{ {felter} }} }} }}')[entitet]
        ud += d['nodes']
        if not d['pageInfo']['hasNextPage']:
            return ud
        after = d['pageInfo']['endCursor']
    raise RuntimeError(f'{entitet}: over 20 sider')


def _tider(nu=None):
    nu = nu or datetime.datetime.now(datetime.timezone.utc)
    return [(nu - datetime.timedelta(days=round(30.44 * m))).strftime('%Y-%m-%dT12:00:00Z') for m in TILBAGE_MDR]


def _vej_noegle(vej):
    """'Ryvangs Allé' = 'Ryvangs Alle', 'Gl. Kongevej' = 'Gammel Kongevej' (som refresh_retail._adr_noegle)."""
    s = re.sub(r'\bgl\.?\s', 'gammel ', (vej or '').lower())
    s = unicodedata.normalize('NFKD', s.replace('æ', 'ae').replace('ø', 'oe').replace('å', 'aa'))
    return re.sub(r'[^0-9a-z]', '', s.encode('ascii', 'ignore').decode())


def _husnumre(vej, husnr, postnr):
    """DAR-husnummerets id'er for 'vej husnr' i postnr. Vores stavemaade kan afvige fra DAR's: 'Ryvangs Allé 87' hedder
    'Ryvangs Alle 87' i DAR (proeven 18-11-2026 meldte derfor Netto Ryvangs Allé som 'findes ikke i DAR', skoent CVR
    har Netto aktiv dér). Saa slaas adressen op gennem retail_sources._oil_geokod (stavevariant, Adressevask), men kun
    SAMME vej og PRAECIS samme husnummer godtages - husnummerfamilien (228 for 229) er en anden adresse."""
    hn = dawa._q(vejnavn=vej, husnr=husnr, postnr=postnr, per_side=10)
    ids = [h['id'] for h in hn if str(h.get('husnr', husnr)).upper() == husnr.upper()]
    if ids:
        return ids
    hit, _ = RS._oil_geokod(f'{vej} {husnr}', postnr)
    if (hit and hit.get('id') and str(hit.get('husnr', '')).upper() == husnr.upper()
            and _vej_noegle(hit.get('vejnavn')) == _vej_noegle(vej) and str(hit.get('postnr', postnr)) == str(postnr)):
        return [hit['id']]
    return []


def _firmanavne(cvrnumre, tid):
    """CVR-numre -> {cvr: selskabets navn paa tiden tid}."""
    ud, cs = {}, sorted({c for c in cvrnumre if c})
    for k in range(0, len(cs), 100):
        vi = _sider('CVR_Virksomhed', f'{{CVRNummer:{{in:{json.dumps(cs[k:k + 100])}}}}}', 'id CVRNummer', tid)
        ids = {v['id']: v['CVRNummer'] for v in vi}
        if ids:
            w = f'{{CVREnhedsId:{{in:{json.dumps(sorted(ids))}}}}}'
            for r in _sider('CVR_Navn', w, 'CVREnhedsId vaerdi', tid):
                ud.setdefault(ids[r['CVREnhedsId']], r['vaerdi'])
    return ud


def enheder_paa_adresse(vej, husnr, postnr):
    """CVR-enhederne (P-enheder og virksomheder) paa adressen nu og for 6 og 12 maaneder siden: DAR-husnummer ->
    DAR-adresser (alle etager) -> CVR_Adressering -> enheden. -> [dict(type, pnr, navn, firma, status, start, ophoer,
    brancher, nu)] eller None, hvis husnummeret ikke findes i DAR. Status og datoer er enhedens nuvaerende
    registrering; 'nu' siger, om enheden staar paa adressen i dag. 'firma' er navnet paa selskabet bag en P-enhed
    (se _egen: P-enhedens eget navn kan vaere et gammelt)."""
    hids = _husnumre(vej, husnr, postnr)
    if not hids:
        return None
    aids = [x['id_lokalId'] for x in dawa._alle('DAR_Adresse', f'{{husnummer:{{in:{json.dumps(hids)}}}}}', 'id_lokalId')]
    tider = _tider()
    set_ = {}
    for tid in tider:
        for k in range(0, len(aids), 100):
            for r in _sider('CVR_Adressering', f'{{Adresse:{{in:{json.dumps(aids[k:k + 100])}}}}}', 'CVREnhedsId', tid):
                set_.setdefault(r['CVREnhedsId'], []).append(tid)
    # Enheden slaas op paa den seneste tid, den stod paa adressen: en ophoert P-enhed findes ikke i CVR i dag
    # (proeve 18-11-2026: Skechers Outlet Ringsted, ophoert 31-08-2026, forsvandt helt, da alt blev slaaet op paa
    # dags dato). Status og datoer er enhedens nuvaerende registrering - ogsaa naar den slaas op paa en gammel tid.
    info = {}
    for tid in tider:
        mangler = [i for i in sorted(set_) if tid in set_[i] and i not in info]
        for k in range(0, len(mangler), 100):
            b = json.dumps(mangler[k:k + 100])
            pe = {x['id']: x for x in _sider('CVR_Produktionsenhed', f'{{id:{{in:{b}}}}}',
                                             'id pNummer status produktionsenhedStartdato produktionsenhedOphoersdato '
                                             'tilknyttetVirksomhedsCVRNummer', tid)}
            firma = _firmanavne([p.get('tilknyttetVirksomhedsCVRNummer') for p in pe.values()], tid)
            vi = {x['id']: x for x in _sider('CVR_Virksomhed', f'{{id:{{in:{b}}}}}', 'id CVRNummer status', tid)}
            navn, br = {}, {}
            for r in _sider('CVR_Navn', f'{{CVREnhedsId:{{in:{b}}}}}', 'CVREnhedsId vaerdi', tid):
                navn.setdefault(r['CVREnhedsId'], r['vaerdi'])
            for r in _sider('CVR_Branche', f'{{CVREnhedsId:{{in:{b}}}}}', 'CVREnhedsId vaerdi', tid):
                br.setdefault(r['CVREnhedsId'], set()).add(r['vaerdi'])
            for i in mangler[k:k + 100]:
                if i in pe:
                    p = pe[i]
                    info[i] = {'type': 'P', 'pnr': p['pNummer'], 'navn': navn.get(i, ''),
                               'firma': firma.get(p.get('tilknyttetVirksomhedsCVRNummer'), ''), 'status': p['status'],
                               'start': p.get('produktionsenhedStartdato'),
                               'ophoer': p.get('produktionsenhedOphoersdato'), 'brancher': sorted(br.get(i, ())),
                               'nu': tider[0] in set_[i]}
                elif i in vi:
                    v = vi[i]
                    info[i] = {'type': 'CVR', 'pnr': v['CVRNummer'], 'navn': navn.get(i, ''), 'status': v['status'],
                               'start': None, 'ophoer': None, 'brancher': sorted(br.get(i, ())),
                               'nu': tider[0] in set_[i]}
    ud = [info[i] for i in sorted(info)]
    return ud


def slaa_op(adresser, frist=None, traade=None):
    """[(vej, husnr, postnr)] -> ({adresse: enheder eller None}, {adresse: fejltekst}, [adresser der ikke blev naaet]).
    Slaar adresserne op parallelt med enheder_paa_adresse i den givne raekkefoelge (ugens fund foerst). Naar fristen
    (time.monotonic()) er naaet, startes ingen nye opslag; de igangvaerende goeres faerdige."""
    unikke = list(dict.fromkeys(adresser))
    svar, fejl = {}, {}
    if not unikke:
        return svar, fejl, []
    ex = concurrent.futures.ThreadPoolExecutor(traade or TRAADE)
    try:
        fut = {ex.submit(enheder_paa_adresse, *a): a for a in unikke}
        rest = None if frist is None else max(0.0, frist - time.monotonic())
        concurrent.futures.wait(fut, timeout=rest)
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
    for f, a in fut.items():
        if f.cancelled() or not f.done():
            continue
        e = f.exception()
        if e is None:
            svar[a] = f.result()
        else:
            fejl[a] = f'{type(e).__name__}: {dawa._skrub(e)[:120]}'
    return svar, fejl, [a for a in unikke if a not in svar and a not in fejl]


# ---------------------------------------------------------------- koerslen
def uden_kilde_raekker():
    """Raekkerne uden en ugentlig kilde: maerket ejes ikke af en aktiv henter (refresh_retail.EJER og KAEDER), er ikke
    OK's tankanlaeg (refresh_data) og ikke en af registertjekkets kaeder. Ladere tages ikke med: de staar ikke i CVR.
    Bilforhandlere, som kun et bilmaerkes liste melder om, tages med: CVR ser andet end maerkelisten. 18-11-2026: 989
    raekker (631 uden nogen ugentlig kilde, 358 med kun en bilmaerkeliste); 248 i uge 47, 3,5 minut."""
    import kaede_register_tjek as K
    import refresh_retail as R
    aktive = {n for n, _ in R.KAEDER}
    egne = {m for h, ms in R.EJER.items() if h in aktive for m in ms}
    ud = []
    for fn in FIL_PRAEFIKS:
        if fn == 'superladere_dk.csv':
            continue
        with open(os.path.join(OUT, fn), encoding='utf-8-sig', newline='') as fh:
            rows = list(csv.reader(fh))[1:]
        ud += [(fn, r) for r in rows
               if r[0] not in egne and r[0] not in K.KAEDER and not (fn == 'tankstationer_dk.csv' and r[0] == 'OK')]
    return ud


def _tal(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _laes_fund(navn, fejl):
    sti = os.path.join(OUT, navn)
    if not os.path.exists(sti):
        fejl.append(f'{navn} mangler (trinnet før fejlede eller kørte uden --fund)')
        return None
    if time.time() - os.path.getmtime(sti) > GAMMEL_FUND_TIMER * 3600:
        fejl.append(f'{navn} er over {GAMMEL_FUND_TIMER} timer gammel - fra en tidligere kørsel, bruges ikke')
        return None
    with open(sti, encoding='utf-8') as fh:
        return json.load(fh)


def saml_fund(retail, register):
    """De to fundfiler -> (fund, nye pr. maerke fra kaedernes egne lister)."""
    fund, nye = [], {}
    if retail:
        for f in retail.get('mulige_lukninger', []):
            fund.append(dict(f, kilde=f"kæde:{f['henter']}", art='LUKNING'))
        for n in retail.get('nye', []):
            nye.setdefault(n['maerke'], []).append(n)
    if register:
        for kaede, k in register.get('kaeder', {}).items():
            for r in k.get('lukkede', []):
                fund.append(dict(r, fil=k['fil'], kilde=f"register:{kaede}", art='LUKNING', registerkilde=k['kilde']))
            for p in k.get('nye', []):
                fund.append({'kilde': f'register:{kaede}', 'art': 'NY', 'maerke': kaede, 'fil': k['fil'],
                             'navn': p['navn'], 'adresse': f"{p['gade']}, {p['postnr']} {p.get('by', '')}".strip(),
                             'postnr': p['postnr'], 'pnr': p['pnr'], 'lat': p['lat'], 'lon': p['lon'],
                             'afstand': p.get('afstand'), 'registerkilde': k['kilde']})
    return fund, nye


def main():
    dawa.tag_dar_laas('ugentlig_gennemgang.py')     # én DAR-tung koersel ad gangen (se dawa)
    rapport = os.path.join(OUT, RAPPORT)
    open(rapport, 'w', encoding='utf-8').write('UGENTLIG GENNEMGANG BLEV IKKE FÆRDIG — ingen liste denne uge\n')
    idag = datetime.date.today()
    fejl = []
    retail, register = _laes_fund(RETAIL_FUND, fejl), _laes_fund(REGISTER_FUND, fejl)
    fund, nye = saml_fund(retail, register)
    # Rullende CVR-kontrol af raekkerne uden egen ugentlig kilde (18-11-2026): en fjerdedel hver uge, saa alle slaas op
    # hver DELE. uge. Kun en AENDRING kommer paa listen: forretningens enhed (dens eget navn, se navne_hit) er ophoert,
    # lukker eller er flyttet fra adressen. En aktiv enhed er i orden; intet med navnet kan CVR ikke afgoere (fuld
    # gennemgang 18-11-2026: 113 med en anden forretning paa adressen, 109 uden enheder - en oprydning for sig).
    uge = idag.isocalendar()[1]
    try:
        uden = uden_kilde_raekker()
    except Exception as e:
        uden = []
        fejl.append(f'raekkerne uden egen kilde kunne ikke laeses: {type(e).__name__}: {e}'[:200])
    udvalg, n_aendret = uge_udvalg(uden, uge), 0
    # Alle CVR-opslag paa een gang, parallelt og inden for tidsbudgettet - ugens fund foerst (se TIDSBUDGET_S).
    fund_adr = [d for f in fund if f['art'] != 'NY' and f.get('fil') != 'superladere_dk.csv'
                for d in [adr_dele(f['adresse'], f.get('postnr'))] if d]
    rul_adr = [d for _, r in udvalg for d in [adr_dele(r[2], r[3])] if d]
    cache, opslag_fejl, ikke_naaet = slaa_op(fund_adr + rul_adr, frist=time.monotonic() + TIDSBUDGET_S)
    if ikke_naaet:
        ik = set(ikke_naaet)
        fejl.append(f'tidsbudgettet ({TIDSBUDGET_S // 60} min) slap op: {len(ikke_naaet)} af '
                    f'{len(set(fund_adr + rul_adr))} adresser blev ikke slået op ({len(ik & set(fund_adr))} af ugens '
                    f'fund og {len(ik & set(rul_adr))} rækker uden egen kilde, som tages igen om {DELE} uger)')
    vurderet = []
    for f in fund:
        if f['art'] == 'NY':
            vurderet.append((f, 'MANGLER', [f"{f['registerkilde']}: «{f['navn']}» (P {f['pnr']}) er registreret på "
                                            f"adressen; nærmeste række hos os {f.get('afstand')} m",
                                            'Mangler en kilde mere end registret, fx centrets egen butiksside'], None))
            continue
        dele = adr_dele(f['adresse'], f.get('postnr'))
        enheder = None
        if dele and f.get('fil') != 'superladere_dk.csv':
            if dele in opslag_fejl:
                fejl.append(f"CVR/DAR-opslag fejlede for {f['adresse']}: {opslag_fejl[dele]}")
                vurderet.append((f, 'MANGLER', ['CVR-opslaget fejlede denne uge - se fejl nederst'], None))
                continue
            if dele not in cache:
                vurderet.append((f, 'MANGLER', ['CVR-opslaget nåede ikke at køre denne uge (tidsbudgettet) - se fejl '
                                                'nederst'], None))
                continue
            enheder = cache[dele]
        egne_nye = nye.get(f['maerke'], []) if f['kilde'].startswith('kæde:') else []
        kat, belaeg, forslag = vurder(f, enheder, egne_nye)
        vurderet.append((f, kat, belaeg, forslag))
    n_slaaet_op = 0
    for fn, r in udvalg:
        dele = adr_dele(r[2], r[3])
        if not dele:
            continue
        if dele in opslag_fejl:
            fejl.append(f"CVR/DAR-opslag fejlede for {r[2]}: {opslag_fejl[dele]}")
            continue
        if dele not in cache:
            continue
        n_slaaet_op += 1
        enheder = cache[dele]
        if not enheder:
            continue
        hit = navne_hit(r, dele[0])
        egne = [e for e in enheder if e.get('type') == 'P' and _egen(e, hit)]
        if not egne or any(e.get('status') == 'aktiv' and e.get('nu') and not _dato(e.get('ophoer')) for e in egne):
            continue
        f = {'kilde': 'cvr:uden-kilde', 'art': 'LUKNING', 'fil': fn, 'maerke': r[0], 'navn': r[1], 'adresse': r[2],
             'postnr': r[3], 'lat': _tal(r[5]), 'lon': _tal(r[6])}
        vurderet.append((f, *vurder(f, enheder, [], idag, hit)))
        n_aendret += 1
    historik_sti = os.path.join(OUT, HISTORIK)
    historik = {}
    if os.path.exists(historik_sti):
        with open(historik_sti, encoding='utf-8') as fh:
            historik = json.load(fh)
    historik = opdater_historik(historik, {noegle(f) for f, *_ in vurderet}, idag)
    with open(historik_sti, 'w', encoding='utf-8') as fh:
        json.dump(dict(sorted(historik.items())), fh, ensure_ascii=False, indent=1)

    raekkef = {'KLAR': 0, 'UENIGE': 1, 'MANGLER': 2}
    vurderet.sort(key=lambda t: (raekkef[t[1]], -uger(historik, noegle(t[0]), idag), t[0]['maerke'], t[0]['navn']))
    overskrift = {'KLAR': 'KLAR TIL GODKENDELSE — to positive kilder; forslaget står i ' + FORSLAG,
                  'UENIGE': 'KILDERNE ER UENIGE — kædens liste eller registret mangler den, men CVR har den aktiv',
                  'MANGLER': 'MANGLER EN KILDE — kun én kilde (eller ingen); står igen næste uge, til den er afklaret'}
    linjer, forslag, nr, sidste = [], [], 0, None
    for f, kat, belaeg, fs in vurderet:
        if kat != sidste:
            linjer += ['', overskrift[kat]]
            sidste = kat
        nr += 1
        u = uger(historik, noegle(f), idag)
        hvad = 'SLET' if fs == 'SLET' else ('NY?' if f['art'] == 'NY' else 'LUKKET?')
        hvor = (f['kilde'].replace('kæde:', 'kædens liste: ').replace('register:', 'registertjek: ')
                .replace('cvr:uden-kilde', 'CVR-tjek, ingen egen liste'))
        linjer.append(f"  {nr:3}. {hvad:7} {f['maerke']} | {f['navn'][:40]} | {f['adresse'][:60]}  "
                      f"({hvor}; {u} uge{'r' if u != 1 else ''} på listen)")
        linjer += [f'         - {b}' for b in belaeg]
        if fs == 'SLET':
            forslag.append(forslag_post(nr, f, belaeg))
    n = {k: sum(1 for _, kk, *_ in vurderet if kk == k) for k in raekkef}
    hoved = [f'Ugentlig gennemgang {time.strftime("%Y-%m-%d %H:%M")} (ugentlig_gennemgang.py)',
             'Mulige lukninger fra kædernes egne lister og registertjekkets fund, slået op i CVR. Botten sletter aldrig '
             'selv; skriv «godkend» (eller «godkend 1, 3») for at anvende forslagene under KLAR.',
             f'{len(vurderet)} fund: {n["KLAR"]} klar til godkendelse · {n["UENIGE"]} hvor kilderne er uenige · '
             f'{n["MANGLER"]} der mangler en kilde · {len(fejl)} fejl.']
    if retail:
        hoved.append(f"Kædernes lister: kørslen {retail.get('koersel')}" + ('' if retail.get('apply') else
                     ' (PRØVEKØRSEL - intet tilføjet)') + (f"; fejlede hentere: {', '.join(retail['fejlede_hentere'])}"
                     if retail.get('fejlede_hentere') else ''))
    hoved.append(f'Rækker uden egen kilde: {n_slaaet_op} af {len(uden)} slået op i CVR i uge {uge} (ugens del er '
                 f'{len(udvalg)}; alle hver {DELE}. uge); {n_aendret} med en ændring i CVR.')
    if register:
        hoved.append(f"Registertjekket: kørslen {register.get('koersel')}" +
                     (f"; fejlede kæder: {', '.join(register['fejlede'])}" if register.get('fejlede') else ''))
    hale = ['', 'FEJL'] + [f'  - {x}' for x in fejl] if fejl else []
    tekst = '\n'.join(hoved + linjer + hale) + '\n'
    with open(rapport, 'w', encoding='utf-8') as fh:
        fh.write(tekst)
    with open(os.path.join(OUT, FORSLAG), 'w', encoding='utf-8') as fh:
        json.dump(forslag, fh, ensure_ascii=False, indent=1)
    print(tekst)
    return 2 if fejl else 0


if __name__ == '__main__':
    sys.exit(main())
