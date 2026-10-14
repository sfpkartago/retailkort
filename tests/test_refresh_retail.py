import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

# Selvtest af refresh_retail.main(): den ugentlige fletning, der KUN TILFOEJER.
#
# Hver test koerer den rigtige main() mod seks smaa syntetiske CSV'er i en midlertidig mappe
# (med repoets RIGTIGE kolonnehoveder) og stubbede hentere. Adresseopslaget er stubbet paa det
# laveste niveau main() selv kalder: normalize_rows (status 'ok', raekken uroert) og
# reverse_full (adressen ligger paa selve punktet). Intet net, ingen noegle, ingen rigtige filer.
# Koer fra repo-roden:  python3 -m unittest -v tests.test_refresh_retail
import collections
import contextlib
import csv
import io
import math
import re
import shutil
import tempfile
import time
import unittest
from unittest import mock

import dawa
import refresh_retail as R

DAG, UDV, PLADS = 'dagligvarer_dk.csv', 'udvalgsvarer_dk.csv', 'pladskraevende_dk.csv'
TANK, FAST, LADE = 'tankstationer_dk.csv', 'fastfood_kaeder_dk.csv', 'superladere_dk.csv'
BOM = b'\xef\xbb\xbf'
M_PR_GRAD = 6371000.0 * math.pi / 180      # meter pr. breddegrad paa R.hav's kugle

# Danske punkter (lat, lon); alle inden for 54,6-57,7 / 8,1-15,1.
AALBORG, AALBORG_SC = (57.048, 9.919), (57.0, 9.88)        # ~5,8 km fra hinanden
AARHUS, AARHUS_N, AARUP = (56.157, 10.211), (56.18, 10.2), (55.37, 10.04)
BALLERUP, BROENSHOEJ, BROERUP = (55.731, 12.363), (55.705, 12.49), (55.48, 9.02)
ESBJERG, FRB, FREDERIKSVAERK = (55.467, 8.452), (55.6786, 12.532), (55.97, 12.02)
GALTEN, HAARBY, HAVERSLEV = (56.155, 9.91), (55.22, 10.12), (56.79, 9.87)
HERNING, HILLEROED, HORSENS = (56.138, 8.973), (55.927, 12.3), (55.861, 9.85)
KOEGE, KOLDING, KORSOER = (55.458, 12.182), (55.49, 9.472), (55.33, 11.14)
LALANDIA, ODENSE, RANDERS = (55.732, 9.13), (55.396, 10.388), (56.46, 10.036)
RIBE, ROSKILDE, SOEBY = (55.33, 8.76), (55.64, 12.08), (55.27, 10.53)
SVINNINGE, TILST, VEJEN = (55.72, 11.46), (56.19, 10.11), (55.48, 9.14)
VEJLE, VIBORG = (55.709, 9.536), (56.451, 9.402)


def _rigtige_hoveder():
    """Kolonnehovederne laeses fra repoets egne CSV'er - de skrives ikke af i testen."""
    ud = {}
    for fn in R.FILER:
        with open(os.path.join(hjaelp.ROD, fn), encoding='utf-8-sig', newline='') as f:
            ud[fn] = next(csv.reader(f))
    return ud


HOVED = _rigtige_hoveder()


def nord(p, m):
    """Punktet m meter nord for p (paa en meridian er R.hav's afstand eksakt)."""
    return (round(p[0] + m / M_PR_GRAD, 6), p[1])


