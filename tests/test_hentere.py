import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

import collections
import contextlib
import html
import io
import json
import threading
import unittest
import urllib.error
import urllib.parse
from unittest import mock

import retail_sources as RS

# Vagter i retail_sources' hentere, der kom til efter rigtige haendelser 13.-14.10.2026: Tjek's
# ustabile bladring (falske Coop-lukninger), IKEA's Esbjerg-side med Hernings data, Fastneds tomme
# kortliste, Shell Recharges antal udtag og Uno-X' Tilst-pin - og de huller i dem og i _pages'
# tolerance for fejlede butikssider, som testene fandt 14-10-2026. Hver test koerer den RIGTIGE henter
# mod en stub af det laveste I/O-led (_json, _text eller _shell_crawl), saa det er vagten selv, der
# proeves - ikke en kopi af logikken. Intet net (hjaelp.py spaerrer soklerne) og ingen pauser.


def _ingen_pause(*a, **k):
    """Erstatter time.sleep: genforsoegene skal proeves, ikke ventes paa."""
    return None


class _Rent(unittest.TestCase):
    """Nulstiller modulets caches og sidelister foer hver test og saetter dem tilbage bagefter."""

    CACHES = ('_ROBOTS', '_SHELL_CRAWL', '_Q8TRUCK_LADE_CACHE')
    SIDELISTER = ('SHELL_RECHARGE_UKENDT', 'SHELL_RECHARGE_UDEN_DATA', 'UNOX_LADER_UKENDT')

    def setUp(self):
        self._caches = {n: dict(getattr(RS, n)) for n in self.CACHES}
        self._lister = {n: list(getattr(RS, n)) for n in self.SIDELISTER}
        for n in self.CACHES:
            getattr(RS, n).clear()

    def tearDown(self):
        for n, gemt in self._caches.items():
            getattr(RS, n).clear()
            getattr(RS, n).update(gemt)
        for n, gemt in self._lister.items():
            getattr(RS, n)[:] = gemt


# ------------------------------------------------------------------ 1. Tjek: flere gennemloeb
TJEK_STORES = 'https://squid-api.tjek.com/v2/stores'


def _tjek_butik(i):
    """Én butik i Tjek's format - de felter, _tjek laeser."""
    return {'id': 'T%03d' % i, 'name': 'Testbutik %03d' % i, 'street': 'Testvej %d' % i,
            'zip_code': str(2000 + i), 'city': 'Testby', 'country': {'id': 'DK'},
            'latitude': round(55.0 + i * 0.004, 6), 'longitude': round(9.0 + (i % 40) * 0.05, 6)}


class _TjekStub:
    """squid-api.tjek.com/v2/stores som 13-10-2026: hvert gennemloeb (offset=0 begynder et nyt) ser
    kaedens liste med sine EGNE huller. En skjult butik erstattes af naermeste synlige forgaenger, saa
    siderne stadig er fulde (100) og bladringen fortsaetter - overlap og spring, som hos Tjek."""

    def __init__(self, alle, huller=lambda g: (), ekstra=None, loft=30):
        self.alle, self.huller, self.ekstra, self.loft = alle, huller, ekstra, loft
        self.gennemloeb = 0
        self.kald = []                    # (gennemloeb, offset) i kaldraekkefoelge

    def _visning(self, g):
        skjult = set(self.huller(g))
        v = []
        for i, b in enumerate(self.alle):
            if i in skjult:
                b = self.alle[max(j for j in range(i) if j not in skjult)]
            v.append(b)
        if self.ekstra:
            v.append(self.ekstra(g))
        return v

    def __call__(self, url, timeout=90, **kw):
        p = urllib.parse.urlsplit(url)
        if '%s://%s%s' % (p.scheme, p.netloc, p.path) != TJEK_STORES:
            raise AssertionError('uventet URL: ' + url)
        q = urllib.parse.parse_qs(p.query)
        off, limit = int(q['offset'][0]), int(q['limit'][0])
        if off == 0:
            self.gennemloeb += 1
        if self.gennemloeb > self.loft:   # sikkerhedsventil: en henter uden loft maa ikke haenge testen
            raise AssertionError('_tjek stopper ikke: over %d gennemloeb' % self.loft)
        self.kald.append((self.gennemloeb, off))
        return [dict(b) for b in self._visning(self.gennemloeb)[off:off + limit]]


