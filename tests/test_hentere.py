import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

import collections
import contextlib
import gzip
import html
import http.client
import io
import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from unittest import mock

import retail_sources as RS

# Vagter i retail_sources' hentere, der kom til efter rigtige haendelser 13.-14.10.2026: Tjek's
# ustabile bladring (falske Coop-lukninger), IKEA's Esbjerg-side med Hernings data, Fastneds tomme
# kortliste, Shell Recharges antal udtag og Uno-X' Tilst-pin - og de huller i dem og i _pages'
# tolerance for fejlede butikssider, som testene fandt 14-10-2026, og fra review 14-10-2026 _pages'
# 404/410 (siden er vaek, ikke et udfald - men foerst naar den er vaek ogsaa ved genforsoeget, og hoejst
# max(1, 2 %) af siderne), omdirigeringer til en forbudt sti (vaek, ikke et stop), _sitemap's relative
# <loc> og synoptik() gennem _pages (ingen stille [] pr. side, antalsvagt). Hver test koerer den RIGTIGE
# henter mod en stub af det laveste I/O-led (_json, _text, _raw eller _shell_crawl - eller en falsk
# vaert i en urllib-opener), saa det er vagten selv, der proeves - ikke en kopi af logikken. Intet net
# (hjaelp.py spaerrer soklerne) og ingen pauser.


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


def _http_fejl(url, kode):
    """HTTPError, som urlopen rejser den, naar siden svarer `kode` - med en tom krop som fp (uden fp er
    Python 3.9's HTTPError ikke et fuldt svarobjekt)."""
    return urllib.error.HTTPError(url, kode, 'HTTP %d' % kode, http.client.HTTPMessage(), io.BytesIO(b''))


STUB_LOFT = 10      # kald af samme side; derover er det et genforsoeg uden loft


class _StubLoft(BaseException):
    """Sikkerhedsventil i side-stubbene: en BaseException, saa _pages' 'except Exception' ikke sluger den.
    Proever _pages en side igen og igen (en side, der altid svarer 404 eller 500), fejler testen i stedet
    for at haenge."""


class _SideStub:
    """_text for _pages: hver butiksside svarer med sin raekke som JSON. `fejl` = {url: n}: de foerste n
    kald fejler med URLError - 1 er et forbigaaende hik, 2 fejler ogsaa genforsoeget. `koder` = {url:
    udfald}: hvert kald derefter giver det udfald - en HTTP-status giver HTTPError, som fra urlopen (404/410
    = siden er vaek, review 14-10-2026), 'timeout' URLError og 'omdirigering' RobotsOmdirigeringForbudt
    (siden flytter til en sti, robots.txt forbyder). En tupel af udfald gaelder kun de naeste kald, ét hver
    (None = svarer), og derefter svarer siden: (404,) er en forbigaaende 404. Traadsikker."""

    def __init__(self, fejl, koder=None):
        self.fejl = dict(fejl)
        self.koder = dict(koder or {})
        self.kald = collections.Counter()
        self.laas = threading.Lock()

    def __call__(self, url, timeout=90, **kw):
        with self.laas:
            self.kald[url] += 1
            n = self.kald[url]
        if n > STUB_LOFT:
            raise _StubLoft('%s hentet %d gange - genforsoeg uden loft?' % (url, n))
        hik = self.fejl.get(url, 0)
        if n <= hik:
            raise urllib.error.URLError('timed out')
        udfald = self.koder.get(url)
        if isinstance(udfald, tuple):
            udfald = udfald[n - hik - 1] if n - hik <= len(udfald) else None
        if udfald == 'timeout':
            raise urllib.error.URLError('timed out')
        if udfald == 'omdirigering':
            raise RS.RobotsOmdirigeringForbudt('robots.txt paa kaede.invalid forbyder /soeg (omdirigering) - '
                                               'foelger ikke')
        if udfald is not None:
            raise _http_fejl(url, udfald)
        return json.dumps({'name': 'Testbutik ' + url.rstrip('/').rsplit('/', 1)[-1], 'url': url})


def _side_parse(t, u):
    """parse(tekst, url) som hos henterne: én raekke pr. side."""
    return json.loads(t)


