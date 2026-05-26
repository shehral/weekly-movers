// Boot Tabulator on both bucket tables.
(function () {
  const fmtNum = (digits) => (cell) => {
    const v = cell.getValue();
    if (v === null || v === undefined || v === '') return '';
    return Number(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  };

  const fmtMoney = (cell) => {
    const v = cell.getValue();
    if (v === null || v === undefined || v === '') return '';
    return '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const fmtVol = (cell) => {
    const v = Number(cell.getValue());
    if (!isFinite(v)) return '';
    if (v >= 1e9) return '$' + (v / 1e9).toFixed(2) + 'B';
    if (v >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M';
    return '$' + v.toLocaleString();
  };

  const fmtPct = (cell) => {
    const v = Number(cell.getValue());
    if (!isFinite(v)) return '';
    return (v * 100).toFixed(2) + '%';
  };

  const badge = (label, fieldOn) => (cell) => {
    const on = cell.getRow().getData()[fieldOn] === true || cell.getRow().getData()[fieldOn] === 'True';
    return `<span class="badge ${on ? 'on' : 'off'}">${label}</span>`;
  };

  const tickerLink = (cell) => {
    const t = cell.getValue();
    const spark = cell.getRow().getData().spark || '';
    return `<a href="stocks/${t}.html" class="ticker">${t}</a><span class="spark">${spark}</span>`;
  };

  function makeColumns(bucket) {
    const isB = bucket === 'B';
    const variationFmt = isB ? fmtPct : fmtNum(2);
    return [
      { title: 'Ticker', field: 'ticker', formatter: tickerLink, cssClass: 'ticker', responsive: 0, headerFilter: 'input', headerSort: true, widthGrow: 1 },
      { title: 'Name', field: 'name', responsive: 3, headerFilter: 'input', widthGrow: 3 },
      { title: 'Last close', field: 'last_close', formatter: fmtMoney, cssClass: 'num', responsive: 0, hozAlign: 'right', sorter: 'number' },
      { title: 'Range', field: 'range_value', formatter: variationFmt, cssClass: 'num', responsive: 1, hozAlign: 'right', sorter: 'number' },
      { title: '5d ret', field: 'ret_5d_value', formatter: variationFmt, cssClass: 'num', responsive: 2, hozAlign: 'right', sorter: 'number' },
      { title: 'Max daily', field: 'max_daily_value', formatter: variationFmt, cssClass: 'num', responsive: 2, hozAlign: 'right', sorter: 'number' },
      { title: 'Triggers', field: 'range_triggers',
        formatter: (cell) => {
          const d = cell.getRow().getData();
          const b = (label, on) => `<span class="badge ${on ? 'on' : 'off'}">${label}</span>`;
          const truthy = (v) => v === true || v === 'True' || v === 'true';
          return `<span class="badges">${b('RNG', truthy(d.range_triggers))}${b('5D', truthy(d.ret_5d_triggers))}${b('MAX', truthy(d.max_daily_triggers))}</span>`;
        },
        responsive: 0, headerSort: false,
      },
      { title: 'Avg $-vol', field: 'avg_dollar_vol', formatter: fmtVol, cssClass: 'num', responsive: 3, hozAlign: 'right', sorter: 'number' },
    ];
  }

  function parseInlineJson(id) {
    const node = document.getElementById(id);
    if (!node) return [];
    try { return JSON.parse(node.textContent); }
    catch (e) { console.error('Bad JSON in', id, e); return []; }
  }

  const dataA = parseInlineJson('data-A');
  const dataB = parseInlineJson('data-B');

  if (document.getElementById('table-A')) {
    new Tabulator('#table-A', {
      data: dataA,
      columns: makeColumns('A'),
      layout: 'fitColumns',
      responsiveLayout: 'collapse',
      initialSort: [{ column: 'range_value', dir: 'desc' }],
      placeholder: 'No names in Bucket A today.',
    });
  }

  if (document.getElementById('table-B')) {
    new Tabulator('#table-B', {
      data: dataB,
      columns: makeColumns('B'),
      layout: 'fitColumns',
      responsiveLayout: 'collapse',
      initialSort: [{ column: 'range_value', dir: 'desc' }],
      placeholder: 'No names in Bucket B today.',
    });
  }
})();