@mock.patch.object(RS.time, 'sleep', new=_ingen_pause)
class TestTjekGennemloeb(_Rent):

    ALLE = [_tjek_butik(i) for i in range(320)]          # 365discount: 320 butikker 13-10-2026
    GADER = {'Testvej %d' % i for i in range(320)}

    def _koer(self, stub):
        with mock.patch.object(RS, '_json', side_effect=stub):
            return RS._tjek('DWZE1w', 'Coop 365discount', forventet=(270, 380), prefiks='365discount')

    def test_ustabil_bladring_samles_og_stopper_foerst_efter_to_tomme(self):
        """13-10-2026: Tjek gav 314/308/314 af 365discounts 320 med skiftende huller (12 falske MULIG
        LUKNING); foerste rettelse stoppede efter ÉT tomt gennemloeb og gav stadig 308 i 1 af 3 koersler."""
        huller = {1: {10, 50, 120, 199, 260, 315},      # 314 af 320
                  2: {77, 120, 199, 260},               # +10, 50, 315
                  3: {88, 120, 199, 260},               # intet nyt: ét tomt gennemloeb
                  4: {150, 151},                        # +120, 199, 260 - efter et tomt
                  5: {300},                             # tomt nr. 1
                  6: {301}}                             # tomt nr. 2 -> stop
        stub = _TjekStub(self.ALLE, lambda g: huller.get(g, ()))
        ud = self._koer(stub)
        # 317 efter tredje gennemloeb ville ligge inden for forventet (270-380): kun foreningen redder det
        self.assertEqual({r['street'] for r in ud}, self.GADER)
        self.assertEqual(len(ud), 320)
        self.assertEqual(stub.gennemloeb, 6, 'skal stoppe efter to tomme gennemloeb i traek (5 og 6)')
        self.assertEqual(stub.kald, [(g, off) for g in range(1, 7) for off in (0, 100, 200, 300)])

    def test_stabil_kilde_giver_tre_gennemloeb(self):
        """Modstykket til 13-10-2026: en stabil liste giver ét fuldt og to tomme gennemloeb - ikke ét
        tomt (den foerste rettelse) og ikke flere end noedvendigt."""
        stub = _TjekStub(self.ALLE)
        ud = self._koer(stub)
        self.assertEqual(len(ud), 320)
        self.assertEqual(stub.gennemloeb, 3)

    def test_loftet_TJEK_GENNEMLOEB_overholdes(self):
        """Samme rettelse 13-10-2026: finder hvert gennemloeb noget nyt, stopper _tjek ved
        TJEK_GENNEMLOEB, saa en kilde, der aldrig falder til ro, ikke giver en endeloes koersel mod Tjek.
        Fundet af testene 14-10-2026: listen ved loftet kan vaere ufuldstaendig (falske lukninger), saa
        _tjek kaster nu RuntimeError i stedet for at svare med den - ogsaa naar kun det SIDSTE gennemloeb
        var tomt (ét tomt gennemloeb er ikke 'faldet til ro', se ovenfor)."""
        tilfaelde = (('hvert gennemloeb finder nyt', {}, lambda g: _tjek_butik(400 + g)),
                     ('kun sidste gennemloeb tomt', {1: {10, 50}, 2: {50}}, None))   # +10 i 2., +50 i 3.
        for navn, huller, ekstra in tilfaelde:
            with self.subTest(navn):
                stub = _TjekStub(self.ALLE, lambda g: huller.get(g, ()), ekstra=ekstra)
                with mock.patch.object(RS, 'TJEK_GENNEMLOEB', 4):
                    with self.assertRaisesRegex(RuntimeError, 'faldt ikke til ro'):
                        self._koer(stub)
                self.assertEqual(stub.gennemloeb, 4, 'hoejst TJEK_GENNEMLOEB gennemloeb - ogsaa naar den kaster')
                offsets = (0, 100, 200, 300)
                self.assertEqual(stub.kald, [(g, off) for g in range(1, 5) for off in offsets])

    def test_ro_praecis_ved_loftet_giver_listen(self):
        """Fundet af testene 14-10-2026 (modstykket til kastet ved loftet): er det sidste tilladte
        gennemloeb det ANDET tomme i traek, faldt listen til ro og er komplet - den bruges, intet kast."""
        stub = _TjekStub(self.ALLE, lambda g: {10, 50} if g == 1 else ())  # 2. finder resten; 3. og 4. tomme
        with mock.patch.object(RS, 'TJEK_GENNEMLOEB', 4):
            ud = self._koer(stub)
        self.assertEqual(stub.gennemloeb, 4)
        self.assertEqual({r['street'] for r in ud}, self.GADER)
        self.assertEqual(len(ud), 320)


# ------------------------------------------------------------------ 2. IKEA: dubletvagten
IKEA_OVERSIGT = 'https://www.ikea.com/dk/da/stores/planning-studios/'
IKEA_PAOP = ('esbjerg', 'herning', 'kolding', 'naestved', 'roskilde', 'vejle')
ESBJERG = IKEA_OVERSIGT + 'esbjerg/'
HERNING = IKEA_OVERSIGT + 'herning/'
KOLDING = IKEA_OVERSIGT + 'kolding/'
AALBORG = RS.IKEA_SIDER[0]
IKEA_UDFORDRING = '<html><body>Just a moment...</body></html>'    # udfordringsside, der svarer 200


def _ikea_butikker():
    """url -> storeConfig for de seks varehuse (RS.IKEA_SIDER) og seks bestillingssteder."""
    b = {}
    for k, u in enumerate(RS.IKEA_SIDER):
        by = u.rstrip('/').rsplit('/', 1)[-1].title()
        b[u] = {'name': 'IKEA ' + by, 'lat': round(55.0 + k * 0.2, 6), 'lng': round(9.0 + k * 0.3, 6),
                'address': {'street': 'Varehusvej %d' % (k + 1), 'zipCode': str(5000 + k), 'city': by}}
    for k, slug in enumerate(IKEA_PAOP):
        by = slug.title()
        b[IKEA_OVERSIGT + slug + '/'] = {
            'name': 'IKEA Plan and order point ' + by, 'lat': round(55.1 + k * 0.2, 6),
            'lng': round(8.5 + k * 0.3, 6),
            'address': {'street': 'Bestillingsvej %d' % (k + 1), 'zipCode': str(6000 + k), 'city': by}}
    return b


def _ikea_side(sc):
    """En butiksside, som ikea() parser den: storeConfig i <script type="text/hydrate">. window.ikea.geo
    (den BESOEGENDES position) staar foran, som paa den rigtige side."""
    return ('<html><head><script>window.ikea = {"geo": {"lat": 55.67594, "lng": 12.56553}};</script>'
            '</head><body><script type="text/hydrate" data-island="store">'
            + json.dumps({'props': {'page': {'storeConfig': sc}}}) + '</script></body></html>')


class _IkeaStub:
    """_text for ikea(): oversigten, de 12 butikssider og Esbjerg-URL'en, der de foerste `forkert`
    gange svarer med Hernings storeConfig (13-10-2026). `udfordring` = {url: n}: de foerste n kald til
    url'en giver IKEA_UDFORDRING (ingen storeConfig). Traadsikker - _pages henter med 8 traade."""

    def __init__(self, forkert, udfordring=None):
        self.butikker = _ikea_butikker()
        self.forkert = forkert
        self.udfordring = dict(udfordring or {})
        self.kald = collections.Counter()
        self.ukendte = []
        self.laas = threading.Lock()

    def __call__(self, url, timeout=90, **kw):
        with self.laas:
            self.kald[url] += 1
            n = self.kald[url]
        if url == IKEA_OVERSIGT:
            return '<main>' + ''.join('<a href="/dk/da/stores/planning-studios/%s/">%s</a>' % (s, s.title())
                                      for s in IKEA_PAOP + IKEA_PAOP) + '</main>'
        if url not in self.butikker:
            self.ukendte.append(url)
            raise AssertionError('uventet URL: ' + url)
        if n <= self.udfordring.get(url, 0):
            return IKEA_UDFORDRING
        sc = self.butikker[url]
        if url == ESBJERG and n <= self.forkert:
            sc = self.butikker[HERNING]
        return _ikea_side(sc)


