// Lightweight Charts v5 boot for per-stock detail page.
// Loads OHLC for this ticker from docs/data/all.json.
(function () {
  const container = document.getElementById('chart');
  if (!container) return;
  const ticker = container.dataset.ticker;
  const bucket = container.dataset.bucket;

  const stocksPathMatch = window.location.pathname.match(/\/stocks\/[^\/]+\.html$/);
  const root = stocksPathMatch ? '..' : '.';

  const colors = {
    up:        '#4ADE80',
    down:      '#F87171',
    highlight: '#F5C451',
    text:      '#A4ACB9',
    grid:      '#232833',
    bg:        '#11141A',
  };

  function showMessage(text, color) {
    container.replaceChildren();
    const p = document.createElement('p');
    p.style.color = color || 'var(--text-md)';
    p.style.padding = '2rem';
    p.textContent = text;
    container.appendChild(p);
  }

  function buildChart(data) {
    if (!data || !data.length) {
      showMessage('No chart data available for ' + ticker + '.');
      return;
    }
    data.sort((a, b) => a.time - b.time);

    const LWC = window.LightweightCharts;
    const chart = LWC.createChart(container, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: colors.text },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      timeScale: { borderColor: colors.grid, timeVisible: false, secondsVisible: false },
      rightPriceScale: { borderColor: colors.grid, mode: bucket === 'B' ? 1 : 0 },
    });

    const candles = chart.addSeries(LWC.CandlestickSeries, {
      upColor: colors.up,
      downColor: colors.down,
      borderVisible: false,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
    });

    const volume = chart.addSeries(LWC.HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      color: colors.text + '80',
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.75, bottom: 0 } });
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.1, bottom: 0.3 } });

    const lastFiveTimes = new Set(data.slice(-5).map((b) => b.time));

    function applyData(slice) {
      const candleData = slice.map((b) => {
        const base = { time: b.time, open: b.o, high: b.h, low: b.l, close: b.c };
        if (lastFiveTimes.has(b.time)) {
          base.color = colors.highlight;
          base.wickColor = colors.highlight;
          base.borderColor = colors.highlight;
        }
        return base;
      });
      const volData = slice.map((b) => ({
        time: b.time,
        value: b.v,
        color: b.c >= b.o ? colors.up + '60' : colors.down + '60',
      }));
      candles.setData(candleData);
      volume.setData(volData);
      chart.timeScale().fitContent();
    }

    applyData(data);

    document.querySelectorAll('.tf-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tf-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        const days = parseInt(btn.dataset.days, 10);
        applyData(data.slice(-days));
      });
    });
  }

  async function loadAll() {
    let bundle;
    try {
      const r = await fetch(root + '/data/all.json');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      bundle = await r.json();
    } catch (e) {
      console.error('Failed to load chart data:', e);
      showMessage('Failed to load chart data.', 'var(--down)');
      return;
    }
    buildChart(bundle[ticker] || []);
  }

  loadAll();
})();