@mock.patch.object(RS.time, 'sleep', new=_ingen_pause)
class TestPagesTolerance(_Rent):

    def _stub(self, antal, to_gange=(), en_gang=(), koder=None):
        """koder = {sidenummer: HTTP-status} (se _SideStub)."""
        urls = [_butiksside(i) for i in range(antal)]
        fejl = dict([(urls[i], 2) for i in to_gange] + [(urls[i], 1) for i in en_gang])
        return urls, _SideStub(fejl, {urls[i]: k for i, k in (koder or {}).items()})

    def _koer(self, urls, stub):
        with mock.patch.object(RS, '_text', side_effect=stub), \
                contextlib.redirect_stderr(io.StringIO()) as fejl:
            ud = RS._pages(urls, _side_parse)
        return ud, fejl.getvalue()

    @staticmethod
    def _melding(err):
        return [linje for linje in err.splitlines() if '_pages' in linje and 'fejlede to gange' in linje]

    @staticmethod
    def _vaek(err):
        """Linjerne om sider, der svarede 404/410 (review 14-10-2026)."""
        return [linje for linje in err.splitlines() if '_pages' in linje and '404/410' in linje]

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

    def test_404_og_410_er_en_side_der_er_vaek_ikke_en_fejl(self):
        """Review 14-10-2026: én doed butiks-url (404) stoppede en kaede under 50 sider HVER uge - og skjulte
        netop lukningen. 404/410 er et svar ('siden er vaek'), ikke et udfald: ingen undtagelse, ogsaa ved 12
        sider (ingen tolerance), butikkens raekke mangler blot, og stderr faar ÉN linje med '_pages' og
        '404/410', der naevner url'en. Ogsaa naar 404 foerst kommer ved genforsoeget. Siden proeves én gang til
        (anden runde i review 14-10-2026: en forbigaaende 404 blev ellers en falsk lukning) - ikke flere."""
        for navn, kode, hik in (('404', 404, ()), ('410', 410, ()), ('404 efter et hik', 404, (4,))):
            with self.subTest(navn):
                urls, stub = self._stub(12, en_gang=hik, koder={4: kode})
                ud, err = self._koer(urls, stub)
                self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[4]})
                self.assertEqual(len(ud), 11)
                self.assertEqual(stub.kald[urls[4]], 2, 'proeves én gang til (ogsaa en 404), ikke flere')
                self.assertEqual({u: n for u, n in stub.kald.items() if u != urls[4] and n != 1}, {})
                linjer = self._vaek(err)
                self.assertEqual(len(linjer), 1, err)
                self.assertIn(urls[4], linjer[0])
                self.assertEqual(err.splitlines(), linjer, 'en side, der er vaek, er ikke en fejlet side')

    def test_andre_http_fejl_er_stadig_fejlede_sider(self):
        """Review 14-10-2026 (modstykket): kun 404/410 betyder 'vaek'. 403 (blokeret), 429 (for mange kald) og
        500 (serverfejl) siger intet om butikken - de er fejlede sider som foer: proeves én gang til, og ved 12
        sider afbryder _pages med en RuntimeError, der naevner siden og statussen."""
        for kode in (403, 429, 500):
            with self.subTest(kode=kode):
                urls, stub = self._stub(12, koder={4: kode})
                with self.assertRaisesRegex(RuntimeError, '1 af 12 butikssider fejlede') as cm:
                    self._koer(urls, stub)
                self.assertIn(urls[4], str(cm.exception))
                self.assertIn('HTTP Error %d' % kode, str(cm.exception))
                self.assertEqual(stub.kald[urls[4]], 2, 'proeves én gang til, ikke flere')

    def test_404_linjen_naevner_hoejst_fem_sider(self):
        """Review 14-10-2026: linjen om sider, der er vaek, naevner antallet og op til fem url'er. 6 af 300 vaek
        (404 og 410; lige inden for graensen paa max(1, 2 %) - 7 af 100 var inden for de gamle 10 %, men kaster
        nu): de 294 andre raekker og ÉN linje med '6 af 300' og fem af de seks."""
        vaek = (0, 48, 96, 150, 222, 299)
        urls, stub = self._stub(300, koder={i: 410 if i % 48 == 0 else 404 for i in vaek})
        ud, err = self._koer(urls, stub)
        self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[i] for i in vaek})
        linjer = self._vaek(err)
        self.assertEqual(len(linjer), 1, err)
        self.assertIn('6 af 300', linjer[0])
        self.assertEqual(sum(urls[i] in linjer[0] for i in vaek), 5, linjer[0])

    def test_robots_forbud_proeves_ikke_igen(self):
        """Testene 14-10-2026: _pages proevede en side, robots.txt forbyder, igen som en sidefejl (to stop i
        rapporten for én side). Nu sendes RobotsForbudt straks videre - siden hentes én gang, henteren stopper."""
        urls = [_butiksside(i) for i in range(12)]
        kald = []

        def stub(u, timeout=60):
            kald.append(u)
            if u == urls[5]:
                raise RS.RobotsForbudt('robots.txt paa test forbyder siden - henter ikke')
            return json.dumps({'url': u})
        with mock.patch.object(RS, '_text', side_effect=stub), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(RS.RobotsForbudt):
                RS._pages(urls, _side_parse)
        self.assertEqual(kald.count(urls[5]), 1)

    def test_mange_sider_vaek_er_en_omlagt_side(self):
        """Testene 14-10-2026: uden graense gav alle 6 faste IKEA-varehussider med 404 seks falske MULIG LUKNING.
        Er flere end max(1, 2 %) af siderne vaek paa én gang - samme 2 % som for fejlede sider (review 14-10-2026;
        foer 10 %, saa 10 af 100 doede url'er blev 10 lukninger) - er siden lagt om: henteren afbryder, efter at
        hver side er proevet to gange. 12 sider: 1 vaek er en lukning, 2 afbryder; 100 sider: 2 gaar, 3 afbryder;
        266 sider (som Matas' 265): 5 gaar, 6 afbryder."""
        for n, antal, afbryder in ((12, 1, False), (12, 2, True), (100, 2, False), (100, 3, True),
                                   (266, 5, False), (266, 6, True)):
            with self.subTest(n=n, vaek=antal):
                vaek = tuple(range(0, n, n // antal))[:antal]
                urls, stub = self._stub(n, koder={i: 404 for i in vaek})
                if afbryder:
                    with self.assertRaisesRegex(RuntimeError, '%d af %d butikssider svarede 404/410.*lagt om'
                                                % (antal, n)):
                        self._koer(urls, stub)
                else:
                    ud, _ = self._koer(urls, stub)
                    self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[i] for i in vaek})
                self.assertEqual({stub.kald[urls[i]] for i in vaek}, {2}, 'dommen falder efter genforsoeget')

    def test_linjen_om_taalte_fejl_naevner_op_til_fem_sider(self):
        """Review 14-10-2026: linjen om taalte fejlede sider naevnte kun den foerste ('fx ...'), saa butikken bag
        den anden kunne staa som MULIG LUKNING uden spor i rapporten. Nu naevner linjen op til fem url'er:
        100 sider, 2 der fejler to gange -> begge; 300 sider, 6 (lige inden for 2 %) -> '6 af 300' og fem."""
        urls, stub = self._stub(100, to_gange=(7, 63))
        ud, err = self._koer(urls, stub)
        self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[7], urls[63]})
        linjer = self._melding(err)
        self.assertEqual(len(linjer), 1, err)
        self.assertIn(urls[7], linjer[0])
        self.assertIn(urls[63], linjer[0])
        fejlede = (3, 50, 101, 150, 222, 299)
        urls, stub = self._stub(300, to_gange=fejlede)
        ud, err = self._koer(urls, stub)
        self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[i] for i in fejlede})
        linjer = self._melding(err)
        self.assertEqual(len(linjer), 1, err)
        self.assertIn('6 af 300', linjer[0])
        self.assertEqual(sum(urls[i] in linjer[0] for i in fejlede), 5, linjer[0])

    def test_vaek_sider_taeller_ikke_mod_tolerancen(self):
        """Review 14-10-2026: sider, der er vaek (404/410), taeller ikke mod MAX_SIDEFEJL, og de to slags staar
        hver i sin linje. 100 sider med 2, der fejler to gange (lige inden for 2 %), og 2, der er vaek (lige inden
        for max(1, 2 %)), giver de 96 raekker - ikke en afbrydelse for '4 af 100'. Ogsaa vaek-siderne er
        proevet to gange (review 14-10-2026: kun en side, der er vaek begge gange, er vaek)."""
        urls, stub = self._stub(100, to_gange=(10, 20), koder={30: 404, 40: 410})
        ud, err = self._koer(urls, stub)
        self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[i] for i in (10, 20, 30, 40)})
        fejlet, vaek = self._melding(err), self._vaek(err)
        self.assertEqual((len(fejlet), len(vaek), len(err.splitlines())), (1, 1, 2), err)
        self.assertEqual([u for u in urls if u in fejlet[0]], [urls[10], urls[20]])
        self.assertEqual([u for u in urls if u in vaek[0]], [urls[30], urls[40]])
        self.assertEqual((stub.kald[urls[30]], stub.kald[urls[40]]), (2, 2))

    def test_forbigaaende_404_er_ikke_en_lukning(self):
        """Review 14-10-2026: en 404/410, der kun kom ved foerste forsoeg (deploy, CDN), blev en falsk MULIG
        LUKNING - siden blev ikke hentet igen. Nu proeves den én gang til i genforsoegsrunden, EFTER pausen paa
        2 s, og svarer den dér, er butikken med: alle 12 raekker, ingen undtagelse, intet paa stderr, ingen
        ekstra kald til de andre sider. Ogsaa naar halvdelen af siderne svarer 404 én gang: graensen for
        vaek-sider ('lagt om') doemmer efter genforsoeget, ikke foer."""
        for navn, koder in (('404', {4: (404,)}), ('410', {4: (410,)}),
                            ('6 af 12 med 404 én gang', {i: (404,) for i in range(0, 12, 2)})):
            with self.subTest(navn):
                urls, stub = self._stub(12, koder=koder)
                logg = []

                def tekst(u, timeout=90, **kw):
                    logg.append(('kald', u))
                    return stub(u, timeout, **kw)
                with mock.patch.object(RS.time, 'sleep', side_effect=lambda s: logg.append(('pause', s))):
                    ud, err = self._koer(urls, tekst)
                self.assertEqual({r['url'] for r in ud}, set(urls))
                self.assertEqual(len(ud), 12)
                self.assertEqual(err, '')
                igen = {urls[i] for i in koder}
                self.assertEqual({u: n for u, n in stub.kald.items() if n != 1}, dict.fromkeys(igen, 2))
                self.assertEqual([e for e in logg if e[0] == 'pause'], [('pause', 2)], 'én pause paa 2 s')
                p = logg.index(('pause', 2))
                for u in igen:
                    foer, efter = [k for k, e in enumerate(logg) if e == ('kald', u)]
                    self.assertLess(foer, p)
                    self.assertGreater(efter, p, 'genforsoeget kommer efter pausen')

    def test_404_derefter_anden_fejl_er_en_fejlet_side(self):
        """Review 14-10-2026: kun en side, der er vaek BEGGE gange, er vaek. Svarer den 404/410 foerst og fejler
        saa paa en anden maade ved genforsoeget (500, timeout), er den en fejlet side som alle andre - ved 12 sider
        (ingen tolerance) en RuntimeError, der naevner siden, og aldrig en stille lukning."""
        for navn, udfald in (('404, saa 500', (404, 500)), ('410, saa timeout', (410, 'timeout'))):
            with self.subTest(navn):
                urls, stub = self._stub(12, koder={4: udfald})
                with self.assertRaisesRegex(RuntimeError, '1 af 12 butikssider fejlede') as cm:
                    self._koer(urls, stub)
                self.assertIn(urls[4], str(cm.exception))
                self.assertEqual(stub.kald[urls[4]], 2, 'proeves én gang til, ikke flere')

    def test_omdirigering_til_forbudt_maal_er_vaek_ikke_et_stop(self):
        """Review 14-10-2026: flytter en butiksside til en sti, robots.txt forbyder (RobotsOmdirigeringForbudt fra
        _RobotsOmdirigering - en lukket butik, der sender videre til en soegeside), er siden VAEK som ved 404/410,
        ikke et stop for hele kaeden: de 11 andre raekker, ingen undtagelse, siden proeves én gang til som en 404,
        og stderr faar vaek-linjen med url'en. Den taeller ogsaa mod graensen for vaek-sider: sammen med en 404
        er det 2 af 12, og siden er lagt om. (RobotsForbudt for selve siden sendes stadig straks videre, se
        test_robots_forbud_proeves_ikke_igen.)"""
        urls, stub = self._stub(12, koder={5: 'omdirigering'})
        ud, err = self._koer(urls, stub)
        self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[5]})
        self.assertEqual(stub.kald[urls[5]], 2)
        self.assertEqual({u: n for u, n in stub.kald.items() if u != urls[5] and n != 1}, {})
        linjer = self._vaek(err)
        self.assertEqual(len(linjer), 1, err)
        self.assertIn(urls[5], linjer[0])
        self.assertEqual(err.splitlines(), linjer, 'en side, der er vaek, er ikke en fejlet side')
        urls, stub = self._stub(12, koder={5: 'omdirigering', 9: 404})
        with self.assertRaisesRegex(RuntimeError, '2 af 12 butikssider svarede 404/410.*lagt om'):
            self._koer(urls, stub)


