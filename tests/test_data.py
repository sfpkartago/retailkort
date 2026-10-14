import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

import csv
import json
import re
import unittest
from collections import Counter

ROD = hjaelp.ROD

HOVED = ['Mærke', 'Navn', 'Adresse', 'Postnr', 'By', 'Latitude', 'Longitude']
FILER = {
    'dagligvarer_dk.csv': HOVED, 'udvalgsvarer_dk.csv': HOVED, 'pladskraevende_dk.csv': HOVED,
    'fastfood_kaeder_dk.csv': HOVED, 'tankstationer_dk.csv': HOVED + ['Lastbil'],
    'superladere_dk.csv': ['Operatør', 'Navn', 'Adresse', 'Postnr', 'By', 'Effekt_kW', 'Stik',
                           'Antal_ladere', 'Latitude', 'Longitude', 'Lastbil'],
}
KOORD = {'superladere_dk.csv': (8, 9)}       # (lat, lon); ellers (5, 6)
DK = (54.4, 57.9, 7.8, 15.3)                 # samme kasse som refresh_retail.DK
LAG = {'daglig': 'dagligvarer_dk.csv', 'udvalg': 'udvalgsvarer_dk.csv', 'plads': 'pladskraevende_dk.csv',
       'food': 'fastfood_kaeder_dk.csv'}


def _raa(fn):
    with open(os.path.join(ROD, fn), 'rb') as f:
        return f.read()


def _laes(fn):
    with open(os.path.join(ROD, fn), encoding='utf-8-sig', newline='') as f:
        r = list(csv.reader(f))
    return r[0], r[1:]


class CsvFormat(unittest.TestCase):
    """Formatet, som alle skrivere (refresh_retail, refresh_data, apply_refresh) bruger: UTF-8 med
    BOM (Excel viser ellers æ/ø/å forkert), CRLF, samme kolonner, sorteret efter (maerke, postnr)."""

    def test_bom_og_crlf(self):
        for fn in FILER:
            b = _raa(fn)
            self.assertTrue(b.startswith(b'\xef\xbb\xbf'), f'{fn}: mangler BOM')
            self.assertEqual(b.count(b'\n'), b.count(b'\r\n'), f'{fn}: linjeskift uden CR')
            b.decode('utf-8-sig')

    def test_hoved_og_bredde(self):
        for fn, hoved in FILER.items():
            h, rows = _laes(fn)
            self.assertEqual(h, hoved, fn)
            skaev = [i + 2 for i, r in enumerate(rows) if len(r) != len(hoved)]
            self.assertEqual(skaev, [], f'{fn}: raekker med forkert antal felter (linje)')

    def test_udfyldte_felter_postnr_og_koordinater(self):
        """Sanity-spaerren tjekker postnr/by; her ogsaa maerke, navn, adresse og at koordinaten
        ligger i Danmark (en ombyttet lat/lon eller en tysk butik ville ellers komme med)."""
        for fn in FILER:
            _, rows = _laes(fn)
            la, lo = KOORD.get(fn, (5, 6))
            fejl = []
            for i, r in enumerate(rows):
                if not all((r[k] or '').strip() for k in range(5)):
                    fejl.append((i + 2, 'tomt felt', r[:5]))
                if not re.fullmatch(r'\d{4}', r[3]):
                    fejl.append((i + 2, 'postnr', r[3]))
                try:
                    y, x = float(r[la]), float(r[lo])
                except ValueError:
                    fejl.append((i + 2, 'koordinat', r[la], r[lo])); continue
                if not (DK[0] < y < DK[1] and DK[2] < x < DK[3]):
                    fejl.append((i + 2, 'uden for DK', y, x))
            self.assertEqual(fejl[:10], [], fn)

    def test_sorteret(self):
        for fn in FILER:
            _, rows = _laes(fn)
            noegle = [(r[0], r[3]) for r in rows]
            forkert = [i + 2 for i in range(1, len(noegle)) if noegle[i] < noegle[i - 1]]
            self.assertEqual(forkert[:10], [], f'{fn}: ikke sorteret efter (maerke, postnr) (linje)')

    def test_ingen_dubletter(self):
        """En byte-identisk dublet slap ind 2026-09 (Tøjeksperten Ballerup, to gange i kilden);
        samme maerke + navn + adresse to gange (inden for samme bil/lastbil-halvdel) er en fejl."""
        for fn in FILER:
            h, rows = _laes(fn)
            lb = h.index('Lastbil') if 'Lastbil' in h else None
            c = Counter((r[0], r[1], r[2], r[lb] if lb is not None else '') for r in rows)
            self.assertEqual([k for k, n in c.items() if n > 1], [], fn)


