import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

# Selvtest af det centrale robots.txt-tjek og request-hjaelperne (indfoert 14-10-2026, fordi 38 af 75
# ugentlige hentere ikke selv tjekkede robots.txt), af Crawl-delay-ventetiden i samme tjek, af
# genforsoegene i dawa.py og af DAR-laasen (dawa.tag_dar_laas). Efter review 14-10-2026 ogsaa af
# url-tjekket foer laasen, ROBOTS_UNDTAGET, ROBOTS_STOP, Crawl-delay-budgettet og omdirigeringerne. Efter
# anden runde af review 14-10-2026 ogsaa af OMDIRIGERING_STOP (et forbudt omdirigeringsmaal er ikke et
# ROBOTS-STOP), url'er uden query i stop-listerne, log=False for dawa._get med dawa.AV_ROBOTS_STOP og
# robots_stoppet(), genforsoeget efter et forbigaaende robots.txt-udfald (ROBOTS_GENFORSOEG) og _gql's
# DawaNede, naar den globale opener rejser RobotsForbudt.
# Al I/O er stubbet paa laveste niveau: retail_sources._text (robots.txt-hentningen i
# _robots_tilladt) eller urllib.request.urlopen - i omdirigeringstestene kun det nederste led i en
# rigtig urllib-kaede (_FalskVaert). Intet net (tests/hjaelp.py) og ingen rigtig
# Datafordeler-noegle (dawa._noegle er stubbet). Crawl-delay-testene koerer paa et simuleret ur
# (time.monotonic/time.sleep); DAR-laasen proeves i en frisk tmp-mappe mod en hjaelpeproces.

import collections
import gzip
import http.client
import io
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import urllib.response
from unittest import mock

import retail_sources as RS
import sources as S
import dawa
import refresh_data


# ---------------------------------------------------------------- stubbe
class _Svar(object):
    """Det urlopen giver tilbage: context manager med .read() og .headers.get(). Er krop en
    undtagelse, rejser .read() den (et afkortet svar opdages foerst under laesningen)."""

    def __init__(self, krop, headers=None):
        self.krop = krop
        self.headers = dict(headers or {})

    def read(self, *a):
        if isinstance(self.krop, BaseException):
            raise self.krop
        return self.krop

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_fejl(url, kode, krop=None):
    """HTTPError, som urllib rejser den. _gql laeser kroppen, saa dér gives en med (Python 3.9's
    HTTPError kan ikke .read() uden fp)."""
    return urllib.error.HTTPError(url, kode, 'HTTP %d' % kode, {},
                                  None if krop is None else io.BytesIO(krop))


class _FalskRobots(object):
    """Stub for retail_sources._text, som _robots_tilladt henter robots.txt med.
    svar: {vaert: [udfald, ...]}; et udfald er robots.txt-teksten, et heltal (HTTP-status ->
    HTTPError) eller en undtagelse. Hvert kald for samme fil tager det naeste udfald; det sidste
    gentages. Alle kald huskes i .kald. (En ukendt vaert giver KeyError, som _robots_tilladt sluger
    som 'forbudt' - derfor tjekker testene .kald og har altid ogsaa et 'tilladt'-udfald.)"""

    def __init__(self, svar):
        self.svar = dict(svar)
        self.kald = []
        self._laas = threading.Lock()

    def __call__(self, url, timeout=90, **kw):
        with self._laas:
            self.kald.append(url)
            n = self.kald.count(url)
        udfald = self.svar[url.rsplit('/robots.txt', 1)[0]]
        x = udfald[min(n, len(udfald)) - 1]
        if isinstance(x, int):
            raise _http_fejl(url, x)
        if isinstance(x, BaseException):
            raise x
        return x


def _med_frist(fn, sek=5.0, hvad='robots.txt-hentningen venter paa sin egen laas (tjekker robots.txt sig selv?)'):
    """fn() i en daemon-traad. Haenger den (en laas, der venter paa sig selv), fejler testen efter
    sek sekunder med `hvad` i stedet for at haenge hele suiten."""
    ud = {}

    def koer():
        try:
            ud['svar'] = fn()
        except BaseException as e:          # gives videre til testen nedenfor
            ud['fejl'] = e

    t = threading.Thread(target=koer)
    t.daemon = True
    t.start()
    t.join(sek)
    if t.is_alive():
        raise AssertionError('haenger efter %.0f s: %s' % (sek, hvad))
    if 'fejl' in ud:
        raise ud['fejl']
    return ud.get('svar')


T0 = 1000.0     # det simulerede urs start (time.monotonic er et vilkaarligt tal)


class _Ur(object):
    """Simuleret ur til Crawl-delay-testene; erstatter time.monotonic og time.sleep. sleep(s) venter
    ikke, men flytter uret frem til pausens start + s: sover to traade fra samme tid, vaagner de til
    samme tid, som paa et rigtigt ur. Med glimt > 0 varer hver pause et oejeblik i virkeligheden, saa
    andre traade kan naa frem til deres egen pause imens. .sovet husker hver pause."""

    def __init__(self, nu=T0):
        self.nu = nu
        self.glimt = 0.0
        self.sovet = []
        self._laas = threading.Lock()

    def monotonic(self):
        with self._laas:
            return self.nu

    def sleep(self, s):
        with self._laas:
            start = self.nu
            self.sovet.append(s)
        if self.glimt:
            threading.Event().wait(self.glimt)
        with self._laas:
            self.nu = max(self.nu, start + s)


class _Logbog(dict):
    """dict, der husker hver tildeling i .log - som RS._SIDSTE_KALD: hvornaar fik hvert kald lov."""

    def __init__(self):
        dict.__init__(self)
        self.log = []

    def __setitem__(self, k, v):
        self.log.append((k, v))
        dict.__setitem__(self, k, v)


class _Omdiriger(object):
    """Et 30x-svar i test.net til _FalskVaert: statuskoden og Location (relativ eller absolut)."""

    def __init__(self, til, kode=301):
        self.til = til
        self.kode = kode


class _FalskVaert(urllib.request.BaseHandler):
    """Det nederste led i en rigtig urllib-kaede (_kaede_som_den_installerede) i stedet for nettet: svarer
    fra test.net (fuld url -> [svar, ...]; hvert kald tager det naeste, det sidste gentages) og husker hver
    anmodning i test.anmodninger og (url, uret) i test.tider. Et svar er bytes (200), et heltal (den
    HTTP-status, tom krop), en undtagelse (rejses) eller _Omdiriger (30x med Location). Hvad en status
    betyder - fejl eller omdirigering - afgoer urllibs egne handlere ovenover, som i en rigtig koersel."""

    def __init__(self, test):
        self.test = test

    def _svar(self, req):
        url = req.full_url
        self.test.anmodninger.append(url)
        self.test.tider.append((url, self.test.ur.nu))
        koe = self.test.net.get(url)
        if not koe:
            raise AssertionError('uventet netkald i testen: ' + url)
        x = koe.pop(0) if len(koe) > 1 else koe[0]
        if isinstance(x, BaseException):
            raise x
        hoved, kode, krop = http.client.HTTPMessage(), 200, x
        if isinstance(x, _Omdiriger):
            kode, krop = x.kode, b''
            hoved['Location'] = x.til
        elif isinstance(x, int):
            kode, krop = x, b''
        svar = urllib.response.addinfourl(io.BytesIO(krop), hoved, url, kode)
        svar.msg = http.client.responses.get(kode, '')     # som HTTPHandler: HTTPErrorProcessor laeser .msg
        return svar

    http_open = https_open = _svar


def _kaede_som_den_installerede(blad):
    """-> en OpenerDirector med samme handler-klasser som den globale opener, retail_sources installerede
    ved import (urllib.request.install_opener): urllibs egen HTTPErrorProcessor og HTTPDefaultErrorHandler
    og omdirigerings-handleren (_RobotsOmdirigering). Udeladt er kun de led, der ville aabne en forbindelse
    eller en fil eller laese maskinens proxy-opsaetning; `blad` (_FalskVaert) svarer i stedet."""
    installeret = urllib.request._opener
    if installeret is None:
        raise AssertionError('retail_sources har ikke installeret en global opener (urllib.request.install_opener)')
    udelad = (urllib.request.ProxyHandler, urllib.request.UnknownHandler, urllib.request.HTTPHandler,
              urllib.request.HTTPSHandler, urllib.request.FTPHandler, urllib.request.FileHandler,
              urllib.request.DataHandler)
    kaede = urllib.request.OpenerDirector()
    for h in installeret.handlers:
        if not isinstance(h, udelad):
            kaede.add_handler(type(h)())
    kaede.add_handler(blad)
    return kaede


# Hjaelpeprocesser til DAR-laasen (sys.executable -I -c ..., filen som argument). Den ene tager laasen,
# skriver sig selv i filen, som tag_dar_laas goer, og holder den, til testen lukker dens stdin; den
# anden proever uden at vente og svarer 'fri' eller 'optaget'.
_HOLD_DAR_LAAS = '\n'.join([
    'import fcntl, os, sys',
    "f = open(sys.argv[1], 'a+')",
    'fcntl.flock(f, fcntl.LOCK_EX)',
    "f.seek(0); f.truncate(); f.write('refresh_retail.py, pid %d' % os.getpid()); f.flush()",
    "print('laast', flush=True)",
    'sys.stdin.readline()',
])
_PROEV_DAR_LAAS = '\n'.join([
    'import fcntl, sys',
    "f = open(sys.argv[1], 'a+')",
    'try:',
    '    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)',
    "    print('fri')",
    'except OSError:',
    "    print('optaget')",
])


def _afslut(p):
    """Stopper en hjaelpeproces, hvis den stadig koerer (saa slipper den laasen), og lukker roerene."""
    if p.poll() is None:
        p.kill()
    p.wait(10)
    for r in (p.stdin, p.stdout, p.stderr):
        if r is not None:
            r.close()


class _Grund(unittest.TestCase):
    """Faelles opsaetning: tom robots-cache og Crawl-delay-tilstand, ingen pauser, dummy-noegle og et
    urlopen, der kun svarer paa de adresser, testen selv har lagt i self.net (og husker alle
    anmodninger i self.anmodninger)."""

    def setUp(self):
        self.net = {}           # fuld url -> [svar, ...]; hvert kald tager det naeste, det sidste gentages
        self.anmodninger = []   # url'en paa hvert kald til urlopen, i raekkefoelge
        self._start(mock.patch.dict(RS._ROBOTS, clear=True))
        # Crawl-delay (14-10-2026): seneste kald og laasen pr. vaert er globale som cachen - tomme pr. test.
        self._start(mock.patch.dict(RS._SIDSTE_KALD, clear=True))
        self._start(mock.patch.dict(RS._KALD_LAASE, clear=True))
        # review 14-10-2026: grunden til et robots-udfald, Crawl-delay-budgettet, stop-listen og traad-
        # flaget for en igangvaerende robots.txt-hentning er ogsaa globale - friske pr. test.
        self._start(mock.patch.dict(RS._ROBOTS_GRUND, clear=True))
        self._start(mock.patch.dict(RS._VENTET, clear=True))
        self._start(mock.patch.object(RS, 'ROBOTS_STOP', []))
        self._start(mock.patch.object(RS, '_ROBOTS_HENTES', threading.local()))
        # review 14-10-2026 (anden runde): omdirigerings-stoppene, tidspunkterne for forbigaaende robots.txt-
        # udfald og Adressevaelgerens seneste robots-stop er ogsaa globale - friske pr. test.
        self._start(mock.patch.object(RS, 'OMDIRIGERING_STOP', []))
        self._start(mock.patch.dict(RS._ROBOTS_FORBIGAAENDE, clear=True))
        self._start(mock.patch.object(dawa, 'AV_ROBOTS_STOP', None))
        # En frisk laas pr. test: gaar koden i haardknude (robots.txt-hentningen venter paa sin egen
        # laas), sidder kun denne fast - ikke den, de naeste tests bruger.
        self._start(mock.patch.object(RS, '_ROBOTS_LAAS', threading.Lock()))
        self._start(mock.patch.object(dawa, '_noegle', return_value='TESTNOEGLE'))
        # RS.time og dawa.time er samme time-modul: én patch fjerner alle genforsoegs-pauser.
        self.sove = self._start(mock.patch.object(RS.time, 'sleep'))
        self.urlopen = self._start(mock.patch.object(urllib.request, 'urlopen', side_effect=self._urlopen))

    def _start(self, p):
        v = p.start()
        self.addCleanup(p.stop)
        return v

    def _urlopen(self, req, timeout=None, **kw):
        url = req.full_url if isinstance(req, urllib.request.Request) else req
        self.anmodninger.append(url)
        koe = self.net.get(url)
        if not koe:
            raise AssertionError('uventet netkald i testen: ' + url)
        x = koe.pop(0) if len(koe) > 1 else koe[0]
        if isinstance(x, BaseException):
            raise x
        return x if isinstance(x, _Svar) else _Svar(x)


# ---------------------------------------------------------------- robots.txt: svarkoder
class RobotsStatus(_Grund):
    """Hvad et svar paa robots.txt betyder (RFC 9309 2.3.1.3 og 2.3.1.4)."""

    def _spoerg(self, udfald, sti='/side'):
        """-> (tilladt?, antal hentninger af robots.txt) for en ny vaert med disse udfald."""
        RS._ROBOTS.clear()
        f = _FalskRobots({'https://v.example': udfald})
        with mock.patch.object(RS, '_text', f):
            ja = RS._robots_tilladt('https://v.example' + sti)
        return ja, len(f.kald)

    def test_4xx_er_ingen_regler_men_401_403_429_er_blokering(self):
        """4xx = ingen regler, men 401/403/429 er en blokering: sport24.dk svarede 403 paa alt, ogsaa
        robots.txt (30-09-2026), og en blokering omgaas ikke. Afgoeres paa ét kald."""
        for kode in (400, 404, 410):
            with self.subTest(kode=kode):
                self.assertEqual(self._spoerg([kode]), (True, 1))
        for kode in (401, 403, 429):
            with self.subTest(kode=kode):
                self.assertEqual(self._spoerg([kode]), (False, 1))
        self.sove.assert_not_called()

    def test_5xx_timeout_og_308_to_gange_er_forbudt(self):
        """5xx, timeout og afbrudt forbindelse to gange = alt forbudt (RFC 9309 2.3.1.4; regel fra 30-09-2026,
        genforsoeg fra 14-10-2026); en 308, som urllib i 3.9 ikke foelger, ligesaa - aldrig 'ingen regler'."""
        for udfald in (500, 503, 308, socket.timeout('timed out'),
                       urllib.error.URLError('forbindelsen blev afbrudt'),
                       ConnectionResetError(54, 'Connection reset by peer')):
            with self.subTest(udfald=repr(udfald)):
                self.sove.reset_mock()
                self.assertEqual(self._spoerg([udfald]), (False, 2))
                self.assertTrue(self.sove.called)       # en pause foer genforsoeget

    def test_et_udfald_og_saa_svar_bruger_svaret(self):
        """Ét udfald (500 eller timeout) og saa robots.txt: filens regler gaelder. Vaerten maa ikke
        regnes som forbudt hele koerslen paa ét udfald (ét genforsoeg, 14-10-2026)."""
        tekst = 'User-agent: *\nDisallow: /privat/\n'
        for foerst in (500, socket.timeout('timed out')):
            with self.subTest(foerst=repr(foerst)):
                self.assertEqual(self._spoerg([foerst, tekst], '/butikker'), (True, 2))
                self.assertEqual(self._spoerg([foerst, tekst], '/privat/x'), (False, 2))