@mock.patch.object(RS.time, 'sleep', new=_ingen_pause)
class TestIkeaDubletvagt(_Rent):

    def _koer(self, stub):
        with mock.patch.object(RS, '_text', side_effect=stub):
            return RS.ikea()

    def _er_rigtig(self, stub, ud):
        forventet = {sc['name']: sc['address']['street'] for sc in stub.butikker.values()}
        self.assertEqual({r['name']: r['street'] for r in ud}, forventet)
        self.assertEqual(len(ud), 12)
        for r in ud:
            self.assertNotIn('_url', r, 'den midlertidige _url-noegle maa ikke slippe ud af ikea()')
        self.assertEqual(stub.ukendte, [])
        self.assertEqual(stub.kald[IKEA_OVERSIGT], 1)

    def test_ingen_dublet_ingen_genhentning(self):
        """Vagten fra 13-10-2026 maa ikke koste ekstra kald: uden dublet hentes hver side én gang."""
        stub = _IkeaStub(0)
        ud = self._koer(stub)
        self._er_rigtig(stub, ud)
        self.assertEqual(set(stub.kald.values()), {1})

    def test_dublet_rettet_ved_foerste_genhentning(self):
        """13-10-2026: Esbjerg-URL'en svarede et oejeblik med Hernings data - to 'Herning', ingen Esbjerg,
        og Esbjerg stod som MULIG LUKNING. Kun de to sider hentes igen; svaret er rigtigt og uden _url."""
        stub = _IkeaStub(1)
        ud = self._koer(stub)
        self._er_rigtig(stub, ud)
        self.assertEqual((stub.kald[ESBJERG], stub.kald[HERNING]), (2, 2))
        self.assertEqual({u: n for u, n in stub.kald.items() if u not in (ESBJERG, HERNING) and n != 1}, {})

    def test_dublet_rettet_foerst_ved_anden_genhentning(self):
        """Review 14-10-2026: den SIDSTE genhentning blev ikke tjekket igen. Retter anden genhentning
        dubletten, skal svaret bruges - ikke kaste paa et foraeldet dublet-fund."""
        stub = _IkeaStub(2)
        ud = self._koer(stub)
        self._er_rigtig(stub, ud)
        self.assertEqual(stub.kald[ESBJERG], 3)

    def test_vedvarende_dublet_kaster_efter_to_genhentninger(self):
        """Review 14-10-2026: er dubletten der efter sidste genhentning, er det en kildefejl - RuntimeError,
        aldrig en liste, hvor Esbjerg ser lukket ud. Hoejst to genhentninger (3 kald i alt)."""
        stub = _IkeaStub(99)
        with mock.patch.object(RS, '_text', side_effect=stub):
            with self.assertRaisesRegex(RuntimeError, 'samme butik'):
                RS.ikea()
        self.assertEqual((stub.kald[ESBJERG], stub.kald[HERNING]), (3, 3))
        self.assertEqual(stub.ukendte, [])

    def test_side_uden_storeConfig_to_gange_kaster(self):
        """Fundet af testene 14-10-2026: en side uden storeConfig (fx en udfordringsside, der svarer 200)
        var 'ingen butik' - ikea() svarede med 11 af 12, og butikken stod som MULIG LUKNING. Nu er den en
        fejlet side: _pages proever den én gang til og afbryder saa - aldrig 11 raekker."""
        for url in (AALBORG, KOLDING):                    # et varehus og et bestillingssted
            with self.subTest(url):
                stub = _IkeaStub(0, udfordring={url: 99})
                with mock.patch.object(RS, '_text', side_effect=stub):
                    with self.assertRaisesRegex(RuntimeError, '1 af 12 butikssider fejlede') as cm:
                        RS.ikea()
                self.assertIn(url, str(cm.exception), 'fejlen skal naevne siden')
                self.assertEqual(stub.kald[url], 2, 'én genhentning, ikke flere')
                self.assertEqual({u: n for u, n in stub.kald.items() if u != url and n != 1}, {})
                self.assertEqual(stub.ukendte, [])

    def test_side_uden_storeConfig_rettet_ved_genforsoeget(self):
        """Fundet af testene 14-10-2026: er udfordringssiden vaek ved _pages' genforsoeg, er svaret alle 12
        butikker - uden _url, uden melding paa stderr og uden ekstra kald til de andre sider."""
        for url in (AALBORG, KOLDING):
            with self.subTest(url):
                stub = _IkeaStub(0, udfordring={url: 1})
                with contextlib.redirect_stderr(io.StringIO()) as fejl:
                    ud = self._koer(stub)
                self._er_rigtig(stub, ud)
                self.assertEqual(stub.kald[url], 2)
                self.assertEqual({u: n for u, n in stub.kald.items() if u != url and n != 1}, {})
                self.assertEqual(fejl.getvalue(), '')


# ------------------------------------------------------------------ 3. Fastned: tom/kort kortliste
FASTNED_VAERT = 'https://www.fastnedcharging.com'
FASTNED_API = RS.FASTNED_STATION.split('%s')[0]


def _fastned_liste(n_udland, dk=7):
    """data-locations: `dk` danske stationer + `n_udland` i Holland (uden for Danmark-kassen)."""
    return ([{'id': 'dk-%d' % i, 'status': 'OPEN',
              'coordinates': {'latitude': round(55.2 + i * 0.15, 6), 'longitude': round(9.2 + i * 0.25, 6)}}
             for i in range(dk)] +
            [{'id': 'nl-%d' % i, 'status': 'OPEN',
              'coordinates': {'latitude': round(52.0 + i * 0.001, 6), 'longitude': round(4.9 + i * 0.001, 6)}}
             for i in range(n_udland)])


