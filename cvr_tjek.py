#!/usr/bin/env python3
"""
cvr_tjek.py — tankstationernes adresser holdt op mod CVR (Virks data via Datafordeleren).

RAPPORTERER kun; den aendrer ingen data. Skriver cvr_report.txt.

Hvorfor: CVR er det officielle register over, hvor en virksomhed driver noget. Hver
tankstation er en produktionsenhed (P-enhed) med en beliggenhedsadresse. Holdt op mod
tanklaget 30-09-2026 fandt den fejl, som hverken kilderne, DAR eller BBR kunne se:
OK's API skriver 'Gammel Stillingvej 4' for OK Harlev J, CVR har stationen som
'Harlev Benzin', Gammel Stillingvej 431 (Brugsforeningen TRYG).

CVR er godt til ADRESSER, ikke til aabent/lukket: den halter begge veje (Brugsen
Virklund stod som aktiv en uge efter lukningen, SuperBrugsen Virklund fem maaneder
foer aabningen). Derfor sammenligner scriptet kun adresser paa stationer vi har.

Metode:
  1. Alle aktive P-enheder med branche 473000 (detailhandel med motorbraendstof) plus
     OK a.m.b.a.'s egne (CVR 39170418; de staar under engroshandel, 468100).
  2. Deres beliggenhedsadresse slaas op i DAR for at faa et punkt.
  3. For hver raekke i tankstationer_dk.csv: P-enheder fra SAMME kaede inden for
     NAER_M. Samme kaede afgoeres af P-enhedens navn, naar det naevner et maerke
     (Circle K ejer ogsaa Ingo, Q8 ogsaa F24), ellers af ejeren.
  4. Rapporter raekker, hvor ingen af dem har samme vej (stavevarianter som Gl./Gammel
     og Allé/Alle godtages, se dawa._ligner) og samme husnummer uden bogstav (CVR har
     intet felt for husbogstav).

Koer:  python3 cvr_tjek.py
"""
import concurrent.futures, csv, json, os, re, sys, time
import dawa

OUT = os.path.dirname(os.path.abspath(__file__))
CVR_URL = 'https://graphql.datafordeler.dk/CVR/v2'
NAER_M = 80
OK_AMBA = 39170418
BRAENDSTOF = '473000'
# Ejere hvis P-enheder ikke altid naevner maerket i navnet (fx OK: '393 - Albertslund').
EJER_MAERKE = {28142412: {'Circle K', 'Ingo'}, 61082913: {'Q8', 'F24'}, 36552816: {'OIL!'},
               36563028: {'Shell'}, 13256772: {'OK'}, OK_AMBA: {'OK'}}
# Maerkenavne som de staar i P-enhedernes navne.
NAVNE_MAERKE = [(re.compile(r'circle\s*k', re.I), 'Circle K'), (re.compile(r'\bingo\b', re.I), 'Ingo'),
                (re.compile(r'\bf24\b', re.I), 'F24'), (re.compile(r'\bq\s?8\b', re.I), 'Q8'),
                (re.compile(r'\bshell\b', re.I), 'Shell'), (re.compile(r'\boil!', re.I), 'OIL!'),
                (re.compile(r'\bok\b', re.I), 'OK'), (re.compile(r'uno-?x', re.I), 'Uno-X'),
                (re.compile(r"go'?on", re.I), "Go'on"), (re.compile(r'\byx\b', re.I), 'Uno-X')]


