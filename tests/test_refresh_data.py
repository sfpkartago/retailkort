import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

# Selvtest af refresh_data.refresh_tesla() og af scriptets hovedloekke (__main__).
#
# refresh_tesla: den ugentlige udskiftning af Tesla-raekkerne i superladere_dk.csv med supercharge.info's
# faellesskabsdata. Review 14-10-2026: refresh_tesla skrev powerKilowatt og stallCount ukontrolleret, saa én
# vaerdi fra faellesskabsdataene (et Semi-anlaeg paa 1.000 kW, '325.0', et antal paa 150) kunne stoppe hele
# ugens udgivelse ved den blokerende data-test (tests/test_data.py, Ladere). Et anlaeg, vi allerede har, og som
# kilden pludselig melder over 600 kW, beholder nu sidste uges raekke i stedet for at forsvinde stille.
#
# Hver test koerer den rigtige refresh_tesla() mod en lille SYNTETISK superladere_dk.csv (fixtur() nedenfor) i en
# midlertidig mappe (refresh_data.OUT) - ikke mod repoets fil. Review 14-10-2026: testene laeste repoets CSV og
# kraevede, at refresh_tesla skrev den byte-identisk tilbage, saa en haandrettet Tesla-pin med 7 decimaler eller en
# tilfoejet raekke fik det BLOKERENDE testtrin foer hentningen til at fejle hver uge. refresh_data.get er stubbet
# til en supercharge.info-lignende liste - fixturens Tesla-raekker, som kilden leverer dem, plus testens anlaeg -
# og normalize_rows til (0, 0) med raekkerne uroerte. Intet net, ingen noegle, og repoets CSV'er roeres ikke (det
# tjekkes efter hver test; deres indhold er ligegyldigt). At refresh_data.get spoerger robots.txt foerst, proeves i
# tests/test_net.py (test_refresh_data_get_forbudt_uden_urlopen).
#
# Hovedprogram: scriptet koert som '__main__' (runpy.run_path paa en kopi i en midlertidig mappe, saa OUT er dén)
# med robots.txt lagt i retail_sources' cache og et stubbet urlopen. Review 14-10-2026: et robots-stop for én
# kilde er en advarsel, ikke et stop for hele ugens job; alle andre fejl afbryder som foer.
# Koer fra repo-roden:  python3 -m unittest -v tests.test_refresh_data
import collections
import contextlib
import copy
import csv
import io
import json
import runpy
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

import dawa
import refresh_data
import refresh_retail as R
import retail_sources as RS

FIL = 'superladere_dk.csv'
TANK = 'tankstationer_dk.csv'
TESLA_URL = 'https://supercharge.info/service/supercharge/allSites'
OK_URL = 'https://mobility-prices.ok.dk/api/v1/fuel-prices'
BOM = b'\xef\xbb\xbf'
NAVN = 'Tesla Supercharger '        # refresh_tesla's praefiks foran kildens navn
UDEN = object()                     # anlaeg(antal=UDEN): feltet stallCount mangler helt

# ---------------------------------------------------------------- fixturen (review 14-10-2026)
# Det rigtige hoved (= tests/test_data.py's FILER['superladere_dk.csv'], som dér tjekkes mod repoets fil) og raekker
# i den form, csv.writer skriver dem. De andre operatoerers raekker har komma, anfoerselstegn, æøå, en haandrettet
# pin med 7 decimaler og en lastbilraekke: refresh_tesla skal skrive dem byte-identisk tilbage. Tesla-raekkerne er
# TESLA_FLOOR + 4 i refresh_tesla's egen form, saa gulvet og maerke-vagten passer til fixturen uden stub - ogsaa i
# scriptkoerslen (Hovedprogram), hvor refresh_data's konstanter ikke kan patches.
HOVED = ['Operatør', 'Navn', 'Adresse', 'Postnr', 'By', 'Effekt_kW', 'Stik', 'Antal_ladere', 'Latitude',
         'Longitude', 'Lastbil']
