import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # repo-roden paa sys.path og nettet spaerret (tests/hjaelp.py)

import http.client
import io
import json
import unittest
import urllib.error
from unittest import mock

import retail_sources as RS
import sources as S

# Selvtest af sources.clever() og sources.ok_chargers(). Hver test genskaber en fejl, der er sket
# eller fanget i en review, med al I/O stubbet paa laveste niveau: sources._raw (Clever),
# sources._post (OK's API) og retail_sources._q8truck_ladesteder (Q8Truck's roamingkort). Den
# sidste OK-test stubber kun urllib.request.urlopen og beviser dermed, at stubbenes form passer
# til de aegte funktioner. Svarenes form foelger svar gemt 13-10-2026 (OK og Q8Truck).

OK_VAERT = 'https://geo-emobility.okcloud.dk'
Q8TRUCK_VAERT = 'https://www.q8truck.com'


# ================================================================ Clever
def _clever_feed():
    """Et lille, gyldigt Clever-feed i den form clever() laeser (id -> lokation med evses og
    connectors): to udtag paa 300 kW og et AC-udtag, som ikke taeller med."""
    def evse(nr, kw, stik):
        return {'evseId': f'DK*CLE*E15105{nr}', 'connectors': {'1': {'maxPowerKw': kw, 'plugType': stik}}}
    return {'loc-1': {'name': 'Lynladestation Test', 'state': 'Active', 'isRoamingPartner': False,
                      'address': {'countryCode': 'DK', 'address': 'Testvej 1', 'postalCode': '8000',
                                  'city': 'Aarhus C'},
                      'coordinates': {'lat': 56.15, 'lng': 10.2},
                      'evses': {'1': evse(1, 300, 'Combo'), '2': evse(2, 300, 'Combo'),
                                '3': evse(3, 22, 'Type2')}}}


