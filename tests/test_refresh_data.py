import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

# Selvtest af refresh_data.refresh_tesla(): den ugentlige udskiftning af Tesla-raekkerne i superladere_dk.csv
# med supercharge.info's faellesskabsdata. Review 14-10-2026: refresh_tesla skrev powerKilowatt og stallCount
# ukontrolleret, saa én vaerdi fra faellesskabsdataene (et Semi-anlaeg paa 1.000 kW, '325.0', et antal paa 150)
# kunne stoppe hele ugens udgivelse ved den blokerende data-test (tests/test_data.py, Ladere).
#
# Hver test koerer den rigtige refresh_tesla() mod en kopi af repoets superladere_dk.csv i en midlertidig mappe
# (refresh_data.OUT). refresh_data.get er stubbet til en supercharge.info-lignende liste - repoets egne
# Tesla-raekker, som kilden leverer dem, plus testens anlaeg - og normalize_rows til (0, 0) med raekkerne
# uroerte. Intet net, ingen noegle, og den rigtige CSV roeres ikke (det tjekkes efter hver test). At
# refresh_data.get spoerger robots.txt foerst, proeves i tests/test_net.py (test_refresh_data_get_forbudt_uden_urlopen).
# Koer fra repo-roden:  python3 -m unittest -v tests.test_refresh_data
import collections
import contextlib
import copy
import csv
import io
import shutil
import tempfile
import unittest
from unittest import mock

import refresh_data
import refresh_retail as R

FIL = 'superladere_dk.csv'
TESLA_URL = 'https://supercharge.info/service/supercharge/allSites'
BOM = b'\xef\xbb\xbf'
NAVN = 'Tesla Supercharger '        # refresh_tesla's praefiks foran kildens navn
UDEN = object()                     # anlaeg(antal=UDEN): feltet stallCount mangler helt


def anlaeg(navn, kw=250, antal=12, land='Denmark', status='OPEN', gade='Testvej 1', postnr='7100', by='Vejle',
           p=(55.709, 9.536)):
    """Et anlaeg, som supercharge.info's allSites leverer det (de felter refresh_tesla laeser og et par til)."""
    a = {'name': f'{navn}, {land}', 'status': status,
         'address': {'street': gade, 'city': by, 'state': None, 'zip': postnr, 'country': land, 'region': 'Europe'},
         'gps': {'latitude': p[0], 'longitude': p[1]}, 'stallCount': antal, 'powerKilowatt': kw,
         'otherEVs': True, 'solarCanopy': False}
    if antal is UDEN:
        del a['stallCount']
    return a


def som_kilde(r):
    """Vores Tesla-raekke, som supercharge.info leverer den: navnet uden praefikset, gaden uden ', postnr by', kW
    og antal som tal (null, naar antallet er ukendt). refresh_tesla skal skrive den byte-identisk tilbage."""
    hale = f', {r[3]} {r[4]}'
    if not (r[1].startswith(NAVN) and r[2].endswith(hale)):
        raise AssertionError(f"{FIL}: Tesla-raekken har ikke refresh_tesla's form: {r}")
    return anlaeg(r[1][len(NAVN):], kw=int(r[5]), antal=int(r[7]) if r[7] else None, gade=r[2][:-len(hale)],
                  postnr=r[3], by=r[4], p=(float(r[8]), float(r[9])))


def laes(b):
    """CSV-bytes -> (hoved, raekker). Afkodningen er streng UTF-8 (BOM'en fjernes)."""
    r = list(csv.reader(io.StringIO(b.decode('utf-8-sig'), newline='')))
    return r[0], r[1:]


