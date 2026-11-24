"""Ugentlig gennemgang (18-11-2026, brugerens valg): ugens mulige lukninger og registertjekkets fund, slaaet op i CVR og
sorteret til godkendelse. Botten sletter aldrig selv. Testene koerer de rigtige funktioner; CVR-opslaget er stubbet."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # noqa: F401  (repo-roden paa sys.path og nettet spaerret)

import datetime
import json
import re
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import kaede_register_tjek as K
import refresh_retail as R
import ugentlig_gennemgang as G

IDAG = datetime.date(2026, 11, 23)
LUK = {'maerke': 'Netto', 'fil': 'dagligvarer_dk.csv', 'navn': 'Netto Ryvangs Allé',
       'adresse': 'Ryvangs Allé 87, 2100 København Ø', 'postnr': '2100', 'lat': 55.7210, 'lon': 12.5760}


def P(navn, status='aktiv', start='2010-01-01', ophoer=None, brancher=('471130',), nu=True, pnr=1000000001, firma=''):
    return {'type': 'P', 'pnr': pnr, 'navn': navn, 'firma': firma, 'status': status, 'start': start, 'ophoer': ophoer,
            'brancher': list(brancher), 'nu': nu}


class TestMaerkeOgAdresse(unittest.TestCase):
    def test_maerkets_navn_i_cvr(self):
        for maerke, cvr_navn in [('Let-Køb', 'LETKØB Bedsted'), ('7-Eleven', '7-ELEVEN Lufthavnen'),
                                 ('Coop 365discount', '365discount Ebeltoft'), ('Matas', 'MATAS 14170'),
                                 ('H&M', '829 H & M HENNES & MAURITZ A/S'),
                                 ('Joe & The Juice', 'JOE & THE JUICE - Store Kongensgade'),
                                 ('Apoteksudsalg', 'Svebølle Apotek'), ('Gasoline Grill', 'Gasoline Grill ApS')]:
            self.assertTrue(G.maerke_rx(maerke).search(cvr_navn), (maerke, cvr_navn))
        for maerke, andet in [('Netto', 'Nettolager ApS'), ('H&M', 'Thomsen Holding'), ('Matas', 'Matassen ApS'),
                              ('Coop 365discount', 'Coop Danmark A/S')]:
            self.assertFalse(G.maerke_rx(maerke).search(andet), (maerke, andet))

    def test_adressen_deles_til_dar(self):
        self.assertEqual(G.adr_dele('Ryvangs Allé 87, 2100 København Ø', '2100'), ('Ryvangs Allé', '87', '2100'))
        self.assertEqual(G.adr_dele('Rødovre Centrum 1L, 2610 Rødovre', '2610'), ('Rødovre Centrum', '1L', '2610'))
        self.assertEqual(G.adr_dele('Nørreport Centret, Nørregade 60, 7500 Holstebro', '7500'),
                         ('Nørregade', '60', '7500'))
        self.assertIsNone(G.adr_dele('Holger Drachmanns pl., 6400 Sønderborg', '6400'))
        self.assertIsNone(G.adr_dele('Ryvangs Allé 87, 2100 København Ø', ''))


class TestHusnummer(unittest.TestCase):
    """Vores stavemaade kan afvige fra DAR's (18-11-2026: 'Ryvangs Allé 87' hedder 'Ryvangs Alle 87' i DAR, og proeven
    meldte Netto som 'findes ikke i DAR'). Reserven godtager kun samme vej og praecis samme husnummer."""

    def ids(self, q, geo):
        with mock.patch.object(G.dawa, '_q', return_value=q), \
                mock.patch.object(G.RS, '_oil_geokod', return_value=(geo, None)):
            return G._husnumre('Ryvangs Allé', '87', '2900')

    def test_dar_direkte(self):
        self.assertEqual(self.ids([{'id': 'a', 'husnr': '87'}, {'id': 'b', 'husnr': '87A'}], None), ['a'])

    def test_stavevariant_via_geokodningen(self):
        hit = {'id': 'x', 'vejnavn': 'Ryvangs Alle', 'husnr': '87', 'postnr': '2900'}
        self.assertEqual(self.ids([], hit), ['x'])
        self.assertEqual(self.ids([], dict(hit, husnr='89')), [])           # husnummerfamilien: en anden adresse
        self.assertEqual(self.ids([], dict(hit, vejnavn='Ryvangsvej')), [])  # en anden vej
        self.assertEqual(self.ids([], dict(hit, postnr='2100')), [])         # et andet postnummer
        self.assertEqual(self.ids([], {k: v for k, v in hit.items() if k != 'id'}), [])
        self.assertEqual(self.ids([], None), [])

    def test_vejnoeglen(self):
        self.assertEqual(G._vej_noegle('Ryvangs Allé'), G._vej_noegle('Ryvangs Alle'))
        self.assertEqual(G._vej_noegle('Gl. Kongevej'), G._vej_noegle('Gammel Kongevej'))
        self.assertNotEqual(G._vej_noegle('Ryvangs Allé'), G._vej_noegle('Ryvangsvej'))


class TestVurdering(unittest.TestCase):
    def v(self, enheder, nye=(), fund=LUK):
        return G.vurder(fund, enheder, list(nye), idag=IDAG)

    def test_lader_og_ukendt_adresse_mangler_en_kilde(self):
        # en lader staar ikke i CVR: heller ikke en aktiv enhed med operatoerens navn paa adressen goer den 'uenig'
        kat, belaeg, fs = self.v([P('Netto Ryvangs Allé')], fund=dict(LUK, fil='superladere_dk.csv'))
        self.assertEqual((kat, fs), ('MANGLER', None))
        self.assertIn('Ladere', belaeg[0])
        kat, belaeg, fs = self.v(None)
        self.assertEqual((kat, fs), ('MANGLER', None))
        self.assertIn('DAR', belaeg[0])

    def test_aktiv_i_cvr_er_uenige(self):
        kat, belaeg, fs = self.v([P('NETTO RYVANGS ALLÉ')])
        self.assertEqual((kat, fs), ('UENIGE', None))
        self.assertIn('aktiv', belaeg[0])
        # en virksomhed (ikke en P-enhed) med kaedens navn er ikke butikken
        self.assertEqual(self.v([dict(P('Netto Holding'), type='CVR')])[0], 'MANGLER')

    def test_kun_ophoert_mangler_en_kilde(self):
        kat, belaeg, fs = self.v([P('Netto Ryvangs Allé', status='inaktiv', ophoer='2026-10-31', nu=False)])
        self.assertEqual((kat, fs), ('MANGLER', None))
        self.assertIn('ophørte 2026-10-31', belaeg[0])

    def test_ophoert_og_flyttet_efter_kaedens_liste_er_klar(self):
        ny = {'navn': 'Netto Strandvejen', 'adresse': 'Strandvejen 100, 2900 Hellerup', 'lat': 55.7300, 'lon': 12.5800}
        kat, belaeg, fs = self.v([P('Netto Ryvangs Allé', status='inaktiv', ophoer='2026-10-31', nu=False)], [ny])
        self.assertEqual((kat, fs), ('KLAR', 'SLET'))
        self.assertTrue(any('flytning' in b for b in belaeg))
        langt = dict(ny, lat=56.0)          # over FLYT_M vaek: ikke en flytning
        self.assertEqual(self.v([P('Netto', status='inaktiv', ophoer='2026-10-31', nu=False)], [langt])[0], 'MANGLER')

    def test_ny_lejer_i_samme_branche_paa_lille_adresse_er_klar(self):
        gammel = P('Netto Ryvangs Allé', status='inaktiv', ophoer='2026-10-31', nu=False)
        lejer = P('Lidl Ryvangs Allé', start='2026-11-10', pnr=1000000002, brancher=('471120',))
        self.assertEqual(self.v([gammel, lejer])[:3:2], ('KLAR', 'SLET'))
        # anden branchegruppe (frisoer) taeller ikke
        self.assertEqual(self.v([gammel, dict(lejer, brancher=['962100'])])[0], 'MANGLER')
        # startet laenge foer ophoeret: en nabo, ikke en afloeser
        self.assertEqual(self.v([gammel, dict(lejer, start='2020-01-01')])[0], 'MANGLER')
        # et center med mange aktive enheder: en ny lejer siger intet
        mange = [P(f'Butik {i}', pnr=1000000100 + i, brancher=('477110',)) for i in range(G.SMAA_ADR)]
        self.assertEqual(self.v([gammel, lejer] + mange)[0], 'MANGLER')

    def test_bilhandlen_er_een_branche_paa_tvaers_af_afdelinger(self):
        # DB25: brugtvognshandel (46.71), vaerksted (95.31) og leasing (77.11) afloeser en bilforhandler (47.81) i samme
        # branche (oprydningen 19-11-2026: Viborg Autohandel, 467100, stod under «intet i branchen»)
        gammel = P('Netto Ryvangs Allé', status='inaktiv', ophoer='2026-10-31', nu=False, brancher=('478100',))
        for kode in ('467100', '953190', '771100'):
            lejer = P('Nye Biler ApS', start='2026-11-10', pnr=1000000002, brancher=(kode,))
            self.assertEqual(self.v([gammel, lejer])[:3:2], ('KLAR', 'SLET'), kode)
        # men et vaerksted efter en dagligvarebutik er ikke samme branche, og en frisoer efter en bilforhandler heller ikke
        vaerksted = P('Nye Biler ApS', start='2026-11-10', pnr=1000000002, brancher=('953190',))
        self.assertEqual(self.v([dict(gammel, brancher=['471120']), vaerksted])[0], 'MANGLER')
        self.assertEqual(self.v([gammel, dict(vaerksted, brancher=['962100'])])[0], 'MANGLER')
        self.assertEqual(G._grupper(['478100', '953190']), {'47', '95', 'bil'})
        self.assertEqual(G._grupper(['471120']), {'47'})

    def test_kommende_ophoer_er_ikke_uenige(self):
        kat, belaeg, fs = self.v([P('MATAS 14170', ophoer='2026-12-11', brancher=('477500',))],
                                 fund=dict(LUK, maerke='Matas', navn='Matas'))
        self.assertEqual((kat, fs), ('MANGLER', None))
        self.assertIn('lukker', belaeg[0])
        # en kommende ophoersdato er ikke en lukning endnu - heller ikke naar kaedens liste har en ny butik i naerheden
        ny = {'navn': 'Matas Ny', 'adresse': 'Strandvejen 100, 2900 Hellerup', 'lat': 55.7300, 'lon': 12.5800}
        self.assertEqual(self.v([P('MATAS 14170', ophoer='2026-12-11', brancher=('477500',))], [ny],
                                fund=dict(LUK, maerke='Matas', navn='Matas'))[0], 'MANGLER')

    def test_flyttet_enhed_plus_kaedens_nye_adresse_er_klar(self):
        ny = {'navn': 'Netto Strandvejen', 'adresse': 'Strandvejen 100, 2900 Hellerup', 'lat': 55.7300, 'lon': 12.5800}
        flyttet = P('Netto Ryvangs Allé', nu=False)
        self.assertEqual(self.v([flyttet], [ny])[0], 'KLAR')
        self.assertEqual(self.v([flyttet])[0], 'MANGLER')

    def test_intet_i_cvr_mangler_en_kilde(self):
        kat, belaeg, fs = self.v([P('Bager Jensen', brancher=('107110',))])
        self.assertEqual((kat, fs), ('MANGLER', None))
        self.assertIn('ingen enhed', belaeg[0])

    def test_selskabets_navn_genkender_enheden(self):
        """19-11-2026: Havlykke Biler ApS' eneste P-enhed hed stadig «Sand & Sten ApS». Selskabets navn ('firma')
        genkender enheden - som aktiv (i orden), som ophoert (en lukning) og ikke som en ny lejer i stedet for sig selv."""
        r = ['Havlykke Biler', 'Havlykke Biler', 'Vejlevej 16B, 7000 Fredericia', '7000', 'Fredericia']
        hit = G.navne_hit(r, 'Vejlevej')
        fund = {'maerke': r[0], 'fil': 'pladskraevende_dk.csv', 'navn': r[1], 'adresse': r[2], 'lat': 55.57,
                'lon': 9.72}
        egen = P('Sand & Sten ApS', firma='Havlykke Biler ApS', brancher=('478100',))
        kat, belaeg, _ = G.vurder(fund, [egen], [], IDAG, hit)
        self.assertEqual(kat, 'UENIGE')
        self.assertIn('«Sand & Sten ApS» (selskabet «Havlykke Biler ApS»)', belaeg[0])
        # genkender enhedens eget navn den, gentages selskabet ikke
        belaeg = G.vurder(fund, [dict(egen, navn='Havlykke Biler ApS')], [], IDAG, hit)[1]
        self.assertIn('«Havlykke Biler ApS» er aktiv', belaeg[0])
        self.assertNotIn('selskabet', belaeg[0])
        lukket = dict(egen, status='inaktiv', ophoer='2026-10-01', nu=False)
        kat, belaeg, _ = G.vurder(fund, [lukket], [], IDAG, hit)
        self.assertEqual(kat, 'MANGLER')
        self.assertIn('(selskabet «Havlykke Biler ApS») ophørte 2026-10-01', belaeg[0])
        # et andet selskab med samme gamle enhedsnavn er ikke forretningen
        self.assertEqual(G.vurder(fund, [dict(egen, firma='Sand & Sten ApS')], [], IDAG, hit)[1][0][:24],
                         'CVR har ingen enhed med ')
        # selskabets nye enhed paa adressen er ikke 'en ny forretning i samme branche' efter dens egen gamle enhed
        ny = P('Havlykke Biler Fredericia', firma='Havlykke Biler ApS', start='2026-10-05', pnr=1000000002,
               brancher=('478100',))
        anden = dict(ny, navn='Nye Biler ApS', firma='Nye Biler ApS')
        self.assertEqual(G.vurder(fund, [lukket, dict(ny, navn='X ApS')], [], IDAG, hit)[0], 'UENIGE')
        # (en aktiv enhed med en kommende ophoersdato er ikke 'aktiv paa adressen', men heller ikke en afloeser)
        self.assertEqual(G.vurder(fund, [lukket, dict(ny, navn='X ApS', ophoer='2026-12-31')], [], IDAG, hit)[0],
                         'MANGLER')
        self.assertEqual(G.vurder(fund, [lukket, anden], [], IDAG, hit)[0], 'KLAR')
        # uden 'firma' (aeldre data) virker alt som foer
        self.assertEqual(G._egen({'navn': 'Havlykke Biler ApS'}, hit), True)
        self.assertEqual(G._egen({'navn': 'Sand & Sten ApS'}, hit), False)


class TestRaekkerUdenKilde(unittest.TestCase):
    def test_navnet_genkendes(self):
        def hit(maerke, navn, cvr, by='Holstebro', vej='Viborgvej'):
            return G.navne_hit([maerke, navn, f'{vej} 1, 7500 {by}', '7500', by], vej)(cvr)
        self.assertTrue(hit('MK Biler', 'MK Biler', 'M.K. Biler v/Max Ørskov Kristensen'))     # enkeltbogstaver
        self.assertTrue(hit('Hobbyhaven', 'Hobbyhaven', 'HOBBY-HAVEN ApS'))                    # skrevet sammen
        self.assertTrue(hit('Ecco', 'Ecco Aarhus C', 'KRM Ryesgade', by='Aarhus C'))           # Eccos KRM-navne
        self.assertTrue(hit('Andersen & Martini', 'Andersen & Martini A/S - Glostrup', 'A&M Biler Glostrup'))
        self.assertTrue(hit('Auto Group Nordvest', 'Auto Group Nordvest – Volkswagen', 'AGN - Lemvig'))
        self.assertFalse(hit('Andersen & Martini', 'Andersen & Martini A/S', 'AM Bilsalg ApS'))
        self.assertTrue(hit('Skive Bilhus', 'Skive Bilhus ApS', 'Skive Bilhus ApS', by='Skive'))
        self.assertFalse(hit('Skive Bilhus', 'Skive Bilhus ApS', 'LS AUTOTEKNIK ApS', by='Skive'))
        self.assertFalse(hit('Skive Bilhus', 'Skive Bilhus ApS', 'Skive Autoservice', by='Skive'))
        self.assertFalse(hit('Havlykke Biler', 'Havlykke Biler', 'Sand & Sten ApS'))
        self.assertFalse(hit('Holstebro Biler', 'Holstebro Biler', 'Viborgvej Biler ApS'))     # by og vej taeller ikke
        self.assertFalse(hit('Peugeot', 'Peugeot Holstebro', 'Jensen Bilsalg'))
        self.assertFalse(hit('AM Bilhus', 'AM Bilhus', 'Hammer Biler ApS'))   # korte ord kun som hele ord ('am' i 'hammer')
        # selskabsformen er ikke en del af navnet
        self.assertTrue(hit('Skive Bilhus', 'Skive Bilhus ApS', 'SKIVE BILHUS A/S', by='Skive'))
        # byen som afdelingsbetegnelse (19-11-2026): to ord uden byen og selskabsformen er nok ...
        self.assertTrue(hit('Bil & Co', 'Bil & Co. A/S - Haderslev', 'BIL & CO. A/S', by='Haderslev',
                            vej="Christian X's Vej"))
        self.assertFalse(hit('Bil & Co', 'Bil & Co. A/S - Haderslev', 'Haderslev Biler A/S', by='Haderslev'))
        # ... men ét ord er ikke ('Skive Bilhus' er ikke enhver 'Bilhus'), og selskabsformen taeller ikke som et ord
        self.assertFalse(hit('Skive Bilhus', 'Skive Bilhus ApS', 'BILHUS ApS', by='Skive'))
        self.assertFalse(hit('Bilhuset', 'Bilhuset A/S - Kolding', 'Bilhuset Syd A/S', by='Kolding'))
        self.assertFalse(hit('', 'A/S', 'Netto ApS'))           # et navn uden ord rammer intet
        # navne med belaeg fra 19-11-2026 (NAVN_ALIAS): handelsnavn, moderselskabets butiksselskab og CVR's stavemaade
        self.assertTrue(hit('RK Biler', 'RK Biler', 'R.Koch Automobiler ApS', by='Brørup', vej='Esbjergvej'))
        self.assertFalse(hit('RK Biler', 'RK Biler', 'R.Koch Holding ApS', by='Brørup', vej='Esbjergvej'))
        self.assertTrue(hit('BoConcept', 'BoConcept Ishøj', 'BC Commercial A/S', by='Ishøj', vej='Industridalen'))
        self.assertTrue(hit('Staurbyskov Havecenter', 'Staurbyskov Havecenter', 'STAVRBYSKOV HAVECENTER ApS',
                            by='Middelfart', vej='Staurbyskovvej'))
        self.assertTrue(hit('Storstrøms Camping Service', 'Storstrøms Camping Service', 'Storstrøm Camping Service',
                            by='Nørre Alslev', vej='Nykøbingvej'))
        self.assertFalse(hit('Storstrøms Camping Service', 'Storstrøms Camping Service', 'Storstrøm Biler ApS',
                             by='Nørre Alslev', vej='Nykøbingvej'))

    def test_hver_raekke_een_gang_paa_fire_uger(self):
        rk = [('plads', ['M', f'Navn {i}', f'Vej {i}, 1000 By', '1000', 'By']) for i in range(200)]
        uger = [G.uge_udvalg(rk, u) for u in range(47, 47 + G.DELE)]
        self.assertEqual(sorted(len(u) for u in uger)[0] > 0, True)
        alle = [r[1][1] for u in uger for r in u]
        self.assertEqual(sorted(alle), sorted(r[1][1] for r in rk))      # alle med, ingen to gange
        self.assertEqual(G.uge_udvalg(rk, 47), G.uge_udvalg(rk, 47 + G.DELE))

    def test_udvalget_af_raekker(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        hoved = ['Mærke', 'Navn', 'Adresse', 'Postnr', 'By', 'Latitude', 'Longitude']
        indhold = {'pladskraevende_dk.csv': [['Bilhuset X', 'Bilhuset X', 'Vej 1, 7500 Holstebro', '7500', 'Holstebro', '56', '8.6'],
                                             ['Bygma', 'Bygma Vejle', 'Vej 2, 7100 Vejle', '7100', 'Vejle', '55.7', '9.5']],
                   'tankstationer_dk.csv': [['OK', 'OK X', 'Vej 3, 8000 Aarhus C', '8000', 'Aarhus C', '56.1', '10.2', ''],
                                            ['CNG/biogas', 'CNG X', 'Vej 4, 4600 Køge', '4600', 'Køge', '55.4', '12.1', '']],
                   'dagligvarer_dk.csv': [['Netto', 'Netto X', 'Vej 5, 2100 København Ø', '2100', 'København Ø', '55.7', '12.5']],
                   'udvalgsvarer_dk.csv': [['H&M', 'H&M X', 'Vej 6, 7400 Herning', '7400', 'Herning', '56.1', '8.9']],
                   'fastfood_kaeder_dk.csv': [], 'superladere_dk.csv': [['Stella', 'S', 'Vej 7, 8000 Aarhus C', '8000',
                                                                          'Aarhus C', '300', 'CCS', '4', '56.1', '10.2', '']]}
        for fn, rows in indhold.items():
            with open(os.path.join(d, fn), 'w', encoding='utf-8-sig', newline='') as f:
                import csv as _csv
                _csv.writer(f).writerows([hoved] + rows)
        with mock.patch.object(G, 'OUT', d):
            navne = sorted(r[1] for _, r in G.uden_kilde_raekker())
        # Bygma og Netto har en henter, OK hentes af refresh_data, H&M er i registertjekket, Stella er en lader
        self.assertEqual(navne, ['Bilhuset X', 'CNG X'])


class TestHistorik(unittest.TestCase):
    def test_uger_paa_listen(self):
        h = G.opdater_historik({}, {'a'}, IDAG)
        self.assertEqual(G.uger(h, 'a', IDAG), 1)
        h = {'a': {'foerst': '2026-11-02', 'sidst': '2026-11-16'}, 'b': {'foerst': '2026-10-01', 'sidst': '2026-11-16'},
             'c': {'foerst': '2026-08-01', 'sidst': '2026-09-01'}, 'd': {'foerst': '2026-09-01', 'sidst': '2026-10-01'}}
        ny = G.opdater_historik(h, {'a', 'd'}, IDAG)
        self.assertEqual(G.uger(ny, 'a', IDAG), 4)                  # 2., 9., 16. og 23. november
        self.assertIn('b', ny)                                       # ikke set i dag, men for nylig: huskes
        self.assertNotIn('c', ny)                                    # ikke set i over GLEM_UGER: glemt
        self.assertEqual(ny['d']['foerst'], IDAG.isoformat())        # vaek i over to uger: et nyt fund
        self.assertEqual(ny['a']['sidst'], IDAG.isoformat())


class TestFundfiler(unittest.TestCase):
    def test_refresh_skriver_fundene(self):
        r = ['Netto', 'Netto Ryvangs Allé', 'Ryvangs Allé 87, 2100 København Ø', '2100', 'København Ø', '55.721', '12.576']
        self.assertEqual(R._fund_post('netto', 'dagligvarer_dk.csv', r),
                         {'henter': 'netto', 'fil': 'dagligvarer_dk.csv', 'maerke': 'Netto', 'navn': 'Netto Ryvangs Allé',
                          'adresse': 'Ryvangs Allé 87, 2100 København Ø', 'postnr': '2100', 'lat': 55.721, 'lon': 12.576})
        lade = ['Clever', 'Clever X', 'Vej 1, 8000 Aarhus C', '8000', 'Aarhus C', '300', 'CCS', '4', '56.1', '10.2', '']
        self.assertEqual(R._fund_post('clever', 'superladere_dk.csv', lade)['lat'], 56.1)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        R._skriv_fund(os.path.join(d, 'f.json'), True, [{'navn': 'x'}], [], {'b', 'a'})
        j = json.load(open(os.path.join(d, 'f.json'), encoding='utf-8'))
        self.assertEqual((j['apply'], j['fejlede_hentere'], j['mulige_lukninger']), (True, ['a', 'b'], [{'navn': 'x'}]))

    def test_registret_skriver_fundene(self):
        p = {'navn': 'JOE & THE JUICE - X', 'gade': 'Vej 1', 'postnr': '1000', 'by': 'Kbh', 'pnr': 5, 'lat': 55.0,
             'lon': 12.0}
        k = K._fund_kaede('Joe & The Juice', 'smiley-registret', 'fastfood_kaeder_dk.csv', [(p, 400)],
                          [(('Joe & The Juice Y', 'Vej 2, 1000 Kbh', '1000', 55.1, 12.1), 600)])
        self.assertEqual(k['nye'][0]['pnr'], 5)
        self.assertEqual(k['lukkede'][0], {'maerke': 'Joe & The Juice', 'navn': 'Joe & The Juice Y',
                                           'adresse': 'Vej 2, 1000 Kbh', 'postnr': '1000', 'lat': 55.1, 'lon': 12.1,
                                           'afstand': 600})


class TestKoerslen(unittest.TestCase):
    """main() mod fundfiler i en mappe og et stubbet CVR-opslag."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        p = mock.patch.object(G, 'OUT', self.d)
        p.start(); self.addCleanup(p.stop)
        self.uden = []               # raekker uden egen kilde i denne test (se test_rullende_cvr_kontrol)
        p = mock.patch.object(G, 'uden_kilde_raekker', side_effect=lambda: self.uden)
        p.start(); self.addCleanup(p.stop)

    def skriv(self, navn, data):
        json.dump(data, open(os.path.join(self.d, navn), 'w', encoding='utf-8'), ensure_ascii=False)

    def koer(self, enheder):
        with mock.patch.object(G, 'enheder_paa_adresse', side_effect=lambda v, h, p: enheder.get((v, h, p))), \
                mock.patch('builtins.print'):
            return G.main()

    def test_liste_forslag_og_historik(self):
        flyt = dict(LUK, henter='netto', navn='Netto Ny', adresse='Strandvejen 100, 2900 Hellerup', lat=55.73,
                    lon=12.58)
        self.skriv(G.RETAIL_FUND, {'koersel': 'x', 'apply': True, 'fejlede_hentere': [],
                                   'mulige_lukninger': [dict(LUK, henter='netto'),
                                                        dict(LUK, henter='netto', navn='Netto B',
                                                             adresse='Bvej 2, 2100 København Ø')],
                                   'nye': [flyt]})
        self.skriv(G.REGISTER_FUND, {'koersel': 'x', 'fejlede': [], 'kaeder': {'H&M': {
            'kilde': 'CVR', 'fil': 'udvalgsvarer_dk.csv',
            'nye': [{'navn': '790 Hennes & Mauritz', 'gade': 'Kordilgade 28', 'postnr': '4400', 'by': 'Kalundborg',
                     'pnr': 1016901276, 'lat': 55.68, 'lon': 11.09, 'afstand': 34820}],
            'lukkede': []}}})
        rk = self.koer({('Ryvangs Allé', '87', '2100'): [P('Netto Ryvangs Allé', status='inaktiv',
                                                            ophoer='2026-10-31', nu=False)],
                        ('Bvej', '2', '2100'): [P('NETTO B')]})
        self.assertEqual(rk, 0)
        tekst = open(os.path.join(self.d, G.RAPPORT), encoding='utf-8').read()
        self.assertIn('1 klar til godkendelse · 1 hvor kilderne er uenige · 1 der mangler en kilde', tekst)
        self.assertLess(tekst.index('KLAR TIL GODKENDELSE'), tekst.index('KILDERNE ER UENIGE'))
        self.assertLess(tekst.index('KILDERNE ER UENIGE'), tekst.index('MANGLER EN KILDE'))
        fs = json.load(open(os.path.join(self.d, G.FORSLAG), encoding='utf-8'))
        self.assertEqual(len(fs), 1)
        self.assertEqual((fs[0]['nr'], fs[0]['handling'], fs[0]['fil'], fs[0]['fra']),
                         (1, 'fjern', 'dagligvarer_dk.csv',
                          {'Mærke': 'Netto', 'Navn': 'Netto Ryvangs Allé', 'Adresse': LUK['adresse']}))
        self.assertIn('flytning', fs[0]['kilder'])
        h = json.load(open(os.path.join(self.d, G.HISTORIK), encoding='utf-8'))
        self.assertEqual(len(h), 3)

    def test_registerfund_bruger_ikke_kaedens_nye_butikker(self):
        """Et registerfund (de spaerrede kaeder) kan ikke faa sin anden kilde fra kaedernes lister: registret og CVR er
        samme kilde, og en ny butik fra en anden henter med samme maerke er ikke kaedens svar paa netop denne."""
        self.skriv(G.RETAIL_FUND, {'mulige_lukninger': [], 'nye': [
            {'henter': 'x', 'fil': 'udvalgsvarer_dk.csv', 'maerke': 'H&M', 'navn': 'H&M Ny', 'postnr': '8660',
             'adresse': 'Adelgade 1, 8660 Skanderborg', 'lat': 56.0286, 'lon': 9.9346}]})
        self.skriv(G.REGISTER_FUND, {'kaeder': {'H&M': {'kilde': 'CVR', 'fil': 'udvalgsvarer_dk.csv', 'nye': [],
            'lukkede': [{'maerke': 'H&M', 'navn': 'H&M Skanderborg', 'adresse': 'Adelgade 65, 8660 Skanderborg',
                         'postnr': '8660', 'lat': 56.0335, 'lon': 9.9317, 'afstand': 575}]}}})
        self.assertEqual(self.koer({('Adelgade', '65', '8660'): [P('877 Hennes & Mauritz', status='inaktiv',
                                                                     ophoer='2026-10-01', nu=False)]}), 0)
        self.assertEqual(json.load(open(os.path.join(self.d, G.FORSLAG), encoding='utf-8')), [])
        self.assertIn('0 klar til godkendelse', open(os.path.join(self.d, G.RAPPORT), encoding='utf-8').read())

    def test_rullende_cvr_kontrol(self):
        """Raekker uden egen kilde (18-11-2026): kun en aendring i CVR kommer paa listen - forretningens enhed er
        ophoert. En aktiv enhed med navnet er i orden; en anden forretning paa adressen kan CVR ikke afgoere."""
        def r(navn, adr):
            return ['Bilforhandler', navn, adr, '6000', 'Kolding', '55.49', '9.47']
        self.uden = [('pladskraevende_dk.csv', r('Lyngsø Biler', 'Haderslevvej 117, 6000 Kolding')),
                     ('pladskraevende_dk.csv', r('Karvil Biler', 'Faaborgvej 149, 6000 Kolding')),
                     ('pladskraevende_dk.csv', r('Havlykke Biler', 'Vejlevej 16B, 6000 Kolding')),
                     ('pladskraevende_dk.csv', r('Bøgely Biler', 'Engvej 2, 6000 Kolding')),
                     ('pladskraevende_dk.csv', r('Kirkeby Biler', 'Engvej 4, 6000 Kolding'))]
        self.skriv(G.RETAIL_FUND, {'mulige_lukninger': [], 'nye': []})
        self.skriv(G.REGISTER_FUND, {'kaeder': {}})
        enh = {('Haderslevvej', '117', '6000'): [P('Lyngsø auto v/ivan lyngsø', status='inaktiv', ophoer='2026-09-04',
                                                   nu=False, brancher=('478100',))],
               ('Faaborgvej', '149', '6000'): [P('KARVIL BILER A/S', brancher=('478100',))],
               # 19-11-2026: P-enheden hed «Sand & Sten ApS», selskabet Havlykke Biler ApS - aktiv, altsaa i orden
               ('Vejlevej', '16B', '6000'): [P('Sand & Sten ApS', firma='Havlykke Biler ApS', brancher=('478100',))],
               # en ophoert enhed med et gammelt navn er forretningens, naar selskabet har forretningens navn ...
               ('Engvej', '2', '6000'): [P('Gamle Navn ApS', firma='Bøgely Biler ApS', status='inaktiv',
                                           ophoer='2026-10-15', nu=False, brancher=('478100',))],
               # ... men ikke, naar selskabet hedder noget andet
               ('Engvej', '4', '6000'): [P('Gamle Navn ApS', firma='Gamle Navn ApS', status='inaktiv',
                                           ophoer='2026-10-15', nu=False, brancher=('478100',))]}
        with mock.patch.object(G, 'uge_udvalg', side_effect=lambda raekker, uge: raekker):
            self.assertEqual(self.koer(enh), 0)
        tekst = open(os.path.join(self.d, G.RAPPORT), encoding='utf-8').read()
        self.assertIn('Rækker uden egen kilde: 5 af 5 slået op i CVR', tekst)
        self.assertIn('2 med en ændring i CVR', tekst)
        self.assertIn('Lyngsø Biler', tekst)
        self.assertIn('ophørte 2026-09-04', tekst)
        self.assertIn('CVR-tjek, ingen egen liste', tekst)
        self.assertIn('Bøgely Biler', tekst)
        self.assertIn('«Gamle Navn ApS» (selskabet «Bøgely Biler ApS») ophørte 2026-10-15', tekst)
        self.assertNotIn('Karvil', tekst)
        self.assertNotIn('Havlykke', tekst)
        self.assertNotIn('Kirkeby', tekst)

    def test_cvr_opslaget_henter_selskabets_navn(self):
        """enheder_paa_adresse mod et stubbet Datafordeler-svar: P-enheden faar selskabets navn ('firma') via
        tilknyttetVirksomhedsCVRNummer, ogsaa naar enhedens eget navn er et gammelt (Havlykke Biler, 19-11-2026)."""
        def sider(entitet, where, felter, tid):
            if entitet == 'CVR_Adressering':
                return [{'CVREnhedsId': 'p1'}]
            if entitet == 'CVR_Produktionsenhed':
                self.assertIn('tilknyttetVirksomhedsCVRNummer', felter)
                return [{'id': 'p1', 'pNummer': 1027673526, 'status': 'aktiv', 'produktionsenhedStartdato': '2021-10-27',
                         'produktionsenhedOphoersdato': None, 'tilknyttetVirksomhedsCVRNummer': 42791385}]
            if entitet == 'CVR_Virksomhed':
                return [{'id': 'v1', 'CVRNummer': 42791385}] if 'CVRNummer' in where else []
            if entitet == 'CVR_Navn':
                return ([{'CVREnhedsId': 'v1', 'vaerdi': 'Havlykke Biler ApS'}] if '"v1"' in where
                        else [{'CVREnhedsId': 'p1', 'vaerdi': 'Sand & Sten ApS'}])
            if entitet == 'CVR_Branche':
                return [{'CVREnhedsId': 'p1', 'vaerdi': '478100'}]
            raise AssertionError(entitet)
        with mock.patch.object(G, '_husnumre', return_value=['h1']), \
                mock.patch.object(G.dawa, '_alle', return_value=[{'id_lokalId': 'a1'}]), \
                mock.patch.object(G, '_sider', side_effect=sider):
            e = G.enheder_paa_adresse('Vejlevej', '16B', '7000')
        self.assertEqual(len(e), 1)
        self.assertEqual((e[0]['navn'], e[0]['firma'], e[0]['pnr'], e[0]['nu']),
                         ('Sand & Sten ApS', 'Havlykke Biler ApS', 1027673526, True))

    def test_manglende_eller_gammel_fundfil_er_en_fejl(self):
        self.skriv(G.RETAIL_FUND, {'mulige_lukninger': [], 'nye': []})
        gammel = time.time() - (G.GAMMEL_FUND_TIMER + 1) * 3600
        os.utime(os.path.join(self.d, G.RETAIL_FUND), (gammel, gammel))
        self.assertEqual(self.koer({}), 2)
        tekst = open(os.path.join(self.d, G.RAPPORT), encoding='utf-8').read()
        self.assertIn(f'{G.RETAIL_FUND} er over', tekst)
        self.assertIn(f'{G.REGISTER_FUND} mangler', tekst)

    def test_fejl_i_cvr_opslaget_lyser_roedt(self):
        self.skriv(G.RETAIL_FUND, {'mulige_lukninger': [dict(LUK, henter='netto')], 'nye': []})
        self.skriv(G.REGISTER_FUND, {'kaeder': {}})
        with mock.patch.object(G, 'enheder_paa_adresse', side_effect=RuntimeError('Datafordeleren svarer ikke')), \
                mock.patch('builtins.print'):
            self.assertEqual(G.main(), 2)
        self.assertIn('CVR/DAR-opslag fejlede', open(os.path.join(self.d, G.RAPPORT), encoding='utf-8').read())


    def test_tidsbudgettet_skriver_listen_og_tager_fundene_foerst(self):
        """23-11-2026 ramte trinnet GitHubs 15 min, og listen blev aldrig skrevet. Naar budgettet er brugt, startes ingen
        nye opslag: listen skrives alligevel, ugens fund er slaaet op foerst, og resten meldes under FEJL."""
        self.uden = [('pladskraevende_dk.csv', ['Bilforhandler', f'Biler {i}', f'Engvej {i}, 6000 Kolding', '6000',
                                                'Kolding', '55.49', '9.47']) for i in range(1, 13)]
        self.skriv(G.RETAIL_FUND, {'koersel': 'x', 'apply': True, 'fejlede_hentere': [],
                                   'mulige_lukninger': [dict(LUK, henter='netto')], 'nye': []})
        self.skriv(G.REGISTER_FUND, {'kaeder': {}})
        def langsom(v, h, p):
            time.sleep(0.25)
            return [P('Netto Ryvangs Allé', status='inaktiv', ophoer='2026-10-31', nu=False)] if v == 'Ryvangs Allé' \
                else [P(f'Biler {h}', brancher=('478100',))]
        t0 = time.time()
        with mock.patch.object(G, 'TIDSBUDGET_S', 0.3), mock.patch.object(G, 'TRAADE', 2), \
                mock.patch.object(G, 'uge_udvalg', side_effect=lambda raekker, uge: raekker), \
                mock.patch.object(G, 'enheder_paa_adresse', side_effect=langsom), mock.patch('builtins.print'):
            self.assertEqual(G.main(), 2)
        self.assertLess(time.time() - t0, 2.5)           # uden budgettet: 13 opslag a 0,25 s paa 2 traade = 1,6 s+
        tekst = open(os.path.join(self.d, G.RAPPORT), encoding='utf-8').read()
        self.assertNotIn('BLEV IKKE FÆRDIG', tekst)
        self.assertIn('tidsbudgettet', tekst)
        n = int(re.search(r'Rækker uden egen kilde: (\d+) af 12 slået op', tekst).group(1))
        self.assertLess(n, 12)
        self.assertIn(f'{12 - n} rækker uden egen kilde, som tages igen', tekst)
        # fundet stod foerst i koeen og er vurderet paa CVR-svaret, ikke meldt som 'naaede ikke'
        self.assertIn('Netto Ryvangs Allé', tekst)
        self.assertIn('ophørte 2026-10-31', tekst)
        self.assertNotIn('nåede ikke at køre', tekst)

    def test_opslagene_koerer_parallelt(self):
        aktive, top, kald, laas = [0], [0], [0], threading.Lock()
        def opslag(v, h, p):
            with laas:
                kald[0] += 1
                aktive[0] += 1
                top[0] = max(top[0], aktive[0])
            time.sleep(0.05)
            with laas:
                aktive[0] -= 1
            if h == '3':
                raise RuntimeError('Datafordeleren svarer ikke')
            return [P(f'X {h}')]
        adr = [('Engvej', str(i), '6000') for i in range(1, 9)] + [('Engvej', '1', '6000')]
        with mock.patch.object(G, 'enheder_paa_adresse', side_effect=opslag):
            svar, fejl, ikke = G.slaa_op(adr, traade=4)
        self.assertGreaterEqual(top[0], 2)
        self.assertEqual((len(svar), list(fejl), ikke), (7, [('Engvej', '3', '6000')], []))
        self.assertIn('RuntimeError: Datafordeleren svarer ikke', fejl[('Engvej', '3', '6000')])
        self.assertEqual(svar[('Engvej', '1', '6000')][0]['navn'], 'X 1')
        self.assertEqual(kald[0], 8)                                          # dubletten slaas kun op een gang

    def test_fund_der_ikke_blev_naaet(self):
        self.skriv(G.RETAIL_FUND, {'koersel': 'x', 'apply': True, 'fejlede_hentere': [],
                                   'mulige_lukninger': [dict(LUK, henter='netto')], 'nye': []})
        self.skriv(G.REGISTER_FUND, {'kaeder': {}})
        with mock.patch.object(G, 'slaa_op', side_effect=lambda adr, frist=None, traade=None:
                               ({}, {}, list(dict.fromkeys(adr)))), mock.patch('builtins.print'):
            self.assertEqual(G.main(), 2)
        tekst = open(os.path.join(self.d, G.RAPPORT), encoding='utf-8').read()
        self.assertIn('nåede ikke at køre denne uge', tekst)
        self.assertIn('1 af 1 adresser blev ikke slået op (1 af ugens fund', tekst)


