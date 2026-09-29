#!/usr/bin/env python3
"""
refresh_retail.py — hold de 30 kaeder friske UDEN at omskrive haandverificerede data.

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
from dawa import normalize_rows, reverse_full

OUT = os.path.dirname(os.path.abspath(__file__))
NAER_M = 150             # samme butik, hvis den ligger inden for dette af en kildepost
MAX_NYE_PR_MAERKE = 0.10 # en kaede maa ikke vokse over 10 % paa én koersel
MIN_NYE_FRIT = 2         # ... men under dette antal er procenten meningsloes
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
}

# Butikker vi BEVIDST ikke vil have, selv om kilden lister dem. Uden denne kommer
# en haandslettet raekke tilbage naeste mandag — og med kildens adresse, ikke den
# rettede. Noeglen er (maerke, kildens gadetekst i lowercase) som KILDEFEJL, og
# hver post skal have en grund.
#
# Tom i dag: de udeladelser der allerede er truffet, ligger i hentererne (thiele()
# frasorterer oejenlaserklinikken) eller fanges af DK-tjekket. Listen findes for at
# naeste udeladelse havner i KODEN og ikke kun i dataene.
UDELADT = {
    # ('Maerke', 'gade nr'): 'grunden, med belaeg',
}

KAEDER = [(n, getattr(RS, n)) for n in (
    'coop', 'netto', 'seven_eleven', 'rema', 'dagrofa', 'lidl', 'apoteker', 'matas',
    'loevbjerg', 'imerco', 'kopkande', 'sport24', 'bogide', 'synoptik', 'thiele',
    'powerdk', 'toejeksperten', 'jysk', 'ilva', 'ikea', 'stark', 'xlbyg', 'bygma',
    'jemogfix', 'davidsen', 'silvan', 'bauhaus', 'plantorama', 'thansen')]
KAEDER += [('lagkagehuset', S.lagkagehuset)]
FILER = ('dagligvarer_dk.csv', 'udvalgsvarer_dk.csv', 'pladskraevende_dk.csv')


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


def _vores_koord(r):
    """Vores EGEN raekke -> (lat, lon) eller None. float() paa en tom streng rejste
    ValueError midt i koerslen, saa alle fund fra de kaeder der allerede var koert
    igennem gik tabt, og den committede rapport blev et traceback."""
    try:
        return (float(r[5]), float(r[6]))
    except (TypeError, ValueError, IndexError):
        return None


def _koord(x):
    try:
        la, lo = float(x['lat']), float(x['lon'])
    except (TypeError, ValueError, KeyError):
        return None
    return (la, lo) if DK[0] < la < DK[1] and DK[2] < lo < DK[3] else None


def main(apply=False):
    filer = {fn: _laes(fn) for fn in FILER}
    hvor, egne = {}, collections.defaultdict(list)
    for fn, (_, body) in filer.items():
        for r in body:
            hvor[r[0]] = fn
            egne[r[0]].append(r)

    nye = collections.defaultdict(list)
    linjer, n_ny, n_luk, n_afvig, n_fejl = [], 0, 0, 0, 0

    for navn, hent in KAEDER:
        try:
            raa = hent()
        except Exception as e:
            linjer.append(f'  {navn:16} HENTER FEJLEDE  {type(e).__name__}: {e}'[:110]); n_fejl += 1; continue
        # Et TOMT svar er ikke "kaeden har lukket alle butikker" — det er en henter
        # der er holdt op med at virke (side lagt om, regex matcher ikke, WAF svarer
        # 200 med en tom shell). Uden dette skrev koerslen "(ingen aendringer)" og
        # exit 0, mens hele maerket stod uden for overvaagning.
        if not raa:
            linjer.append(f'  {navn:16} TOMT SVAR       kilden svarede med 0 poster — '
                          f'behandles som en fejl, ikke som 0 butikker'); n_fejl += 1; continue
        ukoord = [x for x in raa if _koord(x) is None]
        raa = [x for x in raa if _koord(x)]
        # Fjern kildens EGNE dubletter ét sted for alle 29 kaeder. toejeksperten.dk
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
        pr = collections.defaultdict(list)
        for x in raa:
            pr[x.get('brand')].append(x)
        # Maerker denne henter ER ansvarlig for, men som slet ikke optraeder i svaret.
        # 'pr' bygges af kildesvaret, saa uden dette blev de aldrig kigget paa: fjernes
        # Brugsen fra coop-svaret, meldte koerslen "0 mulige lukninger" og exit 0,
        # mens 265 butikker stod uden for overvaagning.
        for maerke in EJER.get(navn, []):
            if maerke not in pr and egne.get(maerke):
                linjer.append(f'  {navn:16} MÆRKE MANGLER   {maerke}: kilden nævner det slet ikke, '
                              f'men vi har {len(egne[maerke])} rækker — behandles som en fejl')
                n_fejl += 1
        for maerke, xs in pr.items():
            if maerke not in hvor:
                linjer.append(f'  {navn:16} UKENDT MÆRKE    {maerke!r} findes ikke i nogen CSV — '
                              f'kategorien er en planlovsafgørelse, ikke en teknisk'); continue
            vore = [r for r in egne[maerke] if _vores_koord(r)]
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
            brugt_vore, brugt_kilde, afvig = set(), set(), []
            for i, x in enumerate(xs):
                if _nk(x.get('name')) not in entydig:
                    continue
                for j, r in enumerate(vore):
                    if j in brugt_vore or not _navn_ens(x.get('name'), r[1]):
                        continue
                    d = hav(*_koord(x), float(r[5]), float(r[6]))
                    brugt_vore.add(j); brugt_kilde.add(i)
                    if d > NAER_M:
                        afvig.append((r, x, d))
                    break
            # NAERMESTE, ikke foerste. 'break ved foerste inden for 150 m' tog raekken
            # i CSV-raekkefoelge: for Matas matches alle 264 paa naerhed alene (ingen
            # entydige navne), og fire Matas-par ligger under 150 m fra hinanden
            # (Frederiksberg 7 m). Lukkede den ene af to nabobutikker, udpegede
            # rapporten den anden — foelger man den, sletter man den AABNE butik.
            par = sorted((hav(*_koord(x), float(r[5]), float(r[6])), i, j)
                         for i, x in enumerate(xs) if i not in brugt_kilde
                         for j, r in enumerate(vore) if j not in brugt_vore)
            for d, i, j in par:
                if d >= NAER_M or i in brugt_kilde or j in brugt_vore:
                    continue
                brugt_vore.add(j); brugt_kilde.add(i)
            mangler = [x for i, x in enumerate(xs) if i not in brugt_kilde]
            lukket = [r for j, r in enumerate(vore) if j not in brugt_vore]
            for r, x, d in afvig:
                linjer.append(f'  {navn:16} KOORD-AFVIGELSE {maerke}: {r[1][:26]} — vores '
                              f'{r[2][:30]} ligger {round(d)} m fra kildens {x.get("street","")[:26]}; '
                              f'RETTES IKKE automatisk')
            n_afvig += len(afvig)
            # Lukninger rapporteres FOER enhver 'continue'. Laa de efter, slugte
            # AFVIST- og DAWA-udfaldet dem, og slutlinjen paastod "0 mulige
            # lukninger" i netop den uge hvor kilden opfoerte sig underligt.
            for r in lukket:
                linjer.append(f'  {navn:16} MULIG LUKNING   {maerke}: {r[1][:30]} · {r[2][:40]} '
                              f'— kilden har den ikke; SLETTES IKKE automatisk')
            n_luk += len(lukket)
            # max(2, 10 %) gjorde spaerren virkningsloes for de smaa maerker: IKEA
            # har 6 raekker, saa 2 nye er 33 % og slap alligevel igennem. Nu gaelder
            # BEGGE graenser — det absolutte tal OG procenten.
            if mangler and len(mangler) > MIN_NYE_FRIT and \
               len(mangler) > len(vore) * MAX_NYE_PR_MAERKE:
                linjer.append(f'  {navn:16} AFVIST          {maerke}: {len(mangler)} nye mod '
                              f'{len(vore)} eksisterende — over {MAX_NYE_PR_MAERKE:.0%}, '
                              f'ser ud som en kildefejl'); continue
            if mangler:
                # Rens ogsaa her: kilderne leverer HTML, og en enkelt henter kan
                # have sin egen parser der ikke gaar gennem _ld_store.
                import html as _h
                _r = lambda s: ' '.join(_h.unescape(s or '').split())
                rows = [[maerke, _r(x.get('name')) or maerke,
                         f"{_r(x.get('street'))}, {x.get('postnr','')} {_r(x.get('by'))}".strip(', '),
                         str(x.get('postnr') or ''), _r(x.get('by')),
                         f"{_koord(x)[0]:.6f}", f"{_koord(x)[1]:.6f}"] for x in mangler]
                _, skip = normalize_rows(rows, adr=2, postnr=3, by=4, lat=5, lon=6, workers=6)
                rows = [r for r in rows if r[3].strip() and r[4].strip()]
                # DK-boksen raekker ~60 km ind i Tyskland og Sverige. En udenlandsk
                # butik faar en opdigtet dansk adresse, fordi DAWA-reverse svarer med
                # det naermeste danske punkt UANSET afstand. Maal derfor hvor langt
                # der er til den adresse DAWA fandt.
                langt = []
                for r in rows:
                    rv = reverse_full(float(r[5]), float(r[6]))
                    if rv and hav(float(r[5]), float(r[6]), rv[4], rv[5]) > 2000:
                        langt.append(r)
                        linjer.append(f'  {navn:16} UDEN FOR DK?    {maerke}: {r[1][:26]} — '
                                      f'naermeste danske adresse ligger '
                                      f'{round(hav(float(r[5]), float(r[6]), rv[4], rv[5])/1000)} km '
                                      f'vaek; udeladt')
                rows = [r for r in rows if r not in langt]
                if skip:
                    linjer.append(f'  {navn:16} AFVIST          {maerke}: DAWA svarede ikke for '
                                  f'{skip} af {len(mangler)} nye — prøv igen senere'); continue
                nye[hvor[maerke]] += rows; n_ny += len(rows)
                for r in rows:
                    linjer.append(f'  {navn:16} NY BUTIK        {maerke}: {r[1][:30]} · {r[2][:40]}')
            pass

    print('\n'.join(linjer) if linjer else '  (ingen ændringer)')
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
          f'{n_afvig} koordinat-afvigelser · {n_fejl} henter(e) fejlede · {skrevet} fil(er) skrevet'
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
