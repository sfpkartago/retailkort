#!/usr/bin/env python3
"""
refresh_retail.py — hold kaederne i KAEDER (detailhandel, tank og spisesteder) friske UDEN at omskrive haandverificerede data.

HVORFOR IKKE BARE ERSTATTE: foerste udgave hentede hver kaede og erstattede dens
raekker. En maalt koersel (16-09-2026) viste hvad det kostede:
    1.248 adresser omskrevet · 3 dubletter genindfoert · 12 navne forvaerret
Blandt dem netop den Netto Svinninge-dublet oprydningen havde fjernet, og
"Reberbanegade 3" -> "Reberbanegade 9" (Synoptik Amager Centret, rettet samme dag).

Aarsagen: dawa.normalize_rows er bygget til at normalisere RAA kildeadresser ÉN
gang. Koert igen paa data der allerede er normaliseret og haandrettet, flytter den
adressen til det naermeste DAWA-punkt og kasserer kildens husnummer. Og dens
'skipped' taeller kun om DAWA SVAREDE — ikke om adressen er rigtig. Den er altsaa
ingen verifikation; den er en omskrivning.

DERFOR: denne koersel TILFOEJER kun. Alt andet rapporteres.
  * butik hos kilden som vi ikke har  -> TILFOEJES (den er ny, saa der er intet
    haandarbejde at oedelaegge; adressen normaliseres som ved foerste hentning)
  * butik vi har som kilden ikke har  -> RAPPORTERES som mulig lukning, slettes ikke
  * adresse eller navn der afviger    -> RAPPORTERES, omskrives ikke
Fjernelser og rettelser vurderes i haanden. Det er samme princip som reconcile.py:
koerslen 08-09-2026 viste at 12 af 26 kandidater var falske.

Koer:  python3 refresh_retail.py [--apply]
Uden --apply skrives intet.
"""
import collections, csv, math, os, sys
import retail_sources as RS
import sources as S
import dawa
from dawa import normalize_rows, reverse_full, DawaNede

OUT = os.path.dirname(os.path.abspath(__file__))
NAER_M = 150             # samme butik, hvis den ligger inden for dette af en kildepost
MAX_NYE_PR_MAERKE = 0.10 # en kaede maa ikke vokse over 10 % paa én koersel
MIN_NYE_FRIT = 1         # ... men ét nyt anlaeg ad gangen er altid tilladt (se AFVIST i main)
# Ladelagets grænser, som tests/test_data.py ogsaa bruger: effekt pr. udtag og hoejst antal udtag.
LADE_KW = {'bil': (250, 600), 'lastbil': (250, 1200)}
LADE_MAX_ANTAL = 100
MAERKESKIFT_M = 150      # en 'ny' butik saa taet paa ejerens andet maerke er et maerkeskift
                         # (var 50: Kvickly -> SuperBrugsen Hjørring 10-2026 laa 107 m fra hinanden,
                         # fordi Coops nye pin er en geokodning af adressen; vagten om at det gamle
                         # maerke er vaek fra kilden holder fortsat to rigtige nabobutikker adskilt)
DK = (54.4, 57.9, 7.8, 15.3)

# Hvilke maerker HVER henter er ansvarlig for. Uden den kan koerslen ikke opdage at
# et helt maerke er forsvundet: 'pr'-dict'en bygges af kildesvaret, saa et maerke
# kilden ikke naevner, bliver aldrig kigget paa. Maalt i gennemgangen 17-09-2026:
# fjernes Brugsen-sektionen fra coop-svaret, skriver koerslen "0 mulige lukninger",
# exit 0 — og 265 butikker er usynligt uden for overvaagning.
# Genskab med:  python3 -c "import refresh_retail as R; R.vis_ejerskab()"
EJER = {
    'coop': ['Brugsen', 'Coop 365discount', 'Kvickly', 'SuperBrugsen'],
    'netto': ['Netto'],
    'seven_eleven': ['7-Eleven'],
    'rema': ['REMA 1000'],
    'dagrofa': ['Let-Køb', 'MENY', 'Min Købmand', 'SPAR'],
    'lidl': ['Lidl'],
    'apoteker': ['Apotek', 'Apoteksudsalg'],
    'matas': ['Matas'],
    'loevbjerg': ['Løvbjerg'],
    'imerco': ['Imerco', 'Imerco Home'],
    'kopkande': ['Kop & Kande'],
    'sport24': ['Sport 24', 'Sport 24 Outlet'],
    'bogide': ['Bog & idé'],
    'synoptik': ['Synoptik'],
    'thiele': ['Thiele'],
    'powerdk': ['POWER'],
    'toejeksperten': ['Tøjeksperten'],
    'jysk': ['JYSK'],
    'ilva': ['ILVA'],
    'ikea': ['IKEA', 'IKEA bestillingssted'],
    'stark': ['STARK'],
    'xlbyg': ['XL-BYG'],
    'bygma': ['Bygma'],
    'jemogfix': ['jem & fix'],
    'davidsen': ['Davidsen'],
    'silvan': ['Silvan'],
    'bauhaus': ['BAUHAUS'],
    'plantorama': ['Plantorama'],
    'lagkagehuset': ['Lagkagehuset'],
    'thansen': ['thansen'],
    'normal': ['Normal'],
    'harald_nyborg': ['Harald Nyborg'],
    'foetex': ['føtex', 'føtex food'],
    'bilka': ['Bilka'],
    'profiloptik': ['Profil Optik'],
    'nytsyn': ['Nyt Syn'],
    'fluegger': ['Flügger'],
    'fribikeshop': ['Fri BikeShop'],
    'maxizoo': ['Maxi Zoo'],
    'skoringen': ['Skoringen'],
    'unox': ['Uno-X'],
    'circlek_ingo': ['Circle K', 'Ingo'],
    'oil': ['OIL!'],
    'shell_tank': ['Shell'],
    'q8_f24': ['Q8', 'F24'],
    'carlsjr': ["Carl's Jr."],
    'subway': ['Subway'],
    'halifax': ['Halifax'],
    'gasolinegrill': ['Gasoline Grill'],
    'burgerking': ['Burger King'],
    'espressohouse': ['Espresso House'],
    'sunset_boulevard': ['Sunset Boulevard'],
    'jagger': ['Jagger'],
    'dominos': ["Domino's Pizza"],
    'max_burgers': ['Max Burgers'],
    'fiveguys': ['Five Guys'],
    'starbucks': ['Starbucks'],
    'kfc': ['KFC'],
    'cocks_cows': ['Cocks & Cows'],
    # Ladere (etape 3c, fra 13-10-2026; foerste ugentlige koersel 19-10-2026): sources.py's hentere, i ladefilen (LADE).
    'clever': ['Clever'],
    'ionity': ['Ionity'],
    'ok_chargers': ['OK'],
    'eon': ['E.ON'],
    'circlek_ladere': ['Circle K'],
    # Etape 3c, resten (13-10-2026). norlys_lastbil leverer kun lastbilraekker og q8_ladere kun
    # bilraekker; noeglerne skiller bil og lastbil, saa den anden halvdel sammenlignes aldrig.
    'norlys_lastbil': ['Norlys'],
    'q8_ladere': ['Q8'],
    'spirii': ['Spirii'],
    'edf': ['EDF'],
    'stella': ['Stella'],
    'allego': ['Allego'],
    'eviny': ['Eviny'],
    'fastned': ['Fastned'],
    'powergo': ['PowerGo'],
    'ampgo': ['AmpGo'],
    'unox_lader': ['Uno-X'],
    'shell_recharge': ['Shell Recharge'],
}

