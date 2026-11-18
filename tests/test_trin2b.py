"""Hentere fra trin 2b (18-11-2026): Flying Tiger Copenhagen (Tjek), SENG, Biltema og Sports World. Hver test koerer
den RIGTIGE henter mod en stub af det laveste I/O-led (_text, _json, _dar_adressepunkt, dawa.postnumre) med de former,
kilderne havde 18-11-2026, og proever vagterne: varehuse der ikke er aabnet endnu, lukkede butikssider, kaedens
ASCII-stavning, kildefejlen i Holstebro og et svar uden for det forventede spaend."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # noqa: F401  (repo-roden paa sys.path og nettet spaerret)

import csv
import datetime
import json
import unittest
from unittest import mock

import dawa
import retail_sources as RS
from test_trin1 import _Rent, _sider, _dar
from test_trin2 import _json_stub

POSTNR = {'2605': 'Brøndby', '1850': 'Frederiksberg C', '2100': 'København Ø', '8960': 'Randers SØ',
          '4400': 'Kalundborg', '2750': 'Ballerup', '2730': 'Herlev', '4800': 'Nykøbing F', '7500': 'Holstebro',
          '2970': 'Hørsholm', '4000': 'Roskilde', '6400': 'Sønderborg', '5250': 'Odense SV', '9800': 'Hjørring'}


class _MedPostnr(_Rent):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(dawa, 'postnumre', new=lambda: POSTNR)
        p.start(); self.addCleanup(p.stop)


# ------------------------------------------------------------------------------------------------ Flying Tiger
class TestFlyingTiger(_MedPostnr):
    def _b(self, i, gade, pn, by, lat, lon, land='DK'):
        return {'id': i, 'name': 'Flying Tiger Copenhagen', 'street': gade, 'zip_code': pn, 'city': by,
                'latitude': lat, 'longitude': lon, 'country': {'id': land}}

    def _koer(self, side):
        with mock.patch.object(RS, '_json', new=_json_stub({'https://squid-api.tjek.com/v2/stores?dealer_ids=jH70PJ': side})):
            return RS.flyingtiger()

    def test_navnet_faar_byen_og_udland_udelades(self):
        side = [self._b('a', 'Frederiksborggade 1', '1360', 'København', 55.6828, 12.5735),
                self._b('b', 'Hveen Boulevard', '2630', 'Taastrup', 55.6438, 12.2766),
                self._b('c', 'Tinganesvegur 1', '100', 'Tórshavn', 62.0, -6.8)]
        with mock.patch.object(RS, 'FLYINGTIGER_FORVENTET', (1, 5)):
            ud = self._koer(side)
        self.assertEqual([(r['brand'], r['name'], r['street']) for r in ud],
                         [('Flying Tiger Copenhagen', 'Flying Tiger Copenhagen København', 'Frederiksborggade 1'),
                          ('Flying Tiger Copenhagen', 'Flying Tiger Copenhagen Taastrup', 'Hveen Boulevard')])

    def test_kappet_liste_er_en_fejl(self):
        with self.assertRaisesRegex(RuntimeError, 'forventet'):
            self._koer([self._b('a', 'Ahlgade 27', '4300', 'Holbæk', 55.7179, 11.7114)])


# ------------------------------------------------------------------------------------------------ SENG
def _seng_side(butikker):
    return ('<html><script>window.__data={"page":{"description":"Hos SENG kan vi hjælpe dig"},"stores":'
            + json.dumps(butikker, ensure_ascii=False) + ',"system":{"lat":0.0}};</script></html>')


def _sb(i, navn, adr, by, pn):
    return {'id': i, 'name1': navn, 'address1': adr, 'city': by, 'postalCode': pn, 'countryCode': None,
            'phone': '1', 'url': '/butikker/x/'}


class TestSeng(_MedPostnr):
    BUTIKKER = [_sb('114', 'SENG Glostrup', 'Søndre Ringvej 35', 'Glostrup', '2605'),
                _sb('116', 'SENG Frederiksberg', 'Gl. Kongevej 165', 'Frederiksberg', '1850'),
                _sb('121', 'SENG Østerbro', 'Østerbrogade 124-126', 'København Ø', '2100'),
                _sb('999', 'SENG Webshop & Kundeservice', 'Online', '', ''),
                _sb('134', 'SENG Hjørring', 'Barfoedsvej 1B', 'Hjørring', '9800')]
    DAR = {('Søndre Ringvej 35', '2605'): (55.657828, 12.39268, 'Brøndby'),
           ('Gl. Kongevej 165', '1850'): (55.677715, 12.535484, 'Frederiksberg C'),
           ('Østerbrogade 124', '2100'): (55.705164, 12.577696, 'København Ø'),
           ('Barfoedsvej 1B', '9800'): (57.455628, 10.018696, 'Hjørring')}

    def _koer(self, side, spaend=(1, 10)):
        with mock.patch.object(RS, '_text', new=_sider({RS.SENG_URL: side})), \
                mock.patch.object(RS, '_dar_adressepunkt', new=_dar(self.DAR)), \
                mock.patch.object(RS, 'SENG_FORVENTET', spaend):
            return RS.seng()

    def test_listen_gade_og_bynavn_fra_dar(self):
        ud = self._koer(_seng_side(self.BUTIKKER))
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['by'], r['lat']) for r in ud],
                         [('SENG Glostrup', 'Søndre Ringvej 35', '2605', 'Brøndby', 55.657828),
                          ('SENG Frederiksberg', 'Gl. Kongevej 165', '1850', 'Frederiksberg C', 55.677715),
                          ('SENG Østerbro', 'Østerbrogade 124', '2100', 'København Ø', 55.705164),
                          ('SENG Hjørring', 'Barfoedsvej 1B', '9800', 'Hjørring', 57.455628)])

    def test_omlagt_eller_kappet_side_er_en_fejl(self):
        with self.assertRaisesRegex(RuntimeError, 'butikslisten'):
            self._koer('<html>ingen liste</html>')
        with self.assertRaisesRegex(RuntimeError, 'forventet'):
            self._koer(_seng_side(self.BUTIKKER[:2]), spaend=(3, 10))


# ------------------------------------------------------------------------------------------------ Biltema
def _bv(i, navn, adr, pn, by, lat, lon, aabner='', tekst=None):
    return {'storeId': i, 'name': navn, 'openDate': aabner, 'openingText': tekst, 'latitude': lat, 'longitude': lon,
            'address': adr, 'zipCode': pn, 'city': by, 'websiteUrl': 'https://www.biltema.dk/x/'}


def _biltema_side(varehuse):
    return ('<footer>© 2026 Biltema</footer><script>\n        window.storeData = window.storeData || '
            + json.dumps(varehuse, ensure_ascii=False) + ';\n</script>')


class TestBiltema(_MedPostnr):
    def _koer(self, side, spaend=(1, 10)):
        with mock.patch.object(RS, '_text', new=_sider({RS.BILTEMA_URL: side})), \
                mock.patch.object(RS, '_dar_adressepunkt', new=_dar({})), \
                mock.patch.object(RS, 'BILTEMA_FORVENTET', spaend):
            return RS.biltema()

    def test_varehusene_og_dem_der_ikke_er_aabnet_endnu(self):
        om_et_aar = (datetime.date.today() + datetime.timedelta(days=365)).isoformat()
        side = _biltema_side([
            _bv(403, 'Aalborg', 'Stenbukken 21', '9200', 'Aalborg SV', 56.996424, 9.869045),
            _bv(424, 'Kalundborg', 'Stejlhøj 33', '4400', 'Kalundborg', 55.677648, 11.137091),
            _bv(421, 'Randers', 'Neptunvej 22', '8960', 'Randers', 56.423083, 10.064778),
            _bv(430, 'Grenaa', 'Energivej 1', '8500', 'Grenaa', 56.40, 10.88, aabner=om_et_aar + 'T00:00:00'),
            _bv(431, 'Hobro', 'Ny Vej 1', '9500', 'Hobro', 56.64, 9.79, tekst='Åbner snart'),
            _bv(432, 'Skive', 'Ny Vej 2', '7800', 'Skive', 56.56, 9.03, aabner='til foråret'),
            _bv(433, 'Gammel', 'Vejen 3', '7100', 'Vejle', 55.70, 9.53, aabner='2019-03-01T00:00:00')])
        ud = self._koer(side)
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['by']) for r in ud],
                         [('Biltema Aalborg', 'Stenbukken 21', '9200', 'Aalborg SV'),
                          ('Biltema Kalundborg', 'Stejlhøj 33', '4400', 'Kalundborg'),
                          ('Biltema Randers', 'Neptunvej 22', '8960', 'Randers SØ'),
                          ('Biltema Gammel', 'Vejen 3', '7100', 'Vejle')])

    def test_omlagt_eller_kappet_side_er_en_fejl(self):
        with self.assertRaisesRegex(RuntimeError, 'storeData'):
            self._koer('<html>ingen data</html>')
        with self.assertRaisesRegex(RuntimeError, 'forventet'):
            self._koer(_biltema_side([_bv(403, 'Aalborg', 'Stenbukken 21', '9200', 'Aalborg SV', 56.99, 9.87)]),
                       spaend=(5, 10))


# ------------------------------------------------------------------------------------------------ Sports World
def _sw_side(navn, gade, pn, by, lat, lon, aabent=True):
    lb = {'@context': 'https://schema.org/', '@type': 'LocalBusiness', 'name': navn,
          'openingHours': ['Mo 10:00-19:00', 'Su 10:00-16:00'] if aabent else [],
          'address': {'@type': 'PostalAddress', 'streetAddress': gade, 'addressLocality': by, 'postalCode': pn,
                      'addressCountry': 'Denmark'},
          'geo': {'@type': 'GeoCoordinates', 'latitude': str(lat), 'longitude': str(lon)}}
    bc = {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': []}
    return ''.join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in (lb, bc))


SW = 'https://www.sportsworld.dk'
SW_SIDER = {
    'ballerup-2-dk-store-3934': _sw_side('Sports World Ballerup 2 DK', 'Ballerup Centret, Baltorpvej 2', '2750',
                                         'Ballerup', 55.72920901, 12.35791517),
    'herlev-sports-world-store-3521': _sw_side('Sports World Herlev - Sports World', 'Herlev Hovedgade, 17', '2730',
                                               'Herlev', 55.71829, 12.44944),
    'holstebro-2-dk-store-3980': _sw_side('Sports World Holstebro 2 DK', 'Lavhedevej 50', '7500', 'Holstebro',
                                          56.358393, 8.616949),
    'hørsholm-store-3505': _sw_side('Sports World Hørsholm', 'Horsholm, Midtpunkt 154', '2970', 'Horsholm',
                                    55.882, 12.49768),
    'nykobing-sm-dk-store-3985': _sw_side('Sports World Nykobing SM DK', 'Guldborgsundcentret 36', '4800',
                                          'Nykobing Falster', 54.75982483, 11.85142125),
    'roskilde-store-3572': _sw_side('Sports World Roskilde', "RO's Torv 1, St 201", '4000', 'Roskilde',
                                    55.64175, 12.09805),
    'sønderborg-store-3554': _sw_side('Sports World Sønderborg', 'Kastanie Alle 3, 1 Sal', '6400', 'Sonderborg',
                                      54.90919, 9.79278),
    'odense-sv-store-3526': _sw_side('Sports World Odense SV', 'Dalumvej 15', '5250', 'Odense SV', 55.37288,
                                     10.36943, aabent=False),
}


def _sw_az(slugs):
    return ''.join(f'<a class="x" data-testid="link" href="/stores/{s}"><span>{s}</span></a>' for s in slugs) + \
        '<a href="/stores">Butik finder kort</a><a href="/stores/az">A-Å</a>'


class TestSportsWorld(_MedPostnr):
    def _koer(self, slugs, sider=None, spaend=(1, 20)):
        from urllib.parse import quote
        tabel = {f'{SW}/stores/az': _sw_az(slugs)}
        for s in slugs:
            tabel[SW + quote(f'/stores/{s}')] = (sider or SW_SIDER)[s]
        with mock.patch.object(RS, '_text', new=_sider(tabel)), \
                mock.patch.object(RS, '_dar_adressepunkt', new=_dar({})), \
                mock.patch.object(RS, 'SPORTSWORLD_FORVENTET', spaend):
            return RS.sportsworld()

    def test_navne_gader_bynavne_og_den_lukkede_side(self):
        ud = self._koer(sorted(SW_SIDER))
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['by']) for r in ud],
                         [('Sports World Ballerup', 'Baltorpvej 2', '2750', 'Ballerup'),
                          ('Sports World Herlev', 'Herlev Hovedgade 17', '2730', 'Herlev'),
                          ('Sports World Holstebro', 'Nørregade 1', '7500', 'Holstebro'),
                          ('Sports World Hørsholm', 'Midtpunkt 154', '2970', 'Hørsholm'),
                          ('Sports World Nykøbing', 'Guldborgsundcentret 36', '4800', 'Nykøbing F'),
                          ('Sports World Roskilde', "RO's Torv 1", '4000', 'Roskilde'),
                          ('Sports World Sønderborg', 'Kastanie Alle 3', '6400', 'Sønderborg')])
        holstebro = ud[2]
        self.assertEqual((holstebro['lat'], holstebro['lon']), (56.358421, 8.616991))   # KILDEFEJL: DAR-punktet

    def test_kort_liste_eller_omlagt_side_er_en_fejl(self):
        with self.assertRaisesRegex(RuntimeError, 'A-Å-listen.*forventet'):
            self._koer(['ballerup-2-dk-store-3934'], spaend=(5, 20))
        with self.assertRaisesRegex(RuntimeError, 'LocalBusiness'):
            self._koer(['roskilde-store-3572'], sider={'roskilde-store-3572': '<html>ingen data</html>'})


# ------------------------------------------------------------------------------------------------ Sunset Boulevard
def _sunset(nr, navn, alias, gade, pn, by, lon, lat, aktiv=True, kanaler=('EAT_IN', 'TAKE_OUT')):
    """En post i den nye webshops liste (shop.sunset-boulevard.dk/api/v2/intusr/shops, 18-11-2026)."""
    return {'id': f'u{nr}', 'shopName': navn, 'shopNameAlias': alias, 'shopNumber': str(nr), 'shopIsActive': aktiv,
            'shopAddress': {'zip': pn, 'city': by, 'street': gade, 'country': 'DK'},
            'shopCoordinates': [lon, lat], 'deliveryMethods': list(kanaler), 'shopOptions': {}}


class TestSunsetNyKilde(_Rent):
    """18-11-2026 blev webshoppen lagt om: det gamle API gav en tom liste, og den nye liste ligger paa kaedens eget
    domaene. En tom liste skal give en koerselsfejl, aldrig 47 'mulige lukninger'."""
    def _koer(self, svar, spaend=(1, 10)):
        with mock.patch.object(RS, '_robots_tilladt', new=lambda *a, **k: True), \
                mock.patch.object(RS, '_json', new=_json_stub({RS.SUNSET_URL: svar})), \
                mock.patch.object(RS, '_text', new=_sider({RS.SUNSET_LALANDIA_URL: '<p>intet</p>'})), \
                mock.patch.object(RS, '_sunset_dar_punkt', new=lambda gade, pn: None), \
                mock.patch.object(RS, 'SUNSET_FORVENTET', spaend):
            return RS.sunset_boulevard()

    def test_kilden_er_kaedens_eget_domaene(self):
        self.assertTrue(RS.SUNSET_URL.startswith('https://shop.sunset-boulevard.dk/api/v2/intusr/shops?'))
        self.assertIn('onlyActive=true', RS.SUNSET_URL)

    def test_tom_liste_er_en_koerselsfejl(self):
        with self.assertRaisesRegex(RuntimeError, 'forventet'):
            self._koer([], spaend=(38, 60))

    def test_nyt_format_test_inaktiv_og_ghost_kitchen_udelades(self):
        svar = [_sunset(16857, 'Taastrup', 'Taastrup', 'Helgeshøj Alle 32A', '2630', 'Taastrup', 12.2849, 55.6607),
                _sunset(1, 'Sunset Boulevard Aarhus, Skejby', 'Aarhus, Skejby', 'Olof Palmes Allé 2', '8200',
                        'Aarhus N', 10.1983, 56.1956),
                _sunset(2, 'Test-Sprinting Software', 'Test', 'Testvej 1', '8000', 'TEST', 0, 0),
                _sunset(3, 'Klostertorvet', 'Klostertorvet', 'Klostertorvet 1', '8000', 'Aarhus C', 10.21, 56.15,
                        aktiv=False),
                _sunset(4, 'Ghost', 'Ghost', 'Køkkenvej 1', '2300', 'København S', 12.6, 55.66, kanaler=('DELIVERY',))]
        ud = self._koer(svar)
        self.assertEqual([(r['name'], r['street'], r['postnr'], round(r['lat'], 4)) for r in ud],
                         [('Taastrup', 'Helgeshøj Alle 32A', '2630', 55.6607),
                          ('Aarhus - Skejby', 'Olof Palmes Allé 2', '8200', 56.1956)])


class TestTrin2bData(unittest.TestCase):
    def test_kildefejlen_i_holstebro_peger_paa_raekken_i_data(self):
        """KILDEFEJL for Sports World Holstebro skal give samme gade og naal som raekken i udvalgsvarer_dk.csv; ellers
        melder refresh_retail en koordinat-afvigelse hver uge."""
        rod = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(rod, 'udvalgsvarer_dk.csv'), encoding='utf-8-sig') as f:
            r = next(x for x in csv.DictReader(f) if x['Navn'] == 'Sports World Holstebro')
        k = RS.KILDEFEJL[('Sports World', 'lavhedevej 50')]
        self.assertEqual(r['Adresse'].split(',')[0], k['street'])
        self.assertLess(RS._afst_m(float(r['Latitude']), float(r['Longitude']), k['lat'], k['lon']), 1)


if __name__ == '__main__':
    unittest.main()