# ---------------------------------------------------------------- robots.txt: RFC 9309-matchning
class RobotsRegler(_Grund):
    """Matchningen i _robots_tilladt (laest i haanden efter RFC 9309, ikke urllib.robotparser)."""

    def _afgoer(self, robots, stier):
        """-> {sti: tilladt?} paa én vaert med denne robots.txt."""
        RS._ROBOTS.clear()
        with mock.patch.object(RS, '_text', _FalskRobots({'https://r.example': [robots]})):
            return {s: RS._robots_tilladt('https://r.example' + s) for s in stier}

    def test_laengste_match_vinder_uanset_raekkefoelge(self):
        """Laengste match vinder, ikke foerste: urllib.robotparser ignorerede Allow med laengste match
        (goon.nu, 30-09-2026; WordPress' /wp-admin/ + Allow: /wp-admin/admin-ajax.php)."""
        for robots in ('User-agent: *\nDisallow: /a\nAllow: /a/b\n',
                       'User-agent: *\nAllow: /a/b\nDisallow: /a\n'):
            with self.subTest(robots=robots):
                self.assertEqual(self._afgoer(robots, ['/a/b/c', '/a/x', '/b']),
                                 {'/a/b/c': True, '/a/x': False, '/b': True})
        wp = 'User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\n'
        ajax = '/wp-admin/admin-ajax.php?action=msb_map_pins'
        self.assertEqual(self._afgoer(wp, [ajax, '/wp-admin/options.php']),
                         {ajax: True, '/wp-admin/options.php': False})

    def test_lige_lange_regler_allow_vinder(self):
        """Lige lange Allow og Disallow: Allow vinder (RFC 9309 2.2.2), uanset hvilken der staar foerst."""
        for robots in ('User-agent: *\nDisallow: /p\nAllow: /p\nDisallow: /p/skjult\n',
                       'User-agent: *\nAllow: /p\nDisallow: /p\nDisallow: /p/skjult\n'):
            with self.subTest(robots=robots):
                self.assertEqual(self._afgoer(robots, ['/p/q', '/p/skjult/1']),
                                 {'/p/q': True, '/p/skjult/1': False})

    def test_stjerne_dollar_og_forespoergsel(self):
        """'*' og '$', og forespoergslen hoerer med til stien: oil-tankstationer.dk's 'Disallow: /*?id=*'
        forbyder finderens /index.php?id=158&... (01-10-2026)."""
        robots = 'User-agent: *\nAllow: /\nDisallow: /*?id=*\nDisallow: /*.pdf$\n'
        id_url = '/index.php?id=158&type=89657201'
        self.assertEqual(
            self._afgoer(robots, [id_url, '/index.php?side=2', '/filer/a.pdf', '/filer/a.pdf?v=2', '/filer/a.pdfx']),
            {id_url: False, '/index.php?side=2': True, '/filer/a.pdf': False, '/filer/a.pdf?v=2': True,
             '/filer/a.pdfx': True})

    def test_claude_gruppe_forbyder_selv_om_stjerne_tillader(self):
        """En Claude-gruppe forbyder, selv om '*' tillader (thansen.dk; normalstores.com 15-09-2026), og
        '*' gaelder ogsaa, naar Claude-gruppen tillader - den strengeste vinder. Andre botter ikke."""
        for agent in ('ClaudeBot', 'Claude-User', 'anthropic-ai'):
            with self.subTest(agent=agent):
                robots = 'User-agent: *\nAllow: /\n\nUser-agent: %s\nDisallow: /butikker\n' % agent
                self.assertEqual(self._afgoer(robots, ['/butikker', '/om']), {'/butikker': False, '/om': True})
        self.assertEqual(self._afgoer('User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n', ['/x']),
                         {'/x': True})
        self.assertEqual(self._afgoer('User-agent: ClaudeBot\nAllow: /\n\nUser-agent: *\nDisallow: /kurv/\n',
                                      ['/kurv/1', '/butikker']),
                         {'/kurv/1': False, '/butikker': True})

    def test_user_agent_linjer_i_traek_deler_regler(self):
        """Flere User-agent-linjer i traek er én gruppe (RFC 9309 2.2.1); en User-agent efter regler
        starter en ny. ClaudeBot foerst i en faelles gruppe maa ikke staa uden regler."""
        self.assertEqual(self._afgoer('User-agent: ClaudeBot\nUser-agent: GPTBot\nDisallow: /privat/\n',
                                      ['/privat/x', '/b']), {'/privat/x': False, '/b': True})
        self.assertEqual(self._afgoer('User-agent: ClaudeBot\nDisallow: /privat/\nUser-agent: GPTBot\nDisallow: /\n',
                                      ['/b', '/privat/y']), {'/b': True, '/privat/y': False})

    def test_tom_disallow_og_kommentarer(self):
        """'Disallow:' uden sti tillader alt (normalstores.com 30-09-2026: 'User-agent: * / Disallow:'),
        og en '#'-kommentar hoerer ikke til stien eller agenten."""
        self.assertEqual(self._afgoer('User-agent: *\nDisallow:\n', ['/', '/butikker']),
                         {'/': True, '/butikker': True})
        self.assertEqual(self._afgoer('User-agent: * # alle\nDisallow: /privat/ # ikke her\n', ['/privat/x', '/b']),
                         {'/privat/x': False, '/b': True})

    def test_bom_foran_foerste_linje(self):
        """En UTF-8-BOM foran 'User-agent: ClaudeBot' gjorde forbuddet usynligt, og stien blev meldt
        tilladt (30-09-2026; ligeher.nu og pub.fvst.dk leverer filer med BOM)."""
        self.assertEqual(self._afgoer('\ufeffUser-agent: ClaudeBot\r\nDisallow: /privat/\r\n', ['/privat/x', '/side']),
                         {'/privat/x': False, '/side': True})

    def test_procentkodning_normaliseres_i_regel_og_sti(self):
        """RFC 9309 2.2.2: regel og sti sammenlignes procent-normaliseret. 'Disallow: /butik/\u00e6ble' forbyder
        baade /butik/%C3%A6ble og /butik/\u00e6ble, 'Disallow: /%7Eadmin' forbyder /~admin, og %c3%a6 er
        %C3%A6 - men %2F afkodes ikke (/a%2Fb er ikke /a/b). Foer blev de kodede stier meldt TILLADT
        (fundet af testene 14-10-2026)."""
        self.assertEqual(self._afgoer('User-agent: *\nDisallow: /butik/\u00e6ble\n',
                                      ['/butik/%C3%A6ble', '/butik/\u00e6ble', '/butik/%c3%a6ble', '/butik/banan']),
                         {'/butik/%C3%A6ble': False, '/butik/\u00e6ble': False, '/butik/%c3%a6ble': False,
                          '/butik/banan': True})
        self.assertEqual(self._afgoer('User-agent: *\nDisallow: /%7Eadmin\n', ['/~admin', '/%7eadmin/x', '/admin']),
                         {'/~admin': False, '/%7eadmin/x': False, '/admin': True})
        self.assertEqual(self._afgoer('User-agent: *\nDisallow: /%c3%a6\n', ['/%C3%A6', '/\u00e6', '/a']),
                         {'/%C3%A6': False, '/\u00e6': False, '/a': True})
        self.assertEqual(self._afgoer('User-agent: *\nDisallow: /a%2Fb\n', ['/a/b', '/a%2Fb', '/a%2fb']),
                         {'/a/b': True, '/a%2Fb': False, '/a%2fb': False})
        self.assertEqual(self._afgoer('User-agent: *\nDisallow: /*?by=K\u00f8benhavn\n',
                                      ['/find?by=K%C3%B8benhavn', '/find?by=Aarhus']),
                         {'/find?by=K%C3%B8benhavn': False, '/find?by=Aarhus': True})

    def test_laengste_match_maales_paa_de_normaliserede_regler(self):
        """Laengste match maales efter normaliseringen: 'Allow: /butik/\u00e6ble' (16 tegn kodet) slaar
        'Disallow: /butik/%C3%A6' (13), skoent den staar kortere i filen, og 'Disallow: /~admin/' (8)
        slaar 'Allow: /%7Eadmin' (7 afkodet) (fundet af testene 14-10-2026)."""
        self.assertEqual(self._afgoer('User-agent: *\nDisallow: /butik/%C3%A6\nAllow: /butik/\u00e6ble\n',
                                      ['/butik/\u00e6ble', '/butik/%c3%a6ble', '/butik/\u00e6g']),
                         {'/butik/\u00e6ble': True, '/butik/%c3%a6ble': True, '/butik/\u00e6g': False})
        self.assertEqual(self._afgoer('User-agent: *\nAllow: /%7Eadmin\nDisallow: /~admin/\n',
                                      ['/~admin/x', '/%7Eadmin/x', '/~admin']),
                         {'/~admin/x': False, '/%7Eadmin/x': False, '/~admin': True})

    def test_grupper_for_samme_agent_laegges_sammen(self):
        """RFC 9309 2.2.1: flere grupper for samme agent er \u00e9n. 'User-agent: * / Disallow: /a' og senere
        'User-agent: * / Allow: /a/b' tillader /a/b; foer blev hver gruppe tjekket for sig, og /a/b blev
        meldt forbudt (fundet af testene 14-10-2026). Ligesaa for to ClaudeBot-grupper."""
        for agent in ('*', 'ClaudeBot'):
            with self.subTest(agent=agent):
                robots = 'User-agent: %s\nDisallow: /a\n\nUser-agent: %s\nAllow: /a/b\n' % (agent, agent)
                self.assertEqual(self._afgoer(robots, ['/a/b', '/a/b/c', '/a/x', '/b']),
                                 {'/a/b': True, '/a/b/c': True, '/a/x': False, '/b': True})
        # lige lange regler fra hver sin gruppe: Allow vinder ogsaa paa tvaers af grupperne
        self.assertEqual(self._afgoer('User-agent: *\nDisallow: /p\n\nUser-agent: *\nAllow: /p\n', ['/p/q']),
                         {'/p/q': True})

    def test_stjerne_og_claude_overholdes_stadig_hver_for_sig(self):
        """Kun grupper for SAMME agent laegges sammen: en ClaudeBot-Disallow forbyder stadig, selv om '*'
        tillader stien med en laengere Allow - ogsaa naar '*'-grupperne er lagt sammen (14-10-2026)."""
        self.assertEqual(self._afgoer('User-agent: ClaudeBot\nDisallow: /a\n\nUser-agent: *\nAllow: /a/b\n',
                                      ['/a/b', '/c']), {'/a/b': False, '/c': True})
        robots = ('User-agent: *\nDisallow: /a\n\nUser-agent: ClaudeBot\nDisallow: /c\n\n'
                  'User-agent: *\nAllow: /a/b\n')
        self.assertEqual(self._afgoer(robots, ['/a/b', '/a/x', '/c/1', '/d']),
                         {'/a/b': True, '/a/x': False, '/c/1': False, '/d': True})

    def test_user_agent_med_version_kommaliste_og_semikolon(self):
        """_ua_navne (review 14-10-2026): 'ClaudeBot/1.0 (+https://anthropic.com)', 'ClaudeBot (+https://...)',
        'ClaudeBot, GPTBot' og 'ClaudeBot;' er alle en ClaudeBot-gruppe, og dens 'Disallow: /' forbyder. Foer
        blev hele vaerdien til foerste '/' brugt som navnet ('claudebot, gptbot', 'claudebot;', 'claudebot
        (+https:'), gruppen blev overset, og stien meldt TILLADT. Andre botters grupper skrevet saadan gaelder
        stadig ikke os."""
        # Alle tokens i vaerdien taeller (ogsaa versions- og url-dele, som ikke kan ligne en agent): et
        # foerste forsoeg klippede ved foerste '/', saa 'GPTBot/1.0, ClaudeBot/1.0' blev til ['gptbot']
        # (testene 14-10-2026).
        for v, skal in (('ClaudeBot/1.0 (+https://anthropic.com)', {'claudebot'}), ('ClaudeBot, GPTBot', {'claudebot', 'gptbot'}),
                        ('ClaudeBot;', {'claudebot'}), ('GPTBot/1.0, ClaudeBot/1.0', {'gptbot', 'claudebot'}),
                        ('Googlebot (compatible); ClaudeBot', {'googlebot', 'claudebot'}), ('*', {'*'})):
            with self.subTest(v=v):
                self.assertTrue(skal <= set(RS._ua_navne(v)), RS._ua_navne(v))
        self.assertNotIn('*', RS._ua_navne('Foo*Bar'))
        for agent, tilladt in (('GPTBot/1.0, ClaudeBot/1.0', False), ('Googlebot (compatible); ClaudeBot', False),
                               ('ClaudeBot/1.0 (+https://anthropic.com)', False),
                               ('ClaudeBot (+https://anthropic.com)', False),
                               ('ClaudeBot, GPTBot', False), ('GPTBot, ClaudeBot', False), ('ClaudeBot;', False),
                               ('GPTBot; Claude-User', False),
                               ('GPTBot, Bingbot', True), ('NotClaudeBot;', True)):
            with self.subTest(agent=agent):
                robots = 'User-agent: *\nAllow: /\n\nUser-agent: %s\nDisallow: /\n' % agent
                self.assertEqual(self._afgoer(robots, ['/', '/butikker/1']), {'/': tilladt, '/butikker/1': tilladt})


