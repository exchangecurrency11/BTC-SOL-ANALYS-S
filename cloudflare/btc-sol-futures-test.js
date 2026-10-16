// Cloudflare Worker: original market-data endpoint + read-only closed-candle history.
// Secret: COINALYZE_API_KEY (Cloudflare secret; never hardcode a key here).
// The existing "/" JSON contract is intentionally unchanged.

async function getClosedHistory(url, env) {
  const config = {
    "1hour": { seconds: 3600, days: 14 },
    "4hour": { seconds: 14400, days: 50 },
    "daily": { seconds: 86400, days: 260 }
  };
  const interval = url.searchParams.get("interval");
  const period = config[interval];

  if (!period) {
    return Response.json(
      { ok: false, error: "Choose interval=1hour, 4hour or daily" },
      { status: 400, headers: { "Cache-Control": "no-store" } }
    );
  }
  if (!env.COINALYZE_API_KEY) {
    return Response.json(
      { ok: false, error: "API key missing" },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  // Fixed symbols and bounded history prevent caller-controlled API fan-out.
  const symbols = ["BTCUSDT_PERP.A", "SOLUSDT_PERP.A"];
  const now = Math.floor(Date.now() / 1000);
  const currentStart = Math.floor(now / period.seconds) * period.seconds;
  const params = new URLSearchParams({
    symbols: symbols.join(","),
    interval,
    from: String(now - period.days * 86400),
    to: String(now)
  });

  try {
    const upstream = await fetch(
      "https://api.coinalyze.net/v1/ohlcv-history?" + params.toString(),
      { headers: { api_key: env.COINALYZE_API_KEY } }
    );
    if (!upstream.ok) {
      return Response.json(
        { ok: false, error: "History data provider unavailable", upstreamStatus: upstream.status },
        { status: upstream.status === 429 ? 429 : 502,
          headers: { "Cache-Control": "no-store" } }
      );
    }

    const payload = await upstream.json();
    if (!Array.isArray(payload)) throw new Error("History response is not an array");

    const result = symbols.map(symbol => {
      const record = payload.find(item => item.symbol === symbol);
      if (!record || !Array.isArray(record.history)) {
        throw new Error("Missing " + symbol + " history");
      }

      const history = record.history
        .map(c => ({
          t: Number(c.t), o: Number(c.o), h: Number(c.h),
          l: Number(c.l), c: Number(c.c), v: Number(c.v)
        }))
        .filter(c => (
          Number.isSafeInteger(c.t) && c.t % period.seconds === 0 &&
          c.t < currentStart &&
          [c.o, c.h, c.l, c.c, c.v].every(Number.isFinite) &&
          c.l > 0 && c.v >= 0 &&
          c.l <= Math.min(c.o, c.c) && c.h >= Math.max(c.o, c.c)
        ))
        .sort((a, b) => a.t - b.t)
        .slice(-300);

      // Never present stale, sparse or still-forming bars as current history.
      const tail = history.slice(-250);
      if (tail.length < 250 ||
          history.at(-1).t + period.seconds !== currentStart ||
          tail.some((c, i) => i > 0 && c.t - tail[i - 1].t !== period.seconds)) {
        throw new Error("Closed " + interval + " candles are incomplete or stale");
      }
      return { symbol, history };
    });
    return Response.json(result, {
      headers: { "Cache-Control": "no-store" }
    });
  } catch (error) {
    // Don't expose provider tokens or request headers in errors.
    return Response.json(
      { ok: false, error: "Closed history not ready", detail: String(error.message || error) },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}

function ema(values, period) {
  const result = [];
  const k = 2 / (period + 1);
  let previous = values[0];

  for (const value of values) {
    previous = value * k + previous * (1 - k);
    result.push(previous);
  }

  return result;
}

function rsi(values, period = 14) {
  if (values.length <= period) return null;

  let gains = 0;
  let losses = 0;

  for (let i = 1; i <= period; i++) {
    const change = values[i] - values[i - 1];
    gains += Math.max(change, 0);
    losses += Math.max(-change, 0);
  }

  gains /= period;
  losses /= period;

  for (let i = period + 1; i < values.length; i++) {
    const change = values[i] - values[i - 1];
    gains = (gains * 13 + Math.max(change, 0)) / 14;
    losses = (losses * 13 + Math.max(-change, 0)) / 14;
  }

  if (gains === 0 && losses === 0) return 50;
  if (losses === 0) return 100;

  const rs = gains / losses;
  return 100 - 100 / (1 + rs);
}

function round(value) {
  return Number(value.toFixed(4));
}

export default {
  async fetch(request, env) {
    // New endpoint: historical closed OHLCV for market_structure.py.
    // No changes to the original "/" JSON used by GitHub and ChatGPT.
    const url = new URL(request.url);
    if (url.pathname === "/history") {
      return getClosedHistory(url, env);
    }

    if (!env.COINALYZE_API_KEY) {
      return Response.json({
        ok: false,
        error: "API key missing"
      });
    }

    const now = Math.floor(Date.now() / 1000);

    const periods = [
      { interval: "1hour", seconds: 3600, days: 14 },
      { interval: "4hour", seconds: 14400, days: 50 },
      { interval: "daily", seconds: 86400, days: 260 }
    ];

    const symbols = [
      "BTCUSDT_PERP.A",
      "SOLUSDT_PERP.A"
    ];

    const results = [];

    try {
      for (const period of periods) {
        const params = new URLSearchParams({
          symbols: symbols.join(","),
          interval: period.interval,
          from: String(now - period.days * 86400),
          to: String(now)
        });

        const response = await fetch(
          "https://api.coinalyze.net/v1/ohlcv-history?" +
            params.toString(),
          {
            headers: {
              api_key: env.COINALYZE_API_KEY
            }
          }
        );

        if (!response.ok) {
          results.push({
            interval: period.interval,
            errorStatus: response.status
          });
          continue;
        }

        const data = await response.json();

        const currentStart =
          Math.floor(now / period.seconds) *
          period.seconds;

        for (const symbol of symbols) {
          const market = data.find(
            item => item.symbol === symbol
          );

          const closed = (market?.history || [])
            .filter(c =>
              Number(c.t) < currentStart &&
              [c.o, c.h, c.l, c.c, c.v].every(
                v => Number.isFinite(Number(v))
              )
            )
            .sort((a, b) => a.t - b.t);

          const last = closed.at(-1);
          const previous = closed.at(-2);

          const recent = closed.slice(-250);

          const continuous =
            recent.length === 250 &&
            recent.every((c, i) =>
              i === 0 ||
              Number(c.t) - Number(recent[i - 1].t) ===
                period.seconds
            );

          const fresh =
            last &&
            Number(last.t) + period.seconds ===
              currentStart;

          const ready = continuous && fresh;

          if (!ready) {
            results.push({
              symbol,
              interval: period.interval,
              status: "NOT_READY",
              closedCandles: closed.length,
              lastCloseTimeUTC: last
                ? new Date(
                    (Number(last.t) + period.seconds) * 1000
                  ).toISOString()
                : null
            });
            continue;
          }

          const closes = closed.map(c => Number(c.c));

          const ema12 = ema(closes, 12);
          const ema26 = ema(closes, 26);

          const macdSeries = ema12.map(
            (v, i) => v - ema26[i]
          );

          const signalSeries = ema(macdSeries, 9);

          const macd = macdSeries.at(-1);
          const signal = signalSeries.at(-1);

          const volumeChange = Number(previous.v) > 0
            ? (Number(last.v) / Number(previous.v) - 1) * 100
            : null;

          results.push({
            symbol,
            interval: period.interval,
            status: "READY",
            closedCandles: closed.length,
            closeTimeUTC: new Date(
              (Number(last.t) + period.seconds) * 1000
            ).toISOString(),
            candle: {
              open: Number(last.o),
              high: Number(last.h),
              low: Number(last.l),
              close: Number(last.c),
              volume: Number(last.v),
              volumeChangePct:
                volumeChange === null
                  ? null
                  : round(volumeChange)
            },
            indicators: {
              RSI14: round(rsi(closes)),
              EMA20: round(ema(closes, 20).at(-1)),
              EMA50: round(ema(closes, 50).at(-1)),
              EMA200: round(ema(closes, 200).at(-1)),
              MACD: round(macd),
              MACDSignal: round(signal),
              MACDHistogram: round(macd - signal)
            }
          });
        }
      }

      return Response.json({
        ok: results.length === 6 &&
          results.every(r => r.status === "READY"),
        provider: "Coinalyze",
        exchange: "Binance",
        market: "Perpetual Futures",
        checkedAtUTC: new Date().toISOString(),
        results
      }, {
        headers: { "Cache-Control": "no-store" }
      });

    } catch (error) {
      return Response.json({
        ok: false,
        error: String(error)
      });
    }
  }
};
