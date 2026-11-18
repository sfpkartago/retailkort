"""Hentere fra trin 2 mod fuld ugentlig daekning (17-11-2026): Søstrene Grene, Land & Fritid, Skechers, Elgiganten (Tjek)
og Intersport (finderen + kampagnesiden). Hver test koerer den RIGTIGE henter mod en stub af det laveste I/O-led (_text,
_json, _dar_adressepunkt) med de former, kilderne havde 17-11-2026, og proever vagterne: udenlandske butikker, kaedens
lager ('Lukket for kundebesøg'), shop-in-shops, kampagnenavne uden adresse og et svar uden for det forventede spaend."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # noqa: F401  (repo-roden paa sys.path og nettet spaerret)

import json
import unittest
from unittest import mock

import retail_sources as RS
from test_trin1 import _Rent, _sider, _dar


def _json_stub(d):
    """_json-stub: url (praefiks) -> svar; ukendt url fejler hoejt."""
    def f(url, *a, **k):
        for u, v in d.items():
            if url.startswith(u):
                return v
        raise AssertionError(f'uventet url {url}')
    return f


# ------------------------------------------------------------------------------------------------ Søstrene Grene
class TestSostreneGrene(_Rent):
    def _st(self, navn, adr, land='dk', lat=56.1, lon=10.2):
        return {'store': {'id': '1', 'name': navn, 'address': adr, 'country': land,
                          'location': {'latitude': lat, 'longitude': lon}}, 'distance': None}

    def test_center_foran_gaden_navn_og_land(self):
        svar = {'stores': [self._st('Storcenter Nord, Aarhus', 'Storcenter Nord, Finlandsgade 17, 8200 Aarhus'),
                           self._st('Søstrene Grene, København K', 'Købmagergade 50 A, 1150 København', lat=55.68, lon=12.57),
                           self._st('Hørsholm Midtpunkt', 'Hørsholm Midtpunkt 1.sal, 2970 Hørsholm', lat=55.88, lon=12.49),
                           self._st('Malmö', 'Södergatan 1, 21134 Malmö', land='se', lat=55.6, lon=13.0)]}
        with mock.patch.object(RS, '_json', new=_json_stub({RS.SOSTRENEGRENE_URL: svar})), \
                mock.patch.object(RS, 'SOSTRENEGRENE_FORVENTET', (1, 5)):
            ud = RS.sostrenegrene()
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['by']) for r in ud],
                         [('Søstrene Grene Storcenter Nord, Aarhus', 'Finlandsgade 17', '8200', 'Aarhus'),
                          ('Søstrene Grene København K', 'Købmagergade 50A', '1150', 'København'),
                          ('Søstrene Grene Hørsholm Midtpunkt', 'Hørsholm Midtpunkt 1', '2970', 'Hørsholm')])

    def test_kappet_eller_omlagt_svar_er_en_fejl(self):
        with mock.patch.object(RS, '_json', new=_json_stub({RS.SOSTRENEGRENE_URL: {'stores': []}})):
            with self.assertRaisesRegex(RuntimeError, 'forventet'):
                RS.sostrenegrene()
        with mock.patch.object(RS, '_json', new=_json_stub({RS.SOSTRENEGRENE_URL: {'error': 'x'}})):
            with self.assertRaisesRegex(RuntimeError, 'uventet svar'):
                RS.sostrenegrene()


# ------------------------------------------------------------------------------------------------ Land & Fritid
class TestLandOgFritid(_Rent):
    def _k(self, titel, adr, pn, by, lat=55.9, lon=12.4):
        return {'Title': titel, 'Address': adr, 'Zipcode': pn, 'City': by, 'Latitude': lat, 'Longitude': lon}

    def test_titlerne_og_dlg_landbutik(self):
        svar = [self._k('Land & Fritid - Fredensborg ', 'Præstemosevej 4B', '3480', 'Fredensborg'),
                self._k('Åkirkeby - Land & Fritid', 'Birgersvej 1', '3720', 'Åkirkeby', 55.07, 14.92),
                self._k('Thisted -Land & Fritid', 'Tigervej 1', '7700', 'Thisted', 56.97, 8.73),
                self._k('Vrå samt outlet - Land & Fritid', 'Vestre Ringvej 21', '9760', 'Vrå', 57.35, 9.93),
                self._k('Årup - Land & Fritid', 'Industrivej 1, Grønnemose', '5560', 'Årup', 55.42, 10.05),
                self._k('Hedensted - Land & Fritid', 'Blæsbjergvej 46', '8722', 'hedensted', 55.78, 9.70),
                self._k('Vaarst - DLG Landbutik', 'Vaarstvej 257', '9260', 'Gistrup', 56.93, 10.05)]
        with mock.patch.object(RS, '_json', new=_json_stub({RS.LANDOGFRITID_URL: svar})), \
                mock.patch.object(RS, 'LANDOGFRITID_FORVENTET', (1, 10)):
            ud = RS.landogfritid()
        self.assertEqual([(r['brand'], r['name'], r['street'], r['by']) for r in ud],
                         [('Land & Fritid', 'Land & Fritid Fredensborg', 'Præstemosevej 4B', 'Fredensborg'),
                          ('Land & Fritid', 'Land & Fritid Åkirkeby', 'Birgersvej 1', 'Åkirkeby'),
                          ('Land & Fritid', 'Land & Fritid Thisted', 'Tigervej 1', 'Thisted'),
                          ('Land & Fritid', 'Land & Fritid Vrå', 'Vestre Ringvej 21', 'Vrå'),
                          ('Land & Fritid', 'Land & Fritid Årup', 'Industrivej 1', 'Årup'),
                          ('Land & Fritid', 'Land & Fritid Hedensted', 'Blæsbjergvej 46', 'Hedensted'),
                          ('DLG Landbutik', 'DLG Landbutik Vaarst', 'Vaarstvej 257', 'Gistrup')])

    def test_kappet_svar_er_en_fejl(self):
        with mock.patch.object(RS, '_json', new=_json_stub({RS.LANDOGFRITID_URL: [self._k('A - Land & Fritid', 'Vej 1', '1000', 'X')]})):
            with self.assertRaisesRegex(RuntimeError, 'forventet'):
                RS.landogfritid()


# ------------------------------------------------------------------------------------------------ Skechers
class TestSkechers(_Rent):
    def test_enhed_efter_nummeret_land_og_maerke_foran(self):
        svar = [{'name': 'Skechers Superstore Kolding', 'address_line_1': 'Skovvangen 42 Lokale 1-017', 'postal_code': '6000',
                 'city': 'Kolding', 'country': 'Danmark', 'latitude': '55.5139', 'longitude': '9.4600'},
                {'name': 'Skechers Bramming', 'address_line_1': 'Nørregade 12 A', 'postal_code': '6740',
                 'city': 'Bramming', 'country': 'Danmark', 'latitude': '55.4654', 'longitude': '8.7006'},
                {'name': 'Outlet Ringsted', 'address_line_1': 'Klosterkrogen 10', 'postal_code': '4100',
                 'city': 'Ringsted', 'country': 'Danmark', 'latitude': '55.4542', 'longitude': '11.7861'},
                {'name': 'Skechers Oslo', 'address_line_1': 'Karl Johans gate 1', 'postal_code': '0154',
                 'city': 'Oslo', 'country': 'Norge', 'latitude': '59.91', 'longitude': '10.75'}]
        with mock.patch.object(RS, '_json', new=_json_stub({RS.SKECHERS_URL: svar})), \
                mock.patch.object(RS, 'SKECHERS_FORVENTET', (1, 5)):
            ud = RS.skechers()
        self.assertEqual([(r['name'], r['street'], r['postnr']) for r in ud],
                         [('Skechers Superstore Kolding', 'Skovvangen 42', '6000'),
                          ('Skechers Bramming', 'Nørregade 12A', '6740'),
                          ('Skechers Outlet Ringsted', 'Klosterkrogen 10', '4100')])


# ------------------------------------------------------------------------------------------------ Elgiganten (Tjek)
class TestElgiganten(_Rent):
    def _b(self, i, navn, gade, pn, by, lat, lon, land='DK'):
        return {'id': i, 'name': navn, 'street': gade, 'zip_code': pn, 'city': by, 'latitude': lat, 'longitude': lon,
                'country': {'id': land}}

    def test_lageret_udelades_og_navnet_faar_byen(self):
        side = [self._b('a', 'Elgiganten', 'Lilli Gyldenkildes Torv 2', '8700', 'Horsens', 55.8589, 9.8467),
                self._b('b', 'Elgiganten DK', 'Østerbakken 99', '7700', 'Thisted', 56.9686, 8.7337),
                self._b('c', 'Elgiganten', 'Lukket for kundebesøg', '8381', 'Aarhus', 56.19, 10.11),
                self._b('d', 'Elgiganten', 'Tórshavnvegur 1', '100', 'Tórshavn', 62.0, -6.8)]
        with mock.patch.object(RS, '_json', new=_json_stub({'https://squid-api.tjek.com/v2/stores?dealer_ids=c35es': side})), \
                mock.patch.object(RS, 'ELGIGANTEN_FORVENTET', (1, 5)):
            ud = RS.elgiganten()
        self.assertEqual([(r['name'], r['street']) for r in ud],
                         [('Elgiganten Horsens', 'Lilli Gyldenkildes Torv 2'), ('Elgiganten Thisted', 'Østerbakken 99')])


# ------------------------------------------------------------------------------------------------ Intersport
_FINDER = '''<div>Find butik</div>
<script id="map-data" type="application/json">
  {"locations": [
    {"name": "INTERSPORT Allerød", "storeId": "1067", "address": {"address1": "M.D. Madsensvej 19", "address2": null,
     "postal_code": "3450", "latitude": "55,869901", "longitude": "12,354101", "city": "Allerød"}},
    {"name": "INTERSPORT Aabenraa", "storeId": null, "address": {"address1": "Storegade 35", "address2": null,
     "postal_code": "6200", "latitude": "55.04289", "longitude": "9.41919", "city": "Aabenraa"}},
    {"name": "INTERSPORT Magasin Kongens Nytorv", "storeId": "1133", "address": {"address1": "Kongens Nytorv 13",
     "address2": null, "postal_code": "1095", "latitude": null, "longitude": null, "city": "København K"}},
    {"name": "INTERSPORT Køge", "storeId": "1086", "address": {"address1": "Torvet 25", "address2": null,
     "postal_code": "4600", "latitude": "55,45663", "longitude": "12,18026", "city": "Køge"}}
  ]}
</script>'''


def _kampagne(navne):
    # Sidefoden har ogsaa linjer, der begynder med 'INTERSPORT' (17-11-2026: 'Om INTERSPORT', 'INTERSPORT Blog').
    return ('<h1>Udvalgte INTERSPORT butikker</h1><p>Følgende INTERSPORT-butikker er en del af kampagnen.</p>'
            + ''.join(f'<p>{n}</p>' for n in navne) + '<h3>Kontakt os</h3><p>Telefon: 43 55 80 00</p>'
            + '<p>INTERSPORT Blog</p><p>INTERSPORT Teamsport</p>')


class TestIntersport(_Rent):
    def _koer(self, navne, finder=_FINDER, dar=None):
        with mock.patch.object(RS, '_text', new=_sider({RS.INTERSPORT_FINDER_URL: finder,
                                                         RS.INTERSPORT_KAMPAGNE_URL: _kampagne(navne)})), \
                mock.patch.object(RS, 'INTERSPORT_FINDER_FORVENTET', (1, 10)), \
                mock.patch.object(RS, 'INTERSPORT_KAMPAGNE_FORVENTET', (1, 10)), \
                mock.patch.object(RS, '_dar_adressepunkt', new=_dar(dar or {})):
            return RS.intersport()

    def test_finder_og_kampagne_uden_shop_in_shop(self):
        ud = self._koer(['INTERSPORT Aalborg', 'INTERSPORT Køge', 'INTERSPORT Greve - Waves'])
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['lat'], r['lon']) for r in ud],
                         [('INTERSPORT Allerød', 'M.D. Madsensvej 19', '3450', 55.869901, 12.354101),
                          ('INTERSPORT Aabenraa', 'Storegade 35', '6200', 55.04289, 9.41919),
                          ('INTERSPORT Køge', 'Torvet 25', '4600', 55.45663, 12.18026),
                          ('INTERSPORT Aalborg', 'Vandmanden 5A', '9200', 57.003511, 9.872792),
                          ('INTERSPORT Greve Waves', 'Over Bølgen 10', '2670', 55.597953, 12.328909)])

    def test_nyt_kampagnenavn_kommer_med_uden_koordinat(self):
        ud = self._koer(['INTERSPORT Aalborg', 'INTERSPORT Billund'])
        self.assertEqual([(r['name'], r['lat']) for r in ud if r['name'] == 'INTERSPORT Billund'],
                         [('INTERSPORT Billund', None)])

    def test_sidefoden_er_ikke_butikker(self):
        ud = self._koer(['INTERSPORT Aalborg'])
        self.assertNotIn('INTERSPORT Blog', [r['name'] for r in ud])
        self.assertNotIn('INTERSPORT Teamsport', [r['name'] for r in ud])

    def test_kappet_finder_er_en_fejl(self):
        with mock.patch.object(RS, '_text', new=_sider({RS.INTERSPORT_FINDER_URL: _FINDER,
                                                         RS.INTERSPORT_KAMPAGNE_URL: _kampagne(['INTERSPORT Aalborg'])})), \
                mock.patch.object(RS, 'INTERSPORT_FINDER_FORVENTET', (5, 10)), \
                mock.patch.object(RS, 'INTERSPORT_KAMPAGNE_FORVENTET', (1, 10)):
            with self.assertRaisesRegex(RuntimeError, 'finderen.*forventet'):
                RS.intersport()

    def test_omlagte_sider_er_en_fejl(self):
        with self.assertRaisesRegex(RuntimeError, 'map-data'):
            self._koer(['INTERSPORT Aalborg'], finder='<p>ingen data</p>')
        with mock.patch.object(RS, '_text', new=_sider({RS.INTERSPORT_FINDER_URL: _FINDER,
                                                         RS.INTERSPORT_KAMPAGNE_URL: '<p>Kampagnen er slut</p>'})), \
                mock.patch.object(RS, 'INTERSPORT_FINDER_FORVENTET', (1, 10)):
            with self.assertRaisesRegex(RuntimeError, 'kampagnesidens liste'):
                RS.intersport()

    def test_kort_kampagneliste_er_en_fejl_ikke_lukninger(self):
        with mock.patch.object(RS, '_text', new=_sider({RS.INTERSPORT_FINDER_URL: _FINDER,
                                                         RS.INTERSPORT_KAMPAGNE_URL: _kampagne(['INTERSPORT Aalborg'])})), \
                mock.patch.object(RS, 'INTERSPORT_FINDER_FORVENTET', (1, 10)):
            with self.assertRaisesRegex(RuntimeError, 'kampagnesiden.*forventet'):
                RS.intersport()

    def test_kampagnetabellen_peger_paa_raekker_i_data(self):
        """Hver adresse i INTERSPORT_KAMPAGNE skal staa i udvalgsvarer_dk.csv med samme navn og naal; ellers melder
        refresh_retail en NY butik og en MULIG LUKNING for den samme butik hver uge."""
        import csv
        rod = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(rod, 'udvalgsvarer_dk.csv'), encoding='utf-8-sig') as f:
            vores = {r['Navn']: r for r in csv.DictReader(f) if r['Mærke'] == 'Intersport'}
        for k, v in RS.INTERSPORT_KAMPAGNE.items():
            if v is None:
                continue
            self.assertIn(v[0], vores, k)
            r = vores[v[0]]
            self.assertEqual((r['Adresse'].split(',')[0], r['Postnr']), (v[1], v[2]), k)
            self.assertLess(RS._afst_m(float(r['Latitude']), float(r['Longitude']), v[4], v[5]), 1, k)


if __name__ == '__main__':
    unittest.main()