# ---------------------------------------------------------------- robots.txt: cache og laas
class RobotsCache(_Grund):
    """robots.txt hentes én gang pr. vaert pr. koersel - ogsaa naar mange traade spoerger samtidig."""

    def test_en_hentning_pr_vaert_pr_koersel(self):
        """_raw spoerger ved HVERT kald (14-10-2026), saa svaret caches pr. vaert - ogsaa 'ingen regler'
        (404) og 'forbudt' (udfald). Ellers hentes filen igen for hver side (Matas: 266 sider)."""
        f = _FalskRobots({'https://a.example': ['User-agent: *\nDisallow: /privat/\n'],
                          'https://b.example': [404], 'https://c.example': [503]})
        urls = ['https://a.example/', 'https://a.example/x', 'https://a.example/privat/y', 'https://a.example/z?q=1',
                'https://b.example/1', 'https://b.example/2', 'https://c.example/1', 'https://c.example/2']
        with mock.patch.object(RS, '_text', f):
            svar = [RS._robots_tilladt(u) for u in urls]
        self.assertEqual(svar, [True, True, False, True, True, True, False, False])
        self.assertEqual(dict(collections.Counter(f.kald)), {'https://a.example/robots.txt': 1,
                                                             'https://b.example/robots.txt': 1,
                                                             'https://c.example/robots.txt': 2})  # ét genforsoeg

    def test_otte_traade_samtidig_giver_en_hentning(self):
        """8 traade (som _map/_pages) spoerger samtidig om en ny vaert: laasen giver ét kald til
        robots.txt, ikke otte - noedvendigt, siden _raw spoerger ved hvert kald (14-10-2026)."""
        start = threading.Barrier(8)
        kald, laas = [], threading.Lock()

        def langsom(url, timeout=90, **kw):
            with laas:
                kald.append(url)
            threading.Event().wait(0.2)     # holder laasen, mens de andre traade naar frem til den
            return 'User-agent: *\nDisallow: /privat/\n'

        svar = [None] * 8

        def traad(i):
            start.wait(5)
            svar[i] = RS._robots_tilladt('https://ny.example/side/%d' % i)

        with mock.patch.object(RS, '_text', langsom):
            ts = [threading.Thread(target=traad, args=(i,)) for i in range(8)]
            for t in ts:
                t.daemon = True
                t.start()
            for t in ts:
                t.join(15)
        self.assertEqual([t for t in ts if t.is_alive()], [])
        self.assertEqual(svar, [True] * 8)
        self.assertEqual(kald, ['https://ny.example/robots.txt'])


# ---------------------------------------------------------------- robots.txt: genforsoeg efter forbigaaende udfald
class RobotsGenforsoeg(_Grund):
    """review 14-10-2026: et FORBIGAAENDE udfald paa robots.txt (5xx eller timeout ved begge forsoeg) gaelder som
    forbud i ROBOTS_GENFORSOEG = 300 s efter det andet forsoeg (tidspunktet staar i _ROBOTS_FORBIGAAENDE); saa
    droppes cache-linjen, og filen hentes igen. Foer gjaldt to timeouts ved foerste kald som forbud resten af
    koerslen, og validate.py's adressevask stod stille. En blokering (401/403/429) hentes aldrig igen. Uret er
    simuleret (_Ur, ogsaa genforsoegets pause paa 3 s); robots.txt-hentningen er stubbet (_FalskRobots)."""

    V = 'https://gen.example'
    REGLER = 'User-agent: *\nDisallow: /privat/\n'

    def setUp(self):
        _Grund.setUp(self)
        self.ur = _Ur()
        self._start(mock.patch.object(RS.time, 'monotonic', self.ur.monotonic))
        self.sove.side_effect = self.ur.sleep
        self.net[self.V + '/side'] = [b'ok']

    def _ny_koersel(self, udfald):
        """Tom robots-tilstand, uret paa T0 og en ny _FalskRobots for V med disse udfald."""
        for d in (RS._ROBOTS, RS._ROBOTS_GRUND, RS._ROBOTS_FORBIGAAENDE, RS._SIDSTE_KALD):
            d.clear()
        del RS.ROBOTS_STOP[:]
        self.ur.nu, self.ur.sovet, self.anmodninger = T0, [], []
        return _FalskRobots({self.V: udfald})

    def _forbudt(self, f, kald):
        """RS._raw(V/side) er forbudt (ingen anmodning til siden), og robots.txt er hentet `kald` gange i alt."""
        with mock.patch.object(RS, '_text', f):
            with self.assertRaises(RS.RobotsForbudt):
                RS._raw(self.V + '/side')
        self.assertEqual(len(f.kald), kald)
        self.assertEqual(self.anmodninger, [])

    def test_forbigaaende_udfald_hentes_igen_efter_300_s(self):
        """5xx, timeout eller afbrudt forbindelse ved begge forsoeg: forbudt ved t=0 (det andet forsoeg, 3 s efter
        det foerste), stadig forbudt ved t=200 og t=300 uden ny hentning, hentet igen ved t=301 - og nu gaelder
        filens regler: siden hentes, /privat/ er stadig forbudt. Et svar hentes ikke igen (review 14-10-2026)."""
        self.assertEqual(RS.ROBOTS_GENFORSOEG, 300)
        for navn, udfald in (('503', 503), ('timeout', socket.timeout('timed out')),
                             ('afbrudt', ConnectionResetError(54, 'Connection reset by peer'))):
            with self.subTest(navn):
                f = self._ny_koersel([udfald, udfald, self.REGLER])
                self._forbudt(f, 2)                                     # t=0: to udfald
                t0 = self.ur.nu
                self.assertEqual(t0, T0 + 3)                            # efter genforsoegets pause
                self.assertEqual(dict(RS._ROBOTS_FORBIGAAENDE), {self.V: t0})
                self.assertIn('kunne ikke laeses', RS.ROBOTS_STOP[0][1])
                for efter in (200, 300):                                # stadig forbudt, ingen ny hentning
                    self.ur.nu = t0 + efter
                    self._forbudt(f, 2)
                self.ur.nu = t0 + 301
                with mock.patch.object(RS, '_text', f):
                    self.assertEqual(RS._raw(self.V + '/side'), b'ok')  # hentet igen og tilladt
                    with self.assertRaises(RS.RobotsForbudt):
                        RS._raw(self.V + '/privat/x')                   # filens regler gaelder
                    self.ur.nu = t0 + 10 ** 6                           # et svar hentes ikke igen
                    self.assertEqual(RS._raw(self.V + '/side'), b'ok')
                self.assertEqual(len(f.kald), 3)
                self.assertEqual((dict(RS._ROBOTS), dict(RS._ROBOTS_FORBIGAAENDE)), ({self.V: self.REGLER}, {}))
                self.assertEqual(self.anmodninger, [self.V + '/side'] * 2)

    def test_nyt_forbigaaende_udfald_venter_300_s_igen(self):
        """Fejler hentningen ved t=301 igen (to forsoeg), gaelder et nyt forbud i 300 s fra det nye andet forsoeg -
        derefter hentes filen igen (review 14-10-2026)."""
        f = self._ny_koersel([503, 503, 503, 503, self.REGLER])
        self._forbudt(f, 2)
        t0 = self.ur.nu
        self.ur.nu = t0 + 301
        self._forbudt(f, 4)                                             # hentet igen, to nye udfald
        t1 = self.ur.nu
        self.assertEqual((t1, dict(RS._ROBOTS_FORBIGAAENDE)), (t0 + 304, {self.V: t1}))
        self.ur.nu = t1 + 300
        self._forbudt(f, 4)
        self.ur.nu = t1 + 301
        with mock.patch.object(RS, '_text', f):
            self.assertEqual(RS._raw(self.V + '/side'), b'ok')
        self.assertEqual((len(f.kald), dict(RS._ROBOTS_FORBIGAAENDE)), (5, {}))

    def test_blokering_401_403_429_hentes_aldrig_igen(self):
        """401/403/429 er en blokering (sport24.dk 30-09-2026), ikke et forbigaaende udfald: forbudt, intet i
        _ROBOTS_FORBIGAAENDE, og robots.txt hentes aldrig igen - heller ikke efter 301 s eller et doegn. Ligesaa
        en 403 ved andet forsoeg efter en 503: det sidste udfald afgoer det (review 14-10-2026)."""
        for navn, udfald, kald in (('401', [401, self.REGLER], 1), ('403', [403, self.REGLER], 1),
                                   ('429', [429, self.REGLER], 1), ('503, saa 403', [503, 403, self.REGLER], 2)):
            with self.subTest(navn):
                f = self._ny_koersel(udfald)
                self._forbudt(f, kald)
                blokeret = self.ur.nu
                self.assertEqual(RS._ROBOTS_FORBIGAAENDE, {})
                for efter in (301, 86400):
                    self.ur.nu = blokeret + efter
                    self._forbudt(f, kald)
                self.assertEqual(RS._ROBOTS, {self.V: None})
                self.assertEqual(self.ur.sovet, [3] * (kald - 1))      # kun genforsoeget efter 503 holder pause

    def test_et_udfald_og_saa_svar_er_ikke_forbigaaende(self):
        """Ét udfald og saa et svar: filen gaelder, og intet staar i _ROBOTS_FORBIGAAENDE - den hentes ikke igen
        (review 14-10-2026)."""
        f = self._ny_koersel([503, self.REGLER])
        with mock.patch.object(RS, '_text', f):
            self.assertEqual(RS._raw(self.V + '/side'), b'ok')
            self.ur.nu += 301
            self.assertEqual(RS._raw(self.V + '/side'), b'ok')
        self.assertEqual((len(f.kald), dict(RS._ROBOTS_FORBIGAAENDE)), (2, {}))