def regelbrud(rows):
    """Data-testens laderegler (tests/test_data.py, Ladere) -> brudene. Graenserne er refresh_retail's (LADE_KW,
    LADE_MAX_ANTAL), som data-testen bruger - ikke de tal, refresh_data selv skriver i koden."""
    fejl = []
    for r in rows:
        lo, hi = R.LADE_KW['lastbil' if r[10] == 'ja' else 'bil']
        if not (r[5].isdigit() and lo <= int(r[5]) <= hi):
            fejl.append((r[1], 'kW', r[5]))
        if r[7] != '' and not (r[7].isdigit() and 1 <= int(r[7]) <= R.LADE_MAX_ANTAL):
            fejl.append((r[1], 'antal', r[7]))
        if not r[6].strip():
            fejl.append((r[1], 'stik', r[6]))
        if r[10] not in ('', 'ja'):
            fejl.append((r[1], 'Lastbil', r[10]))
    return fejl


class RefreshTesla(unittest.TestCase):
    """refresh_data.refresh_tesla() mod en kopi af repoets superladere_dk.csv (se filens hoved)."""

    def setUp(self):
        with open(os.path.join(hjaelp.ROD, FIL), 'rb') as f:
            self.foer = f.read()            # den rigtige fil; kun kopien i self.mappe skrives
        self.hoved, rows = laes(self.foer)
        self.kilde = [som_kilde(r) for r in rows if r[0] == 'Tesla']
        self.assertGreaterEqual(len(self.kilde), refresh_data.TESLA_FLOOR, f'{FIL} har for faa Tesla-raekker')
        self.mappe = tempfile.mkdtemp(prefix='test_refresh_data_')
        self.addCleanup(shutil.rmtree, self.mappe, True)
        self.addCleanup(self._rigtig_fil_uroert)
        self.normaliseret, self.hentet = [], []
        for navn, ny in (('OUT', self.mappe), ('normalize_rows', self._normalize)):
            p = mock.patch.object(refresh_data, navn, ny)
            p.start()
            self.addCleanup(p.stop)

    def _normalize(self, rows, adr, postnr, by, lat, lon, workers=10, status_ud=None, bygning=None):
        """Stub for dawa.normalize_rows (samme signatur): hver raekke 'ok' og uroert -> (0 aendret, 0 ikke fundet)."""
        self.normaliseret.append([list(r) for r in rows])
        if status_ud is not None:
            status_ud.extend('ok' for _ in rows)
        return 0, 0

    def _rigtig_fil_uroert(self):
        with open(os.path.join(hjaelp.ROD, FIL), 'rb') as f:
            self.assertTrue(f.read() == self.foer, f'testen har skrevet i repoets {FIL}')

    def koer(self, kilde, vagt=None):
        """Laeg en frisk kopi af den rigtige fil, koer refresh_tesla() med kilden og fang stderr -> (svar, stderr).
        vagt: en liste, der fanger kaldene til _maerke_vagt, som saa ikke afbryder (kun til gulv-testen)."""
        with open(os.path.join(self.mappe, FIL), 'wb') as f:
            f.write(self.foer)
        self.normaliseret, self.hentet = [], []

        def get(url, timeout=60):
            self.hentet.append(url)
            return copy.deepcopy(kilde)
        err = io.StringIO()
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(refresh_data, 'get', get))
            if vagt is not None:
                st.enter_context(mock.patch.object(refresh_data, '_maerke_vagt', lambda *a: vagt.append(a)))
            st.enter_context(contextlib.redirect_stderr(err))
            svar = refresh_data.refresh_tesla()
        self.assertEqual(self.hentet, [TESLA_URL])
        return svar, err.getvalue()

    def raa(self):
        with open(os.path.join(self.mappe, FIL), 'rb') as f:
            return f.read()

    def tesla(self):
        """Navn -> Tesla-raekke i den skrevne fil."""
        _, rows = laes(self.raa())
        return {r[1]: r for r in rows if r[0] == 'Tesla'}

    # =================================================================== tests
    def test_over_600_kw_udelades_og_naevnes_paa_stderr(self):
        """Et dansk, aabent anlaeg paa 1.000 kW (Semi) er ikke en billader: det udelades og naevnes paa stderr
        ('over 600 kW'); 600 kW er lagets loft og skrives, 601 udelades. Et svensk 1.000 kW-anlaeg naevnes ikke
        (allSites har hele verdens anlaeg; kun de danske er vores). Review 14-10-2026: anlaegget blev skrevet,
        og data-testen (kW 250-600 for en billader) ville have stoppet hele ugens udgivelse."""
        kilde = self.kilde + [anlaeg('Test Semi', kw=1000, gade='Industrivej 1', postnr='6330', by='Padborg',
                                     p=(54.8266, 9.3614)),
                              anlaeg('Test over loftet', kw=601), anlaeg('Test paa loftet', kw=600),
                              anlaeg('Test Sverige', kw=1000, land='Sweden', postnr='21120', by='Malmö',
                                     p=(55.605, 13.0038))]
        (n, _), err = self.koer(kilde)
        t = self.tesla()
        self.assertNotIn(NAVN + 'Test Semi', t)
        self.assertNotIn(NAVN + 'Test over loftet', t)
        self.assertIn(NAVN + 'Test paa loftet', t)
        self.assertEqual(t[NAVN + 'Test paa loftet'][5], '600')
        self.assertEqual(n, len(self.kilde) + 1)
        for tekst in ('over 600 kW', 'Test Semi', '1000 kW', 'Test over loftet', '601 kW'):
            self.assertIn(tekst, err)
        self.assertNotIn('Test paa loftet', err)
        self.assertNotIn('Sverige', err)

    def test_effekt_som_heltal_og_antal_uden_for_1_100_er_ukendt(self):
        """powerKilowatt 325.0 skrives '325' (data-testen kraever et heltal), og stallCount null, 0, 150, 101 eller
        et manglende felt skrives '' (ukendt - et antal gaettes aldrig); 12 og 100 skrives som tallet. Review
        14-10-2026: refresh_tesla skrev kildens vaerdier, som de kom, saa '325.0' eller '150' stoppede ugen."""
        tilfaelde = (('Test 325.0 kW', 325.0, 12, '325', '12'), ('Test antal null', 250, None, '250', ''),
                     ('Test antal 0', 250, 0, '250', ''), ('Test antal 150', 250, 150, '250', ''),
                     ('Test antal 101', 250, 101, '250', ''), ('Test antal mangler', 250, UDEN, '250', ''),
                     ('Test antal 100', 300, 100, '300', '100'))
        self.koer(self.kilde + [anlaeg(navn, kw=kw, antal=antal) for navn, kw, antal, _, _ in tilfaelde])
        t = self.tesla()
        for navn, _, _, kw, antal in tilfaelde:
            with self.subTest(navn):
                r = t.get(NAVN + navn)
                self.assertIsNotNone(r, f'{navn} mangler i filen')
                self.assertEqual((r[5], r[7]), (kw, antal))

    def test_samme_anlaeg_to_gange_og_effekt_som_tekst(self):
        """Testene 14-10-2026: listede allSites samme anlaeg to gange, blev begge skrevet - en dublet, som den
        blokerende data-test stopper ugen paa; og powerKilowatt som tekst ('250') gav TypeError i
        sammenligningen, saa refresh_data stoppede. Nu skrives anlaegget én gang, og '250' laeses som 250;
        en ugyldig effekt ('?') springes over."""
        dublet = anlaeg('Test Dublet', kw=300, antal=8, p=(55.8, 9.9))
        tekst = anlaeg('Test Tekst', kw='250', antal=6, p=(55.6, 9.7))
        ugyldig = anlaeg('Test Ugyldig', kw='?', antal=6, p=(55.5, 9.6))
        self.koer(self.kilde + [dublet, dict(dublet), tekst, ugyldig])
        alle = [r for r in laes(self.raa())[1] if r[0] == 'Tesla']
        self.assertEqual(sum(1 for r in alle if r[1] == NAVN + 'Test Dublet'), 1)
        t = self.tesla()
        self.assertEqual((t[NAVN + 'Test Tekst'][5], t[NAVN + 'Test Tekst'][7]), ('250', '6'))
        self.assertNotIn(NAVN + 'Test Ugyldig', t)

    def test_udenlandske_ikke_aabne_og_under_250_kw_springes_over(self):
        """Som foer (uaendret ved review 14-10-2026): kun danske, aabne anlaeg paa mindst 250 kW skrives. Et svensk,
        et under opfoerelse, midlertidigt lukket eller kun med tilladelse, 249 og 150 kW, uden effekt og uden adresse
        springes tavst over (ingen er over 600 kW) - og er resten repoets egne anlaeg, er filen byte-identisk."""
        uden_adresse = anlaeg('Test uden adresse')
        uden_adresse['address'] = None
        kilde = self.kilde + [anlaeg('Test Sverige', land='Sweden', postnr='21120', by='Malmö', p=(55.605, 13.0038)),
                              anlaeg('Test under opfoerelse', status='CONSTRUCTION'),
                              anlaeg('Test midlertidigt lukket', status='CLOSED_TEMP'),
                              anlaeg('Test tilladelse', status='PERMIT'),
                              anlaeg('Test 249 kW', kw=249), anlaeg('Test 150 kW', kw=150),
                              anlaeg('Test uden effekt', kw=None), uden_adresse]
        (n, _), err = self.koer(kilde)
        self.assertEqual(n, len(self.kilde))
        self.assertTrue(self.raa() == self.foer, 'et oversprunget anlaeg aendrede filen')
        self.assertEqual(err, '')

    def test_faerre_end_gulvet_afbryder_foer_skrivning(self):
        """Under TESLA_FLOOR anlaeg, der kan skrives, rejser RuntimeError FOER adresseopslaget og skrivningen: filen
        er byte-identisk. De oversprungne taeller ikke med - heller ikke et over 600 kW (review 14-10-2026), hverken
        i gulvet eller i maerke-vagten. Uden maerke-vagten afbryder gulvet selv; med den rigtige vagt (kopien har
        repoets Tesla-raekker) afbrydes ogsaa foer skrivning."""
        gulv = refresh_data.TESLA_FLOOR
        kilde = self.kilde[:gulv - 1] + [anlaeg('Test Semi', kw=1000), anlaeg('Test Sverige', land='Sweden'),
                                        anlaeg('Test under opfoerelse', status='CONSTRUCTION'),
                                        anlaeg('Test 150 kW', kw=150)]
        vagt = []
        with self.assertRaises(RuntimeError) as cm:
            self.koer(kilde, vagt=vagt)
        self.assertIn(f'Tesla returnerede kun {gulv - 1} anlæg', str(cm.exception))
        self.assertEqual(vagt, [(FIL, 'Tesla', gulv - 1)])
        self.assertTrue(self.raa() == self.foer, 'filen blev skrevet trods for faa anlaeg')
        self.assertEqual(self.normaliseret, [])
        with self.assertRaises(RuntimeError) as cm:
            self.koer(kilde)
        self.assertIn('AFBRYDER før skrivning', str(cm.exception))
        self.assertTrue(self.raa() == self.foer, 'filen blev skrevet trods for faa anlaeg')
        self.assertEqual(self.normaliseret, [])

    def test_skrevet_fil_bevarer_andre_raekker_og_holder_ladereglerne(self):
        """Den skrevne fil, ogsaa naar kilden har skaeve vaerdier: hver raekke, der ikke er Tesla, er byte-identisk og
        i samme raekkefoelge (og repoets Tesla-raekker kommer byte-identisk tilbage); UTF-8 med BOM og CRLF, sorteret
        efter (Operatoer, Postnr), og Tesla-raekkerne holder data-testens laderegler (kW i refresh_retail.LADE_KW,
        antal '' eller 1..LADE_MAX_ANTAL) - de oevrige er uroerte, saa filen holder dem, naar den gamle gjorde.
        Graenseanlaeggene tages fra refresh_retail, saa flyttes en graense dér uden i refresh_data, fanges det
        her - foer data-testen stopper ugen (review 14-10-2026). En uge uden aendringer giver en byte-identisk
        fil og ingen melding."""
        (n, _), err = self.koer(self.kilde)
        self.assertTrue(self.raa() == self.foer, 'en uge uden aendringer gav en anden fil')
        self.assertEqual((n, err), (len(self.kilde), ''))

        hi, maks = R.LADE_KW['bil'][1], R.LADE_MAX_ANTAL
        skaeve = [anlaeg('Test Semi', kw=1000, gade='Industrivej 1', postnr='6330', by='Padborg', p=(54.8266, 9.3614)),
                  anlaeg('Test paa loftet', kw=hi, antal=maks, postnr='1050', by='København K', p=(55.6796, 12.5857)),
                  anlaeg('Test over loftet', kw=hi + 1, postnr='7400', by='Herning', p=(56.138, 8.973)),
                  anlaeg('Test 325.0 kW', kw=325.0, antal=maks + 1, postnr='5000', by='Odense C', p=(55.396, 10.388)),
                  anlaeg('Test antal 0', antal=0, postnr='8000', by='Aarhus C', p=(56.157, 10.211)),
                  anlaeg('Test antal null', antal=None, postnr='3700', by='Rønne', p=(55.1, 14.7)),
                  anlaeg('Test antal 150', antal=150, postnr='4600', by='Køge', p=(55.458, 12.182)),
                  anlaeg('Test antal mangler', antal=UDEN, postnr='9990', by='Skagen', p=(57.7209, 10.5839)),
                  anlaeg('Test Sverige', kw=1000, antal=150, land='Sweden', postnr='21120', by='Malmö',
                         p=(55.605, 13.0038))]
        skrevne = ['Test paa loftet', 'Test 325.0 kW', 'Test antal 0', 'Test antal null', 'Test antal 150',
                   'Test antal mangler']
        (n, alle), _ = self.koer(self.kilde + skaeve)
        b = self.raa()
        self.assertTrue(b.startswith(BOM), 'mangler BOM')
        self.assertTrue(b.endswith(b'\r\n'), 'sidste linje uden CRLF')
        self.assertEqual(b.count(b'\n'), b.count(b'\r\n'), 'linjeskift uden CR')
        self.assertEqual(b.count(b'\r'), b.count(b'\r\n'), 'CR uden LF')
        hoved, rows = laes(b)
        self.assertEqual(hoved, self.hoved)
        self.assertEqual([r for r in rows if len(r) != len(hoved)], [])
        fl, el = self.foer[len(BOM):].split(b'\r\n'), b[len(BOM):].split(b'\r\n')

        def er_tesla(linje):
            return linje.startswith(b'Tesla,')
        self.assertEqual([x for x in el if not er_tesla(x)], [x for x in fl if not er_tesla(x)],
                         'andre raekker (eller hovedet) er aendret, flyttet eller tabt')
        ft, et = collections.Counter(filter(er_tesla, fl)), collections.Counter(filter(er_tesla, el))
        self.assertEqual(ft - et, collections.Counter(), 'repoets Tesla-raekker kom ikke byte-identisk tilbage')
        nye = sorted(next(csv.reader([x.decode('utf-8')]))[1] for x in (et - ft).elements())
        self.assertEqual(nye, sorted(NAVN + x for x in skrevne))
        self.assertEqual((n, alle), (len(self.kilde) + len(skrevne), len(rows)))
        self.assertEqual([len(x) for x in self.normaliseret], [n])
        noegle = [(r[0], r[3]) for r in rows]
        self.assertEqual(noegle, sorted(noegle), 'ikke sorteret efter (Operatoer, Postnr)')
        self.assertEqual(regelbrud([r for r in rows if r[0] == 'Tesla']), [])


if __name__ == '__main__':
    unittest.main()