# Afgjorte tilfaelde, hvor raekken er rigtig og CVR ikke: (maerke, raekkens gadetekst i
# lowercase) -> grund med belaeg. Saa melder rapporten dem ikke igen hver uge.
KENDTE = {
    ('F24', 'grenåvej 740f'): 'CVR har Grenåvej 742, som ikke findes i DAR; BBR-tankbygningen er 740F (30-09-2026)',
    # Efterproevet 30-09-2026 (efterforsker + skeptiker):
    ('Circle K', 'korskrovej 12'): 'Circle K bruger nr. 12, stationens egen grund (27k); P-enheden '
                                   'staar paa nr. 10, fordi den er aeldre end nr. 12 (oprettet 2019)',
    ('F24', 'søndre tobølvej 12'): 'F24 og pinnen er paa nr. 12; P-enheden staar paa naboens boligadresse',
    ('OK', 'bilbyen 12'): 'OK bruger 12 i API og finder, og tankene er registreret paa 12; nr. 10 er '
                          'en anden, ubebygget grund',
    ('OK', 'viborgvej 111'): 'DAR, tankene og grunden siger 111; 109 i CVR er naboens pizzeria',
    ('Shell', 'sibeliusgade 4'): 'DAR-punktet og BBR-bygningerne er nr. 4; DCC\'s CVR-nr. 2 er en cykel-'
                                 'parkering, Shells egen tekst (nr. 8) et kolonihavehus (medium sikkerhed)',
}


# SIKKERHEDSNET mod manglende stationer ("hvor er thansen i Vordingborg?" - butikken
# manglede, fordi laget kun kom fra OSM): P-enheder fra disse kaeder, som ikke har en
# raekke fra kaeden inden for MANGLER_M. OK og Tesla er ikke med; de hentes komplet fra
# kaedernes egne API'er hver uge. CVR halter begge veje, saa listen er kandidater til
# efterproevning - en station der har skiftet kaede, staar ofte i CVR i maaneder.
MANGLER_EJERE = {28142412: {'Circle K', 'Ingo'}, 61082913: {'Q8', 'F24'}, 36552816: {'OIL!'},
                 36563028: {'Shell'}}
MANGLER_M = 150
IKKE_STATION = re.compile(r'\bvask\b|bilvask|vaskehal|kontor|lager|administration|hovedsæde|'
                          r'domicil|depot|værksted', re.I)