# ---------------------------------------------------------------- Crawl-delay
class CrawlDelay(_Grund):
    """Crawl-delay overholdes centralt (14-10-2026): _crawl_delay finder den forsinkelse, der gaelder os,
    i den cachede robots.txt, og _vent_crawl_delay (kaldt af _tjek_robots foer hvert kald) venter, til
    den er gaaet siden seneste kald til vaerten. Uret er simuleret (_Ur), saa ingen test venter 10 s."""

    V = 'https://cd.example'

    def setUp(self):
        _Grund.setUp(self)
        self.ur = _Ur()
        self._start(mock.patch.object(RS.time, 'monotonic', self.ur.monotonic))
        self.sove.side_effect = self.ur.sleep
        self.kald = self._start(mock.patch.object(RS, '_SIDSTE_KALD', _Logbog()))
        self.tider = []         # (url, uret) ved hvert urlopen

    def _urlopen(self, req, timeout=None, **kw):
        url = req.full_url if isinstance(req, urllib.request.Request) else req
        self.tider.append((url, self.ur.nu))
        return _Grund._urlopen(self, req, timeout, **kw)

    def _forsinkelse(self, robots):
        """-> RS._crawl_delay for en vaert, hvis cachede robots.txt er `robots`."""
        RS._ROBOTS[self.V] = robots
        return RS._crawl_delay(self.V)

    def test_forsinkelsen_der_gaelder_os_den_strengeste_vinder(self):
        """'*'-gruppen, Claude-grupper og linjer foer enhver gruppe gaelder os (halifax.dk har
        'Crawl-delay: 10' foer Yoast-blokken), og den strengeste vinder (central Crawl-delay, 14-10-2026)."""
        for robots, sek in (('User-agent: *\nCrawl-delay: 10\n', 10),                     # lovbjerg.dk
                            ('User-agent: ClaudeBot\nCrawl-delay: 7\n\nUser-agent: *\nDisallow:\n', 7),
                            ('User-agent: GPTBot\nUser-agent: anthropic-ai\nCrawl-delay: 6\n', 6),
                            ('User-agent: *\nCrawl-delay: 2\n\nUser-agent: Claude-User\nCrawl-delay: 8\n', 8),
                            ('User-agent: ClaudeBot\nCrawl-delay: 8\n\nUser-agent: *\nCrawl-delay: 2\n', 8),
                            ('Crawl-delay: 10\n\n# Yoast\nUser-agent: *\nDisallow: /wp-admin/\n', 10),
                            ('User-Agent: *\nCRAWL-DELAY: 1.5  # pause\n', 1.5),
                            ('User-agent: *\nDisallow: /privat/\n', 0),
                            ('', 0)):
            with self.subTest(robots=robots):
                self.assertEqual(self._forsinkelse(robots), sek)

    def test_andre_botters_grupper_gaelder_ikke_os(self):
        """Grupper for andre bots gaelder ikke os: starbucks.com har 'User-Agent: MJ12bot / Crawl-Delay: 5',
        maxizoo.dk grupper for AhrefsBot, MJ12bot og Pinterest (14-10-2026) - ellers ventede vi for
        andres skyld. En User-agent efter en Crawl-delay starter en ny gruppe."""
        for robots, sek in (('User-Agent: MJ12bot\nCrawl-Delay: 5\n\nUser-agent: *\nDisallow: /account/\n', 0),
                            ('User-agent: AhrefsBot\nCrawl-delay: 10\n\nUser-agent: MJ12bot\nCrawl-delay: 10\n\n'
                             'User-agent: Pinterest\nCrawl-delay: 1\n\nUser-agent: *\nDisallow: /checkout\n', 0),
                            ('User-agent: *\nCrawl-delay: 1\n\nUser-agent: MJ12bot\nCrawl-delay: 5\n', 1),
                            ('User-agent: ClaudeBot\nCrawl-delay: 3\nUser-agent: GPTBot\nCrawl-delay: 20\n', 3)):
            with self.subTest(robots=robots):
                self.assertEqual(self._forsinkelse(robots), sek)

    def test_loft_ugyldige_tal_bom_og_ingen_fil(self):
        """Intet loft (review 14-10-2026: en vaert, der bad om 60 s, fik 30 s - et brud; CRAWL_BUDGET
        stopper i stedet en henter, der ville vente for laenge); ugyldige tal springes over (de maa ikke
        stoppe henteren); en BOM foran foerste linje skjuler hverken en Crawl-delay eller starten paa en
        andens gruppe (som i _robots_tilladt, 30-09-2026); uden laesbar robots.txt ingen pause."""
        for robots, sek in (('User-agent: *\nCrawl-delay: 120\n', 120),
                            ('User-agent: *\nCrawl-delay: langsomt\nCrawl-delay:\nCrawl-delay: 3\n', 3),
                            ('\ufeffCrawl-delay: 10\r\nUser-agent: *\r\nDisallow:\r\n', 10),
                            ('\ufeffUser-agent: MJ12bot\nCrawl-delay: 5\n', 0),
                            (None, 0)):
            with self.subTest(robots=robots):
                self.assertEqual(self._forsinkelse(robots), sek)
        RS._ROBOTS.clear()
        self.assertEqual(RS._crawl_delay(self.V), 0)

    def test_nan_inf_og_negative_tal_ignoreres(self):
        """'nan' og negative tal ignoreres; store tal og 'inf' gaelder fuldt (CRAWL_BUDGET stopper henteren).
        'Crawl-delay: nan' foran 'Crawl-delay: 10' gjorde forsinkelsen til nan (max() med nan afhaenger af
        raekkefoelgen), og da nan > 0 er falsk, ventede _raw slet ikke; '-5' gav -5 (fundet af testene
        14-10-2026). Et foerste forsoeg droppede ogsaa tal over 86400, saa en vaert, der bad om at vente
        laenge, fik ingen ventetid (testene 14-10-2026); nu gaelder de fuldt (review 14-10-2026)."""
        for robots, sek in (('User-agent: *\nCrawl-delay: nan\nCrawl-delay: 10\n', 10),
                            ('User-agent: *\nCrawl-delay: 10\nCrawl-delay: nan\n', 10),
                            ('User-agent: *\nCrawl-delay: NaN\n', 0),
                            ('User-agent: *\nCrawl-delay: inf\nCrawl-delay: 5\n', float('inf')),
                            ('User-agent: *\nCrawl-delay: 100000\n', 100000),
                            ('User-agent: *\nCrawl-delay: 1e999\n', float('inf')),
                            ('Crawl-delay: -5\n', 0),
                            ('User-agent: *\nCrawl-delay: -5\nCrawl-delay: 2\n', 2),
                            ('User-agent: *\nCrawl-delay: 0\n', 0),             # graenserne gaelder
                            ('User-agent: *\nCrawl-delay: 86400\n', 86400)):    # (intet loft)
            with self.subTest(robots=robots):
                self.assertEqual(self._forsinkelse(robots), sek)
        # og ventetiden virker: med nan foerst i filen gaar der stadig 10 s mellem kaldene
        v = 'https://nan.example'
        self.net[v + '/robots.txt'] = [b'User-agent: *\nCrawl-delay: nan\nCrawl-delay: 10\n']
        self.net[v + '/side'] = [b'ok']
        for _ in range(2):
            self.assertEqual(RS._raw(v + '/side'), b'ok')
        self.assertEqual(self.ur.sovet, [10, 10])
        self.assertEqual(self.tider, [(v + '/robots.txt', T0), (v + '/side', T0 + 10), (v + '/side', T0 + 20)])

    def test_crawl_delay_for_claude_med_version_kommaliste_og_semikolon(self):
        """Samme navne-regel (_ua_navne) i _crawl_delay (review 14-10-2026): en Crawl-delay i en gruppe for
        'ClaudeBot/1.0 (+https://anthropic.com)', 'ClaudeBot (+https://...)', 'ClaudeBot, GPTBot' eller
        'ClaudeBot;' gaelder os. Foer genkendtes kun formen med '/' (alt efter den blev skaaret af), og
        de andre gav ingen ventetid. Andre botters grupper skrevet saadan gaelder stadig ikke os."""
        for agent, sek in (('ClaudeBot/1.0 (+https://anthropic.com)', 7), ('ClaudeBot (+https://anthropic.com)', 7),
                           ('ClaudeBot, GPTBot', 7), ('GPTBot, ClaudeBot', 7), ('ClaudeBot;', 7),
                           ('GPTBot; anthropic-ai', 7), ('GPTBot, Bingbot', 0), ('NotClaudeBot;', 0)):
            with self.subTest(agent=agent):
                robots = 'User-agent: %s\nCrawl-delay: 7\n\nUser-agent: *\nDisallow:\n' % agent
                self.assertEqual(self._forsinkelse(robots), sek)

    def test_budget_pr_vaert_stopper_henteren_i_stedet_for_et_loft(self):
        """Intet loft paa Crawl-delay mere, men CRAWL_BUDGET (review 14-10-2026): hoejst 300 s samlet ventetid
        pr. vaert pr. koersel (_VENTET). Med 'Crawl-delay: 120' ventes 120 + 120 = 240 s; det tredje kald ville
        naa 360 s og stoppes med RobotsForbudt ('budgettet', og i ROBOTS_STOP) uden pause og uden kald. En anden
        vaert har sit eget budget, og 'Crawl-delay: inf' stopper allerede ved foerste ventetid. Foer kappedes
        ventetiden ved 30 s - et brud paa vaertens Crawl-delay."""
        self.assertEqual(RS.CRAWL_BUDGET, 300)
        v, egen, inf = self.V, 'https://egen.example', 'https://inf.example'
        for vaert, d in ((v, b'120'), (egen, b'120'), (inf, b'inf')):
            self.net[vaert + '/robots.txt'] = [b'User-agent: *\nCrawl-delay: ' + d + b'\n']
        for i in (1, 2, 3):
            self.net['%s/side/%d' % (v, i)] = [b'side %d' % i]
        self.net[egen + '/side'] = [b'egen side']
        self.net[inf + '/side'] = [b'maa ikke hentes']
        self.assertEqual(RS._raw(v + '/side/1'), b'side 1')     # 120 s efter robots.txt
        self.assertEqual(RS._raw(v + '/side/2'), b'side 2')     # 120 s mere: 240 s i alt
        with self.assertRaises(RS.RobotsForbudt) as cm:
            RS._raw(v + '/side/3')                              # 360 s > 300 s
        self.assertIn('budgettet', str(cm.exception))
        self.assertEqual(self.ur.sovet, [120, 120])             # ingen pause for det tredje kald
        self.assertEqual(RS._raw(egen + '/side'), b'egen side')  # en anden vaert: sit eget budget
        with self.assertRaises(RS.RobotsForbudt) as cm:
            RS._raw(inf + '/side')
        self.assertIn('budgettet', str(cm.exception))
        self.assertEqual(self.ur.sovet, [120, 120, 120])
        self.assertEqual(self.tider, [(v + '/robots.txt', T0), (v + '/side/1', T0 + 120), (v + '/side/2', T0 + 240),
                                      (egen + '/robots.txt', T0 + 240), (egen + '/side', T0 + 360),
                                      (inf + '/robots.txt', T0 + 360)])
        self.assertEqual(RS._VENTET, {v: 240, egen: 120})
        self.assertEqual([u for u, _ in RS.ROBOTS_STOP], [v + '/side/3', inf + '/side'])
        for _, grund in RS.ROBOTS_STOP:
            self.assertIn('budgettet', grund)

    def test_venter_fra_robots_hentningen_og_mellem_kald(self):
        """lovbjerg.dk ('User-agent: * / Crawl-delay: 10'): loevbjerg() hentede butikssiden straks efter
        robots.txt (14-10-2026). Nu venter _raw, til 10 s er gaaet siden seneste kald til vaerten -
        robots.txt-hentningen medregnet - og kun den tid, der mangler."""
        v = self.V
        self.net[v + '/robots.txt'] = [b'User-agent: *\nCrawl-delay: 10\n']
        for i in (1, 2, 3):
            self.net['%s/side/%d' % (v, i)] = [b'side %d' % i]
        self.assertEqual(RS._raw(v + '/side/1'), b'side 1')     # robots.txt ved T0, siden straks efter
        self.ur.nu += 12                                         # 12 s efter side 1: ingen pause
        self.assertEqual(RS._raw(v + '/side/2'), b'side 2')
        self.ur.nu += 3                                          # 3 s efter side 2: de 7 s, der mangler
        self.assertEqual(RS._raw(v + '/side/3'), b'side 3')
        self.assertEqual(self.ur.sovet, [10, 7])
        self.assertEqual(self.tider, [(v + '/robots.txt', T0), (v + '/side/1', T0 + 10),
                                      (v + '/side/2', T0 + 22), (v + '/side/3', T0 + 32)])

    def test_vaert_uden_crawl_delay_venter_aldrig(self):
        """Uden Crawl-delay for os - ingen linje, kun for en anden bot (som starbucks.com) eller 404 paa
        robots.txt - sover _raw aldrig: de andre hentere maa ikke blive langsommere (14-10-2026)."""
        for v, robots in (('https://ingen.example', b'User-agent: *\nDisallow: /privat/\n'),
                          ('https://mj12.example', b'User-Agent: MJ12bot\nCrawl-Delay: 5\n\nUser-agent: *\nDisallow:\n'),
                          ('https://mangler.example', _http_fejl('https://mangler.example/robots.txt', 404))):
            self.net[v + '/robots.txt'] = [robots]
            for i in range(3):
                self.net['%s/%d' % (v, i)] = [b'ok']
                self.assertEqual(RS._raw('%s/%d' % (v, i)), b'ok')
        self.sove.assert_not_called()
        self.assertEqual(len(self.anmodninger), 12)

    def test_hver_vaert_har_sit_eget_seneste_kald(self):
        """Ventetiden gaelder pr. vaert: et kald til b.example taeller ikke for a.example, saa a's andet
        kald 10 s efter dets foerste gaar straks, mens b venter paa sit eget (14-10-2026)."""
        a, b = 'https://a.example', 'https://b.example'
        for v in (a, b):
            self.net[v + '/robots.txt'] = [b'User-agent: *\nCrawl-delay: 10\n']
            self.net[v + '/1'] = [b'ok']
            self.net[v + '/2'] = [b'ok']
        for url in (a + '/1', b + '/1', a + '/2', b + '/2'):
            RS._raw(url)
        self.assertEqual(self.ur.sovet, [10, 10, 10])
        self.assertEqual(self.tider, [(a + '/robots.txt', T0), (a + '/1', T0 + 10), (b + '/robots.txt', T0 + 10),
                                      (b + '/1', T0 + 20), (a + '/2', T0 + 20), (b + '/2', T0 + 30)])

    def test_samtidige_traade_til_samme_vaert_tager_tur(self):
        """4 traade (som _map) til én vaert med Crawl-delay faar lov én ad gangen med 10 s imellem
        (laasen pr. vaert i _KALD_LAASE, 14-10-2026). Uden laasen saa alle fire robots.txt-hentningen
        som seneste kald og gik i gang paa samme tid."""
        self.ur.glimt = 0.05        # hver pause varer et oejeblik, saa de andre traade naar frem imens
        v = self.V
        self.net[v + '/robots.txt'] = [b'User-agent: *\nCrawl-delay: 10\n']
        for i in range(4):
            self.net['%s/side/%d' % (v, i)] = [b'ok']
        self.assertTrue(RS._robots_tilladt(v + '/'))            # robots.txt hentet ved T0
        start, fejl = threading.Barrier(4), []

        def traad(i):
            try:
                start.wait(5)
                RS._raw('%s/side/%d' % (v, i))
            except BaseException as e:      # gives videre til testen nedenfor
                fejl.append(e)

        ts = [threading.Thread(target=traad, args=(i,)) for i in range(4)]
        for t in ts:
            t.daemon = True
            t.start()
        for t in ts:
            t.join(10)
        self.assertEqual([t for t in ts if t.is_alive()], [])
        self.assertEqual(fejl, [])
        self.assertEqual([tid for vaert, tid in self.kald.log if vaert == v],
                         [T0, T0 + 10, T0 + 20, T0 + 30, T0 + 40])
        self.assertEqual(sorted(self.anmodninger[1:]), ['%s/side/%d' % (v, i) for i in range(4)])
        self.assertEqual(list(RS._KALD_LAASE), [v])

    def test_venter_ikke_paa_en_anden_vaerts_robots_hentning(self):
        """Laasen pr. vaert slaas op under sin egen laas (_KALD_LAASE_LAAS), ikke under _ROBOTS_LAAS: den
        holder _robots_tilladt, mens en NY vaerts robots.txt hentes - op til 63 s (2 x 30 s timeout og 3 s
        pause). Saa laenge stod ethvert kald til en vaert med Crawl-delay ellers stille, ogsaa i andre traade
        og for vaerter, hvis robots.txt laa i cachen (fundet af testene 14-10-2026)."""
        v, langsom = self.V, 'https://langsom.example'
        RS._ROBOTS[v] = 'User-agent: *\nCrawl-delay: 10\n'      # i cachen, hentet ved T0
        RS._SIDSTE_KALD[v] = T0
        self.net[v + '/side'] = [b'ok']
        inde, slip = threading.Event(), threading.Event()

        def langsom_robots(url, timeout=90, **kw):
            inde.set()                          # _ROBOTS_LAAS er taget
            slip.wait(10)
            return 'User-agent: *\nDisallow:\n'

        with mock.patch.object(RS, '_text', langsom_robots):
            t = threading.Thread(target=RS._robots_tilladt, args=(langsom + '/',))
            t.daemon = True
            t.start()
            try:
                self.assertTrue(inde.wait(5), 'robots.txt-hentningen for langsom.example begyndte ikke')
                self.assertTrue(RS._ROBOTS_LAAS.locked())
                hvad = 'venter paa _ROBOTS_LAAS, mens en anden vaerts robots.txt hentes'
                _med_frist(lambda: RS._vent_crawl_delay(v + '/side'), 2, '_vent_crawl_delay ' + hvad)
                self.assertEqual(_med_frist(lambda: RS._raw(v + '/side'), 2, '_raw ' + hvad), b'ok')
                self.assertTrue(RS._ROBOTS_LAAS.locked())        # hentningen var stadig i gang
            finally:
                slip.set()
                t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(self.ur.sovet, [10, 10])               # Crawl-delay blev overholdt imens
        self.assertEqual(self.tider, [(v + '/side', T0 + 20)])

    def test_dawa_get_venter_crawl_delay_og_forbud_er_dawanede(self):
        """dawa._get gaar nu gennem RS._tjek_robots - robots.txt OG Crawl-delay, som alle andre kald. Med
        'Crawl-delay: 10' for adressevaelger.dk i cachen venter to kald i traek 10 s (og kun den tid, der
        mangler); et forbud i samme fil er stadig DawaNede foer urlopen og uden at vente forgaeves. Uden
        Crawl-delay-tjekket kaldte _get vaerten igen straks (fundet af testene 14-10-2026)."""
        av = dawa.AV_URL
        RS._ROBOTS[av] = 'User-agent: *\nCrawl-delay: 10\nDisallow: /vask/\n'     # hentet tidligere i koerslen
        u1, u2, u3 = (av + '/adresser/%d?token=x' % i for i in (1, 2, 3))
        for i, u in enumerate((u1, u2, u3), 1):
            self.net[u] = [b'{"id": "%d"}' % i]
        self.assertEqual(dawa._get(u1), {'id': '1'})     # intet tidligere kald til vaerten: straks
        self.assertEqual(dawa._get(u2), {'id': '2'})     # lige efter: 10 s
        self.ur.nu += 4
        self.assertEqual(dawa._get(u3), {'id': '3'})     # 4 s efter: de 6 s, der mangler
        self.assertEqual(self.ur.sovet, [10, 6])
        self.assertEqual(self.tider, [(u1, T0), (u2, T0 + 10), (u3, T0 + 20)])
        # et forbud i samme fil: DawaNede (ikke RobotsForbudt) foer urlopen og uden at vente forgaeves
        with self.assertRaises(dawa.DawaNede) as cm:
            dawa._get(av + '/vask/?token=x&adresse=Vestergade+1')
        self.assertIn('robots.txt', str(cm.exception))
        self.assertEqual(self.ur.sovet, [10, 6])         # ingen ny pause ...
        self.assertEqual(len(self.tider), 3)             # ... og intet urlopen

    def test_budget_stop_uden_query_og_uden_log_for_dawa(self):
        """review 14-10-2026 (anden runde): ogsaa Crawl-delay-budgettets stop respekterer log og gemmer url'en uden
        query. dawa._get (log=False) stoppes som DawaNede med grunden i dawa.AV_ROBOTS_STOP, men ROBOTS_STOP vokser
        ikke - ellers kasserede refresh_retail svaret fra den henter, der slog adressen op. Et almindeligt kald
        (log=True) staar i ROBOTS_STOP uden ?token=..., og tokenet staar intet sted."""
        av, token = dawa.AV_URL, 'HEMMELIGT-TOKEN-4711'
        RS._ROBOTS[av] = 'User-agent: *\nCrawl-delay: 400\n'     # hentet tidligere i koerslen
        u1, u2 = (av + '/adresser/%d?token=%s' % (i, token) for i in (1, 2))
        self.net[u1] = [b'{"id": "1"}']
        self.net[u2] = [b'{"id": "2"}']                         # maa ikke hentes
        self.assertEqual(dawa._get(u1), {'id': '1'})            # intet tidligere kald: straks
        grund = 'Crawl-delay 400 s paa adressevaelger.dk: budgettet paa 300 s ventetid pr. koersel er brugt'
        with self.assertRaises(dawa.DawaNede) as cm:
            dawa._get(u2)                                       # 400 s > budgettet paa 300 s
        self.assertEqual(str(cm.exception), grund + ' - henter ikke flere sider')
        self.assertEqual(dawa.AV_ROBOTS_STOP, (str(cm.exception), T0))
        self.assertEqual(RS.ROBOTS_STOP, [])
        with self.assertRaises(RS.RobotsForbudt):
            RS._tjek_robots(u2, log=False)
        self.assertEqual(RS.ROBOTS_STOP, [])
        with self.assertRaises(RS.RobotsForbudt):
            RS._tjek_robots(u2)                                 # log=True: i ROBOTS_STOP, uden query
        self.assertEqual(RS.ROBOTS_STOP, [(av + '/adresser/2', grund)])
        self.assertEqual((self.ur.sovet, self.tider, RS._VENTET), ([], [(u1, T0)], {}))
        self.assertNotIn(token, repr((str(cm.exception), RS.ROBOTS_STOP, RS.OMDIRIGERING_STOP, dawa.AV_ROBOTS_STOP)))