ANDRE = (
    ['Allego', 'Allego Taastrup', 'Helgeshøj Alle 32E, 2630 Taastrup', '2630', 'Taastrup', '300', 'CCS', '4',
     '55.6608812', '12.2852761', ''],
    ['Circle K', 'Circle K Padborg Lastbil', 'Industrivej 3, 6330 Padborg', '6330', 'Padborg', '1000', 'MCS', '2',
     '54.8266', '9.3614', 'ja'],
    ['Clever', 'Clever "Nord", Aalborg', 'Hobrovej 1, 9000 Aalborg', '9000', 'Aalborg', '300', 'CCS', '',
     '57.02', '9.9', ''],
    ['TotalEnergies', 'Thisted ladepark', 'Aalborgvej 117A, 7700 Thisted', '7700', 'Thisted', '300', 'CCS', '4',
     '56.972373', '8.742147', ''],
    ['Uno-X', 'Uno-X Køge', 'Ølbyvej 2, 4600 Køge', '4600', 'Køge', '400', 'CCS', '8', '55.458', '12.182', ''],
)
KENDT = NAVN + 'Testby 05'          # et af fixturens anlaeg (review 14-10-2026: kilden melder det over 600 kW)


def tesla_raekker(antal):
    """antal Tesla-raekker, som refresh_tesla selv skriver dem: navnet med praefikset, 'gade, postnr by', kW og antal
    inden for lagets graenser (refresh_retail), koordinater med hoejst 6 decimaler og hvert sit postnr i stigende
    orden. Én har komma og anfoerselstegn i navnet."""
    lo, hi = R.LADE_KW['bil']
    kw, stik = (str(lo), str((lo + hi) // 2), str(hi)), ('12', '', str(R.LADE_MAX_ANTAL), '1')
    ud = []
    for i in range(antal):
        by, postnr = f'Testby {i:02d}', str(1000 + i * (8900 // antal))
        navn = by + (' "Øst", Motorvej' if i == 7 else '')
        ud.append(['Tesla', NAVN + navn, f'Testvej {i + 1}, {postnr} {by}', postnr, by, kw[i % 3], 'CCS+Tesla',
                   stik[i % 4], repr(round(54.62 + 0.097 * i, 6)), repr(round(8.15 + 0.2 * i, 6)), ''])
    return ud


def fixtur():
    """Fixturens raekker (uden hoved), sorteret som refresh_tesla sorterer: efter (Operatoer, Postnr)."""
    rows = [list(r) for r in ANDRE] + tesla_raekker(refresh_data.TESLA_FLOOR + 4)
    return sorted(rows, key=lambda x: (x[0], x[3]))


def csv_bytes(hoved, rows):
    """-> filen, som refresh_data.write skriver den: UTF-8 med BOM, CRLF og csv.writer's citering."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(hoved)
    w.writerows(rows)
    return BOM + buf.getvalue().encode('utf-8')


def repoets_filer():
    """Repoets egne CSV'er (bytes, None hvis filen mangler) - kun for at se, at en test ikke skriver i dem. Indholdet
    er ligegyldigt: testene maa ikke afhaenge af det (review 14-10-2026)."""
    ud = {}
    for fn in (FIL, TANK):
        try:
            with open(os.path.join(hjaelp.ROD, fn), 'rb') as f:
                ud[fn] = f.read()
        except FileNotFoundError:
            ud[fn] = None
    return ud


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
    """refresh_data.refresh_tesla() mod fixturen i en midlertidig mappe (se filens hoved)."""

    def setUp(self):
        foer = repoets_filer()
        self.addCleanup(lambda: self.assertTrue(repoets_filer() == foer, "testen har skrevet i repoets CSV'er"))
        self.raekker = fixtur()
        self.hoved, self.foer = HOVED, csv_bytes(HOVED, self.raekker)
        self.kilde = [som_kilde(r) for r in self.raekker if r[0] == 'Tesla']
        self.assertGreaterEqual(len(self.kilde), refresh_data.TESLA_FLOOR, 'fixturen har for faa Tesla-raekker')
        self.mappe = tempfile.mkdtemp(prefix='test_refresh_data_')
        self.addCleanup(shutil.rmtree, self.mappe, True)
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

    def koer(self, kilde, vagt=None, foer=None):
        """Laeg fixturen (eller `foer`: sidste uges fil) i mappen, koer refresh_tesla() med kilden og fang stderr
        -> (svar, stderr). vagt: en liste, der fanger kaldene til _maerke_vagt, som saa ikke afbryder (kun til
        gulv-testene)."""
        with open(os.path.join(self.mappe, FIL), 'wb') as f:
            f.write(self.foer if foer is None else foer)
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
        """Et NYT dansk, aabent anlaeg paa 1.000 kW (Semi; ikke i sidste uges fil) er ikke en billader: det udelades
        og naevnes paa stderr ('over 600 kW'); 600 kW er lagets loft og skrives, 601 udelades. Et svensk 1.000
        kW-anlaeg naevnes ikke (allSites har hele verdens anlaeg; kun de danske er vores). Review 14-10-2026:
        anlaegget blev skrevet, og data-testen (kW 250-600 for en billader) ville have stoppet hele ugens
        udgivelse. (Et anlaeg, vi allerede har: test_kendt_anlaeg_over_600_kw_beholder_sidste_uges_raekke.)"""
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

    def test_anlaeg_over_loftet_to_gange_eller_ogsaa_frisk_giver_ingen_dublet(self):
        """Testene 14-10-2026: et kendt anlaeg, som allSites lister to gange over 600 kW, fik sidste uges raekke
        skrevet to gange; og et kendt anlaeg, der baade staar frisk (250 kW) og over loftet (1000 kW) under samme
        navn, fik baade den friske og den gamle raekke - dubletter, som den blokerende data-test stopper ugen paa.
        Nu skrives hvert navn én gang, og den friske raekke vinder."""
        to_gange, frisk_og_over = sorted(r[1] for r in self.raekker if r[0] == 'Tesla')[:2]
        kort = lambda n: n[len(NAVN):]
        kilde = [a for a in self.kilde if a['name'].replace(', Denmark', '') not in (kort(to_gange), kort(frisk_og_over))]
        kilde += [anlaeg(kort(to_gange), kw=1000, p=(55.70, 9.50)), anlaeg(kort(to_gange), kw=1000, p=(55.71, 9.51)),
                  anlaeg(kort(frisk_og_over), kw=250, p=(55.80, 9.60)), anlaeg(kort(frisk_og_over), kw=1000, p=(55.81, 9.61))]
        self.koer(kilde)
        alle = [r for r in laes(self.raa())[1] if r[0] == 'Tesla']
        for navn in (to_gange, frisk_og_over):
            with self.subTest(navn):
                self.assertEqual(sum(1 for r in alle if r[1] == navn), 1, [r for r in alle if r[1] == navn])
        self.assertEqual(self.tesla()[frisk_og_over][5], '250')

    def test_udenlandske_ikke_aabne_og_under_250_kw_springes_over(self):
        """Som foer (uaendret ved review 14-10-2026): kun danske, aabne anlaeg paa mindst 250 kW skrives. Et svensk,
        et under opfoerelse, midlertidigt lukket eller kun med tilladelse, 249 og 150 kW, uden effekt og uden adresse
        springes tavst over (ingen er over 600 kW) - og er resten fixturens egne anlaeg, er filen byte-identisk."""
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
        er byte-identisk. De oversprungne taeller ikke med - heller ikke et NYT over 600 kW (review 14-10-2026),
        hverken i gulvet eller i maerke-vagten. Uden maerke-vagten afbryder gulvet selv; med den rigtige vagt
        (fixturen har TESLA_FLOOR + 4 Tesla-raekker) afbrydes ogsaa foer skrivning."""
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
        i samme raekkefoelge (og fixturens Tesla-raekker kommer byte-identisk tilbage); UTF-8 med BOM og CRLF,
        sorteret efter (Operatoer, Postnr), og Tesla-raekkerne holder data-testens laderegler (kW i
        refresh_retail.LADE_KW, antal '' eller 1..LADE_MAX_ANTAL) - de oevrige er uroerte, saa filen holder dem, naar
        den gamle gjorde. Graenseanlaeggene tages fra refresh_retail, saa flyttes en graense dér uden i refresh_data,
        fanges det her - foer data-testen stopper ugen (review 14-10-2026). En uge uden aendringer giver en
        byte-identisk fil og ingen melding."""
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
        self.assertEqual(ft - et, collections.Counter(), 'fixturens Tesla-raekker kom ikke byte-identisk tilbage')
        nye = sorted(next(csv.reader([x.decode('utf-8')]))[1] for x in (et - ft).elements())
        self.assertEqual(nye, sorted(NAVN + x for x in skrevne))
        self.assertEqual((n, alle), (len(self.kilde) + len(skrevne), len(rows)))
        self.assertEqual([len(x) for x in self.normaliseret], [n])
        noegle = [(r[0], r[3]) for r in rows]
        self.assertEqual(noegle, sorted(noegle), 'ikke sorteret efter (Operatoer, Postnr)')
        self.assertEqual(regelbrud([r for r in rows if r[0] == 'Tesla']), [])

    def test_kendt_anlaeg_over_600_kw_beholder_sidste_uges_raekke(self):
        """Review 14-10-2026: et anlaeg, vi allerede har (samme raekkenavn 'Tesla Supercharger <navn>'), og som
        supercharge.info nu melder over 600 kW (en tastefejl i faellesskabsdataene), forsvinder ikke stille: sidste
        uges raekke staar uaendret - ogsaa en haandrettet adresse og en pin med 7 decimaler - og den sendes IKKE
        gennem normalize_rows (der flytter adressen til naermeste DAR-punkt). Et NYT anlaeg over 600 kW udelades
        stadig. Begge naevnes paa stderr sammen med en '::warning::'-linje til Action'en, og den beholdte raekke
        taeller med i svaret."""
        raekker = copy.deepcopy(self.raekker)
        kendt = next(r for r in raekker if r[1] == KENDT)
        kendt[2] = kendt[2].replace('Testvej', 'Rettet Vej')       # haandrettet i sidste uge ...
        kendt[8], kendt[9] = '55.1234567', '10.7654321'           # ... ogsaa pinnen (7 decimaler)
        foer = csv_bytes(HOVED, raekker)
        kilde = copy.deepcopy(self.kilde)                         # kilden har sin egen adresse og pin
        next(a for a in kilde if a['name'] == KENDT[len(NAVN):] + ', Denmark')['powerKilowatt'] = 1000
        ny = anlaeg('Test Semi', kw=1200, gade='Industrivej 1', postnr='6330', by='Padborg', p=(54.8266, 9.3614))
        (n, alle), err = self.koer(kilde + [ny], foer=foer)
        self.assertTrue(self.raa() == foer, 'sidste uges fil kom ikke byte-identisk tilbage (den kendte raekke '
                                            'uaendret, det nye anlaeg over 600 kW udeladt)')
        self.assertEqual([[r for r in rows if r[1] == KENDT] for rows in self.normaliseret], [[]],
                         'den beholdte raekke gik gennem normalize_rows')
        self.assertEqual([len(rows) for rows in self.normaliseret], [len(kilde) - 1])
        self.assertEqual((n, alle), (len(kilde), len(raekker)))
        for tekst in (KENDT + ' (1000 kW)', NAVN + 'Test Semi (1200 kW)', '1 beholdt'):
            self.assertIn(tekst, err)
        advarsel = [x for x in err.splitlines() if x.startswith('::warning::')]
        self.assertEqual(len(advarsel), 1, err)
        self.assertIn('Tesla', advarsel[0])
        self.assertIn('600 kW', advarsel[0])

    def test_kendt_anlaeg_over_600_kw_taeller_med_i_gulv_og_vagt(self):
        """Review 14-10-2026: den beholdte raekke taeller med i TESLA_FLOOR, maerke-vagten og svaret - ellers stoppede
        en tastefejl i kilden en uge med praecis gulvet - og den skrives uaendret uden adresseopslag. Kilden har her
        TESLA_FLOOR anlaeg, hvoraf ét kendt melder 1.000 kW."""
        gulv = refresh_data.TESLA_FLOOR
        kilde = copy.deepcopy(self.kilde[:gulv])
        kilde[-1]['powerKilowatt'] = 1000
        kendt = NAVN + kilde[-1]['name'].replace(', Denmark', '')
        vagt = []
        (n, _), err = self.koer(kilde, vagt=vagt)
        self.assertEqual(vagt, [(FIL, 'Tesla', gulv)])
        self.assertEqual(n, gulv)
        t = self.tesla()
        self.assertEqual(len(t), gulv)
        self.assertEqual(t[kendt], next(r for r in self.raekker if r[1] == kendt))
        self.assertEqual([len(x) for x in self.normaliseret], [gulv - 1])
        self.assertIn(kendt + ' (1000 kW)', err)


# ---------------------------------------------------------------- scriptet (__main__)
OK_VAERT, TESLA_VAERT = 'https://mobility-prices.ok.dk', 'https://supercharge.info'
TILLADER, FORBYDER = 'User-agent: *\nAllow: /\n', 'User-agent: *\nDisallow: /\n'
TANK_HOVED = ['Mærke', 'Navn', 'Adresse', 'Postnr', 'By', 'Latitude', 'Longitude', 'Lastbil']   # = tests/test_data.py
TANK_RAEKKER = (['Circle K', 'Circle K Vejle', 'Vestre Engvej 2, 7100 Vejle', '7100', 'Vejle', '55.7', '9.5', ''],
                ['OK', 'OK Aarhus C', 'Testvej 1, 8000 Aarhus C', '8000', 'Aarhus C', '56.15', '10.2', ''],
                ['Q8', 'Q8 Padborg', 'Industrivej 1, 6330 Padborg', '6330', 'Padborg', '54.82', '9.36', 'ja'])


def ok_svar(antal):
    """OK's pris-API, som refresh_ok laeser det: antal stationer med hver sin adresse og koordinat."""
    return {'items': [{'street': 'Testvej', 'house_number': str(i + 1), 'postal_code': str(1000 + i % 8000),
                       'city': 'Testby', 'coordinates': {'latitude': 55 + i / 1000, 'longitude': 10 + i / 1000}}
                      for i in range(antal)]}


class Hovedprogram(unittest.TestCase):
    """refresh_data.py som script: '__main__' koert i processen med runpy.run_path paa en kopi af den rigtige fil i en
    midlertidig mappe, saa OUT - og dermed CSV'erne - er dén. robots.txt ligger i retail_sources' cache (intet hentes),
    urlopen svarer kun paa testens adresser, og normalize_rows og DAR-laasen er stubbet; nettet er spaerret
    (tests/hjaelp.py). Review 14-10-2026: et robots-stop for ÉN kilde maatte ikke stoppe hele ugens job."""

    def setUp(self):
        foer = repoets_filer()
        self.addCleanup(lambda: self.assertTrue(repoets_filer() == foer, "scriptet har skrevet i repoets CSV'er"))
        self.mappe = tempfile.mkdtemp(prefix='test_refresh_data_main_')
        self.addCleanup(shutil.rmtree, self.mappe, True)
        self.script = os.path.join(self.mappe, 'refresh_data.py')
        shutil.copyfile(os.path.join(hjaelp.ROD, 'refresh_data.py'), self.script)
        self.addCleanup(sys.path_importer_cache.pop, self.script, None)     # run_path's opslag af stien
        # retail_sources' robots- og Crawl-delay-tilstand er global: frisk pr. test (som tests/test_net.py).
        for d in (RS._ROBOTS, RS._ROBOTS_GRUND, RS._ROBOTS_FORBIGAAENDE, RS._SIDSTE_KALD, RS._KALD_LAASE, RS._VENTET):
            self._start(mock.patch.dict(d, clear=True))
        self._start(mock.patch.object(RS, 'ROBOTS_STOP', []))
        self._start(mock.patch.object(RS, 'OMDIRIGERING_STOP', []))
        self._start(mock.patch.object(RS, '_ROBOTS_HENTES', threading.local()))
        self._start(mock.patch.object(RS, '_ROBOTS_LAAS', threading.Lock()))
        self._start(mock.patch.object(RS.time, 'sleep'))                   # ingen genforsoegs-pauser
        # Scriptet laeser dem med 'from dawa import ...', naar run_path koerer det - derfor dawa's navne.
        self.laas = self._start(mock.patch.object(dawa, 'tag_dar_laas'))
        self._start(mock.patch.object(dawa, 'normalize_rows', self._normalize))
        self._start(mock.patch.object(urllib.request, 'urlopen', side_effect=self._urlopen))
        self.tesla_kilde = [som_kilde(r) for r in fixtur() if r[0] == 'Tesla'] + [
            anlaeg('Test Ny', kw=300, antal=8, gade='Ny Vej 1', postnr='4000', by='Roskilde', p=(55.64, 12.08))]
        self.n_ok = refresh_data.OK_FLOOR + 5

    def _start(self, p):
        v = p.start()
        self.addCleanup(p.stop)
        return v

    def _normalize(self, rows, adr, postnr, by, lat, lon, workers=10, status_ud=None, bygning=None):
        self.normaliseret.append(len(rows))
        if status_ud is not None:
            status_ud.extend('ok' for _ in rows)
        return 0, 0

    def _urlopen(self, req, timeout=None, **kw):
        url = req.full_url if isinstance(req, urllib.request.Request) else req
        self.anmodninger.append(url)
        if url not in self.svar:
            raise AssertionError('uventet netkald i testen: ' + url)
        x = self.svar[url]
        if isinstance(x, BaseException):
            raise x
        return io.BytesIO(json.dumps(x).encode('utf-8'))

    def koer(self, robots, svar, grund=None):
        """Laeg friske CSV'er i mappen og koer scriptet med robots.txt pr. vaert i cachen (None: kunne ikke laeses;
        grund: hvorfor) og urlopen-svarene `svar` (url -> JSON eller en undtagelse)
        -> (exit-status, stdout, stderr, sys.exit-beskeden eller None)."""
        for fn, b in ((FIL, csv_bytes(HOVED, fixtur())), (TANK, csv_bytes(TANK_HOVED, TANK_RAEKKER))):
            with open(os.path.join(self.mappe, fn), 'wb') as f:
                f.write(b)
        RS._ROBOTS.clear()
        RS._ROBOTS.update(robots)
        RS._ROBOTS_GRUND.clear()
        RS._ROBOTS_GRUND.update(grund or {})
        del RS.ROBOTS_STOP[:]
        self.svar, self.anmodninger, self.normaliseret = svar, [], []
        self.laas.reset_mock()
        out, err, status, besked = io.StringIO(), io.StringIO(), 0, None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                runpy.run_path(self.script, run_name='__main__')
            except SystemExit as e:
                # Som Python selv: None -> 0, et heltal -> tallet, alt andet skrives paa stderr og giver 1.
                if e.code is None or isinstance(e.code, int):
                    status = e.code or 0
                else:
                    status, besked = 1, str(e.code)
        self.laas.assert_called_once_with('refresh_data.py')
        return status, out.getvalue(), err.getvalue(), besked

    def fil(self, fn):
        with open(os.path.join(self.mappe, fn), 'rb') as f:
            return f.read()

    def test_robots_stop_for_ok_er_en_advarsel_og_tesla_koerer(self):
        """Review 14-10-2026: forbyder OK's robots.txt pris-API'et, skriver scriptet en '::warning::OK'-linje (OK's
        raekker fra sidste uge bliver staaende), henter IKKE OK, koerer Tesla til ende og slutter med status 0. Foer
        stoppede ét robots-stop hele ugens job (75 kilder, rebuild, rapporter) med AFBRYDER."""
        status, out, err, besked = self.koer({OK_VAERT: FORBYDER, TESLA_VAERT: TILLADER},
                                             {TESLA_URL: self.tesla_kilde})
        self.assertEqual((status, besked), (0, None), out + err)
        self.assertEqual(self.anmodninger, [TESLA_URL], 'OK (eller en robots.txt) blev hentet')
        advarsel = [x for x in out.splitlines() if x.startswith('::warning::')]
        self.assertEqual(len(advarsel), 1, out)
        self.assertTrue(advarsel[0].startswith('::warning::OK: robots.txt paa mobility-prices.ok.dk'), advarsel)
        self.assertIn('sidste uges raekker bliver staaende', advarsel[0])
        self.assertTrue(self.fil(TANK) == csv_bytes(TANK_HOVED, TANK_RAEKKER), 'OK-filen blev roert trods robots-stop')
        self.assertIn(NAVN + 'Test Ny', [r[1] for r in laes(self.fil(FIL))[1]], 'Tesla skrev ikke sin fil')
        self.assertEqual(self.normaliseret, [len(self.tesla_kilde)])
        self.assertIn('Tesla superladere:', out)
        self.assertIn('Færdig.', out)
        self.assertNotIn('AFBRYDER', out + err)

    def test_robots_stop_for_tesla_er_en_advarsel_og_ok_koerer(self):
        """Review 14-10-2026: det samme for Tesla - robots.txt forbyder stien, kunne ikke laeses (regnes som forbud),
        eller svaret omdirigerer til en forbudt sti (RobotsOmdirigeringForbudt, en RobotsForbudt): én
        '::warning::Tesla'-linje, Tesla-filen uroert (sidste uges raekker staar), OK koerer til ende, status 0."""
        omdirigeret = RS.RobotsOmdirigeringForbudt('robots.txt paa supercharge.info forbyder /x (omdirigering) - '
                                                   'foelger ikke')
        tilfaelde = (('forbyder', {TESLA_VAERT: 'User-agent: *\nDisallow: /service/\n'}, {}, {},
                      'forbyder /service/supercharge/allSites'),
                     ('kan ikke laeses', {TESLA_VAERT: None}, {TESLA_VAERT: 'HTTP 503'}, {}, 'kunne ikke laeses'),
                     ('omdirigering', {TESLA_VAERT: TILLADER}, {}, {TESLA_URL: omdirigeret}, '(omdirigering)'))
        for navn, robots, grund, ekstra, tekst in tilfaelde:
            with self.subTest(navn):
                status, out, err, besked = self.koer({OK_VAERT: TILLADER, **robots},
                                                     {OK_URL: ok_svar(self.n_ok), **ekstra}, grund)
                self.assertEqual((status, besked), (0, None), out + err)
                self.assertEqual(self.anmodninger, [OK_URL] + list(ekstra))
                advarsel = [x for x in out.splitlines() if x.startswith('::warning::')]
                self.assertEqual(len(advarsel), 1, out)
                self.assertTrue(advarsel[0].startswith('::warning::Tesla: '), advarsel)
                self.assertIn(tekst, advarsel[0])
                self.assertIn('sidste uges raekker bliver staaende', advarsel[0])
                self.assertTrue(self.fil(FIL) == csv_bytes(HOVED, fixtur()), 'Tesla-filen blev roert trods robots-stop')
                ok = [r for r in laes(self.fil(TANK))[1] if r[0] == 'OK']
                self.assertEqual(len(ok), self.n_ok, 'OK skrev ikke sin fil')
                self.assertEqual(self.normaliseret, [self.n_ok])
                self.assertIn('OK tankstationer:', out)
                self.assertNotIn('AFBRYDER', out + err)

    def test_anden_fejl_afbryder_med_status_1(self):
        """Review 14-10-2026: kun et robots-stop er en advarsel. Enhver anden fejl afbryder som foer med 'AFBRYDER' og
        exit-status 1, efter at den anden kilde er proevet - ogsaa en RuntimeError (som RobotsForbudt arver fra):
        Tesla under maerke-vagten. Et samtidigt robots-stop for OK staar kun som advarsel, ikke i AFBRYDER-listen;
        en netfejl hos OK afbryder, og Tesla koeres alligevel."""
        with self.subTest('OK robots-stop, Tesla under vagten'):
            status, out, err, besked = self.koer({OK_VAERT: FORBYDER, TESLA_VAERT: TILLADER},
                                                 {TESLA_URL: self.tesla_kilde[:3]})
            self.assertEqual(status, 1, out + err)
            self.assertTrue(besked.startswith('AFBRYDER:\n'), besked)
            punkter = besked.split('\n')[1:]
            self.assertEqual([x.split(':')[0] for x in punkter], ['  - Tesla'], besked)
            self.assertIn('AFBRYDER før skrivning', punkter[0])
            self.assertEqual(len([x for x in out.splitlines() if x.startswith('::warning::OK: ')]), 1, out)
            self.assertTrue(self.fil(FIL) == csv_bytes(HOVED, fixtur()), 'Tesla-filen blev skrevet trods fejlen')
            self.assertEqual(self.anmodninger, [TESLA_URL])
        with self.subTest('netfejl hos OK, Tesla i orden'):
            status, out, err, besked = self.koer({OK_VAERT: TILLADER, TESLA_VAERT: TILLADER},
                                                 {OK_URL: urllib.error.URLError('timed out'),
                                                  TESLA_URL: self.tesla_kilde})
            self.assertEqual((status, besked), (1, 'AFBRYDER:\n  - OK: <urlopen error timed out>'), out + err)
            self.assertEqual(self.anmodninger, [OK_URL, TESLA_URL])
            self.assertIn('Tesla superladere:', out)
            self.assertNotIn('::warning::', out + err)
            self.assertNotIn('Færdig.', out)


if __name__ == '__main__':
    unittest.main()
