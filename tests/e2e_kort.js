// Roegtest af kortet i headless Chrome via DevTools-protokollen (node 22: global WebSocket). Koeres af
// tests/e2e_kort.py, som starter Chrome med --host-resolver-rules="MAP * ~NOTFOUND": INGEN netkald (fliser,
// feed og adressetjeneste svarer ikke), saa kortet koerer paa sin indbyggede DATA. Udskriver JSON.
const [fil, port] = [process.argv[2], +process.argv[3]];
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let liste;
  for (let i = 0; i < 80; i++) { try { liste = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); break; } catch (e) { await sleep(250); } }
  const side = liste.find(x => x.type === 'page');
  const ws = new WebSocket(side.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0; const vent = {}, fejl = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && vent[m.id]) { vent[m.id](m); delete vent[m.id]; }
    if (m.method === 'Runtime.exceptionThrown') fejl.push(String((m.params.exceptionDetails.exception || {}).description || m.params.exceptionDetails.text));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') fejl.push('console.error: ' + m.params.args.map(a => a.value || a.description).join(' '));
  };
  const kald = (method, params = {}) => new Promise(r => { const i = ++id; vent[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async expr => (await kald('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result.result.value;
  await kald('Runtime.enable'); await kald('Page.enable');
  async function koer(navn, bredde, hoejde) {
    await kald('Emulation.setDeviceMetricsOverride', { width: bredde, height: hoejde, deviceScaleFactor: 1, mobile: bredde < 800 });
    await kald('Page.navigate', { url: 'file://' + fil });
    for (let i = 0; i < 60; i++) { await sleep(250); if (await ev("document.querySelectorAll('#cats .cat-row').length") > 0) break; }
    const r = { navn };
    r.kategorier = await ev("document.querySelectorAll('#cats .cat-row').length");
    if (bredde < 800) await ev("document.getElementById('panel').classList.add('open')");
    if (bredde < 800) await sleep(500);                 // som en bruger: panelet er aabent og tegnet
    await ev("document.getElementById('ana-klik').click()");
    r.panel_lukket_ved_vaelg = bredde < 800 ? await ev("!document.getElementById('panel').classList.contains('open')") : true;
    // vent, til panelet faktisk er gledet ud (transition .2s), foer der maales og klikkes (review 15-10-2026)
    for (let i = 0; bredde < 800 && i < 40; i++) { if (await ev("document.getElementById('panel').getBoundingClientRect().right <= 1")) break; await sleep(50); }
    // Et tryk paa en klynge i vaelg-tilstand skal gaa igennem til kortet (pointer-events: none paa naale/klynger)
    const pkt = await ev(`(() => { const m = document.getElementById('map').getBoundingClientRect();
      const ikon = [...document.querySelectorAll('.leaflet-marker-icon')].map(e => e.getBoundingClientRect())
        .find(b => b.width > 0 && b.left > m.left + 30 && b.right < m.right - 30 && b.top > m.top + 30 && b.bottom < m.bottom - 30);
      if (!ikon) return null; const x = ikon.left + ikon.width / 2, y = ikon.top + ikon.height / 2;
      const el = document.elementFromPoint(x, y); return { x, y, gennem: !!el.closest('#map') && !el.closest('.leaflet-marker-icon') }; })()`);
    r.tryk_gennem_klynge = pkt ? pkt.gennem : 'ingen klynge i synsfeltet';
    await ev(`(() => { const x = ${pkt ? pkt.x : 0}, y = ${pkt ? pkt.y : 0};
      const el = document.elementFromPoint(x, y);
      for (const t of ['mousedown', 'mouseup', 'click']) el.dispatchEvent(new MouseEvent(t, { clientX: x, clientY: y, bubbles: true, button: 0 }));
      return true; })()`);
    await sleep(900);
    r.lag = await ev("document.querySelectorAll('#ana .ana-lag').length");
    r.i_omraadet = await ev("[...document.querySelectorAll('#ana .ana-lag h5 .n')].map(e => parseInt(e.textContent)).reduce((a, b) => a + b, 0)");
    r.mangler = await ev("document.querySelectorAll('#ana .ana-m').length");
    r.cirkel = await ev("document.querySelectorAll('.leaflet-overlay-pane path').length");
    r.panel_aaben_efter = bredde < 800 ? await ev("document.getElementById('panel').classList.contains('open')") : true;
    // Klik paa en manglende kaede: en popup med 'Naermeste' (ogsaa naar laget er slukket)
    await ev("(document.querySelector('#ana .ana-m') || {click(){}}).click()");
    await sleep(900);
    r.popup = await ev("(document.querySelector('.leaflet-popup-content') || {}).textContent || ''");
    // Ny radius: hele cirklen skal kunne ses
    if (bredde < 800) await ev("document.getElementById('panel').classList.add('open')");
    await ev("(() => { const s = document.getElementById('ana-r'); s.value = '10'; s.dispatchEvent(new Event('change')); return true; })()");
    await sleep(1200);
    r.radius_tekst = await ev("(document.querySelector('#ana .ana-lag h5 .n') || {}).textContent");
    // Undersoegelse 15-10-2026: kun kendte linjer i 'Til stede'-delen; i pladskraevende kun hvidlistede kaeder under
    // Mangler; aldrig et bilmaerke eller samlenavn under Mangler; og ingen vandret overloeb (mobil 390 px).
    r.linjer = await ev(`[...new Set([...document.querySelectorAll('#ana .ana-lag .til')].map(e => (e.textContent.match(/^([^:]+):/) || [])[1]).filter(Boolean))]`);
    r.plads_mangler_uden_for_hvidliste = await ev(`(() => { const lag = [...document.querySelectorAll('#ana .ana-lag')].find(e => e.querySelector('h5').textContent.includes('Pladskrævende'));
      return lag ? [...lag.querySelectorAll('.ana-m')].map(e => e.dataset.kaede).filter(n => !ANA_KAN_MANGLE_LAG.plads.includes(n)) : null; })()`);
    // samlenavne i alle lag; bilmaerker kun i pladskraevende (Tesla er ogsaa en ladeoperatoer og maa mangle dér)
    r.bil_eller_samle_under_mangler = await ev(`(() => { const samle = new Set(ANA_GENERISK.map(anaNorm)), bil = new Set(ANA_GENERISK_LAG.plads.map(anaNorm));
      return [...document.querySelectorAll('#ana .ana-lag')].flatMap(lag => { const plads = lag.querySelector('h5').textContent.includes('Pladskrævende');
        return [...lag.querySelectorAll('.ana-m')].map(e => e.dataset.kaede).filter(n => samle.has(anaNorm(n)) || (plads && bil.has(anaNorm(n)))); }); })()`);
    // Brugerens valg 20-10-2026: en kaede paa lagets ANA_IKKE_AJOUR_LAG staar aldrig under Mangler (laget findes ud fra
    // overskriftens tekst uden de to span'er, saa 'Superladere' og 'Lastbil-ladere' ikke blandes sammen).
    r.ikke_ajour_under_mangler = await ev(`(() => { const lab = {}; for (const k in DATA) lab[DATA[k].label] = k;
      return [...document.querySelectorAll('#ana .ana-lag')].flatMap(lag => { const h5 = lag.querySelector('h5');
        const k = lab[[...h5.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim()];
        if (!k) return ['ukendt lag: ' + h5.textContent];
        return [...lag.querySelectorAll('.ana-m')].map(e => e.dataset.kaede).filter(n => (ANA_IKKE_AJOUR_LAG[k] || []).includes(n)); }); })()`);
    r.overloeb = await ev("(() => { const a = document.getElementById('ana'); return a.scrollWidth - a.clientWidth; })()");
    // Review 15-10-2026: hvert navn i 'Til stede'-delen staar paa den linje, dets g giver, og tallene (ogsaa de skjulte)
    // summerer til tallet i overskriften - en linje, der forsvinder eller samler alt, fejler her. (Regex uden
    // backslash: i en template-streng ville '\d' blive til 'd'.)
    r.linje_fejl = await ev(`(() => { const samle = new Set(ANA_GENERISK.map(anaNorm)), bil = new Set(ANA_GENERISK_LAG.plads.map(anaNorm)), f = [];
      for (const lag of document.querySelectorAll('#ana .ana-lag')) {
        const h5 = lag.querySelector('h5'), n = parseInt(h5.querySelector('.n').textContent.replace(/[.]/g, ''), 10);
        const plads = h5.textContent.includes('Pladskrævende'); let sum = 0;
        for (const til of lag.querySelectorAll('.til')) {
          const t = (til.textContent.match(/^([^:]+):/) || [])[1]; if (!t) continue;
          for (const s of til.querySelectorAll(':scope > span')) {
            const m = s.textContent.replace(/^ · /, '').match(/^(.*) ([0-9]+)$/); if (!m) { f.push('uparset: ' + s.textContent); continue; }
            sum += +m[2];
            const forv = samle.has(anaNorm(m[1])) ? 'Samlebetegnelser' : plads && bil.has(anaNorm(m[1])) ? 'Under bilmærke' : 'Til stede';
            if (t !== forv) f.push(m[1] + ' under ' + t);
          }
        }
        if (sum !== n) f.push(h5.textContent + ': sum ' + sum);
      }
      return f; })()`);
    r.cirkel_synlig = await ev(`(() => { const p = [...document.querySelectorAll('.leaflet-overlay-pane path')].map(e => e.getBoundingClientRect())
      .sort((a, b) => b.width - a.width)[0]; const m = document.getElementById('map').getBoundingClientRect();
      return !!p && p.width > 50 && p.left >= m.left - 2 && p.right <= m.right + 2 && p.top >= m.top - 2 && p.bottom <= m.bottom + 2; })()`);
    await ev("document.getElementById('ana-ryd').click()");
    await sleep(150);
    r.efter_ryd = [await ev("document.querySelectorAll('#ana .ana-lag').length"), await ev("document.querySelectorAll('.leaflet-overlay-pane path').length")];
    return r;
  }
  const ud = { desktop: await koer('desktop', 1280, 900), mobil: await koer('mobil', 390, 844), js_fejl: fejl };
  console.log(JSON.stringify(ud));
  ws.close(); process.exit(0);
})().catch(e => { console.log(JSON.stringify({ e2e_fejl: String(e) })); process.exit(1); });