# ---------------------------------------------------------------- retail_sources._raw og venner
class RawHjaelpere(_Grund):
    """retail_sources._raw/_text/_json/_post_*: robots.txt foerst, og robots.txt selv uden tjek."""

    def test_forbudt_giver_robotsforbudt_og_intet_urlopen(self):
        """Forbyder robots.txt stien, rejser _raw og venner RobotsForbudt (en RuntimeError) uden urlopen
        for siden (centralt fra 14-10-2026: 38 af 75 hentere tjekkede ikke selv). Filen har BOM (30-09-2026)."""
        self.assertTrue(issubclass(RS.RobotsForbudt, RuntimeError))
        side = 'https://bom.example/butikker'
        self.net['https://bom.example/robots.txt'] = [b'\xef\xbb\xbfUser-agent: ClaudeBot\r\nDisallow: /\r\n']
        self.net[side] = [b'{"butikker": []}']          # maa ikke hentes
        for kald in (lambda: RS._raw(side), lambda: RS._text(side), lambda: RS._json(side),
                     lambda: RS._post_json(side, {'q': 1}), lambda: RS._post_form(side, 'q=1')):
            with self.assertRaises(RS.RobotsForbudt):
                _med_frist(kald)
        self.assertEqual(self.anmodninger, ['https://bom.example/robots.txt'])

    def test_robots_txt_selv_hentes_uden_tjek(self):
        """robots.txt selv hentes uden robots-tjek (undtagelsen i _tjek_robots, 14-10-2026) - ellers
        spoerger hentningen sig selv og venter paa sin egen laas (haardknude)."""
        with mock.patch.object(RS, '_robots_tilladt', side_effect=AssertionError('robots.txt tjekkede sig selv')) as m:
            RS._tjek_robots('https://x.example/robots.txt')
        m.assert_not_called()
        self.net['https://y.example/robots.txt'] = [b'User-agent: *\nDisallow:\n']
        self.net['https://y.example/side'] = [b'ok']
        self.assertEqual(_med_frist(lambda: RS._raw('https://y.example/side')), b'ok')
        self.assertEqual(self.anmodninger, ['https://y.example/robots.txt', 'https://y.example/side'])

    def test_gzip_robots_txt_pakkes_ud(self):
        """UA'en beder om gzip, saa robots.txt kan komme pakket: den skal pakkes ud, ellers er reglerne
        volapyk og alt tilladt. En tilladt side hentes (og pakkes ud) som foer."""
        pak = {'Content-Encoding': 'gzip'}
        self.net['https://gz.example/robots.txt'] = [_Svar(gzip.compress(b'User-agent: *\nDisallow: /privat/\n'), pak)]
        self.net['https://gz.example/butikker'] = [_Svar(gzip.compress(b'{"n": 3}'), pak)]
        self.net['https://gz.example/privat/kurv'] = [b'maa ikke hentes']
        self.assertEqual(_med_frist(lambda: RS._json('https://gz.example/butikker')), {'n': 3})
        with self.assertRaises(RS.RobotsForbudt):
            _med_frist(lambda: RS._raw('https://gz.example/privat/kurv'))
        self.assertEqual(self.anmodninger, ['https://gz.example/robots.txt', 'https://gz.example/butikker'])


# ---------------------------------------------------------------- _tjek_robots: url-tjek, undtagelse og stop
class RobotsKanter(_Grund):
    """_tjek_robots' kanter efter review 14-10-2026: en url uden http(s)-skema og vaert afvises, foer nogen
    laas tages; ROBOTS_UNDTAGET (Datafordelerens GraphQL) tjekkes ikke; og hvert stop staar i ROBOTS_STOP
    med en grund, der skelner 'kunne ikke laeses' fra 'forbyder'."""

    def test_url_uden_skema_eller_vaert_afvises_foer_laasen(self):
        """En url uden http(s)-skema og vaert giver straks ValueError, foer _ROBOTS_LAAS. '/butikker/x' fra et
        sitemap blev foer til vaerten '://', hvis robots.txt (':///robots.txt') spurgte robots.txt for sig selv
        og ventede paa sin egen laas: koerslen hang (review 14-10-2026). Her holder testen selv laasen (som
        under en anden vaerts robots.txt-hentning, op til 63 s), saa et kald, der tager den, ikke kommer
        videre; hvert kald har 1 s. ftp:// afvises ogsaa - url-tjekket kommer foer genvejene for /robots.txt
        og for en igangvaerende robots.txt-hentning."""
        laas = RS._ROBOTS_LAAS                  # testens egen (_Grund.setUp)
        self.assertTrue(laas.acquire(timeout=1))
        # Slippes ikke igen: venter koden paa laasen, sidder dens traad fast paa denne tests laas - ikke paa
        # modulets, som de naeste tests bruger.

        def under_robots_hentning(url):
            RS._ROBOTS_HENTES.aktiv = True      # som _robots_tilladt saetter det, i kaldets egen traad
            return RS._tjek_robots(url)

        for navn, kald in (("RS._raw('/butikker/x')", lambda: RS._raw('/butikker/x')),
                           ("RS._raw('//cdn.example.dk/f.pdf')", lambda: RS._raw('//cdn.example.dk/f.pdf')),
                           ("RS._raw('butikker/x')", lambda: RS._raw('butikker/x')),
                           ("RS._robots_tilladt('/x')", lambda: RS._robots_tilladt('/x')),
                           ("sources._raw('//h/x')", lambda: S._raw('//h/x')),
                           ("RS._tjek_robots('ftp://cdn.example.dk/robots.txt')",
                            lambda: RS._tjek_robots('ftp://cdn.example.dk/robots.txt')),
                           ("RS._tjek_robots('/x') under en robots.txt-hentning", lambda: under_robots_hentning('/x')),
                           # netloc uden vaert ('https://:443/x') slap foer igennem (testene 14-10-2026)
                           ("RS._raw('https://:443/x')", lambda: RS._raw('https://:443/x')),
                           ("RS._robots_tilladt('https://:443/x')", lambda: RS._robots_tilladt('https://:443/x'))):
            with self.subTest(navn):
                with self.assertRaises(ValueError) as cm:
                    _med_frist(kald, 1, navn + ' venter paa _ROBOTS_LAAS - url-tjekket skal ligge foer laasen')
                self.assertIn('ikke en http(s)-url', str(cm.exception))
        self.assertEqual(self.anmodninger, [])
        self.assertEqual((dict(RS._ROBOTS), RS.ROBOTS_STOP), ({}, []))

    def test_datafordelerens_graphql_tjekkes_ikke(self):
        """ROBOTS_UNDTAGET: graphql.datafordeler.dk svarer 401 paa alle stier uden noeglen, ogsaa /robots.txt,
        og efter repoets regel (401 = blokeret) kunne DAR saa aldrig kaldes (14-10-2026). En url dertil
        robots-tjekkes derfor ikke: ingen robots.txt-hentning, intet stop, ingen pause (review 14-10-2026).
        Kun praecis den vaert (ogsaa med store bogstaver og port) - en vaert, der blot ligner, tjekkes som
        alle andre."""
        self.assertIn('graphql.datafordeler.dk', RS.ROBOTS_UNDTAGET)
        g, ligner = 'https://graphql.datafordeler.dk', 'https://graphql.datafordeler.dk.example'
        f = _FalskRobots({g: [401], 'http://graphql.datafordeler.dk': [401],
                          'https://GraphQL.Datafordeler.dk:443': [401], ligner: ['User-agent: *\nDisallow: /\n']})
        dar = g + '/DAR/v2?apikey=TESTNOEGLE'
        self.net[dar] = [b'{"data": {}}']
        with mock.patch.object(RS, '_text', f):
            for url in (dar, 'https://GraphQL.Datafordeler.dk:443/DAR/v2', 'http://graphql.datafordeler.dk/BBR/v2'):
                with self.subTest(url=url):
                    self.assertIsNone(RS._tjek_robots(url))
            self.assertEqual(RS._raw(dar), b'{"data": {}}')
            self.assertEqual((f.kald, RS.ROBOTS_STOP, dict(RS._ROBOTS)), ([], [], {}))
            with self.assertRaises(RS.RobotsForbudt):
                RS._raw(ligner + '/DAR/v2')
        self.assertEqual(f.kald, [ligner + '/robots.txt'])
        self.assertEqual(RS.ROBOTS_STOP, [(ligner + '/DAR/v2', 'robots.txt paa graphql.datafordeler.dk.example '
                                                               'forbyder /DAR/v2')])
        self.assertEqual(self.anmodninger, [dar])
        self.sove.assert_not_called()

    def test_robots_stop_husker_hvert_stop_med_grund(self):
        """ROBOTS_STOP: hvert kald, robots.txt stopper, tilfoejer (url, grund) - ogsaa naar kalderen sluger
        fejlen (23 brede 'except Exception' i henterne) - saa refresh_retail kan se, at et svar mangler sider
        (review 14-10-2026). Grunden skelner en robots.txt, der ikke kunne laeses (HTTP-status eller undtagelse
        fra _ROBOTS_GRUND; 'regnes som forbud'), fra et forbud i filen ('forbyder <sti>'), ogsaa naar filen kom
        efter et udfald. Anden runde af review 14-10-2026: url'en gemmes uden query (den kan baere et token), og
        dawa._get (log=False) skriver ikke i listen - dens stop er et adresse-udfald (DawaNede) med samme grund."""
        a, b, c, d, e = ('https://%s.example' % x for x in 'abcde')
        self.net[a + '/robots.txt'] = [_http_fejl(a + '/robots.txt', 503)]
        self.net[b + '/robots.txt'] = [TimeoutError('timed out')]
        self.net[c + '/robots.txt'] = [_http_fejl(c + '/robots.txt', 403)]
        self.net[d + '/robots.txt'] = [b'User-agent: *\nDisallow: /privat/\n']
        self.net[e + '/robots.txt'] = [_http_fejl(e + '/robots.txt', 503), b'User-agent: ClaudeBot\nDisallow: /kort\n']
        self.net[dawa.AV_URL + '/robots.txt'] = [b'User-agent: *\nDisallow: /vask/\n']
        vask = dawa.AV_URL + '/vask/?token=x&adresse=Vestergade+1'
        beskeder = []
        for kald in (lambda: RS._raw(a + '/side'), lambda: RS._json(a + '/side'), lambda: RS._text(b + '/butikker'),
                     lambda: RS._raw(c + '/'), lambda: S._raw(d + '/privat/x?id=1'),
                     lambda: RS._post_json(e + '/kort/1', {}), lambda: dawa._get(vask)):
            try:
                kald()
            except Exception as fejl:           # som en henter, der sluger fejlen
                beskeder.append(str(fejl))
        laeses = ' - regnes som forbud'
        self.assertEqual(RS.ROBOTS_STOP, [
            (a + '/side', 'robots.txt paa a.example kunne ikke laeses (HTTP 503)' + laeses),
            (a + '/side', 'robots.txt paa a.example kunne ikke laeses (HTTP 503)' + laeses),
            (b + '/butikker', 'robots.txt paa b.example kunne ikke laeses (TimeoutError: timed out)' + laeses),
            (c + '/', 'robots.txt paa c.example kunne ikke laeses (HTTP 403)' + laeses),
            (d + '/privat/x', 'robots.txt paa d.example forbyder /privat/x'),
            (e + '/kort/1', 'robots.txt paa e.example forbyder /kort/1')])
        self.assertEqual(beskeder, [grund + ' - henter ikke' for _, grund in RS.ROBOTS_STOP]
                         + ['robots.txt paa adressevaelger.dk forbyder /vask/ - henter ikke'])    # dawa._get
        self.assertEqual(dict(RS._ROBOTS_GRUND), {a: 'HTTP 503', b: 'TimeoutError: timed out', c: 'HTTP 403',
                                                  e: 'HTTP 503'})
        self.assertEqual(self.anmodninger, [a + '/robots.txt'] * 2 + [b + '/robots.txt'] * 2 + [c + '/robots.txt',
                                            d + '/robots.txt'] + [e + '/robots.txt'] * 2 + [dawa.AV_URL + '/robots.txt'])

    def test_log_false_skriver_intet_og_url_gemmes_uden_query(self):
        """review 14-10-2026 (anden runde): _tjek_robots(url, log=False) - som dawa._get bruger - rejser RobotsForbudt
        med samme grund som foer, men tilfoejer intet til ROBOTS_STOP; det gaelder baade et forbud i filen og en
        robots.txt, der ikke kunne laeses. Med log=True (standard) gemmes url'en som scheme://vaert/sti: en query kan
        baere et token (adressevaelger.dk's ?token=), og linjen kan ende i en committet rapport. Ogsaa et #anker
        falder bort."""
        d, x, token = 'https://d.example', 'https://x.example', 'HEMMELIGT-TOKEN-4711'
        self.net[d + '/robots.txt'] = [b'User-agent: *\nDisallow: /privat/\n']
        self.net[x + '/robots.txt'] = [_http_fejl(x + '/robots.txt', 503)]
        hale = '?token=%s&id=1#anker' % token
        for sti, grund in ((d + '/privat/x', 'robots.txt paa d.example forbyder /privat/x'),
                           (x + '/api/v1', 'robots.txt paa x.example kunne ikke laeses (HTTP 503) - regnes som forbud')):
            with self.subTest(sti=sti):
                del RS.ROBOTS_STOP[:]
                with self.assertRaises(RS.RobotsForbudt) as cm:
                    RS._tjek_robots(sti + hale, log=False)
                self.assertEqual(str(cm.exception), grund + ' - henter ikke')
                self.assertEqual(RS.ROBOTS_STOP, [])
                with self.assertRaises(RS.RobotsForbudt):
                    RS._tjek_robots(sti + hale)
                self.assertEqual(RS.ROBOTS_STOP, [(sti, grund)])
                self.assertNotIn(token, repr(RS.ROBOTS_STOP) + str(cm.exception))
        self.assertEqual((RS.OMDIRIGERING_STOP, self.anmodninger),
                         ([], [d + '/robots.txt'] + [x + '/robots.txt'] * 2))