def gitter(n, start, trin=0.05):
    """n punkter i et gitter med >= 3 km mellem naboerne."""
    side = int(math.ceil(math.sqrt(n)))
    return [(round(start[0] + (i // side) * trin, 6), round(start[1] + (i % side) * trin, 6))
            for i in range(n)]


def ll(p):
    return [f'{p[0]:.6f}', f'{p[1]:.6f}']


def butik(maerke, navn, gade, postnr, by, p):
    """Vores egen raekke i en 7-kolonners fil (Maerke..Longitude)."""
    return [maerke, navn, f'{gade}, {postnr} {by}', postnr, by] + ll(p)


def tank(maerke, navn, gade, postnr, by, p, lastbil=''):
    """Vores raekke i tankfilen: 8. kolonne er Lastbil."""
    return butik(maerke, navn, gade, postnr, by, p) + [lastbil]


def lader(op, navn, gade, postnr, by, kw, stik, antal, p, lastbil=''):
    """Vores raekke i ladefilen: kW, stik og antal FOER koordinaterne, Lastbil sidst."""
    return [op, navn, f'{gade}, {postnr} {by}', postnr, by, str(kw), stik, str(antal)] + ll(p) + [lastbil]


def post(brand, name, street, postnr, by, p, **ekstra):
    """En kildepost, som henterne leverer dem."""
    d = {'brand': brand, 'name': name, 'street': street, 'postnr': postnr, 'by': by,
         'lat': p[0], 'lon': p[1]}
    d.update(ekstra)
    return d


def som_kilde(r, **ekstra):
    """Vores raekke, som kilden ville levere den: samme navn, gade og punkt (og kW/stik/antal), og
    lastbil='ja' for en lastbilraekke i lade- eller tankfilen."""
    if len(r) == 11:
        d = post(r[0], r[1], r[2].split(', ')[0], r[3], r[4], (float(r[8]), float(r[9])),
                 kw=r[5], plug=r[6], count=r[7])
        lastbil = r[10]
    else:
        d = post(r[0], r[1], r[2].split(', ')[0], r[3], r[4], (float(r[5]), float(r[6])))
        lastbil = r[7] if len(r) == 8 else ''
    if lastbil == 'ja':
        d['lastbil'] = 'ja'
    d.update(ekstra)
    return d


def henter(*poster):
    """Stub for en henter: friske kopier ved hvert kald."""
    return lambda: [dict(p) for p in poster]


def tal(ud):
    """Slutlinjens fem tal."""
    m = re.search(r'(\d+) nye butikker\D+(\d+) mulige lukninger\D+(\d+) koordinat-afvigelser'
                  r'\D+(\d+) henter\(e\) fejlede\D+(\d+) fil\(er\) skrevet', ud)
    if not m:
        raise AssertionError('ingen slutlinje i:\n' + ud)
    return dict(zip(('nye', 'luk', 'afvig', 'fejl', 'skrevet'), map(int, m.groups())))


class TestRefreshRetailMain(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.mappe = tempfile.mkdtemp(prefix='test_refresh_retail_')
        self.addCleanup(shutil.rmtree, self.mappe, True)
        self.normaliseret = []     # [(raekkerne normalize_rows fik, kolonneindeksene)]
        self.status = {}           # Navn -> status fra normalize_rows (standard 'ok')
        self.rv_svar = {}          # (lat, lon) -> 6-tuple, None eller en undtagelse
        self.foer = {}
        st = contextlib.ExitStack()
        self.addCleanup(st.close)
        # Noeglen laeses aldrig: adresseopslaget er stubbet, og skulle et kald alligevel naa
        # dawa, faar det en dummy-noegle (og hjaelp.py spaerrer nettet).
        st.enter_context(mock.patch.object(dawa, '_noegle', return_value='TESTNOEGLE'))
        # Samme time-modul som retail_sources/dawa bruger: ingen genforsoeg maa sove.
        st.enter_context(mock.patch.object(time, 'sleep', lambda *a, **k: None))
        st.enter_context(mock.patch.object(R, 'OUT', self.mappe))
        st.enter_context(mock.patch.object(R, 'normalize_rows', self._normalize))
        st.enter_context(mock.patch.object(R, 'reverse_full', self._reverse))

    # ---- stubs for adresseopslaget
    def _normalize(self, rows, adr, postnr, by, lat, lon, workers=10, status_ud=None, bygning=None):
        self.normaliseret.append(([list(r) for r in rows],
                                  {'adr': adr, 'postnr': postnr, 'by': by, 'lat': lat, 'lon': lon}))
        for r in rows:
            status_ud.append(self.status.get(r[1], 'ok'))
        return 0, 0

    def _reverse(self, lat, lon):
        svar = self.rv_svar.get((round(lat, 6), round(lon, 6)), 'paa punktet')
        if isinstance(svar, Exception):
            raise svar
        if svar == 'paa punktet':
            return ('Testvej', '1', '9999', 'Testby', lat, lon)
        return svar

    # ---- koersel og aflaesning
    def koer(self, filer, kaeder, apply=True, ejer=None, lade=(), kun_rapport=(), en_halvdel=None,
             kendt=None, udeladt=None, lader_kendt=None, halvdel_ikke=None):
        """Skriv de seks CSV'er, koer main() med testens registre og fang udskriften."""
        for fn in R.FILER:
            with open(os.path.join(self.mappe, fn), 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(HOVED[fn])
                w.writerows(filer.get(fn, []))
            self.foer[fn] = self.raa(fn)
        ud = io.StringIO()
        with contextlib.ExitStack() as st:
            for navn, v in (('KAEDER', list(kaeder)), ('EJER', dict(ejer or {})),
                            ('LADE_KAEDER', set(lade)), ('KUN_RAPPORT', set(kun_rapport)),
                            ('EN_HALVDEL', dict(en_halvdel or {})),
                            ('HALVDEL_IKKE_I_KILDEN', dict(halvdel_ikke or {})),
                            ('KENDT_UDEN_KILDE', dict(kendt or {})),
                            ('UDELADT', dict(udeladt or {})), ('LADER_KENDT', dict(lader_kendt or {}))):
                st.enter_context(mock.patch.object(R, navn, v))
            st.enter_context(contextlib.redirect_stdout(ud))
            rc = R.main(apply=apply)
        return rc, ud.getvalue()

    def raa(self, fn):
        with open(os.path.join(self.mappe, fn), 'rb') as f:
            return f.read()

    def laes(self, fn):
        with open(os.path.join(self.mappe, fn), encoding='utf-8-sig', newline='') as f:
            r = list(csv.reader(f))
        return r[0], r[1:]

    def linjer(self, ud, status, *dele):
        """Rapportlinjerne med denne status (lige efter hentenavnet), som indeholder alle 'dele'."""
        m = re.compile(r'^  \S+\s+' + re.escape(status) + r'(?=\s|$)')
        return [l for l in ud.splitlines() if m.match(l) and all(d in l for d in dele)]

    def en_linje(self, ud, status, *dele):
        self.assertEqual(len(self.linjer(ud, status, *dele)), 1,
                         f'forventede een {status}-linje med {dele}:\n{ud}')

    def ingen_linje(self, ud, status, *dele):
        self.assertEqual(self.linjer(ud, status, *dele), [], f'uventet {status}-linje:\n{ud}')

    def uroert(self, *filer):
        for fn in filer or R.FILER:
            self.assertEqual(self.raa(fn), self.foer[fn], f'{fn} er aendret')

    def kun_tilfoejet(self, fn, n_nye):
        """Hver oprindelig linje staar BYTE-IDENTISK i den skrevne fil, og kun n_nye er kommet til;
        filen er UTF-8 med BOM og CRLF."""
        foer, efter = self.foer[fn], self.raa(fn)
        self.assertTrue(efter.startswith(BOM), f'{fn}: mangler BOM')
        self.assertTrue(efter.endswith(b'\r\n'), f'{fn}: sidste linje uden CRLF')
        self.assertEqual(efter.count(b'\n'), efter.count(b'\r\n'), f'{fn}: linjeskift skal vaere CRLF')
        fl, el = foer[3:].split(b'\r\n')[:-1], efter[3:].split(b'\r\n')[:-1]
        self.assertEqual(el[0], fl[0], f'{fn}: hovedet er aendret')
        self.assertEqual(collections.Counter(fl) - collections.Counter(el), collections.Counter(),
                         f'{fn}: eksisterende linjer er aendret eller slettet')
        self.assertEqual(len(el) - len(fl), n_nye)

    # ---- fixtur til tilfoej-kun og proevekoersel
    def _netto(self):
        svin = butik('Netto', 'Netto Svinninge', 'Hovedgaden 1', '4520', 'Svinninge', SVINNINGE)
        aarhus = butik('Netto', 'Netto Aarhus Nord', 'Randersvej 100', '8200', 'Aarhus N', AARHUS_N)
        lidl = butik('Lidl', 'Lidl Køge Ølsemagle', 'Ølsemaglevej 2', '4600', 'Køge', KOEGE)
        kilde = [post('Netto', 'Netto Svinninge', 'Hovedgaden 9', '4520', 'Svinninge', nord(SVINNINGE, 11)),
                 post('Netto', 'Netto Roskilde Ny', 'Nyvej 2', '4000', 'Roskilde', ROSKILDE)]
        ny = ['Netto', 'Netto Roskilde Ny', 'Nyvej 2, 4000 Roskilde', '4000', 'Roskilde'] + ll(ROSKILDE)
        return {DAG: [aarhus, svin, lidl]}, [('netto', henter(*kilde))], (svin, aarhus, lidl, ny)

    # =================================================================== tests
    def test_kun_tilfoejelse_eksisterende_raekker_roeres_ikke(self):
        """16-09-2026: foerste udgave ERSTATTEDE raekkerne og omskrev 1.248 adresser (Reberbanegade
        3 -> 9). Nu overtages kildens gade ikke, en raekke kilden mangler bliver staaende (MULIG
        LUKNING, exit 0), kun den nye butik kommer til, og kun DEN gaar gennem normalize_rows."""
        filer, kaeder, (svin, aarhus, lidl, ny) = self._netto()
        rc, ud = self.koer(filer, kaeder, ejer={'netto': ['Netto']})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'MULIG LUKNING', 'Netto Aarhus Nord', 'Randersvej 100')
        self.en_linje(ud, 'NY BUTIK', 'Netto Roskilde Ny')
        self.assertEqual(tal(ud), {'nye': 1, 'luk': 1, 'afvig': 0, 'fejl': 0, 'skrevet': 1})
        head, body = self.laes(DAG)
        self.assertEqual(head, HOVED[DAG])
        self.assertEqual(body, [lidl, ny, svin, aarhus])     # sorteret paa (Maerke, Postnr)
        self.kun_tilfoejet(DAG, 1)
        self.uroert(UDV, PLADS, TANK, FAST, LADE)
        self.assertEqual([rows for rows, _ in self.normaliseret], [[ny]])
        self.assertEqual(self.normaliseret[0][1], {'adr': 2, 'postnr': 3, 'by': 4, 'lat': 5, 'lon': 6})

    def test_uden_apply_skrives_intet(self):
        """'Uden --apply skrives intet' (modulets docstring): en proevekoersel maa ikke roere en
        eneste fil, men skal stadig vise, hvad den ville tilfoeje."""
        filer, kaeder, _ = self._netto()
        rc, ud = self.koer(filer, kaeder, ejer={'netto': ['Netto']}, apply=False)
        self.assertEqual(rc, 0, ud)
        self.uroert()
        self.assertEqual(tal(ud), {'nye': 1, 'luk': 1, 'afvig': 0, 'fejl': 0, 'skrevet': 0})
        self.assertIn('[ingen --apply: intet skrevet]', ud)
        self.assertIn(f'{DAG}: 3 -> 4 (+1 nye)', ud)

    def test_kun_rapport_meldes_men_skrives_aldrig(self):
        """01-10-2026: Shells egne pins var forkerte for 6 af de 24 anlaeg, Shell tilfoejede i
        2025-26 (Starbucks 3 af 17). En KUN_RAPPORT-henters nye post er 'NY (RAPPORT)', aldrig skrevet."""
        vejle = tank('Shell', 'SHELL VEJLE', 'Vejlevej 1', '7100', 'Vejle', VEJLE)
        kilde = [som_kilde(vejle), post('Shell', 'SHELL HERNING', 'Herningvej 5', '7400', 'Herning', HERNING)]
        rc, ud = self.koer({TANK: [vejle]}, [('shell_tank', henter(*kilde))],
                           ejer={'shell_tank': ['Shell']}, kun_rapport={'shell_tank'})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'NY (RAPPORT)', 'SHELL HERNING')
        self.ingen_linje(ud, 'NY BUTIK')
        self.assertEqual(tal(ud), {'nye': 0, 'luk': 0, 'afvig': 0, 'fejl': 0, 'skrevet': 0})
        self.uroert()

    def test_vaekstspaerre_begge_graenser(self):
        """17-09-2026 (ced2af0) skulle vaekstspaerren stoppe IKEA 6 -> 8 (33 %), men 'flere end 2 OG flere
        end 10 %' var det samme som det gamle max(2, 10 %): 2 nye slap igennem for ethvert maerke under 20
        raekker (fundet af testene 14-10-2026; nu MIN_NYE_FRIT = 1). 2 nye mod 6 AFVISES - og lukningen i
        samme maerke meldes alligevel (17-09-2026 slugte AFVIST de aegte lukninger). 1 ny mod 6 tilfoejes
        (ét ad gangen er altid tilladt), 4 mod 40 (praecis 10 %) ogsaa, men 5 mod 40 AFVISES."""
        ikea = [butik('IKEA', f'IKEA Butik {i}', f'Ikeavej {i}', '6000', 'Kolding', p)
                for i, p in enumerate(gitter(6, (55.0, 9.0)), 1)]
        jysk = [butik('JYSK', f'JYSK Butik {i}', f'Jyskvej {i}', '5000', 'Odense C', p)
                for i, p in enumerate(gitter(6, (55.5, 10.0)), 1)]
        bygma = [butik('Bygma', f'Bygma Butik {i}', f'Bygmavej {i}', '7400', 'Herning', p)
                 for i, p in enumerate(gitter(40, (56.0, 9.0)), 1)]
        stark = [butik('STARK', f'STARK Butik {i}', f'Starkvej {i}', '4700', 'Næstved', p)
                 for i, p in enumerate(gitter(40, (55.0, 11.5)), 1)]
        ny_ikea = [post('IKEA', f'IKEA Ny {k}', f'Nyvej {k}', '9000', 'Aalborg', (57.0 + k * 0.05, 10.0))
                   for k in range(2)]
        ny_jysk = [post('JYSK', 'JYSK Ny 0', 'Nyvej 0', '9000', 'Aalborg', (57.2, 10.3))]
        ny_bygma = [post('Bygma', f'Bygma Ny {k}', f'Nyvej {k}', '9900', 'Frederikshavn',
                         (57.4 + k * 0.05, 10.0)) for k in range(4)]
        ny_stark = [post('STARK', f'STARK Ny {k}', f'Nyvej {k}', '8500', 'Grenaa', (56.4 + k * 0.05, 10.9))
                    for k in range(5)]
        kaeder = [('ikea', henter(*[som_kilde(r) for r in ikea[:5]], *ny_ikea)),
                  ('jysk', henter(*[som_kilde(r) for r in jysk], *ny_jysk)),
                  ('bygma', henter(*[som_kilde(r) for r in bygma], *ny_bygma)),
                  ('stark', henter(*[som_kilde(r) for r in stark], *ny_stark))]
        rc, ud = self.koer({PLADS: ikea + jysk + bygma + stark}, kaeder,
                           ejer={'ikea': ['IKEA'], 'jysk': ['JYSK'], 'bygma': ['Bygma'], 'stark': ['STARK']})
        self.assertEqual(rc, 0, ud)          # AFVIST er et fund til gennemsyn, ikke en henterfejl
        self.en_linje(ud, 'AFVIST', 'IKEA: 2 nye mod 6 eksisterende')
        self.en_linje(ud, 'MULIG LUKNING', 'IKEA Butik 6')
        self.ingen_linje(ud, 'NY BUTIK', 'IKEA')
        self.en_linje(ud, 'AFVIST', 'STARK: 5 nye mod 40 eksisterende')
        self.ingen_linje(ud, 'NY BUTIK', 'STARK')
        self.ingen_linje(ud, 'AFVIST', 'JYSK')
        self.ingen_linje(ud, 'AFVIST', 'Bygma')
        self.en_linje(ud, 'NY BUTIK', 'JYSK Ny 0')
        self.assertEqual(len(self.linjer(ud, 'NY BUTIK', 'Bygma Ny')), 4, ud)
        _, body = self.laes(PLADS)
        self.assertEqual(collections.Counter(r[0] for r in body), {'IKEA': 6, 'JYSK': 7, 'Bygma': 44, 'STARK': 40})
        self.assertEqual(sorted(r[1] for r in body if r[0] == 'IKEA'), sorted(r[1] for r in ikea))
        self.kun_tilfoejet(PLADS, 5)
        self.assertEqual(tal(ud)['luk'], 1)

    def test_vaekstspaerre_noegle_uden_raekker(self):
        """Fundet af testene 14-10-2026: en kaedes FOERSTE lastbilanlaeg har 0 raekker i sin noegle
        ('maerke|lade|lastbil'), saa 10 %-graensen er 0, og kun MIN_NYE_FRIT afgoer sagen. Med 2 slap to
        nye lastbilanlaeg ind paa én koersel; nu tilfoejes ét (Ionity), og to AFVISES (Fastned)."""
        ionity = [lader('Ionity', f'Ionity Bil {i}', f'Ionityvej {i}', '6000', 'Kolding', 350, 'CCS', 4, p)
                  for i, p in enumerate(gitter(3, (55.5, 9.4)), 1)]
        fastned = [lader('Fastned', f'Fastned Bil {i}', f'Fastnedvej {i}', '4100', 'Ringsted', 300, 'CCS', 4, p)
                   for i, p in enumerate(gitter(3, (55.4, 11.7)), 1)]

        def truck(brand, navn, p):         # fuldstaendig lastbilpost, langt fra maerkets bilraekker
            return post(brand, navn, 'Transportvej 1', '8700', 'Horsens', p,
                        kw=720, plug='MCS', count=2, lastbil='ja')
        kaeder = [('ionity', henter(*[som_kilde(r) for r in ionity],
                                    truck('Ionity', 'Ionity Truck Horsens', HORSENS))),
                  ('fastned', henter(*[som_kilde(r) for r in fastned],
                                     truck('Fastned', 'Fastned Truck Køge', KOEGE),
                                     truck('Fastned', 'Fastned Truck Roskilde', ROSKILDE)))]
        rc, ud = self.koer({LADE: ionity + fastned}, kaeder,
                           ejer={'ionity': ['Ionity'], 'fastned': ['Fastned']}, lade={'ionity', 'fastned'})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'NY BUTIK', 'Ionity (lader) (lastbil): Ionity Truck Horsens')
        self.en_linje(ud, 'AFVIST', 'Fastned (lader) (lastbil): 2 nye mod 0 eksisterende')
        self.ingen_linje(ud, 'NY BUTIK', 'Fastned')
        ny = ['Ionity', 'Ionity Truck Horsens', 'Transportvej 1, 8700 Horsens', '8700', 'Horsens', '720', 'MCS', '2'] \
            + ll(HORSENS) + ['ja']
        self.assertIn(ny, self.laes(LADE)[1])
        self.kun_tilfoejet(LADE, 1)
        self.assertEqual(tal(ud), {'nye': 1, 'luk': 0, 'afvig': 0, 'fejl': 0, 'skrevet': 1})

    def test_tomt_svar_er_en_fejl_ikke_nul_butikker(self):
        """17-09-2026: et tomt svar gav '(ingen aendringer)' og exit 0, mens hele maerket stod uden
        for overvaagning. [] og None er begge TOMT SVAR og exit 2 - og ingen lukninger."""
        rows = [butik('Netto', 'Netto Odense', 'Vestergade 1', '5000', 'Odense C', ODENSE),
                butik('Lidl', 'Lidl Aalborg', 'Hobrovej 1', '9000', 'Aalborg', AALBORG)]
        rc, ud = self.koer({DAG: rows}, [('netto', lambda: []), ('lidl', lambda: None)],
                           ejer={'netto': ['Netto'], 'lidl': ['Lidl']})
        self.assertEqual(rc, 2, ud)
        self.assertEqual(len(self.linjer(ud, 'TOMT SVAR')), 2, ud)
        self.ingen_linje(ud, 'MULIG LUKNING')
        self.assertEqual(tal(ud), {'nye': 0, 'luk': 0, 'afvig': 0, 'fejl': 2, 'skrevet': 0})
        self.uroert()

    def test_henter_der_fejler_stopper_ikke_de_andre(self):
        """Foerste udgave gav exit 0 for alt undtagen en exception, saa fejl var usynlige i Actions.
        En henter der rejser, er HENTER FEJLEDE og exit 2 - og de oevrige hentere koeres og skriver."""
        def boom():
            raise RuntimeError('HTTP 503 fra kilden')
        netto = butik('Netto', 'Netto Odense', 'Vestergade 1', '5000', 'Odense C', ODENSE)
        kilde = [som_kilde(netto), post('Netto', 'Netto Ny Vejle', 'Vejlevej 9', '7100', 'Vejle', VEJLE)]
        rc, ud = self.koer({DAG: [netto]}, [('boom', boom), ('netto', henter(*kilde))],
                           ejer={'netto': ['Netto']})
        self.assertEqual(rc, 2, ud)
        self.en_linje(ud, 'HENTER FEJLEDE', 'RuntimeError: HTTP 503 fra kilden')
        self.en_linje(ud, 'NY BUTIK', 'Netto Ny Vejle')
        self.assertIn('Netto Ny Vejle', [r[1] for r in self.laes(DAG)[1]])
        self.kun_tilfoejet(DAG, 1)
        self.assertEqual(tal(ud), {'nye': 1, 'luk': 0, 'afvig': 0, 'fejl': 1, 'skrevet': 1})

    def test_maerke_mangler_i_svaret_er_en_fejl(self):
        """17-09-2026: Brugsen fjernet fra coop-svaret gav '0 mulige lukninger', exit 0 - 265 butikker
        usynligt uden for overvaagning. EJER-maerke uden for svaret + vores raekker = MÆRKE MANGLER,
        exit 2; ogsaa for ladere (bil + lastbil taelles) og ved omdoebt maerke. Ingen raekker: ingen fejl."""
        dag = [butik('Brugsen', 'Brugsen Aarup', 'Algade 1', '5560', 'Aarup', AARUP),
               butik('Brugsen', 'Brugsen Haarby', 'Assensvej 2', '5683', 'Haarby', HAARBY),
               butik('SuperBrugsen', 'SuperBrugsen Odense', 'Vestergade 3', '5000', 'Odense C', ODENSE)]
        lade = [lader('Clever', 'Clever Vejle', 'Vejlevej 1', '7100', 'Vejle', 300, 'CCS', 4, VEJLE),
                lader('Clever', 'Clever Truck Kolding', 'Truckvej 1', '6000', 'Kolding', 400, 'CCS', 2,
                      KOLDING, 'ja')]
        omdoebt = som_kilde(lade[0], brand='Clever A/S')
        rc, ud = self.koer({DAG: dag, LADE: lade},
                           [('coop', henter(som_kilde(dag[2]))), ('clever', henter(omdoebt))],
                           ejer={'coop': ['Brugsen', 'Kvickly', 'SuperBrugsen'], 'clever': ['Clever']},
                           lade={'clever'})
        self.assertEqual(rc, 2, ud)
        self.en_linje(ud, 'MÆRKE MANGLER', ' Brugsen:', 'vi har 2 rækker')
        self.en_linje(ud, 'MÆRKE MANGLER', ' Clever:', 'vi har 2 rækker')
        self.ingen_linje(ud, 'MÆRKE MANGLER', 'Kvickly')
        self.ingen_linje(ud, 'MÆRKE MANGLER', 'SuperBrugsen')
        self.en_linje(ud, 'UKENDT MÆRKE', 'Clever A/S')
        self.assertEqual(tal(ud)['fejl'], 2)
        self.uroert()

    def _uno_x_og_eon(self):
        """Uno-X i tankfilen og E.ON i ladefilen, begge med to bilraekker og lastbilraekker."""
        tankr = [tank('Uno-X', 'Uno-X Herning', 'Herningvej 1', '7400', 'Herning', HERNING),
                 tank('Uno-X', 'Uno-X Vejle', 'Vejlevej 1', '7100', 'Vejle', VEJLE),
                 tank('Uno-X', 'Uno-X Truck Kolding', 'Truckvej 1', '6000', 'Kolding', KOLDING, 'ja'),
                 tank('Uno-X', 'Uno-X Truck Korsør', 'Truckvej 2', '4220', 'Korsør', KORSOER, 'ja')]
        lade_r = [lader('E.ON', 'E.ON Odense', 'Odensevej 1', '5000', 'Odense C', 300, 'CCS', 4, ODENSE),
                  lader('E.ON', 'E.ON Aarhus', 'Aarhusvej 1', '8000', 'Aarhus C', 300, 'CCS', 4, AARHUS),
                  lader('E.ON', 'E.ON MAN Tilst', 'Industrivej 1', '8381', 'Tilst', 400, 'CCS', 2, TILST, 'ja')]
        return tankr, lade_r

    def test_halvdel_mangler_er_en_fejl(self):
        """Fundet af testene 14-10-2026: holdt en henter, der leverer baade bil- og lastbilanlaeg, op med
        at levere den ene halvdel, blev den halvdels raekker aldrig sammenlignet - og rapporten sagde intet,
        ikke engang mulige lukninger (Uno-X har 81 lastbilanlaeg i tankfilen). Naevner kilden maerket, men
        har 0 poster i en halvdel, hvor vi har raekker: HALVDEL MANGLER og exit 2 - i tank- og i ladefilen."""
        tankr, lade_r = self._uno_x_og_eon()
        rc, ud = self.koer({TANK: tankr, LADE: lade_r},
                           [('unox', henter(som_kilde(tankr[0]), som_kilde(tankr[1]))),    # kun bilposter
                            ('eon', henter(som_kilde(lade_r[2])))],                         # kun lastbilposten
                           ejer={'unox': ['Uno-X'], 'eon': ['E.ON']}, lade={'eon'})
        self.assertEqual(rc, 2, ud)
        self.en_linje(ud, 'HALVDEL MANGLER', 'Uno-X (lastbil):', 'ingen lastbil-poster', 'vi har 2 rækker')
        self.en_linje(ud, 'HALVDEL MANGLER', 'E.ON (bil):', 'ingen bil-poster', 'vi har 2 rækker')
        self.assertEqual(len(self.linjer(ud, 'HALVDEL MANGLER')), 2, ud)
        self.ingen_linje(ud, 'MÆRKE MANGLER')
        self.ingen_linje(ud, 'MULIG LUKNING')     # halvdelen sammenlignes slet ikke; kun linjen ovenfor siger det
        self.assertEqual(tal(ud), {'nye': 0, 'luk': 0, 'afvig': 0, 'fejl': 2, 'skrevet': 0})
        self.uroert()

    def test_maerke_mangler_giver_ikke_ogsaa_halvdel_mangler(self):
        """14-10-2026: HALVDEL MANGLER er MÆRKE MANGLER paa halvdel-niveau. Mangler hele maerket i svaret
        (Circle K fra circlek_ingo, med bil- og lastbilraekker), er det én fejl og én linje - ikke ogsaa
        en HALVDEL-linje pr. halvdel. Soestermaerket (Ingo) i samme svar vurderes som foer."""
        ck = [tank('Circle K', 'Circle K Ribe', 'Ribevej 1', '6760', 'Ribe', RIBE),
              tank('Circle K', 'Circle K Vejen', 'Vejenvej 1', '6600', 'Vejen', VEJEN),
              tank('Circle K', 'Circle K Truck Kolding', 'Truckvej 1', '6000', 'Kolding', KOLDING, 'ja')]
        ingo = tank('Ingo', 'Ingo Brørup', 'Brørupvej 1', '6650', 'Brørup', BROERUP)
        rc, ud = self.koer({TANK: ck + [ingo]}, [('circlek_ingo', henter(som_kilde(ingo)))],
                           ejer={'circlek_ingo': ['Circle K', 'Ingo']})
        self.assertEqual(rc, 2, ud)
        self.en_linje(ud, 'MÆRKE MANGLER', 'Circle K:', 'vi har 3 rækker')
        self.ingen_linje(ud, 'HALVDEL MANGLER')
        self.ingen_linje(ud, 'MULIG LUKNING')
        self.assertEqual(tal(ud)['fejl'], 1)
        self.uroert()

    def test_en_halvdel_henter_melder_ikke_den_anden_halvdel(self):
        """14-10-2026: norlys_lastbil leverer med vilje kun lastbilanlaeg og q8_ladere kun bilanlaeg
        (EN_HALVDEL); den halvdel, de ikke leverer, giver ingen HALVDEL MANGLER, selv om vi har raekker i
        den. En almindelig henter med samme hul (unox_lader uden lastbilposter) melder det stadig."""
        norlys = [lader('Norlys', 'Norlys Korsør', 'Korsørvej 1', '4220', 'Korsør', 300, 'CCS', 6, KORSOER),
                  lader('Norlys', 'Norlys Køge', 'Køgevej 1', '4600', 'Køge', 300, 'CCS', 6, KOEGE),
                  lader('Norlys', 'Norlys Aarup Truck', 'Aarupvej 1', '5560', 'Aarup', 400, 'CCS', 2, AARUP, 'ja')]
        q8 = [lader('Q8', 'Q8 Ribe', 'Ribevej 1', '6760', 'Ribe', 300, 'CCS', 4, RIBE),
              lader('Q8', 'Q8 Truck Vejen', 'Vejenvej 1', '6600', 'Vejen', 400, 'CCS', 2, VEJEN, 'ja')]
        unox = [lader('Uno-X', 'Uno-X Herning', 'Herningvej 1', '7400', 'Herning', 300, 'CCS', 4, HERNING),
                lader('Uno-X', 'Uno-X Truck Kolding', 'Truckvej 1', '6000', 'Kolding', 400, 'CCS', 2, KOLDING, 'ja')]
        rc, ud = self.koer({LADE: norlys + q8 + unox},
                           [('norlys_lastbil', henter(som_kilde(norlys[2]))),
                            ('q8_ladere', henter(som_kilde(q8[0]))),
                            ('unox_lader', henter(som_kilde(unox[0])))],
                           ejer={'norlys_lastbil': ['Norlys'], 'q8_ladere': ['Q8'], 'unox_lader': ['Uno-X']},
                           lade={'norlys_lastbil', 'q8_ladere', 'unox_lader'},
                           en_halvdel={'norlys_lastbil': 'lastbil', 'q8_ladere': 'bil'})
        self.ingen_linje(ud, 'HALVDEL MANGLER', 'Norlys')
        self.ingen_linje(ud, 'HALVDEL MANGLER', 'Q8')
        self.en_linje(ud, 'HALVDEL MANGLER', 'Uno-X (lastbil):', 'vi har 1 rækker')
        self.assertEqual(len(self.linjer(ud, 'HALVDEL MANGLER')), 1, ud)
        self.ingen_linje(ud, 'MULIG LUKNING')
        self.assertEqual((rc, tal(ud)['fejl']), (2, 1), ud)
        self.uroert()

    def test_halvdel_ikke_i_kilden_slukker_kun_sin_egen_noegle(self):
        """14-10-2026: leverer en henter med vilje ikke den ene halvdel, staar (henter, maerke, halvdel) i
        HALVDEL_IKKE_I_KILDEN med grunden, og HALVDEL MANGLER tier for netop den noegle. Samme maerke fra en
        anden henter (unox_lader) og den anden halvdel (E.ON's bilhalvdel) melder stadig."""
        tankr, lade_r = self._uno_x_og_eon()
        unox_lade = [lader('Uno-X', 'Uno-X Herning', 'Herningvej 1', '7400', 'Herning', 300, 'CCS', 4, HERNING),
                     lader('Uno-X', 'Uno-X Truck Kolding', 'Truckvej 1', '6000', 'Kolding', 400, 'CCS', 2,
                           KOLDING, 'ja')]
        rc, ud = self.koer({TANK: tankr, LADE: lade_r + unox_lade},
                           [('unox', henter(som_kilde(tankr[0]), som_kilde(tankr[1]))),       # ingen lastbil
                            ('unox_lader', henter(som_kilde(unox_lade[0]))),                  # ingen lastbil
                            ('eon', henter(som_kilde(lade_r[2])))],                            # ingen bil
                           ejer={'unox': ['Uno-X'], 'unox_lader': ['Uno-X'], 'eon': ['E.ON']},
                           lade={'unox_lader', 'eon'},
                           halvdel_ikke={('unox', 'Uno-X', 'lastbil'): 'testgrund (14-10-2026)',
                                         ('eon', 'E.ON', 'lastbil'): 'testgrund, den anden halvdel (14-10-2026)'})
        self.assertEqual(sorted(l.split()[0] for l in self.linjer(ud, 'HALVDEL MANGLER')), ['eon', 'unox_lader'], ud)
        self.en_linje(ud, 'HALVDEL MANGLER', 'Uno-X (lastbil):', 'vi har 1 rækker')
        self.en_linje(ud, 'HALVDEL MANGLER', 'E.ON (bil):', 'vi har 2 rækker')
        self.assertEqual((rc, tal(ud)['fejl']), (2, 2), ud)
        self.uroert()

    def _eon(self):
        tilst = lader('E.ON', 'E.ON MAN Tilst', 'Industrivej 1', '8381', 'Tilst', 300, 'CCS', 4, TILST)
        odense = lader('E.ON', 'E.ON Odense', 'Odensevej 1', '5000', 'Odense C', 300, 'CCS', 4, ODENSE)
        truck = post('E.ON', 'E.ON MAN Tilst', 'Industrivej 3', '8381', 'Tilst', nord(TILST, 20),
                     kw=400, plug='CCS', count=2, lastbil='ja')
        self.assertLess(R.hav(*TILST, *nord(TILST, 20)), R.NAER_M)
        return tilst, odense, truck

    def test_bil_lastbil_skift_tilfoejes_ikke(self):
        """Review 13-10-2026: flyttede kilden et anlaeg til den anden halvdel (E.ON's chargingUseCase,
        Uno-X' truck-flag), blev MAN Tilst og Cafeteria Storebaelt dubletter 0 m fra den gamle raekke.
        Vores raekke fra den anden halvdel inden for NAER_M, og kilden har den ikke dér: BIL/LASTBIL."""
        tilst, odense, truck = self._eon()
        fvaerk = tank('Uno-X', 'Uno-X Truck Frederiksværk', 'Havnevej 1', '3300', 'Frederiksværk',
                      FREDERIKSVAERK, 'ja')
        kolding = tank('Uno-X', 'Uno-X Truck Kolding', 'Truckvej 1', '6000', 'Kolding', KOLDING, 'ja')
        herning = tank('Uno-X', 'Uno-X Herning', 'Herningvej 1', '7400', 'Herning', HERNING)
        bil = post('Uno-X', 'Uno-X Frederiksværk', 'Havnevej 1', '3300', 'Frederiksværk',
                   nord(FREDERIKSVAERK, 4))
        # Kilden leverer stadig sine oevrige lastbilanlaeg (Kolding) og E.ON sine bilanlaeg (Odense): er
        # hele halvdelen vaek, er det HALVDEL MANGLER (14-10-2026), ikke et skifte.
        rc, ud = self.koer({LADE: [tilst, odense], TANK: [fvaerk, kolding, herning]},
                           [('eon', henter(som_kilde(odense), truck)),
                            ('unox', henter(som_kilde(herning), som_kilde(kolding), bil))],
                           ejer={'eon': ['E.ON'], 'unox': ['Uno-X']}, lade={'eon'})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'BIL/LASTBIL', 'E.ON MAN Tilst', 'vores bilrække', 'står 20 m')   # bil -> lastbil
        self.en_linje(ud, 'BIL/LASTBIL', 'Uno-X Frederiksværk', 'vores lastbilrække')       # lastbil -> bil
        self.ingen_linje(ud, 'NY BUTIK')
        self.ingen_linje(ud, 'HALVDEL MANGLER')
        self.ingen_linje(ud, 'AFVIST')
        self.assertEqual(tal(ud)['nye'], 0)
        self.uroert()

    def test_bil_og_lastbil_samme_sted_er_to_anlaeg(self):
        """Modstykket til BIL/LASTBIL-vagten (review 13-10-2026): har kilden STADIG bilposten ved vores
        bilraekke, er lastbilposten et andet anlaeg og tilfoejes som lastbilraekke (Lastbil 'ja')."""
        tilst, odense, truck = self._eon()
        rc, ud = self.koer({LADE: [tilst, odense]},
                           [('eon', henter(som_kilde(odense), som_kilde(tilst), truck))],
                           ejer={'eon': ['E.ON']}, lade={'eon'})
        self.assertEqual(rc, 0, ud)
        self.ingen_linje(ud, 'BIL/LASTBIL')
        self.ingen_linje(ud, 'MULIG LUKNING')
        ny = ['E.ON', 'E.ON MAN Tilst', 'Industrivej 3, 8381 Tilst', '8381', 'Tilst', '400', 'CCS', '2'] \
            + ll(nord(TILST, 20)) + ['ja']
        self.assertIn(ny, self.laes(LADE)[1])
        self.kun_tilfoejet(LADE, 1)
        self.assertEqual(self.normaliseret[0][1], {'adr': 2, 'postnr': 3, 'by': 4, 'lat': 8, 'lon': 9})

    def test_en_halvdel_henter_springer_bil_lastbil_vagten_over(self):
        """Review 14-10-2026: Norlys' lastbilstationer ligger 74-106 m fra en Norlys-bilpark (Korsør,
        Aarup, Køge) og blev meldt som skifte. En EN_HALVDEL-henters nye lastbilpost 90 m fra vores
        bilraekke TILFOEJES, og dens manglende bilposter giver ingen bil-lukninger."""
        korsoer = lader('Norlys', 'Norlys Korsør', 'Korsørvej 1', '4220', 'Korsør', 300, 'CCS', 6, KORSOER)
        koege = lader('Norlys', 'Norlys Køge', 'Køgevej 1', '4600', 'Køge', 300, 'CCS', 6, KOEGE)
        aarup = lader('Norlys', 'Norlys Aarup Truck', 'Aarupvej 1', '5560', 'Aarup', 400, 'CCS', 2, AARUP, 'ja')
        p = nord(KORSOER, 90)
        self.assertLess(R.hav(*KORSOER, *p), R.NAER_M)
        ny_post = post('Norlys', 'Norlys Korsør Truck', 'Truckvej 2', '4220', 'Korsør', p,
                       kw=400, plug='CCS', count=4, lastbil='ja')
        rc, ud = self.koer({LADE: [korsoer, koege, aarup]},
                           [('norlys_lastbil', henter(som_kilde(aarup), ny_post))],
                           ejer={'norlys_lastbil': ['Norlys']}, lade={'norlys_lastbil'},
                           en_halvdel={'norlys_lastbil': 'lastbil'})
        self.assertEqual(rc, 0, ud)
        self.ingen_linje(ud, 'BIL/LASTBIL')
        self.ingen_linje(ud, 'MULIG LUKNING')
        self.en_linje(ud, 'NY BUTIK', 'Norlys Korsør Truck')
        ny = ['Norlys', 'Norlys Korsør Truck', 'Truckvej 2, 4220 Korsør', '4220', 'Korsør', '400', 'CCS', '4'] \
            + ll(p) + ['ja']
        self.assertIn(ny, self.laes(LADE)[1])
        self.kun_tilfoejet(LADE, 1)
        self.assertEqual(tal(ud), {'nye': 1, 'luk': 0, 'afvig': 0, 'fejl': 0, 'skrevet': 1})

    def test_forkert_halvdel_udelades_og_er_en_fejl(self):
        """Testene 14-10-2026: en EN_HALVDEL-henter springer BIL/LASTBIL-vagten over, saa en post fra den
        halvdel, den ikke leverer, er en fejl i henteren - ikke et anlaeg. 'FORKERT HALVDEL' og exit 2;
        posten udelades (skrives aldrig og aabner ikke den anden halvdel for lukninger), og henterens
        oevrige poster vurderes som normalt (den nye lastbilpost tilfoejes)."""
        korsoer = lader('Norlys', 'Norlys Korsør', 'Korsørvej 1', '4220', 'Korsør', 300, 'CCS', 6, KORSOER)
        koege = lader('Norlys', 'Norlys Køge', 'Køgevej 1', '4600', 'Køge', 300, 'CCS', 6, KOEGE)
        aarup = lader('Norlys', 'Norlys Aarup Truck', 'Aarupvej 1', '5560', 'Aarup', 400, 'CCS', 2, AARUP, 'ja')
        ribe = lader('Q8', 'Q8 Ribe', 'Ribevej 1', '6760', 'Ribe', 300, 'CCS', 4, RIBE)
        ny_truck = post('Norlys', 'Norlys Roskilde Truck', 'Truckvej 9', '4000', 'Roskilde', ROSKILDE,
                        kw=400, plug='CCS', count=4, lastbil='ja')
        bil_fejl = post('Norlys', 'Norlys Horsens', 'Horsensvej 1', '8700', 'Horsens', HORSENS,
                        kw=300, plug='CCS', count=6)                         # bilpost fra lastbilhenteren
        truck_fejl = post('Q8', 'Q8 Truck Vejen', 'Vejenvej 1', '6600', 'Vejen', VEJEN,
                          kw=400, plug='CCS', count=2, lastbil='ja')         # lastbilpost fra bilhenteren
        rc, ud = self.koer({LADE: [korsoer, koege, aarup, ribe]},
                           [('norlys_lastbil', henter(som_kilde(aarup), bil_fejl, ny_truck)),
                            ('q8_ladere', henter(som_kilde(ribe), truck_fejl))],
                           ejer={'norlys_lastbil': ['Norlys'], 'q8_ladere': ['Q8']},
                           lade={'norlys_lastbil', 'q8_ladere'},
                           en_halvdel={'norlys_lastbil': 'lastbil', 'q8_ladere': 'bil'})
        self.assertEqual(rc, 2, ud)
        self.en_linje(ud, 'FORKERT HALVDEL', '1 post(er) er ikke lastbil', 'Norlys Horsens')
        self.en_linje(ud, 'FORKERT HALVDEL', '1 post(er) er ikke bil', 'Q8 Truck Vejen')
        self.ingen_linje(ud, 'MULIG LUKNING')     # bilposten aabnede ikke Norlys' bilhalvdel for sammenligning
        self.ingen_linje(ud, 'BIL/LASTBIL')
        self.ingen_linje(ud, 'HALVDEL MANGLER')
        self.en_linje(ud, 'NY BUTIK', 'Norlys Roskilde Truck')
        self.assertEqual(len(self.linjer(ud, 'NY BUTIK')), 1, ud)
        body = self.laes(LADE)[1]
        ny = ['Norlys', 'Norlys Roskilde Truck', 'Truckvej 9, 4000 Roskilde', '4000', 'Roskilde', '400', 'CCS', '4'] \
            + ll(ROSKILDE) + ['ja']
        self.assertIn(ny, body)
        self.assertEqual([r for r in body if r[1] in ('Norlys Horsens', 'Q8 Truck Vejen')], [])
        self.kun_tilfoejet(LADE, 1)
        self.assertEqual(tal(ud), {'nye': 1, 'luk': 0, 'afvig': 0, 'fejl': 2, 'skrevet': 1})

    def test_kw_loft_og_ufuldstaendige_ladere(self):
        """Review 13-10-2026: en henter uden eget loft (clever) eller med 1.200 for alle (ok_chargers)
        kunne tilfoeje en BILraekke paa 1.000 kW. Bil 250-600 kW, lastbil 250-1.200; uden antal eller
        stik tilfoejes intet - 'NY (UFULDSTÆNDIG)'. Siden 14-10-2026 meldes de FOER vaekstspaerren."""
        # 80 raekker, saa vaekstspaerren aldrig er det, der stopper en post her. Foer 14-10-2026 talte den
        # alle 7 nye bilposter; nu kun de 2 fuldstaendige (test_ufuldstaendige_ladere_taeller_ikke_i_vaekstspaerren).
        # Lastbilhalvdelen har 0 raekker: Kw1201 meldes, og Kw1000 er da kun 1 ny og slipper igennem.
        clever = [lader('Clever', f'Clever Gitter {i}', f'Gittervej {i}', '7500', 'Holstebro', 300, 'CCS', 4, p)
                  for i, p in enumerate(gitter(80, (56.5, 8.5)), 1)]
        galten = lader('OK', 'OK Galten', 'Galtenvej 1', '8464', 'Galten', 300, 'CCS', 4, GALTEN)

        def ny(brand, navn, k, **e):      # paa Sjaelland, langt fra alle vores raekker
            return post(brand, navn, f'Ladevej {k}', '4100', 'Ringsted', (55.4 + k * 0.02, 11.8), **e)
        clever_nye = [ny('Clever', 'Clever Kw1000', 1, kw=1000, plug='CCS', count=4),
                      ny('Clever', 'Clever Kw200', 2, kw=200, plug='CCS', count=4),
                      ny('Clever', 'Clever Kw601', 3, kw=601, plug='CCS', count=4),
                      ny('Clever', 'Clever Uden Antal', 4, kw=300, plug='CCS', count=None),
                      ny('Clever', 'Clever Uden Stik', 5, kw=300, plug='', count=4),
                      ny('Clever', 'Clever Kw600', 6, kw=600, plug='CCS', count=4),
                      ny('Clever', 'Clever Kw250', 7, kw='250', plug='CCS', count='2'),
                      ny('Clever', 'Clever Truck Kw1201', 8, kw=1201, plug='MCS', count=1, lastbil='ja'),
                      ny('Clever', 'Clever Truck Kw1000', 9, kw=1000, plug='CCS', count=2, lastbil='ja')]
        ok_nye = [ny('OK', 'OK Bil 1200', 10, kw=1200, plug='CCS', count=4),
                  ny('OK', 'OK Truck 1200', 11, kw=1200, plug='MCS', count=1, lastbil='ja')]
        rc, ud = self.koer({LADE: clever + [galten]},
                           [('clever', henter(*[som_kilde(r) for r in clever], *clever_nye)),
                            ('ok_chargers', henter(som_kilde(galten), *ok_nye))],
                           ejer={'clever': ['Clever'], 'ok_chargers': ['OK']}, lade={'clever', 'ok_chargers'})
        self.assertEqual(rc, 0, ud)
        afvist = {'Clever Kw1000', 'Clever Kw200', 'Clever Kw601', 'Clever Uden Antal', 'Clever Uden Stik',
                  'Clever Truck Kw1201', 'OK Bil 1200'}
        alle = {p['name'] for p in clever_nye + ok_nye}
        self.assertEqual({n for n in alle if self.linjer(ud, 'NY (UFULDSTÆNDIG)', f': {n} \u2014')}, afvist, ud)
        _, body = self.laes(LADE)
        self.assertEqual({r[1] for r in body} - {r[1] for r in clever + [galten]},
                         alle - afvist, ud)          # Kw600, Kw250, Truck Kw1000, OK Truck 1200
        nye = {r[1]: r for r in body}
        self.assertEqual(nye['Clever Truck Kw1000'][5:8] + nye['Clever Truck Kw1000'][10:], ['1000', 'CCS', '2', 'ja'])
        self.assertEqual(nye['OK Truck 1200'][5:8] + nye['OK Truck 1200'][10:], ['1200', 'MCS', '1', 'ja'])
        self.assertEqual(nye['Clever Kw250'], ['Clever', 'Clever Kw250', 'Ladevej 7, 4100 Ringsted', '4100',
                                               'Ringsted', '250', 'CCS', '2'] + ll((55.4 + 7 * 0.02, 11.8)) + [''])
        self.kun_tilfoejet(LADE, 4)
        self.ingen_linje(ud, 'AFVIST')

    def test_ufuldstaendige_ladere_taeller_ikke_i_vaekstspaerren(self):
        """Testene 14-10-2026, efter MIN_NYE_FRIT = 1: kom fuldstaendighedstjekket EFTER vaekstspaerren,
        talte poster uden brugbar effekt, stik eller antal med, og ét rigtigt nyt anlaeg ved siden af 3
        ufuldstaendige blev AFVIST sammen med dem (Allego, 6 raekker). Nu meldes de 3 som 'NY
        (UFULDSTÆNDIG)' foer spaerren, og det fuldstaendige tilfoejes. Spaerren taeller kun det, der kan
        tilfoejes: 2 fuldstaendige mod 6 afvises stadig (Eviny), men den ufuldstaendige meldes alligevel."""
        allego = [lader('Allego', f'Allego Bil {i}', f'Allegovej {i}', '7100', 'Vejle', 300, 'CCS', 4, p)
                  for i, p in enumerate(gitter(6, (55.6, 9.3)), 1)]
        eviny = [lader('Eviny', f'Eviny Bil {i}', f'Evinyvej {i}', '4000', 'Roskilde', 300, 'CCS', 4, p)
                 for i, p in enumerate(gitter(6, (55.5, 11.6)), 1)]

        def ny(brand, navn, k, **e):      # i Vendsyssel, langt fra alle vores raekker
            return post(brand, navn, f'Ladevej {k}', '9800', 'Hjørring', (57.0 + k * 0.03, 10.0), **e)
        allego_nye = [ny('Allego', 'Allego Ny Fuld', 1, kw=300, plug='CCS', count=4),
                      ny('Allego', 'Allego Ny Kw150', 2, kw=150, plug='CCS', count=4),
                      ny('Allego', 'Allego Ny Uden Stik', 3, kw=300, plug='', count=4),
                      ny('Allego', 'Allego Ny Uden Antal', 4, kw=300, plug='CCS', count=0)]
        eviny_nye = [ny('Eviny', 'Eviny Ny Fuld 1', 5, kw=400, plug='CCS', count=2),
                     ny('Eviny', 'Eviny Ny Fuld 2', 6, kw=400, plug='CCS', count=2),
                     ny('Eviny', 'Eviny Ny Uden Effekt', 7, kw=None, plug='CCS', count=2)]
        rc, ud = self.koer({LADE: allego + eviny},
                           [('allego', henter(*[som_kilde(r) for r in allego], *allego_nye)),
                            ('eviny', henter(*[som_kilde(r) for r in eviny], *eviny_nye))],
                           ejer={'allego': ['Allego'], 'eviny': ['Eviny']}, lade={'allego', 'eviny'})
        self.assertEqual(rc, 0, ud)
        navne = ('Allego Ny Kw150', 'Allego Ny Uden Stik', 'Allego Ny Uden Antal', 'Allego Ny Fuld')
        self.assertEqual({n for n in navne if self.linjer(ud, 'NY (UFULDSTÆNDIG)', f': {n} —')},
                         set(navne[:3]), ud)
        self.ingen_linje(ud, 'AFVIST', 'Allego')
        self.en_linje(ud, 'NY BUTIK', 'Allego Ny Fuld')
        self.en_linje(ud, 'NY (UFULDSTÆNDIG)', 'Eviny Ny Uden Effekt')
        self.en_linje(ud, 'AFVIST', 'Eviny (lader): 2 nye mod 6 eksisterende')
        self.ingen_linje(ud, 'NY BUTIK', 'Eviny')
        vore = {r[1] for r in allego + eviny}
        self.assertEqual([r[1] for r in self.laes(LADE)[1] if r[1] not in vore], ['Allego Ny Fuld'])
        self.kun_tilfoejet(LADE, 1)

    def _elleve_ladere(self, brand, n_nye):
        """11 bilraekker for maerket (Spirii har 11 i ladefilen, 14-10-2026), som kilden har uaendret, og
        n_nye fuldstaendige nye anlaeg paa Sjaelland, langt fra dem alle. 2 nye mod 11 er over vaekstspaerren
        (flere end MIN_NYE_FRIT = 1 og end 10 % af 11 = 1,1); 1 ny er altid tilladt."""
        vore = [lader(brand, f'{brand} Bil {i}', f'{brand}vej {i}', '6950', 'Ringkøbing', 300, 'CCS', 4, p)
                for i, p in enumerate(gitter(11, (56.0, 8.5)), 1)]
        nye = [post(brand, f'{brand} Ny Køge', 'Køgevej 12', '4600', 'Køge', KOEGE, kw=400, plug='CCS', count=2),
               post(brand, f'{brand} Ny Roskilde', 'Roskildevej 80', '4000', 'Roskilde', ROSKILDE,
                    kw=400, plug='CCS', count=2)][:n_nye]
        return vore, henter(*[som_kilde(r) for r in vore], *nye)

    def test_kun_rapport_over_vaekstspaerren_navngiver_hvert_nyt_anlaeg(self):
        """Fundet af testene 14-10-2026: en KUN_RAPPORT-henter skriver aldrig noget, men vaekstspaerren gav
        Spirii (11 raekker + 2 nye fuldstaendige anlaeg) én AFVIST-linje uden navne, saa de nye anlaeg var
        usynlige i rapporten. Nu er hvert nyt anlaeg 'NY (RAPPORT)' med kildens EGET navn og gade og
        spaerrens tal - uden adresseopslag i DAR (kilden kan vaere i stykker), intet skrives, ingen AFVIST."""
        vore, hent = self._elleve_ladere('Spirii', 2)
        with mock.patch.object(R, 'reverse_full', side_effect=self._reverse) as rv:
            rc, ud = self.koer({LADE: vore}, [('spirii', hent)], ejer={'spirii': ['Spirii']},
                               lade={'spirii'}, kun_rapport={'spirii'})
        self.assertEqual(rc, 0, ud)
        # Gaden staar, som kilden skrev den ('Køgevej 12'), ikke som den adresse DAR ville have bygget.
        self.en_linje(ud, 'NY (RAPPORT)', 'Spirii (lader): Spirii Ny Køge · Køgevej 12 — tilføjes IKKE '
                                          '(KUN_RAPPORT; 2 nye mod 11, over 10%)')
        self.en_linje(ud, 'NY (RAPPORT)', 'Spirii (lader): Spirii Ny Roskilde · Roskildevej 80 — tilføjes IKKE '
                                          '(KUN_RAPPORT; 2 nye mod 11, over 10%)')
        self.assertEqual(len(self.linjer(ud, 'NY (RAPPORT)')), 2, ud)
        self.ingen_linje(ud, 'AFVIST')
        self.ingen_linje(ud, 'NY BUTIK')
        self.assertEqual(self.normaliseret, [], 'normalize_rows (DAR) kaldt for en mulig kildefejl')
        rv.assert_not_called()
        self.assertEqual(tal(ud), {'nye': 0, 'luk': 0, 'afvig': 0, 'fejl': 0, 'skrevet': 0})
        self.uroert()

    def test_kun_rapport_under_vaekstspaerren_gaar_stadig_gennem_dar(self):
        """Graensen for rettelsen 14-10-2026 (fundet af testene): kun vaekstspaerren springer adresseopslaget
        over. Under den (1 ny mod 11 - ét ad gangen er altid tilladt) gaar en KUN_RAPPORT-henters nye anlaeg
        stadig gennem normalize_rows og reverse_full og meldes med den normale 'NY (RAPPORT)'-linje og den
        opslaaede adresse - aldrig skrevet."""
        vore, hent = self._elleve_ladere('Spirii', 1)
        with mock.patch.object(R, 'reverse_full', side_effect=self._reverse) as rv:
            rc, ud = self.koer({LADE: vore}, [('spirii', hent)], ejer={'spirii': ['Spirii']},
                               lade={'spirii'}, kun_rapport={'spirii'})
        self.assertEqual(rc, 0, ud)
        ny = ['Spirii', 'Spirii Ny Køge', 'Køgevej 12, 4600 Køge', '4600', 'Køge', '400', 'CCS', '2'] \
            + ll(KOEGE) + ['']
        self.assertEqual([rows for rows, _ in self.normaliseret], [[ny]])
        self.assertEqual(self.normaliseret[0][1], {'adr': 2, 'postnr': 3, 'by': 4, 'lat': 8, 'lon': 9})
        rv.assert_called_once_with(*KOEGE)
        self.en_linje(ud, 'NY (RAPPORT)', 'Spirii (lader): Spirii Ny Køge · Køgevej 12, 4600 Køge',
                      'tilføjes IKKE automatisk (KUN_RAPPORT)')
        self.assertEqual(len(self.linjer(ud, 'NY (RAPPORT)')), 1, ud)
        self.ingen_linje(ud, 'AFVIST')
        self.assertEqual(tal(ud), {'nye': 0, 'luk': 0, 'afvig': 0, 'fejl': 0, 'skrevet': 0})
        self.uroert()

    def test_auto_henter_over_vaekstspaerren_er_stadig_afvist(self):
        """Modstykket til rettelsen 14-10-2026 (fundet af testene): kun KUN_RAPPORT faar navnene. En henter,
        der selv tilfoejer (Allego), med samme 11 raekker + 2 nye er stadig AFVIST - én linje, intet
        adresseopslag, intet skrevet og exit 0 (et fund til gennemsyn, ikke en henterfejl)."""
        vore, hent = self._elleve_ladere('Allego', 2)
        rc, ud = self.koer({LADE: vore}, [('allego', hent)], ejer={'allego': ['Allego']}, lade={'allego'})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'AFVIST', 'Allego (lader): 2 nye mod 11 eksisterende')
        self.assertEqual(len(self.linjer(ud, 'AFVIST')), 1, ud)
        self.ingen_linje(ud, 'NY (RAPPORT)')
        self.ingen_linje(ud, 'NY BUTIK')
        self.assertEqual(self.normaliseret, [])
        self.assertEqual(tal(ud), {'nye': 0, 'luk': 0, 'afvig': 0, 'fejl': 0, 'skrevet': 0})
        self.uroert()

    def test_kendt_uden_kilde_er_ikke_en_lukning(self):
        """reconcile.py meldte 10 nye ladeanlaeg i tre uger uden at nogen saa det: en rapport med de
        samme afgjorte poster bliver ikke laest. KENDT_UDEN_KILDE (Espresso House Lalandia 01-10-2026,
        Clevers UFC-anlaeg 13-10-2026) meldes som KENDT med grunden; noeglen er (maerke uden |lade, Navn)."""
        fast = [butik('Espresso House', 'Espresso House Lalandia Billund', 'Ellehammers Alle 1', '7190',
                      'Billund', LALANDIA),
                butik('Espresso House', 'Espresso House Aarhus', 'Strøget 9', '8000', 'Aarhus C', AARHUS),
                butik('Espresso House', 'Espresso House Odense', 'Vestergade 9', '5000', 'Odense C', ODENSE)]
        haverslev = lader('Clever', 'Haverslev UFC (Powered by E.ON Drive & Clever)', 'Motorvejen 1', '9610',
                          'Nørager', 300, 'CCS', 4, HAVERSLEV)
        vejle = lader('Clever', 'Clever Vejle', 'Vejlevej 1', '7100', 'Vejle', 300, 'CCS', 4, VEJLE)
        rc, ud = self.koer({FAST: fast, LADE: [haverslev, vejle]},
                           [('espressohouse', henter(som_kilde(fast[2]))), ('clever', henter(som_kilde(vejle)))],
                           ejer={'espressohouse': ['Espresso House'], 'clever': ['Clever']}, lade={'clever'},
                           kendt={('Espresso House', 'Espresso House Lalandia Billund'): 'to caféer (testgrund)',
                                  ('Clever', haverslev[1]): 'joint venture (testgrund)'})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'KENDT', 'Espresso House Lalandia', 'to caféer (testgrund)')   # navnet kappes ved 30
        self.en_linje(ud, 'KENDT', 'Haverslev UFC', 'joint venture (testgrund)')
        self.assertEqual(len(self.linjer(ud, 'MULIG LUKNING')), 1, ud)
        self.en_linje(ud, 'MULIG LUKNING', 'Espresso House Aarhus')
        self.assertEqual(tal(ud)['luk'], 1)

    def test_udeladt_kommer_ikke_tilbage(self):
        """30-09-2026: faengselsbutikken (SuperBrugsen Søbysøgård) blev slettet i haanden og var uden
        UDELADT kommet tilbage naeste mandag. Noeglen er (maerke, gade i lowercase med enkelte mellemrum)."""
        odense = butik('SuperBrugsen', 'SuperBrugsen Odense', 'Vestergade 3', '5000', 'Odense C', ODENSE)
        kilde = [som_kilde(odense),
                 post('SuperBrugsen', 'SuperBrugsen Søbysøgård', 'Søvej  27', '5792', 'Årslev', SOEBY)]
        rc, ud = self.koer({DAG: [odense]}, [('coop', henter(*kilde))], ejer={'coop': ['SuperBrugsen']},
                           udeladt={('SuperBrugsen', 'søvej 27'): 'fængselsbutik (testgrund)'})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'UDELADT', 'SuperBrugsen', 'fængselsbutik (testgrund)')
        self.ingen_linje(ud, 'NY BUTIK')
        self.assertEqual(tal(ud)['nye'], 0)
        self.uroert()

    def test_kildedubletter_tilfoejes_hoejst_en_gang(self):
        """toejeksperten.dk listede 'Tøjeksperten Ballerup' to gange (samme navn, gade, koordinat):
        navnematchen faldt bort, og den anden blev skrevet ind som byte-identisk dublet (hard error i
        validate.py). En kendt butik tilfoejes ikke igen, en ny kun én gang - KILDEDUBLET meldes."""
        ballerup = butik('Tøjeksperten', 'Tøjeksperten Ballerup', 'Centervej 1', '2750', 'Ballerup', BALLERUP)
        aarhus = butik('Tøjeksperten', 'Tøjeksperten Aarhus', 'Strøget 1', '8000', 'Aarhus C', AARHUS)
        koege = post('Tøjeksperten', 'Tøjeksperten Køge', 'Torvet 1', '4600', 'Køge', KOEGE)
        kilde = [som_kilde(ballerup), som_kilde(ballerup), som_kilde(aarhus), koege, dict(koege)]
        rc, ud = self.koer({UDV: [ballerup, aarhus]}, [('toejeksperten', henter(*kilde))],
                           ejer={'toejeksperten': ['Tøjeksperten']})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'KILDEDUBLET', '2 post(er)')
        self.assertEqual(sorted(r[1] for r in self.laes(UDV)[1]),
                         ['Tøjeksperten Aarhus', 'Tøjeksperten Ballerup', 'Tøjeksperten Køge'])
        self.kun_tilfoejet(UDV, 1)
        self.assertEqual(tal(ud), {'nye': 1, 'luk': 0, 'afvig': 0, 'fejl': 0, 'skrevet': 1})

    def test_lader_aendret_meldes_og_rettes_ikke(self):
        """06-10-2026: OK Galten 4 -> 8 udtag. Afviger kW/antal fra vores parrede raekke: LADER ÆNDRET,
        intet rettes - heller ikke naar filen skrives om. LADER_KENDT (Clever Brønshøj 350, 13-10-2026)
        giver KENDT, men kun for netop den kildevaerdi: aendrer kilden tallet, kommer linjen igen."""
        broenshoej = lader('Clever', 'Lynladestation Brønshøj', 'Frederikssundsvej 1', '2700', 'Brønshøj',
                           300, 'CCS', 8, BROENSHOEJ)
        vejle = lader('Clever', 'Clever Vejle', 'Vejlevej 1', '7100', 'Vejle', 300, 'CCS', 4, VEJLE)
        kolding = lader('Clever', 'Clever Kolding', 'Koldingvej 1', '6000', 'Kolding', 300, 'CCS', 4, KOLDING)
        kilde = [som_kilde(broenshoej, kw=350), som_kilde(vejle, count=6), som_kilde(kolding, kw=400),
                 post('Clever', 'Clever Horsens', 'Horsensvej 1', '8700', 'Horsens', HORSENS,
                      kw=300, plug='CCS', count=4)]
        rc, ud = self.koer({LADE: [broenshoej, vejle, kolding]}, [('clever', henter(*kilde))],
                           ejer={'clever': ['Clever']}, lade={'clever'},
                           lader_kendt={('Clever', 'Lynladestation Brønshøj', 'kW', '350'): 'rest fra juli (testgrund)',
                                        ('Clever', 'Clever Kolding', 'kW', '350'): 'gammel afgørelse (testgrund)'})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'KENDT', 'Lynladestation Brønshøj', 'kW 300 -> 350', 'rest fra juli (testgrund)')
        self.ingen_linje(ud, 'LADER ÆNDRET', 'Brønshøj')
        self.en_linje(ud, 'LADER ÆNDRET', 'Clever Vejle', 'ladepunkter 4 -> 6', 'RETTES IKKE')
        self.en_linje(ud, 'LADER ÆNDRET', 'Clever Kolding', 'kW 300 -> 400')
        body = self.laes(LADE)[1]
        for r in (broenshoej, vejle, kolding):
            self.assertIn(r, body)
        self.kun_tilfoejet(LADE, 1)

    def test_egen_raekke_uden_koordinat_vaelter_ikke_koerslen(self):
        """17-09-2026: float('') paa en tom koordinat i vores egen CSV vaeltede hele koerslen, og
        rapporten blev et traceback. Raekken meldes (UBRUGELIG RÆKKE), resten koeres, raekken staar uroert."""
        tom = ['Matas', 'Matas', 'Torvet 1, 8800 Viborg', '8800', 'Viborg', '', '']
        randers = butik('Matas', 'Matas', 'Brødregade 1', '8900', 'Randers C', RANDERS)
        kilde = [som_kilde(randers), post('Matas', 'Matas', 'Sct. Mathias Gade 1', '8800', 'Viborg', VIBORG)]
        rc, ud = self.koer({UDV: [tom, randers]}, [('matas', henter(*kilde))], ejer={'matas': ['Matas']})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'UBRUGELIG RÆKKE', 'Matas: 1 af vores egne rækker')
        self.en_linje(ud, 'NY BUTIK', 'Sct. Mathias Gade 1')
        self.kun_tilfoejet(UDV, 1)

    def test_adresseopslag_udfald_og_udenlandske_punkter(self):
        """17-09-2026: DK-boksen raekker ind i Tyskland/Sverige, og reverse svarer med naermeste danske
        punkt (Flensburg 5,4 km): udelad raekken. 'ingen-adresse' udelader kun RAEKKEN. Svarer DAR ikke
        (status eller DawaNede fra reverse_full, review 29-09-2026), AFVISES maerkets nye - intet crash."""
        lidl = butik('Lidl', 'Lidl Aalborg', 'Hobrovej 1', '9000', 'Aalborg', AALBORG)
        rema = butik('REMA 1000', 'REMA 1000 Odense', 'Vestergade 9', '5000', 'Odense C', ODENSE)
        meny = butik('MENY', 'MENY Hillerød', 'Slotsgade 1', '3400', 'Hillerød', HILLEROED)
        spar = butik('SPAR', 'SPAR Esbjerg', 'Kongensgade 1', '6700', 'Esbjerg', ESBJERG)
        # Lidl og SPAR faar hver 2 nye. Med MIN_NYE_FRIT = 1 (14-10-2026) skal et maerke have mindst 20
        # raekker, for at 2 nye slipper under vaekstspaerren - og den er ikke det, der proeves her. Begge
        # faar derfor 23 raekker mere, som kilden ogsaa har.
        lidl_flere = [butik('Lidl', f'Lidl Gitter {i}', f'Lidlvej {i}', '7500', 'Holstebro', p)
                      for i, p in enumerate(gitter(23, (56.3, 8.5)), 1)]
        spar_flere = [butik('SPAR', f'SPAR Gitter {i}', f'Sparvej {i}', '6900', 'Skjern', p)
                      for i, p in enumerate(gitter(23, (55.8, 8.2)), 1)]
        graense, flensborg, malmoe = (54.82, 9.43), (54.79, 9.43), (55.6, 13.0)
        rema_ny, meny_ny = (55.3, 10.7), (55.95, 12.3)
        self.status = {'Lidl Grænsen': 'ingen-adresse', 'REMA 1000 Ny': 'dawa-nede'}
        self.rv_svar = {meny_ny: R.DawaNede('DAR svarer ikke (test)'),
                        flensborg: ('Grænsevej', '1', '6330', 'Padborg', 54.8386, 9.43),
                        malmoe: None}
        kaeder = [('lidl', henter(som_kilde(lidl), *[som_kilde(r) for r in lidl_flere],
                                  post('Lidl', 'Lidl Grænsen', 'Grænsevej 2', '6330', 'Padborg', graense),
                                  post('Lidl', 'Lidl Vejle Ny', 'Vejlevej 7', '7100', 'Vejle', VEJLE))),
                  ('rema', henter(som_kilde(rema),
                                  post('REMA 1000', 'REMA 1000 Ny', 'Nyvej 1', '5700', 'Svendborg', rema_ny))),
                  ('dagrofa', henter(som_kilde(meny),
                                     post('MENY', 'MENY Ny', 'Nyvej 2', '3480', 'Fredensborg', meny_ny))),
                  ('spar', henter(som_kilde(spar), *[som_kilde(r) for r in spar_flere],
                                  post('SPAR', 'SPAR Flensborg', 'Holm 1', '24937', 'Flensburg', flensborg),
                                  post('SPAR', 'SPAR Malmø', 'Torget 1', '21122', 'Malmö', malmoe)))]
        rc, ud = self.koer({DAG: [lidl, rema, meny, spar] + lidl_flere + spar_flere}, kaeder,
                           ejer={'lidl': ['Lidl'], 'rema': ['REMA 1000'], 'dagrofa': ['MENY'], 'spar': ['SPAR']})
        self.en_linje(ud, 'UDEN FOR DK?', 'Lidl Grænsen', 'ingen dansk adresse')
        self.en_linje(ud, 'NY BUTIK', 'Lidl Vejle Ny')
        self.en_linje(ud, 'AFVIST', 'REMA 1000:', 'svarede ikke for 1 af 1 nye')
        self.en_linje(ud, 'AFVIST', 'MENY:', 'svarede ikke for 1 af 1 nye')
        self.assertEqual(len(self.linjer(ud, 'AFVIST')), 2, ud)      # kun DAR-udfaldene, ingen vaekstspaerre
        self.ingen_linje(ud, 'HALVDEL MANGLER')
        self.en_linje(ud, 'UDEN FOR DK?', 'SPAR Flensborg', '5 km vaek')
        self.en_linje(ud, 'UDEN FOR DK?', 'SPAR Malmø', 'ingen dansk adresse')
        self.assertEqual(sorted(r[1] for r in self.laes(DAG)[1]),
                         sorted(['Lidl Aalborg', 'REMA 1000 Odense', 'MENY Hillerød', 'SPAR Esbjerg', 'Lidl Vejle Ny']
                                + [r[1] for r in lidl_flere + spar_flere]))
        self.kun_tilfoejet(DAG, 1)
        self.assertEqual(tal(ud)['nye'], 1)

    def _q8(self):
        ribe = tank('Q8', 'Q8 Ribe', 'Ribevej 1', '6760', 'Ribe', RIBE)
        vejen = tank('Q8', 'Q8 Vejen', 'Vejenvej 1', '6600', 'Vejen', VEJEN)
        broerup = tank('F24', 'F24 Brørup', 'Brørupvej 1', '6650', 'Brørup', BROERUP)
        f24_ribe = post('F24', 'F24 Ribe', 'Ribevej 3', '6760', 'Ribe', nord(RIBE, 107))
        return ribe, vejen, broerup, f24_ribe

    def test_maerkeskift_tilfoejes_ikke(self):
        """Review 02-10-2026: en Q8-station omdoebt til F24 staar paa den gamle pin og blev tilfoejet
        oven paa den gamle raekke (kryds-maerke-dublet). Er det gamle maerke vaek fra kilden dér: MÆRKESKIFT.
        107 m = Kvickly -> SuperBrugsen Hjørring 10-2026, der flyttede MAERKESKIFT_M fra 50 til 150."""
        ribe, vejen, broerup, f24_ribe = self._q8()
        rc, ud = self.koer({TANK: [ribe, vejen, broerup]},
                           [('q8_f24', henter(som_kilde(vejen), som_kilde(broerup), f24_ribe))],
                           ejer={'q8_f24': ['Q8', 'F24']})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'MÆRKESKIFT', 'F24 Ribe', 'Q8-række "Q8 Ribe"', 'står 107 m')
        self.en_linje(ud, 'MULIG LUKNING', 'Q8 Ribe')
        self.ingen_linje(ud, 'NY BUTIK')
        self.uroert()

    def test_to_maerker_samme_sted_er_to_butikker(self):
        """Modstykket til MÆRKESKIFT (review 02-10-2026): staar det gamle maerke STADIG i kilden paa
        stedet, er det to butikker (fx Kvickly og 365discount i samme center), og den nye tilfoejes."""
        ribe, vejen, broerup, f24_ribe = self._q8()
        rc, ud = self.koer({TANK: [ribe, vejen, broerup]},
                           [('q8_f24', henter(som_kilde(vejen), som_kilde(ribe), som_kilde(broerup), f24_ribe))],
                           ejer={'q8_f24': ['Q8', 'F24']})
        self.assertEqual(rc, 0, ud)
        self.ingen_linje(ud, 'MÆRKESKIFT')
        self.ingen_linje(ud, 'MULIG LUKNING')
        ny = ['F24', 'F24 Ribe', 'Ribevej 3, 6760 Ribe', '6760', 'Ribe'] + ll(nord(RIBE, 107)) + ['']
        self.assertIn(ny, self.laes(TANK)[1])
        self.kun_tilfoejet(TANK, 1)

    def test_navn_foer_naerhed_og_naermeste_par(self):
        """16-09-2026: naerhed alene gjorde vores egne flyttede raekker til 'ny' + 'lukning' (11 af 12);
        delstreng-match parrede 'THIELE Aalborg' med '... Storcenter' (5,7 km). 17-09-2026: ved to
        nabobutikker (Matas Frederiksberg 7 m) skal den NAERMESTE parres, ellers peger lukningen forkert."""
        meny = butik('MENY', 'MENY Roskilde', 'Algade 1', '4000', 'Roskilde', ROSKILDE)
        th_sc = butik('THIELE', 'THIELE Aalborg Storcenter', 'Hobrovej 452', '9200', 'Aalborg SV', AALBORG_SC)
        th_c = butik('THIELE', 'THIELE Aalborg', 'Bispensgade 1', '9000', 'Aalborg', AALBORG)
        m21 = butik('Matas', 'Matas', 'Falkoner Allé 21', '2000', 'Frederiksberg', FRB)
        m25 = butik('Matas', 'Matas', 'Falkoner Allé 25', '2000', 'Frederiksberg', nord(FRB, 7))
        kaeder = [('dagrofa', henter(post('MENY', 'MENY Roskilde', 'Algade 1', '4000', 'Roskilde',
                                          nord(ROSKILDE, 2000)))),
                  ('thiele', henter(som_kilde(th_c), som_kilde(th_sc))),
                  ('matas', henter(som_kilde(m25)))]
        rc, ud = self.koer({DAG: [meny], UDV: [th_sc, th_c, m21, m25]}, kaeder,
                           ejer={'dagrofa': ['MENY'], 'thiele': ['THIELE'], 'matas': ['Matas']})
        self.assertEqual(rc, 0, ud)
        self.en_linje(ud, 'KOORD-AFVIGELSE', 'MENY Roskilde', 'ligger 2000 m')
        self.ingen_linje(ud, 'KOORD-AFVIGELSE', 'THIELE')
        self.ingen_linje(ud, 'NY BUTIK')
        luk = self.linjer(ud, 'MULIG LUKNING')
        self.assertEqual(len(luk), 1, ud)
        self.assertIn('Falkoner Allé 21', luk[0])
        self.assertEqual(tal(ud), {'nye': 0, 'luk': 1, 'afvig': 1, 'fejl': 0, 'skrevet': 0})
        self.uroert()

    def test_rigtige_registre_og_kolonner_haenger_sammen(self):
        """17-09-2026: uden en EJER-post kan MÆRKE MANGLER ikke fyre for henteren. Og _rk/_ll/normalize
        laeser kolonner efter NUMMER (Lastbil i 7/10, lat/lon i 8/9 i ladefilen): de skal passe til de
        RIGTIGE CSV-hoveder. En UDELADT-gade med versaler eller en LADER_KENDT-vaerdi som tal rammer aldrig."""
        self.assertEqual(set(R.FILER), {DAG, UDV, PLADS, TANK, FAST, LADE})
        self.assertEqual((R.TANK, R.LADE), (TANK, LADE))
        for fn, h in HOVED.items():
            la, lo = R._ll(fn)
            self.assertEqual((h[1], h[2:5], h[la], h[lo]), ('Navn', ['Adresse', 'Postnr', 'By'], 'Latitude',
                                                           'Longitude'), fn)
        self.assertEqual(HOVED[TANK][7], 'Lastbil')
        self.assertEqual(HOVED[LADE][5:8] + HOVED[LADE][10:], ['Effekt_kW', 'Stik', 'Antal_ladere', 'Lastbil'])
        navne = [n for n, _ in R.KAEDER]
        self.assertEqual(len(navne), len(set(navne)))
        self.assertEqual([n for n in navne if n not in R.EJER], [], 'hentere uden EJER-post')
        self.assertLessEqual(R.LADE_KAEDER | R.KUN_RAPPORT, set(navne))
        self.assertLessEqual(set(R.EN_HALVDEL), R.LADE_KAEDER)
        self.assertLessEqual(set(R.EN_HALVDEL.values()), {'bil', 'lastbil'})
        for d in (R.UDELADT, R.KENDT_UDEN_KILDE, R.LADER_KENDT):
            for k, grund in d.items():
                self.assertTrue(isinstance(grund, str) and grund.strip(), k)
                self.assertNotIn('|', k[0], k)
        for maerke, gade in R.UDELADT:
            self.assertEqual(gade, ' '.join(gade.lower().split()), (maerke, gade))
        for maerke, navn, felt, vaerdi in R.LADER_KENDT:
            self.assertIn(felt, ('kW', 'ladepunkter'))
            self.assertIsInstance(vaerdi, str)

    def test_halvdel_ikke_i_kilden_kan_ramme(self):
        """14-10-2026 (HALVDEL MANGLER): en post i HALVDEL_IKKE_I_KILDEN slukker en fejlmelding hver uge,
        saa den skal kunne ramme og baere sin grund med dato (registrets egen regel). Noeglen er (henter,
        maerke, halvdel) med henteren i KAEDER, maerket i EJER[henter] og halvdelen 'bil' eller 'lastbil' -
        og ikke den halvdel, en EN_HALVDEL-henter alligevel aldrig vurderer."""
        navne = {n for n, _ in R.KAEDER}
        self.assertIsInstance(R.HALVDEL_IKKE_I_KILDEN, dict)
        for k, grund in R.HALVDEL_IKKE_I_KILDEN.items():
            self.assertTrue(isinstance(k, tuple) and len(k) == 3, k)
            henter_navn, maerke, halvdel = k
            self.assertIn(henter_navn, navne, k)
            self.assertIn(maerke, R.EJER.get(henter_navn, []), k)
            self.assertIn(halvdel, ('bil', 'lastbil'), k)
            self.assertEqual(R.EN_HALVDEL.get(henter_navn, halvdel), halvdel, f'{k}: halvdelen vurderes aldrig')
            self.assertTrue(isinstance(grund, str) and re.search(r'\b\d{1,2}-\d{1,2}-\d{4}\b', grund),
                            f'{k}: grunden skal have en dato')

    def test_kun_rapport_over_vaekstspaerren_hoejst_20_navne_og_rensede_tekster(self):
        """Fundet af testene 14-10-2026: navnelinjerne for en KUN_RAPPORT-henter over vaekstspaerren brugte
        kildens raa tekst (HTML-entiteter, linjeskift) og havde intet loft - en kilde i stykker med 200 nye
        poster ville give 200 linjer. Nu renses teksten som paa den normale vej, og der vises hoejst 20
        navne plus én linje med resten."""
        vore, _ = self._elleve_ladere('Spirii', 0)
        nye = [post('Spirii', f'Spirii Ny {i} &amp; Co', f'Nyvej\n{i}', '4000', 'Roskilde', p,
                    kw=400, plug='CCS', count=2)
               for i, p in enumerate(gitter(25, (55.2, 11.5)), 1)]
        hent = henter(*[som_kilde(r) for r in vore], *nye)
        with mock.patch.object(R, 'reverse_full', side_effect=self._reverse) as rv:
            rc, ud = self.koer({LADE: vore}, [('spirii', hent)], ejer={'spirii': ['Spirii']},
                               lade={'spirii'}, kun_rapport={'spirii'})
        self.assertEqual(rc, 0, ud)
        self.assertEqual(len(self.linjer(ud, 'NY (RAPPORT)')), 21, ud)        # 20 navne + 'og 5 flere'
        self.en_linje(ud, 'NY (RAPPORT)', 'Spirii (lader): Spirii Ny 1 & Co · Nyvej 1 — tilføjes IKKE '
                                          '(KUN_RAPPORT; 25 nye mod 11, over 10%)')
        self.en_linje(ud, 'NY (RAPPORT)', 'Spirii (lader): ... og 5 flere — mulig kildefejl')
        self.assertNotIn('&amp;', ud)
        self.ingen_linje(ud, 'AFVIST')
        self.assertEqual(self.normaliseret, [])
        rv.assert_not_called()
        self.uroert()

if __name__ == '__main__':
    unittest.main()