GYLDIG = json.dumps(_clever_feed()).encode()
AFKORTET = GYLDIG[:len(GYLDIG) // 2]                                   # det, der naaede frem
OEDELAGT = GYLDIG[:len(GYLDIG) // 3] + GYLDIG[len(GYLDIG) // 3 + 25:]  # et stykke midt i mangler
FORVENTET = [('Lynladestation Test', 300, 2)]                          # (navn, kW, antal) af GYLDIG


def _clever_kort(ud):
    return [(r['name'], r['kw'], r['count']) for r in ud]


class TestClever(unittest.TestCase):
    def setUp(self):
        p = mock.patch('time.sleep')       # clever() importerer time lokalt; pauserne maa ikke koste tid
        self.sleep = p.start()
        self.addCleanup(p.stop)

    def test_afkortet_download_proeves_igen(self):
        """14-10-2026: et 9,3 MB svar kom 322 bytes for kort (http.client.IncompleteRead, som ikke er
        en ValueError). clever() skal vente, proeve igen med en ny url og bruge det hele svar."""
        with mock.patch.object(S, '_raw', side_effect=[http.client.IncompleteRead(AFKORTET, 322),
                                                       GYLDIG]) as raw:
            ud = S.clever()
        self.assertEqual(_clever_kort(ud), FORVENTET)
        self.assertEqual(raw.call_count, 2)
        url1, url2 = (c[0][0] for c in raw.call_args_list)
        self.assertNotEqual(url1, url2)       # cache-buster: CDN'et maa ikke servere samme kopi igen
        self.assertTrue(self.sleep.called)    # og en kort pause foer det nye forsoeg

    def test_oedelagt_json_proeves_igen(self):
        """01-10 og 05-10-2026: CDN'et serverede en oedelagt kopi (et stykke midt i manglede, json
        fejlede ved tegn ~8.382.770), og Clever blev ikke afstemt den uge."""
        self.assertRaises(ValueError, json.loads, OEDELAGT)   # forudsaetning: kopien ER ugyldig
        with mock.patch.object(S, '_raw', side_effect=[OEDELAGT, GYLDIG]) as raw:
            ud = S.clever()
        self.assertEqual(_clever_kort(ud), FORVENTET)
        self.assertEqual(raw.call_count, 2)

    def test_tre_forsoeg_i_alt(self):
        """Op til tre forsoeg (01-10, 05-10 og 14-10-2026): et afkortet og et oedelagt svar i traek
        maa ikke koste ugens afstemning, naar det tredje svar er helt."""
        with mock.patch.object(S, '_raw', side_effect=[http.client.IncompleteRead(AFKORTET, 322),
                                                       OEDELAGT, GYLDIG]) as raw:
            ud = S.clever()
        self.assertEqual(_clever_kort(ud), FORVENTET)
        self.assertEqual(raw.call_count, 3)

    def test_vedvarende_fejl_rejser_i_stedet_for_en_halv_liste(self):
        """Fejler alle tre forsoeg, skal clever() rejse (refresh_retail: HENTER FEJLEDE) - aldrig
        returnere en tom eller halv liste (jf. 01-10, 05-10 og 14-10-2026)."""
        for navn, svar, fejltype in (
                ('afkortet', http.client.IncompleteRead(AFKORTET, 322), http.client.IncompleteRead),
                ('oedelagt', OEDELAGT, ValueError)):
            with self.subTest(navn):
                with mock.patch.object(S, '_raw', side_effect=[svar] * 3) as raw:
                    with self.assertRaises(fejltype):
                        S.clever()
                self.assertEqual(raw.call_count, 3)


# ================================================================ OK (ladere)
def _okl(lid, navn, lat, lon, spots, roaming, power=300):
    """Én OK-lokation i testens verden. spots: [(evseId, connectorTypes)] som clusters/search giver
    dem; roaming: {evseId: kW} for lokationens EVSE'er i Q8Truck's roamingkort (et spot, der ikke
    staar her, findes ikke i kortet)."""
    return {'id': lid, 'navn': navn, 'lat': round(lat, 6), 'lon': round(lon, 6), 'power': power,
            'spots': list(spots), 'roaming': dict(roaming)}


def _ccs(ids):
    return [(e, ['Ccs']) for e in ids]


I_ALT = 80   # lokationer pr. scenarie (ok_chargers kraever 60-160); 8 clusters-fejl er saa graensen


def _fyld(n):
    """n almindelige OK-lokationer med 2 beviste CCS-udtag hver, i et gitter 0,02 grader fra
    hinanden (clusters/search-boksene overlapper ikke)."""
    ud = []
    for i in range(n):
        ids = [f'DK*OKO*EF{i:02d}*AA1', f'DK*OKO*EF{i:02d}*AA2']
        ud.append(_okl(f'fyld-{i}', f'OK Fyldvej {i}', 55.0 + 0.02 * (i // 40), 9.0 + 0.02 * (i % 40),
                       _ccs(ids), {e: 300.0 for e in ids}))
    return ud


def _scenarie(*saerlige):
    return list(saerlige) + _fyld(I_ALT - len(saerlige))


def _bevist():
    """4 CCS-spots, alle i roamingkortet med >= 250 kW, plus et AC- og et CHAdeMO-spot uden for kortet."""
    ccs = ['DK*OKO*EBV1*AA1', 'DK*OKO*EBV1*AA2', 'DK*OKO*EBV2*AA1', 'DK*OKO*EBV2*AA2']
    return _okl('bevist', 'OK Bevistvej', 56.10, 10.0,
                _ccs(ccs) + [('DK*OKO*EBV3*AC1', ['Type2']), ('DK*OKO*EBV3*CH1', ['Chademo'])],
                dict(zip(ccs, (300.0, 300.0, 360.0, 400.0))))


def _graense():
    """2 CCS-spots paa praecis 250 kW (= floor)."""
    ccs = ['DK*OKO*EGR1*AA1', 'DK*OKO*EGR1*AA2']
    return _okl('graense', 'OK Graensevej', 56.12, 10.0, _ccs(ccs), {e: 250.0 for e in ccs})


def _galten():
    """OK Galten: 8 CCS-spots, men kun de 4 gamle er bevist >= 250 kW; de 4 nye staar med 150 kW."""
    gamle = ['DK*OKO*EGA1*AA1', 'DK*OKO*EGA1*AA2', 'DK*OKO*EGA1*AA3', 'DK*OKO*EGA1*AA4']
    nye = ['DK*OKO*EGA2*BB1', 'DK*OKO*EGA2*BB2', 'DK*OKO*EGA2*BB3', 'DK*OKO*EGA2*BB4']
    roaming = {e: 300.0 for e in gamle}
    roaming.update({e: 150.0 for e in nye})
    return _okl('galten', 'OK Galten', 56.14, 10.0, _ccs(gamle + nye), roaming)


def _lyngby():
    """OK Kongens Lyngby Syd: 6 CCS-spots; de 2 nye findes ikke i roamingkortet (ukendt effekt)."""
    gamle = ['DK*OKO*EKL1*AA1', 'DK*OKO*EKL1*AA2', 'DK*OKO*EKL1*AA3', 'DK*OKO*EKL1*AA4']
    nye = ['DK*OKO*EKL2*BB1', 'DK*OKO*EKL2*BB2']
    return _okl('lyngby', 'OK Kongens Lyngby Syd', 56.16, 10.0, _ccs(gamle + nye),
                {e: 300.0 for e in gamle})


def _kun_ac():
    """Ingen CCS-spots (kun AC og CHAdeMO): intet at bevise."""
    return _okl('kun-ac', 'OK Kun AC', 56.18, 10.0,
                [('DK*OKO*EAC1*AA1', ['Type2']), ('DK*OKO*EAC1*AA2', ['Chademo'])],
                {'DK*OKO*EAC1*AA2': 50.0})


def _uden_ccs(n):
    """n OK-lokationer, som clusters/search FINDER, men kun med et AC- og et CHAdeMO-spot (som OK
    Kun AC) og uden EVSE'er i roamingkortet; 0,01 grader fra hinanden."""
    return [_okl(f'kun-ac-{k}', f'OK Kun AC {k}', 56.60, 10.0 + 0.01 * k,
                 [(f'DK*OKO*EAC{k}*AA1', ['Type2']), (f'DK*OKO*EAC{k}*AA2', ['Chademo'])], {})
            for k in range(n)]


def _stiktyper(lokationer, om):
    """Lokationerne med hvert spots connectorTypes omdoebt: om(type) -> den nye type."""
    return [dict(l, spots=[(e, [om(t) for t in typer]) for e, typer in l['spots']]) for l in lokationer]


def _advarsler(fejlud):
    """Linjerne med 'ANTAL IKKE TJEKKET' i det, ok_chargers skrev paa stderr."""
    return [l for l in fejlud.splitlines() if 'ANTAL IKKE TJEKKET' in l]


class _OkApi:
    """OK's geo-emobility-API, som sources._post ser den. locations/nearby giver alle lokationer
    med 'power'; clusters/search giver lokationerne i boksen med deres spots. Ligger flere i
    boksen, samles de i en klynge uden spots (klyngens egen form kendes ikke; koden ser kun efter
    locationId under 'locations'). fejler: locationId'er, hvor clusters/search fejler. skjult:
    locationId'er, som clusters/search svarer paa, men aldrig lister (i ingen af boksene)."""

    def __init__(self, lokationer, fejler=(), skjult=()):
        self.lokationer, self.fejler, self.skjult = lokationer, set(fejler), set(skjult)

    def svar(self, url, body):
        if url == S.OK_NEARBY_URL:
            return {'locations': [{'locationId': l['id'], 'source': 'OK', 'operatorCode': 'OKO',
                                   'latitude': l['lat'], 'longitude': l['lon'], 'name': l['navn'],
                                   'address': 'Testvej 1', 'chargingSpeed': 'Super', 'power': l['power']}
                                  for l in self.lokationer], 'nextDistanceM': 300100}
        if url == S.OK_CLUSTERS_URL:
            i_boks = [l for l in self.lokationer if body['swLat'] <= l['lat'] <= body['neLat']
                      and body['swLng'] <= l['lon'] <= body['neLng']]
            if any(l['id'] in self.fejler for l in i_boks):
                raise urllib.error.URLError('timed out')
            if len(i_boks) > 1:
                return {'clusters': [{'count': len(i_boks)}], 'locations': [], 'locationMarkers': []}
            return {'clusters': [], 'locationMarkers': [], 'locations': [
                {'source': 'OK', 'locationId': l['id'], 'latitude': l['lat'], 'longitude': l['lon'],
                 'operatorId': 'DK*OKO', 'name': l['navn'],
                 'spots': [{'evseId': e, 'connectorTypes': t} for e, t in l['spots']]}
                for l in i_boks if l['id'] not in self.skjult]}
        raise AssertionError('uventet url: ' + url)

    def post(self, url, body, timeout=90):
        """Erstatter sources._post."""
        return self.svar(url, body)


def _roamingkort(lokationer):
    """Svaret fra retail_sources._q8truck_ladesteder (se dens docstring): [{'navn','operatoer','lat',
    'lon','adresse','evser': [(id, stik, kw, status)]}]. Kortet har ogsaa andre operatoerers EVSE'er."""
    ud = [{'navn': 'Q8 Testvej', 'operatoer': 'DKQ8E', 'lat': 55.7, 'lon': 12.5, 'adresse': {},
           'evser': [('DK*Q8E*E78005', 'Ccs', 300.0, 'Available')]}]
    for l in lokationer:
        if l['roaming']:
            ud.append({'navn': l['navn'], 'operatoer': 'DKOKO', 'lat': l['lat'], 'lon': l['lon'],
                       'adresse': {}, 'evser': [(e, 'Ccs', kw, 'Available') for e, kw in l['roaming'].items()]})
    return ud


class _Svar:
    """Et svar fra urllib.request.urlopen: context manager med read() og headers."""

    def __init__(self, data):
        self.data, self.headers = data, {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.data


def _q8truck_svar(lokationer):
    """Q8Truck's /api/poi/locations med hasCharging (form som gemt 13-10-2026): OK's EVSE'er pr.
    lokation plus andre operatoerers, fyldt op til det antal, _q8truck_ladesteder kraever."""
    def evse(eid, kw):
        return {'id': eid, 'status': 'Available', 'chargingConnectorType': {'plugType': 'Ccs', 'maxPower': kw}}
    res = [{'name': l['navn'], 'address': {'country': 'DK'},
            'coordinates': {'latitude': l['lat'], 'longitude': l['lon']},
            'chargingLos': {'operator': 'DKOKO', 'chargingDevices': [
                {'evses': [evse(e, kw) for e, kw in l['roaming'].items()]}]}}
           for l in lokationer if l['roaming']]
    while len(res) < RS.Q8TRUCK_LADE_SPAEND[0]:
        res.append({'name': f'Anden operatoer {len(res)}', 'address': {'country': 'DK'},
                    'coordinates': {'latitude': 55.6, 'longitude': 12.0},
                    'chargingLos': {'operator': 'DKQ8E', 'chargingDevices': [
                        {'evses': [evse(f'DK*Q8E*E{len(res):05d}', 300)]}]}})
    return {'results': res}


class TestOkChargers(unittest.TestCase):
    def setUp(self):
        self.sleep = self._patch(mock.patch('time.sleep'))   # ok_chargers importerer time lokalt
        # robots.txt-cachen: OK's vaert uden regler (= tilladt), saa robots-tjekket koerer for alvor
        # uden net. Tom roamingkort-cache, saa intet svar fra en tidligere test genbruges.
        self._patch(mock.patch.dict(RS._ROBOTS, {OK_VAERT: ''}, clear=True))
        self._patch(mock.patch.dict(RS._Q8TRUCK_LADE_CACHE, clear=True))
        self.stderr = self._patch(mock.patch('sys.stderr', new_callable=io.StringIO))

    def _patch(self, p):
        v = p.start()
        self.addCleanup(p.stop)
        return v

    def _koer(self, lokationer, fejler=(), kort_svar=None, skjult=()):
        """ok_chargers() mod den falske OK-API (fejler, skjult: se _OkApi). kort_svar: roamingkortets
        svar pr. kald (en undtagelse i listen = det kald fejler). -> ({navn: raekke}, roamingkort-mock)"""
        api = _OkApi(lokationer, fejler, skjult)
        kort = mock.Mock(side_effect=kort_svar or [_roamingkort(lokationer)])
        with mock.patch.object(S, '_post', side_effect=api.post), \
                mock.patch.object(RS, '_q8truck_ladesteder', kort):
            ud = S.ok_chargers()
        return {r['name']: r for r in ud}, kort

    # ---- antal udtag: kun bevist (review 13-10-2026)
    def test_antal_kun_naar_alle_ccs_udtag_er_bevist(self):
        """Review 13-10-2026: count talte alle CCS-spots uanset effekt. Nu er antallet kun med, naar
        HVERT CCS-spot staar i OK's egne EVSE'er i roamingkortet med >= floor kW (praecis 250 kW
        taeller); AC- og CHAdeMO-spots taeller ikke med."""
        ud, _ = self._koer(_scenarie(_bevist(), _graense()))
        self.assertEqual(len(ud), I_ALT)
        self.assertEqual(ud['OK Bevistvej']['count'], 4)
        self.assertEqual(ud['OK Graensevej']['count'], 2)
        self.assertEqual(ud['OK Fyldvej 0']['count'], 2)

    def test_intet_antal_naar_et_udtag_mangler_eller_er_for_svagt(self):
        """Review 13-10-2026: OK Galten (4 -> 8) og OK Kongens Lyngby Syd (4 -> 6) fik et gaettet antal.
        Et CCS-spot under floor eller uden for roamingkortet (eller ingen CCS-spots) giver count '',
        saa refresh_retail hverken tilfoejer eller sammenligner - men lokationen og dens kW er med."""
        ud, _ = self._koer(_scenarie(_galten(), _lyngby(), _kun_ac()))
        self.assertEqual(len(ud), I_ALT)
        for navn in ('OK Galten', 'OK Kongens Lyngby Syd', 'OK Kun AC'):
            with self.subTest(navn):
                self.assertEqual(ud[navn]['count'], '')
                self.assertEqual(ud[navn]['kw'], 300)

    def test_naboer_i_samme_boks_udskilles_med_mindre_boks(self):
        """OK Aarslev: bil- og lastbilanlaegget (Logistikparken E-truck, paa kortet fra 01-10-2026)
        staar 26 m fra hinanden. I den foerste boks samler clusters/search dem i en klynge uden spots;
        _ok_ccs_spots skal proeve en mindre boks, ellers mister begge deres antal."""
        bil = ['DK*OKO*EAA1*AA1', 'DK*OKO*EAA1*AA2']
        truck = ['DK*OKO*EAA2*TT1', 'DK*OKO*EAA2*TT2', 'DK*OKO*EAA2*TT3']
        ud, _ = self._koer(_scenarie(
            _okl('aarslev-bil', 'OK Aarslev', 56.30, 10.0, _ccs(bil), {e: 300.0 for e in bil}),
            _okl('aarslev-truck', 'OK Aarslev, Logistikparken E-truck', 56.300234, 10.0,  # 26 m nord
                 _ccs(truck), {e: 400.0 for e in truck}, power=400)))
        self.assertEqual(ud['OK Aarslev']['count'], 2)
        self.assertEqual(ud['OK Aarslev, Logistikparken E-truck']['count'], 3)

    # ---- roamingkortet (review 14-10-2026)
    def test_roamingkort_nede_giver_tomt_antal_og_advarsel(self):
        """Review 14-10-2026: svarede Q8Truck's roamingkort ikke, forsvandt antal-tjekket stille. Efter
        to forsoeg skal alle antal vaere '' og 'ANTAL IKKE TJEKKET' staa paa stderr med grunden, mens
        lokationerne (lukninger, effekt) stadig kommer med."""
        ud, kort = self._koer(_scenarie(_bevist()), kort_svar=[
            RuntimeError('q8truck_ladesteder: 0 lokationer (forventet ~490, hoejst 1499)'),
            urllib.error.URLError('timed out')])
        self.assertEqual(kort.call_count, 2)
        self.assertEqual(len(ud), I_ALT)
        self.assertEqual({r['count'] for r in ud.values()}, {''})
        fejlud = self.stderr.getvalue()
        self.assertIn('ok_chargers', fejlud)
        self.assertIn('ANTAL IKKE TJEKKET', fejlud)
        self.assertIn('URLError', fejlud)

    def test_roamingkort_forbigaaende_udfald_proeves_igen(self):
        """Review 14-10-2026: ét forbigaaende udfald i roamingkortet maa ikke koste ugens antal-tjek;
        andet forsoeg (efter en pause) bruges, og der advares ikke."""
        lok = _scenarie(_bevist())
        ud, kort = self._koer(lok, kort_svar=[urllib.error.URLError('timed out'), _roamingkort(lok)])
        self.assertEqual(kort.call_count, 2)
        self.assertEqual(ud['OK Bevistvej']['count'], 4)
        self.assertNotIn('ANTAL IKKE TJEKKET', self.stderr.getvalue())
        self.assertTrue(self.sleep.called)

    def test_roamingkort_uden_oko_udtag_giver_tomt_antal_og_advarsel(self):
        """Fundet af testene 14-10-2026: svarede roamingkortet, men uden et eneste DK*OKO-udtag (OK
        ude af kortet eller et nyt praefiks), blev alle antal '' i stilhed. Nu staar 'ANTAL IKKE
        TJEKKET ... har ingen DK*OKO-udtag' paa stderr - ikke 'svarede ikke', for kortet svarede, ogsaa
        naar et udfald gik forud - mens lokationerne og deres kW stadig kommer med."""
        lok = _scenarie(_bevist())
        andre = _roamingkort([])                                   # kun Q8's eget EVSE
        nyt = [dict(l, evser=[(e.replace('DK*OKO*', 'DK*OKC*'), stik, kw, st)
                              for e, stik, kw, st in l['evser']]) for l in _roamingkort(lok)]
        for navn, kort_svar in (('OK ude af kortet', [andre]), ('nyt praefiks', [nyt]),
                                ('udfald, saa svar uden OK', [urllib.error.URLError('timed out'), andre])):
            with self.subTest(navn), mock.patch('sys.stderr', new_callable=io.StringIO) as fejl:
                ud, _ = self._koer(lok, kort_svar=kort_svar)
                self.assertEqual(len(ud), I_ALT)
                self.assertEqual({r['count'] for r in ud.values()}, {''})
                self.assertEqual(ud['OK Bevistvej']['kw'], 300)
                fejlud = fejl.getvalue()
                self.assertIn('ok_chargers', fejlud)
                self.assertIn('ANTAL IKKE TJEKKET', fejlud)
                self.assertIn('har ingen DK*OKO-udtag', fejlud)
                self.assertNotIn('svarede ikke', fejlud)

    def test_roamingkort_uden_oko_effekt_giver_tomt_antal_og_advarsel(self):
        """Fundet af testene 14-10-2026: havde roamingkortet OK's EVSE'er, men intet paa >= floor kW
        (maxPower mangler -> 0 kW, eller alle staar under 250 kW), blev alle antal '' i stilhed. Nu
        staar én linje 'ANTAL IKKE TJEKKET ... har ingen DK*OKO-udtag med >= 250 kW' paa stderr - ikke
        'svarede ikke', ogsaa naar et udfald gik forud - mens lokationerne og deres kW stadig kommer
        med. Modstykket: ét anlaeg, hvis udtag alle staar paa praecis 250 kW (OK Graensevej), er nok -
        ingen advarsel, og det beholder sit antal."""
        lok = _scenarie(_bevist(), _graense())

        def kort(kw):
            """Roamingkortet med alle OK's EVSE'er paa kw(lokation) kW."""
            return _roamingkort([dict(l, roaming={e: kw(l) for e in l['roaming']}) for l in lok])

        for navn, kort_svar, advares in (
                ('maxPower mangler (0 kW)', [kort(lambda l: 0)], True),
                ('alle under floor (249,9 kW)', [kort(lambda l: 249.9)], True),
                ('udfald, saa svar uden effekt', [urllib.error.URLError('timed out'), kort(lambda l: 0)], True),
                ('kun OK Graensevej paa praecis 250 kW',
                 [kort(lambda l: 250.0 if l['id'] == 'graense' else 0)], False)):
            with self.subTest(navn), mock.patch('sys.stderr', new_callable=io.StringIO) as fejl:
                ud, _ = self._koer(lok, kort_svar=kort_svar)
                self.assertEqual(len(ud), I_ALT)
                self.assertEqual(ud['OK Bevistvej']['kw'], 300)
                advarsler = _advarsler(fejl.getvalue())
                if advares:
                    self.assertEqual({r['count'] for r in ud.values()}, {''})
                    self.assertEqual(len(advarsler), 1, advarsler)
                    self.assertIn('ok_chargers', advarsler[0])
                    self.assertIn('har ingen DK*OKO-udtag med >= 250 kW', advarsler[0])
                    self.assertNotIn('svarede ikke', advarsler[0])
                else:
                    self.assertEqual(advarsler, [])
                    self.assertEqual(ud['OK Graensevej']['count'], 2)
                    self.assertEqual({r['count'] for n, r in ud.items() if n != 'OK Graensevej'}, {''})

    # ---- clusters/search-udfald (review 13-10-2026)
    def test_clusters_fejl_for_mange_lokationer_rejser(self):
        """Review 13-10-2026: fejler clusters/search for mere end hver tiende lokation (her 9 af 80),
        er antal-tjekket i stykker: RuntimeError, saa ugen staar som HENTER FEJLEDE i stedet for
        stille at miste tjekket."""
        lok = _scenarie()
        with self.assertRaisesRegex(RuntimeError, 'clusters/search'):
            self._koer(lok, fejler=[l['id'] for l in lok[:9]])

    def test_clusters_fejl_faa_lokationer_er_ok(self):
        """Modstykket (review 13-10-2026): 8 af 80 (lige paa graensen) er enkeltudfald - ingen fejl,
        men de 8 lokationer faar count '' og resten deres beviste antal."""
        lok = _scenarie()
        fejler = {l['id'] for l in lok[:8]}
        ud, _ = self._koer(lok, fejler=fejler)
        self.assertEqual(len(ud), I_ALT)
        for l in lok:
            self.assertEqual(ud[l['navn']]['count'], '' if l['id'] in fejler else 2, l['navn'])

    # ---- lokationer, clusters/search aldrig lister (fundet af testene 14-10-2026)
    def test_ikke_fundet_i_clusters_for_mange_lokationer_rejser(self):
        """Fundet af testene 14-10-2026: listede clusters/search ikke lokationen i nogen af de tre
        bokse, gav _ok_ccs_spots stille [] - 80 af 80 saadanne gav 80 tomme antal uden fejl. Nu er det
        et udfald som et fejlet kald og taeller i samme vagt: 9 af 80 (ogsaa 4 skjulte + 5 fejlede
        kald, og alle 80) giver RuntimeError, der naevner 'ikke fundet i clusters/search'."""
        lok = _scenarie()
        ids = [l['id'] for l in lok]
        for navn, skjult, fejler in (('9 skjulte', ids[:9], []), ('alle 80 skjulte', ids, []),
                                     ('4 skjulte + 5 fejlede kald', ids[:4], ids[4:9])):
            with self.subTest(navn):
                n = len(skjult) + len(fejler)
                with self.assertRaisesRegex(RuntimeError, rf'{n} af {I_ALT}\b.*ikke fundet i clusters/search'):
                    self._koer(lok, fejler=fejler, skjult=skjult)

    def test_ikke_fundet_i_clusters_faa_lokationer_er_ok(self):
        """Modstykket (fundet af testene 14-10-2026): 8 af 80 lokationer, som clusters/search aldrig
        lister, er enkeltudfald paa graensen - ingen fejl (hver taeller én gang, selv om alle tre bokse
        blev proevet), de 8 faar count '' og resten deres beviste antal."""
        lok = _scenarie()
        skjult = {l['id'] for l in lok[:8]}
        ud, _ = self._koer(lok, skjult=skjult)
        self.assertEqual(len(ud), I_ALT)
        for l in lok:
            self.assertEqual(ud[l['navn']]['count'], '' if l['id'] in skjult else 2, l['navn'])

    def test_fundet_uden_ccs_spots_er_ikke_et_udfald(self):
        """Fundet af testene 14-10-2026: en lokation, clusters/search FINDER, men kun med AC- og
        CHAdeMO-spots (som OK Kun AC), er ikke et udfald - den har blot intet CCS-antal at bevise.
        9 af 80 saadanne (over graensen, hvis de talte) giver ingen fejl, men count '' og deres kW."""
        kun_ac = [_okl(f'kun-ac-{k}', f'OK Kun AC {k}', 56.60, 10.0 + 0.01 * k,
                       [(f'DK*OKO*EAC{k}*AA1', ['Type2']), (f'DK*OKO*EAC{k}*AA2', ['Chademo'])], {})
                  for k in range(9)]
        ud, _ = self._koer(_scenarie(*kun_ac))
        self.assertEqual(len(ud), I_ALT)
        for l in kun_ac:
            self.assertEqual((ud[l['navn']]['count'], ud[l['navn']]['kw']), ('', 300), l['navn'])
        self.assertEqual(ud['OK Fyldvej 0']['count'], 2)

    def test_naboer_udskilt_i_mindre_boks_er_ikke_udfald(self):
        """Fundet af testene 14-10-2026: kun en lokation, der mangler i ALLE tre bokse, er et udfald.
        Naboer, der foerst udskilles i anden boks (26 m, som OK Aarslev) eller tredje (10 m), er
        fundet: 20 af 80 saadanne maa ikke vaelte vagten, og alle faar deres beviste antal."""
        naboer = []
        for k, afst in enumerate([0.000234] * 5 + [0.00009] * 5):
            for nr, lat in ((1, 56.50), (2, 56.50 + afst)):
                ids = [f'DK*OKO*EN{k}{nr}*AA1', f'DK*OKO*EN{k}{nr}*AA2']
                naboer.append(_okl(f'nabo-{k}-{nr}', f'OK Nabovej {k}-{nr}', lat, 10.0 + 0.01 * k,
                                   _ccs(ids), {e: 300.0 for e in ids}))
        ud, _ = self._koer(_scenarie(*naboer))
        self.assertEqual(len(ud), I_ALT)
        for l in naboer:
            self.assertEqual(ud[l['navn']]['count'], 2, l['navn'])

    # ---- stiktypen og lokationer uden CCS-spots (fundet af testene 14-10-2026)
    def test_ccs_stiktype_uanset_store_og_smaa_bogstaver(self):
        """Fundet af testene 14-10-2026: CCS-tjekket saa kun efter praecis 'Ccs'. Skrev OK's API
        stiktyperne med store (eller smaa) bogstaver, blev alle 80 antal '' i stilhed. Nu taeller 'CCS'
        og 'ccs' som 'Ccs' - AC- og CHAdeMO-spots ('TYPE2', 'CHADEMO') stadig ikke - og der advares
        ikke, for alle lokationer er fundet med CCS-spots."""
        for navn, om in (('STORE', str.upper), ('smaa', str.lower)):
            with self.subTest(navn), mock.patch('sys.stderr', new_callable=io.StringIO) as fejl:
                lok = _stiktyper(_scenarie(_bevist(), _graense()), om)
                ud, _ = self._koer(lok)
                self.assertEqual(len(ud), I_ALT)
                self.assertEqual(ud['OK Bevistvej']['count'], 4)        # AC- og CHAdeMO-spottet ikke med
                self.assertEqual(ud['OK Graensevej']['count'], 2)
                self.assertEqual({ud[l['navn']]['count'] for l in lok[2:]}, {2})
                self.assertEqual(_advarsler(fejl.getvalue()), [])

    def test_ok_ccs_spots_noterer_fundet_uden_ccs_for_sig(self):
        """Fundet af testene 14-10-2026: _ok_ccs_spots skriver en lokation, clusters/search FINDER uden
        et eneste CCS-spot, i den nye, valgfri liste uden_ccs - ikke i fejl, for det er intet udfald.
        En lokation med CCS-spots, en, clusters/search aldrig lister, og et fejlet kald kommer ikke i
        uden_ccs (de to sidste staar i fejl som foer), og uden uden_ccs virker kaldet som foer."""
        lok = [_bevist(), _kun_ac(),
               _okl('skjult', 'OK Skjult', 56.20, 10.0, _ccs(['DK*OKO*ESK1*AA1']), {}),
               _okl('fejler', 'OK Fejler', 56.22, 10.0, _ccs(['DK*OKO*EFE1*AA1']), {})]
        api = _OkApi(lok, fejler=['fejler'], skjult=['skjult'])
        fejl, uden_ccs = [], []
        with mock.patch.object(S, '_post', side_effect=api.post):
            spots = {l['id']: S._ok_ccs_spots(l['id'], l['lat'], l['lon'], fejl, uden_ccs) for l in lok}
            uden_liste = S._ok_ccs_spots('kun-ac', lok[1]['lat'], lok[1]['lon'], [])
        self.assertEqual(spots, {'bevist': [e for e, t in lok[0]['spots'] if t == ['Ccs']],
                                 'kun-ac': [], 'skjult': [], 'fejler': []})
        self.assertEqual(uden_ccs, ['kun-ac'])
        self.assertEqual([f.split(':')[0] for f in fejl], ['skjult', 'fejler'])
        self.assertEqual(uden_liste, [])

    def test_fundet_uden_ccs_spots_giver_een_advarsel(self):
        """Fundet af testene 14-10-2026: lokationer paa >= 250 kW, som clusters/search finder uden et
        eneste CCS-spot, fik count '' i stilhed - en stiktype omdoebt til fx 'Combo2' ville toemme alle
        80 antal uden et ord. Nu staar praecis én linje 'ANTAL IKKE TJEKKET ... uden CCS-spots' med
        antallet paa stderr (ikke én pr. lokation). Det er stadig intet udfald: ingen RuntimeError,
        heller ikke med 8 ikke-fundne lokationer (lige paa graensen) oveni, som ikke taeller med i
        advarslen; lokationerne faar count '' og resten deres beviste antal."""
        lok_9 = _scenarie(*_uden_ccs(9))
        for navn, lok, skjult, n in (
                ('9 kun AC', lok_9, set(), 9),
                ('9 kun AC + 8 ikke fundet', lok_9, {l['id'] for l in lok_9[9:17]}, 9),
                ('alle 80 omdoebt til Combo2',
                 _stiktyper(_scenarie(), lambda t: 'Combo2' if t == 'Ccs' else t), set(), I_ALT)):
            with self.subTest(navn), mock.patch('sys.stderr', new_callable=io.StringIO) as fejl:
                ud, _ = self._koer(lok, skjult=skjult)
                self.assertEqual(len(ud), I_ALT)
                for l in lok:
                    ikke_tjekket = l['id'] in skjult or all(t != ['Ccs'] for _, t in l['spots'])
                    self.assertEqual(ud[l['navn']]['count'], '' if ikke_tjekket else 2, l['navn'])
                advarsler = _advarsler(fejl.getvalue())
                self.assertEqual(len(advarsler), 1, advarsler)
                self.assertIn('ok_chargers', advarsler[0])
                self.assertIn('uden CCS-spots', advarsler[0])
                self.assertRegex(advarsler[0], rf'\b{n} lokation')

    # ---- robots.txt (13-10-2026)
    def _assert_intet_kald(self):
        """ok_chargers skal rejse paa robots.txt, foer OK, roamingkortet eller nettet kaldes."""
        api, kort, urlopen = _OkApi(_scenarie()), mock.Mock(return_value=[]), mock.Mock()
        with mock.patch.object(S, '_post', side_effect=api.post) as post, \
                mock.patch.object(RS, '_q8truck_ladesteder', kort), \
                mock.patch('urllib.request.urlopen', urlopen):
            with self.assertRaisesRegex(RuntimeError, 'robots.txt'):
                S.ok_chargers()
        self.assertEqual((post.call_count, kort.call_count, urlopen.call_count), (0, 0, 0))

    def test_robots_forbud_henter_intet(self):
        """13-10-2026 tjekkede flere hentere ikke selv robots.txt (bl.a. clever og ionity). Forbyder
        robots.txt OK's API, rejser ok_chargers uden et eneste kald."""
        with mock.patch.object(RS, '_robots_tilladt', return_value=False):
            self._assert_intet_kald()

    def test_robots_forbud_paa_clusters_stopper_foer_nearby(self):
        """Begge OK-stier tjekkes FOER det foerste kald (13-10-2026): forbyder robots.txt kun
        clusters/search, hentes heller ikke locations/nearby eller roamingkortet. Her med den aegte
        robots-parser og en robots.txt i cachen."""
        RS._ROBOTS[OK_VAERT] = 'User-agent: *\nDisallow: /api/v2/clusters/\n'
        self._assert_intet_kald()

    # ---- kontrakt: stubbenes form = de aegte funktioners
    def test_kontrakt_roamingkort_uden_maxpower(self):
        """Kontrakt (fundet af testene 14-10-2026): 0 kW i stubben i
        test_roamingkort_uden_oko_effekt_giver_tomt_antal_og_advarsel er det, den aegte parser giver et
        EVSE uden 'maxPower' i Q8Truck's svar. Her stubbes kun urllib.request.urlopen: mangler maxPower
        paa alle OK's EVSE'er, bliver alle antal '', og ok_chargers advarer med 'har ingen DK*OKO-udtag
        med >= 250 kW' - i stedet for at tie eller fejle paa en manglende vaerdi."""
        lok = _scenarie(_bevist())
        api = _OkApi(lok)
        svar = _q8truck_svar(lok)
        for x in svar['results']:
            if x['chargingLos']['operator'] == 'DKOKO':
                for dev in x['chargingLos']['chargingDevices']:
                    for e in dev['evses']:
                        del e['chargingConnectorType']['maxPower']
        q8 = json.dumps(svar).encode()
        RS._ROBOTS[Q8TRUCK_VAERT] = 'User-Agent: *\nAllow: /\nDisallow: /preview-visual-editor\n'

        def urlopen(req, timeout=None):
            if req.full_url == RS.Q8TRUCK_URL:
                return _Svar(q8)
            return _Svar(json.dumps(api.svar(req.full_url, json.loads(req.data))).encode())

        with mock.patch('urllib.request.urlopen', urlopen):
            ud = {r['name']: r for r in S.ok_chargers()}
        self.assertEqual(len(ud), I_ALT)
        self.assertEqual({r['count'] for r in ud.values()}, {''})
        self.assertEqual(ud['OK Bevistvej']['kw'], 300)
        advarsler = _advarsler(self.stderr.getvalue())
        self.assertEqual(len(advarsler), 1, advarsler)
        self.assertIn('har ingen DK*OKO-udtag med >= 250 kW', advarsler[0])

    def test_kontrakt_hele_vejen_ned_til_urlopen(self):
        """Review 13-10-2026 (bevist antal): testene ovenfor maa ikke kunne bestaa paa en stub-form,
        koden aldrig ser. Her stubbes kun urllib.request.urlopen; sources._post, robots-tjekket og
        retail_sources._q8truck_ladesteder (roamingkortets parser) koerer for alvor."""
        lok = _scenarie(_bevist(), _galten())
        api = _OkApi(lok)
        q8 = json.dumps(_q8truck_svar(lok)).encode()
        RS._ROBOTS[Q8TRUCK_VAERT] = 'User-Agent: *\nAllow: /\nDisallow: /preview-visual-editor\n'
        urls = []

        def urlopen(req, timeout=None):
            urls.append(req.full_url)
            if req.full_url == RS.Q8TRUCK_URL:
                return _Svar(q8)
            return _Svar(json.dumps(api.svar(req.full_url, json.loads(req.data))).encode())

        with mock.patch('urllib.request.urlopen', urlopen):
            ud = {r['name']: r for r in S.ok_chargers()}
        self.assertEqual(len(ud), I_ALT)
        self.assertEqual(ud['OK Bevistvej']['count'], 4)
        self.assertEqual(ud['OK Galten']['count'], '')
        self.assertEqual(urls.count(RS.Q8TRUCK_URL), 1)
        self.assertNotIn('ANTAL IKKE TJEKKET', self.stderr.getvalue())

    def test_ingen_bevist_lokation_giver_een_advarsel(self):
        """Fundet af testene 14-10-2026: et omdoebt felt ('evseID') eller et nyt id-format paa den ene side
        gav alle antal '' i stilhed - hverken 'uden CCS-spots' eller 'har ingen DK*OKO-udtag' slog til.
        Nu staar én linje 'ingen af N lokationer kunne bevises', naar roamingkortet har OK's udtag med
        effekt, men ikke en eneste lokation kan bevises. Med de rigtige id'er kommer linjen ikke."""
        lok = _scenarie(_bevist(), _graense())
        kort = _roamingkort([dict(l, roaming={e + '-NYT': 300.0 for e in l['roaming']}) for l in lok])
        with mock.patch('sys.stderr', new_callable=io.StringIO) as fejl:
            ud, _ = self._koer(lok, kort_svar=[kort])
        self.assertEqual({r['count'] for r in ud.values()}, {''})
        advarsler = _advarsler(fejl.getvalue())
        self.assertEqual(len(advarsler), 1, advarsler)
        self.assertIn(f'ingen af {I_ALT} lokationer kunne bevises', advarsler[0])
        with mock.patch('sys.stderr', new_callable=io.StringIO) as fejl:
            ud, _ = self._koer(lok)
        self.assertNotIn('kunne bevises', fejl.getvalue())
        self.assertEqual(ud['OK Bevistvej']['count'], 4)

if __name__ == '__main__':
    unittest.main()
