#!/usr/bin/env python3
"""Roegtest af kortet (kort_soeg.html) i headless Chrome - omraadeanalysen og resten af panelet. INGEN netkald:
Chrome startes med --host-resolver-rules="MAP * ~NOTFOUND", saa fliser, feed og adressetjeneste ikke naas, og kortet
koerer paa sin indbyggede DATA. Kraever Chrome og node; mangler de, springes testen over (exit 0).

Koer:  python3 tests/e2e_kort.py      (den ugentlige Action koerer den som et trin, der ikke blokerer)
Ikke en del af 'unittest discover': en browser kan vaere langsom eller ustabil paa en runner, og dens fejl skal
ikke stoppe ugens data. Den deterministiske del (analyser() og syntaksen) ligger i tests/test_kort.py.
"""
import json, os, shutil, subprocess, sys, tempfile, time

HER = os.path.dirname(os.path.abspath(__file__))
KORT = os.path.join(os.path.dirname(HER), 'kort_soeg.html')
PORT = 9339


def chrome():
    for p in ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',):
        if os.path.exists(p):
            return p
    for n in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        if shutil.which(n):
            return shutil.which(n)
    return None


def main():
    c, node = chrome(), shutil.which('node')
    if not c or not node:
        print(f'SPRUNGET OVER: {"Chrome" if not c else "node"} findes ikke')
        return 0
    profil = tempfile.mkdtemp(prefix='e2e_kort_')
    proc = subprocess.Popen([c, '--headless=new', f'--remote-debugging-port={PORT}', f'--user-data-dir={profil}',
                             '--host-resolver-rules=MAP * ~NOTFOUND', '--no-first-run', '--no-default-browser-check',
                             '--disable-extensions', '--disable-background-networking', '--disable-component-update',
                             '--disable-sync', '--no-sandbox', 'about:blank'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        p = subprocess.run([node, os.path.join(HER, 'e2e_kort.js'), KORT, str(PORT)], capture_output=True, text=True,
                           timeout=180)
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profil, ignore_errors=True)
    try:
        r = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print('FEJL: intet svar fra testen\n' + p.stdout[-2000:] + p.stderr[-2000:])
        return 1
    fejl = []
    if 'e2e_fejl' in r:
        fejl.append(r['e2e_fejl'])
    else:
        if r['js_fejl']:
            fejl.append(f'JavaScript-fejl: {r["js_fejl"][:3]}')
        for navn in ('desktop', 'mobil'):
            x = r[navn]
            krav = {'8 kategorier': x['kategorier'] == 8, 'panelet lukker ved vaelg (mobil)': x['panel_lukket_ved_vaelg'],
                    'tryk gaar gennem klyngen': x['tryk_gennem_klynge'] is True, '8 lag i analysen': x['lag'] == 8,
                    # en klynges ikon staar i klyngens midtpunkt, saa 2 km om det kan vaere tomt; 10 km er det ikke
                    'punkter inden for 10 km': int((x['radius_tekst'] or '0').split()[0].replace('.', '')) > 0,
                    'cirkel tegnet': x['cirkel'] >= 1,
                    'panelet aabner efter (mobil)': x['panel_aaben_efter'], 'popup for manglende kaede': 'Nærmeste' in x['popup'],
                    'ny radius vises': '10 km' in (x['radius_tekst'] or ''), 'hele cirklen kan ses': x['cirkel_synlig'],
                    'Ryd fjerner alt': x['efter_ryd'] == [0, 0]}
            fejl += [f'{navn}: {k}' for k, ok in krav.items() if not ok]
    print(json.dumps(r, ensure_ascii=False, indent=1)[:3000])
    print('OK' if not fejl else 'FEJL:\n  - ' + '\n  - '.join(fejl))
    return 1 if fejl else 0


if __name__ == '__main__':
    sys.exit(main())