# ------------------------------------------------------------------ 7. _pages gennem den rigtige urllib
KAEDE_VAERT = 'https://kaede.invalid'


class _FalskVaert(urllib.request.BaseHandler):
    """En falsk vaert i en urllib-opener - ingen sokkel: https_open svarer med (status, krop) eller (status,
    krop, {hoved: vaerdi}) pr. url, og urllib's egne handlere goer resten, saa en status >= 400 bliver til
    HTTPError (HTTPErrorProcessor og HTTPDefaultErrorHandler) og en 301 med Location til en omdirigering
    (openerens _RobotsOmdirigering) som fra en rigtig vaert. Ukendte url'er fejler hoejt. Traadsikker."""

    handler_order = 400          # foer urllib's egen HTTPSHandler (500), der ville aabne en sokkel

    def __init__(self, sider):
        self.sider = dict(sider)
        self.kald = collections.Counter()
        self.laas = threading.Lock()

    def https_open(self, req):
        url = req.full_url
        with self.laas:
            self.kald[url] += 1
            n = self.kald[url]
        if n > STUB_LOFT:
            raise _StubLoft('%s hentet %d gange - genforsoeg uden loft?' % (url, n))
        if url not in self.sider:
            raise AssertionError('uventet URL: ' + url)
        status, krop, *hoveder = self.sider[url]
        msg = http.client.HTTPMessage()
        for k, v in (hoveder[0] if hoveder else {}).items():
            msg[k] = v
        svar = urllib.response.addinfourl(io.BytesIO(krop), msg, url, status)
        svar.msg = 'HTTP %d' % status        # aarsagsteksten, som urllib's HTTPSHandler saetter den
        return svar