class TestWorkflow(unittest.TestCase):
    def test_trinnets_graense_ligger_over_tidsbudgettet(self):
        t = open(os.path.join(hjaelp.ROD, '.github', 'workflows', 'weekly-refresh.yml'), encoding='utf-8').read()
        trin = t[t.index('id: gennemgang'):t.index('run: python3 ugentlig_gennemgang.py')]
        graense = int(re.search(r'timeout-minutes:\s*(\d+)', trin).group(1))
        self.assertGreaterEqual(graense * 60, G.TIDSBUDGET_S + 5 * 60)

    def test_trinnet_koerer_og_listen_committes(self):
        t = open(os.path.join(hjaelp.ROD, '.github', 'workflows', 'weekly-refresh.yml'), encoding='utf-8').read()
        self.assertIn('python3 refresh_retail.py --apply --fund retail_refresh_fund.json', t)
        self.assertIn('python3 kaede_register_tjek.py --fund kaede_register_fund.json', t)
        self.assertIn('run: python3 ugentlig_gennemgang.py', t)
        self.assertIn('id: gennemgang', t)
        self.assertIn('gennemgang=${{ steps.gennemgang.outcome }}', t)
        commit = t[t.index('Commit frisk feed'):]
        for f in (G.RAPPORT, G.FORSLAG, G.HISTORIK):
            self.assertIn(f, commit)
        # gennemgangen koerer efter de to trin, der skriver fundene
        self.assertLess(t.index('--fund retail_refresh_fund.json'), t.index('run: python3 ugentlig_gennemgang.py'))
        self.assertLess(t.index('--fund kaede_register_fund.json'), t.index('run: python3 ugentlig_gennemgang.py'))
        gi = open(os.path.join(hjaelp.ROD, '.gitignore'), encoding='utf-8').read()
        self.assertIn(G.RETAIL_FUND, gi)
        self.assertIn(G.REGISTER_FUND, gi)


if __name__ == '__main__':
    unittest.main()