def _fastned_side(liste):
    """/en/locations: hele listen HTML-escapet i attributten data-locations."""
    return ('<html><body><div class="locations-map" data-locations="'
            + html.escape(json.dumps(liste), quote=True) + '" data-zoom="7"></div></body></html>')


FASTNED_GOD = _fastned_side(_fastned_liste(320))        # 327 stationer (13-10-2026: 451 i Europa)
FASTNED_KORT = _fastned_side(_fastned_liste(100))       # 107 - men alle 7 danske er med
FASTNED_TOM = _fastned_side([])                         # data-locations="[]"
FASTNED_NAVNE = sorted('Fastned Teststation %d' % i for i in range(7))


class _FastnedStub:
    """_text (stationslisten: svar nr. 1, 2, 3 ...; det sidste gentages) og _json (stationsdetaljen)."""

    def __init__(self, sider):
        self.sider = sider
        self.liste_kald, self.station_kald, self.ukendte = [], [], []
        self.laas = threading.Lock()

    def text(self, url, timeout=90, **kw):
        if url.split('?')[0] != RS.FASTNED_LISTE:
            self.ukendte.append(url)
            raise AssertionError('uventet URL: ' + url)
        self.liste_kald.append(url)
        return self.sider[min(len(self.liste_kald), len(self.sider)) - 1]

    def json(self, url, timeout=90, **kw):
        sid = url[len(FASTNED_API):].split('/')[0] if url.startswith(FASTNED_API) else ''
        if not sid.startswith('dk-'):
            self.ukendte.append(url)
            raise AssertionError('uventet URL: ' + url)
        with self.laas:
            self.station_kald.append(sid)
        i = int(sid[3:])
        return {'id': sid, 'name': 'Fastned Teststation %d' % i, 'address': 'Testvej %d' % i,
                'city': 'Testby', 'country': 'DNK', 'status': 'OPEN',
                'connectors': [{'name': 'CCS', 'power': 400, 'total': 8},
                               {'name': 'CHADEMO', 'power': 50, 'total': 1}]}


@mock.patch.object(RS.time, 'sleep', new=_ingen_pause)
class TestFastnedGenforsoeg(_Rent):

    def setUp(self):
        super().setUp()
        # robots.txt som 13-10-2026 ('User-agent: * / Allow: /') - lagt i cachen, saa intet hentes
        RS._ROBOTS[FASTNED_VAERT] = 'User-agent: *\nAllow: /\n'

    def _koer(self, stub):
        with mock.patch.object(RS, '_text', side_effect=stub.text), \
                mock.patch.object(RS, '_json', side_effect=stub.json), \
                mock.patch.object(RS.time, 'sleep') as pause:
            ud = RS.fastned()
        self.assertEqual(stub.ukendte, [])
        return ud, pause

    def test_god_liste_hentes_een_gang(self):
        """Modstykket til genforsoegene fra 13-10-2026: en fuld liste hentes én gang, uden pause."""
        stub = _FastnedStub([FASTNED_GOD])
        ud, pause = self._koer(stub)
        self.assertEqual(sorted(r['name'] for r in ud), FASTNED_NAVNE)
        self.assertEqual(len(stub.liste_kald), 1)
        pause.assert_not_called()

    def test_tom_liste_proeves_igen_med_cache_buster(self):
        """13-10-2026 kl. 11.35 svarede /en/locations i 2 af 3 kald med data-locations="[]". Et tomt svar
        hentes igen - efter pause og med cache-buster - og den fulde liste paa andet forsoeg bruges."""
        stub = _FastnedStub([FASTNED_TOM, FASTNED_GOD])
        ud, pause = self._koer(stub)
        self.assertEqual(sorted(r['name'] for r in ud), FASTNED_NAVNE)
        self.assertEqual(len(stub.liste_kald), 2)
        self.assertNotIn('?_=', stub.liste_kald[0])
        self.assertIn('?_=', stub.liste_kald[1], 'genforsoeget skal have cache-buster')
        pause.assert_called_with(15)

    def test_kort_liste_proeves_igen_og_tredje_forsoeg_bruges(self):
        """13-10-2026: siden svarede ogsaa med en delvis liste. Under FASTNED_MIN_STATIONER er den ikke
        brugbar, selv om de danske stationer staar i den; den fulde liste paa tredje forsoeg bruges."""
        stub = _FastnedStub([FASTNED_TOM, FASTNED_KORT, FASTNED_GOD])
        ud, _ = self._koer(stub)
        self.assertEqual(sorted(r['name'] for r in ud), FASTNED_NAVNE)
        self.assertEqual(len(stub.liste_kald), 3)

    def test_vedvarende_tom_eller_kort_liste_kaster(self):
        """13-10-2026: er listen stadig tom eller kort efter tre forsoeg, er kilden i stykker - RuntimeError,
        aldrig [] eller en halv liste, som refresh_retail ville melde som lukninger."""
        for navn, side in (('tom', FASTNED_TOM), ('kort', FASTNED_KORT)):
            with self.subTest(navn):
                stub = _FastnedStub([side])
                with mock.patch.object(RS, '_text', side_effect=stub.text), \
                        mock.patch.object(RS, '_json', side_effect=stub.json):
                    with self.assertRaisesRegex(RuntimeError, 'stationer i listen'):
                        RS.fastned()
                self.assertEqual(len(stub.liste_kald), 3)
                self.assertEqual(stub.station_kald, [])
                self.assertEqual(stub.ukendte, [])

    def test_ingen_pause_efter_tredje_forsoeg(self):
        """Fundet af testene 14-10-2026: efter TREDJE mislykkede forsoeg ventede fastned() 15 s mere, foer
        den kastede - en pause uden et forsoeg efter. Nu praecis to pauser: mellem 1. og 2. og mellem 2. og 3."""
        for navn, side in (('tom', FASTNED_TOM), ('kort', FASTNED_KORT)):
            with self.subTest(navn):
                stub = _FastnedStub([side])
                with mock.patch.object(RS, '_text', side_effect=stub.text), \
                        mock.patch.object(RS, '_json', side_effect=stub.json), \
                        mock.patch.object(RS.time, 'sleep') as pause:
                    with self.assertRaisesRegex(RuntimeError, 'stationer i listen'):
                        RS.fastned()
                self.assertEqual(pause.call_args_list, [mock.call(15), mock.call(15)])
                self.assertEqual(len(stub.liste_kald), 3)
                self.assertEqual(stub.ukendte, [])