def _med_frist(fn, sek=5.0):
    """fn() i en daemon-traad: haenger den (en laas i robots-tjekket, der venter paa sig selv), fejler testen
    efter sek sekunder i stedet for at haenge suiten. fn's undtagelse gives videre."""
    ud = {}

    def koer():
        try:
            ud['svar'] = fn()
        except BaseException as e:          # gives videre nedenfor
            ud['fejl'] = e

    t = threading.Thread(target=koer)
    t.daemon = True
    t.start()
    t.join(sek)
    if t.is_alive():
        raise AssertionError('haenger efter %.0f s' % sek)
    if 'fejl' in ud:
        raise ud['fejl']
    return ud.get('svar')


@mock.patch.object(RS.time, 'sleep', new=_ingen_pause)
class TestPagesGennemUrllib(_Rent):

    def setUp(self):
        super().setUp()
        RS._ROBOTS[KAEDE_VAERT] = 'User-agent: *\nAllow: /\n'   # cachet: hentes ikke, ingen Crawl-delay
        # Robots-tjekket i _raw kan roere denne tilstand (en hentning, Crawl-delay, et stop): den er som foer
        # efter testen, og laasen er frisk, saa en haardknude her ikke rammer de naeste tests.
        for d in (RS._ROBOTS_GRUND, RS._ROBOTS_FORBIGAAENDE, RS._SIDSTE_KALD, RS._KALD_LAASE, RS._VENTET):
            self._start(mock.patch.dict(d))
        self._start(mock.patch.object(RS, '_ROBOTS_LAAS', threading.Lock()))
        self._start(mock.patch.object(RS, '_ROBOTS_HENTES', threading.local()))
        stop, omd = list(RS.ROBOTS_STOP), list(RS.OMDIRIGERING_STOP)
        self.addCleanup(lambda: RS.ROBOTS_STOP.__setitem__(slice(None), stop))
        self.addCleanup(lambda: RS.OMDIRIGERING_STOP.__setitem__(slice(None), omd))
        RS.OMDIRIGERING_STOP[:] = []
        # Uden traade: en haardknude rammer saa kun _med_frist's daemon-traad - ikke executor-traade, som
        # Python venter paa ved afslutningen.
        self._start(mock.patch.object(RS, '_map', new=lambda fn, seq, workers=8: [fn(x) for x in seq]))
        # Som retail_sources' globale opener (build_opener med _RobotsOmdirigering), med den falske vaert foran
        # urllib's HTTPSHandler. Én opener pr. test: hver bygger en SSL-kontekst (ca. 25 ms i 3.12).
        self.vaert = _FalskVaert({})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RS._RobotsOmdirigering, self.vaert)
        self._start(mock.patch.object(urllib.request, 'urlopen', new=opener.open))

    def _start(self, p):
        v = p.start()
        self.addCleanup(p.stop)
        return v

    def _side_svarer(self, kode):
        """12 butikssider paa den falske vaert; side 4 svarer `kode`. Nulstiller vaertens kald."""
        urls = [_butiksside(i) for i in range(12)]
        self.vaert.sider = {u: (200, json.dumps({'name': 'Testbutik', 'url': u}).encode()) for u in urls}
        self.vaert.sider[urls[4]] = (kode, b'<html><body>Siden findes ikke</body></html>')
        self.vaert.kald.clear()
        return urls

    def _pages(self, urls):
        return _med_frist(lambda: RS._pages(urls, _side_parse))

    def test_404_og_410_fra_urllib_er_vaek_500_er_en_fejl(self):
        """Review 14-10-2026, gennem det rigtige _text -> _raw (robots-tjek) -> urlopen med en falsk vaert i
        openeren: svarer en side 404 eller 410 - ogsaa ved genforsoeget -, svarer _pages med de 11 og melder
        url'en paa stderr; svarer den 500, er den en fejlet side som foer (to forsoeg, saa RuntimeError).
        Stubtestene ovenfor ser ikke, om _raw en dag pakker HTTPError ind i en anden undtagelse - saa blev
        hver doed url igen et udfald."""
        for kode in (404, 410):
            with self.subTest(kode=kode):
                urls = self._side_svarer(kode)
                with contextlib.redirect_stderr(io.StringIO()) as fejl:
                    ud = self._pages(urls)
                self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[4]})
                self.assertEqual(dict(self.vaert.kald), dict(dict.fromkeys(urls, 1), **{urls[4]: 2}),
                                 'side 4 to gange (genforsoeget), de andre én gang, ingen robots.txt')
                linjer = TestPagesTolerance._vaek(fejl.getvalue())
                self.assertEqual(len(linjer), 1, fejl.getvalue())
                self.assertIn(urls[4], linjer[0])
        urls = self._side_svarer(500)
        with self.assertRaisesRegex(RuntimeError, '1 af 12 butikssider fejlede') as cm:
            self._pages(urls)
        self.assertIn('HTTP Error 500', str(cm.exception))
        self.assertEqual(self.vaert.kald[urls[4]], 2, 'proeves én gang til, ikke flere')

    def test_omdirigering_til_forbudt_sti_er_vaek_forbudt_side_stopper(self):
        """Review 14-10-2026, gennem den rigtige opener med _RobotsOmdirigering: svarer side 4 med 301 til en
        soegeside, robots.txt forbyder (en lukket butik, der sender videre), er siden VAEK - _pages svarer med de
        11 og naevner url'en i vaek-linjen; maalet hentes aldrig, OMDIRIGERING_STOP faar maalet uden query-
        streng (den kan baere et token), og ROBOTS_STOP roeres ikke. Forbyder robots.txt derimod selve siden, er
        det et stop: RobotsForbudt (ikke underklassen) straks videre, siden hentes ikke, intet genforsoeg."""
        RS._ROBOTS[KAEDE_VAERT] = 'User-agent: *\nDisallow: /soeg\n'
        urls = self._side_svarer(301)
        self.vaert.sider[urls[4]] = (301, b'', {'Location': '/soeg?q=lukket&token=hemmeligt'})
        stop_foer = list(RS.ROBOTS_STOP)
        with contextlib.redirect_stderr(io.StringIO()) as fejl:
            ud = self._pages(urls)
        self.assertEqual({r['url'] for r in ud}, set(urls) - {urls[4]})
        self.assertEqual(dict(self.vaert.kald), dict(dict.fromkeys(urls, 1), **{urls[4]: 2}),
                         'side 4 to gange (som en 404), maalet aldrig')
        linjer = TestPagesTolerance._vaek(fejl.getvalue())
        self.assertEqual(len(linjer), 1, fejl.getvalue())
        self.assertIn(urls[4], linjer[0])
        self.assertTrue(RS.OMDIRIGERING_STOP)
        self.assertEqual({u for u, _ in RS.OMDIRIGERING_STOP}, {KAEDE_VAERT + '/soeg'})
        self.assertEqual(RS.ROBOTS_STOP, stop_foer, 'en omdirigering er ikke et ROBOTS-STOP')
        # Selve siden forbudt: et stop, ikke en side, der er vaek
        RS._ROBOTS[KAEDE_VAERT] = 'User-agent: *\nDisallow: /butik/004/\n'
        urls = self._side_svarer(200)
        omd_foer = list(RS.OMDIRIGERING_STOP)
        with mock.patch.object(RS.time, 'sleep') as pause:
            with self.assertRaises(RS.RobotsForbudt) as cm:
                self._pages(urls)
        self.assertIs(type(cm.exception), RS.RobotsForbudt)
        self.assertNotIn(urls[4], self.vaert.kald, 'en forbudt side hentes ikke')
        pause.assert_not_called()
        self.assertEqual([u for u, _ in RS.ROBOTS_STOP[len(stop_foer):]], [urls[4]])
        self.assertEqual(RS.OMDIRIGERING_STOP, omd_foer)


