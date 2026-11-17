"""Hentere fra trin 1 mod fuld ugentlig daekning (17-11-2026): koekkenkaederne, Go'on/Lavpris, Oles Olie, Billigblomst
og Bestseller-maerkerne. Hver test koerer den RIGTIGE henter mod en stub af det laveste I/O-led (_text, _json, _sitemap,
_dar_adressepunkt) med de former, kilderne havde 17-11-2026, og proever de vagter, der skal holde falske butikker og
falske lukninger ude: udenlandske butikker (Færøerne, Grønland, Båstad, Antwerpen), skjulte og udkommenterede butikker,
shop-in-shops, kortudsnit i stedet for naal, og et svar uden for det forventede spaend."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # noqa: F401  (repo-roden paa sys.path og nettet spaerret)

import json
import unittest
from unittest import mock

import retail_sources as RS
import sources as S


def _sider(d):
    """_text-stub: url -> html; ukendt url fejler hoejt."""
    def f(url, *a, **k):
        if url not in d:
            raise AssertionError(f'uventet url {url}')
        return d[url]
    return f


class _Rent(unittest.TestCase):
    def setUp(self):
        self._kf = (set(RS.KILDEFEJL_KALDT), set(RS.KILDEFEJL_RAMT), set(RS.KILDEFEJL_TVETYDIG))
        p = mock.patch.object(RS.time, 'sleep', new=lambda *a, **k: None)
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(RS, '_map', new=lambda fn, seq, workers=8: [fn(x) for x in seq])
        p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        for s, gemt in zip((RS.KILDEFEJL_KALDT, RS.KILDEFEJL_RAMT, RS.KILDEFEJL_TVETYDIG), self._kf):
            s.clear(); s.update(gemt)


def _dar(tabel):
    """_dar_adressepunkt-stub: (gade, postnr) -> (lat, lon, postnrnavn); ukendt -> (None, None, '')."""
    return lambda gade, pn: tabel.get((gade, pn), (None, None, ''))


# ------------------------------------------------------------------------------------------------ hjaelpere
class TestAdresseLinjer(unittest.TestCase):
    def test_pn_by_formerne(self):
        self.assertEqual(RS._pn_by('9200 Aalborg'), ('9200', 'Aalborg'))
        self.assertEqual(RS._pn_by('DK-7100, Vejle'), ('7100', 'Vejle'))
        self.assertEqual(RS._pn_by('Aarhus C, DK-8000'), ('8000', 'Aarhus C'))
        self.assertEqual(RS._pn_by('Antwerpen, 2000', kraev_dk=True), ('', ''))
        self.assertEqual(RS._pn_by('3905 Nuussuaq'), ('', ''))           # Grønland (39xx)
        self.assertEqual(RS._pn_by('Fo-100 Tórshavn'), ('', ''))

    def test_adresse_efter_navn_imellem_og_paa_en_linje(self):
        self.assertEqual(RS._adresse_efter(['ADRESSE', 'Nettoline Sæby', 'Grønnegade 22', '9300 Sæby', 'CVR: 1'],
                                           'ADRESSE'), ('Grønnegade 22', '9300', 'Sæby'))
        self.assertEqual(RS._adresse_efter(['ADRESSE', 'Nettoline Hillerød', 'Markedsstræde 8 3400 Hillerød'],
                                           'ADRESSE'), ('Markedsstræde 8', '3400', 'Hillerød'))
        self.assertEqual(RS._adresse_efter(['ADRESSE', 'x', 'Vestervang 7 og 8 - indgang fra Vestergade 8660 '
                                            'Skanderborg'], 'ADRESSE'), ('Vestervang 7', '8660', 'Skanderborg'))
        # Svanes Frederiksberg-side har ingen 'Adresse', men 'Kontakt'
        self.assertEqual(RS._adresse_efter(['Kontakt', 'Svane Køkkenet Frederiksberg', 'Gl. Kongevej 99, Frederiksberg',
                                            '1850 København'], ('Adresse', 'Kontakt')),
                         ('Gl. Kongevej 99', '1850', 'København'))
        self.assertIsNone(RS._adresse_efter(['ADRESSE', 'Nettoline Kopavogur', 'Askalind 3', '201 Kópavogur'], 'ADRESSE'))

    def test_tekstlinjer_dropper_kommentarer(self):
        self.assertNotIn('Nyborg', ' '.join(RS._tekstlinjer('<p>a</p><!--<a>Nettoline Nyborg</a>--><p>b</p>')))

    def test_med_dar_punkt_opgiver_ved_mange_ukendte(self):
        rows = [{'street': f'Vej {i}', 'postnr': '1000', 'lat': None, 'lon': None} for i in range(8)]
        with mock.patch.object(RS, '_dar_adressepunkt', new=_dar({('Vej 0', '1000'): (55.6, 12.5, 'Kbh')})):
            with self.assertRaisesRegex(RuntimeError, 'findes ikke i DAR'):
                RS._med_dar_punkt(rows, 'x')
        rows = [{'street': 'Vej 1', 'postnr': '1000', 'lat': None, 'lon': None},
                {'street': 'Vej 2', 'postnr': '1000', 'lat': 55.0, 'lon': 12.0}]
        with mock.patch.object(RS, '_dar_adressepunkt', new=_dar({('Vej 1', '1000'): (55.6, 12.5, 'Kbh')})):
            self.assertEqual([(r['lat'], r['lon']) for r in RS._med_dar_punkt(rows, 'x')], [(55.6, 12.5), (55.0, 12.0)])


# ------------------------------------------------------------------------------------------------ koekken
class TestKvik(_Rent):
    def _butik(self, navn, land='Denmark', **ekstra):
        b = {'name': navn, 'showOnWebsite': True, 'isDigital': False, 'startDate': '2020-01-01T00:00:00Z',
             'endDate': None, 'address': {'streetName': 'Industrivej 16', 'postal': '6200', 'city': 'Aabenraa',
                                          'country': land, 'latitude': '55.049177', 'longitude': '9.404018'}}
        b.update(ekstra)
        return b

    def test_kun_aabne_danske_butikker(self):
        st = [self._butik('Kvik Aabenraa'), self._butik('Kvik Thorshavn', land='Faroe Islands'),
              self._butik('Kvik Digital', isDigital=True), self._butik('Kvik Skjult', showOnWebsite=False),
              self._butik('Kvik Lukket', endDate='2020-06-01T00:00:00Z'),
              self._butik('Kvik Ny', startDate='2099-01-01T00:00:00Z')]
        h = '<script id="__NEXT_DATA__" type="application/json">%s</script>' % json.dumps(
            {'props': {'pageProps': {'stores': st}}})
        with mock.patch.object(RS, '_text', new=_sider({RS.KVIK_URL: h})), \
                mock.patch.object(RS, 'KVIK_FORVENTET', (1, 5)):
            ud = RS.kvik()
        self.assertEqual([r['name'] for r in ud], ['Kvik Aabenraa'])
        self.assertEqual((ud[0]['street'], ud[0]['postnr'], ud[0]['lat']), ('Industrivej 16', '6200', 55.049177))
        with mock.patch.object(RS, '_text', new=_sider({RS.KVIK_URL: h})), \
                mock.patch.object(RS, 'KVIK_FORVENTET', (2, 5)):
            with self.assertRaisesRegex(RuntimeError, 'forventet'):
                RS.kvik()


class TestHth(_Rent):
    def test_udenlandske_og_skjulte_udelades(self):
        def b(navn, pn, lat, lon, **e):
            d = {'name': navn, 'addressLine1': 'Industrivej 34G', 'zipCode': pn, 'city': 'x', 'latitude': lat,
                 'longitude': lon, 'hide': False, 'hideOnStoreFinderPage': False}
            d.update(e)
            return d
        data = [b('HTH Grønland', '3905', '64.17', '-51.70'), b('HTH Færøerne', '188', '62.02', '-6.76'),
                b('HTH Thisted', '7700', '56.9623743', '8.715107'), b('HTH Skjult', '7400', '56.13', '8.99', hide=True),
                b('HTH Skjult2', '7400', '56.13', '8.99', hideOnStoreFinderPage=True)]
        with mock.patch.object(RS, '_json', return_value=data), mock.patch.object(RS, 'HTH_FORVENTET', (1, 5)):
            self.assertEqual([r['name'] for r in RS.hth()], ['HTH Thisted'])


class TestSvane(_Rent):
    def test_begge_sidelayouts_og_dar(self):
        liste = '<a href="/butikker/jylland/aalborg">x</a><a href="/butikker/sjaelland/frederiksberg">y</a>'
        aalborg = ('<h3>Velkommen til Svane Køkkenet Aalborg</h3><h4>Adresse</h4><p>Svane Køkkenet Aalborg<br/>'
                   'Fiskene 29, City Syd<br/>9200 Aalborg</p>')
        frb = ('<h3>Velkommen til Svane Køkkenet Frederiksberg</h3><h4>Kontakt</h4><p>Svane Køkkenet Frederiksberg'
               '<br/>Gl. Kongevej 99, Frederiksberg<br/>1850 København</p>')
        sider = {RS.SVANE_URL: liste, RS.SVANE_ROD + '/butikker/jylland/aalborg': aalborg,
                 RS.SVANE_ROD + '/butikker/sjaelland/frederiksberg': frb}
        dar = _dar({('Fiskene 29', '9200'): (56.9987, 9.867946, 'Aalborg SV'),
                    ('Gl. Kongevej 99', '1850'): (55.675006, 12.547228, 'Frederiksberg C')})
        with mock.patch.object(RS, '_text', new=_sider(sider)), mock.patch.object(RS, '_dar_adressepunkt', new=dar), \
                mock.patch.object(RS, 'SVANE_FORVENTET', (1, 5)):
            ud = {r['name']: r for r in RS.svane()}
        self.assertEqual(ud['Svane Køkkenet Aalborg']['street'], 'Fiskene 29')
        self.assertEqual(ud['Svane Køkkenet Frederiksberg']['lat'], 55.675006)


class TestNettoline(_Rent):
    def test_udkommenteret_og_udenlandsk_forhandler_udelades(self):
        oversigt = ('<h3>BUTIKSOVERSIGT</h3><a href="/nettoline-saeby/">Nettoline Sæby</a>'
                    '<!--<a href="/nettoline-fyn-nyborg/">Nettoline Nyborg</a>-->'
                    '<a href="/nettoline-kopavogur/">Nettoline Kopavogur</a><h2>FIND DIN LOKALE</h2>')
        saeby = '<h4>ADRESSE</h4><p>Nettoline Sæby<br>Grønnegade 22<br>9300 Sæby</p><p>CVR: 37141720</p>'
        kopa = '<h4>ADRESSE</h4><p>Nettoline Kopavogur<br>v/ Friform ehf<br>Askalind 3<br>201 Kópavogur</p>'
        sider = {RS.NETTOLINE_URL: oversigt, RS.NETTOLINE_ROD + '/nettoline-saeby/': saeby,
                 RS.NETTOLINE_ROD + '/nettoline-kopavogur/': kopa}
        with mock.patch.object(RS, '_text', new=_sider(sider)), \
                mock.patch.object(RS, '_dar_adressepunkt', new=_dar({('Grønnegade 22', '9300'): (57.33, 10.51, 'Sæby')})), \
                mock.patch.object(RS, 'NETTOLINE_FORVENTET', (1, 5)):
            ud = RS.nettoline()
        self.assertEqual([(r['name'], r['street'], r['lat']) for r in ud], [('Nettoline Sæby', 'Grønnegade 22', 57.33)])
        # en dansk side, hvis adresse ikke kan laeses, er en fejl - ikke en stille lukning
        sider[RS.NETTOLINE_ROD + '/nettoline-saeby/'] = '<h4>KONTAKT</h4><p>Nettoline Sæby</p>'
        with mock.patch.object(RS, '_text', new=_sider(sider)), mock.patch.object(RS, 'NETTOLINE_FORVENTET', (0, 5)):
            with self.assertRaisesRegex(RuntimeError, 'butikssider fejlede'):
                RS.nettoline()


class TestVordingborg(_Rent):
    def test_erhverv_webshop_og_udland_udelades(self):
        rod = 'https://www.vordingborg.com/butik/'
        oversigt = ''.join(f'<a href="{rod}{s}">x</a>' for s in
                           ('aalborg', 'erhverv-kolding', 'onlinesalg', 'malmo', 'torshavn'))
        side = ('<div itemprop="streetAddress">Løven 3</div><span itemprop="postalCode">9200</span> '
                '<span itemprop="addressLocality">Aalborg</span><div data-lat="57.0011998" data-lng="9.872333"></div>')
        with mock.patch.object(RS, '_text', new=_sider({RS.VORDINGBORG_URL: oversigt, rod + 'aalborg': side})), \
                mock.patch.object(RS, 'VORDINGBORG_FORVENTET', (1, 5)):
            ud = RS.vordingborg()
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['lat']) for r in ud],
                         [('Vordingborg Køkkenet Aalborg', 'Løven 3', '9200', 57.0012)])


class TestDesigna(_Rent):
    def test_postnr_klippes_af_gaden_og_udland_udelades(self):
        data = [{'name': ' Designa Frederikshavn', 'address': 'Maigårdsvej 11 B 9900 Frederikshavn',
                 'zipCode': '9900', 'city': 'Frederikshavn', 'latitude': '57.447399', 'longitude': '10.500805'},
                {'name': ' Designa Thorshavn', 'address': 'x 1', 'zipCode': '100', 'city': 'Tórshavn',
                 'latitude': '62.0', 'longitude': '-6.7'}]
        h = '<script>window.shopData = %s;</script>' % json.dumps(data)
        with mock.patch.object(RS, '_text', new=_sider({RS.DESIGNA_URL: h})), \
                mock.patch.object(RS, 'DESIGNA_FORVENTET', (1, 5)):
            ud = RS.designa()
        self.assertEqual([(r['name'], r['street']) for r in ud], [('Designa Frederikshavn', 'Maigårdsvej 11B')])


class TestAubo(_Rent):
    def _oversigt(self, *mk):
        return ''.join(f'<div class="marker" data-lat="{la}" data-lng="{lo}"><h4>{n}</h4>'
                       f'<a class="marker-btn" href="https://aubo.dk/find-forhandler/{s}/">Se forhandlerside</a></div>'
                       for n, s, la, lo in mk)

    def test_baastad_i_dk_boksen_udelades_men_en_dansk_side_uden_adresse_fejler(self):
        h = self._oversigt(('Vejle', 'aubo-vejle', '55.7324152', '9.5941367'),
                           ('Båstad', 'kitchen-in', '56.4267169', '12.8'))
        vejle = '<h1>AUBO Vejle</h1><h4>Adresse</h4><p>Løversysselvej 2E<br>DK-7100, Vejle</p>'
        baastad = '<h1>Kitchen In</h1><h4>Adresse</h4><p>Köpmansgatan 1<br>SE-269 36, Båstad</p>'
        rod = 'https://aubo.dk/find-forhandler/'
        with mock.patch.object(RS, '_text', new=_sider({RS.AUBO_URL: h, rod + 'aubo-vejle/': vejle,
                                                        rod + 'kitchen-in/': baastad})), \
                mock.patch.object(RS, 'AUBO_FORVENTET', (1, 5)):
            ud = RS.aubo()
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['lat']) for r in ud],
                         [('AUBO Vejle', 'Løversysselvej 2E', '7100', 55.732415)])
        with mock.patch.object(RS, '_text', new=_sider({RS.AUBO_URL: h, rod + 'aubo-vejle/': '<h1>AUBO Vejle</h1>',
                                                        rod + 'kitchen-in/': baastad})), \
                mock.patch.object(RS, 'AUBO_FORVENTET', (1, 5)):
            with self.assertRaisesRegex(RuntimeError, 'butikssider fejlede'):
                RS.aubo()


class TestTvis(_Rent):
    def test_nuxt3_henvisninger_og_land(self):
        d = [{'stores': 1}, [2, 6],
             {'name': 3, 'address': 4, 'latitude': 10, 'longitude': 11}, 'Tvis Køkken Aalborg',
             {'zip': 5, 'city': 12, 'street': 13, 'country': 14}, '9200',
             {'name': 7, 'address': 8, 'latitude': 15, 'longitude': 16}, 'Tvis Køkken Tórshavn',
             {'zip': 9, 'city': 12, 'street': 13, 'country': 17}, '100',
             56.997796, 9.86886, 'Aalborg', 'Stenbukken 18', 'DK', 62.0, -6.7, 'FO']
        h = '<script type="application/json" id="__NUXT_DATA__">%s</script>' % json.dumps(d)
        with mock.patch.object(RS, '_text', new=_sider({RS.TVIS_URL: h})), mock.patch.object(RS, 'TVIS_FORVENTET', (1, 5)):
            ud = RS.tvis()
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['lat']) for r in ud],
                         [('Tvis Køkken Aalborg', 'Stenbukken 18', '9200', 56.997796)])


class TestGetCloseststores(_Rent):
    def test_adresseformerne_og_skjulte(self):
        st = [{'StoreName': 'INVITA København', 'Address': '<p>Frederiksborggade 33, 1360 København K</p>',
               'Latitude': 55.6852608, 'Longitude': 12.5670468, 'HideOnStoreFinderPage': False},
              {'StoreName': 'INVITA Aalborg', 'Address': '<p>City Syd - Stenbukken 11, 9200 Aalborg</p>',
               'Latitude': 56.998, 'Longitude': 9.871, 'HideOnStoreFinderPage': False},
              {'StoreName': 'uno form Lyngby', 'Address': 'uno form Lyngby , Lyngby Hovedgade 82 \n2800 Lyngby\nDenmark\n',
               'Latitude': 55.768693, 'Longitude': 12.505926, 'HideOnStoreFinderPage': False},
              {'StoreName': 'Skjult', 'Address': '<p>Vej 1, 1000 København</p>', 'Latitude': 55.6, 'Longitude': 12.5,
               'HideOnStoreFinderPage': True},
              {'StoreName': 'Oslo', 'Address': 'Karl Johans gate 1, 0154 Oslo, Norway', 'Latitude': 59.9,
               'Longitude': 10.7, 'HideOnStoreFinderPage': False},
              {'StoreName': 'uno form Bornholm', 'Address': 'HTH Køkkenforum Bornholm, Åkirkebyvej 50\n3700 Rønne\nDenmark',
               'Latitude': 55.097233, 'Longitude': 14.713885, 'HideOnStoreFinderPage': False}]
        with mock.patch.object(RS, '_json', return_value={'stores': st}):
            ud = RS._getcloseststores('https://x', 'Invita', (1, 5), 'invita', RS.UNOFORM_I_ANDEN_BUTIK)
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['by']) for r in ud],
                         [('INVITA København', 'Frederiksborggade 33', '1360', 'København K'),
                          ('INVITA Aalborg', 'Stenbukken 11', '9200', 'Aalborg'),
                          ('uno form Lyngby', 'Lyngby Hovedgade 82', '2800', 'Lyngby')])


class TestJke(_Rent):
    def test_kun_butikssider_fra_sitemappet(self):
        u = 'https://jke-design.com/da/butikker/jke-aarhus'
        ld = {'@type': 'LocalBusiness', 'name': 'JKE Aarhus', 'address': {'streetAddress': 'Søren Frichs Vej 13 B',
              'postalCode': '8000', 'addressLocality': 'Aarhus C'}, 'geo': {'latitude': 56.15273, 'longitude': 10.185307}}
        h = '<script type="application/ld+json">%s</script>' % json.dumps(ld)
        with mock.patch.object(RS, '_sitemap', return_value=['https://jke-design.com/da/butikker', u,
                                                             'https://jke-design.com/da/butikker/jke-aarhus/job']), \
                mock.patch.object(RS, '_text', new=_sider({u: h})), mock.patch.object(RS, 'JKE_FORVENTET', (1, 5)):
            ud = RS.jke()
        self.assertEqual([(r['name'], r['street'], r['lat']) for r in ud], [('JKE Aarhus', 'Søren Frichs Vej 13B', 56.15273)])


class TestMultiform(_Rent):
    def test_kun_danske_forhandlere(self):
        rod = 'https://multiform.dk/forhandler/'
        oversigt = f'<a href="{rod}aarhus/">x</a><a href="{rod}antwerpen/">y</a><a href="{rod}malmoe/">z</a>'
        sider = {RS.MULTIFORM_URL: oversigt,
                 rod + 'aarhus/': '<h4>Adresse</h4><p>Søren Frichs Vej 23 A</p><p>Aarhus C, DK-8000</p><h4>Kontakt</h4>',
                 rod + 'antwerpen/': '<h4>Adresse</h4><p>BVBA Leopoldstraat 59</p><p>Antwerpen, 2000</p>',
                 rod + 'malmoe/': '<h4>Adresse</h4><p>Dockplatsen 8</p><p>Malmö, SV-211 19</p>'}
        with mock.patch.object(RS, '_text', new=_sider(sider)), mock.patch.object(RS, 'MULTIFORM_FORVENTET', (1, 5)), \
                mock.patch.object(RS, '_dar_adressepunkt', new=_dar({('Søren Frichs Vej 23A', '8000'): (56.15285, 10.184718, 'Aarhus C')})):
            ud = RS.multiform()
        self.assertEqual([(r['name'], r['street'], r['lat']) for r in ud], [('Multiform Aarhus', 'Søren Frichs Vej 23A', 56.15285)])
        sider[rod + 'aarhus/'] = '<h4>Adresse</h4><p>Aarhus C, DK-8000</p>'      # dansk, men ingen gade
        with mock.patch.object(RS, '_text', new=_sider(sider)), mock.patch.object(RS, 'MULTIFORM_FORVENTET', (0, 5)):
            with self.assertRaisesRegex(RuntimeError, 'butikssider fejlede'):
                RS.multiform()


# ------------------------------------------------------------------------------------------------ tank
class TestOlesOlie(_Rent):
    LISTE = ('<a href="/tankstationer/bygade-50-5662-haastrup.aspx">a</a>'
             '<a href="/tankstationer/oemosevej-1-5400-skovby.aspx">b</a><a href="/tankstationer/oemosevej-4-5400-skovby.aspx">c</a>'
             '<a href="/tankstationer/damhusvej-16-5750-ringe.aspx">d</a><a href="/tankstationer/oestreringvej-26-5750-ringe.aspx">e</a>')
    HQ = ('<a href="https://www.google.com/maps/place/Oles+Olie+A%2FS/@55.237555,10.4825131,17z/data=!3m1!4b1!4m6!3m5'
          '!1s0x0:0x0!8m2!3d55.237555!4d10.4825131!16s">kontor</a>')

    def _side(self, adr, link):
        return f'<h2>Tankstation – {adr}</h2><p><a href="{link}" target="_blank">Find vej</a></p>{self.HQ}'

    def test_naalen_ikke_kortudsnittet_og_dubletsider(self):
        hastrup = self._side('Bygade 50, 5662 Håstrup', 'https://www.google.com/maps/place/Oles+Olie+A%2FS+H%C3%A5strup/'
                             '@55.1721022,10.1852305,17z/data=!4m15!3d55.1721022!4d10.1878108!16s')
        skovby = self._side('Ømosevej 1, 5400 Skovby', 'https://www.google.com/maps/place/x/@55.5258465,10.0751808,17z/'
                            'data=!3d55.5258465!4d10.0777611')
        damhus = self._side('Damhusvej 16, 5750 Ringe', 'https://www.google.com/maps/place/Oles+Olie+A%2FS/'
                            '@55.2375543,10.4799499,563m/data=!3d55.237555!4d10.4825131')
        # Brenderups link er brudt HTML: attributterne er delt, og naalen staar i et andet attribut
        oestre = ('<h2>Tankstation – Østreringvej 26, 5750 Ringe</h2><a href="https://www.google.com/maps/place/Ole" '
                  's+olie="" @55.2375146,10.4806728,17z="" data="!3d55.2375146!4d10.4832531!16s" class="c">Find vej</a>'
                  + self.HQ)
        r = RS.OLESOLIE_ROD + '/tankstationer/'
        sider = {RS.OLESOLIE_URL: self.LISTE, r + 'bygade-50-5662-haastrup.aspx': hastrup,
                 r + 'oemosevej-1-5400-skovby.aspx': skovby, r + 'oemosevej-4-5400-skovby.aspx': skovby,
                 r + 'damhusvej-16-5750-ringe.aspx': damhus, r + 'oestreringvej-26-5750-ringe.aspx': oestre}
        with mock.patch.object(RS, '_text', new=_sider(sider)), mock.patch.object(RS, 'OLESOLIE_FORVENTET', (1, 8)):
            ud = {r['name']: r for r in RS.oles_olie()}
        self.assertEqual(sorted(ud), ['Oles Olie Håstrup', 'Oles Olie Ringe (Damhusvej)', 'Oles Olie Ringe (Østreringvej)',
                                      'Oles Olie Skovby'])
        self.assertEqual((ud['Oles Olie Håstrup']['lat'], ud['Oles Olie Håstrup']['lon']), (55.172102, 10.187811))
        self.assertEqual(ud['Oles Olie Ringe (Østreringvej)']['lon'], 10.483253)
        self.assertEqual(ud['Oles Olie Skovby']['lastbil'], '')


class TestGoon(unittest.TestCase):
    def _svar(self, n_bil):
        pins = [{'title': f"Go'on {i}", 'lat': '56.0\r\n', 'lng': '9.0', 'address': f'Vej {i}, 9440 Aabybro',
                 'town': 'Aabybro', 'categories': 'goon'} for i in range(n_bil)]
        pins += [{'title': "Go'on Kolding - Truck", 'lat': '55.5', 'lng': '9.4', 'address': 'Hesselly 13, 6000 Kolding',
                  'town': 'Kolding', 'categories': 'goon-truck'},
                 {'title': 'LAVPRIS Hurup Thy', 'lat': '56.7', 'lng': '8.4', 'address': 'Bredgade 15, 7760 Hurup Thy',
                  'town': 'Hurup Thy', 'categories': 'lavpris'},
                 {'title': 'YX Aarhus', 'lat': '56.1', 'lng': '10.2', 'address': '8000 Aarhus, Vandvejen 5',
                  'town': 'Aarhus', 'categories': 'partner'}]
        return ('var x = ' + json.dumps(pins) + ';').encode()

    def test_lastbil_gade_og_postnr(self):
        with mock.patch.object(S, '_raw', return_value=self._svar(3)), mock.patch.object(S, 'GOON_FORVENTET', (1, 10)):
            ud = {r['name']: r for r in S.goon()}
        self.assertNotIn('YX Aarhus', ud)
        self.assertEqual(ud["Go'on Kolding - Truck"]['lastbil'], 'ja')
        self.assertEqual((ud['LAVPRIS Hurup Thy']['brand'], ud['LAVPRIS Hurup Thy']['lastbil']), ('Lavpris', ''))
        self.assertEqual((ud["Go'on 0"]['street'], ud["Go'on 0"]['postnr'], ud["Go'on 0"]['by']), ('Vej 0', '9440', 'Aabybro'))

    def test_kappet_svar_er_en_fejl(self):
        with mock.patch.object(S, '_raw', return_value=self._svar(3)), mock.patch.object(S, 'GOON_FORVENTET', (6, 10)):
            with self.assertRaisesRegex(RuntimeError, 'forventet'):
                S.goon()


# ------------------------------------------------------------------------------------------------ dagligvarer
class TestBilligblomst(_Rent):
    def test_latlng(self):
        h = ('<script>var __CONTENT_CACHE = {"page":{"stores":[{"latlng":"56.999074,9.8665452","name":"Billigblomst '
             'Aalborg","city":"Aalborg SV","postalCode":"9200","address":"Fiskene 20"}]}};</script>')
        with mock.patch.object(RS, '_text', new=_sider({RS.BILLIGBLOMST_URL: h})), \
                mock.patch.object(RS, 'BILLIGBLOMST_FORVENTET', (1, 5)):
            ud = RS.billigblomst()
        self.assertEqual([(r['name'], r['street'], r['lat'], r['lon']) for r in ud],
                         [('Billigblomst Aalborg', 'Fiskene 20', 56.999074, 9.866545)])


# ------------------------------------------------------------------------------------------------ Bestseller
class TestBestseller(_Rent):
    def test_api_navn_uden_dobbelt_maerke_og_kun_danmark(self):
        data = [{'name': 'Vero Moda Aabenraa', 'address': {'countryCode': 'DNK', 'street': 'Ramsherred 33 a',
                 'postalCode': '6200', 'city': 'Aabenraa', 'latitude': 55.04, 'longitude': 9.42}},
                {'name': 'Aarhus - Bruuns Galleri', 'address': {'countryCode': 'DNK', 'street': 'M.P. Bruunsgade 25',
                 'postalCode': '8000', 'city': 'Aarhus C', 'latitude': 56.149, 'longitude': 10.205}},
                {'name': 'Flensburg', 'address': {'countryCode': 'DEU', 'street': 'Holm 1', 'postalCode': '24937',
                 'city': 'Flensburg', 'latitude': 54.78, 'longitude': 9.43}}]
        with mock.patch.object(RS, '_json', return_value=data), \
                mock.patch.dict(RS.BESTSELLER_API, {'Vero Moda': ('www.veromoda.com', (1, 5))}):
            ud = RS.veromoda()
        self.assertEqual([(r['name'], r['street']) for r in ud],
                         [('Vero Moda Aabenraa', 'Ramsherred 33A'), ('Vero Moda Aarhus Bruuns Galleri', 'M.P. Bruunsgade 25')])

    def test_sfcc_infoboks(self):
        locs = [{'id': '5681', 'name': 'København K - Vimmelskaftet', 'latitude': 55.67890167, 'longitude': 12.5742998,
                 'countryCode': 'DK', 'infoWindowHtml': '<div class="store-name">Pieces / København K - Vimmelskaftet</div>'
                 '<div>Vimmelskaftet 42</div><div>1161</div><div>København K</div><div>+45 1</div>'},
                {'id': '1', 'name': 'Malmö', 'latitude': 55.6, 'longitude': 13.0, 'countryCode': 'SE',
                 'infoWindowHtml': '<div>Södergatan 1</div><div>21134</div><div>Malmö</div>'}]
        import html as _h
        h = '<div class="store-locator__results__map" data-locations="%s"></div>' % _h.escape(json.dumps(locs))
        url = RS.BESTSELLER_SFCC['PIECES'][0]
        with mock.patch.object(RS, '_text', new=_sider({url: h})), \
                mock.patch.dict(RS.BESTSELLER_SFCC, {'PIECES': (url, (1, 5))}):
            ud = RS.pieces()
        self.assertEqual([(r['name'], r['street'], r['postnr'], r['by']) for r in ud],
                         [('PIECES København K Vimmelskaftet', 'Vimmelskaftet 42', '1161', 'København K')])

    def test_selected_uden_shop_in_shops(self):
        st = [{'id': '1050', 'address': 'M.P. Bruuns Gade 25', 'city': 'Aarhus C', 'latitude': 56.149399,
               'longitude': 10.2053, 'name': 'Aarhus - Bruuns Galleri', 'postalCode': '8000', 'brandName': 'Selected'},
              {'id': '2', 'address': 'Immervad 2 - 8', 'city': 'Aarhus C', 'latitude': 56.1572, 'longitude': 10.2068,
               'name': 'Magasin - Aarhus', 'postalCode': '8000', 'brandName': 'Selected'},
              {'id': '3', 'address': 'Søndergade 27', 'city': 'Aarhus C', 'latitude': 56.1543, 'longitude': 10.2071,
               'name': 'Salling - Afd. 1101-470 - Herremode', 'postalCode': '8000', 'brandName': 'Selected'}]
        payload = json.dumps('{"stores":{"findStore":"Find butik"},"x":{"stores":' + json.dumps(st) + '}}')
        h = '<script>self.__next_f.push([1,%s])</script>' % payload
        with mock.patch.object(RS, '_text', new=_sider({RS.SELECTED_URL: h})), \
                mock.patch.object(RS, 'SELECTED_FORVENTET', (1, 5)):
            ud = RS.selected()
        self.assertEqual([r['name'] for r in ud], ['SELECTED Aarhus Bruuns Galleri'])



# ------------------------------------------------------------------------------------------------ Norlys og EWII
def _lok(navn, gade, pn, lat, lon, evser):
    return {'navn': navn, 'operatoer': '', 'lat': lat, 'lon': lon,
            'adresse': {'street': gade, 'zipCode': pn, 'city': 'x'}, 'evser': evser}


class TestRoamingNorlysEwii(_Rent):
    def test_ewii_270_kw_taeller_ikke(self):
        lok = [_lok('ABC Tarm', 'Aboulevarden 70', '6880', 55.916, 8.519,
                    [('DK*EWI*E1*1', 'Ccs', 400, ''), ('DK*EWI*E1*2', 'Ccs', 400, '')]),
               _lok('DK*EWI*E2 - CP1', 'Vikkevej 2', '6990', 56.257, 8.135,
                    [('DK*EWI*E2*1', 'Ccs', 270, ''), ('DK*EWI*E2*2', 'Ccs', 270, '')])]
        with mock.patch.object(RS, '_q8truck_ladesteder', return_value=lok), \
                mock.patch.dict(RS.ROAMING_OPERATOERER, {'EWII': (('DK*EWI',), (1, 5))}):
            ud = RS.ewii()
        self.assertEqual([(r['name'], r['kw'], r['count']) for r in ud], [('ABC Tarm', 400, 2)])

    def test_udelad_holder_lokationen_ude_og_spores(self):
        lok = [_lok('Skanska A/S', 'Amager Strandvej 395', '2770', 55.635, 12.652, [('DK*NOR*E9*1', 'Ccs', 300, '')]),
               _lok('Meny Kalundborg', 'Nørre Alle 133', '4400', 55.682, 11.114,
                    [('DK*NOR*E8*1', 'Ccs', 300, ''), ('DK*NOR*E8*2', 'Ccs', 300, '')])]
        RS.KILDEFEJL_RAMT.clear()
        with mock.patch.object(RS, '_q8truck_ladesteder', return_value=lok), \
                mock.patch.dict(RS.ROAMING_OPERATOERER, {'Norlys': (('DK*NOR',), (1, 5))}), \
                mock.patch.dict(RS.NORLYS_LASTBIL, {}, clear=True):
            ud = RS.norlys_bil()
        self.assertEqual([r['name'] for r in ud], ['Meny Kalundborg'])
        self.assertIn(('Norlys', 'amager strandvej 395'), RS.KILDEFEJL_RAMT)
        self.assertFalse(any('_udelad' in r for r in ud))

    def test_kun_den_naermeste_lokation_ved_en_lastbilstation_holdes_ude(self):
        # Korsør 17-11-2026: lastbilstationen (Energivej 8B) og McDonald's (Energivej 4) ligger begge under 150 m
        # fra lastbilstationens punkt; kun lastbilanlaegget maa holdes ude.
        lastbil = {'k': ('Korsør', 'Energivej 8B, Korsør', 'Energivej 8B', '4220', 'Korsør', 55.354182, 11.141465,
                         400, 4, 'CCS')}
        lok = [_lok('Energivej 8b, Korsør', 'Energivej 8B', '4220', 55.35419, 11.14147,
                    [('DK*NOR*E1*%d' % i, 'Ccs', 400, '') for i in range(4)]),
               _lok("McDonald's - Korsør", 'Energivej 4', '4220', 55.35352, 11.14152,
                    [('DK*NOR*E2*%d' % i, 'Ccs', 400, '') for i in range(8)])]
        with mock.patch.object(RS, '_q8truck_ladesteder', return_value=lok), \
                mock.patch.dict(RS.ROAMING_OPERATOERER, {'Norlys': (('DK*NOR',), (1, 5))}), \
                mock.patch.dict(RS.NORLYS_LASTBIL, lastbil, clear=True):
            ud = RS.norlys_bil()
        self.assertEqual([(r['name'], r['count']) for r in ud], [("McDonald's - Korsør", 8)])


if __name__ == '__main__':
    unittest.main()