# ---------------------------------------------------------------- omdirigeringer (den globale opener)
class Omdirigeringer(_Grund):
    """urlopen foelger 301/302 uden om _raw: en butiksside, der flyttede til en forbudt soegeside eller en anden
    vaert, blev hentet uden robots-tjek og Crawl-delay (review 14-10-2026). retail_sources installerer derfor
    ved import en global opener, hvis omdirigerings-handler (_RobotsOmdirigering) tjekker hvert nyt maal, foer
    det foelges. Her koerer urllibs egen maskine - OpenerDirector, HTTPErrorProcessor og den installerede
    handler (_kaede_som_den_installerede); kun det nederste led, der ellers aabner en forbindelse, er en stub
    (_FalskVaert). Uret er simuleret som i CrawlDelay."""

    def setUp(self):
        _Grund.setUp(self)
        self.ur = _Ur()
        self._start(mock.patch.object(RS.time, 'monotonic', self.ur.monotonic))
        self.sove.side_effect = self.ur.sleep
        self.tider = []         # (url, uret) ved hver anmodning
        self.kaede = _kaede_som_den_installerede(_FalskVaert(self))

    def _urlopen(self, req, timeout=None, **kw):
        return self.kaede.open(req, timeout=timeout)

    def test_den_globale_opener_har_robots_omdirigeringen(self):
        """Den opener, retail_sources installerer ved import, har _RobotsOmdirigering som eneste
        omdirigerings-handler; den gaelder alle urlopen-kald i processen, ogsaa i sources.py, refresh_data.py
        og dawa.py (review 14-10-2026)."""
        installeret = urllib.request._opener
        self.assertIsNotNone(installeret, 'ingen global opener installeret')
        self.assertEqual([type(h) for h in installeret.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)],
                         [RS._RobotsOmdirigering])

    def test_omdirigering_til_forbudt_sti_rejser_robotsforbudt_uden_kald(self):
        """Flytter en tilladt side (301/302) til en sti, maalvaertens robots.txt forbyder - paa samme vaert
        (relativ Location) eller en anden - rejser kaldet RobotsForbudt, og den forbudte url hentes aldrig. Foer
        fulgte urlopen omdirigeringen uden om tjekket (review 14-10-2026). Anden runde af review 14-10-2026: det er
        en RobotsOmdirigeringForbudt (en RobotsForbudt), og stoppet staar i OMDIRIGERING_STOP uden query - IKKE i
        ROBOTS_STOP: en lukket butiks side, der flytter til en forbudt soegeside, er en side, der er vaek, ikke et
        stop, der skal kassere hele kaedens svar."""
        self.assertTrue(issubclass(RS.RobotsOmdirigeringForbudt, RS.RobotsForbudt))
        a, b = 'https://a.example', 'https://b.example'
        self.net[a + '/robots.txt'] = [b'User-agent: *\nDisallow: /soeg\n']
        self.net[a + '/butik/1'] = [_Omdiriger('/soeg?q=butik+1', 301)]
        self.net[a + '/soeg?q=butik+1'] = [b'maa ikke hentes']
        self.net[a + '/butik/2'] = [_Omdiriger(b + '/privat/2', 302)]
        self.net[b + '/robots.txt'] = [b'User-agent: ClaudeBot\nDisallow: /privat/\n']
        self.net[b + '/privat/2'] = [b'maa ikke hentes']
        for side in (a + '/butik/1', a + '/butik/2'):
            with self.assertRaises(RS.RobotsOmdirigeringForbudt) as cm:
                _med_frist(lambda s=side: RS._raw(s), 5, 'omdirigeringen af ' + side + ' haenger')
            self.assertIn('(omdirigering) - foelger ikke', str(cm.exception))
        self.assertEqual(self.anmodninger, [a + '/robots.txt', a + '/butik/1', a + '/butik/2', b + '/robots.txt'])
        self.assertEqual(RS.OMDIRIGERING_STOP, [(a + '/soeg', 'robots.txt paa a.example forbyder /soeg'),
                                                (b + '/privat/2', 'robots.txt paa b.example forbyder /privat/2')])
        self.assertEqual(RS.ROBOTS_STOP, [])

    def test_omdirigering_til_vaert_med_ulaeselig_robots_er_et_udfald(self):
        """Testene 14-10-2026: kunne maalvaertens robots.txt ikke laeses (503 to gange), blev omdirigeringen ogsaa
        til 'siden er vaek', og et kort udfald hos en anden vaert en falsk lukning. Nu er kun et LAEST forbud
        'vaek' (RobotsOmdirigeringForbudt); en ulaeselig robots.txt giver en almindelig RobotsForbudt, der staar i
        ROBOTS_STOP (henteren stoppes), og intet i OMDIRIGERING_STOP."""
        a, c = 'https://a.example', 'https://cdn.example'
        self.net[a + '/robots.txt'] = [b'User-agent: *\nDisallow:\n']
        self.net[a + '/butik/4'] = [_Omdiriger(c + '/butik/4/', 301)]
        fejl503 = urllib.error.HTTPError(c + '/robots.txt', 503, 'nede', {}, None)
        self.net[c + '/robots.txt'] = [fejl503, fejl503]
        self.net[c + '/butik/4/'] = [b'maa ikke hentes']
        with self.assertRaises(RS.RobotsForbudt) as cm:
            _med_frist(lambda: RS._raw(a + '/butik/4'), 5, 'omdirigeringen haenger')
        self.assertNotIsInstance(cm.exception, RS.RobotsOmdirigeringForbudt)
        self.assertIn('kunne ikke laeses (HTTP 503)', str(cm.exception))
        self.assertEqual(RS.OMDIRIGERING_STOP, [])
        self.assertEqual([u for u, _ in RS.ROBOTS_STOP], [c + '/butik/4/'])
        self.assertNotIn(c + '/butik/4/', self.anmodninger)

    def test_omdirigering_urllib_ikke_foelger_tjekkes_ikke(self):
        """review 14-10-2026 (anden runde): _RobotsOmdirigering spoerger urllib (super().redirect_request) FOERST og
        tjekker kun et maal, urllib faktisk foelger. En POST, der svarer 307, foelger urllib ikke (hverken 3.9 eller
        3.12): kaldet giver urllibs egen HTTPError 307, maalvaertens robots.txt hentes ikke, der ventes ingen
        Crawl-delay, og intet stop skrives. Foer blev maalet tjekket foerst: dets robots.txt blev hentet til ingen
        nytte, og et forbud dér blev et falsk stop, skoent intet ville blive hentet."""
        a, b, c = 'https://a.example', 'https://b.example', 'https://c.example'
        self.net[a + '/robots.txt'] = [b'User-agent: *\nDisallow:\n']
        self.net[a + '/api/1'] = [_Omdiriger(b + '/privat/api', 307)]          # maalet er forbudt
        self.net[a + '/api/2'] = [_Omdiriger(c + '/api', 307)]                 # maalet er tilladt, Crawl-delay
        self.net[b + '/robots.txt'] = [b'User-agent: *\nDisallow: /privat/\n']
        self.net[c + '/robots.txt'] = [b'User-agent: *\nCrawl-delay: 10\n']
        for side in (a + '/api/1', a + '/api/2'):
            with self.subTest(side=side):
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    _med_frist(lambda s=side: RS._post_json(s, {'q': 1}), 5, 'omdirigeringen af ' + side + ' haenger')
                self.assertEqual(cm.exception.code, 307)
        self.assertEqual(self.anmodninger, [a + '/robots.txt', a + '/api/1', a + '/api/2'])
        self.assertEqual((RS.ROBOTS_STOP, RS.OMDIRIGERING_STOP, self.ur.sovet), ([], [], []))
        self.assertEqual(list(RS._ROBOTS), [a])

    def test_omdirigering_af_dar_til_forbudt_vaert_er_dawanede(self):
        """review 14-10-2026 (anden runde): _gql kalder urlopen direkte (Datafordelerens GraphQL er undtaget
        robots-tjekket), men den globale opener tjekker stadig et omdirigeringsmaal. Sender DAR en 302 videre til en
        anden vaert, hvis robots.txt forbyder stien, slap RobotsOmdirigeringForbudt foer ud af _gql og vaeltede hele
        koerslen; nu er det et DAR-udfald (DawaNede) efter ét kald og uden pause. Maalet hentes ikke, stoppet staar i
        OMDIRIGERING_STOP uden query, og noeglen staar hverken dér eller i fejlteksten."""
        dar, andet = dawa.DAR_URL + '?apikey=TESTNOEGLE', 'https://andet.example'
        self.net[dar] = [_Omdiriger(andet + '/DAR/v2?apikey=TESTNOEGLE', 302)]
        self.net[andet + '/robots.txt'] = [b'User-agent: *\nDisallow: /DAR/\n']
        self.net[andet + '/DAR/v2?apikey=TESTNOEGLE'] = [b'{"data": {"ok": 1}}']     # maa ikke hentes
        with self.assertRaises(dawa.DawaNede) as cm:
            _med_frist(lambda: dawa._gql('{ ok }'), 5, 'omdirigeringen af DAR haenger')
        self.assertEqual(str(cm.exception),
                         'DAR: robots.txt paa andet.example forbyder /DAR/v2 (omdirigering) - foelger ikke')
        self.assertEqual(self.anmodninger, [dar, andet + '/robots.txt'])
        self.assertEqual(RS.OMDIRIGERING_STOP, [(andet + '/DAR/v2', 'robots.txt paa andet.example forbyder /DAR/v2')])
        self.assertEqual((RS.ROBOTS_STOP, self.ur.sovet), ([], []))
        self.assertNotIn('TESTNOEGLE', str(cm.exception) + repr(RS.OMDIRIGERING_STOP))

    def test_omdirigering_til_anden_vaert_spoerger_dens_robots_txt_og_venter_dens_crawl_delay(self):
        """En omdirigering til en anden vaert henter DEN vaerts robots.txt og venter dens Crawl-delay, foer
        maalet hentes - ogsaa ved naeste omdirigering dertil (review 14-10-2026: foer blev maalet hentet
        straks, uden at spoerge)."""
        a, b = 'https://a.example', 'https://b.example'
        self.net[a + '/robots.txt'] = [b'User-agent: *\nDisallow:\n']
        self.net[b + '/robots.txt'] = [b'User-agent: *\nCrawl-delay: 10\n']
        for i in (1, 2):
            self.net['%s/butik/%d' % (a, i)] = [_Omdiriger('%s/butik/%d' % (b, i), 302)]
            self.net['%s/butik/%d' % (b, i)] = [b'side %d' % i]
        for i in (1, 2):
            self.assertEqual(_med_frist(lambda i=i: RS._raw('%s/butik/%d' % (a, i)), 5, 'omdirigeringen haenger'),
                             b'side %d' % i)
        self.assertEqual(self.ur.sovet, [10, 10])
        self.assertEqual(self.tider, [(a + '/robots.txt', T0), (a + '/butik/1', T0), (b + '/robots.txt', T0),
                                      (b + '/butik/1', T0 + 10), (a + '/butik/2', T0 + 10), (b + '/butik/2', T0 + 20)])

    def test_omdirigering_af_robots_txt_foelges_uden_tjek_og_uden_haardknude(self):
        """En omdirigering, mens en robots.txt hentes, foelges uden robots-tjek (RFC 9309 2.3.1.2), ogsaa til en
        anden sti eller vaert, hvis egen robots.txt forbyder alt: traad-flaget _ROBOTS_HENTES.aktiv. Foer
        spurgte maalet robots.txt, mens _ROBOTS_LAAS var taget, og til en ny vaert eller sti ventede hentningen
        paa sin egen laas (review 14-10-2026). Flaget slippes bagefter: et forbudt kald i samme traad stoppes
        stadig. Hvert forsoeg har 3 s og sin egen laas."""
        a, lukket = 'https://a.example', 'https://lukket.example'
        regler = 'User-agent: *\nDisallow: /privat/\n'

        def i_en_traad():
            side = RS._raw(a + '/side')
            try:
                RS._raw(a + '/privat/1')
                privat = 'hentet'
            except RS.RobotsForbudt:
                privat = 'forbudt'
            return side, privat, getattr(RS._ROBOTS_HENTES, 'aktiv', False)

        for til in ('https://www.a.example/robots.txt',     # anden vaert, samme sti
                    'https://cdn.example/robots/a.txt',     # anden vaert og sti
                    a + '/robots-2026.txt',                 # samme vaert, anden sti
                    lukket + '/robots/a.txt'):              # en vaert, hvis cachede robots.txt forbyder alt
            with self.subTest(til=til):
                RS._ROBOTS.clear()
                RS._ROBOTS[lukket] = 'User-agent: *\nDisallow: /\n'
                del RS.ROBOTS_STOP[:]
                del RS.OMDIRIGERING_STOP[:]
                self.net = {a + '/robots.txt': [_Omdiriger(til, 301)], til: [regler.encode()], a + '/side': [b'ok']}
                self.anmodninger, self.tider = [], []
                with mock.patch.object(RS, '_ROBOTS_LAAS', threading.Lock()):
                    svar = _med_frist(i_en_traad, 3, 'omdirigeringen af robots.txt venter paa _ROBOTS_LAAS')
                self.assertEqual(svar, (b'ok', 'forbudt', False))
                self.assertEqual(self.anmodninger, [a + '/robots.txt', til, a + '/side'])
                self.assertEqual(dict(RS._ROBOTS), {a: regler, lukket: 'User-agent: *\nDisallow: /\n'})
                self.assertEqual(RS.ROBOTS_STOP, [(a + '/privat/1', 'robots.txt paa a.example forbyder /privat/1')])
                self.assertEqual(RS.OMDIRIGERING_STOP, [])     # robots.txt' omdirigering er ikke et stop (review)

    def test_omdirigering_til_datafordelerens_graphql_er_ikke_et_forbud(self):
        """ROBOTS_UNDTAGET gaelder ogsaa et omdirigeringsmaal: graphql.datafordeler.dk's robots.txt (401 uden
        noeglen) spoerges ikke, saa omdirigeringen foelges og bliver ikke til et falsk forbud (review
        14-10-2026)."""
        a, g = 'https://a.example', 'https://graphql.datafordeler.dk'
        self.net[a + '/robots.txt'] = [b'User-agent: *\nDisallow:\n']
        self.net[a + '/dar'] = [_Omdiriger(g + '/DAR/v2', 302)]
        self.net[g + '/robots.txt'] = [401]
        self.net[g + '/DAR/v2'] = [b'{"data": {}}']
        self.assertEqual(_med_frist(lambda: RS._raw(a + '/dar'), 5, 'omdirigeringen haenger'), b'{"data": {}}')
        self.assertEqual(self.anmodninger, [a + '/robots.txt', a + '/dar', g + '/DAR/v2'])
        self.assertEqual(RS.ROBOTS_STOP, [])
        self.assertEqual(RS.OMDIRIGERING_STOP, [])     # et omdirigerings-stop staar dér nu (review 14-10-2026)