# ------------------------------------------------------------------ 4. Shell Recharge: antal udtag
# (navn, CCS-effekter i connector_data, charging_points, med CHAdeMO, forventet count)
SHELL_ALLE_HOEJE = (
    ('SHELL TEST 400 OTTE', (400,), 8, False, 8),
    ('SHELL TEST 300+400 FIRE', (300, 400), 4, False, 4),
    ('SHELL TEST 0+300 TO', (0, 300), 2, False, 2),              # 0 = manglende vaerdi, ikke en klasse
    ('SHELL TEST 300 CHADEMO TO', (300,), 2, True, 2),
)
SHELL_ASYM = (('SHELL TEST 150+300 TO', (150, 300), 2, False, 1),)
SHELL_UAFGJORT = (
    ('SHELL TEST 150+300 FIRE', (150, 300), 4, False, ''),       # som EXPRESS VEJLE ØST: 1-3 udtag
    ('SHELL TEST 150+300 TRE', (150, 300), 3, False, ''),
    ('SHELL TEST 150+300 ET', (150, 300), 1, False, ''),
    ('SHELL TEST 150+300+400 TO', (150, 300, 400), 2, False, ''),
)
# tre klasser, men kun én >= 250 kW, paa to punkter: modstridende, ikke den asymmetriske enhed (14-10-2026)
SHELL_TRE_KLASSER = (('SHELL TEST 150+200+300 TO', (150, 200, 300), 2, False, ''),)
# tre CCS-stik paa to punkter, det tredje uden effekt: stadig kun klasserne 150 og 300, men ikke enhedens
# to stik, og stikket uden effekt kan vaere et udtag >= 250 kW (fundet af testene 14-10-2026)
SHELL_TREDJE_STIK = (('SHELL TEST 0+150+300 TO', (0, 150, 300), 2, False, ''),)
# modstykkerne: to ens hoeje CCS-stik (ikke deduplikeret) er alle hoeje; CHAdeMO er ikke et CCS-stik
SHELL_TO_ENS_HOEJE = (('SHELL TEST 300+300 TO', (300, 300), 2, False, 2),)
SHELL_ASYM_CHADEMO = (('SHELL TEST 150+300 CHADEMO TO', (150, 300), 2, True, 1),)
SHELL_AC_UDEN = 'SHELL TEST AC UDEN BELAEG'
SHELL_AC_MED = 'SHELL TEST AC MED BELAEG'


def _shell_ev(ccs, punkter, chademo=False, ac=False):
    """location.ev_charging i find.shell.com's form (laest af en gemt stationsside 13-10-2026)."""
    stik = [{'type': 'type_2_combo', 'max_power': float(p), 'status': None, 'total': None} for p in ccs]
    if chademo:
        stik.append({'type': 'tepco_chademo', 'max_power': 60.0, 'status': None, 'total': None})
    if ac:
        stik.append({'type': 'type_2', 'max_power': 22.0, 'status': None, 'total': None})
    return {'connector_data': stik, 'charging_points': punkter,
            'ocpi_evse_ids': ['DK*DCC*E%05d*%d' % (len(ccs), e) for e in range(1, punkter + 1)],
            'operator_name': ['Shell Recharge']}


def _shell_crawl_data():
    """(stationer, st_urls, detaljer) som _shell_crawl giver dem: 200 anlaeg (13-10-2026: 215), heraf
    60 med ladedata (83): de saerlige ovenfor, 25 almindelige 'CCS 300'-anlaeg og 20 150 kW-anlaeg."""
    antal_sid, antal_n = next(iter(RS.SHELL_RECHARGE_ANTAL.items()))
    anlaeg = [('S%03d' % k, navn, _shell_ev(ccs, p, ch)) for k, (navn, ccs, p, ch, _) in
              enumerate(SHELL_ALLE_HOEJE + SHELL_ASYM + SHELL_UAFGJORT + SHELL_TRE_KLASSER
                        + SHELL_TREDJE_STIK + SHELL_TO_ENS_HOEJE + SHELL_ASYM_CHADEMO)]
    anlaeg.append(('S100', SHELL_AC_UDEN, _shell_ev((300,), 8, ac=True)))
    anlaeg.append((antal_sid, SHELL_AC_MED, _shell_ev((300,), 8, chademo=True, ac=True)))
    anlaeg += [('A%03d' % k, 'SHELL TEST 300 NR %d' % k, _shell_ev((300,), 2)) for k in range(25)]
    anlaeg += [('L%03d' % k, 'SHELL TEST 150 NR %d' % k, _shell_ev((150,), 2)) for k in range(20)]
    anlaeg += [('T%03d' % k, 'SHELL TEST TANK %d' % k, None) for k in range(200 - len(anlaeg))]
    stationer, st_urls, detaljer = {}, {}, {}
    for k, (sid, navn, ev) in enumerate(anlaeg):
        u = 'https://find.shell.com/dk/fuel/locations/da_DK/%s' % sid
        stationer[sid] = {'id': sid, 'name': navn, 'link': u[len('https://find.shell.com'):],
                          'formatted_address': 'Testvej %d\n%d\nTestby\nDK' % (k + 1, 2000 + k),
                          'logo_url': 'https://find.shell.com/img/conventional-fuel-site-with-ev.svg'}
        d = {'country_code': 'DK', 'site_status': 'Active', 'name': navn, 'lat': round(55.0 + k * 0.01, 6),
             'lng': round(9.0 + k * 0.015, 6), 'fuels': ['premium_gasoline', 'premium_diesel']}
        if ev:
            d['ev_charging'] = ev
        st_urls[sid] = u
        detaljer[u] = d
    return (stationer, st_urls, detaljer), antal_n


