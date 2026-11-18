"""Ugentlig gennemgang (18-11-2026, brugerens valg): ugens mulige lukninger og registertjekkets fund, slaaet op i CVR og
sorteret til godkendelse. Botten sletter aldrig selv. Testene koerer de rigtige funktioner; CVR-opslaget er stubbet."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # noqa: F401  (repo-roden paa sys.path og nettet spaerret)

import datetime
import json
import shutil
import tempfile
import time
import unittest
from unittest import mock

import kaede_register_tjek as K
import refresh_retail as R
import ugentlig_gennemgang as G

IDAG = datetime.date(2026, 11, 23)
LUK = {'maerke': 'Netto', 'fil': 'dagligvarer_dk.csv', 'navn': 'Netto Ryvangs Allé',
       'adresse': 'Ryvangs Allé 87, 2100 København Ø', 'postnr': '2100', 'lat': 55.7210, 'lon': 12.5760}


def P(navn, status='aktiv', start='2010-01-01', ophoer=None, brancher=('471130',), nu=True, pnr=1000000001):
    return {'type': 'P', 'pnr': pnr, 'navn': navn, 'status': status, 'start': start, 'ophoer': ophoer,
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


class TestWorkflow(unittest.TestCase):
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
