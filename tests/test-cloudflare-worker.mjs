import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../cloudflare/btc-sol-futures-test.js';

const originalFetch = globalThis.fetch;
const originalDateNow = Date.now;
const fixedNow = Date.UTC(2026, 9, 17, 0, 7, 0);
const periodSeconds = { '1hour': 3600, '4hour': 14400, daily: 86400 };
const symbols = ['BTCUSDT_PERP.A', 'SOLUSDT_PERP.A'];
let seenRequests = [];
let stale = false;

function makeHistory(interval) {
  const seconds = periodSeconds[interval];
  const currentStart = Math.floor(fixedNow / 1000 / seconds) * seconds;
  return Array.from({length: 260}, (_, i) => {
    const t = currentStart - (260 - i) * seconds;
    const open = 100 + i / 10;
    return {t, o:open, h:open + 1.2, l:open - 1.2,
            c:open + .4, v: 2000 + i};
  });
}
function mockProvider(url, init) {
  const link = new URL(url);
  seenRequests.push({url:link, init});
  const interval = link.searchParams.get('interval');
  const history = makeHistory(interval);
  if (stale) history.pop();
  return Promise.resolve(Response.json(symbols.map(symbol => ({symbol, history}))));
}
async function get(path, env = {COINALYZE_API_KEY:'SENTINEL_TEST_SECRET'}) {
  return worker.fetch(new Request('https://btc-sol-futures-test.example'+path), env);
}

test.beforeEach(() => {
  Date.now = () => fixedNow;
  seenRequests = [];
  stale = false;
  globalThis.fetch = mockProvider;
});
test.after(() => {
  globalThis.fetch = originalFetch;
  Date.now = originalDateNow;
});

test('history provides 260 closed, ascending, correctly-aligned candles without secrets', async () => {
  for (const interval of Object.keys(periodSeconds)) {
    const response = await get('/history?interval='+interval);
    assert.equal(response.status, 200);
    const data = await response.json();
    assert.deepEqual(data.map(x=>x.symbol),symbols);
    assert.equal(data[0].history.length,260);
    const series = data[0].history;
    const seconds = periodSeconds[interval];
    const currentStart = Math.floor(fixedNow / 1000 / seconds) * seconds;
    assert.equal(series.at(-1).t + seconds,currentStart);
    assert.ok(series.every((bar,i) => i===0||bar.t-series[i-1].t===seconds));
    assert.ok(!JSON.stringify(data).includes('SENTINEL_TEST_SECRET'));
  }
});
test('original endpoint retains exact six READY groups and indicators', async () => {
  const response = await get('/');
  assert.equal(response.status,200);
  const data = await response.json();
  assert.equal(data.ok,true);
  assert.deepEqual(Object.keys(data),['ok','provider','exchange','market','checkedAtUTC','results']);
  assert.equal(data.results.length,6);
  assert.ok(data.results.every(x=>x.status==='READY'));
  assert.ok(data.results.every(x=>Number.isFinite(x.indicators.RSI14)));
});
test('bad interval is rejected without calling the provider', async () => {
  const response = await get('/history?interval=15min');
  assert.equal(response.status,400);
  assert.equal(seenRequests.length,0);
});
test('incomplete closed history is refused', async () => {
  stale=true;
  const response = await get('/history?interval=4hour');
  assert.equal(response.status,503);
  const data = await response.json();
  assert.equal(data.ok,false);
});
test('API secret stays out of request query and response', async () => {
  const response = await get('/history?interval=1hour');
  assert.equal(response.status,200);
  assert.equal(seenRequests[0].init.headers.api_key,'SENTINEL_TEST_SECRET');
  assert.ok(!seenRequests[0].url.toString().includes('SENTINEL_TEST_SECRET'));
  assert.ok(!JSON.stringify(await response.json()).includes('SENTINEL_TEST_SECRET'));
});