@mock.patch.object(RS.time, 'sleep', new=_ingen_pause)
class TestShellRechargeAntal(_Rent):

    def _koer(self):
        data, self.antal_belaeg = _shell_crawl_data()
        with mock.patch.object(RS, '_shell_crawl', return_value=data) as crawl, \
                contextlib.redirect_stderr(io.StringIO()) as fejl:
            ud = RS.shell_recharge()
        crawl.assert_called_once_with('shell_recharge')
        return {r['name']: r['count'] for r in ud}, fejl.getvalue()

    def test_alle_udtag_over_250_kw_taeller_alle_punkter(self):
        """Kalibreret 13-10-2026 paa 40+ DCC-anlaeg: er alle CCS-klasser >= 250 kW, er antallet
        charging_points; effekten 0 er en manglende vaerdi (Esbjerg Oe., Viby J, Niels B), ikke en klasse."""
        antal, _ = self._koer()
        for navn, _, _, _, n in SHELL_ALLE_HOEJE:
            with self.subTest(navn):
                self.assertEqual(antal.get(navn), n)
        self.assertEqual({antal.get('SHELL TEST 300 NR %d' % k) for k in range(25)}, {2})
        self.assertFalse([n for n in antal if n.startswith('SHELL TEST 150 NR')], '150 kW hoerer ikke til laget')

    def test_asymmetrisk_150_300_paa_to_punkter_er_et_udtag(self):
        """13-10-2026: DCC's foerste lynladere (2022) er asymmetriske XCharge-enheder - 300 kW paa den ene
        side, 120/150 kW paa den anden: 'CCS 150 + CCS 300' paa 2 ladepunkter = 1 udtag >= 250 kW."""
        antal, _ = self._koer()
        for navn, _, _, _, n in SHELL_ASYM:
            self.assertEqual(antal.get(navn), n)

    def test_andre_blandinger_giver_tomt_antal(self):
        """13-10-2026 (EXPRESS VEJLE ØST: 4 punkter med 150 + 300 = 1-3 udtag): kan antallet ikke afgoeres,
        er count '' - ubevist er tomt, aldrig et gaet. Anlaegget udsendes stadig, saa effekten sammenlignes."""
        antal, _ = self._koer()
        for navn, _, _, _, n in SHELL_UAFGJORT:
            with self.subTest(navn):
                self.assertIn(navn, antal)
                self.assertEqual(antal[navn], n)

    def test_tre_klasser_paa_to_punkter_er_ikke_asymmetrisk(self):
        """Fundet af testene 14-10-2026: reglen '2 punkter, én klasse >= 250 kW = 1 udtag' gav ogsaa 1 for
        150 + 200 + 300 kW paa 2 punkter. Tre klasser paa to punkter er modstridende og ikke XCharge-
        enhedens 150/300-signatur, saa count er '' (ubevist); 150 + 300 paa 2 punkter er stadig 1."""
        antal, _ = self._koer()
        for navn, _, _, _, n in SHELL_TRE_KLASSER + SHELL_ASYM:
            with self.subTest(navn):
                self.assertIn(navn, antal, 'anlaegget udsendes stadig, saa effekten sammenlignes')
                self.assertEqual(antal[navn], n)

    def test_tredje_ccs_stik_paa_to_punkter_er_ikke_asymmetrisk(self):
        """Fundet af testene 14-10-2026: reglen '2 punkter, én klasse >= 250 kW og to klasser = 1 udtag' gav
        ogsaa 1 for 'CCS 0 + CCS 150 + CCS 300' paa 2 ladepunkter. connector_data er deduplikeret paa
        (stiktype, effekt), saa det er tre CCS-stik - ikke XCharge-enhedens to - og stikket uden effekt kan
        lige saa vel vaere et udtag >= 250 kW. Nu kraeves praecis to CCS-stik: count er '' (ubevist), og
        anlaegget udsendes stadig; 150 + 300 paa 2 punkter er stadig 1."""
        antal, _ = self._koer()
        for navn, _, _, _, n in SHELL_TREDJE_STIK + SHELL_ASYM:
            with self.subTest(navn):
                self.assertIn(navn, antal, 'anlaegget udsendes stadig, saa effekten sammenlignes')
                self.assertEqual(antal[navn], n)

    def test_to_ens_hoeje_ccs_stik_paa_to_punkter_taeller_begge(self):
        """Fundet af testene 14-10-2026 (modstykket): to CCS-stik med SAMME effekt >= 250 kW - fx hvis Shell
        holder op med at deduplikere connector_data - er alle-hoeje-reglen, ikke den asymmetriske enhed:
        begge ladepunkter taeller (count 2). Kravet om praecis to CCS-stik maa ikke goere 300 + 300 til 1."""
        antal, _ = self._koer()
        for navn, _, _, _, n in SHELL_TO_ENS_HOEJE:
            with self.subTest(navn):
                self.assertEqual(antal.get(navn), n)

    def test_chademo_er_ikke_et_ccs_stik_i_den_asymmetriske_regel(self):
        """Fundet af testene 14-10-2026 (modstykket): kravet er praecis to CCS-stik, ikke to stik i alt. Et
        CHAdeMO-stik deler side med et CCS-udtag (Esbjerg Ø.: 2 ladepunkter, OSM 2 x CCS + 1 CHAdeMO), saa
        'CCS 150 + CCS 300 + CHAdeMO' paa 2 ladepunkter er stadig den asymmetriske enhed: 1 udtag."""
        antal, _ = self._koer()
        for navn, _, _, _, n in SHELL_ASYM_CHADEMO:
            with self.subTest(navn):
                self.assertEqual(antal.get(navn), n)

    def test_ac_uden_belaeg_udsendes_ikke(self):
        """06-10-2026 (Aalborg Øst: 8 ladepunkter = 6 AC + 2 DC): med AC-stik taeller charging_points ogsaa
        AC. Uden post i SHELL_RECHARGE_ANTAL udsendes anlaegget ikke, men meldes paa stderr til rapporten."""
        antal, fejl = self._koer()
        self.assertNotIn(SHELL_AC_UDEN, antal)
        self.assertTrue([s for s in RS.SHELL_RECHARGE_UKENDT if SHELL_AC_UDEN in s])
        self.assertIn(SHELL_AC_UDEN, fejl)
        self.assertEqual(antal.get(SHELL_AC_MED), self.antal_belaeg)


