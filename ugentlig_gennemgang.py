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
  UENIGE    CVR har en AKTIV enhed med kaedens navn paa adressen: kilderne siger noget forskelligt.
  MANGLER   alt andet: kun én kilde (fx ophoert i CVR, men intet andet), eller ingen (CVR har intet paa adressen,
            adressen findes ikke i DAR, eller fundet er en lader, som CVR ikke kender). Registrets mulige nye
            butikker staar altid her: CVR eller smiley er én kilde, og den anden (fx centrets side) findes i haanden.
Hvert fund faar antal uger paa listen fra gennemgang_historik.json (committes hver uge).

Koer:  python3 ugentlig_gennemgang.py      (efter refresh_retail.py --fund og kaede_register_tjek.py --fund)
"""
import datetime, json, os, re, sys, time, unicodedata

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


def _dato(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def vurder(fund, enheder, nye_samme, idag=None):
    """Et fund (dict med maerke, fil, navn, adresse, lat, lon) -> (kategori, belaeg, forslag).

    enheder: CVR-enhederne paa adressen (se enheder_paa_adresse) - None, hvis adressen ikke findes i DAR.
    nye_samme: kaedens nye butikker fra samme koersel (dicts med navn, adresse, lat, lon) - kun fra kaedens EGEN
    liste; registrets fund er samme kilde som CVR og kan ikke vaere den anden kilde.
    forslag er 'SLET' for KLAR, ellers None. Funktionen er ren, saa den kan testes uden net.

    CVR's positive tegn paa, at butikken ikke er der mere: kaedens P-enhed er ophoert (en ophoersdato, der er
    passeret), har en kommende ophoersdato (Matas Vestamager 18-11-2026: aktiv, men ophoer 11-12-2026), eller staar
    stadig som aktiv, men ikke laengere paa adressen (flyttet). En aktiv enhed uden ophoersdato paa adressen i dag
    betyder, at CVR og kilden er uenige."""
    idag = idag or datetime.date.today()
    if fund.get('fil') == 'superladere_dk.csv':
        return 'MANGLER', ['Ladere står ikke i CVR; kun kildens fravær taler for en lukning'], None
    if enheder is None:
        return 'MANGLER', ['Adressen findes ikke i DAR, så CVR kan ikke slås op på den'], None
    rx = maerke_rx(fund['maerke'])
    egne = [e for e in enheder if e.get('type') == 'P' and rx.search(e.get('navn') or '')]
    aktive = [e for e in egne if e.get('status') == 'aktiv' and e.get('nu') and not _dato(e.get('ophoer'))]
    if aktive:
        return 'UENIGE', [f"CVR: P {e['pnr']} «{e['navn']}» er aktiv på adressen"
                          + (f" (siden {e['start']})" if e.get('start') else '') for e in aktive][:3], None
    ophoerte = [e for e in egne if _dato(e.get('ophoer')) and _dato(e['ophoer']) <= idag]
    lukker = [e for e in egne if _dato(e.get('ophoer')) and _dato(e['ophoer']) > idag]
    flyttede = [e for e in egne if e.get('status') == 'aktiv' and not e.get('nu') and not _dato(e.get('ophoer'))]
    belaeg = ([f"CVR: P {e['pnr']} «{e['navn']}» ophørte {e['ophoer'][:10]}" for e in ophoerte]
              + [f"CVR: P {e['pnr']} «{e['navn']}» lukker: ophørsdato {e['ophoer'][:10]}" for e in lukker]
              + [f"CVR: P {e['pnr']} «{e['navn']}» stod på adressen for 6-12 måneder siden og er stadig aktiv, men "
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
            gruppe = {b[:2] for b in sidst.get('brancher') or []}
            for e in aktive_nu:
                start = _dato(e.get('start'))
                if (not rx.search(e.get('navn') or '') and start and start >= slut - datetime.timedelta(NY_LEJER_FOER)
                        and gruppe & {b[:2] for b in e.get('brancher') or []}):
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


def enheder_paa_adresse(vej, husnr, postnr):
    """CVR-enhederne (P-enheder og virksomheder) paa adressen nu og for 6 og 12 maaneder siden: DAR-husnummer ->
    DAR-adresser (alle etager) -> CVR_Adressering -> enheden. -> [dict(type, pnr, navn, status, start, ophoer,
    brancher, nu)] eller None, hvis husnummeret ikke findes i DAR. Status og datoer er enhedens nuvaerende
    registrering; 'nu' siger, om enheden staar paa adressen i dag."""
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
                                             'id pNummer status produktionsenhedStartdato produktionsenhedOphoersdato',
                                             tid)}
            vi = {x['id']: x for x in _sider('CVR_Virksomhed', f'{{id:{{in:{b}}}}}', 'id CVRNummer status', tid)}
            navn, br = {}, {}
            for r in _sider('CVR_Navn', f'{{CVREnhedsId:{{in:{b}}}}}', 'CVREnhedsId vaerdi', tid):
                navn.setdefault(r['CVREnhedsId'], r['vaerdi'])
            for r in _sider('CVR_Branche', f'{{CVREnhedsId:{{in:{b}}}}}', 'CVREnhedsId vaerdi', tid):
                br.setdefault(r['CVREnhedsId'], set()).add(r['vaerdi'])
            for i in mangler[k:k + 100]:
                if i in pe:
                    p = pe[i]
                    info[i] = {'type': 'P', 'pnr': p['pNummer'], 'navn': navn.get(i, ''), 'status': p['status'],
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


# ---------------------------------------------------------------- koerslen
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
    cache, vurderet = {}, []
    for f in fund:
        if f['art'] == 'NY':
            vurderet.append((f, 'MANGLER', [f"{f['registerkilde']}: «{f['navn']}» (P {f['pnr']}) er registreret på "
                                            f"adressen; nærmeste række hos os {f.get('afstand')} m",
                                            'Mangler en kilde mere end registret, fx centrets egen butiksside'], None))
            continue
        dele = adr_dele(f['adresse'], f.get('postnr'))
        enheder = None
        if dele and f.get('fil') != 'superladere_dk.csv':
            try:
                if dele not in cache:
                    cache[dele] = enheder_paa_adresse(*dele)
                enheder = cache[dele]
            except Exception as e:
                fejl.append(f"CVR/DAR-opslag fejlede for {f['adresse']}: {type(e).__name__}: {dawa._skrub(e)[:120]}")
                vurderet.append((f, 'MANGLER', ['CVR-opslaget fejlede denne uge - se fejl nederst'], None))
                continue
        egne_nye = nye.get(f['maerke'], []) if f['kilde'].startswith('kæde:') else []
        kat, belaeg, forslag = vurder(f, enheder, egne_nye)
        vurderet.append((f, kat, belaeg, forslag))
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
        hvor = f['kilde'].replace('kæde:', 'kædens liste: ').replace('register:', 'registertjek: ')
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