# Butikker vi BEVIDST ikke vil have, selv om kilden lister dem. Uden denne kommer
# en haandslettet raekke tilbage naeste mandag — og med kildens adresse, ikke den
# rettede. Noeglen er (maerke, kildens gadetekst i lowercase) som KILDEFEJL, og
# hver post skal have en grund.
#
# De fleste udeladelser ligger i hentererne (thiele() frasorterer oejenlaser-
# klinikken, coop() Kvicklys vinbutik) eller fanges af DK-tjekket. Listen her er til
# enkeltbutikker, saa udeladelsen havner i KODEN og ikke kun i dataene.
UDELADT = {
    # ('Maerke', 'gade nr'): 'grunden, med belaeg',
    # Coop/Tjek lister faengselsbutikken; den er kun for indsatte. Coops fire andre
    # (Noerre Snede, Renbaek, Soender Omme, Noerre Alslev) var aldrig med, fordi
    # Coops API ikke gav dem en koordinat. Fjernet 30-09-2026.
    ('SuperBrugsen', 'søvej 27'): 'fængselsbutik (Søbysøgård Fængsel) - ikke åben for offentligheden',
    # OIL!'s folder: 'Kun for OIL! firmakort kunder'; industrigrund uden tankbygning
    # (BBR 321 kontor + lagre). Fjernet 01-10-2026, samme princip som faengselsbutikken.
    ('OIL!', 'jomfruløkken 9'): 'kun for OIL! firmakort-kunder - ikke en offentlig tankstation',
    # OK's lader paa Katrinebjergvej 58 er samme anlaeg som vores 'Stella Aarhus' (samme adresse,
    # 4 CCS, 34 m) - afgjort 08-09-2026 og tidligere vist som '= AFGJORT' i reconcile.py.
    ('OK', 'katrinebjergvej 58'): 'samme anlæg som "Stella Aarhus" (afgjort 08-09-2026)',
}

# Afgjorte LADER ÆNDRET-forskelle: (maerke, vores Navn, felt, KILDENS vaerdi) -> grund. Kildens
# vaerdi er med i noeglen, saa linjen kommer igen, hvis kilden aendrer tallet.
# (OK Galten 4 -> 8 og OK Kongens Lyngby Syd 4 -> 6 stod her til 13-10-2026; siden taeller ok_chargers kun
# udtag, hvis effekt er bevist i OK's egne EVSE'er i roamingkortet, saa de to melder ikke laengere noget.)
LADER_KENDT = {
    ('Clever', 'Lynladestation Brønshøj', 'kW', '350'):
        "ét af 8 udtag (DK*CLE*E151056*1) staar med 350 i Clevers feed, tvillingeudtaget paa samme "
        "lader med 300; Clevers egen tekst for anlaegget siger 'max-effekt paa 300 kW' pr. lader (live og "
        "Wayback 21-05-2026) - 350 er en rest fra juli - 13-10-2026",
    ('Spirii', 'FDM Jyllandsringen (DC)', 'kW', '300'):
        "FDM (ejeren) skriver 'DC-anlaeg paa 400 kW' med 2 CCS + 1 CHAdeMO (Kempower), men ikke hvad ét "
        "udtag faar alene; vores 280 (mobilsiden) og roamingkortets 300 er begge sekundaere - uafklaret, "
        "begge >= 250 kW - 13-10-2026",
}

# Raekker vi BEVIDST beholder, selv om kilden ikke har dem. De vises som 'KENDT' med
# grunden i stedet for 'MULIG LUKNING': en rapport, hvor de samme afgjorte poster staar
# hver uge, bliver ikke laest (reconcile.py meldte 10 nye ladeanlaeg i tre uger, uden at
# nogen saa det). Noeglen er (maerke, vores Navn). Hver post skal have en grund med belaeg.
KENDT_UDEN_KILDE = {
    ('Espresso House', 'Lalandia Søndervig Espresso House'):
        "kaedens API udelader den, men smiley 1225327 (CVR 40523219, kontrol 19-06-2025) og "
        "lalandia.dk Søndervig ('På Torvet finder I også Espresso House') viser den (01-10-2026)",
    ('Shell', 'SHELL KNUDSHOVED'):
        "ombygget fra ubemandet Express til bemandet Shell ca. 01-10-2026 (ny CVR-P 1032724430 "
        "TCB Retail, smiley 1599706); Shells finder har endnu ingen ny post - fjern posten, naar den kommer",
    # Ladere (13-10-2026). Kilderne er efterproevet af en efterforsker og en skeptiker.
    # 'Powered by E.ON Drive & Clever' (Ultra-Fast Charging Venture Scandinavia ApS, CVR 40107584; EVSE-praefiks
    # DK*UFC): Clever overtager joint venturens seks danske anlaeg og 48 lynladeudtag og skifter dem til Clever
    # omkring aarsskiftet (Clever 11-08-2026). Anlaeggene staar endnu hverken i Clevers eller E.ON's egen liste.
    # Fundet i Q8Truck's roamingkort og efterproevet mod OSM 13-10-2026. Fjern posterne, naar Clevers feed har dem.
    ('Clever', 'Haverslev UFC (Powered by E.ON Drive & Clever)'):
        "joint venture-anlaeg (DK*UFC), endnu ikke i Clevers feed; OSM way/1393692898 4 x CCS 300 kW (13-10-2026)",
    ('Clever', 'Kliplev UFC (Powered by E.ON Drive & Clever)'):
        "joint venture-anlaeg (DK*UFC), endnu ikke i Clevers feed; OSM way/1289732963 10 x CCS 300 kW (13-10-2026)",
    ('Clever', 'Halsskov UFC (Powered by E.ON Drive & Clever)'):
        "joint venture-anlaeg (DK*UFC), endnu ikke i Clevers feed; OSM way/1058323241 6 x CCS 270 kW (13-10-2026)",
    ('Clever', 'Farø UFC (Powered by E.ON Drive & Clever)'):
        "joint venture-anlaeg (DK*UFC), endnu ikke i Clevers feed; OSM/foto 07-2024 4 x CCS 300 kW, roaming nu "
        "6 x 400 kW (ny hardware?) - efterproev effekt og antal (13-10-2026)",
    ('Shell Recharge', 'SHELL KNUDSHOVED'):
        "ombygget til bemandet Shell ca. 01-10-2026 og ude af Shells finder; DCC's egne EVSE'er i Q8Truck's "
        "roamingkort: 4 x 300 kW (E00130401/02), DCC: '400 kW-lynladere' (BygTek 07-07-2026) - ret effekt/antal "
        "og pin, naar Shell lister stationen igen (13-10-2026)",
    ('Spirii', 'DB Kirke Hyllinge Public'):
        "roamingkortet har 4 x 150 kW (DK*SPI*EDBKRHYDC1/2), Electromaps 'CCS2 x 8, 300 kW' "
        "(01-06-2026); sandsynligvis 2 x 300 kW med delt effekt - uafklaret (13-10-2026)",
    ('Stella', 'Stella Tobaksvejen'):
        "mangler i roamingkortet; Electromaps 'Stella - Tobaksvejen' 8 x CCS (30-07-2026)",
    ('Stella', 'Stella Strandvejen'):
        "mangler i roamingkortet; Electromaps 'Stella - Skovriderkroen' 6 x CCS (29-07-2026)",
    ('Stella', 'Stella Torvestrædet'):
        "mangler i roamingkortet; Electromaps 'Stella - Torvestrædet' 6 x CCS (29-07-2026)",
    ('Stella', 'Stella Aarhus'):
        "roamingkortet har kun 4 x 225 kW Stella-udtag paa Katrinebjergvej 58, OK's kort en OK-lokation "
        "(280 kW) samme sted - uafklaret, se UDELADT for OK (13-10-2026)",
    ('Espresso House', 'Espresso House Lalandia Billund'):
        "Lalandia Billund har TO caféer, og kaedens API har kun den ene (Ellehammers Alle 3, "
        "246 m vaek): lalandia.dk nævner 'Espresso House på Lalandia Plaza' og 'Espresso House "
        "ved Adventure Tower', og smiley har to registreringer paa P 1010767160 (01-10-2026)",
}