# Afgjorte kandidater: P-nummer -> grund med belaeg (ikke en station, lukket, skiftet kaede).
KENDTE_MANGLER = {
    # Efterproevet 30-09-2026 (efterforsker + skeptiker, kaedens finder, CVR, BBR, OSM, presse).
    # Circle K's fire motorvejsanlaeg blev OK i januar 2026 (Vejdirektoratets rastepladsudbud).
    1013513046: 'Tankstationen Ejer Bavnehøj Ø blev OK 15-01-2026 (Vejdirektoratets rastepladsudbud; OK facility 1022, raekken ’OK Skanderborg, Østjyske Motorvej 545’); Circle K har kun ladere tilbage paa adressen (CIRCLE K EV EJER BAVNEHØJ, siteT',   # Circle K Ejer Bavnehøj (ck-ejer-bavnehoej)
    1031770080: 'Ren ladelokation: circlek.dk har CIRCLE K EV EJER BAUNEHØJ VEST som siteType EV med kun ’EL Ladestander’ (staar i superladere_dk.csv); tankstationen paa Ejer Bavnehøj V er OK, nr. 536A (30-09-2026)',   # CIRCLE K EV EJER BAUNEHØJ VEST (ck-ev-baunehoej-vest)
    1021478624: 'Karlslunde V (296A) blev OK 13-01-2026 (Vejdirektoratets rastepladsudbud; OK facility 1028 har raekke); circlek.dk-siden ’MOTORVEJSCENTER KARLSLUNDE-CL’ siger ’Station closed down’ (30-09-2026)',   # Circle K Karlslunde (ck-karlslunde)
    1021479027: 'Skærup Ø (617B) blev OK 08-01-2026 (Vejdirektoratets rastepladsudbud; raekken ’OK Vejle, Østjyske Motorvej 617B’); circlek.dk-siden ’SKÆRUP ØST MOTORVEJSCENTER-CL’ siger ’Station closed down’; Circle K driver kun Skærup V (616A) (',   # Circle K Skærup Øst (ck-skaerup-oest)
    1003108538: 'Tappernøje V (380) blev OK 06-01-2026 (Vejdirektoratets rastepladsudbud; raekken ’OK Tappernøje, Sydmotorvejen 380’); Circle K har kun ladere her (CIRCLE K EV TAPPERNØJE VEST, siteType EV, i superladere_dk.csv) og driver stadig Ta',   # Circle K Tappernøje Vest (ck-tappernoeje-vest)
    1021479000: 'Circle K Kildebjerg Syd (reelt Fynske Motorvej 531A; CVR skriver Kildebjergvaenget 2, som ikke findes i DAR) blev Shell 1/1-2026 (DCC 7/2-2025); circlek.dk: ’Station closed down’, Assens Kommunes tilsyn 2/9-2026: ’Circle K’s aktiv',   # CIRCLE K DANMARK A/S (ck-kildebjergvaenget)
    1005100996: 'Circle K Automat Soeborg Hovedgade 17 er lukket: ikke i Circle K’s liste, stationssiden ’...-cl’ giver nu 404; grunden solgt 2025 til MB Boliger, der planlaegger 26 boliger (Dansk Byudvikling 16/9-2026)',   # Circle K Automat (ck-soeborg-automat)
    1021569077: 'Circle K Truck Noerremarken (HVO100-lastbilpumpe paa raffinaderiets adresse Egeskovvej 265): circlek.dk siger ’Station closed down’, og den er ikke i Circle K’s liste (30/9-2026)',   # Circle K Danmark A/S (ck-egeskovvej)
    1003108162: 'Circle K Automat Glostrup, Ndr. Ringvej 7: circlek.dk siger ’Station closed down’, ikke i Circle K’s liste, intet tankanlaeg i OSM; Uno-X 149 m vaek er en anden station (Hovedvejen 141, egen BBR-tankbygning)',   # Circle K Danmark A/S (ck-nordre-ringvej-glostrup)
    1000692482: 'Statoil/Circle K Sundvej 92 revet ned juli 2017 (HSFO 6/7-2017), nu Lidl Sundvej 92; BBR-bygningerne er nedrevet (status 10)',   # Circle K Danmark A/S (ck-sundvej-horsens)
    1021564296: 'Ingo Soendergade 60/Hessgade solgt til Melfarhus 2021 (Melfarposten 25/2-2021); tankbygningen er nedrevet (BBR status 10), grunden bebygget med boliger 2026',   # Circle K Danmark A/S (ck-middelfart)
    1021564199: 'Ubemandet station Tagensvej 40 revet ned foer lokalplanen (KK 13/6-2022); Lidl bygger butik og boliger; BBR-tankbygningerne er nedrevet (status 10)',   # Circle K Danmark A/S (ck-tagensvej)
    1021478896: 'Circle K Silkeborgvej 4, Aarhus C lukkede 24/8-2025 og rives ned (Mig og Aarhus 28/8-2025); circlek.dk: ’Station closed down’; byggeplads i OSM',   # Circle K Silkeborgvej, Aarhus C (ck-silkeborgvej-aarhus)
    1008488564: 'P-enheden er vores CIRCLE K SKIBBY (Hovedgaden 1D: BBR-tankbygninger og Circle K’s egen koordinat); CVR’s ’Hovedgaden 1A’ er butikscentret 579 m mod nord',   # Circle K Skibby (ck-skibby)
    1021567740: 'Ingo Hjoerring, A F Heidemanns Vej 3: ingo.dk siger ’A F HEIDEMANNSVEJ-CL ... Station closed down’, ikke i Circle K/Ingo-listen; Circle K Ringvejen (Heerfordtsvej 2) er en anden station, og raekken er rigtig',   # Ingo (ingo-hjoerring)
    1017703621: 'F24 Kolding Storcenter, Skovvangen 42, er lukket: stationen stod i Q8/F24’s finder 2010-2014 (Wayback 28-06-2010, 25-10-2012 og 21-02-2014, punkt 55.51545, 9.45966 på centrets nordlige P-plads). Stedet er nyasfalteret P-areal på l',   # F24 (f24-kolding-skovvangen)
    1003139228: 'Samme station som Q8-rækken ’København V, Nyropsgade 42’: anlægget står i Nyropsgades midterrabat ved Gyldenløvesgade (DAR/BBR: Nyropsgade 35). CVR’s og Q8’s ’Nyropsgade 42’ har DAR-punkt på en anden bygning 172 m mod syd.',   # Q 8 SERVICE (q8-nyropsgade)
    1003139034: 'Q8 Danmark A/S’ hovedkontor (Arne Jacobsens Allé 17, 6. sal; branche 468100 + 473000; samme adresse som selskabet og q8.dk’s sidefod) - ingen tankstation.',   # Q8 DANMARK A/S (q8-arne-jacobsens)
    1015217231: 'Stationen på Munkholmvej 107 er i dag Uno-X ’Holbæk Munkholmvej’ (Uno-X’ finder nr. 1017; OSM operator=Uno-X), som ligger i datasættet; Q8-P-enheden fra 2008 er forældet.',   # Q8 DANMARK A/S (q8-munkholmvej)
    1023869698: 'Shell CRT på Olievej 7 er lukket: ikke i Shells finder 30-09-2026 (i 9220 kun Kertemindevej 2A, som er i datasættet). Tankpladsen ses på luftfoto 2018-2019, men grunden er nu LOXAM med en ny kontorbygning på adressepunktet (BBR 20',   # Shell CRT (shell-crt-olievej)
    1026879473: 'Shell Express Karrebækvej 5-7 blev Uno-X i uge 10 2024 (et af de 57 Shell→Uno-X-skift, TV2 Øst). Uno-X ’Næstved Karrebækvej’ (nr. 2454) ligger i datasættet.',   # Shell EXPRESS KARREBÆKVEJ NÆSTVED (shell-karrebaekvej)
    1026879309: 'Shell Express Randersvej 164 lukkede 22-06-2025, og grunden er solgt til Lidl (Din Avis/Stiften, juni 2025). BBR har tankbygningerne som nedrevet fra 06-08-2025. Q8 på Randersvej 162 ved siden af er en anden station med egen P-enh',   # Shell EXPRESS ÅRHUS N (shell-aarhus-n)
    1023866311: 'Shell Express Hundige Strandvej 184 er lukket: fjernet fra Shells finder (EXPRESS HUNDIGE, id 10123169, giver 404), og BBR har tankbygningen (325, opført 1954) som nedrevet fra 04-03-2026.',   # Shell Express (shell-hundige)
    1020456023: 'P 1020456023 ’OIL! tank & go ApS’, Andkærvej 26A, 7100 Vejle, er OIL!’s hovedkontor og serviceteam ifølge kontaktsiden og folderens sidefod (CVR 36552816). BBR registrerer en kontor-, handels- og lagerbygning (329) og ingen tankby',   # OIL! tank & go ApS (oil-andkaervej)
    1020462058: 'P 1020462058 ’OIL! tank & go Sønderborg’ svarer til vores række med samme navn (Grundtvigs Alle 185, 6400). CVR har Bilka-grundens adresse, Grundtvigs Alle 195, hvis DAR-punkt ligger cirka 160 m fra pumperne. DAR-punktet for nr. 1',   # OIL! tank & go Sønderborg (oil-soenderborg)
    1023876759: 'Den gamle Shell CRT Padborg (Lejrvejen 4-6) er lukket; BBR har tankbygningen som nedrevet fra 04-08-2025. Stationen er nu Shell CRT Padborg Nord, Kilen 4 (aabnet 29-06-2023), som har sin raekke',   # Shell CRT (shell-crt-lejrvejen)
    1027049407: 'OIL! Randers NØ, Jomfruløkken 9: kun for OIL! firmakort-kunder (kaedens folder); bevidst fjernet fra kortet 01-10-2026 og lagt i refresh_retail.UDELADT',   # OIL! Randers NØ
}