# ---------------------------------------------------------------- sources.py og refresh_data.py
class SourcesOgRefreshData(_Grund):
    """sources._raw/_json/_post/osm_brand og refresh_data.get bruger samme tjek (RS._tjek_robots)."""

    K = 'https://overpass.kumi.systems'
    P = 'https://overpass.private.coffee'

    def test_sources_raw_json_post_forbudt_uden_urlopen(self):
        """sources._raw/_json/_post rejser RobotsForbudt uden urlopen (13-10-2026: clever, ionity og
        lagkagehuset tjekkede ikke robots.txt); en tilladt sti hentes stadig."""
        f = _FalskRobots({'https://geo.example': ['User-agent: *\nDisallow: /api/\n']})
        self.net['https://geo.example/kort'] = [b'{"ok": true}']
        with mock.patch.object(RS, '_text', f):
            for kald in (lambda: S._raw('https://geo.example/api/v2/locations'),
                         lambda: S._json('https://geo.example/api/v2/locations'),
                         lambda: S._post('https://geo.example/api/v2/locations/nearby', {'distanceM': 300000})):
                with self.assertRaises(RS.RobotsForbudt):
                    kald()
            self.assertEqual(self.anmodninger, [])
            self.assertEqual(S._post('https://geo.example/kort', {}), {'ok': True})
        self.assertEqual(self.anmodninger, ['https://geo.example/kort'])
        self.assertEqual(f.kald, ['https://geo.example/robots.txt'])

    def test_osm_brand_springer_forbudt_spejl_over(self):
        """osm_brand: forbyder et Overpass-spejls robots.txt /api/ (derfor er overpass-api.de taget ud),
        bruges det naeste - og det forbudte spejl kaldes ikke."""
        f = _FalskRobots({self.K: ['User-agent: *\nDisallow: /api/\n'],
                          self.P: ['User-agent: *\nAllow: /api/interpreter\n']})
        el = {'elements': [{'type': 'node', 'id': 42, 'lat': 55.676, 'lon': 12.568,
                            'tags': {'brand': '7-Eleven', 'name': '7-Eleven Test'}}]}
        self.net[self.P + '/api/interpreter'] = [json.dumps(el).encode()]
        with mock.patch.object(RS, '_text', f):
            rk = S.osm_brand(['7-Eleven'])
        self.assertEqual(self.anmodninger, [self.P + '/api/interpreter'])
        self.assertEqual([(r['brand'], r['name'], r['osm']) for r in rk], [('7-Eleven', '7-Eleven Test', 'node/42')])

    def test_osm_brand_alle_spejle_forbudt(self):
        """Forbyder (eller blokerer, 403) begge spejles robots.txt kaldet, er det en fejl - 'alle
        Overpass-spejle fejlede' - ikke et tomt svar, og intet spejl kaldes."""
        f = _FalskRobots({self.K: ['User-agent: *\nDisallow: /api/\n'], self.P: [403]})
        with mock.patch.object(RS, '_text', f):
            with self.assertRaises(RuntimeError) as cm:
                S.osm_brand(['7-Eleven'])
        self.assertIn('alle Overpass-spejle fejlede', str(cm.exception))
        self.assertIn('robots.txt', str(cm.exception))
        self.assertEqual(self.anmodninger, [])

    def test_osm_brand_tomt_svar_og_et_udfald_er_en_fejl(self):
        """Ét spejl svarer tomt ({"elements": []}), det andet fejler (HTTP 504, afbrudt forbindelse eller
        robots-forbud): RuntimeError, ikke []. Det tomme svar kan vaere Overpass' interne timeout (7-Eleven
        gav 0 og saa 177), og intet andet spejl bekraefter det (fundet af testene 14-10-2026)."""
        k, p = self.K + '/api/interpreter', self.P + '/api/interpreter'
        tomt, aaben = b'{"elements": []}', 'User-agent: *\nAllow: /api/interpreter\n'
        for navn, robots, net, spurgt, aarsag in (
                ('504, saa tomt', {self.K: [aaben], self.P: [aaben]},
                 {k: [_http_fejl(k, 504)], p: [tomt]}, [k, p], '504'),
                ('tomt, saa afbrudt', {self.K: [aaben], self.P: [aaben]},
                 {k: [tomt], p: [urllib.error.URLError('forbindelsen blev afbrudt')]}, [k, p], 'afbrudt'),
                ('forbudt, saa tomt', {self.K: ['User-agent: *\nDisallow: /api/\n'], self.P: [aaben]},
                 {p: [tomt]}, [p], 'robots.txt')):
            with self.subTest(navn):
                RS._ROBOTS.clear()
                self.net, self.anmodninger = net, []
                with mock.patch.object(RS, '_text', _FalskRobots(robots)):
                    with self.assertRaises(RuntimeError) as cm:
                        S.osm_brand(['7-Eleven'])
                self.assertIn('tomt', str(cm.exception))
                self.assertIn(aarsag, str(cm.exception))      # udfaldet staar i rapporten
                self.assertEqual(self.anmodninger, spurgt)

    def test_osm_brand_begge_spejle_tomme_er_et_svar(self):
        """Svarer begge spejle tomt, er de enige: [] (kaeden findes ikke i OSM) - men foerst, naar begge er
        spurgt (ét tomt svar kan vaere en intern timeout, se ovenfor; 14-10-2026)."""
        k, p = self.K + '/api/interpreter', self.P + '/api/interpreter'
        self.net[k] = [b'{"elements": []}']
        self.net[p] = [b'{"elements": []}']
        with mock.patch.object(RS, '_text', _FalskRobots({self.K: ['User-agent: *\nAllow: /api/interpreter\n'],
                                                          self.P: [404]})):
            self.assertEqual(S.osm_brand(['7-Eleven']), [])
        self.assertEqual(self.anmodninger, [k, p])

    def test_refresh_data_get_forbudt_uden_urlopen(self):
        """refresh_data.get (OK og Tesla) spoerger robots.txt foerst: forbudt -> RobotsForbudt uden
        urlopen; tilladt -> JSON'en (14-10-2026)."""
        tesla = 'https://supercharge.info/service/supercharge/allSites'
        f = _FalskRobots({'https://mobility-prices.ok.dk': ['User-agent: *\nDisallow: /api/\n'],
                          'https://supercharge.info': [404]})
        self.net[tesla] = [b'[{"id": 1}]']
        with mock.patch.object(RS, '_text', f):
            with self.assertRaises(RS.RobotsForbudt):
                refresh_data.get('https://mobility-prices.ok.dk/api/v1/fuel-prices')
            self.assertEqual(refresh_data.get(tesla), [{'id': 1}])
        self.assertEqual(self.anmodninger, [tesla])


