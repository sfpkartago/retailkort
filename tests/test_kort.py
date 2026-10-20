import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

import json
import math
import shutil
import subprocess
import tempfile
import unicodedata
import unittest

ROD = hjaelp.ROD
KORT = os.path.join(ROD, 'kort_soeg.html')
START, SLUT = '/* ANALYSE-START', '/* ANALYSE-SLUT */'
LAG = ['daglig', 'udvalg', 'plads', 'food', 'tank', 'charge', 'tanktruck', 'truck']


def _html():
    with open(KORT, encoding='utf-8') as f:
        return f.read()


def _hav(a, b, c, d):
    r = math.pi / 180
    s = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(s))


def _punkt(lat, lon, km_nord):
    """Et punkt km_nord km nord for (lat, lon) - en breddegrad er ca. 111,195 km."""
    return round(lat + km_nord / 111.195, 6), lon


def _norm(s):
    """Som sidens anaNorm: uden accenter og uden forskel paa store og smaa bogstaver (Seat/SEAT, Skoda/Škoda)."""
    return ''.join(c for c in unicodedata.normalize('NFD', s or '') if not unicodedata.combining(c)).lower().strip()


# Forhandlergrupper med mindst ANA_MIN raekker i pladskraevende, bevidst UDEN for hvidlisten (designreglen: i
# pladskraevende kan kun hvidlistede kaeder mangle). Bjarne Nielsen og Autohuset Vestergaard stod delvis under
# bilmaerker (Bjarne Nielsen A/S - Slagelse under Hyundai), saa 'mangler' var forkert ved deres egne forretninger
# (undersoegelse 15-10-2026); oprydningen 16-10-2026 flyttede gruppernes afdelinger til gruppens navn. Med ANA_MIN = 5
# (20-10-2026) er det disse 23 grupper. Naar en ny gruppe naar ANA_MIN, fejler
# test_alle_store_maerker_i_pladskraevende_er_klassificeret, og nogen skal tage stilling.
FORHANDLERGRUPPER = {'Ejner Hessel', 'Bjarne Nielsen', 'Andersen Biler', 'Autohuset Vestergaard', 'Via Biler',
                     'Pedersen & Nielsen', 'P. Christensen', 'Uggerhøj', 'Auto Group Nordvest', 'Autocentralen',
                     'MTH Biler', 'STS Biler', 'C.A. Larsen Automobiler', 'Krogsgaard-Jensen Automobiler', 'Terminalen',
                     'ATbiler', 'Andersen & Martini', 'Bayern AutoGroup', 'Carto', 'Frimann Hansen Automobiler',
                     'Louis Lund', 'Nellemann', 'SDKbiler'}

# Brugerens valg 20-10-2026: kun kaeder, hvis liste holdes ajour hver uge eller er efterproevet mod kaedens egen liste,
# maa staa under Mangler; resten staar i ANA_IKKE_AJOUR_LAG i kort_soeg.html (SELECTED og Billigblomst blev meldt som
# manglende ved deres egne butikker, review 20-10-2026). Ugentligt: en henter i refresh_retail.KAEDER, der ejer
# maerket (EJER) i lagets halvdel, eller ANDRE_UGENTLIGE. EFTERPROEVET: kaeder uden henter, holdt op mod kaedens egen
# liste - med dato og kilde, saa det kan gentages.
ANDRE_UGENTLIGE = {('tank', 'OK'), ('charge', 'Tesla'),           # refresh_data erstatter dem (OK's ladere: ok_chargers)
                   ('tank', "Go'on"), ('tanktruck', "Go'on"), ('tank', 'Lavpris')}  # reconcile.py afstemmer dem
IKKE_EGEN_LISTE = {'spirii', 'edf', 'stella'}      # holdes kun op mod Q8Truck's roamingkort, der ikke er komplet
_KOEKKEN = '15-10-2026: alle 12 køkkenkæders egne lister mod vores 263 rækker (7 tilføjet 16-10-2026)'
EFTERPROEVET = {('plads', n): _KOEKKEN for n in (
    'Kvik', 'HTH', 'Svane Køkkenet', 'Nettoline', 'Vordingborg Køkkenet', 'Designa', 'AUBO Køkken & Bad', 'Tvis Køkken',
    'Invita', 'JKE Design', 'uno form', 'Multiform')}
EFTERPROEVET[('tank', 'Oles Olie')] = '20-10-2026: olesolie.dk, 8 af 8 (review)'