def _nu():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _q(query):
    return dawa._gql(query, base=CVR_URL)


def _sider(entitet, where, felter):
    ud, after = [], None
    for _ in range(100):
        a = f', after:{json.dumps(after)}' if after else ''
        d = _q(f'{{ {entitet}(first:1000{a}, virkningstid:"{_nu()}", where:{where}) '
               f'{{ pageInfo{{hasNextPage endCursor}} nodes {{ {felter} }} }} }}')[entitet]
        ud += d['nodes']
        if not d['pageInfo']['hasNextPage']:
            return ud
        after = d['pageInfo']['endCursor']
    raise dawa.DawaNede(f'{entitet}: over 100 sider')


def p_enheder():
    """-> liste af {pnr, ejer, navn, vej, husnr, postnr, lat, lon} for aktive P-enheder."""
    ids = sorted({n['CVREnhedsId'] for n in _sider('CVR_Branche', f'{{vaerdi:{{eq:"{BRAENDSTOF}"}}}}', 'CVREnhedsId')})
    pe = []
    for i in range(0, len(ids), 100):
        pe += _sider('CVR_Produktionsenhed', f'{{id:{{in:{json.dumps(ids[i:i + 100])}}}}}',
                     'id pNummer status produktionsenhedOphoersdato tilknyttetVirksomhedsCVRNummer')
    pe += _sider('CVR_Produktionsenhed', f'{{tilknyttetVirksomhedsCVRNummer:{{eq:{OK_AMBA}}}}}',
                 'id pNummer status produktionsenhedOphoersdato tilknyttetVirksomhedsCVRNummer')
    pe = {x['id']: x for x in pe if x['status'] == 'aktiv' and not x['produktionsenhedOphoersdato']}
    ids = list(pe)
    navn, adr = {}, {}
    for i in range(0, len(ids), 100):
        b = json.dumps(ids[i:i + 100])
        for r in _sider('CVR_Navn', f'{{CVREnhedsId:{{in:{b}}}}}', 'CVREnhedsId vaerdi'):
            navn[r['CVREnhedsId']] = r['vaerdi']
        for r in _sider('CVR_Adressering', f'{{CVREnhedsId:{{in:{b}}}}}',
                        'CVREnhedsId AdresseringAnvendelse CVRAdresse_vejnavn CVRAdresse_husnummerFra CVRAdresse_postnummer'):
            if r['AdresseringAnvendelse'] == 'beliggenhedsadresse' and r['CVRAdresse_vejnavn']:
                adr[r['CVREnhedsId']] = (r['CVRAdresse_vejnavn'], str(r['CVRAdresse_husnummerFra'] or ''),
                                         str(r['CVRAdresse_postnummer'] or ''))

    def geo(i):
        a = adr.get(i)
        if not a:
            return None
        # CVR har intet husbogstav: '2' kan i DAR kun findes som 2A. Tag da familiens
        # foerste - men ALDRIG et andet nummer; saa springes P-enheden over.
        j = dawa._q(vejnavn=a[0], husnr=a[1], postnr=a[2], per_side=1) or \
            dawa._q(vejnavn=a[0], postnr=a[2], per_side=1000)
        hit = [x for x in j if dawa._base(x['husnr']) == dawa._base(a[1])]
        if not hit:
            return None
        x = pe[i]
        return {'pnr': x['pNummer'], 'ejer': x['tilknyttetVirksomhedsCVRNummer'], 'navn': navn.get(i, ''),
                'vej': a[0], 'husnr': a[1], 'postnr': a[2], 'lat': hit[0]['y'], 'lon': hit[0]['x']}
    with concurrent.futures.ThreadPoolExecutor(12) as ex:
        return [g for g in ex.map(geo, ids) if g]