# ------------------------------------------------------------------ 8. _sitemap: relative <loc>
def _urlset(*locs):
    """Et sitemap (urlset) med disse <loc>, som bytes - som _raw giver det."""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + ''.join('<url><loc>%s</loc></url>' % s for s in locs) + '</urlset>').encode()


def _sitemapindex(*locs):
    """Et sitemapindex med disse delsitemaps som <loc>."""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + ''.join('<sitemap><loc>%s</loc></sitemap>' % s for s in locs) + '</sitemapindex>').encode()


class _SitemapStub:
    """_raw for _sitemap: {url: bytes}; en ukendt url fejler hoejt. Husker kaldene i raekkefoelge."""

    def __init__(self, filer):
        self.filer = dict(filer)
        self.kald = []

    def __call__(self, url, timeout=90, **kw):
        self.kald.append(url)
        if url not in self.filer:
            raise AssertionError('uventet URL: ' + url)
        return self.filer[url]


class TestSitemapRelativeLoc(_Rent):

    def _koer(self, url, filer):
        stub = _SitemapStub(filer)
        with mock.patch.object(RS, '_raw', side_effect=stub):
            return RS._sitemap(url), stub.kald

    def test_relative_loc_i_urlset_goeres_absolutte(self):
        """Review 14-10-2026: et urlset med relative <loc> (sitemaps.org kraever absolutte, men Plantorama har
        haft dem) gav url'er uden skema og vaert - '/butikker/x' videre til _pages gav en selv-laas i
        _robots_tilladt. Nu goeres de absolutte med urljoin mod sitemappets url, som det allerede skete i et
        sitemapindex; absolutte <loc> (ogsaa med http eller paa en anden vaert) er uaendrede."""
        sm = 'https://kaede.invalid/da/sitemap-butikker.xml'
        ud, kald = self._koer(sm, {sm: _urlset(
            '/butikker/aarhus/', 'butikker/vejle/', '//kaede.invalid/butikker/odense/',
            'https://kaede.invalid/butikker/aalborg/', 'http://kaede.invalid/butikker/horsens/',
            'https://www.kaede.invalid/butikker/kolding/?id=7')})
        self.assertEqual(ud, ['https://kaede.invalid/butikker/aarhus/',
                              'https://kaede.invalid/da/butikker/vejle/',
                              'https://kaede.invalid/butikker/odense/',
                              'https://kaede.invalid/butikker/aalborg/',
                              'http://kaede.invalid/butikker/horsens/',
                              'https://www.kaede.invalid/butikker/kolding/?id=7'])
        self.assertEqual(kald, [sm])

    def test_relative_loc_i_gzippet_delsitemap_goeres_absolutte_mod_delsitemappet(self):
        """Review 14-10-2026, i Plantoramas form: et sitemapindex med et relativt, gzippet delsitemap, hvis <loc>
        ogsaa er relative. De goeres absolutte mod DELSITEMAPPETS url, hvor de staar - ikke indexets."""
        idx = 'https://kaede.invalid/sitemap.xml'
        dl = 'https://kaede.invalid/sitemaps/butikker.xml.gz'
        ud, kald = self._koer(idx, {idx: _sitemapindex('/sitemaps/butikker.xml.gz'),
                                    dl: gzip.compress(_urlset('/butikker/aarhus/', 'odense/',
                                                              'https://kaede.invalid/butikker/aalborg/'))})
        self.assertEqual(ud, ['https://kaede.invalid/butikker/aarhus/',
                              'https://kaede.invalid/sitemaps/odense/',
                              'https://kaede.invalid/butikker/aalborg/'])
        self.assertEqual(kald, [idx, dl])