# 'sport24' er taget ud 30-09-2026: sport24.dk's CloudFront svarer 403 "Request blocked"
# paa alt, ogsaa robots.txt - samme situation som thansen.dk, og en blokering
# omgaas ikke. De eksisterende Sport 24-raekker bliver staaende, men overvaages ikke
# ugentligt; retail_sources.sport24() er bevaret, hvis kaeden aabner igen.
KAEDER = [(n, getattr(RS, n)) for n in (
    'coop', 'netto', 'seven_eleven', 'rema', 'dagrofa', 'lidl', 'apoteker', 'matas',
    'loevbjerg', 'imerco', 'kopkande', 'bogide', 'synoptik', 'thiele',
    'powerdk', 'toejeksperten', 'jysk', 'ilva', 'ikea', 'stark', 'xlbyg', 'bygma',
    'jemogfix', 'davidsen', 'silvan', 'bauhaus', 'plantorama', 'thansen',
    # Etape 2 (30-09-2026): kaedernes egne lister, hver efterproevet af en skeptiker.
    'normal', 'harald_nyborg', 'foetex', 'bilka', 'profiloptik', 'nytsyn', 'fluegger',
    'fribikeshop', 'maxizoo', 'skoringen',
    # Etape 3 (01-10-2026): tankkaeder; shell_tank kun til rapport (se KUN_RAPPORT).
    'unox', 'circlek_ingo', 'oil', 'shell_tank', 'q8_f24',
    # Etape 3b (01-10-2026): spisesteder; starbucks, kfc og cocks_cows kun til rapport.
    'carlsjr', 'subway', 'halifax', 'gasolinegrill', 'burgerking', 'espressohouse',
    'sunset_boulevard', 'jagger', 'dominos', 'max_burgers', 'fiveguys',
    'starbucks', 'kfc', 'cocks_cows')]
KAEDER += [('lagkagehuset', S.lagkagehuset)]
# Laderne (etape 3c, fra 13-10-2026). Tesla erstattes fortsat af refresh_data.py.
KAEDER += [('clever', S.clever), ('ionity', S.ionity), ('ok_chargers', S.ok_chargers)]
# Etape 3c (13-10-2026): operatoerernes egne lister, efterproevet af skeptikere.
KAEDER += [('eon', RS.eon), ('circlek_ladere', RS.circlek_ladere)]
KAEDER += [(n, getattr(RS, n)) for n in (
    'norlys_lastbil', 'q8_ladere', 'spirii', 'edf', 'stella', 'allego', 'eviny', 'fastned',
    'powergo', 'ampgo', 'unox_lader', 'shell_recharge')]
LADE_KAEDER = {'clever', 'ionity', 'ok_chargers', 'eon', 'circlek_ladere',
               'norlys_lastbil', 'q8_ladere', 'spirii', 'edf', 'stella', 'allego', 'eviny',
               'fastned', 'powergo', 'ampgo', 'unox_lader', 'shell_recharge'}
# Hentere, der kun leverer den ENE halvdel (bil eller lastbil): for dem kan BIL/LASTBIL-vagten ikke
# se, om kilden 'stadig har den anden halvdel dér', saa den springes over. Norlys' lastbilstationer
# ligger ofte 74-106 m fra en Norlys-bilpark (Korsør, Aarup, Køge); uden undtagelsen blev en ny
# lastbilstation meldt som et skifte med raadet 'ret Lastbil i haanden' (review 14-10-2026).
EN_HALVDEL = {'norlys_lastbil': 'lastbil', 'q8_ladere': 'bil'}   # henter -> den halvdel, den leverer
# (henter, maerke, halvdel), som henteren med vilje IKKE leverer, selv om vi har raekker i den halvdel;
# uden en post her melder main() HALVDEL MANGLER. Hver post skal have en grund med dato.
HALVDEL_IKKE_I_KILDEN = {}
# Hentere, hvis NYE anlaeg kun kan komme med via en haandtabel i retail_sources (kilden har ikke det,
# der skal til): de tilfoejer ikke selv nye anlaeg, kun dem i tabellen. Bruges af readme_tal.py.
TABEL_HENTERE = {'unox_lader': 'nye anlaeg kraever en post i UNOX_LADER (finderen har ingen effekt)'}
FILER = ('dagligvarer_dk.csv', 'udvalgsvarer_dk.csv', 'pladskraevende_dk.csv', 'tankstationer_dk.csv',
         'fastfood_kaeder_dk.csv', 'superladere_dk.csv')
