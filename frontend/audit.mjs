/* Walk every page, every tab, every interactive control, and report what each
   actually rendered. Testing nav links only is what let empty tabs ship. */
const t = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const ws = new WebSocket(t.find((x) => x.type === "page").webSocketDebuggerUrl);
let id = 0; const results = new Map(); let errors = [];
await new Promise((r) => (ws.onopen = r));
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.exception?.description?.split("\n")[0]);
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push("console: " + m.params.args.map(a=>a.value??a.description).join(" "));
  if (m.id && m.result?.result?.value !== undefined) results.set(m.id, m.result.result.value);
};
const ev = async (expression, wait = 900) => {
  const i = ++id;
  ws.send(JSON.stringify({ id: i, method: "Runtime.evaluate", params: { expression, returnByValue: true } }));
  await new Promise((r) => setTimeout(r, wait));
  return results.get(i);
};
const go = async (path, wait = 6000) => {
  errors = [];
  ws.send(JSON.stringify({ id: ++id, method: "Page.navigate", params: { url: "http://127.0.0.1:18090" + path } }));
  await new Promise((r) => setTimeout(r, wait));
};
const stats = async () => ev(`({
  text: document.querySelector('main').innerText.length,
  svgs: document.querySelectorAll('main svg').length,
  rows: document.querySelectorAll('main table tbody tr').length,
  imgs: [...document.querySelectorAll('main img')].filter(i=>i.naturalWidth>0).length,
  err: document.body.innerText.includes('hit an error'),
})`);

ws.send(JSON.stringify({ id: ++id, method: "Runtime.enable" }));

const PAGES = ["/", "/league", "/teams", "/teams/7", "/players", "/players/36",
               "/games", "/games/1361", "/research", "/model", "/nonsense"];
console.log("PAGE".padEnd(16), "chars  svgs  rows  imgs  status");
for (const path of PAGES) {
  await go(path);
  const s = await stats();
  const bad = s.err ? "ERROR BOUNDARY" : errors.length ? "JS: " + errors[0].slice(0,50) : "ok";
  console.log(path.padEnd(16), String(s.text).padStart(5), String(s.svgs).padStart(5), String(s.rows).padStart(5), String(s.imgs).padStart(5), " ", bad);
}

console.log("\nGAME PANEL TABS (scoreboard, first game)");
await go("/");
await ev(`document.querySelector('article.panel button').click()`, 2500);
for (const label of ["Team lines","Player props","Shot charts","Shot defense","Box score","Score flow"]) {
  errors = [];
  await ev(`[...document.querySelectorAll('button.control')].find(b=>b.textContent.trim()===${JSON.stringify(label)}).click()`, 3200);
  const s = await stats();
  console.log("  " + label.padEnd(14), String(s.text).padStart(5), String(s.svgs).padStart(5), String(s.rows).padStart(5), " ", errors.length ? "JS: "+errors[0].slice(0,50) : "ok");
}

console.log("\nCONTROLS");
await go("/players");
await ev(`(()=>{const i=document.querySelector('input[type=search]'); const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set; set.call(i,'clark'); i.dispatchEvent(new Event('input',{bubbles:true}));})()`, 2500);
console.log("  player search 'clark' rows:", (await stats()).rows, errors.length ? "JS: "+errors[0] : "ok");
await go("/league");
await ev(`(()=>{const s=document.querySelector('select'); s.value='2025'; s.dispatchEvent(new Event('change',{bubbles:true}));})()`, 4000);
console.log("  league season -> 2025:", (await stats()).rows, "rows", errors.length ? "JS: "+errors[0] : "ok");
ws.close();