class Opbygning(unittest.TestCase):
    """Omraadeanalysen i kort_soeg.html (15-10-2026): brugeren soeger en adresse eller klikker paa kortet og
    ser, hvad der er inden for en radius - og hvilke kaeder med mindst ANA_MIN adresser i landet der mangler
    (10 indtil 20-10-2026, nu 5)."""

    def test_analysen_ligger_uden_for_data_blokken(self):
        """rebuild.py udskifter KUN 'const DATA = {...}' (swap_data); ligger analysen inde i den, forsvinder den
        ved naeste ugentlige genopbygning. Den skal staa efter DATA-objektet og kun én gang."""
        h = _html()
        self.assertEqual((h.count(START), h.count(SLUT)), (1, 1))
        i = h.find('const DATA = ')
        self.assertGreater(i, 0)
        _, slut = json.JSONDecoder().raw_decode(h, i + len('const DATA = '))
        self.assertGreater(h.find(START), slut)

    def test_ui_er_koblet_paa(self):
        """Sektionen findes, adressesoegningen saetter centrum, og graensen for en 'kaede' er 10 adresser."""
        h = _html()
        for tekst in ('id="anasec"', 'id="ana-r"', 'id="ana-klik"', 'id="ana-ryd"', 'id="ana"',
                      'saetAnaCenter(lat,lon,true);', 'const ANA_MIN=5;', "map.on('click'", 'const ANA_IKKE_AJOUR_LAG={',
                      'Kun kæder, hvis butiksliste holdes ajour eller er efterprøvet mod kædens egen liste, kan stå som manglende.',
                      "Kæder, hvis butiksliste hverken holdes ajour eller er efterprøvet mod kædens egen liste, meldes ikke som manglende"):
            with self.subTest(tekst):
                self.assertIn(tekst, h)

    def test_bilmaerker_og_samlenavne_har_egne_linjer(self):
        """Undersoegelse 15-10-2026: bilmaerker og samlenavne stod blandt kaederne under 'Til stede'. Panelet viser
        dem nu paa egne linjer efter analyser()'s g, og hintet paastaar ikke laengere, at forhandlere 'staar under
        deres eget navn' (274 raekker staar under et bilmaerke)."""
        h = _html()
        for tekst in ("[['','Til stede',''],", "['bil','Under bilmærke',", "['samle','Samlebetegnelser',",
                      'for(const [g,titel,forkl] of ANA_LINJER)', 'a.til.filter(t=>t.g===g)',
                      'en bilforhandler kan stå under sit eget navn, under bilmærket'):
            with self.subTest(tekst):
                self.assertIn(tekst, h)
        # 182 af de 274 raekker under et bilmaerke er forhandlere med eget navn (review 15-10-2026)
        for tekst in ('Bilmærker tæller ikke: forhandlere står under deres eget navn',
                      'Forhandlere med eget navn står under «Til stede»'):
            with self.subTest(tekst):
                self.assertNotIn(tekst, h)


def _kraev_node(self):
    """Uden node springes over lokalt, men i GitHub Actions er det en fejl: en tavs overspringning dér ville
    skjule, at analysen ikke er testet (review 15-10-2026)."""
    if not shutil.which('node'):
        if os.environ.get('GITHUB_ACTIONS'):
            self.fail('node mangler paa runneren - kortets analyse kan ikke testes')
        self.skipTest('node findes ikke')


class Syntaks(unittest.TestCase):
    def test_kortets_script_kan_parses(self):
        """Review 15-10-2026: panelkoden havde ingen test - en syntaksfejl i visningen bestod alle tests og gav et
        tomt offentligt kort. Hele kortets app-script (efter DATA) parses med node."""
        _kraev_node(self)
        h = _html()
        i = h.find('const DATA = ')
        k = h.rfind('<script>', 0, i) + len('<script>')
        j = h.find('</script>', i)
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write('new Function(require("fs").readFileSync(0, "utf8"));')
            sti = f.name
        try:
            p = subprocess.run(['node', sti], input=h[k:j], capture_output=True, text=True, timeout=60)
        finally:
            os.unlink(sti)
        self.assertEqual(p.returncode, 0, p.stderr[-800:])