# ------------------------------------------------------------------ 9. synoptik: gennem _pages
SYNOPTIK_OVERSIGT = 'https://www.synoptik.dk/butiksoversigt'
SYNOPTIK_BUTIKKER = 'https://www.synoptik.dk/butikker/'
SYNOPTIK_BYSIDER = (6, 6) + (3,) * 12      # 14 by-sider med butik 0-47
SYNOPTIK_FOERSTE_ENKELT = 44               # enkeltbutiks-sider fra butik 44; 44-47 staar ogsaa paa en by-side


def _synoptik_enkelt(j):
    """Url'en til butik j's enkeltbutiks-side (/butikker/<by>/<butik>)."""
    return SYNOPTIK_BUTIKKER + 'testby-%02d/synoptik-%03d' % (j % 14, j)


def _synoptik_butik(j):
    """Butik j, som Synoptiks sider har den i __NEXT_DATA__ - de felter, synoptik() laeser."""
    return {'code': 'SYN%03d' % j, 'slug': 'synoptik-testby-%d' % j, 'name': 'Synoptik Testby %d' % j,
            'streetName': 'Synsvej %d' % (j + 1), 'postalCode': str(2000 + j), 'town': 'Testby',
            'lat': round(55.0 + j * 0.02, 6), 'lon': round(9.0 + j * 0.03, 6), 'country': 'DK'}


