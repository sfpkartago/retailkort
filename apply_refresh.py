#!/usr/bin/env python3
"""
apply_refresh.py — det verificerede ændringssæt fra refresh'et 2026-09-08.
v2 (efter adversariel revision): tre af v1's beslutninger var forkerte og er rettet.
Hvert punkt er begrundet i REFRESH_LOG.md. Idempotent.

Kør:  python3 refresh_data.py && python3 apply_refresh.py && python3 validate.py && python3 rebuild.py
"""
import csv, os
from dawa import normalize_one

OUT = os.path.dirname(os.path.abspath(__file__))
log = []


def read(fn):
    with open(os.path.join(OUT, fn), encoding='utf-8-sig') as f:
        r = list(csv.reader(f)); return r[0], r[1:]


def write(fn, head, rows):
    rows.sort(key=lambda x: (x[0], str(x[3])))
    with open(os.path.join(OUT, fn), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(head); w.writerows(rows)


def L(m):
    log.append(m); print(m)


def setnum(rows, brand, name, kw=None, cnt=None, coord=None):
    for r in rows:
        if r[0] == brand and r[1] == name:
            before = f"{r[5]}kW/{r[7]}"
            if kw: r[5] = kw
            if cnt: r[7] = cnt
            if coord: r[8], r[9] = coord
            if before != f"{r[5]}kW/{r[7]}":
                L(f"~ {brand:8} {name[:34]:36} {before} -> {r[5]}kW/{r[7]}")
            return True
    return False


# ============================================================ superladere
head, rows = read('superladere_dk.csv')
n0 = len(rows)

# --- 1) Clever: ægte nye anlæg -------------------------------------------------
# 'Veri Centret' blev AFVIST i v1 som roaming-dublet af Eviny's 'VERI Center' 37 m
# væk. Det var forkert: OSM har to separate anlæg på grunden — en Clever-node
# (brand=Clever, capacity=10, 300 kW) og en Eviny-way (capacity=8, 360 kW) ~40 m
# derfra. Clever-anlægget har sine egne 5 alpitronic-standere (chargePointIds
# 15464-15468) og roamingAgreement=null. Forskelligt hardware, effekt og antal.
CLEVER_NEW = [
    ('Odsherred Musikskole - Asnæs', 'Centervejen 4A',   '300', '2',  55.81128,  11.502479),
    ('Veri Centret',                 'Frijsenborgvej 5', '300', '10', 56.189604, 10.214744),
]
for name, street, kw, cnt, lat, lon in CLEVER_NEW:
    if any(r[0] == 'Clever' and r[1] == name for r in rows):
        continue
    adr, pn, by = normalize_one(street, '', '', lat, lon)
    if not pn:
        raise SystemExit(f"AFBRYDER: DAWA kunne ikke normalisere '{street}' — kør igen")
    rows.append(['Clever', name, adr, pn, by, kw, 'CCS', cnt, str(lat), str(lon)])
    L(f"+ Clever   {name[:34]:36} {adr}   {kw} kW / {cnt} ladere")

# --- 2) Clever: antal/koordinat iflg. Clevers eget API -------------------------
setnum(rows, 'Clever', 'Bilka - Odense Øst', cnt='2', coord=('55.378059', '10.433246'))
setnum(rows, 'Clever', 'Føtex Food - Dragør', cnt='6')

# --- 3) Ionity: effekt+antal regnet ud af mapdata's stik-trin ------------------
for name, kw, cnt in [('IONITY Aarup', '400', '6'), ('IONITY Billund', '350', '8'),
                      ('IONITY Korsør', '400', '24'), ('IONITY Nørresundby', '400', '6'),
                      ('IONITY Ringsted', '400', '6'), ('IONITY Struer', '400', '6')]:
    setnum(rows, 'Ionity', name, kw=kw, cnt=cnt)

# --- 4) OK: nye anlæg fra locations/nearby ------------------------------------
# Antal = kun Ccs-spots. v1 satte Årslev til 6 = ALLE spots, men de to sidste er
# langsomme Type2-AC-stik (DK*OKO*EY8LB…/EYZABRM…) — i strid med >=250 kW-reglen.
OK_NEW = [
    ('OK Brøndby Strand, Gammel Køge Landevej', 'Gammel Køge Landevej 722', '400', '8',  55.618366, 12.418056),
    ('OK Helsingør, Esrumvej',                  'Esrumvej 90',              '400', '2',  56.040855, 12.586894),
    ('OK Odden, Oddenvej',                      'Oddenvej 217',             '300', '6',  55.966763, 11.364389),
    ('OK Sønderborg, Grundtvigs Plads',         'Grundtvigs Plads 14',      '300', '6',  54.922135,  9.810431),
    ('OK Valby, Julius Andersens Vej. DC',      'Julius Andersens Vej 3A',  '400', '16', 55.650137, 12.517716),
    ('OK Århus, Årslev, Logistikparken',        'Logistikparken 12',        '400', '4',  56.158715, 10.068036),
]
for name, street, kw, cnt, lat, lon in OK_NEW:
    if any(r[0] == 'OK' and r[1] == name for r in rows):
        continue
    adr, pn, by = normalize_one(street, '', '', lat, lon)
    if not pn:
        raise SystemExit(f"AFBRYDER: DAWA kunne ikke normalisere '{street}' — kør igen")
    rows.append(['OK', name, adr, pn, by, kw, 'CCS', cnt, str(lat), str(lon)])
    L(f"+ OK       {name[:34]:36} {adr}   {kw} kW / {cnt} ladere")

# --- 5) OK: Antal_ladere talte langsomme stik med (pre-eksisterende fejl) ------
# Fem anlæg havde et 100 kW CHAdeMO-stik tælt med som lynlader; Støvring var
# omvendt sat for lavt. Tal verificeret mod clusters/search (kun 'Ccs'-spots).
for name, cnt in [('OK Karlslunde V, Køge Bugt Motorvejen', '14'),
                  ('OK Karlslunde Ø, Køge Bugt Motorvejen', '14'),
                  ('OK Skærup Øst, Østjyske Motorvej', '10'),
                  ('OK Ejer Bavnehøj V. Østjysk Motorvej', '8'),
                  ('OK Ejer Bavnehøj Ø. Østjysk Motorvej', '8'),
                  ('OK Støvring, Juelstrupparken', '6')]:
    if not setnum(rows, 'OK', name, cnt=cnt):
        L(f"! advarsel: fandt ikke OK-rækken '{name}'")

# --- 5b) E.ON: samme fejltype som OK-rækkerne (pre-eksisterende) ---------------
# edri's eget stations-API (www.edri.com/api/stations) giver effekt pr. EVSE. 64 af
# de 68 E.ON-rækker tæller korrekt kun EVSE'er >=250 kW; disse fire tæller alle med,
# ned til 22 kW AC. Tal verificeret mod API'et (koordinat-match 0-3 m).
for name, cnt in [('Rødovre Centrum', '6'),                  # 70 EVSE'er, 6 x 300 kW
                  ('Harte Syd', '6'),                        # 6 x 400 + 110/62,5/22
                  ('Harte Nord', '6'),                       # 6 x 400 + 2 x 150
                  ('OmtankestationTM Frederikshavn', '10')]:  # 10 x 300 + 1 x 150
    if not setnum(rows, 'E.ON', name, cnt=cnt):
        L(f"! advarsel: fandt ikke E.ON-rækken '{name}'")

# --- 5c) OK Vordingborg: adressen tilhørte et andet anlæg ----------------------
# Rækken stod med "Højgaardsvej 13" — det er IONITY's adresse 308 m væk. Anlægget
# ligger på nr. 3A (DAWA-reverse på rækkens egen koordinat, 23 m). dawa.py v2.2's
# nye trin-2-gate fanger den nu automatisk, men rækken er ikke i det normaliserede
# sæt (kun OK-TANK og Tesla normaliseres), så den rettes her.
for r in rows:
    if r[0] == 'OK' and 'Vordingborg' in r[1] and r[2].startswith('Højgaardsvej 13'):
        adr, pn, by = normalize_one(r[2], r[3], r[4], r[8], r[9])
        if adr != r[2]:
            L(f"~ OK       {r[1][:34]:36} {r[2]} -> {adr}")
            r[2], r[3], r[4] = adr, pn, by

# --- afviste kandidater, tjekket enkeltvis ------------------------------------
L("x OK       Aarhus N, Katrinebjergvej — afvist: samme anlæg som 'Stella Aarhus' "
  "(Katrinebjergvej 58, 4 CCS-stik, 34 m)")
L("x OK       Aarslev, Logistikparken E-truck — afvist: lastbil-lader (designregel)")
L("x OK       Truck Korsør, Storebæltsvej (1000 kW) — afvist: lastbil-megawattlader, "
  "over validate.py's 500 kW-grænse")
L("x Ionity   Aalborg Skalborg + Odense Åsumvej — afvist: state='planned', 0 stik")

write('superladere_dk.csv', head, rows)
L(f"  superladere_dk.csv: {n0} -> {len(rows)} rækker")

# ============================================================ tankstationer
head, rows = read('tankstationer_dk.csv')
n0 = len(rows)

# --- 6) tilgang fra Go'on-kortet ----------------------------------------------
for brand, name, street, lat, lon in [
        ("Go'on", "Go'on Stenderup-Krogager", 'Storegade 30', 55.699, 8.842259),
        ('Lavpris', 'Lavpris Svankjær', 'Hedegårdsvej 24A', 56.845515, 8.364075)]:
    if any(r[0] == brand and r[1] == name for r in rows):
        continue
    adr, pn, by = normalize_one(street, '', '', lat, lon)
    if not pn:
        raise SystemExit(f"AFBRYDER: DAWA kunne ikke normalisere '{street}' — kør igen")
    rows.append([brand, name, adr, pn, by, str(lat), str(lon)])
    L(f"+ {brand:8} {name[:34]:36} {adr}")

# --- 7) Shell: ægte manglende station ----------------------------------------
# Shell stempler den med nabo-anlæggets koordinat (Hovedgaden 482, 2 m derfra),
# men Roskildevej 335 ligger 1,2 km væk og OSM har en Shell-tankstation 6 m fra
# netop den adresse. Derfor DAWA's koordinat for Roskildevej 335.
if not any(r[0] == 'Shell' and 'ROSKILDEVEJ' in r[1].upper() and r[3] == '2640' for r in rows):
    adr, pn, by = normalize_one('Roskildevej 335', '', '', 55.650971, 12.221417)
    if not pn:
        raise SystemExit("AFBRYDER: DAWA kunne ikke normalisere Roskildevej 335 — kør igen")
    rows.append(['Shell', 'SHELL HEDEHUSENE ROSKILDEVEJ', adr, pn, by, '55.650971', '12.221417'])
    L(f"+ Shell    SHELL HEDEHUSENE ROSKILDEVEJ    {adr}   (koordinat fra DAWA, bekræftet i OSM)")

# --- 8) dubletter: kilden har hver station én gang ----------------------------
for brand, name, street in [("Go'on", "Go'on Billum", 'Vesterhavsvej 40B'),
                            ('Lavpris', 'Lavpris Benzin - Merko Koldby', 'Svinget 2B')]:
    for r in [x for x in rows if x[0] == brand and x[1] == name and x[2].startswith(street)]:
        rows.remove(r)
        L(f"- {brand:8} {name[:34]:36} {r[2][:40]}   (dublet)")

# --- 9) kategori-renhed: ren-EV-anlæg hører ikke i tank-datasættet -------------
# Circle K klassificerer selv præcis 8 danske anlæg som siteType='EV'. Kriteriet er
# siteType='EV' — IKKE 'tom brændstofliste': tre af de otte har fuels=['EL Ladestander'],
# og to ST-anlæg (Billund Lufthavn, Truck Home Contino) har faktisk tom liste uden at
# være EV-anlæg. Seks af de otte lå her (fire som kryds-lags-dublet med superladere).
# 'EV HOVEDKONTOR' findes slet ikke blandt Circle K's 443 stationer.
# Shell fører 'RECHARGE AALBORG ØST' med fuels=['shell_recharge'] og logoet
# destination-charging-ev — ingen benzin/diesel.
#
# v1 fjernede DERUDOVER 'CIRCLE K RECHARGE CITY'. Det var FORKERT: Circle K fører
# den som siteType='ST' med miles 95, miles Diesel, miles+ 95, miles+ Diesel,
# HVO100 og AdBlue, med live literpriser. Den er en tankstation MED ladehub og
# bliver stående. Den fejl er rettet i v2.
EV_ONLY = ['CIRCLE K EV HOVEDKONTOR', 'CIRCLE K EV TAXA 4X35', 'CIRCLE K EV HILLERØD',
           'CIRCLE K EV TAPPERNØJE VEST', 'CIRCLE K EV VTS VOJENS',
           'CIRCLE K EV EJER BAUNEHØJ VEST', 'CIRCLE K EV EJER BAVNEHØJ',
           'SHELL RECHARGE AALBORG ØST']
for name in EV_ONLY:
    hit = [r for r in rows if r[1].upper() == name]
    if not hit:
        L(f"  (allerede fjernet: {name})")
    for r in hit:
        rows.remove(r)
        L(f"- {r[0]:8} {r[1][:34]:36} {r[2][:40]}   (ren EV-lokation)")
# Bind vagten til mærke OG fuldt navn: substringen 'RECHARGE CITY' matches også af
# Shells reelle 'Shell Truck Recharge City' på Kai Lindbergs Vej 12 samme sted, så en
# løs test kunne blive opfyldt af Shell-rækken alene. Og SystemExit frem for assert —
# assert fjernes af python3 -O.
if not any(r[0] == 'Circle K' and r[1].upper() == 'CIRCLE K RECHARGE CITY' for r in rows):
    raise SystemExit("AFBRYDER: CIRCLE K RECHARGE CITY skal BLIVE i tank — Circle K fører "
                     "den som siteType=ST med miles 95/Diesel + HVO100")
L("= Circle K CIRCLE K RECHARGE CITY bevaret: siteType=ST, sælger miles 95/Diesel + HVO100")

write('tankstationer_dk.csv', head, rows)
L(f"  tankstationer_dk.csv: {n0} -> {len(rows)} rækker")

# ============================================================ fastfood
head, rows = read('fastfood_kaeder_dk.csv')
n0 = len(rows)

# Burger King Taastrup: koordinaten laa 465 m fra raekkens egen adresse
# (Helgeshøj Alle 32B) — inde i kontorparken ved Hveen Boulevard, hvor der slet
# ingen fast food er (Overpass: 0 fast_food inden for 250 m). Adressen er rigtig,
# koordinaten var forkert; vi bruger DAWA's punkt for adressen.
# Praeeksisterende fejl — laa ogsaa i baseline. validate.py er blind for den, fordi
# dens forskydnings-tjek kun slaar til naar reverse-VEJNAVNET afviger, og her er
# begge "Helgeshøj Alle".
for r in rows:
    if r[0] == 'Burger King' and r[1] == 'Taastrup' and r[5].startswith('55.6572'):
        L(f"~ Burger King Taastrup: koordinat ({r[5]},{r[6]}) -> (55.661250,12.283589)  "
          f"— laa 465 m fra Helgeshøj Alle 32B")
        r[5], r[6] = '55.66125', '12.283589'

write('fastfood_kaeder_dk.csv', head, rows)
L(f"  fastfood_kaeder_dk.csv: {n0} -> {len(rows)} rækker")

open(os.path.join(OUT, 'refresh_apply_log.txt'), 'w', encoding='utf-8').write("\n".join(log) + "\n")
print("\n(log gemt i refresh_apply_log.txt)")