# Tankfilen har en 8. kolonne, Lastbil ('ja' = rent lastbilanlaeg, eget kortlag). Bil- og
# lastbilanlaeg af samme maerke matches HVER FOR SIG: Uno-X Truck Frederiksvaerk staar 4 m
# fra Uno-X-bilstationen, og uden adskillelse kunne den ene 'daekke' den anden (01-10-2026).
TANK = 'tankstationer_dk.csv'
LASTBIL = '|lastbil'
# Ladefilen har kW, stik og antal FOER koordinaterne (lat/lon i kolonne 8/9, Lastbil i 10), og
# flere maerker findes baade som tankstation og som lader (Circle K, OK, Uno-X, Q8). Ladernes
# noegler faar derfor et eget suffiks, saa tank- og laderaekker af samme maerke aldrig blandes.
LADE = 'superladere_dk.csv'
LADEKEY = '|lade'
KOL = {LADE: (8, 9), }      # (lat, lon) pr. fil; standard (5, 6)
# Kaeder hvis nye anlaeg kun RAPPORTERES: Shells egne pins var forkerte for 6 af de 24
# anlaeg, Shell tilfoejede i 2025-26, saa en automatisk tilfoejelse ville arve dem.
KUN_RAPPORT = {'shell_tank',
               # Spisesteder (01-10-2026): Starbucks' pins staar forkert for 3 af 17 (Fisketorvet
               # 3,4 km), og adresseteksten er ASCII og ofte forkert; KFC's kilde er en
               # kontaktformular uden aabningsstatus; Cocks & Cows' gitter er ikke vedligeholdt
               # og har ingen koordinater.
               'starbucks', 'kfc', 'cocks_cows',
               # Circle K's ladere: ingen kW pr. udtag i kilden (kw=0 stopper ogsaa tilfoejelse).
               'circlek_ladere',
               # Ladere (13-10-2026): Norlys' lastbilstationer er aflaest af videoer (et nyt
               # video-id stopper henteren); Spirii, EDF og Stella kommer fra et roamingkort, der
               # ikke er komplet og kapper effekten; Shell Recharge arver Shells pins (se ovenfor).
               'norlys_lastbil', 'spirii', 'edf', 'stella', 'shell_recharge',
               # PowerGo's 'Ladepunkter' kan taelle CHAdeMO med under CCS og skiller ikke 150 fra
               # 400 kW (Lillebaelt Syd: 21 for 14) - antallet er et loft, ikke et bevis (review 13-10-2026).
               'powergo'}


def _rk(fn, r):
    """Matchnoegle for vores egen raekke: maerket (+ LADEKEY i ladefilen), + LASTBIL for
    lastbilanlaeg i tank- og ladefilen."""
    if fn == LADE:
        return r[0] + LADEKEY + (LASTBIL if len(r) > 10 and r[10] == 'ja' else '')
    return r[0] + (LASTBIL if fn == TANK and len(r) > 7 and r[7] == 'ja' else '')


def _kk(x, lade=False):
    """Matchnoegle for en kildepost: maerket (+ LADEKEY for laderhentere), + LASTBIL naar
    henteren siger lastbil='ja'."""
    return ((x.get('brand') or '') + (LADEKEY if lade else '')
            + (LASTBIL if x.get('lastbil') == 'ja' else ''))


def _basis(k):
    """'Norlys|lade|lastbil' -> 'Norlys'."""
    return k.split(LADEKEY)[0].split(LASTBIL)[0]


def _ll(fn):
    return KOL.get(fn, (5, 6))


def hav(a, b, c, d):
    R = 6371000.0; r = math.pi / 180
    x = (c - a) * r; y = (d - b) * r
    return 2 * R * math.asin(math.sqrt(math.sin(x / 2) ** 2 +
                                       math.cos(a * r) * math.cos(c * r) * math.sin(y / 2) ** 2))


def _laes(fn):
    with open(os.path.join(OUT, fn), encoding='utf-8-sig') as f:
        r = list(csv.reader(f))
    return r[0], r[1:]


def _nk(s):
    import re as _re
    s = _re.sub(r'[^a-z0-9æøå ]', ' ', (s or '').lower())
    return ' '.join(s.split())


def _navn_ens(a, b):
    """Samme butik? Sammenlign uden versaler, tegn og kaedenavn."""
    import re as _re
    def k(s):
        s = _re.sub(r'[^a-z0-9æøå ]', ' ', (s or '').lower())
        return ' '.join(s.split())
    ka, kb = k(a), k(b)
    # KUN eksakt lighed. Delstreng-match parrede "THIELE Aalborg" med "THIELE Aalborg
    # Storcenter" — og dermed de to butikker OMVENDT, 5,7 km fra hinanden. Samme med
    # Bygma Esbjerg/Esbjerg N og jem & fix Esbjerg/Esbjerg V. En loes matcher rammer
    # naboen, ikke butikken.
    return bool(ka) and ka == kb


def _vores_koord(r, fn=None):
    """Vores EGEN raekke -> (lat, lon) eller None. float() paa en tom streng rejste
    ValueError midt i koerslen, saa alle fund fra de kaeder der allerede var koert
    igennem gik tabt, og den committede rapport blev et traceback."""
    la, lo = _ll(fn)
    try:
        return (float(r[la]), float(r[lo]))
    except (TypeError, ValueError, IndexError):
        return None


def _koord(x):
    try:
        la, lo = float(x['lat']), float(x['lon'])
    except (TypeError, ValueError, KeyError):
        return None
    return (la, lo) if DK[0] < la < DK[1] and DK[2] < lo < DK[3] else None


