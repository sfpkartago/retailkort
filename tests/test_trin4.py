"""Trin 4 (18-11-2026): de spaerrede kaeder holdt op mod smiley-registret og CVR (kaede_register_tjek.py). Kun rapport.
Testene koerer de rigtige funktioner mod stubbe af registrene: smiley-XML'en, Datafordelerens CVR-sider og DAR."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # noqa: F401  (repo-roden paa sys.path og nettet spaerret)

import contextlib
import csv
import io
import re
import shutil
import tempfile
import unittest
from unittest import mock

import kaede_register_tjek as K
from test_refresh_retail import HOVED, nord

KBH, AARHUS, ODENSE = (55.6761, 12.5683), (56.157, 10.211), (55.396, 10.388)


def _smiley(*rows):
    from xml.sax.saxutils import escape as e

    def row(navn, adr, pn, by, pnr, typ='Detail', branche='Serveringsvirksomhed - Restauranter m.v.'):
        navn, adr, by = e(navn), e(adr), e(by)
        return (f'<Row><P_nummer>{pnr}</P_nummer><FVST_branche>{branche}</FVST_branche>'
                f'<Virksomhedstype>{typ}</Virksomhedstype><Virksomhed>{navn}</Virksomhed><Adresse>{adr}</Adresse>'
                f'<Postnummer>{pn}</Postnummer><By>{by}</By></Row>')
    return ('<?xml version="1.0" encoding="utf-8"?><Root>' + ''.join(row(*r) for r in rows) + '</Root>').encode('utf-8')


class TestSmiley(unittest.TestCase):
    def test_kun_kaedens_restauranter_ikke_kontor_og_shop_in_shop(self):
        xml = _smiley(("McDonald's Ringsted", 'Klosterparks Alle 9', '4100', 'Ringsted', '1029617992'),
                      ("McDonald's Danmark", 'Skt. Petri Passage 5', '1165', 'København K', '1', 'Engros',
                       'Kædekontrolhovedkontor - Fødevarer'),
                      # hver betingelse alene: detail, men kontor - og servering, men engros
                      ("McDonald's Kontor", 'Kontorvej 1', '1165', 'København K', '6', 'Detail',
                       'Kontorvirksomhed eller agenturvirksomhed - uden lager'),
                      ("McDonald's Engros", 'Engrosvej 1', '1165', 'København K', '7', 'Engros',
                       'Serveringsvirksomhed - Restauranter m.v.'),
                      ('Joe & The Juice - Lyngby Magasin', 'Lyngby Hovedgade 43', '2800', 'Lyngby', '2'),
                      ('JOE & THE JUICE - Kongens Nytorv', 'Kongens Nytorv 13', '1050', 'København K', '3'),
                      ('Spis hos pries', 'Kværndrup Vænge 26', '5772', 'Kværndrup', '4'))
        mcd = K.smiley_poster(xml, K.KAEDER["McDonald's"]['navn'])
        self.assertEqual([p['navn'] for p in mcd], ["McDonald's Ringsted"])
        jj = K.smiley_poster(xml, K.KAEDER['Joe & The Juice']['navn'], K.KAEDER['Joe & The Juice']['ikke'])
        self.assertEqual([(p['navn'], p['gade'], p['postnr'], p['pnr']) for p in jj],
                         [('JOE & THE JUICE - Kongens Nytorv', 'Kongens Nytorv 13', '1050', '3')])


class TestCvr(unittest.TestCase):
    def setUp(self):
        self.slaaet_op = []

    def _sider(self, enheder, navne, adresser, branche=None):
        """enheder: [(id, pnr, ejer, aktiv)]; navne: {id: navn}; adresser: {id: (vej, nr, pn)}."""
        def f(entitet, where, felter):
            ids = [int(x) for x in re.findall(r'\d+', where.split('in:')[1])] if 'in:' in where else None
            if entitet == 'CVR_Branche':
                return [{'CVREnhedsId': i} for i in (branche or [])]
            if entitet == 'CVR_Produktionsenhed':
                self.slaaet_op += ids or []
                ejer = int(re.search(r'eq:(\d+)', where).group(1)) if 'eq:' in where else None
                return [{'id': i, 'pNummer': p, 'status': 'aktiv' if a else 'ophoert',
                         'produktionsenhedOphoersdato': None if a else '2026-01-01', 'tilknyttetVirksomhedsCVRNummer': e}
                        for i, p, e, a in enheder if (ejer and e == ejer) or (ids and i in ids)]
            if entitet == 'CVR_Navn':
                return [{'CVREnhedsId': i, 'vaerdi': navne[i]} for i in ids if i in navne]
            if entitet == 'CVR_Adressering':
                return [{'CVREnhedsId': i, 'AdresseringAnvendelse': 'beliggenhedsadresse', 'CVRAdresse_vejnavn': v,
                         'CVRAdresse_husnummerFra': n, 'CVRAdresse_postnummer': p, 'CVRAdresse_postdistrikt': 'X'}
                        for i, (v, n, p) in adresser.items() if i in ids]
            raise AssertionError(entitet)
        return f

    def test_ejer_filtre_og_ophoerte(self):
        enh = [(1, 101, 33345828, True), (2, 102, 33345828, True), (3, 103, 33345828, True), (4, 104, 33345828, False),
               (5, 105, 33345828, True)]
        navne = {1: '808 H & M HENNES & MAURITZ', 2: 'H & M HENNES & MAURITZ A/S HOVEDKONTOR', 3: '622 Monki',
                 4: '809 H & M Fisketorvet', 5: 'Ukendt Butik Greve'}       # 5: kun navnefilteret holder den ude
        adr = {1: ('Rødovre Centrum', 1, 2610), 2: ('Amagertorv', 25, 1160), 3: ('Arne Jacobsens Allé', 12, 2300),
               4: ('Kalvebod Brygge', 59, 1560), 5: ('Ventrupparken', 7, 2670)}
        with mock.patch.object(K.C, '_sider', new=self._sider(enh, navne, adr)):
            ud = K.cvr_poster(K.KAEDER['H&M'])
        self.assertEqual([(p['navn'], p['gade'], p['postnr'], p['pnr']) for p in ud],
                         [('808 H & M HENNES & MAURITZ', 'Rødovre Centrum 1', '2610', '101')])

    def test_branche_og_navn(self):
        enh = [(11, 201, 31284880, True), (12, 202, 99, True)]
        navne = {11: 'LOUIS NIELSEN KØBMAGERGADE ApS', 12: 'Synoptik Købmagergade', 13: 'LOUIS NIELSEN HOLDING'}
        adr = {11: ('Købmagergade', 62, 1150), 12: ('Købmagergade', 1, 1150)}
        with mock.patch.object(K.C, '_sider', new=self._sider(enh, navne, adr, branche=[11, 12, 13])):
            ud = K.cvr_poster(K.KAEDER['Louis Nielsen'])
        self.assertEqual([p['pnr'] for p in ud], ['201'])
        # Kun enheder med kaedens navn slaas op som P-enheder - ikke hele branchen (1.514 enheder 18-11-2026)
        self.assertIn(11, self.slaaet_op)
        self.assertNotIn(12, self.slaaet_op)


class TestSammenlign(unittest.TestCase):
    def test_afstand_adresse_og_kendte(self):
        raekker = [('H&M Rødovre', 'Rødovre Centrum 1L, 2610 Rødovre', '2610', *KBH),
                   ('H&M Field\'s', 'Arne Jacobsens Allé 12, 2300 København S', '2300', *AARHUS),
                   ('H&M Odense', 'Testvej 1, 5000 Odense C', '5000', *ODENSE),
                   ('H&M Lukket', 'Testvej 3, 8000 Aarhus C', '8000', *nord(AARHUS, 9000)),
                   ('H&M Afgjort', 'Andenvej 2, 5000 Odense C', '5000', *nord(ODENSE, 5000))]
        poster = [{'navn': 'A', 'gade': 'Rødovre Centrum 1', 'postnr': '2610', 'pnr': '1', 'lat': nord(KBH, 100)[0], 'lon': KBH[1]},
                  # samme adresse (uden husbogstav i CVR), men centerets punkt 400 m vaek
                  {'navn': 'B', 'gade': 'Arne Jacobsens Allé 12', 'postnr': '2300', 'pnr': '2',
                   'lat': nord(AARHUS, 400)[0], 'lon': AARHUS[1]},
                  {'navn': 'C ny', 'gade': 'Nyvej 9', 'postnr': '8000', 'pnr': '3', 'lat': nord(AARHUS, 3000)[0], 'lon': AARHUS[1]},
                  # kun afstanden parrer: anden adressetekst, 200 m fra raekken (under NAER_M)
                  {'navn': 'F centeradresse', 'gade': 'Centervej 1', 'postnr': '5000', 'pnr': '6',
                   'lat': nord(ODENSE, 200)[0], 'lon': ODENSE[1]},
                  {'navn': 'D afgjort', 'gade': 'Lagervej 1', 'postnr': '2670', 'pnr': '4', 'lat': 55.6, 'lon': 12.3},
                  {'navn': 'E uden punkt', 'gade': 'Findes ikke 1', 'postnr': '9999', 'pnr': '5', 'lat': None, 'lon': None}]
        kendte = {('H&M', '4'): 'lager (18-11-2026)', ('H&M', 'H&M Afgjort'): 'grund (18-11-2026)'}
        nye, luk, uden, kendt = K.sammenlign('H&M', raekker, poster, kendte)
        self.assertEqual([p['navn'] for p, _ in nye], ['C ny'])
        self.assertEqual([r[0] for r, _ in luk], ['H&M Lukket'])
        self.assertEqual([p['navn'] for p in uden], ['E uden punkt'])
        self.assertEqual(len(kendt), 2)

    def test_adressenoeglen(self):
        self.assertEqual(K._adr_noegle('Lygten 2L', '2400'), K._adr_noegle('Lygten 2', '2400'))
        self.assertEqual(K._adr_noegle('Husby Allé 7', '2630'), K._adr_noegle('Husby Alle 7', '2630'))
        self.assertEqual(K._adr_noegle('Gl. Køge Landevej 248', '2650'), K._adr_noegle('Gammel Køge Landevej 248', '2650'))
        self.assertNotEqual(K._adr_noegle('Lygten 2', '2400'), K._adr_noegle('Lygten 20', '2400'))
        self.assertIsNone(K._adr_noegle('', '2400'))


class TestMain(unittest.TestCase):
    def setUp(self):
        self.mappe = tempfile.mkdtemp(prefix='test_trin4_')
        self.addCleanup(shutil.rmtree, self.mappe, True)
        for fn in (K.FAST, K.UDV):
            with open(os.path.join(self.mappe, fn), 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(HOVED[fn])
                if fn == K.FAST:
                    w.writerow(["McDonald's", "McDonald's Ringsted", 'Klosterparks Alle 9, 4100 Ringsted', '4100',
                                'Ringsted', f'{KBH[0]:.6f}', f'{KBH[1]:.6f}'])

    def koer(self, kaeder, poster):
        ud = io.StringIO()
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(K, 'OUT', self.mappe))
            st.enter_context(mock.patch.object(K, 'KAEDER', kaeder))
            st.enter_context(mock.patch.object(K.RS, '_robots_tilladt', new=lambda *a, **k: True))
            st.enter_context(mock.patch.object(K.RS, '_raw', new=lambda *a, **k: b'<Root/>'))
            st.enter_context(mock.patch.object(K, 'smiley_poster', new=lambda xml, rx, ikke=None: list(poster)))
            st.enter_context(mock.patch.object(K, 'geokod', new=lambda ps, workers=8: [dict(p, lat=KBH[0], lon=KBH[1]) for p in ps]))
            st.enter_context(contextlib.redirect_stdout(ud))
            rc = K.main()
        return rc, open(os.path.join(self.mappe, K.RAPPORT), encoding='utf-8').read()

    def test_ren_koersel_og_rapport(self):
        kaeder = {"McDonald's": dict(K.KAEDER["McDonald's"], forventet=(1, 5))}
        rc, rap = self.koer(kaeder, [{'navn': "McDonald's Ringsted", 'gade': 'Klosterparks Alle 9', 'postnr': '4100',
                                      'by': 'Ringsted', 'pnr': '1'}])
        self.assertEqual(rc, 0, rap)
        self.assertIn("McDonald's: 1 rækker hos os, 1 forretninger i smiley-registret", rap)
        self.assertIn('0 mulige nye butikker · 0 mulige lukninger · 0 kæde(r) fejlede', rap)

    def test_uventet_antal_er_en_koerselsfejl(self):
        kaeder = {"McDonald's": dict(K.KAEDER["McDonald's"], forventet=(100, 150))}
        rc, rap = self.koer(kaeder, [])
        self.assertEqual(rc, 2, rap)
        self.assertIn("McDonald's: FEJL", rap)
        self.assertIn('forventet 100-150', rap)

    def test_advarslen_skrives_foerst(self):
        """Doer tjekket undervejs, maa sidste uges rapport ikke blive liggende og ligne en ren kontrol."""
        kaeder = {"McDonald's": dict(K.KAEDER["McDonald's"], forventet=(1, 5))}

        def doer(*a, **k):
            with open(os.path.join(self.mappe, K.RAPPORT), encoding='utf-8') as f:
                self.assertIn('BLEV IKKE FÆRDIGT', f.read())
            raise KeyboardInterrupt
        with mock.patch.object(K, 'vore_raekker', new=doer):
            with self.assertRaises(KeyboardInterrupt):
                self.koer(kaeder, [{'navn': 'x', 'gade': 'y 1', 'postnr': '4100', 'by': 'z', 'pnr': '1'}])
        self.assertIn('BLEV IKKE FÆRDIGT', open(os.path.join(self.mappe, K.RAPPORT), encoding='utf-8').read())


class TestKendte(unittest.TestCase):
    def test_hver_post_har_dato_og_hoerer_til_en_kaede(self):
        self.assertEqual([k for k, v in K.KENDTE.items() if not re.search(r'\d{2}-\d{2}-\d{4}', v)], [])
        self.assertEqual([k for k in K.KENDTE if k[0] not in K.KAEDER], [])


class TestWorkflow(unittest.TestCase):
    def test_trinnet_koerer_og_rapporten_committes(self):
        t = open(os.path.join(hjaelp.ROD, '.github', 'workflows', 'weekly-refresh.yml'), encoding='utf-8').read()
        self.assertIn('run: python3 kaede_register_tjek.py', t)
        self.assertIn('id: register', t)
        self.assertIn('kaede_register_report.txt', t[t.index('Commit frisk feed'):])
        self.assertIn('register=${{ steps.register.outcome }}', t)


if __name__ == '__main__':
    unittest.main()
