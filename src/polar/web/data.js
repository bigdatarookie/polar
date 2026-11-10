// Adapted from selected data.js: only supplied retained observations, no fixture.
'use strict';
const GRANULARITIES = ['1D', '1W', '1M'];
const numberOrNull = value => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
function bucketKey(time, interval) {
  const day = time.slice(0, 10);
  if (interval === '1D') return day;
  if (interval === '1M') return day.slice(0, 7);
  const monday = new Date(day + 'T00:00:00Z');
  monday.setUTCDate(monday.getUTCDate() - (monday.getUTCDay() + 6) % 7);
  return monday.toISOString().slice(0, 10);
}
function validOHLC(bar) {
  return bar?.price_status === 'OBSERVED' && ['open', 'high', 'low', 'close'].every(k => numberOrNull(bar[k]) > 0);
}
function buildView(dataset, report, interval) {
  if (!GRANULARITIES.includes(interval)) throw new Error('UNSUPPORTED_INTERVAL');
  const groups = [], bySession = new Map(dataset.bars.map(b => [b.session_id, b]));
  const nav = new Map((report?.nav || []).map(n => [n.session_id, n]));
  for (const session of dataset.sessions) {
    const key = bucketKey(session.open_at, interval);
    if (groups.at(-1)?.key !== key) groups.push({key, sessions: []});
    groups.at(-1).sessions.push(session);
  }
  const bars = [], equity = [];
  for (const {sessions} of groups) {
    const rows = sessions.map(s => bySession.get(s.session_id)), usable = rows.filter(validOHLC);
    const complete = usable.length === sessions.length;
    const extrema = key => usable.reduce((winner, row) => winner === null ||
      (key === 'high' ? Number(decimalDelta(row[key], winner)) > 0 : Number(decimalDelta(row[key], winner)) < 0) ? row[key] : winner, null);
    const bar = {time: sessions[0].open_at, endTime: sessions.at(-1).close_at,
      sessionIds: sessions.map(s => s.session_id), open: complete ? usable[0].open : null,
      high: complete ? extrema('high') : null, low: complete ? extrema('low') : null,
      close: complete ? usable.at(-1).close : null, price_status: complete ? 'OBSERVED' : 'INCOMPLETE',
      originalStatuses: rows.map(r => r?.price_status || 'ABSENT'),
      coverage: {observed: usable.length, supplied: sessions.length, calendar: 'NOT_ASSERTED'}};
    bars.push(bar);
    // Last supplied session only, never forward-filled or interpolated.
    const n = nav.get(sessions.at(-1).session_id);
    equity.push({time: bar.time, value: n?.nav ?? null, at: n?.at ?? null,
      cash: n?.cash ?? null, shares: n?.shares ?? null, status: n?.status ?? 'UNAVAILABLE'});
  }
  const first = dataset.sessions.map(s => bySession.get(s.session_id)).find(validOHLC);
  const sma = bars.map((bar, i) => {
    const window = bars.slice(i - 19, i + 1);
    return {time: bar.time, value: i >= 19 && window.every(b => b.price_status === 'OBSERVED') ?
      window.reduce((s, b) => s + Number(b.close), 0) / 20 : null};
  });
  const markers = (report?.fills || []).map((fill, index) => ({...fill, presentationIndex: index,
    plotIndex: bars.findIndex(b => Date.parse(fill.fill_at) >= Date.parse(b.time) && Date.parse(fill.fill_at) <= Date.parse(b.endTime))}));
  return {bars, equity, sma, markers, baseClose: first?.open ?? null,
    initialCash: numberOrNull(report?.initial_cash) > 0 ? report.initial_cash : null};
}
function indexValue(value, base) {
  const raw = numberOrNull(value), denominator = numberOrNull(base);
  return raw !== null && denominator > 0 ? raw / denominator * 100 : null;
}
function createLatestLoader(fetcher) {
  let epoch = 0, controller;
  return {
    cancel() {epoch++; controller?.abort();},
    async load(url) {
      const token = ++epoch;
      controller?.abort(); controller = new AbortController();
      try {
        const response = await fetcher(url, {signal: controller.signal, cache: 'no-store', credentials: 'same-origin'});
        if (token !== epoch) return null;
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(typeof body.code === 'string' && /^[A-Z0-9_]+$/.test(body.code) ? body.code : 'API_UNAVAILABLE');
        }
        const body = await response.json();
        return token === epoch ? body : null;
      } catch (error) {
        if (token !== epoch || error.name === 'AbortError') return null;
        throw new Error(/^[A-Z0-9_]+$/.test(error.message) ? error.message : 'API_UNAVAILABLE');
      }
    }
  };
}
function indicatorDefaults(){return {sma:{period:20},ema:{period:20},bollinger:{period:20,deviation:'2'},rsi:{period:14}};}
function restoredControls(saved, count) {
  const clean = {granularity: '1D', rangeId: 'All', mode: 'Orders', theme: 'auto', sma: false, markers: true, volume:true, diagnostics:{},
    ema:false,bollinger:false,rsi:false,benchmark:false,referenceFamily:'RAW_PRICE_RELATIVE',indicators:indicatorDefaults(),sortBy: 'createdAt', sortDir: 'desc', cursorSource: 'assetClose', lo: 0, hi: Math.max(0, count - 1)};
  if (!saved || typeof saved !== 'object') return clean;
  if (GRANULARITIES.includes(saved.granularity)) clean.granularity = saved.granularity;
  if (['1W','1M','3M','6M','12M','All','Custom'].includes(saved.rangeId)) clean.rangeId = saved.rangeId;
  if (['Orders','Overlays','Settings'].includes(saved.mode)) clean.mode = saved.mode;
  if (['auto','light','dark'].includes(saved.theme)) clean.theme = saved.theme;
  for (const key of ['sma','ema','bollinger','rsi','benchmark','markers','volume']) if (typeof saved[key] === 'boolean') clean[key] = saved[key];
  for(const key of ['raw','sma','ema','bollinger','rsi','reference','source'])if(typeof saved.diagnostics?.[key]==='boolean')clean.diagnostics[key]=saved.diagnostics[key];
  for(const key of ['sma','ema','bollinger','rsi']){const period=saved.indicators?.[key]?.period;if(Number.isInteger(period)&&period>=2&&period<=500)clean.indicators[key].period=period;}
  const k=saved.indicators?.bollinger?.deviation;if(typeof k==='string'&&k.length<=40&&/^\d+(?:\.\d+)?$/.test(k)&&Number(k)>0&&Number(k)<=10)clean.indicators.bollinger.deviation=k;
  if(['RAW_PRICE_RELATIVE','PROVIDER_ADJUSTED_CLOSE_INDEX'].includes(saved.referenceFamily))clean.referenceFamily=saved.referenceFamily;
  if (['createdAt','returnPct','sharpe'].includes(saved.sortBy)) clean.sortBy = saved.sortBy;
  if (['asc','desc'].includes(saved.sortDir)) clean.sortDir = saved.sortDir;
  if (['assetClose','strategyEquity'].includes(saved.cursorSource)) clean.cursorSource = saved.cursorSource;
  if (Number.isInteger(saved.lo) && Number.isInteger(saved.hi) && saved.lo >= 0 && saved.hi >= saved.lo && saved.hi < count) {
    clean.lo = saved.lo; clean.hi = saved.hi;
  }
  return clean;
}
// Readout-only exact subtraction; never used to compute report metrics.
function decimalDelta(end, start) {
  function scaled(value) {
    if (typeof value !== 'string' || !/^[+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?$/.test(value) || value.length > 120) return null;
    const [coefficient, exp = '0'] = value.toLowerCase().split('e'), exponent = Number(exp);
    if (!Number.isInteger(exponent) || Math.abs(exponent) > 100) return null;
    const [whole, fraction = ''] = coefficient.split('.');
    return {integer: BigInt(whole + fraction), scale: fraction.length - exponent};
  }
  const a = scaled(end), b = scaled(start);
  if (!a || !b) return null;
  const scale = Math.max(0, a.scale, b.scale), value = a.integer * 10n**BigInt(scale-a.scale) - b.integer * 10n**BigInt(scale-b.scale);
  const digits = (value < 0n ? -value : value).toString().padStart(scale+1, '0');
  return (value < 0n ? '-' : '') + (scale ? digits.slice(0,-scale) + '.' + digits.slice(-scale) : digits);
}

// Presentation-only decimal HALF_EVEN. Never modifies a metric or report object.
function fixedTwoDecimal(value) {
  if (typeof value !== 'string' && typeof value !== 'number') return null;
  if (typeof value === 'number' && !Number.isFinite(value)) return null;
  const text=String(value).trim();
  if (text.length>512 || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text)) return null;
  const negative=text[0]==='-',unsigned=text.replace(/^[+-]/,''),[coefficient,rawExponent='0']=unsigned.toLowerCase().split('e');
  const exponent=Number(rawExponent);
  if (!Number.isInteger(exponent)||Math.abs(exponent)>10000) return null;
  const [whole='',fraction='']=coefficient.split('.'),digits=(whole+fraction).replace(/^0+(?=\d)/,'')||'0',shift=exponent-fraction.length+2;
  let scaled;
  if (shift>=0) scaled=BigInt(digits+'0'.repeat(shift));
  else {
    const drop=-shift,kept=digits.slice(0,Math.max(0,digits.length-drop))||'0',discarded=digits.padStart(drop,'0').slice(-drop);
    scaled=BigInt(kept);
    const first=discarded[0]||'0',rest=discarded.slice(1);
    if(first>'5'||first==='5'&&(/[1-9]/.test(rest)||scaled%2n===1n)) scaled++;
  }
  const output=scaled.toString().padStart(3,'0');
  return (negative&&scaled!==0n?'−':'')+output.slice(0,-2)+'.'+output.slice(-2);
}
function sharpeText(metric) {
  if(!metric||['UNAVAILABLE','INVALID','UNDEFINED','NO_DATA','NOT_COMPUTED','NOT_APPLICABLE','INSUFFICIENT_DATA','UNSUPPORTED'].includes(String(metric.status).toUpperCase())) return 'Unavailable';
  return fixedTwoDecimal(metric.value)??'Unavailable';
}

if (typeof module !== 'undefined') module.exports = {buildView, indexValue, createLatestLoader, restoredControls, decimalDelta, fixedTwoDecimal, sharpeText, indicatorDefaults};
