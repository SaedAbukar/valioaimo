// Event-brief parser tests (EN + FI). Run: node tests/js/parser.test.js  (needs ui/src/data.js from `python3 ui/build.py`)
globalThis.window = globalThis;
const fs = require('fs'); const path = require('path'); const assert = require('assert');
const R = path.join(__dirname, '..', '..', 'ui', 'src');
for (const f of ['data.js', 'engine.js', 'flows.js']) eval(fs.readFileSync(path.join(R, f), 'utf8'));
const F = globalThis.AimoFlows, C = globalThis.AimoCore;
(async () => {
  await F.boot(); // demo clock: Fri 13 Nov 2026
  const cases = [
    ['Pikkujoulut lauantaina 21.11. 120 hengelle: kinkku, laatikot, rosolli ja riisipuuro. 6 vegaania, yksi pähkinäallergia.',
      b => { assert.equal(b.lang, 'fi'); assert.equal(b.date, '2026-11-21'); assert.equal(b.guests, 120); assert.equal(b.diet.vegan, 6); assert.equal(b.allergies.nuts, 1); assert.equal(b.eventType, 'christmas_party'); assert.ok(['kinkku', 'lanttulaatikko', 'porkkanalaatikko', 'rosolli', 'riisipuuro'].every(id => b.services[0].dishes.some(d => d.recipeId === id))); }],
    ['Syntymäpäivät ensi perjantaina 40 vieraalle: lohikeitto ja mustikkapiirakka. 3 gluteenitonta, 2 laktoositonta.',
      b => { assert.equal(b.lang, 'fi'); assert.equal(b.date, '2026-11-20'); assert.equal(b.guests, 40); assert.equal(b.diet.gluten_free, 3); assert.equal(b.diet.lactose_free, 2); assert.ok(b.services[0].dishes.some(d => d.recipeId === 'lohikeitto')); assert.ok(b.services[0].dishes.some(d => d.recipeId === 'berry_pie')); }],
    ['Lounas huomenna 25 henkilölle: kanacurry. Yksi vegaani, kaksi kalaallergikkoa.',
      b => { assert.equal(b.date, '2026-11-14'); assert.equal(b.guests, 25); assert.equal(b.diet.vegan, 1); assert.equal(b.allergies.fish, 2); assert.ok(b.services[0].dishes.some(d => d.recipeId === 'chicken_curry')); }],
    [F.GALA,
      b => { assert.equal(b.lang, 'en'); assert.equal(b.date, '2026-11-21'); assert.equal(b.guests, 180); assert.equal(b.diet.vegan, 12); assert.equal(b.diet.gluten_free, 8); assert.equal(b.allergies.nuts, 1); assert.equal(b.services[1].guests, 60); assert.equal(b.services[1].date, '2026-11-22'); }],
    ['Wedding next Saturday for 80 guests: salmon soup, reindeer, blueberry pie. 4 vegetarians, two fish allergies.',
      b => { assert.equal(b.date, '2026-11-21'); assert.equal(b.guests, 80); assert.equal(b.diet.vegetarian, 4); assert.equal(b.allergies.fish, 2); }],
  ];
  let n = 0;
  for (const [text, check] of cases) { check(F.parseBrief(text)); n++; }
  // request parser
  const p = F.parseRequest('I need 1,000 litres of lactose-free milk by Monday.');
  assert.equal(p.lines[0].qty, 1000); assert.equal(p.lines[0].unit, 'L'); assert.equal(p.needBy, '2026-11-16'); n++;
  console.log(`parser tests passed: ${n}`);
})().catch(e => { console.error(e); process.exit(1); });