# ---------------------------------------------------------------- dawa.py
class DawaKald(_Grund):
    """dawa._get (Adressevaelgeren, med robots-tjek) og dawa._gql (DAR, uden robots-tjek, med genforsoeg)."""

    DAR = dawa.DAR_URL + '?apikey=TESTNOEGLE'

    def test_get_robots_forbud_er_dawanede_foer_urlopen(self):
        """Forbyder eller blokerer adressevaelger.dk's robots.txt kaldet, rejser _get DawaNede foer
        urlopen: et forbud er et udfald, ikke None ('findes ikke') (14-10-2026)."""
        url = dawa.AV_URL + '/vask/?token=x&adresse=Vestergade+1'
        for udfald in (['User-agent: *\nDisallow: /vask/\n'], [403], [503]):
            with self.subTest(udfald=repr(udfald)):
                RS._ROBOTS.clear()
                with mock.patch.object(RS, '_text', _FalskRobots({dawa.AV_URL: udfald})):
                    with self.assertRaises(dawa.DawaNede) as cm:
                        dawa._get(url)
                self.assertIn('robots.txt', str(cm.exception))
        self.assertEqual(self.anmodninger, [])

    def test_get_robots_stop_logges_ikke_saetter_av_robots_stop_og_udloeber(self):
        """review 14-10-2026 (anden runde): dawa._get kalder _tjek_robots(url, log=False). Et robots-stop paa
        adressevaelger.dk er et adresse-udfald (DawaNede), ikke henterens egen kilde: ROBOTS_STOP forbliver tom
        (ellers kasserede refresh_retail fx carlsjr's fuldstaendige svar), og url'ens ?token= staar intet sted -
        hverken i stop-listerne, i dawa.AV_ROBOTS_STOP eller i fejlteksten. AV_ROBOTS_STOP = (grund, uret), og
        robots_stoppet() giver grunden i 300 s (validate.py's adressevask venter saa ikke 15 s pr. raekke), derefter
        None; robots_stoppet(inden=10 ** 9), som rapporten bruger, husker den stadig. Ligesaa for en blokeret (403)
        og en ulaeselig (503 to gange) robots.txt. Uret er simuleret."""
        ur = _Ur()
        self._start(mock.patch.object(RS.time, 'monotonic', ur.monotonic))
        av, token = dawa.AV_URL, 'HEMMELIGT-TOKEN-4711'
        vask = av + '/vask/?token=%s&adresse=Vestergade+1' % token
        self.net[vask] = [b'{"maa": "ikke hentes"}']
        laeses = 'robots.txt paa adressevaelger.dk kunne ikke laeses (HTTP %d) - regnes som forbud'
        for udfald, grund, hentninger in (
                (b'User-agent: *\nDisallow: /vask/\n', 'robots.txt paa adressevaelger.dk forbyder /vask/', 1),
                (_http_fejl(av + '/robots.txt', 403), laeses % 403, 1),
                (_http_fejl(av + '/robots.txt', 503), laeses % 503, 2)):
            with self.subTest(grund=grund):
                for d in (RS._ROBOTS, RS._ROBOTS_GRUND, RS._ROBOTS_FORBIGAAENDE):
                    d.clear()
                dawa.AV_ROBOTS_STOP, ur.nu, self.anmodninger = None, T0, []
                self.net[av + '/robots.txt'] = [udfald]
                self.assertIsNone(dawa.robots_stoppet())
                with self.assertRaises(dawa.DawaNede) as cm:
                    _med_frist(lambda: dawa._get(vask), 5, 'dawa._get haenger')
                besked = grund + ' - henter ikke'
                self.assertEqual(str(cm.exception), besked)
                self.assertEqual(dawa.AV_ROBOTS_STOP, (besked, T0))
                self.assertEqual((RS.ROBOTS_STOP, RS.OMDIRIGERING_STOP), ([], []))
                self.assertEqual(self.anmodninger, [av + '/robots.txt'] * hentninger)     # intet kald til /vask/
                alt = repr((str(cm.exception), RS.ROBOTS_STOP, RS.OMDIRIGERING_STOP, dawa.AV_ROBOTS_STOP,
                            dict(RS._ROBOTS_GRUND), dawa.robots_stoppet()))
                self.assertNotIn('?token', alt)
                self.assertNotIn(token, alt)
                for efter, svar in ((200, besked), (300, besked), (301, None), (10 ** 6, None)):
                    ur.nu = T0 + efter
                    self.assertEqual(dawa.robots_stoppet(), svar)
                self.assertEqual(dawa.robots_stoppet(inden=10 ** 9), besked)

    def test_get_genforsoeg_og_400_404_er_et_svar(self):
        """_get proever et tabt kald igen (ellers fik en raekke tavst intet postnr/by); tre udfald = DawaNede,
        men 400/404 er et SVAR (None) uden genforsoeg (review 29-09-2026: falsk koerselsfejl hver uge)."""
        u1, u2, u3, u4 = (dawa.AV_URL + '/adresser/%d?token=x' % i for i in range(1, 5))
        self.net[u1] = [urllib.error.URLError('afbrudt'), _http_fejl(u1, 503, b''), b'{"id": "1"}']
        self.net[u2] = [_http_fejl(u2, 503, b'')]
        self.net[u3] = [_http_fejl(u3, 404, b'')]
        self.net[u4] = [_http_fejl(u4, 400, b'')]
        with mock.patch.object(RS, '_text', _FalskRobots({dawa.AV_URL: [404]})):
            self.assertEqual(dawa._get(u1), {'id': '1'})
            with self.assertRaises(dawa.DawaNede):
                dawa._get(u2)
            self.assertIsNone(dawa._get(u3))
            self.assertIsNone(dawa._get(u4))
        self.assertEqual(dict(collections.Counter(self.anmodninger)), {u1: 3, u2: 3, u3: 1, u4: 1})

    def test_gql_unexpected_execution_error_proeves_igen(self):
        """DAR svarer under belastning HTTP 200 med GraphQL-fejlen 'Unexpected Execution Error': den proeves
        igen (13-10-2026 fejlede syv hentere paa den, mens validate.py koerte)."""
        fejl = json.dumps({'errors': [{'message': 'Unexpected Execution Error', 'path': ['DAR_Postnummer'],
                                       'locations': [{'line': 1, 'column': 3}]}], 'data': None}).encode()
        data = {'DAR_Postnummer': {'nodes': [{'postnr': '8000'}]}}
        self.net[self.DAR] = [fejl, fejl, json.dumps({'data': data}).encode()]
        self.assertEqual(dawa._gql('{ DAR_Postnummer { nodes { postnr } } }'), data)
        self.assertEqual(self.anmodninger, [self.DAR] * 3)

    def test_gql_fejl_i_forespoergslen_rejses_efter_et_kald(self):
        """En fejl i SELVE forespoergslen (ukendt felt) er ikke forbigaaende: DawaNede efter praecis ét
        kald og ingen pause (reglen fra 13-10-2026 maa ikke gentage alt)."""
        fejl = {'errors': [{'message': "Field 'foo' is not defined", 'locations': [{'line': 1, 'column': 3}]}],
                'data': None}
        self.net[self.DAR] = [json.dumps(fejl).encode(), b'{"data": {"foo": 1}}']
        with self.assertRaises(dawa.DawaNede) as cm:
            dawa._gql('{ foo }')
        self.assertIn('foo', str(cm.exception))
        self.assertEqual(self.anmodninger, [self.DAR])
        self.sove.assert_not_called()

    def test_gql_http_udfald_og_afkortet_svar_proeves_igen(self):
        """_gql proever 503, 401 (ny noegle: tilfaeldige 401 den foerste time, DAF-AUTH-0005, 29-09-2026),
        afbrudt forbindelse og et afkortet svar (IncompleteRead, review 29-09-2026) igen."""
        self.net[self.DAR] = [_http_fejl(self.DAR, 503, b'Service Unavailable'),
                              _http_fejl(self.DAR, 401, b'DAF-AUTH-0005'),
                              urllib.error.URLError('forbindelsen blev afbrudt'),
                              _Svar(http.client.IncompleteRead(b'{"da', 300)),
                              b'{"data": {"ok": 1}}']
        self.assertEqual(dawa._gql('{ ok }'), {'ok': 1})
        self.assertEqual(self.anmodninger, [self.DAR] * 5)

    def test_gql_http_400_rejses_straks_og_noeglen_skjules(self):
        """HTTP 400 er en fejl i forespoergslen: DawaNede efter ét kald - og noeglen maa ikke staa i
        fejlteksten, som ender i rapporten ('HENTER FEJLEDE ...')."""
        self.net[self.DAR] = [_http_fejl(self.DAR, 400, b'DAF-GQL-0009 ugyldig: ' + self.DAR.encode()),
                              b'{"data": {}}']
        with self.assertRaises(dawa.DawaNede) as cm:
            dawa._gql('{ x }')
        self.assertEqual(self.anmodninger, [self.DAR])
        self.assertIn('400', str(cm.exception))
        self.assertNotIn('TESTNOEGLE', str(cm.exception))

    def test_gql_robotsforbudt_fra_urlopen_er_dawanede(self):
        """review 14-10-2026 (anden runde): den globale opener (retail_sources) kan rejse RobotsForbudt eller
        RobotsOmdirigeringForbudt inde i urlopen - fx ved en omdirigering til en anden vaert (se Omdirigeringer). _gql
        goer det til et DAR-udfald (DawaNede) efter ét kald og uden pause; foer slap undtagelsen ud af _gql og
        vaeltede hele koerslen."""
        for fejl in (RS.RobotsForbudt('robots.txt paa andet.example forbyder /DAR/v2 - henter ikke'),
                     RS.RobotsOmdirigeringForbudt('robots.txt paa andet.example forbyder /DAR/v2 (omdirigering) - '
                                                  'foelger ikke')):
            with self.subTest(fejl=type(fejl).__name__):
                self.anmodninger = []
                self.sove.reset_mock()
                self.net[self.DAR] = [fejl, b'{"data": {"ok": 1}}']
                with self.assertRaises(dawa.DawaNede) as cm:
                    dawa._gql('{ ok }')
                self.assertEqual(str(cm.exception), 'DAR: ' + str(fejl))
                self.assertEqual(self.anmodninger, [self.DAR])
                self.sove.assert_not_called()

    def test_gql_andre_runtimeerrors_rejses_uaendret(self):
        """Kun RobotsForbudt og RobotsOmdirigeringForbudt bliver til DawaNede (review 14-10-2026): en anden
        RuntimeError inde i urlopen - fx tests/hjaelp.py's NetSpaerret, naar et kald slipper forbi stubbene - rejses
        uaendret efter ét kald og uden genforsoeg; den maa ikke forklaedes som et DAR-udfald."""
        for fejl in (RuntimeError('noget helt andet'), hjaelp.NetSpaerret('testene maa ikke bruge nettet')):
            with self.subTest(fejl=type(fejl).__name__):
                self.anmodninger = []
                self.sove.reset_mock()
                self.net[self.DAR] = [fejl, b'{"data": {"ok": 1}}']
                with self.assertRaises(RuntimeError) as cm:
                    dawa._gql('{ ok }')
                self.assertIs(cm.exception, fejl)
                self.assertEqual(self.anmodninger, [self.DAR])
                self.sove.assert_not_called()


# ---------------------------------------------------------------- DAR-laasen
class DarLaas(unittest.TestCase):
    """dawa.tag_dar_laas: én DAR-tung koersel ad gangen paa maskinen (flock paa kartago-dar.lock i tmp,
    14-10-2026; 13-10-2026 gav validate.py og en proevekoersel samtidig 96 % udfald). tests/hjaelp.py
    slaar den fra i alle andre tests; her proeves den rigtige, i en frisk tmp-mappe."""

    def setUp(self):
        self.tag = hjaelp.AEGTE_TAG_DAR_LAAS
        # den rigtige funktion - ikke hjaelp.py's tomme erstatning
        self.assertEqual((self.tag.__module__, self.tag.__name__), ('dawa', 'tag_dar_laas'))
        self.mappe = tempfile.mkdtemp(prefix='kartago-test-')
        self.addCleanup(shutil.rmtree, self.mappe, True)
        self.fil = os.path.join(self.mappe, 'kartago-dar.lock')
        for p in (mock.patch.object(tempfile, 'tempdir', self.mappe),     # tempfile.gettempdir() -> mappen
                  mock.patch.object(dawa, '_DAR_LAAS', None)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._slip)             # koerer foer patchene stoppes (sidst ind, foerst ud)

    def _slip(self):
        """Lukker filen, testen tog laasen paa (og dermed flock'en), saa senere tests ikke paavirkes."""
        f, dawa._DAR_LAAS = dawa._DAR_LAAS, None
        if f is not None:
            f.close()

    def _laes(self):
        with open(self.fil) as f:
            return f.read()

    def test_tager_laasen_skriver_hvem_og_andet_kald_goer_intet(self):
        """Laasen tages med flock, og navn og pid skrives i kartago-dar.lock; et andet kald i samme proces
        goer intet - det maa ikke vente paa processens egen laas (DAR-laasen, 14-10-2026)."""
        with mock.patch.object(sys, 'stderr', io.StringIO()) as err:
            _med_frist(lambda: self.tag('validate.py'), 3, 'tag_dar_laas venter, skoent ingen holder laasen')
            f = dawa._DAR_LAAS
            self.assertIsNotNone(f)
            self.assertEqual(self._laes(), 'validate.py, pid %d' % os.getpid())
            r = subprocess.run([sys.executable, '-I', '-c', _PROEV_DAR_LAAS, self.fil],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30)
            self.assertEqual((r.stdout.strip(), r.returncode), ('optaget', 0), r.stderr)   # flock'en holdes
            _med_frist(lambda: self.tag('refresh_retail.py'), 3, 'andet kald venter paa processens egen laas')
        self.assertIs(dawa._DAR_LAAS, f)
        self.assertEqual(self._laes(), 'validate.py, pid %d' % os.getpid())
        self.assertEqual(err.getvalue(), '')

    def test_venter_paa_en_anden_proces_og_siger_det(self):
        """Holder en anden proces laasen, venter tag_dar_laas, til den slipper, og skriver i stderr, at den
        venter og paa hvem - foer koerte to DAR-tunge koersler samtidig (13-10-2026: 96 % udfald)."""
        p = subprocess.Popen([sys.executable, '-I', '-c', _HOLD_DAR_LAAS, self.fil], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.addCleanup(_afslut, p)
        linje = _med_frist(p.stdout.readline, 30, 'hjaelpeprocessen tog ikke laasen')
        self.assertEqual(linje.strip(), 'laast', p.stderr.read() if not linje else linje)
        holder = self._laes()                   # 'refresh_retail.py, pid N' - skrevet af hjaelpeprocessen
        ud, err = {}, io.StringIO()

        def tag():
            try:
                self.tag('validate.py')
            except BaseException as e:          # gives videre til testen nedenfor
                ud['fejl'] = e

        t = threading.Thread(target=tag)
        t.daemon = True
        try:
            with mock.patch.object(sys, 'stderr', err):
                t.start()
                frist = time.monotonic() + 5
                while 'venter' not in err.getvalue() and t.is_alive() and time.monotonic() < frist:
                    threading.Event().wait(0.01)
                threading.Event().wait(0.3)     # tid nok til at vende tilbage, hvis den ikke venter
                besked, ventede = err.getvalue(), t.is_alive()
                ventende = (dawa._DAR_LAAS, self._laes())
                p.stdin.close()                 # den anden koersel slutter og slipper laasen
                t.join(5)
                p.wait(10)                      # slutter af sig selv (draebes kun, hvis testen fejler)
        finally:
            _afslut(p)
            if t.is_alive():
                t.join(5)
        self.assertIn('venter', besked)
        self.assertIn(holder, besked)           # hvem den venter paa
        self.assertTrue(ventede, 'tag_dar_laas vendte tilbage, mens en anden proces holdt laasen')
        self.assertEqual(ventende, (None, holder))      # roerer hverken filen eller _DAR_LAAS imens
        self.assertFalse(t.is_alive(), 'tag_dar_laas fik ikke laasen, da den anden proces slap den')
        self.assertNotIn('fejl', ud)
        self.assertEqual(self._laes(), 'validate.py, pid %d' % os.getpid())
        self.assertEqual(p.returncode, 0)



class RobotsTidspunkt(unittest.TestCase):
    def test_tidspunktet_skrives_foer_cachen(self):
        """Fundet af testene 14-10-2026: _ROBOTS blev skrevet foer _SIDSTE_KALD. En traad, der saa
        vaerten i cachen i netop det oejeblik, fandt intet seneste kald og kaldte straks efter
        robots.txt - uden Crawl-delay. Nu skrives tidspunktet foerst: efter et svar, efter et
        genforsoeg, ved 4xx og ved to udfald."""
        class Kontrol(dict):
            def __setitem__(selv, k, v):
                if k not in RS._SIDSTE_KALD:
                    raise AssertionError(f'_ROBOTS[{k!r}] skrevet foer _SIDSTE_KALD')
                dict.__setitem__(selv, k, v)
        fejl500 = urllib.error.HTTPError('https://x.dk/robots.txt', 500, 'fejl', {}, None)
        fejl404 = urllib.error.HTTPError('https://x.dk/robots.txt', 404, 'nej', {}, None)
        for navn, svar, tilladt in (('svar straks', ['User-agent: *\nCrawl-delay: 10\n'], True),
                                    ('5xx, saa svar', [fejl500, 'User-agent: *\nCrawl-delay: 10\n'], True),
                                    ('404', [fejl404], True),
                                    ('to timeouts', [TimeoutError('t'), TimeoutError('t')], False)):
            with self.subTest(navn), \
                    mock.patch.object(RS, '_ROBOTS', Kontrol()), \
                    mock.patch.object(RS, '_SIDSTE_KALD', {}), \
                    mock.patch.dict(RS._ROBOTS_GRUND, clear=True), \
                    mock.patch.dict(RS._ROBOTS_FORBIGAAENDE, clear=True), \
                    mock.patch.object(RS, '_text', side_effect=svar), \
                    mock.patch.object(RS.time, 'sleep'):
                self.assertEqual(RS._robots_tilladt('https://x.dk/side'), tilladt)
                self.assertIn('https://x.dk', RS._SIDSTE_KALD)
                self.assertIn('https://x.dk', RS._ROBOTS)


if __name__ == '__main__':
    unittest.main()