def main(apply=False):
    dawa.tag_dar_laas('refresh_retail.py')      # én DAR-tung koersel ad gangen (se dawa)
    filer = {fn: _laes(fn) for fn in FILER}
    hvor, egne = {}, collections.defaultdict(list)
    for fn, (_, body) in filer.items():
        for r in body:
            hvor[_rk(fn, r)] = fn
            egne[_rk(fn, r)].append(r)

    nye = collections.defaultdict(list)
    linjer, n_ny, n_luk, n_afvig, n_fejl = [], 0, 0, 0, 0
    fejlede = set()                       # hentere med mindst én fejl (n_fejl taeller linjerne)

    for navn, hent in KAEDER:
        stop_foer = len(RS.ROBOTS_STOP)
        try:
            raa = hent()
        except Exception as e:
            linjer.append(f'  {navn:16} HENTER FEJLEDE  {type(e).__name__}: {e}'[:250]); n_fejl += 1
            fejlede.add(navn); continue
        # Stoppede robots.txt (eller Crawl-delay-budgettet) et kald undervejs, kan svaret mangle sider -
        # ogsaa naar henteren selv slugte fejlen. Saa bruges det ikke; ellers blev de sider til falske
        # lukninger (review 14-10-2026).
        stop = RS.ROBOTS_STOP[stop_foer:]
        if stop:
            linjer.append(f'  {navn:16} ROBOTS-STOP     {len(stop)} kald stoppet (fx {stop[0][0]}: {stop[0][1]}) '
                          f'— henterens svar bruges ikke'[:250]); n_fejl += 1
            fejlede.add(navn); continue
        # Et TOMT svar er ikke "kaeden har lukket alle butikker" — det er en henter
        # der er holdt op med at virke (side lagt om, regex matcher ikke, WAF svarer
        # 200 med en tom shell). Uden dette skrev koerslen "(ingen aendringer)" og
        # exit 0, mens hele maerket stod uden for overvaagning.
        if not raa:
            linjer.append(f'  {navn:16} TOMT SVAR       kilden svarede med 0 poster — '
                          f'behandles som en fejl, ikke som 0 butikker'); n_fejl += 1
            fejlede.add(navn); continue
        ukoord = [x for x in raa if _koord(x) is None]
        raa = [x for x in raa if _koord(x)]
        # Fjern kildens EGNE dubletter ét sted for alle kaeder. toejeksperten.dk
        # lister "Toejeksperten Ballerup" to gange med identisk navn, gade OG
        # koordinat; saa faldt navnematchningen bort (navnet er ikke entydigt) og
        # naerhedsmatchningen parrede kun den foerste — den anden blev meldt som
        # NY BUTIK og skrevet ind som en byte-identisk dublet. Én hard error i
        # validate.py. En kildedublet er altid en kildedublet, saa den hoerer her.
        udeladt = [x for x in raa
                   if (x.get('brand'), ' '.join((x.get('street') or '').lower().split())) in UDELADT]
        if udeladt:
            raa = [x for x in raa if x not in udeladt]
            for x in udeladt:
                grund = UDELADT[(x.get('brand'), ' '.join((x.get('street') or '').lower().split()))]
                linjer.append(f'  {navn:16} UDELADT         {x.get("brand")}: '
                              f'{x.get("street","")[:30]} — {grund}')
        foer = len(raa)
        raa = RS._naer_uniq(raa)
        if len(raa) < foer:
            linjer.append(f'  {navn:16} KILDEDUBLET     {foer - len(raa)} post(er) fra kilden '
                          f'var dubletter (samme navn og koordinat) — udeladt')
        # Én linje pr. KAEDE, ikke pr. maerke: coop viste de samme 10 poster fire
        # gange, saa laeseren talte 40. Og den forsvandt helt, hvis kaedens maerker
        # alle blev afvist — for den laa inde i maerkeloekken.
        if ukoord:
            linjer.append(f'  {navn:16} INFO            {len(ukoord)} kildepost(er) uden '
                          f'brugbar dansk koordinat — ikke vurderet (kan blive til '
                          f'falske lukninger)')
        # En henter i EN_HALVDEL leverer kun sin egen halvdel, og BIL/LASTBIL-vagten springes over for den.
        # En post fra den anden halvdel er derfor en fejl i henteren, ikke et anlaeg (testene 14-10-2026).
        if navn in EN_HALVDEL:
            forkert = [x for x in raa if ('lastbil' if x.get('lastbil') == 'ja' else 'bil') != EN_HALVDEL[navn]]
            if forkert:
                linjer.append(f'  {navn:16} FORKERT HALVDEL {len(forkert)} post(er) er ikke {EN_HALVDEL[navn]} '
                              f'(fx {(forkert[0].get("name") or "")[:30]}) — udeladt; ret henteren')
                n_fejl += 1
                fejlede.add(navn)
                raa = [x for x in raa if x not in forkert]
        pr = collections.defaultdict(list)
        for x in raa:
            pr[_kk(x, navn in LADE_KAEDER)].append(x)
        # Maerker denne henter ER ansvarlig for, men som slet ikke optraeder i svaret.
        # 'pr' bygges af kildesvaret, saa uden dette blev de aldrig kigget paa: fjernes
        # Brugsen fra coop-svaret, meldte koerslen "0 mulige lukninger" og exit 0,
        # mens 265 butikker stod uden for overvaagning.
        lk = LADEKEY if navn in LADE_KAEDER else ''
        til_stede = {_basis(k) for k in pr}
        for maerke in EJER.get(navn, []):
            vi_har = len(egne.get(maerke + lk, [])) + len(egne.get(maerke + lk + LASTBIL, []))
            if maerke not in til_stede and vi_har:
                linjer.append(f'  {navn:16} MÆRKE MANGLER   {maerke}: kilden nævner det slet ikke, '
                              f'men vi har {vi_har} rækker — behandles som en fejl')
                n_fejl += 1
                fejlede.add(navn)
                continue
            # Samme fejl paa halvdel-niveau (fundet af testene 14-10-2026): giver en henter, der plejer at
            # levere baade bil- og lastbilanlaeg, pludselig kun den ene halvdel, blev den andens raekker
            # aldrig sammenlignet - og rapporten sagde intet (Uno-X har 81 lastbilanlaeg i tankfilen).
            for lb, h in (('', 'bil'), (LASTBIL, 'lastbil')):
                if navn in EN_HALVDEL and EN_HALVDEL[navn] != h:
                    continue
                n_vore = len(egne.get(maerke + lk + lb, []))
                if n_vore and maerke in til_stede and not pr.get(maerke + lk + lb) \
                        and (navn, maerke, h) not in HALVDEL_IKKE_I_KILDEN:
                    linjer.append(f'  {navn:16} HALVDEL MANGLER {maerke} ({h}): kilden har ingen {h}-poster, '
                                  f'men vi har {n_vore} rækker — behandles som en fejl')
                    n_fejl += 1
                    fejlede.add(navn)
        for maerke, xs in pr.items():
            # En kaedes FOERSTE lastbilanlaeg: maerket kendes fra tankfilen, men vi har
            # endnu ingen lastbilraekker for det.
            if maerke not in hvor and maerke.endswith(LASTBIL) and hvor.get(maerke[:-len(LASTBIL)]) in (TANK, LADE):
                hvor[maerke] = hvor[maerke[:-len(LASTBIL)]]
            if maerke not in hvor:
                linjer.append(f'  {navn:16} UKENDT MÆRKE    {maerke!r} findes ikke i nogen CSV — '
                              f'kategorien er en planlovsafgørelse, ikke en teknisk'); continue
            fn = hvor[maerke]
            la_i, lo_i = _ll(fn)
            vore = [r for r in egne[maerke] if _vores_koord(r, fn)]
            if len(vore) < len(egne[maerke]):
                linjer.append(f'  {navn:16} UBRUGELIG RÆKKE {maerke}: '
                              f'{len(egne[maerke]) - len(vore)} af vores egne rækker har ingen '
                              f'brugbar koordinat og kan ikke sammenlignes')
            # Match FOERST paa navn, saa paa naerhed. Naerhed alene duer ikke: har vi
            # flyttet en raekke mere end NAER_M for at rette den (16-09-2026 blev 10
            # Dagrofa- og Matas-koordinater flyttet 1-10 km), ser kildens gamle punkt
            # ud som en ny butik og vores rettede som en lukning. Med navnematchning
            # bliver det i stedet en KOORDINAT-AFVIGELSE, som er det den er.
            # Navnematch duer KUN naar navnet er entydigt paa begge sider. Alle
            # Matas-raekker hedder bare "Matas", saa eksakt match parrede tilfaeldige
            # butikker — "Soendergade 6, Frederikshavn" med "Raadhuscentret 37",
            # 255 km fra hinanden. Er navnet ikke entydigt, afgoer naerheden.
            _t_k = collections.Counter(_nk(x.get('name')) for x in xs)
            _t_v = collections.Counter(_nk(r[1]) for r in vore)
            entydig = {n for n in _t_k if _t_k[n] == 1 and _t_v.get(n) == 1}
            brugt_vore, brugt_kilde, afvig, parret = set(), set(), [], []
            for i, x in enumerate(xs):
                if _nk(x.get('name')) not in entydig:
                    continue
                for j, r in enumerate(vore):
                    if j in brugt_vore or not _navn_ens(x.get('name'), r[1]):
                        continue
                    d = hav(*_koord(x), float(r[la_i]), float(r[lo_i]))
                    brugt_vore.add(j); brugt_kilde.add(i); parret.append((x, r))
                    if d > NAER_M:
                        afvig.append((r, x, d))
                    break
            # NAERMESTE, ikke foerste. 'break ved foerste inden for 150 m' tog raekken
            # i CSV-raekkefoelge: for Matas matches alle 264 paa naerhed alene (ingen
            # entydige navne), og fire Matas-par ligger under 150 m fra hinanden
            # (Frederiksberg 7 m). Lukkede den ene af to nabobutikker, udpegede
            # rapporten den anden — foelger man den, sletter man den AABNE butik.
            par = sorted((hav(*_koord(x), float(r[la_i]), float(r[lo_i])), i, j)
                         for i, x in enumerate(xs) if i not in brugt_kilde
                         for j, r in enumerate(vore) if j not in brugt_vore)
            for d, i, j in par:
                if d >= NAER_M or i in brugt_kilde or j in brugt_vore:
                    continue
                brugt_vore.add(j); brugt_kilde.add(i); parret.append((xs[i], vore[j]))
            mangler = [x for i, x in enumerate(xs) if i not in brugt_kilde]
            lukket = [r for j, r in enumerate(vore) if j not in brugt_vore]
            # Ladere: kilden kender effekt og antal ladepunkter. Afviger de fra vores parrede
            # raekke (OK Galten: 4 -> 8 udtag 06-10-2026), meldes det; intet rettes automatisk.
            if fn == LADE:
                for x, r in parret:
                    kw, ant = str(x.get('kw') or ''), str(x.get('count') or '')
                    forskel = []
                    for t, v, k in (('kW', r[5], kw), ('ladepunkter', r[7], ant)):
                        if not k or v == k:
                            continue
                        grund = LADER_KENDT.get((_basis(maerke), r[1], t, k))
                        if grund:
                            linjer.append(f'  {navn:16} KENDT           {maerke}: {r[1][:30]} — {t} {v} -> {k}: {grund}'[:220])
                        else:
                            forskel.append(f'{t} {v} -> {k}')
                    if forskel:
                        linjer.append(f'  {navn:16} LADER ÆNDRET    {maerke}: {r[1][:30]} — kilden siger '
                                      + ', '.join(forskel) + '; RETTES IKKE automatisk')
            for r, x, d in afvig:
                linjer.append(f'  {navn:16} KOORD-AFVIGELSE {maerke}: {r[1][:26]} — vores '
                              f'{r[2][:30]} ligger {round(d)} m fra kildens {x.get("street","")[:26]}; '
                              f'RETTES IKKE automatisk')
            n_afvig += len(afvig)
            # Lukninger rapporteres FOER enhver 'continue'. Laa de efter, slugte
            # AFVIST- og DAWA-udfaldet dem, og slutlinjen paastod "0 mulige
            # lukninger" i netop den uge hvor kilden opfoerte sig underligt.
            kendt = [r for r in lukket if (_basis(maerke), r[1]) in KENDT_UDEN_KILDE]
            lukket = [r for r in lukket if (_basis(maerke), r[1]) not in KENDT_UDEN_KILDE]
            for r in kendt:
                linjer.append(f'  {navn:16} KENDT           {maerke}: {r[1][:30]} — '
                              f'{KENDT_UDEN_KILDE[(_basis(maerke), r[1])]}'[:200])
            for r in lukket:
                linjer.append(f'  {navn:16} MULIG LUKNING   {maerke}: {r[1][:30]} · {r[2][:40]} '
                              f'— kilden har den ikke; SLETTES IKKE automatisk')
            n_luk += len(lukket)
            # MAERKESKIFT: samme ejer, nyt maerke, samme sted. Q8 og F24 deler én liste med
            # faelles id'er og pins (ligesom Circle K/Ingo og Coops fire kaeder). Konverteres
            # en station, staar den under det nye maerke paa den gamle pin, og uden dette blev
            # den tilfoejet oven paa den gamle raekke: en haard kryds-maerke-dublet i validate.py
            # (fundet i review 02-10-2026). Det er kun et skifte, naar kilden IKKE laengere har
            # det gamle maerke paa stedet; staar begge der, er det to butikker (fx Kvickly og
            # 365discount i samme center), og den nye tilfoejes normalt. Den gamle raekke
            # meldes som MULIG LUKNING under sit eget maerke; ret maerket i haanden.
            soestre = [m for m in EJER.get(navn, []) if m != _basis(maerke)]
            if mangler and soestre:
                lb = LASTBIL if maerke.endswith(LASTBIL) else ''
                andre = [r for m in soestre for r in egne.get(m + lk + lb, []) if _vores_koord(r, fn)]
                kilde_andre = [x2 for m in soestre for x2 in pr.get(m + lk + lb, [])]
                skift = []
                for x in mangler:
                    naer = min(((hav(*_koord(x), float(r[la_i]), float(r[lo_i])), r) for r in andre),
                               key=lambda t: t[0], default=None)
                    if not naer or naer[0] >= MAERKESKIFT_M:
                        continue
                    if any(hav(*_koord(x2), float(naer[1][la_i]), float(naer[1][lo_i])) < MAERKESKIFT_M
                           for x2 in kilde_andre if x2.get('brand') == naer[1][0]):
                        continue                  # det gamle maerke staar der stadig: to butikker
                    skift.append(x)
                    linjer.append(f'  {navn:16} MÆRKESKIFT      {maerke}: {(x.get("name") or "")[:28]} — vores '
                                  f'{naer[1][0]}-række "{naer[1][1][:28]}" står {round(naer[0])} m væk og '
                                  f'er væk fra kilden; tilføjes IKKE - ret mærket i hånden')
                mangler = [x for x in mangler if x not in skift]
            # BIL/LASTBIL-SKIFT: bil- og lastbilanlaeg af samme maerke matches hver for sig (noeglen
            # 'maerke|lastbil'). Flytter kilden et anlaeg fra den ene halvdel til den anden (E.ON's
            # chargingUseCase, Uno-X' truck-flag), blev den nye post tilfoejet oven paa vores raekke i
            # den anden halvdel - en dublet 0 m fra den gamle (reproduceret i review 13-10-2026 med
            # MAN Tilst og Cafeteria Storebælt). Staar vores raekke fra den anden halvdel inden for
            # NAER_M, og har kilden den ikke laengere dér, er det et skifte: meld, tilfoej ikke.
            anden_h = 'bil' if maerke.endswith(LASTBIL) else 'lastbil'
            if mangler and fn in (LADE, TANK) and navn not in EN_HALVDEL \
                    and (navn, _basis(maerke), anden_h) not in HALVDEL_IKKE_I_KILDEN:
                # (Leverer henteren med vilje ikke den anden halvdel, kan den ikke sige, om anlaegget
                # 'stadig er dér' - samme grund som EN_HALVDEL; review 14-10-2026.)
                anden = maerke[:-len(LASTBIL)] if maerke.endswith(LASTBIL) else maerke + LASTBIL
                andre_r = [r for r in egne.get(anden, []) if _vores_koord(r, fn)]
                kilde_anden = pr.get(anden, [])
                flip = []
                for x in (mangler if andre_r else []):
                    naer = min(((hav(*_koord(x), float(r[la_i]), float(r[lo_i])), r) for r in andre_r),
                               key=lambda t: t[0], default=None)
                    if not naer or naer[0] >= NAER_M:
                        continue
                    if any(hav(*_koord(x2), float(naer[1][la_i]), float(naer[1][lo_i])) < NAER_M
                           for x2 in kilde_anden):
                        continue                  # kilden har stadig den anden halvdel dér: to anlaeg
                    flip.append(x)
                    linjer.append(f'  {navn:16} BIL/LASTBIL     {maerke}: {(x.get("name") or "")[:28]} — vores '
                                  f'{"lastbil" if anden.endswith(LASTBIL) else "bil"}række "{naer[1][1][:28]}" '
                                  f'står {round(naer[0])} m væk og er væk fra kilden dér; tilføjes IKKE - '
                                  f'ret Lastbil i hånden')
                mangler = [x for x in mangler if x not in flip]
            # Hoejst 10 % nye pr. koersel, men ét nyt er altid tilladt (MIN_NYE_FRIT). 17-09-2026 skulle
            # spaerren stoppe IKEA 6 -> 8 (33 %), men 'flere end 2 OG flere end 10 %' er det samme som det
            # gamle max(2, 10 %): 2 nye slap stadig igennem for ethvert maerke under 20 raekker (fundet af
            # testene 14-10-2026). Med MIN_NYE_FRIT = 1 afvises 2 nye til IKEA; 40 raekker taaler 4.
            # Ladere uden brugbar effekt, stik eller antal meldes FOER vaekstspaerren, saa spaerren kun
            # taeller anlaeg, der kan tilfoejes: ellers kunne én ufuldstaendig post faa et rigtigt nyt anlaeg
            # ved siden af afvist (testene 14-10-2026, efter MIN_NYE_FRIT = 1).
            def _int(v):
                try:
                    return int(float(v))
                except (TypeError, ValueError, OverflowError):   # ogsaa 'inf' (testene 14-10-2026)
                    return 0
            gulv, loft = LADE_KW['lastbil' if maerke.endswith(LASTBIL) else 'bil']
            if mangler and fn == LADE:
                # En lader uden effekt, stik og antal ladepunkter kan ikke vises rigtigt, og effekten afgoer,
                # om den overhovedet hoerer til laget. Lagets loft (validate.py): ét CCS-udtag paa en bilraekke
                # giver hoejst 600 kW, en lastbilraekke med MCS hoejst 1.200 kW. Uden loftet kunne en henter
                # uden eget loft (clever) eller med 1.200 for alle (ok_chargers) tilfoeje en bilraekke paa 1.000 kW.
                # Samme graenser som tests/test_data.py: en raekke, testen ville afvise, maa ikke tilfoejes
                # - ellers stopper én kildevaerdi hele ugens udgivelse (review 14-10-2026).
                ufuld = [x for x in mangler if not (gulv <= _int(x.get('kw')) <= loft
                                                    and 0 < _int(x.get('count')) <= LADE_MAX_ANTAL
                                                    and str(x.get('plug') or '').strip())]
                for x in ufuld:
                    linjer.append(f'  {navn:16} NY (UFULDSTÆNDIG) {maerke}: {(x.get("name") or "")[:30]} — '
                                  f'mangler effekt/stik/antal, eller effekten er uden for {gulv}-{loft} kW '
                                  f'(kW={x.get("kw")!r}, antal={x.get("count")!r}); tilføjes IKKE')
                mangler = [x for x in mangler if x not in ufuld]
            if mangler and len(mangler) > MIN_NYE_FRIT and \
               len(mangler) > len(vore) * MAX_NYE_PR_MAERKE:
                if navn in KUN_RAPPORT:
                    # KUN_RAPPORT skriver aldrig noget, saa spaerren maa ikke skjule navnene paa de nye
                    # anlaeg (Spirii 11 + 2 nye gav én AFVIST-linje uden navne; testene 14-10-2026). De
                    # meldes med kildens egne tekster, uden adresseopslag i DAR (mulig kildefejl).
                    import html as _h
                    _r = lambda s: ' '.join(_h.unescape(s or '').split())
                    for x in mangler[:20]:
                        linjer.append(f'  {navn:16} NY (RAPPORT)    {maerke}: {_r(x.get("name"))[:30]} · '
                                      f'{_r(x.get("street"))[:40]} — tilføjes IKKE (KUN_RAPPORT; '
                                      f'{len(mangler)} nye mod {len(vore)}, over {MAX_NYE_PR_MAERKE:.0%})')
                    if len(mangler) > 20:
                        linjer.append(f'  {navn:16} NY (RAPPORT)    {maerke}: ... og {len(mangler) - 20} flere '
                                      f'— mulig kildefejl')
                    continue
                linjer.append(f'  {navn:16} AFVIST          {maerke}: {len(mangler)} nye mod '
                              f'{len(vore)} eksisterende — over {MAX_NYE_PR_MAERKE:.0%}, '
                              f'ser ud som en kildefejl (fx '
                              + ', '.join((x.get('name') or '?')[:30] for x in mangler[:3]) + ')'); continue
            if mangler:
                # Rens ogsaa her: kilderne leverer HTML, og en enkelt henter kan
                # have sin egen parser der ikke gaar gennem _ld_store.
                import html as _h
                _r = lambda s: ' '.join(_h.unescape(s or '').split())
                basis = _basis(maerke)
                if fn == LADE:
                    rows = [[basis, _r(x.get('name')) or basis,
                             f"{_r(x.get('street'))}, {x.get('postnr','')} {_r(x.get('by'))}".strip(', '),
                             str(x.get('postnr') or ''), _r(x.get('by')),
                             str(_int(x.get('kw'))), x.get('plug'), str(_int(x.get('count'))),
                             f"{_koord(x)[0]:.6f}", f"{_koord(x)[1]:.6f}",
                             'ja' if maerke.endswith(LASTBIL) else ''] for x in mangler]
                else:
                    rows = [[basis, _r(x.get('name')) or basis,
                             f"{_r(x.get('street'))}, {x.get('postnr','')} {_r(x.get('by'))}".strip(', '),
                             str(x.get('postnr') or ''), _r(x.get('by')),
                             f"{_koord(x)[0]:.6f}", f"{_koord(x)[1]:.6f}"] for x in mangler]
                    if fn == TANK:            # 8. kolonne: Lastbil
                        for r in rows:
                            r.append('ja' if maerke.endswith(LASTBIL) else '')
                if not rows:
                    continue
                st = []
                raekker_foer = list(rows)
                normalize_rows(rows, adr=2, postnr=3, by=4, lat=la_i, lon=lo_i, workers=6, status_ud=st)
                # 'ingen-adresse' = ingen dansk adresse inden for 3,3 km: en udenlandsk
                # koordinat eller en kildefejl. Udelad RAEKKEN - men det er ikke et
                # udfald, saa den maa ikke faa hele maerkets nye butikker afvist.
                for r, s in zip(rows, st):
                    if s == 'ingen-adresse':
                        linjer.append(f'  {navn:16} UDEN FOR DK?    {maerke}: {r[1][:26]} — '
                                      f'ingen dansk adresse inden for 3 km; udeladt')
                skip = sum(1 for s in st if s not in ('ok', 'ingen-adresse'))
                rows = [r for r, s in zip(rows, st) if s != 'ingen-adresse']
                rows = [r for r in rows if r[3].strip() and r[4].strip()]
                # DK-boksen raekker ~60 km ind i Tyskland og Sverige. En udenlandsk
                # butik faar en opdigtet dansk adresse, fordi DAWA-reverse svarer med
                # det naermeste danske punkt UANSET afstand. Maal derfor hvor langt
                # der er til den adresse DAWA fandt.
                langt = []
                ok_raekker = {id(r) for r, s in zip(raekker_foer, st) if s == 'ok'}
                for r in rows:
                    # Raekker hvor opslaget fejlede, taeller allerede i 'skip' og afviser
                    # maerket nedenfor; spoerg ikke DAR igen. Og et nyt udfald HER maa ikke
                    # crashe hele koerslen for alle kaederne (fundet i review 29-09-2026).
                    if id(r) not in ok_raekker:
                        continue
                    try:
                        rv = reverse_full(float(r[la_i]), float(r[lo_i]))
                    except DawaNede:
                        skip += 1
                        continue
                    # None = ingen adresse inden for 3,3 km (DAR-udgaven; DAWA fandt altid én)
                    if rv is None or hav(float(r[la_i]), float(r[lo_i]), rv[4], rv[5]) > 2000:
                        langt.append(r)
                        linjer.append(f'  {navn:16} UDEN FOR DK?    {maerke}: {r[1][:26]} — '
                                      + (f'naermeste danske adresse ligger '
                                         f'{round(hav(float(r[la_i]), float(r[lo_i]), rv[4], rv[5])/1000)} km vaek'
                                         if rv else 'ingen dansk adresse inden for 3 km') + '; udeladt')
                rows = [r for r in rows if r not in langt]
                if skip:
                    linjer.append(f'  {navn:16} AFVIST          {maerke}: adresse-opslaget (DAR) svarede ikke for '
                                  f'{skip} af {len(mangler)} nye — prøv igen senere'); continue
                # Ingen eksakt dublet: samme maerke, navn og adresse (og halvdel) som en raekke, vi har, eller en,
                # der lige er tilfoejet. Flytter kilden en pin 150-300 m for en butik uden entydigt navn (264 x
                # 'Matas'), bliver kildeposten ellers NY BUTIK med vores raekkes adresse - og den blokerende
                # data-test stopper hele ugens udgivelse, hver uge (review 14-10-2026).
                lbi = 10 if fn == LADE else 7 if fn == TANK else None
                noegle = lambda r: (r[0], r[1], r[2], r[lbi] if lbi is not None and len(r) > lbi else '')
                kendte = {noegle(r) for r in filer[fn][1]} | {noegle(r) for r in nye[fn]}
                ude = []
                for r in rows:
                    if noegle(r) in kendte:
                        ude.append(r)
                        linjer.append(f'  {navn:16} DUBLET          {maerke}: {r[1][:30]} · {r[2][:40]} — samme '
                                      f'mærke, navn og adresse som en eksisterende eller netop tilføjet række; '
                                      f'tilføjes IKKE (kildens pin flyttet?)')
                    kendte.add(noegle(r))
                rows = [r for r in rows if r not in ude]
                if navn in KUN_RAPPORT:
                    for r in rows:
                        linjer.append(f'  {navn:16} NY (RAPPORT)    {maerke}: {r[1][:30]} · {r[2][:40]} '
                                      f'— tilføjes IKKE automatisk (KUN_RAPPORT)')
                    continue
                nye[hvor[maerke]] += rows; n_ny += len(rows)
                for r in rows:
                    linjer.append(f'  {navn:16} NY BUTIK        {maerke}: {r[1][:30]} · {r[2][:40]}')
            pass

    print('\n'.join(linjer).replace(LADEKEY, ' (lader)').replace(LASTBIL, ' (lastbil)')
          if linjer else '  (ingen ændringer)')
    skrevet = 0
    for fn, (head, body) in filer.items():
        if not nye[fn]:
            continue
        ud = body + [r + [''] * (len(head) - len(r)) for r in nye[fn]]
        ud.sort(key=lambda z: (z[0], str(z[3])))
        print(f'  {fn}: {len(body)} -> {len(ud)} (+{len(nye[fn])} nye)')
        if apply:
            with open(os.path.join(OUT, fn), 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f); w.writerow(head); w.writerows(ud)
            skrevet += 1
    print(f'\n{n_ny} nye butikker · {n_luk} mulige lukninger (ikke slettet) · '
          f'{n_afvig} koordinat-afvigelser · {len(fejlede)} henter(e) fejlede ({n_fejl} fejllinjer) · '
          f'{skrevet} fil(er) skrevet'
          + ('' if apply else '   [ingen --apply: intet skrevet]'))
    # Exit-koden: 2 naar en HENTER fejlede — det er en rigtig fejl, og trinnet skal
    # lyse roedt i Actions. Mulige lukninger og afvigelser er derimod normale fund
    # til gennemsyn og maa ikke faelde jobbet; de staar i loggen.
    # (Foerste udgave returnerede 0 for alt undtagen en exception, saa enhver
    # afvisning var usynlig. Anden udgave returnerede 1 ved lukninger, hvilket ville
    # faelde trinnet hver gang en kaede lukkede en butik — ogsaa naar alt var i orden.)
    return 2 if n_fejl else 0


if __name__ == '__main__':
    sys.exit(main(apply='--apply' in sys.argv))
