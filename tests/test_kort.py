import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

import json
import math
import shutil
import subprocess
import tempfile
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


class Opbygning(unittest.TestCase):
    """Omraadeanalysen i kort_soeg.html (15-10-2026): brugeren soeger en adresse eller klikker paa kortet og
    ser, hvad der er inden for en radius - og hvilke kaeder med mindst 10 adresser i landet der mangler."""

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
                      'saetAnaCenter(lat,lon,true);', 'const ANA_MIN=10;', "map.on('click'"):
            with self.subTest(tekst):
                self.assertIn(tekst, h)


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

    def _node(self, data, lat, lon, km, lag=None, minimum=None, generisk=None, km_til=None, km_tekst=None):
        h = _html()
        blok = h[h.find(START):h.find(SLUT)]
        # km_til = [lag, indeks]: radius = afstanden til det punkt, regnet af sidens EGEN anaAfstand (ellers kan
        # Pythons og JavaScripts sidste decimaler skille, og graensen ikke testes praecist).
        script = blok + '\nconst a = JSON.parse(require("fs").readFileSync(0, "utf8"));\n' \
            + 'if (a.km_til) { const p = a.data[a.km_til[0]].pts[a.km_til[1]]; a.km = anaAfstand(a.lat, a.lon, p[0], p[1]); }\n' \
            + 'const r = a.data ? analyser(a.data, a.lag, a.lat, a.lon, a.km, a.min, a.gen) : {};\n' \
            + 'r.__konst = {gen: ANA_GENERISK, lag: ANA_GENERISK_LAG, km: (a.km_tekst || []).map(x => kmTekst(x[0], x[1]))};\n' \
            + 'process.stdout.write(JSON.stringify(r));\n'
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(script)
            sti = f.name
        try:
            p = subprocess.run(['node', sti], input=json.dumps({
                'data': data, 'lag': lag or list(data or {}), 'lat': lat, 'lon': lon, 'km': km,
                'min': minimum, 'gen': generisk, 'km_til': km_til, 'km_tekst': km_tekst}),
                capture_output=True, text=True, timeout=60)
        finally:
            os.unlink(sti)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

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
        self.assertEqual([t['n'] for t in r['plads']['til']], ['Škoda Holstebro'])
        self.assertEqual([m['n'] for m in r['charge']['mangler']], ['Tesla'])

    def test_ingen_loft_paa_mangler_og_nul_kaeder(self):
        """Funktionen afkorter ikke (panelet viser 8 og 'Vis alle'): 12 manglende kaeder kommer alle med. Et lag uden
        en eneste kaede med mindst 10 adresser giver kaeder=0 - saa skriver panelet IKKE 'alle kaeder er til
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

    def test_rigtige_data_holder_reglerne(self):
        """Paa det rigtige feed for et bycentrum og et yderomraade: tallene til stede summerer til antallet inden
        for radius; hver manglende kaede har mindst 10 adresser, er ikke et samlenavn og ligger uden for
        radius; og intet maerke staar baade som til stede og som manglende."""
        with open(os.path.join(ROD, 'retailkort_data.json'), encoding='utf-8') as f:
            feed = json.load(f)
        lag = [k for k in LAG if k in feed]
        for navn, lat, lon, km in (('Raadhuspladsen', 55.6761, 12.5683, 1), ('Thyboroen', 56.6985, 8.2128, 5),
                                   ('Holstebro Nybovej', 56.3583, 8.6372, 2)):
            r = self._node(feed, lat, lon, km, lag=lag)
            konst = r['__konst']
            for k in lag:
                with self.subTest(sted=navn, lag=k):
                    a = r[k]
                    # FULDSTAENDIG (review 15-10-2026): praecis de kaeder med k >= 10, der ikke er samlenavne og ikke
                    # har et punkt inden for radius - ingen afkortning, ingen fjerne kaeder, der falder ud.
                    gen = set(konst['gen']) | set(konst['lag'].get(k, []))
                    forventet = set()
                    for bi, b in enumerate(feed[k]['brands']):
                        if b['k'] < 10 or b['n'] in gen:
                            continue
                        if min(_hav(lat, lon, p[0], p[1]) for p in feed[k]['pts'] if p[2] == bi) > km:
                            forventet.add(b['n'])
                    self.assertEqual({m['n'] for m in a['mangler']}, forventet)
                    self.assertEqual(sum(t['k'] for t in a['til']), a['n'])
                    til = {t['n'] for t in a['til']}
                    for m in a['mangler']:
                        self.assertGreaterEqual(m['k'], 10)
                        self.assertNotIn(m['n'], gen)
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


if __name__ == '__main__':
    unittest.main()
