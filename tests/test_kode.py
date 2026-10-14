import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

import ast
import hashlib
import re
import unittest
import urllib.parse

ROD = hjaelp.ROD

# Engangsscripts, der ligger i repoet som dokumentation, men aldrig koeres. De er undtaget
# reglerne for netkald, fordi de ikke kan koere: de kaldte DAWA, som lukkede 1/10-2026 (HTTP 410).
HISTORISK = {'apply_audit_fixes.py': 'QA-auditten 08-07-2026; kaldte DAWA, som er lukket'}
PROD = sorted(f for f in os.listdir(ROD) if f.endswith('.py') and f not in HISTORISK)

# Hvert netkald i repoet gaar gennem en af disse funktioner, og de spoerger robots.txt foerst
# (14-10-2026 tjekkede 38 af 75 ugentlige hentere det ikke selv).
NETKALD = {('retail_sources.py', '_raw'), ('sources.py', '_raw'), ('sources.py', '_post'),
           ('sources.py', 'osm_brand'), ('dawa.py', '_get'), ('dawa.py', '_gql'),
           ('refresh_data.py', 'get')}
UDEN_ROBOTS = {('dawa.py', '_gql'): 'Datafordelerens GraphQL: vores egen noegle og vilkaar; vaerten '
                                    'svarer 401 paa alle stier uden noeglen, ogsaa /robots.txt (14-10-2026)'}
ROBOTS_KALD = {'_tjek_robots', '_robots_tilladt'}

# Vaerter, der aldrig maa kaldes (brugerens regler og vaerternes robots.txt). Teksten er grunden.
FORBUDTE_VAERTER = {
    'krak.dk': 'udelukket af brugeren',
    'degulesider.dk': 'udelukket af brugeren',
    'overpass-api.de': "robots.txt 'Disallow: /api/' - brug overpass.kumi.systems / overpass.private.coffee",
    'api.openstreetmap.org': "robots.txt 'Disallow: /api/'",
    'tile.openstreetmap.org': 'robots.txt forbyder /12/-/23/',
    'api.monta.app': 'kraever et bearer-token; tokens hentes ikke ud af apps',
    'map-prod-public.evmaps-prod.alpaque.net': 'udelukket af brugeren',
    'businessservice.dataudveksler.app.vd.dk': 'udelukket af brugeren',
    'kartago.dk': 'brugerens egen side - roeres aldrig',
}
FORBUDTE_STIER = [('coop.dk', '/umbraco/', 'robots.txt forbyder /umbraco/'),
                  ('geo-emobility.okcloud.dk', '/api/manual/', 'brugerens regel: aldrig /api/manual/*')]
# Brugerens adresse som SHA-256 - selve adressen maa ikke staa i repoet (heller ikke her).
BRUGER_SHA256 = 'bc5cf6f693f154af5fb7e5ee536bbf67309edba518d1569971dfec0f38af4c34'
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
# Ikke-personlige adresser, der maa staa i kode: bot-identiteten i workflowet.
EMAIL_TILLADT = {'actions@users.noreply.github.com'}


def _traeer():
    ud = {}
    for f in PROD:
        with open(os.path.join(ROD, f), encoding='utf-8') as fh:
            ud[f] = ast.parse(fh.read(), filename=f)
    return ud


TRAEER = _traeer()


def _forfaedre(tree):
    far = {}
    for n in ast.walk(tree):
        for b in ast.iter_child_nodes(n):
            far[b] = n
    return far


def _doc_ider(tree):
    """id() paa strenge, der staar som et udtryk for sig selv (docstrings og 'kommentar-strenge')."""
    return {id(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}


def _kodestrenge(tree):
    """(linje, tekst) for alle strengkonstanter i KODEN - ikke i docstrings."""
    doc = _doc_ider(tree)
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc]