class AnalyseFunktion(unittest.TestCase):
    """analyser() koert med node - den rigtige funktion fra kort_soeg.html, ikke en kopi."""

    def setUp(self):
        _kraev_node(self)

    def _koer_js(self, kode, inddata):
        """Koer kode efter sidens ANALYSE-blok med node; inddata som JSON paa stdin (variablen a), svar paa stdout."""
        h = _html()
        script = h[h.find(START):h.find(SLUT)] + '\nconst a = JSON.parse(require("fs").readFileSync(0, "utf8"));\n' + kode
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(script)
            sti = f.name
        try:
            p = subprocess.run(['node', sti], input=json.dumps(inddata), capture_output=True, text=True, timeout=120)
        finally:
            os.unlink(sti)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def _node(self, data, lat, lon, km, lag=None, minimum=None, generisk=None, km_til=None, km_tekst=None, kan=None,
              ude=None):
        # km_til = [lag, indeks]: radius = afstanden til det punkt, regnet af sidens EGEN anaAfstand (ellers kan
        # Pythons og JavaScripts sidste decimaler skille, og graensen ikke testes praecist).
        return self._koer_js(
            'if (a.km_til) { const p = a.data[a.km_til[0]].pts[a.km_til[1]]; a.km = anaAfstand(a.lat, a.lon, p[0], p[1]); }\n'
            'const r = a.data ? analyser(a.data, a.lag, a.lat, a.lon, a.km, a.min, a.gen, null, a.kan, a.ude) : {};\n'
            'r.__konst = {gen: ANA_GENERISK, lag: ANA_GENERISK_LAG, kan: ANA_KAN_MANGLE_LAG, ude: ANA_IKKE_AJOUR_LAG,\n'
            '  min: ANA_MIN,\n'
            '  km: (a.km_tekst || []).map(x => kmTekst(x[0], x[1]))};\n'
            'process.stdout.write(JSON.stringify(r));\n',
            {'data': data, 'lag': lag or list(data or {}), 'lat': lat, 'lon': lon, 'km': km, 'min': minimum,
             'gen': generisk, 'km_til': km_til, 'km_tekst': km_tekst, 'kan': kan, 'ude': ude})

    def test_til_stede_mangler_graense_og_samlenavne(self):
        """A har ét punkt 1 km fra centrum (til stede); B har ti punkter, det naermeste 5 km vaek (mangler, med
        afstanden); C har kun tre adresser i landet (ingen kaede - meldes aldrig); 'Bilforhandler' er et
        samlenavn (meldes aldrig); D ligger PRAECIS paa radius (til stede: graensen taeller med)."""
        c = (56.0, 10.0)
        brands = [{'n': 'A', 'k': 12}, {'n': 'B', 'k': 10}, {'n': 'C', 'k': 3}, {'n': 'Bilforhandler', 'k': 50},
                  {'n': 'D', 'k': 11}]
        pts = [list(_punkt(*c, 1.0)) + [0, 'A Centrum', 'Torvet 1']]
        pts += [list(_punkt(*c, 20.0 + i)) + [0, 'A %d' % i, ''] for i in range(11)]
        # B's punkter i OMVENDT raekkefoelge (det fjerneste foerst): 'naermeste' maa ikke vaere 'foerste'
        pts += [list(_punkt(*c, 5.0 + i * 3)) + [1, 'B %d' % i, 'Vej %d' % i] for i in reversed(range(10))]
        pts += [list(_punkt(*c, 30.0 + i)) + [2, 'C %d' % i, ''] for i in range(3)]
        pts += [list(_punkt(*c, 40.0 + i)) + [3, 'Bil %d' % i, ''] for i in range(50)]
        i_graense = len(pts)
        pts += [[round(c[0] + 2.0 / 111.195, 9), c[1], 4, 'D graense', '']]
        pts += [list(_punkt(*c, 60.0 + i)) + [4, 'D %d' % i, ''] for i in range(10)]
        data = {'daglig': {'label': 'Dagligvarer', 'brands': brands, 'pts': pts}}
        # radius PRAECIS = afstanden til D's graensepunkt (regnet af sidens egen funktion): D er til stede
        r = self._node(data, c[0], c[1], None, km_til=['daglig', i_graense])['daglig']
        km = _hav(c[0], c[1], pts[i_graense][0], pts[i_graense][1])
        self.assertEqual(r['kaeder'], 3)          # A, B og D (C er for lille, Bilforhandler et samlenavn)
        self.assertEqual(r['n'], 2)
        self.assertEqual([(t['n'], t['k']) for t in r['til']], [('A', 1), ('D', 1)])
        self.assertEqual([m['n'] for m in r['mangler']], ['B'])
        b = r['mangler'][0]
        self.assertAlmostEqual(b['d'], _hav(c[0], c[1], *_punkt(*c, 5.0)), places=6)
        self.assertEqual((b['navn'], b['adr'], b['k']), ('B 0', 'Vej 0', 10))
        # samme data, minimum 3: C regnes nu som kaede og mangler; Bilforhandler stadig aldrig
        r = self._node(data, c[0], c[1], None, minimum=3, km_til=['daglig', i_graense])['daglig']
        self.assertEqual([m['n'] for m in r['mangler']], ['B', 'C'])

    def test_bilmaerker_kun_samlenavn_i_pladskraevende(self):
        """Review 15-10-2026: 'Škoda 92 km' stod under Mangler, mens forhandleren 'Škoda Holstebro' (eget navn efter
        maerkereglen) laa 110 m vaek. Bilmaerker er derfor samlenavne i pladskraevende - men kun dér: 'Tesla' er
        ogsaa en ladeoperatoer og skal kunne mangle blandt superladerne."""
        c = (56.36, 8.62)
        plads = {'label': 'Pladskrævende', 'brands': [{'n': 'Škoda', 'k': 20}, {'n': 'Škoda Holstebro', 'k': 1},
                                                    {'n': 'STARK', 'k': 81}],
                 'pts': [list(_punkt(*c, 0.11)) + [1, 'Škoda Holstebro', 'Nybovej 25']]
                 + [list(_punkt(*c, 90.0 + i)) + [0, 'Škoda %d' % i, ''] for i in range(20)]
                 + [list(_punkt(*c, 5.0 + i)) + [2, 'STARK %d' % i, ''] for i in range(81)]}
        charge = {'label': 'Superladere', 'brands': [{'n': 'Tesla', 'k': 36}],
                  'pts': [list(_punkt(*c, 30.0 + i)) + [0, 'Tesla %d' % i, ''] for i in range(36)]}
        r = self._node({'plads': plads, 'charge': charge}, c[0], c[1], 2)
        self.assertEqual([m['n'] for m in r['plads']['mangler']], ['STARK'])
        self.assertEqual([(t['n'], t['g']) for t in r['plads']['til']], [('Škoda Holstebro', '')])
        self.assertEqual([m['n'] for m in r['charge']['mangler']], ['Tesla'])
        # ... og inden for radius er Tesla blandt superladerne en almindelig operatoer, ikke et bilmaerke
        r = self._node({'charge': charge}, c[0], c[1], 40)
        self.assertEqual({t['g'] for t in r['charge']['til']}, {''})

    def test_hvidliste_i_pladskraevende(self):
        """Undersoegelse 15-10-2026: 'Bjarne Nielsen 35,4 km' stod under Mangler paa Bjarne Nielsen A/S - Slagelse,
        fordi forretningen staar under Hyundai. I pladskraevende kan kun kaeder paa hvidlisten (byggemarkeder,
        koekkenkaeder og havecentre) mangle: en forhandlergruppe med 10+ raekker (her 'Gruppe') meldes aldrig,
        STARK stadig. Gruppens raekke under Ford i centrum staar under 'Under bilmaerke' (g='bil')."""
        c = (55.4, 11.35)
        plads = {'label': 'Pladskrævende', 'brands': [{'n': 'Gruppe', 'k': 10}, {'n': 'Ford', 'k': 12},
                                                    {'n': 'STARK', 'k': 81}, {'n': 'Ukendt Kæde', 'k': 15},
                                                    {'n': 'Bilforhandler', 'k': 21}],
                 'pts': [list(_punkt(*c, 0.05)) + [1, 'Gruppe A/S - Slagelse', 'Asienvej 3']]
                 + [list(_punkt(*c, 30.0 + i)) + [0, 'Gruppe %d' % i, ''] for i in range(10)]
                 + [list(_punkt(*c, 50.0 + i)) + [1, 'Ford %d' % i, ''] for i in range(11)]
                 + [list(_punkt(*c, 3.0 + i)) + [2, 'STARK %d' % i, ''] for i in range(81)]
                 + [list(_punkt(*c, 8.0 + i)) + [3, 'Ukendt %d' % i, ''] for i in range(15)]
                 + [list(_punkt(*c, 0.5)) + [4, 'Bilforhandler Slagelse', '']]
                 + [list(_punkt(*c, 60.0 + i)) + [4, 'Bilforhandler %d' % i, ''] for i in range(20)]}
        r = self._node({'plads': plads}, c[0], c[1], 2)['plads']
        self.assertEqual([m['n'] for m in r['mangler']], ['STARK'])
        self.assertEqual(r['kaeder'], 1)          # kun STARK er i mangler-tjekket
        # samlenavnet faar ogsaa i pladskraevende sin egen linje (review 15-10-2026)
        self.assertEqual([(t['n'], t['k'], t['g']) for t in r['til']], [('Bilforhandler', 1, 'samle'), ('Ford', 1, 'bil')])
        # en egen hvidliste med 'Ukendt Kæde': nu kan den mangle - listen er det, der afgoer det
        r = self._node({'plads': plads}, c[0], c[1], 2, kan={'plads': ['STARK', 'Ukendt Kæde']})['plads']
        self.assertEqual([m['n'] for m in r['mangler']], ['STARK', 'Ukendt Kæde'])
        # uden hvidliste for laget (som i dagligvarer): alle med 10+ raekker kan mangle, ogsaa 'Gruppe'
        r = self._node({'plads': plads}, c[0], c[1], 2, kan={'andet': []})['plads']
        self.assertEqual([m['n'] for m in r['mangler']], ['STARK', 'Ukendt Kæde', 'Gruppe'])

    def test_kaeder_uden_ajourfoert_liste_meldes_ikke(self):
        """Brugerens valg 20-10-2026: en kaede paa lagets undtagelsesliste (ANA_IKKE_AJOUR_LAG) meldes aldrig som
        manglende, men taeller stadig med under Til stede; listen gaelder kun sit eget lag (Norlys' lastbilladere holdes
        ajour, bilnettet ikke)."""
        c = (55.7, 12.5)
        lag = {'label': 'Udvalgsvarer', 'brands': [{'n': 'Ajour', 'k': 10}, {'n': 'Uden liste', 'k': 10}],
               'pts': [list(_punkt(*c, 5.0 + i)) + [0, 'Ajour %d' % i, ''] for i in range(10)]
               + [list(_punkt(*c, 6.0 + i)) + [1, 'Uden %d' % i, ''] for i in range(10)]}
        ude = {'udvalg': ['Uden liste']}
        r = self._node({'udvalg': lag, 'truck': dict(lag, label='Lastbil-ladere')}, c[0], c[1], 2, ude=ude)
        self.assertEqual([m['n'] for m in r['udvalg']['mangler']], ['Ajour'])
        self.assertEqual(r['udvalg']['kaeder'], 1)
        self.assertEqual([m['n'] for m in r['truck']['mangler']], ['Ajour', 'Uden liste'])
        # inden for radius staar den under Til stede som alle andre
        r = self._node({'udvalg': lag}, c[0], c[1], 6.5, ude=ude)['udvalg']
        self.assertIn(('Uden liste', 1, ''), [(t['n'], t['k'], t['g']) for t in r['til']])
        self.assertEqual([m['n'] for m in r['mangler']], [])

    def test_bilmaerker_sammenlignes_uden_store_smaa_og_accenter(self):
        """Data har 'Seat', 'Cupra' og 'Xpeng', listen 'SEAT', 'CUPRA', 'XPENG' og 'Škoda' (undersoegelse 15-10-2026);
        'Skoda' er et syntetisk tilfaelde (listen havde foer begge stavemaader). De er bilmaerker trods stavningen;
        'Škoda Holstebro' er en forhandler med eget navn."""
        c = (56.0, 9.0)
        navne = ['Seat', 'Cupra', 'Xpeng', 'Skoda', 'Škoda Holstebro']
        plads = {'label': 'P', 'brands': [{'n': n, 'k': 1} for n in navne],
                 'pts': [list(_punkt(*c, 0.1 * (i + 1))) + [i, n, ''] for i, n in enumerate(navne)]}
        r = self._node({'plads': plads}, c[0], c[1], 1)['plads']
        self.assertEqual({t['n']: t['g'] for t in r['til']},
                         {'Seat': 'bil', 'Cupra': 'bil', 'Xpeng': 'bil', 'Skoda': 'bil', 'Škoda Holstebro': ''})

    def test_samlenavne_grupperes_og_taelles_med(self):
        """Et samlenavn (her Apoteksudsalg med 20 raekker) meldes aldrig som manglende - ogsaa i et lag uden
        hvidliste - men staar i 'til' med g='samle', og tallene i 'til' summerer stadig til antallet i overskriften."""
        c = (56.08, 12.2)
        daglig = {'label': 'Dagligvarer', 'brands': [{'n': 'Netto', 'k': 12}, {'n': 'Apoteksudsalg', 'k': 20},
                                                    {'n': 'Apotek', 'k': 11}],
                  'pts': [list(_punkt(*c, 0.2)) + [0, 'Netto Græsted', ''], list(_punkt(*c, 0.3)) + [1, 'Udsalg', '']]
                  + [list(_punkt(*c, 6.8 + i)) + [2, 'Apotek %d' % i, ''] for i in range(11)]
                  + [list(_punkt(*c, 20.0 + i)) + [0, 'Netto %d' % i, ''] for i in range(11)]
                  + [list(_punkt(*c, 40.0 + i)) + [1, 'Udsalg %d' % i, ''] for i in range(19)]}
        r = self._node({'daglig': daglig}, c[0], c[1], 1)['daglig']
        self.assertEqual([m['n'] for m in r['mangler']], ['Apotek'])
        self.assertEqual(r['kaeder'], 2)          # Netto og Apotek - ikke samlenavnet (review 15-10-2026)
        self.assertEqual({t['n']: t['g'] for t in r['til']}, {'Netto': '', 'Apoteksudsalg': 'samle'})
        self.assertEqual(sum(t['k'] for t in r['til']), r['n'])
        self.assertEqual(r['n'], 2)

    def test_ingen_loft_paa_mangler_og_nul_kaeder(self):
        """Funktionen afkorter ikke (panelet viser 8 og 'Vis alle'): 12 manglende kaeder kommer alle med. Et lag uden
        en eneste kaede med mindst ANA_MIN adresser giver kaeder=0 - saa skriver panelet IKKE 'alle kaeder er til
        stede' (review 15-10-2026)."""
        c = (55.0, 10.0)
        brands = [{'n': 'K%02d' % i, 'k': 10} for i in range(12)]
        pts = [list(_punkt(*c, 3.0 + bi + j * 0.1)) + [bi, 'K', ''] for bi in range(12) for j in range(10)]
        smaa = {'label': 'Smaa', 'brands': [{'n': 'X', 'k': 3}], 'pts': [list(_punkt(*c, 0.5)) + [0, 'X', '']] * 3}
        r = self._node({'daglig': {'label': 'D', 'brands': brands, 'pts': pts}, 'truck': smaa}, c[0], c[1], 1)
        self.assertEqual(len(r['daglig']['mangler']), 12)
        self.assertEqual((r['truck']['kaeder'], r['truck']['mangler'], r['truck']['n']), (0, [], 3))

    def test_afstand_som_tekst_rundes_op_for_manglende(self):
        """Review 15-10-2026: en manglende kaede 1,04 km vaek stod som '1,0 km' ved radius 1 km. kmTekst(d, op=True)
        runder OP, saa en manglende kaede aldrig vises med radius selv."""
        k = self._node(None, 0, 0, 0, km_tekst=[[1.0001, True], [2.0001, True], [1.04, False], [0.4501, True],
                                                  [0.4, False], [0.9999, True], [12.31, True]])['__konst']['km']
        self.assertEqual(k, ['1,1 km', '2,1 km', '1,0 km', '460 m', '400 m', '1,0 km', '12,4 km'])

    def test_mangler_sorteres_efter_afstand(self):
        """De naermeste kaeder foerst; ved lige afstand alfabetisk."""
        c = (55.5, 9.5)
        brands = [{'n': n, 'k': 10} for n in ('Fjern', 'Naer', 'Mellem', 'Lige1', 'Lige2')]
        afst = {'Fjern': 30, 'Naer': 3, 'Mellem': 10, 'Lige1': 7, 'Lige2': 7}
        pts = [list(_punkt(*c, afst[b['n']] + i)) + [bi, b['n'], ''] for bi, b in enumerate(brands) for i in range(10)]
        r = self._node({'tank': {'label': 'Tank', 'brands': brands, 'pts': pts}}, c[0], c[1], 1)['tank']
        self.assertEqual([m['n'] for m in r['mangler']], ['Naer', 'Lige1', 'Lige2', 'Mellem', 'Fjern'])
        self.assertEqual((r['n'], r['til']), (0, []))

    def _feed(self):
        with open(os.path.join(ROD, 'retailkort_data.json'), encoding='utf-8') as f:
            return json.load(f)

    def test_rigtige_data_holder_reglerne(self):
        """Paa det rigtige feed for et bycentrum og et yderomraade: tallene til stede summerer til antallet inden
        for radius; hver manglende kaede har mindst ANA_MIN adresser, er ikke et samlenavn eller bilmaerke, staar paa
        lagets hvidliste (hvis laget har en) og ligger uden for radius; og intet maerke staar baade som til stede
        og som manglende. Forventningen regnes med hvidlisten - ikke kun ud fra maerkefeltet, som laaste fejlen med
        forhandlergrupperne fast (undersoegelse 15-10-2026)."""
        feed = self._feed()
        lag = [k for k in LAG if k in feed]
        for navn, lat, lon, km in (('Raadhuspladsen', 55.6761, 12.5683, 1), ('Thyboroen', 56.6985, 8.2128, 5),
                                   ('Holstebro Nybovej', 56.3583, 8.6372, 2),
                                   ('Asienvej 3 Slagelse', 55.387178, 11.322516, 2)):
            r = self._node(feed, lat, lon, km, lag=lag)
            konst = r['__konst']
            for k in lag:
                with self.subTest(sted=navn, lag=k):
                    a = r[k]
                    samle = {_norm(x) for x in konst['gen']}
                    bil = {_norm(x) for x in konst['lag'].get(k, [])}
                    kan = set(konst['kan'][k]) if k in konst['kan'] else None
                    ude = set(konst['ude'].get(k, []))
                    # FULDSTAENDIG (review 15-10-2026): praecis de kaeder med k >= ANA_MIN, der ikke er samlenavne eller
                    # bilmaerker, staar paa hvidlisten og ikke har et punkt inden for radius - ingen afkortning.
                    forventet = set()
                    for bi, b in enumerate(feed[k]['brands']):
                        if b['k'] < konst['min'] or _norm(b['n']) in samle | bil or (kan is not None and b['n'] not in kan) \
                                or b['n'] in ude:
                            continue
                        if min(_hav(lat, lon, p[0], p[1]) for p in feed[k]['pts'] if p[2] == bi) > km:
                            forventet.add(b['n'])
                    self.assertEqual({m['n'] for m in a['mangler']}, forventet)
                    self.assertEqual(sum(t['k'] for t in a['til']), a['n'])
                    for t in a['til']:
                        self.assertEqual(t['g'], 'samle' if _norm(t['n']) in samle else 'bil' if _norm(t['n']) in bil
                                         else '', t['n'])
                    til = {t['n'] for t in a['til']}
                    for m in a['mangler']:
                        self.assertGreaterEqual(m['k'], konst['min'])
                        self.assertNotIn(_norm(m['n']), samle | bil)
                        self.assertNotIn(m['n'], ude)
                        self.assertGreater(m['d'], km)
                        self.assertNotIn(m['n'], til)
                        self.assertAlmostEqual(m['d'], _hav(lat, lon, m['lat'], m['lon']), places=6)
                        bi = next(i for i, b in enumerate(feed[k]['brands']) if b['n'] == m['n'])
                        mindst = min(_hav(lat, lon, p[0], p[1]) for p in feed[k]['pts'] if p[2] == bi)
                        self.assertAlmostEqual(m['d'], mindst, places=6)
        # et kendt eksempel: inden for 1 km af Raadhuspladsen er der dagligvarebutikker, og Netto er til stede
        r = self._node(feed, 55.6761, 12.5683, 1, lag=['daglig'])['daglig']
        self.assertGreater(r['n'], 10)
        self.assertIn('Netto', {t['n'] for t in r['til']})
        # ... og paa Bjarne Nielsen A/S - Slagelse meldes Bjarne Nielsen ikke som manglende. (Ingen fast paastand om
        # rækkens maerke: Hyundai er netop den fejlregistrering, der skal rettes - review 15-10-2026.)
        r = self._node(feed, 55.387178, 11.322516, 2, lag=['plads'])['plads']
        self.assertNotIn('Bjarne Nielsen', {m['n'] for m in r['mangler']})

    def test_ingen_kaede_meldes_manglende_ved_sin_egen_forretning(self):
        """Undersoegelse 15-10-2026: med hver pladskraevende-adresse som centrum ved 1, 2, 5 og 10 km meldte panelet
        296 gange en kaede som manglende, selv om en forretning med kaedens navn laa inden for radius (Bjarne
        Nielsen og Autohuset Vestergaard, hvis forretninger ogsaa staar under bilmaerker). Med hvidlisten: 0. Kun
        pladskraevende: i andre lag deler formater et navn med vilje (føtex / føtex food, Imerco / Imerco Home)."""
        r = self._koer_js(
            'const D = a.data, p = D.plads.pts, ud = {n: 0, ialt: 0, eks: []};\n'
            'for (const c of p) for (const km of [1, 2, 5, 10]) {\n'
            '  ud.ialt++;\n'
            '  const inde = p.filter(q => anaAfstand(c[0], c[1], q[0], q[1]) <= km).map(q => anaNorm(q[3]));\n'
            '  for (const m of analyser(D, ["plads"], c[0], c[1], km).plads.mangler) {\n'
            '    const n = anaNorm(m.n);\n'
            '    if (inde.some(x => x === n || x.startsWith(n + " "))) { ud.n++; if (ud.eks.length < 5) ud.eks.push([c[3], km, m.n]); }\n'
            '  }\n'
            '}\n'
            'process.stdout.write(JSON.stringify(ud));\n', {'data': {'plads': self._feed()['plads']}})
        self.assertGreater(r['ialt'], 4000)
        self.assertEqual(r['n'], 0, r['eks'])

    def test_alle_store_maerker_i_pladskraevende_er_klassificeret(self):
        """Hvert maerke med mindst ANA_MIN raekker i pladskraevende er klassificeret: paa hvidlisten (kan mangle),
        et bilmaerke, et samlenavn eller en kendt forhandlergruppe (FORHANDLERGRUPPER). Ellers falder en ny kaede
        tavst ud af Mangler - eller en ny forhandlergruppe skal afgoeres. Og hvert navn paa hvidlisten findes i
        data: en stavefejl ville tavst fjerne kaeden fra Mangler."""
        feed = self._feed()
        konst = self._node(None, 0, 0, 0)['__konst']
        kan = set(konst['kan']['plads'])
        bil = {_norm(x) for x in konst['lag']['plads']} | {_norm(x) for x in konst['gen']}
        navne = {b['n'] for b in feed['plads']['brands']}
        uklassificeret = sorted(b['n'] for b in feed['plads']['brands'] if b['k'] >= konst['min'] and b['n'] not in kan
                                and _norm(b['n']) not in bil and b['n'] not in FORHANDLERGRUPPER)
        self.assertEqual(uklassificeret, [])
        self.assertEqual(sorted(kan - navne), [])
        self.assertEqual(sorted(FORHANDLERGRUPPER - navne), [])
        self.assertEqual(sorted(FORHANDLERGRUPPER & kan), [])

    @staticmethod
    def _ajour(lag, navn):
        """Holdes kaedens liste ajour hver uge i dette lag? En henter, der ejer maerket, i den rigtige halvdel: ladehentere
        til superladere/lastbilladere (EN_HALVDEL), de andre til resten - eller en kilde i ANDRE_UGENTLIGE."""
        import refresh_retail as R
        if (lag, navn) in ANDRE_UGENTLIGE:
            return True
        for h, _ in R.KAEDER:
            if navn not in R.EJER.get(h, ()) or h in IKKE_EGEN_LISTE:
                continue
            lade, halv = h in R.LADE_KAEDER, R.EN_HALVDEL.get(h)
            if (lag == 'charge' and lade and halv != 'lastbil') or (lag == 'truck' and lade and halv != 'bil') \
                    or (lag not in ('charge', 'truck') and not lade):
                return True
        return False

    def test_hver_kaede_i_mangler_tjekket_har_en_ajourfoert_liste(self):
        """Brugerens valg 20-10-2026: hver kaede, der kan staa under Mangler, holdes ajour hver uge eller er
        efterproevet (EFTERPROEVET); resten staar i ANA_IKKE_AJOUR_LAG. Og listen har kun kaeder, som er i tjekket og
        ikke holdes ajour: faar en af dem en henter, skal den ud af listen igen. Botten tilfoejer kun raekker til kaeder
        med en henter, saa testen holder fra uge til uge."""
        feed = self._feed()
        konst = self._node(None, 0, 0, 0)['__konst']
        self.assertEqual(sorted(set(konst['ude']) - set(LAG)), [])
        for k in LAG:
            with self.subTest(lag=k):
                samle = {_norm(x) for x in konst['gen']}
                bil = {_norm(x) for x in konst['lag'].get(k, [])}
                kan = set(konst['kan'][k]) if k in konst['kan'] else None
                i_tjek = {b['n'] for b in feed[k]['brands'] if b['k'] >= konst['min']
                          and _norm(b['n']) not in samle | bil and (kan is None or b['n'] in kan)}
                uden = {n for n in i_tjek if not self._ajour(k, n) and (k, n) not in EFTERPROEVET}
                ude = set(konst['ude'].get(k, []))
                self.assertEqual(sorted(uden - ude), [], 'kan staa under Mangler, men listen holdes ikke ajour')
                self.assertEqual(sorted(ude - uden), [], 'i ANA_IKKE_AJOUR_LAG, men holdes ajour eller er ikke i tjekket')
                for (lag, n), grund in EFTERPROEVET.items():
                    if lag == k:
                        self.assertIn(n, i_tjek, 'EFTERPROEVET naevner en kaede uden for tjekket')
                        self.assertFalse(self._ajour(k, n), f'{n} har nu en ugentlig kilde - tag den ud af EFTERPROEVET')
                        self.assertRegex(grund, r'\b\d{2}-\d{2}-\d{4}\b')


if __name__ == '__main__':
    unittest.main()