def _synoptik_html(page_props):
    """En Next.js-side med pageProps under initialProps i <script id="__NEXT_DATA__"> (se synoptik())."""
    data = {'props': {'initialProps': {'pageProps': page_props}}, 'page': '/butikker/[...slug]'}
    return ('<html><head><title>Synoptik</title></head><body><div id="__next"></div>'
            '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + '</script></body></html>')


def _synoptik_sider(n_dk):
    """{url: html} som 14-10-2026: 14 by-sider med listen i pageProps.stores (butik 0-47), en enkeltbutiks-side
    med pageProps.storeData for hver butik fra 44 til n_dk-1 (44-47 staar ogsaa paa en by-side: dedupliker paa
    code), Nuuk (country GL: frasorteres) og butiksoversigten, der linker til dem alle. n_dk=98 giver 14 + 54 + 1
    = 69 butikssider - de 14 by-sider og 55 enkeltbutiks-sider, synoptik()'s docstring beskriver."""
    sider, i = {}, 0
    for by, antal in enumerate(SYNOPTIK_BYSIDER):
        sider[SYNOPTIK_BUTIKKER + 'testby-%02d' % by] = _synoptik_html(
            {'stores': [_synoptik_butik(j) for j in range(i, i + antal)]})
        i += antal
    for j in range(SYNOPTIK_FOERSTE_ENKELT, n_dk):
        sider[_synoptik_enkelt(j)] = _synoptik_html({'storeData': _synoptik_butik(j)})
    sider[SYNOPTIK_BUTIKKER + 'nuuk/synoptik-nuuk'] = _synoptik_html({'storeData': dict(
        _synoptik_butik(999), name='Synoptik Nuuk', streetName='Imaneq 2', postalCode='3900', town='Nuuk',
        lat=64.1767, lon=-51.7361, country='GL')})
    sider[SYNOPTIK_OVERSIGT] = ('<html><body><main>' + ''.join(
        '<a href="%s">%s</a>' % (u, u.rsplit('/', 1)[-1]) for u in sorted(sider)) + '</main></body></html>')
    return sider


def _synoptik_forventet(n_dk, uden=()):
    """De raekker, synoptik() skal give for butik 0..n_dk-1 (uden butikkerne i `uden`), sorteret som
    _synoptik_raekker."""
    return sorted(({'brand': 'Synoptik', 'name': b['name'], 'street': b['streetName'], 'postnr': b['postalCode'],
                    'by': b['town'], 'lat': b['lat'], 'lon': b['lon']}
                   for b in map(_synoptik_butik, range(n_dk)) if int(b['code'][3:]) not in uden),
                  key=lambda r: r['street'])


def _synoptik_raekker(ud):
    return sorted(ud, key=lambda r: r['street'])


class _SynoptikStub:
    """_text for synoptik(): {url: html} fra _synoptik_sider. `hik` = {url: n}: de foerste n kald fejler med
    URLError('timed out') - 1 er en forbigaaende timeout, 2 fejler ogsaa _pages' genforsoeg. `koder` = {url:
    HTTP-status}: hvert kald giver HTTPError (404 = en lukket butiks side). En ukendt url fejler hoejt, og
    _StubLoft stopper et genforsoeg uden loft. Traadsikker - _pages henter med 8 traade."""

    def __init__(self, sider, hik=None, koder=None):
        self.sider = sider
        self.hik = dict(hik or {})
        self.koder = dict(koder or {})
        self.kald = collections.Counter()
        self.ukendte = []
        self.laas = threading.Lock()

    def __call__(self, url, timeout=90, **kw):
        with self.laas:
            self.kald[url] += 1
            n = self.kald[url]
        if n > STUB_LOFT:
            raise _StubLoft('%s hentet %d gange - genforsoeg uden loft?' % (url, n))
        if url not in self.sider:
            self.ukendte.append(url)
            raise AssertionError('uventet URL: ' + url)
        if n <= self.hik.get(url, 0):
            raise urllib.error.URLError('timed out')
        if url in self.koder:
            raise _http_fejl(url, self.koder[url])
        return self.sider[url]


@mock.patch.object(RS.time, 'sleep', new=_ingen_pause)
class TestSynoptikGennemPages(_Rent):

    BYSIDE = SYNOPTIK_BUTIKKER + 'testby-00'          # by-side med seks butikker (0-5), ingen af dem enkeltsider

    def _koer(self, stub):
        with mock.patch.object(RS, '_text', side_effect=stub), \
                contextlib.redirect_stderr(io.StringIO()) as fejl:
            ud = RS.synoptik()
        self.assertEqual(stub.ukendte, [])
        return ud, fejl.getvalue()

    def _kaster(self, stub, regex):
        with mock.patch.object(RS, '_text', side_effect=stub), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, regex) as cm:
                RS.synoptik()
        self.assertEqual(stub.ukendte, [])
        return str(cm.exception)

    def test_timeout_rettet_ved_genforsoeget_giver_alle_butikker(self):
        """Review 14-10-2026: synoptik() slugte enhver fejl pr. side ('except Exception: return []'), saa én timeout
        gjorde butikkerne bag siden til falske MULIG LUKNING - uden et ord i rapporten. Nu henter den gennem
        _pages: en side, der faar timeout én gang og svarer ved genforsoeget, giver alle 98 butikker (Nuuk
        frasorteret, by- og enkeltbutiks-sider dedupliceret paa code) uden melding paa stderr - for en by-side
        (seks butikker) som for en enkeltbutiks-side. Oversigten og de andre sider hentes én gang."""
        sider = _synoptik_sider(98)
        self.assertEqual(len(sider) - 1, 69, 'som 14-10-2026: 14 by-sider og 55 enkeltbutiks-sider')
        for navn, url in (('by-side', self.BYSIDE), ('enkeltbutiks-side', _synoptik_enkelt(60))):
            with self.subTest(navn):
                stub = _SynoptikStub(sider, hik={url: 1})
                ud, err = self._koer(stub)
                self.assertEqual(_synoptik_raekker(ud), _synoptik_forventet(98))
                self.assertEqual(dict(stub.kald), dict(dict.fromkeys(sider, 1), **{url: 2}),
                                 'siden med timeout to gange, alle andre (og oversigten) én gang')
                self.assertEqual(err, '')

    def test_side_der_fejler_to_gange_er_aldrig_en_stille_lukning(self):
        """Review 14-10-2026: en side, der ogsaa faar timeout ved genforsoeget, blev stille til [] - butikkerne bag
        den stod som MULIG LUKNING uden spor. synoptik() taaler ingen fejlede sider (maks_fejl=0): en byside rummer
        flere butikker, saa selv én side, der fejler to gange, afbryder med en RuntimeError, der naevner den (de
        2 % ville have taalt én byside - testene 14-10-2026)."""
        sider = _synoptik_sider(98)
        to = (_synoptik_enkelt(50), _synoptik_enkelt(90))
        stub = _SynoptikStub(sider, hik=dict.fromkeys(to, 2))
        fejl = self._kaster(stub, '2 af 69 butikssider fejlede')
        self.assertTrue(any(u in fejl for u in to), fejl)
        self.assertEqual({stub.kald[u] for u in to}, {2}, 'proeves én gang til, ikke flere')
        stub = _SynoptikStub(sider, hik={to[0]: 2})
        fejl = self._kaster(stub, '1 af 69 butikssider fejlede')
        self.assertIn(to[0], fejl)

    def test_404_koster_kun_den_lukkede_butik_to_kaster(self):
        """Review 14-10-2026: en lukket butiks side svarer 404 - ogsaa ved genforsoeget - og koster kun den butik
        (97 af 98; stderr naevner siden). Svarer to af de 69 sider 404/410, er siden lagt om (graensen er max(1,
        2 %) = 1): RuntimeError, ikke 96 raekker. Foer blev hver 404 et stille [] (docstringens '54 x 404')."""
        sider = _synoptik_sider(98)
        lukket = _synoptik_enkelt(70)
        stub = _SynoptikStub(sider, koder={lukket: 404})
        ud, err = self._koer(stub)
        self.assertEqual(_synoptik_raekker(ud), _synoptik_forventet(98, uden={70}))
        self.assertEqual(stub.kald[lukket], 2)
        linjer = TestPagesTolerance._vaek(err)
        self.assertEqual(len(linjer), 1, err)
        self.assertIn(lukket, linjer[0])
        stub = _SynoptikStub(sider, koder={lukket: 404, _synoptik_enkelt(80): 410})
        self._kaster(stub, '2 af 69 butikssider svarede 404/410.*lagt om')

    def test_antal_uden_for_SYNOPTIK_FORVENTET_kaster(self):
        """Review 14-10-2026: synoptik() havde ingen antalsvagt, saa en omlagt side med faerre butikker blev til
        falske lukninger. Nu kaster den uden for SYNOPTIK_FORVENTET (80-125; 98 i data 14-10-2026): 79 butikker,
        alle sider hentet uden fejl, giver RuntimeError - ikke 79 raekker -, og 126 ligesaa; 80 og 125 er gyldige."""
        for n, kaster in ((79, True), (80, False), (125, False), (126, True)):
            with self.subTest(n=n):
                stub = _SynoptikStub(_synoptik_sider(n))
                if kaster:
                    self._kaster(stub, r'synoptik: %d butikker, forventet \(80, 125\)' % n)
                else:
                    ud, err = self._koer(stub)
                    self.assertEqual(_synoptik_raekker(ud), _synoptik_forventet(n))
                    self.assertEqual(err, '')


if __name__ == '__main__':
    unittest.main()
