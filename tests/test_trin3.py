"""Trin 3 (18-11-2026): bilmaerkernes forhandlerlister, KUN RAPPORT (brugerens valg). Del 1 koerer de RIGTIGE hentere
mod stubbe af kildernes former 18-11-2026 og proever vagterne (rene vaerksteder, Nuuk/Tórshavn, '(Kun værksted)',
kappede lister). Del 2 koerer refresh_retail.main() med en bilhenter og proever, at listen holdes op mod ALLE
bilraekker paa afstand, uanset Mærke, at kun salgssteder taeller, at havecentre og kaeder ikke 'daekker' et
salgssted, og at intet skrives."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # noqa: F401  (repo-roden paa sys.path og nettet spaerret)

import contextlib
import csv
import html
import io
import json
import shutil
import tempfile
import unittest
from unittest import mock

import refresh_retail as R
import retail_sources as RS
from test_trin1 import _Rent, _sider, _dar
from test_trin2 import _json_stub
from test_refresh_retail import HOVED, butik, post, nord, tal, AALBORG, ODENSE, VEJLE, KOLDING, RIBE

PLADS = 'pladskraevende_dk.csv'


def _dealer_map(dealers):
    return f'<div><dealer-map :dealers="{html.escape(json.dumps(dealers, ensure_ascii=False))}" gmaps-api-key="x">'


# ------------------------------------------------------------------------------------------------ Semler
class TestSemler(_Rent):
    def _f(self, navn, deps):
        return {'name': navn, 'isDealer': any(d[0] == 'Salgsafdeling' for d in deps), 'departments': [
            {'departmentTypeName': t, 'address': a, 'zipcode': pn, 'city': by, 'latitude': la, 'longitude': lo}
            for t, a, pn, by, la, lo in deps]}

    def test_salgsafdeling_er_salg_andet_er_vaerksted(self):
        side = _dealer_map([
            self._f('Bilhuset Præstø A/S', [('Værksted', 'Jernbanevej 4 - 6', '4720', 'Præstø', 55.122, 12.036)]),
            self._f('Škoda Hobro', [('Værksted', 'Erhvervsparken 6', '9500', 'Hobro', 56.64, 9.79),
                                    ('Salgsafdeling', 'Erhvervsparken 6', '9500', 'Hobro', 56.64, 9.79)])])
        with mock.patch.object(RS, '_text', new=_sider({RS.BIL_SEMLER['Škoda'][0]: side})), \
                mock.patch.dict(RS.BIL_SEMLER, {'Škoda': (RS.BIL_SEMLER['Škoda'][0], (1, 5))}):
            ud = RS.bil_skoda()
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['salg']) for r in ud],
                         [('Bilhuset Præstø A/S', 'Jernbanevej 4', '4720', False),
                          ('Škoda Hobro', 'Erhvervsparken 6', '9500', True)])

    def test_omlagt_eller_kappet_side_er_en_fejl(self):
        url = RS.BIL_SEMLER['CUPRA'][0]
        with mock.patch.object(RS, '_text', new=_sider({url: '<html>intet kort</html>'})):
            with self.assertRaisesRegex(RuntimeError, 'dealer-map'):
                RS.bil_cupra()
        with mock.patch.object(RS, '_text', new=_sider({url: _dealer_map([])})):
            with self.assertRaisesRegex(RuntimeError, 'forventet'):
                RS.bil_cupra()


# ------------------------------------------------------------------------------------------------ Suzuki
class TestSuzuki(_Rent):
    def test_saleandservice(self):
        side = _dealer_map([
            {'name': 'Andersen Biler Ballerup', 'address': 'Energivej 2', 'city': 'Ballerup', 'postalCode': 2750,
             'position': {'lat': '55.723151', 'lng': '12.38315'}, 'service': True, 'saleAndService': True},
            {'name': 'Carsten Andersen Biler', 'address': 'Gammel Køge Landevej 248', 'city': 'Hvidovre',
             'postalCode': 2650, 'position': {'lat': '55.63', 'lng': '12.47'}, 'service': True,
             'saleAndService': False}])
        with mock.patch.object(RS, '_text', new=_sider({RS.BIL_SUZUKI_URL: side})), \
                mock.patch.object(RS, 'BIL_SUZUKI_FORVENTET', (1, 5)):
            ud = RS.bil_suzuki()
        self.assertEqual([(r['name'], r['postnr'], r['salg']) for r in ud],
                         [('Andersen Biler Ballerup', '2750', True), ('Carsten Andersen Biler', '2650', False)])


# ------------------------------------------------------------------------------------------------ Renault / Dacia
class TestRenault(_Rent):
    def _side(self, dealers):
        nd = {'props': {'pageProps': {'componentProps': {'abc': {'basicDealers': dealers}}}}}
        return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script>'

    def test_markertype_sales_er_salg(self):
        d = [{'name': 'Pedersen & Nielsen Randers', 'streetAddress': 'Ribevej 3', 'zip': '8960', 'city': 'Randers SV',
              'latitude': 56.436, 'longitude': 10.050, 'markerType': 'service'},
             {'name': 'Autohuset Vestergaard Odense', 'streetAddress': 'Bondovej 18', 'zip': '5250',
              'city': 'Odense SV', 'latitude': 55.361, 'longitude': 10.350, 'markerType': 'sales'}]
        with mock.patch.object(RS, '_text', new=_sider({RS.BIL_RENAULT['Dacia'][0]: self._side(d)})), \
                mock.patch.dict(RS.BIL_RENAULT, {'Dacia': (RS.BIL_RENAULT['Dacia'][0], (1, 5))}):
            ud = RS.bil_dacia()
        self.assertEqual([(r['brand'], r['name'], r['salg']) for r in ud],
                         [('Dacia', 'Pedersen & Nielsen Randers', False), ('Dacia', 'Autohuset Vestergaard Odense', True)])

    def test_uden_basicdealers_er_en_fejl(self):
        with mock.patch.object(RS, '_text', new=_sider({RS.BIL_RENAULT['Renault'][0]: self._side(None)})):
            with self.assertRaisesRegex(RuntimeError, 'basicDealers'):
                RS.bil_renault()


# ------------------------------------------------------------------------------------------------ Ford / Hyundai
def _ld(obj):
    return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'


class TestFindLokation(_Rent):
    def test_autodealer_er_salg_autorepair_er_vaerksted(self):
        base = 'https://www.ford.dk/find-lokation/'
        sider = {base + 'ford-aalborg': _ld({'@type': 'AutoDealer', 'name': 'Ford Aalborg', 'address': {
                     'streetAddress': 'Skjernvej 4B', 'postalCode': '9220', 'addressLocality': 'Aalborg Ø'},
                     'geo': {'latitude': 57.02993, 'longitude': 9.97507}}),
                 base + 'ford-aars': _ld({'@type': 'AutoRepair', 'name': 'Ford Aars Servicepartner', 'address': {
                     'streetAddress': 'Industrivej 1', 'postalCode': '9600', 'addressLocality': 'Aars'},
                     'geo': {'latitude': 56.80, 'longitude': 9.52}})}
        with mock.patch.object(RS, '_sitemap', new=lambda u, *a, **k: list(sider) + ['https://www.ford.dk/biler']), \
                mock.patch.object(RS, '_text', new=_sider(sider)), \
                mock.patch.dict(RS.BIL_FIND_LOKATION, {'Ford': ('www.ford.dk', (1, 5))}):
            ud = RS.bil_ford()
        self.assertEqual(sorted((r['name'], r['salg']) for r in ud),
                         [('Ford Aalborg', True), ('Ford Aars Servicepartner', False)])

    def test_faa_forhandlere_er_en_fejl(self):
        side = 'https://www.hyundai.dk/find-lokation/x'
        with mock.patch.object(RS, '_sitemap', new=lambda u, *a, **k: [side]), \
                mock.patch.object(RS, '_text', new=_sider({side: _ld({'@type': 'AutoRepair', 'name': 'x',
                                                                         'address': {}, 'geo': {}})})):
            with self.assertRaisesRegex(RuntimeError, 'forhandlere.*forventet'):
                RS.bil_hyundai()


# ------------------------------------------------------------------------------------------------ Toyota
class TestToyota(_Rent):
    def _kort(self, navn, adr, pn, by):
        return (f'<div class="retailer-details" role="listitem"><h2 class="x">{navn}</h2><ul><li class="address">'
                f'{adr}</li><li class="phone"><a data-gt-dealercity="{by}" data-gt-dealerzipcode="{pn}">1</a></li>'
                f'</ul><div class="btn-group-vertical"></div></div>')

    def test_kun_vaerksted_postnr_og_dar(self):
        side = self._kort('(Kun værksted) Arne Stubbe Automobiler A/S - Måløv', 'Måløv Byvej 7 - Ballerup', '2760',
                          'Ballerup') + self._kort('STS Biler A/S - Holstebro', 'Bastrupgårdvej 1 - Holstebro', '7500',
                                                   'Holstebro')
        dar = _dar({('Måløv Byvej 7', '2760'): (55.75, 12.32, 'Måløv'),
                    ('Bastrupgårdvej 1', '7500'): (56.37, 8.62, 'Holstebro')})
        with mock.patch.object(RS, '_text', new=_sider({RS.BIL_TOYOTA_URL: side})), \
                mock.patch.object(RS, '_dar_adressepunkt', new=dar), \
                mock.patch.object(RS, 'BIL_TOYOTA_FORVENTET', (1, 5)):
            ud = RS.bil_toyota()
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['salg'], r['lat']) for r in ud],
                         [('Arne Stubbe Automobiler A/S - Måløv', 'Måløv Byvej 7', '2760', False, 55.75),
                          ('STS Biler A/S - Holstebro', 'Bastrupgårdvej 1', '7500', True, 56.37)])


# ------------------------------------------------------------------------------------------------ Subaru / Isuzu
class TestSubaruIsuzu(_Rent):
    def test_subaru_showroom_og_udland_udelades(self):
        j = [{'title': 'Rafn-Larsen - Ballerup', 'hasShowroom': True, 'lat': 55.7246, 'lng': 12.3809,
              'address': {'street': 'Energivej 16', 'zipCode': '2750', 'city': 'Ballerup'}},
             {'title': 'Hampen - Herfølge', 'hasShowroom': False, 'lat': 55.42, 'lng': 12.15,
              'address': {'street': 'Solvangsvej 4', 'zipCode': '4681', 'city': 'Herfølge'}},
             {'title': 'Autonord Service - Nuuk', 'hasShowroom': True, 'lat': 64.18, 'lng': -51.72,
              'address': {'street': 'Nuukullak 23', 'zipCode': '3900', 'city': 'Nuuk'}}]
        with mock.patch.object(RS, '_json', new=_json_stub({RS.BIL_SUBARU_URL: j})), \
                mock.patch.object(RS, 'BIL_SUBARU_FORVENTET', (1, 5)):
            ud = RS.bil_subaru()
        self.assertEqual([(r['name'], r['salg']) for r in ud],
                         [('Rafn-Larsen - Ballerup', True), ('Hampen - Herfølge', False)])

    def test_isuzu_kort(self):
        kort = lambda la, lo, navn, adr: (f'<div class="dealer-card"     data-lat="{la}"     data-lng="{lo}"     '
                                          f'data-element_id="0" data-categories="0" ><h3 class="dealer-card__title">'
                                          f'{navn}</h3><p>{adr}</p><p>Tlf.: 1</p></div>')
        side = kort(55.529, 8.452, 'Anders Hansen Automobiler', 'Tarp Byvej 6C, 6715 Esbjerg, Danmark') + \
            kort(56.018, 12.558, 'Benny Djarlo Automobiler', 'Støberivej 1, 3000 Helsingør, Danmark')
        with mock.patch.object(RS, '_text', new=_sider({RS.BIL_ISUZU_URL: side})), \
                mock.patch.object(RS, 'BIL_ISUZU_FORVENTET', (1, 5)):
            ud = RS.bil_isuzu()
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['by']) for r in ud],
                         [('Anders Hansen Automobiler', 'Tarp Byvej 6C', '6715', 'Esbjerg'),
                          ('Benny Djarlo Automobiler', 'Støberivej 1', '3000', 'Helsingør')])


# ------------------------------------------------------------------------------------------------ Land Rover / Polestar
class TestLdSider(_Rent):
    def test_land_rover_adresse_som_tekst_og_komma_koordinat(self):
        u = 'https://www.landrover.dk/forhandlere/british-motorgroup-kobenhavn'
        side = _ld({'@type': 'AutoDealer', 'name': 'BRITISH MOTORGROUP KØBENHAVN', 'address': 'Dynamovej 12A, 2860 Søborg',
                    'location': {'@type': 'Place', 'geo': {'latitude': '55,73418436', 'longitude': '12,46202374'}}})
        with mock.patch.object(RS, '_sitemap', new=lambda *a, **k: [u, 'https://www.landrover.dk/forhandlere']), \
                mock.patch.object(RS, '_text', new=_sider({u: side})):
            ud = RS.bil_landrover()
        self.assertEqual([(r['street'], r['postnr'], r['by'], round(r['lat'], 4)) for r in ud],
                         [('Dynamovej 12A', '2860', 'Søborg', 55.7342)])


# ================================================================================================ refresh_retail
class TestBilTjek(unittest.TestCase):
    """main() med én bilhenter. Vores raekker staar under gruppe, eget navn eller maerket."""

    def setUp(self):
        self.mappe = tempfile.mkdtemp(prefix='test_trin3_')
        self.addCleanup(shutil.rmtree, self.mappe, True)

    def koer(self, plads, poster, bil_kaeder=None, bil_kendt=None, kendt=None):
        for fn in R.FILER:
            with open(os.path.join(self.mappe, fn), 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(HOVED[fn])
                w.writerows(plads if fn == PLADS else [])
        foer = open(os.path.join(self.mappe, PLADS), 'rb').read()
        ud = io.StringIO()
        with contextlib.ExitStack() as st:
            for navn, v in (('OUT', self.mappe), ('KAEDER', [('bil_suzuki', lambda: [dict(p) for p in poster])]),
                            ('BIL_KAEDER', bil_kaeder or {'bil_suzuki': ['Suzuki']}),
                            ('BIL_KENDT', dict(bil_kendt or {})), ('KENDT_UDEN_KILDE', dict(kendt or {}))):
                st.enter_context(mock.patch.object(R, navn, v))
            st.enter_context(contextlib.redirect_stdout(ud))
            rc = R.main(apply=True)
        self.assertEqual(open(os.path.join(self.mappe, PLADS), 'rb').read(), foer, 'bilgrenen maa intet skrive')
        return rc, ud.getvalue()

    def linjer(self, ud, status):
        return [l for l in ud.splitlines() if l.startswith('  bil_suzuki') and f' {status} ' in l]

    def test_gruppe_bekraefter_salgssted_nyt_meldes_intet_skrives(self):
        plads = [butik('Bjarne Nielsen', 'Bjarne Nielsen A/S - Aalborg', 'Vej 1', '9000', 'Aalborg', AALBORG)]
        poster = [post('Suzuki', 'Suzuki Aalborg', 'Vej 1', '9000', 'Aalborg', nord(AALBORG, 60), salg=True),
                  post('Suzuki', 'Suzuki Odense', 'Vej 2', '5000', 'Odense', ODENSE, salg=True),
                  post('Suzuki', 'Suzuki Vejle Værksted', 'Vej 3', '7100', 'Vejle', VEJLE, salg=False)]
        rc, ud = self.koer(plads, poster)
        self.assertEqual(rc, 0, ud)
        ny = self.linjer(ud, 'NY FORHANDLER')
        self.assertEqual(len(ny), 1, ud)
        self.assertIn('Suzuki Odense', ny[0])
        self.assertIn('1 nye bilforhandlere (kun rapport)', ud)
        self.assertEqual(tal(ud)['nye'], 0)

    def test_havecenter_og_kaede_daekker_ikke_et_salgssted(self):
        plads = [butik('Havecenter', 'Havecenter Odense', 'Vej 9', '5000', 'Odense', ODENSE),
                 butik('Solbjerg Havecenter', 'Solbjerg Havecenter', 'Vej 8', '5000', 'Odense', nord(ODENSE, 20)),
                 butik('jem & fix', 'jem & fix Odense', 'Vej 7', '5000', 'Odense', nord(ODENSE, 40))]
        rc, ud = self.koer(plads, [post('Suzuki', 'Suzuki Odense', 'Vej 2', '5000', 'Odense', ODENSE, salg=True)])
        self.assertEqual(len(self.linjer(ud, 'NY FORHANDLER')), 1, ud)

    def test_raekke_under_maerket_uden_salgssted_er_mulig_lukning(self):
        plads = [butik('Suzuki', 'Suzuki Hobro', 'Randersvej 91', '9500', 'Hobro', AALBORG),
                 butik('Suzuki', 'Carsten Andersen Biler ApS', 'Vej 5', '2650', 'Hvidovre', ODENSE),
                 butik('Suzuki', 'Suzuki Kolding', 'Vej 6', '6000', 'Kolding', KOLDING),
                 butik('Andersen Biler', 'Andersen Biler Vejle', 'Vej 7', '7100', 'Vejle', VEJLE)]
        plads.append(butik('Suzuki', 'Suzuki Ribe', 'Vej 8', '6760', 'Ribe', RIBE))
        poster = [post('Suzuki', 'Carsten Andersen', 'Vej 5', '2650', 'Hvidovre', nord(ODENSE, 30), salg=False),
                  post('Suzuki', 'Suzuki Kolding', 'Vej 6', '6000', 'Kolding', nord(KOLDING, 80), salg=True),
                  post('Suzuki', 'Ribe Værksted', 'Andenvej 2', '6760', 'Ribe', nord(RIBE, 90), salg=False)]
        rc, ud = self.koer(plads, poster)
        luk = self.linjer(ud, 'MULIG LUKNING')
        self.assertEqual(len(luk), 1, ud)
        self.assertIn('Suzuki Hobro', luk[0])
        # Et rent vaerksted paa stedet (samme adresse eller inden for NAER_M): forretningen findes; kun maerket er i
        # tvivl - ikke en lukning
        vk = self.linjer(ud, 'KUN VÆRKSTED')
        self.assertEqual(len(vk), 2, ud)
        self.assertTrue(any('Carsten Andersen' in l for l in vk) and any('Suzuki Ribe' in l for l in vk), ud)
        # Andersen Biler Vejle staar under sit eget navn: listen kan ikke melde den lukket
        self.assertFalse(any('Andersen Biler Vejle' in l for l in ud.splitlines()), ud)
        self.assertEqual(tal(ud)['luk'], 1)

    def test_kendt_dæmper_begge_veje(self):
        plads = [butik('Suzuki', 'Suzuki Hobro', 'Randersvej 91', '9500', 'Hobro', AALBORG)]
        poster = [post('Suzuki', 'Suzuki Odense', 'Vej 2', '5000', 'Odense', ODENSE, salg=True)]
        rc, ud = self.koer(plads, poster, bil_kendt={('bil_suzuki', 'Suzuki Odense'): 'grund 18-11-2026'},
                           kendt={('Suzuki', 'Suzuki Hobro'): 'grund 18-11-2026'})
        self.assertEqual(self.linjer(ud, 'NY FORHANDLER') + self.linjer(ud, 'MULIG LUKNING'), [], ud)
        self.assertEqual(len(self.linjer(ud, 'KENDT')), 2, ud)

    def test_grænsen_er_naer_m(self):
        """100 m fra en bilraekke er samme forhandler; 200 m er en anden (Škoda Holstebro 183 m fra Tang Biler)."""
        plads = [butik('Tang Biler', 'Tang Biler, Holstebro A/S', 'Vej 1', '7500', 'Holstebro', AALBORG),
                 butik('Uggerhøj', 'Uggerhøj Odense', 'Vej 2', '5000', 'Odense', ODENSE)]
        poster = [post('Suzuki', 'Suzuki A', 'Vej 11', '7500', 'Holstebro', nord(AALBORG, 200), salg=True),
                  post('Suzuki', 'Suzuki B', 'Vej 22', '5000', 'Odense', nord(ODENSE, 100), salg=True)]
        rc, ud = self.koer(plads, poster)
        ny = self.linjer(ud, 'NY FORHANDLER')
        self.assertEqual(len(ny), 1, ud)
        self.assertIn('Suzuki A', ny[0])
        self.assertIn('nærmeste: Tang Biler', ny[0])

    def test_samme_adresse_er_samme_forhandler_trods_naalen(self):
        """Škoda Slagelse 18-11-2026: listens naal 157 m fra vores (DAR-punktet), samme adresse 'Teknikvej 2C' - hverken
        NY FORHANDLER eller MULIG LUKNING. 'Gl.' = 'Gammel' og 'Allé' = 'Alle'; et andet husnummer er en anden butik."""
        plads = [butik('Suzuki', 'Slagelse Autocenter A/S', 'Teknikvej 2C', '4200', 'Slagelse', ODENSE),
                 butik('Andersen Biler', 'Andersen Biler A/S - Taastrup', 'Husby Alle 7', '2630', 'Taastrup', VEJLE),
                 butik('Suzuki', 'Carsten Andersen', 'Gammel Køge Landevej 248', '2650', 'Hvidovre', KOLDING)]
        poster = [post('Suzuki', 'Suzuki Slagelse', 'Teknikvej 2C', '4200', 'Slagelse', nord(ODENSE, 400), salg=True),
                  post('Suzuki', 'Suzuki Taastrup', 'Husby Allé 7', '2630', 'Taastrup', nord(VEJLE, 290), salg=True),
                  post('Suzuki', 'Carsten Andersen', 'Gl. Køge Landevej 248', '2650', 'Hvidovre', nord(KOLDING, 500),
                       salg=True),
                  post('Suzuki', 'Suzuki Slagelse 2', 'Teknikvej 4', '4200', 'Slagelse', nord(ODENSE, 450), salg=True)]
        rc, ud = self.koer(plads, poster)
        ny = self.linjer(ud, 'NY FORHANDLER')
        self.assertEqual(len(ny), 1, ud)
        self.assertIn('Teknikvej 4', ny[0])
        self.assertEqual(self.linjer(ud, 'MULIG LUKNING'), [], ud)

    def test_ingen_koordinat_er_info(self):
        p = post('Suzuki', 'Suzuki Ingen', 'Vej 1', '9000', 'Aalborg', AALBORG, salg=True)
        p['lat'] = p['lon'] = None
        rc, ud = self.koer([], [p, post('Suzuki', 'Suzuki Odense', 'Vej 2', '5000', 'Odense', ODENSE, salg=True)])
        self.assertEqual(len(self.linjer(ud, 'INFO')), 1, ud)
        self.assertEqual(len(self.linjer(ud, 'NY FORHANDLER')), 1, ud)


class TestBilRegistre(unittest.TestCase):
    def test_hver_bilhenter_findes_og_koeres(self):
        navne = [n for n, _ in R.KAEDER]
        for n in R.BIL_KAEDER:
            self.assertIn(n, navne)
            self.assertTrue(callable(getattr(RS, n)))

    def test_bil_kendt_har_dato(self):
        import re
        self.assertEqual([k for k, v in R.BIL_KENDT.items() if not re.search(r'\d{2}-\d{2}-\d{4}', v)], [])
        self.assertEqual([k for k in R.BIL_KENDT if k[0] not in R.BIL_KAEDER], [])


if __name__ == '__main__':
    unittest.main()