class Ladere(unittest.TestCase):
    """Lagets definition: offentlige DC-ladere, effekt pr. udtag 250-600 kW til bil og op til
    1.200 kW til lastbil (MCS); Antal_ladere = udtag paa >= 250 kW, aldrig gaettet."""

    @classmethod
    def setUpClass(cls):
        _, cls.rows = _laes('superladere_dk.csv')

    def test_effekt_i_intervallet(self):
        fejl = []
        for r in self.rows:
            hi = 1200 if r[10] == 'ja' else 600
            if not (r[5].isdigit() and 250 <= int(r[5]) <= hi):
                fejl.append((r[0], r[1], r[5], r[10]))
        self.assertEqual(fejl, [])

    def test_antal_stik_og_lastbil(self):
        fejl = []
        for r in self.rows:
            if not (r[7].isdigit() and 1 <= int(r[7]) <= 100):
                fejl.append((r[0], r[1], 'antal', r[7]))
            if not r[6].strip():
                fejl.append((r[0], r[1], 'stik', r[6]))
            if r[10] not in ('', 'ja'):
                fejl.append((r[0], r[1], 'Lastbil', r[10]))
        self.assertEqual(fejl, [])

    def test_tankfilens_lastbil(self):
        _, rows = _laes('tankstationer_dk.csv')
        self.assertEqual({r[7] for r in rows} - {'', 'ja'}, set())


class FeedOgKort(unittest.TestCase):
    """Feedet og kortets indbyggede DATA skal vaere bygget af de nuvaerende CSV'er (rebuild.py)."""

    @classmethod
    def setUpClass(cls):
        def n(fn, lastbil=None):
            h, rows = _laes(fn)
            if lastbil is None:
                return len(rows)
            i = h.index('Lastbil')
            return sum(1 for r in rows if (r[i] == 'ja') == lastbil)
        cls.forventet = {'charge': n('superladere_dk.csv', False), 'truck': n('superladere_dk.csv', True),
                         'tank': n('tankstationer_dk.csv', False), 'tanktruck': n('tankstationer_dk.csv', True),
                         **{k: n(fn) for k, fn in LAG.items()}}

    def test_feed(self):
        d = json.loads(_raa('retailkort_data.json').decode('utf-8'))
        self.assertTrue(d.get('stamp'))
        self.assertEqual({k: d[k]['total'] for k in self.forventet}, self.forventet)
        self.assertEqual({k: len(d[k]['pts']) for k in self.forventet}, self.forventet)

    def test_kortets_indbyggede_data(self):
        h = _raa('kort_soeg.html').decode('utf-8')
        i = h.find('const DATA = ')
        self.assertGreater(i, 0)
        d, _ = json.JSONDecoder().raw_decode(h, i + len('const DATA = '))
        self.assertEqual({k: d[k]['total'] for k in self.forventet}, self.forventet)


class Readme(unittest.TestCase):
    def test_readme_tal_passer_til_data(self):
        """Tallene i README.md skrives af rebuild.py (readme_tal.py). 13-10-2026 var fire tal
        gledet fra data uden at noget sagde fra (540 + 19 apoteker, 563 maerker, 3.536 punkter,
        '27 kaeder'). Fejler denne, er README rettet i haanden eller rebuild.py ikke koert."""
        import readme_tal
        with open(readme_tal.README, encoding='utf-8', newline='') as f:
            tekst = f.read()
        ny = readme_tal.udfyld(tekst, readme_tal.beregn())     # uden 'opdateret': datoen beholdes
        if ny != tekst:
            import difflib
            diff = ''.join(list(difflib.unified_diff(tekst.splitlines(True), ny.splitlines(True),
                                                     'README.md', 'beregnet', n=0))[:40])
            self.fail('README.md passer ikke til data - koer python3 rebuild.py:\n' + diff)

    def test_markoerregler(self):
        """udfyld() afviser ukendte noegler, manglende slutmarkoerer og en linje-markoer forrest i en
        linje (CommonMark viser saa linjen som raa HTML)."""
        import readme_tal
        t = {'a': '1'}
        self.assertEqual(readme_tal.udfyld('x <!--n:a-->9<!--/n--> y', t), 'x <!--n:a-->1<!--/n--> y')
        with self.assertRaises(ValueError):
            readme_tal.udfyld('x <!--n:b-->9<!--/n-->', t)
        with self.assertRaises(ValueError):
            readme_tal.udfyld('x <!--n:a-->9', t)
        with self.assertRaises(ValueError):
            readme_tal.udfyld('<!--n:a-->9<!--/n--> y', t)
        with self.assertRaises(ValueError):
            readme_tal.udfyld('ingen markoerer', t)
        self.assertEqual(readme_tal.udfyld('x\n<!--n:a-->\ngammel\n<!--/n-->\n', t), 'x\n<!--n:a-->\n1\n<!--/n-->\n')
        with self.assertRaises(ValueError):          # en ombrudt linje, der ville blive en liste
            readme_tal.udfyld('x\n<!--n:a-->\ng\n<!--/n-->\n', {'a': 'Foo 1,\n2. Bar'})


if __name__ == '__main__':
    unittest.main()