def _funktion(node, far):
    while node in far:
        node = far[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


def _tekst(*sti):
    with open(os.path.join(ROD, *sti), encoding='utf-8') as fh:
        return fh.read()


def _kaldnavn(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None


class Netkald(unittest.TestCase):
    def test_hvert_netkald_gaar_gennem_en_robots_tjekket_hjaelper(self):
        """14-10-2026: 38 af 75 ugentlige hentere spurgte ikke selv robots.txt. Nu ligger
        tjekket i hjaelperne; et nyt urlopen et andet sted ville gaa uden om det."""
        fejl = []
        for f, tree in TRAEER.items():
            far = _forfaedre(tree)
            for n in ast.walk(tree):
                if not (isinstance(n, ast.Call) and _kaldnavn(n) == 'urlopen'):
                    continue
                fn = _funktion(n, far)
                navn = fn.name if fn else '<modul>'
                if (f, navn) not in NETKALD:
                    fejl.append(f'{f}:{n.lineno} urlopen i {navn}() - kald via en robots-tjekket hjaelper')
                    continue
                if (f, navn) in UDEN_ROBOTS:
                    continue
                tjek = [c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call) and _kaldnavn(c) in ROBOTS_KALD]
                if not any(l < n.lineno for l in tjek):
                    fejl.append(f'{f}:{n.lineno} {navn}() kalder urlopen uden robots-tjek foerst')
        self.assertEqual(fejl, [])

    def test_ingen_reference_til_urlopen_uden_for_hjaelperne(self):
        """Review 14-10-2026: reglen saa kun KALD til urlopen, saa 'hent = urllib.request.urlopen; hent(req)'
        eller functools.partial(urllib.request.urlopen) gik uden om robots-tjekket. Nu maa urlopen slet ikke
        naevnes uden for de godkendte hjaelpere."""
        fejl = []
        for f, tree in TRAEER.items():
            far = _forfaedre(tree)
            for n in ast.walk(tree):
                navn = n.attr if isinstance(n, ast.Attribute) else n.id if isinstance(n, ast.Name) else None
                if navn != 'urlopen':
                    continue
                fn = _funktion(n, far)
                if (f, fn.name if fn else '<modul>') not in NETKALD:
                    fejl.append(f'{f}:{n.lineno} urlopen naevnt i {fn.name if fn else "<modul>"}()')
        self.assertEqual(fejl, [])

    def test_ingen_andre_netveje(self):
        """Ingen genveje uden om hjaelperne: http.client-forbindelser, sockets, urlretrieve,
        egne openers, requests eller curl/wget i en subprocess - heller ikke via 'from ... import
        urlopen as x' eller getattr(modul, 'urlopen') (review 14-10-2026). Den eneste opener er
        retail_sources' globale, der tjekker robots.txt ved omdirigeringer."""
        forbudt = {'HTTPConnection', 'HTTPSConnection', 'create_connection', 'urlretrieve',
                   'build_opener', 'OpenerDirector', 'install_opener', 'urlopen'}
        fejl = []
        for f, tree in TRAEER.items():
            far = _forfaedre(tree)
            for n in ast.walk(tree):
                if isinstance(n, ast.Attribute) and n.attr in forbudt - {'urlopen'}:
                    if f == 'retail_sources.py' and n.attr in ('build_opener', 'install_opener') \
                            and _funktion(n, far) is None:
                        continue                  # den globale opener med _RobotsOmdirigering
                    fejl.append(f'{f}:{n.lineno} {n.attr}')
                if isinstance(n, ast.ImportFrom) and n.module in ('urllib.request', 'http.client', 'urllib'):
                    navne = {a.name for a in n.names}
                    if navne & forbudt or (n.module == 'urllib' and 'request' in navne):
                        fejl.append(f'{f}:{n.lineno} from {n.module} import {sorted(navne)}')
                if isinstance(n, ast.Call) and _kaldnavn(n) == 'getattr' and len(n.args) > 1 \
                        and isinstance(n.args[1], ast.Constant) and n.args[1].value in forbudt:
                    fejl.append(f'{f}:{n.lineno} getattr(..., {n.args[1].value!r})')
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    mods = [a.name for a in n.names] + ([n.module] if isinstance(n, ast.ImportFrom) and n.module else [])
                    if any(m.split('.')[0] in ('requests', 'httpx', 'aiohttp', 'socket') for m in mods):
                        fejl.append(f'{f}:{n.lineno} import {mods}')
            for linje, s in _kodestrenge(tree):
                if re.search(r'(?<![\w-])(curl|wget)(?![\w-])', s) and len(s) < 40:
                    fejl.append(f'{f}:{linje} {s!r}')
        self.assertEqual(fejl, [])

    def test_omdirigeringer_tjekkes(self):
        """urlopen foelger omdirigeringer uden om _raw; den globale opener i retail_sources skal derfor
        have en omdirigerings-handler, der kalder _tjek_robots paa det nye maal (review 14-10-2026)."""
        tree = TRAEER['retail_sources.py']
        klasser = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        self.assertIn('_RobotsOmdirigering', klasser)
        metode = next(m for m in klasser['_RobotsOmdirigering'].body
                      if isinstance(m, ast.FunctionDef) and m.name == 'redirect_request')
        self.assertTrue(any(isinstance(c, ast.Call) and _kaldnavn(c) == '_tjek_robots' for c in ast.walk(metode)))
        installeret = [n for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                       and _kaldnavn(n.value) == 'install_opener']
        self.assertEqual(len(installeret), 1)
        self.assertIn('_RobotsOmdirigering', ast.dump(installeret[0]))

    def test_ingen_forbudte_vaerter(self):
        """Vaerter, som brugerens regler eller deres robots.txt udelukker, maa ikke staa i koden."""
        fejl = []
        for f, tree in TRAEER.items():
            for linje, s in _kodestrenge(tree):
                lav = s.lower()
                for vaert, grund in FORBUDTE_VAERTER.items():
                    if re.search(r'(?<![a-z0-9.-])(?:[a-z0-9-]+\.)*' + re.escape(vaert) + r'(?![a-z0-9-])', lav):
                        fejl.append(f'{f}:{linje} {vaert}: {grund}')
                for vaert, sti, grund in FORBUDTE_STIER:
                    if vaert in lav and sti in lav:
                        fejl.append(f'{f}:{linje} {vaert}{sti}: {grund}')
                if 'maps.monta.app' in lav and '?' in lav:
                    fejl.append(f'{f}:{linje} maps.monta.app med query-streng: udelukket af brugeren')
        self.assertEqual(fejl, [])


class Headers(unittest.TestCase):
    def test_ingen_forfalskede_referer_eller_origin(self):
        """Review 13-10-2026: et kald til q8truck.com sendte en Referer, kopieret fra gammel kode.
        En kilde skal svare os som os selv - ingen Referer/Origin, der foregiver en anden side."""
        navne = {'referer', 'referrer', 'origin'}
        fejl = []
        for f, tree in TRAEER.items():
            for n in ast.walk(tree):
                if isinstance(n, ast.Dict):
                    for k in n.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value.lower() in navne:
                            fejl.append(f'{f}:{k.lineno} {k.value!r} i en dict')
                elif isinstance(n, ast.Call) and any(k.arg and k.arg.lower() in navne for k in n.keywords):
                    fejl.append(f'{f}:{n.lineno} {_kaldnavn(n)}(..., Referer/Origin=...)')
                elif isinstance(n, ast.Call) and _kaldnavn(n) in ('add_header', 'putheader', 'add_unredirected_header') and n.args:
                    a = n.args[0]
                    if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.lower() in navne:
                        fejl.append(f'{f}:{n.lineno} {_kaldnavn(n)}({a.value!r})')
                elif isinstance(n, ast.Assign):
                    for t in n.targets:
                        if (isinstance(t, ast.Subscript) and isinstance(getattr(t, 'slice', None), ast.Constant)
                                and isinstance(t.slice.value, str) and t.slice.value.lower() in navne):
                            fejl.append(f'{f}:{n.lineno} [{t.slice.value!r}] = ...')
        self.assertEqual(fejl, [])


class Emailadresser(unittest.TestCase):
    TEKSTFILER = ('.py', '.yml', '.yaml', '.md', '.txt', '.json', '.html', '.csv', '.js')

    def _filer(self):
        for d, dirs, fs in os.walk(ROD):
            dirs[:] = [x for x in dirs if x not in ('.git', '__pycache__')]
            for f in fs:
                if f.endswith(self.TEKSTFILER):
                    yield os.path.join(d, f)

    def test_brugerens_adresse_staar_ingen_steder(self):
        """Brugerens e-mail stod i en User-Agent (06-10-2026, stadig i git-historikken). Den maa
        aldrig staa i en fil igen - heller ikke URL-kodet eller med et tegn foran ('(+adresse)',
        '%2Badresse', '_adresse'; review 14-10-2026). Testen kender kun dens SHA-256."""
        fundet = []
        for p in self._filer():
            with open(p, encoding='utf-8', errors='replace') as fh:
                t = urllib.parse.unquote(urllib.parse.unquote(fh.read()))
            for m in EMAIL.finditer(t):
                a = m.group(0).lower()
                lokal = a.split('@')[0]
                kandidater = [a] + [a[i:] for i in range(1, len(lokal)) if a[i - 1] in '._%+-']
                if any(hashlib.sha256(k.encode()).hexdigest() == BRUGER_SHA256 for k in kandidater):
                    fundet.append(os.path.relpath(p, ROD))
        self.assertEqual(fundet, [])

    def test_ingen_emailadresser_i_koden(self):
        """Ingen e-mailadresse i kodens strenge (User-Agents, headers, URL'er, payloads).
        Docstrings maa citere en kildes egne adresser (fx normal.dk's butiksmails)."""
        fejl = []
        for f, tree in TRAEER.items():
            for linje, s in _kodestrenge(tree):
                for m in EMAIL.finditer(s.replace('%40', '@')):
                    if m.group(0).lower() not in EMAIL_TILLADT:
                        fejl.append(f'{f}:{linje} {m.group(0)}')
        for m in EMAIL.finditer(_tekst('.github', 'workflows', 'weekly-refresh.yml')):
            if m.group(0).lower() not in EMAIL_TILLADT:
                fejl.append(f'weekly-refresh.yml: {m.group(0)}')
        self.assertEqual(fejl, [])


class DarLaas(unittest.TestCase):
    def test_de_fire_dar_tunge_skripter_tager_laasen(self):
        """testene goer dawa.tag_dar_laas til en no-op (hjaelp.py), saa uden denne test kunne et kald
        forsvinde uden at noget fejlede (review 14-10-2026). Hver DAR-tung indgang skal tage laasen:
        refresh_retail.main, refresh_data's __main__, validate.py's topniveau og cvr_tjek.main."""
        def kalder(knude):
            return any(isinstance(c, ast.Call) and _kaldnavn(c) == 'tag_dar_laas' for c in ast.walk(knude))

        def funktion(f, navn):
            return next(n for n in TRAEER[f].body if isinstance(n, ast.FunctionDef) and n.name == navn)
        self.assertTrue(kalder(funktion('refresh_retail.py', 'main')))
        self.assertTrue(kalder(funktion('cvr_tjek.py', 'main')))
        main_blok = [s for s in TRAEER['refresh_data.py'].body if isinstance(s, ast.If)
                     and isinstance(s.test, ast.Compare) and getattr(s.test.left, 'id', '') == '__name__']
        self.assertTrue(main_blok and kalder(main_blok[0]))
        topniveau = [s for s in TRAEER['validate.py'].body if isinstance(s, ast.Expr)]
        self.assertTrue(any(kalder(s) for s in topniveau))


class Modulstruktur(unittest.TestCase):
    def test_ingen_indsat_hoved_eller_testblok(self):
        """01-10-2026 kom en builder-agents Uno-X-blok ind i retail_sources.py med eget hoved
        (sys.path.insert, selvimport) og egen __main__-blok; 'python3 retail_sources.py netto'
        ville skrive Uno-X' JSON til en fil ved navn 'netto'. Kun ét __main__, og det staar sidst."""
        fejl = []
        for f, tree in TRAEER.items():
            mod = f[:-3]
            for n in ast.walk(tree):
                if (isinstance(n, ast.Attribute) and n.attr in ('insert', 'append')
                        and isinstance(n.value, ast.Attribute) and n.value.attr == 'path'
                        and isinstance(n.value.value, ast.Name) and n.value.value.id == 'sys'):
                    fejl.append(f'{f}:{n.lineno} sys.path.{n.attr}')
                if isinstance(n, ast.Import) and any(a.name == mod for a in n.names):
                    fejl.append(f'{f}:{n.lineno} importerer sig selv')
                if isinstance(n, ast.ImportFrom) and n.module == mod:
                    fejl.append(f'{f}:{n.lineno} importerer fra sig selv')
            main = [i for i, s in enumerate(tree.body)
                    if isinstance(s, ast.If) and isinstance(s.test, ast.Compare)
                    and isinstance(s.test.left, ast.Name) and s.test.left.id == '__name__']
            if len(main) > 1:
                fejl.append(f'{f}: {len(main)} __main__-blokke')
            if main and main[-1] != len(tree.body) - 1:
                fejl.append(f'{f}: kode efter __main__-blokken (linje {tree.body[main[-1] + 1].lineno})')
        self.assertEqual(fejl, [])


class Registre(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import csv
        import refresh_retail as R
        import retail_sources as RS
        cls.R, cls.RS = R, RS
        cls.navne = [n for n, _ in R.KAEDER]
        cls.raekker = {}
        for fn in R.FILER:
            with open(os.path.join(ROD, fn), encoding='utf-8-sig', newline='') as fh:
                cls.raekker[fn] = list(csv.reader(fh))[1:]
        cls.dato = re.compile(r'\b\d{2}-\d{2}-\d{4}\b|\b\d{4}-\d{2}-\d{2}\b')

    def test_kaeder_er_entydige_og_kaldbare(self):
        self.assertEqual(len(self.navne), len(set(self.navne)))
        self.assertTrue(all(callable(f) for _, f in self.R.KAEDER))

    def test_delmaengder_af_kaeder(self):
        """LADE_KAEDER, KUN_RAPPORT og EN_HALVDEL maa kun naevne hentere, der koeres; ellers er
        en stavefejl en tavs regel, der aldrig gaelder."""
        R, alle = self.R, set(self.navne)
        self.assertEqual(R.LADE_KAEDER - alle, set())
        self.assertEqual(R.KUN_RAPPORT - alle, set())
        self.assertEqual(set(R.EN_HALVDEL) - R.LADE_KAEDER, set())
        self.assertTrue(set(R.EN_HALVDEL.values()) <= {'bil', 'lastbil'}, R.EN_HALVDEL)

    def test_hver_henter_har_ejer(self):
        """17-09-2026: et maerke, som ingen henter er ansvarlig for, forsvinder tavst ud af
        overvaagningen (Brugsen: 265 butikker). Hver henter skal naevne sine maerker i EJER."""
        R = self.R
        self.assertEqual(set(self.navne) - set(R.EJER), set())
        # sport24 er taget ud af KAEDER 30-09-2026 (sport24.dk svarer 403 paa alt) men bevaret
        # i EJER og retail_sources, til kaeden aabner igen.
        self.assertEqual(set(R.EJER) - set(self.navne), {'sport24'})
        alle_maerker = {r[0] for rs in self.raekker.values() for r in rs}
        for k, ms in R.EJER.items():
            self.assertTrue(ms, k)
            if k in self.navne:
                self.assertEqual([m for m in ms if m not in alle_maerker], [], f'{k}: maerke findes ikke i data')

    def test_kendt_uden_kilde_peger_paa_rigtige_raekker_med_belaeg(self):
        """En KENDT-post for en raekke, der ikke findes (omdoebt/slettet), er en tavs, doed regel.
        Hver grund skal have en dato, saa man kan se hvor gammelt belaegget er."""
        par = {(r[0], r[1]) for rs in self.raekker.values() for r in rs}
        self.assertEqual([k for k in self.R.KENDT_UDEN_KILDE if k not in par], [])
        self.assertEqual([k for k, v in self.R.KENDT_UDEN_KILDE.items() if not self.dato.search(v)], [])

    def test_lader_kendt(self):
        lade = {(r[0], r[1]) for r in self.raekker[self.R.LADE]}
        for (b, navn, felt, vaerdi), grund in self.R.LADER_KENDT.items():
            self.assertIn((b, navn), lade)
            self.assertIn(felt, ('kW', 'ladepunkter'))
            self.assertTrue(vaerdi.isdigit(), vaerdi)
            self.assertRegex(grund, self.dato)

    def test_halvdel_ikke_i_kilden(self):
        """Undtagelser fra HALVDEL MANGLER: henteren koeres, maerket er dens, halvdelen er bil/lastbil,
        og grunden har en dato - ellers er det en tavs regel, der skjuler raekker fra overvaagningen."""
        R = self.R
        for (k, b, h), grund in R.HALVDEL_IKKE_I_KILDEN.items():
            self.assertIn(k, self.navne)
            self.assertIn(b, R.EJER.get(k, ()))
            self.assertIn(h, ('bil', 'lastbil'))
            self.assertRegex(grund, self.dato)

    def test_udeladt(self):
        for (b, gade), grund in self.R.UDELADT.items():
            self.assertEqual(gade, ' '.join(gade.lower().split()), 'noeglen er gadeteksten i lowercase')
            self.assertTrue(grund.strip(), (b, gade))

    def test_kildefejl(self):
        """KILDEFEJL rettes ind i kildeposterne foer sammenligningen; en forkert noegle eller en
        koordinat uden for Danmark ville give en tavs fejl eller en falsk ny butik."""
        felter = {'name', 'street', 'postnr', 'by', 'lat', 'lon', 'lastbil', 'kw', 'count', 'plug'}
        for (b, gade), v in self.RS.KILDEFEJL.items():
            self.assertEqual(gade, ' '.join(gade.lower().split()), (b, gade))
            self.assertTrue(v and set(v) <= felter, ((b, gade), v))
            if 'lat' in v or 'lon' in v:
                self.assertTrue(54.4 < v['lat'] < 57.9 and 7.8 < v['lon'] < 15.3, (b, gade))
            if 'postnr' in v:
                self.assertRegex(v['postnr'], r'^\d{4}$')
            if 'kw' in v:
                self.assertTrue(250 <= int(v['kw']) <= 1200, (b, gade))


class Dokumentation(unittest.TestCase):
    def test_antal_kilder_i_workflow_og_auto_update(self):
        """Tal i docs skrives aldrig fra hukommelsen (13-10-2026: '78 raekker' i et udkast)."""
        import refresh_retail as R
        n, nl = len(R.KAEDER), len(R.LADE_KAEDER)
        for fn in ('AUTO_UPDATE.md', os.path.join('.github', 'workflows', 'weekly-refresh.yml')):
            t = _tekst(fn)
            tal = [int(x) for x in re.findall(r'(\d+) kilder', t)]
            self.assertTrue(tal, fn)
            self.assertEqual(set(tal), {n}, fn)
            for a, b in re.findall(r'(\d+) (?:kaeder|kæder) (?:\+|og) (\d+) (?:ladeoperatoerer|ladeoperatørers?)', t):
                self.assertEqual((int(a), int(b)), (n - nl, nl), fn)

    def test_workflow_tester_og_committer_readme(self):
        """Selvtesten koerer foer hentningen (uden test_data, som jobbets rebuild selv kan rette),
        data-testene efter genopbygningen og foer commit, ingen af de to testtrin kan slaas fra med
        continue-on-error eller if:, og README.md (med tallene fra readme_tal.py) er med i committen."""
        t = _tekst('.github', 'workflows', 'weekly-refresh.yml')
        trin = {}
        for blok in re.split(r'\n(?=      - name:)', t):
            m = re.match(r'      - name: (.*)', blok)
            if m:
                trin[m.group(1).strip()] = blok
        test_trin = [b for n, b in trin.items() if 'unittest' in b and '(blokerer)' in n]
        self.assertEqual(len(test_trin), 2, list(trin))
        for b in test_trin:
            self.assertNotIn('continue-on-error', b)
            self.assertNotRegex(b, r'\n\s+if:')
        self.assertIn("-p 'test_[!d]*.py'", test_trin[0])
        for klasse in ('CsvFormat', 'Ladere', 'FeedOgKort'):
            self.assertIn('tests.test_data.' + klasse, test_trin[1])
        # README-trinnet maa ikke blokere (en markoerfejl maa ikke stoppe ugens data), men skal findes.
        readme_trin = [b for b in trin.values() if 'tests.test_data.Readme' in b]
        self.assertEqual(len(readme_trin), 1)
        self.assertIn('continue-on-error: true', readme_trin[0])
        # Moensteret i foerste trin skal fange hver testfil undtagen test_data.py (en ny tests/test_dawa.py
        # ville ellers aldrig koere; review 14-10-2026).
        import fnmatch
        filer = sorted(f for f in os.listdir(os.path.join(ROD, 'tests')) if f.startswith('test_') and f.endswith('.py'))
        self.assertEqual([f for f in filer if (f == 'test_data.py') == fnmatch.fnmatch(f, 'test_[!d]*.py')], [])
        i_test = t.find('unittest discover -s tests')
        i_data = t.find('python3 refresh_data.py')
        i_rebuild = t.find('python3 rebuild.py')
        i_datatest = t.find('tests.test_data')
        i_commit = t.find('git commit')
        self.assertTrue(0 <= i_test < i_data, 'selvtest foer refresh_data.py')
        self.assertTrue(0 <= i_rebuild < i_datatest < i_commit, 'data-test efter rebuild og foer commit')
        liste = t[t.find('for f in retailkort_data.json'):i_commit]
        for f in ('README.md', 'retailkort_data.json', 'kort_soeg.html', 'kaede_adresser.xlsx',
                  'superladere_dk.csv', 'tankstationer_dk.csv', 'dagligvarer_dk.csv', 'udvalgsvarer_dk.csv',
                  'pladskraevende_dk.csv', 'fastfood_kaeder_dk.csv'):
            self.assertIn(f, liste)


if __name__ == '__main__':
    unittest.main()