def maerker_for(p):
    # En vaskehal ('426 - Grenå - Vask') er ikke tankstationen, selv om den staar ved siden af.
    if re.search(r'\bvask\b|bilvask|vaskehal', p['navn'], re.I):
        return set()
    fundet = {m for rx, m in NAVNE_MAERKE if rx.search(p['navn'])}
    return fundet or EJER_MAERKE.get(p['ejer'], set())


def samme_adresse(adresse, p):
    vej, husnr = dawa.split_street(adresse)
    if not (dawa._loose(vej) == dawa._loose(p['vej']) or dawa._ligner(vej, p['vej'])):
        return False
    # Et interval ('Buddingevej 81-83') daekker P-enhedens nummer, hvis det ligger i det.
    m = re.search(r'\b(\d+)\s*[A-Za-z]?\s*-\s*(\d+)', adresse.split(',')[0])
    n = dawa._base(p['husnr'])
    if m and n and int(m.group(1)) <= int(n) <= int(m.group(2)):
        return True
    return dawa._base(husnr) == n


def main():
    rapport = os.path.join(OUT, 'cvr_report.txt')
    # Advarslen skrives foerst og overskrives til sidst: doer scriptet undervejs, maa den
    # gamle rapport ikke blive liggende og ligne en ren kontrol.
    open(rapport, 'w', encoding='utf-8').write('CVR-TJEKKET BLEV IKKE FÆRDIGT — ingen rapport for denne kørsel\n')
    pe = p_enheder()
    if len(pe) < 600:
        raise RuntimeError(f'CVR gav kun {len(pe)} tankstations-P-enheder (forventet ~1.200)')
    with open(os.path.join(OUT, 'tankstationer_dk.csv'), encoding='utf-8-sig') as f:
        raekker = list(csv.reader(f))[1:]
    daekket, afvig = 0, []
    for r in raekker:
        la, lo = float(r[5]), float(r[6])
        naer = sorted(((dawa.hav(la, lo, p['lat'], p['lon']), p) for p in pe
                       if abs(p['lat'] - la) < 0.002 and abs(p['lon'] - lo) < 0.004), key=lambda t: t[0])
        naer = [(d, p) for d, p in naer if d <= NAER_M and r[0] in maerker_for(p)]
        if not naer:
            continue
        daekket += 1
        if (r[0], ' '.join(r[2].split(',')[0].lower().split())) in KENDTE:
            continue
        if not any(samme_adresse(r[2], p) for _, p in naer):
            d, p = naer[0]
            afvig.append((r[0], r[1], r[2], f"{p['vej']} {p['husnr']}, {p['postnr']}", round(d), p['navn'], p['pnr']))
    mangler = []
    for p in pe:
        m = MANGLER_EJERE.get(p['ejer'])
        if not m or IKKE_STATION.search(p['navn']) or p['pnr'] in KENDTE_MANGLER:
            continue
        d = min((dawa.hav(p['lat'], p['lon'], float(r[5]), float(r[6])) for r in raekker if r[0] in m),
                default=9e9)
        if d > MANGLER_M:
            mangler.append((p['navn'], f"{p['vej']} {p['husnr']}, {p['postnr']}", round(d), p['pnr']))
    linjer = [f'CVR-tjek af tanklaget koert {time.strftime("%Y-%m-%d %H:%M")} (cvr_tjek.py)',
              f'{len(pe)} aktive P-enheder (branche {BRAENDSTOF} + OK a.m.b.a.) med DAR-punkt.',
              f'{daekket} af {len(raekker)} raekker har en P-enhed fra samme kaede inden for {NAER_M} m; '
              f'{len(afvig)} af dem har en anden adresse end P-enheden.',
              'Rapporten er vejledende: en P-enhed kan staa paa et nabonummer (fx vaskehallen), og',
              'OK-raekker rettes i refresh_data.OK_KILDEFEJL, ikke i CSV\'en.', '']
    for a in sorted(afvig):
        linjer.append(f'  {a[0]:9} {a[1][:30]:30} raekke: {a[2].split(",")[0][:30]:30} '
                      f'CVR: {a[3][:34]:34} {a[4]:3} m  ({a[5][:32]}, P {a[6]})')
    linjer += ['', f'MULIGT MANGLENDE STATIONER: {len(mangler)} P-enheder fra '
                   f'{", ".join(sorted({x for s in MANGLER_EJERE.values() for x in s}))} uden en raekke fra '
                   f'kaeden inden for {MANGLER_M} m.',
               'Kandidater til efterproevning - ikke automatisk tilfoejet. Afgjorte staar i KENDTE_MANGLER.', '']
    for x in sorted(mangler):
        linjer.append(f'  {x[0][:34]:34} {x[1][:36]:36} naermeste egne raekke {x[2]:6} m  (P {x[3]})')
    open(rapport, 'w', encoding='utf-8').write('\n'.join(linjer) + '\n')
    print('\n'.join(linjer[:3]))
    print(f'(rapport gemt i cvr_report.txt: {len(afvig)} afvigelser, {len(mangler)} mulige manglende)')


if __name__ == '__main__':
    sys.exit(main())