# ------------------------------------------------------------------ 5. Uno-X: Tilst-pinnen
UNOX_VAERT = 'https://unoxmobility.dk'
TILST = 3000
TILST_LADERE = (56.185103, 10.123236)      # efterproevet 13-10-2026 (OSM, roamingpin, DAR Havkærvej 79)
TILST_FINDER = (56.186100, 10.120300)      # syntetisk finder-pin ca. 200 m vaek (Ertebjerg 20B: 196 m)


def _unox_post(nr, navn, lat, lon, **felter):
    """Én post i "initialStations" - de felter, unox_lader laeser."""
    p = {'stationNumber': nr, 'stationName': navn, 'stationAddress': 'Testvej %d' % nr,
         'stationZipcode': '8000', 'stationCity': 'Aarhus C', 'country': 'DK', 'brand': 'Uno-X',
         'truck': False, 'services': ['Tankning'], 'chargePointCount': 0, 'chargePointPlugs': 0,
         'active_el': False, 'latitude': lat, 'longitude': lon}
    p.update(felter)
    return p


def _unox_poster():
    """Alle bil- og truckladere i UNOX_LADER (kildens koordinat = finderens pin), fyldt op med
    tankstationer uden ladere til 360 danske poster (13-10-2026: 374) plus nogle norske.
    -> (poster, {navn: (stationsnummer, kildens koordinat)})."""
    poster, kilde = [], {}
    for k, nr in enumerate(nr for nr, p in RS.UNOX_LADER.items() if p[2] == ''):
        navn = 'Tilst (El)' if nr == TILST else 'Testlader %d' % nr
        la, lo = TILST_FINDER if nr == TILST else (round(55.2 + k * 0.03, 6), round(9.0 + k * 0.03, 6))
        kilde[navn] = (nr, (la, lo))
        poster.append(_unox_post(nr, navn, la, lo, chargePointCount=2, chargePointPlugs=4, active_el=True))
    for k, nr in enumerate(nr for nr, p in RS.UNOX_LADER.items() if p[2] == 'ja'):
        navn = 'Uno-X Truck Test %d' % nr
        la, lo = round(54.9 + k * 0.05, 6), round(8.6 + k * 0.05, 6)
        kilde[navn] = (nr, (la, lo))
        poster.append(_unox_post(nr, navn, la, lo, truck=True, services=['Tankning', 'Truckladning'],
                                 chargePointCount=1, chargePointPlugs=1))
    for i in range(360 - len(poster)):
        poster.append(_unox_post(20000 + i, 'Uno-X Tank %d' % i, round(55.5 + (i % 100) * 0.01, 6),
                                 round(10.0 + (i // 100) * 0.3, 6)))
    for i in range(15):
        poster.append(_unox_post(30000 + i, 'Uno-X Norge %d' % i, 59.9, 10.7, country='NO',
                                 stationZipcode='0150', chargePointCount=2, chargePointPlugs=4, active_el=True))
    return poster, kilde


def _unox_side(poster):
    """find-station: RSC-payloaden i self.__next_f.push-chunks. Foerste "initialStations" er tom, og den
    rigtige liste er delt over to chunks (se _flight)."""
    rsc = ('1:{"initialStations":[]}\n2:["$","div",null,{"initialStations":'
           + json.dumps(poster, ensure_ascii=False) + '}]\n')
    midt = len(rsc) // 2
    return '<html><body>' + ''.join('<script>self.__next_f.push([1,%s])</script>' % json.dumps(c)
                                    for c in (rsc[:midt], rsc[midt:])) + '</body></html>'


@mock.patch.object(RS.time, 'sleep', new=_ingen_pause)
class TestUnoxLaderPin(_Rent):

    def setUp(self):
        super().setUp()
        RS._ROBOTS[UNOX_VAERT] = 'User-Agent: *\nAllow: /\n'      # robots.txt som 06-10 og 13-10-2026

    def test_tilst_pin_overtrumfer_finderens_koordinat(self):
        """13-10-2026: finderens pin for 'Tilst (El)' (nr. 3000) staar ved Ertebjerg 20B, 196 m fra laderne
        ved REMA 1000, Havkærvej 79. UNOX_LADER_PIN erstatter kildens koordinat - kun for sit eget nummer."""
        self.assertIn(TILST, RS.UNOX_LADER, 'Tilst (El) er ikke laengere i UNOX_LADER - se testen efter')
        self.assertEqual(RS.UNOX_LADER[TILST][2], '')
        self.assertGreaterEqual(RS.UNOX_LADER[TILST][0], RS.UNOX_LADER_MIN_KW)
        poster, kilde = _unox_poster()
        kald = []

        def tekst(url, timeout=90, **kw):
            kald.append(url)
            if url != RS.UNOX_URL:
                raise AssertionError('uventet URL: ' + url)
            return _unox_side(poster)
        with mock.patch.object(RS, '_text', side_effect=tekst), contextlib.redirect_stderr(io.StringIO()):
            ud = RS.unox_lader()
        self.assertEqual(kald, [RS.UNOX_URL])
        rk = {r['name']: r for r in ud}
        self.assertEqual((rk['Tilst (El)']['lat'], rk['Tilst (El)']['lon']), TILST_LADERE)
        for navn, r in rk.items():
            nr, kilde_koord = kilde[navn]
            with self.subTest(navn):
                if nr in RS.UNOX_LADER_PIN:
                    self.assertEqual((r['lat'], r['lon']), tuple(RS.UNOX_LADER_PIN[nr]))
                else:
                    self.assertEqual((r['lat'], r['lon']), kilde_koord, 'en pin maa kun flytte sit eget nummer')


# ------------------------------------------------------------------ 6. _pages: fejlede butikssider
def _butiksside(i):
    return 'https://kaede.invalid/butik/%03d/' % i


class _SideStub:
    """_text for _pages: hver butiksside svarer med sin raekke som JSON. `fejl` = {url: n}: de foerste n
    kald fejler med URLError - 1 er et forbigaaende hik, 2 fejler ogsaa genforsoeget. Traadsikker."""

    def __init__(self, fejl):
        self.fejl = dict(fejl)
        self.kald = collections.Counter()
        self.laas = threading.Lock()

    def __call__(self, url, timeout=90, **kw):
        with self.laas:
            self.kald[url] += 1
            n = self.kald[url]
        if n <= self.fejl.get(url, 0):
            raise urllib.error.URLError('timed out')
        return json.dumps({'name': 'Testbutik ' + url.rstrip('/').rsplit('/', 1)[-1], 'url': url})


def _side_parse(t, u):
    """parse(tekst, url) som hos henterne: én raekke pr. side."""
    return json.loads(t)


@mock.patch.object(RS.time, 'sleep', new=_ingen_pause)
class TestPagesTolerance(_Rent):

    def _stub(self, antal, to_gange=(), en_gang=()):
        urls = [_butiksside(i) for i in range(antal)]
        fejl = dict([(urls[i], 2) for i in to_gange] + [(urls[i], 1) for i in en_gang])
        return urls, _SideStub(fejl)

    def _koer(self, urls, stub):
        with mock.patch.object(RS, '_text', side_effect=stub), \
                contextlib.redirect_stderr(io.StringIO()) as fejl:
            ud = RS._pages(urls, _side_parse)
        return ud, fejl.getvalue()

    @staticmethod
    def _melding(err):
        return [linje for linje in err.splitlines() if '_pages' in linje and 'fejlede to gange' in linje]

    def test_12_sider_taaler_ingen_side_der_fejler_to_gange(self):
        """Fundet af testene 14-10-2026: tolerancen var max(2, 2 %), saa IKEA (12 sider) kunne miste 2
        butikker (17 %) uden at afbryde - to falske MULIG LUKNING. Nu int(antal * MAX_SIDEFEJL): under 50
        sider taales ingen side, der ogsaa fejler ved genforsoeget."""
        urls, stub = self._stub(12, to_gange=(4,))
        with self.assertRaisesRegex(RuntimeError, '1 af 12 butikssider fejlede'):
            self._koer(urls, stub)
        self.assertEqual(stub.kald[urls[4]], 2, 'proeves én gang til, ikke flere')
        self.assertEqual({u: n for u, n in stub.kald.items() if u != urls[4] and n != 1}, {})

    def test_100_sider_taaler_2_og_melder_dem_paa_stderr(self):
        """Fundet af testene 14-10-2026: inden for 2 % (2 af 100) svarer _pages med de 98, men melder de
        fejlede sider paa stderr (havner i rapporten), for butikkerne bag dem kan staa som MULIG LUKNING."""
        urls, stub = self._stub(100, to_gange=(7, 63))
        ud, err = self._koer(urls, stub)
        self.assertEqual(len(ud), 98)
        self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[7], urls[63]})
        linjer = self._melding(err)
        self.assertEqual(len(linjer), 1, err)
        self.assertTrue(urls[7] in linjer[0] or urls[63] in linjer[0], 'meldingen skal naevne en fejlet side')

    def test_100_sider_med_3_der_fejler_to_gange_afbryder(self):
        """Fundet af testene 14-10-2026: over 2 % (3 af 100) afbryder _pages i stedet for at svare med 97."""
        urls, stub = self._stub(100, to_gange=(5, 50, 95))
        with self.assertRaisesRegex(RuntimeError, '3 af 100 butikssider fejlede'):
            self._koer(urls, stub)
        self.assertEqual({stub.kald[urls[i]] for i in (5, 50, 95)}, {2})

    def test_side_der_lykkes_ved_genforsoeget_taeller_som_god(self):
        """Fundet af testene 14-10-2026 (modstykket): kun sider, der fejler BAADE foerste gang og ved
        genforsoeget, taeller mod tolerancen. Et forbigaaende hik giver hverken afbrydelse eller melding."""
        urls, stub = self._stub(12, en_gang=(4,))
        ud, err = self._koer(urls, stub)
        self.assertEqual({r['url'] for r in ud}, set(urls))
        self.assertEqual(len(ud), 12)
        self.assertEqual(stub.kald[urls[4]], 2)
        self.assertEqual(err, '')
        # 100 sider: 3 hik + 2, der fejler to gange = 2 fejlede (inden for 2 %), ikke 5
        urls, stub = self._stub(100, to_gange=(10, 20), en_gang=(30, 40, 50))
        ud, err = self._koer(urls, stub)
        self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[10], urls[20]})
        self.assertEqual(len(ud), 98)
        self.assertEqual(len(self._melding(err)), 1, err)

    def test_graensen_gaar_ved_50_sider(self):
        """Fundet af testene 14-10-2026: int(antal * 2 %) runder NED - 49 sider taaler ingen side, der fejler
        to gange (0,98 -> 0), 50 sider taaler én (som kommentaren i _pages siger)."""
        urls, stub = self._stub(49, to_gange=(48,))
        with self.assertRaisesRegex(RuntimeError, '1 af 49 butikssider fejlede'):
            self._koer(urls, stub)
        urls, stub = self._stub(50, to_gange=(49,))
        ud, err = self._koer(urls, stub)
        self.assertEqual({r['url'] for r in ud}, set(urls[:49]))
        self.assertEqual(len(self._melding(err)), 1, err)


if __name__ == '__main__':
    unittest.main()
