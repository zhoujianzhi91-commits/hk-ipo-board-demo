const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "hk-ipo.html"), "utf8");
const officialUpdates = fs.readFileSync(path.join(root, "data", "official-updates-2026.js"), "utf8");
const inlineScript = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]).pop();

const context = {
  window: {},
  document: {
    addEventListener() {},
    getElementById() { return null; },
    querySelectorAll() { return []; },
  },
  console,
  setTimeout() {},
  setInterval() {},
  clearInterval() {},
  Intl,
  Date,
  Math,
  Number,
  String,
  Array,
  Object,
  JSON,
  RegExp,
  parseFloat,
  parseInt,
  isFinite,
};

vm.createContext(context);
vm.runInContext(officialUpdates, context);
context.window.LATEST_LISTED_2026 = [];
context.window.MARKET_PERFORMANCE_2025 = {};
context.window.MARKET_PERFORMANCE_2026 = {};
context.window.__NOW_OVERRIDE = "2026-05-30T12:00:00+08:00";
try {
  vm.runInContext(inlineScript, context);
} catch (error) {
  if (!String(error && error.message || "").includes("oninput")) throw error;
}

function assert(condition, message) {
  if (!condition) {
    console.error(`FAIL: ${message}`);
    process.exitCode = 1;
  }
}

for (const code of ["01779", "02553"]) {
  const stock = vm.runInContext(`stocks.find(item => item.stockCode === "${code}")`, context);
  assert(stock, `${code} should be loaded`);
  const rows = vm.runInContext(`predictedAllotmentRows(stocks.find(item => item.stockCode === "${code}"))`, context);
  assert(rows.length > 0, `${code} should have predicted rows`);
  for (const group of ["A", "B"]) {
    const groupRows = rows
      .filter(row => row.group === group)
      .sort((a, b) => Number(a.lots) - Number(b.lots));
    let previous = null;
    for (const row of groupRows) {
      const expectedLots = Number(row.expectedShares) / Number(stock.sharesPerLot);
      if (previous != null) {
        assert(expectedLots + 1e-9 >= previous.expectedLots, `${code} ${group} group should be non-decreasing: ${previous.lots} lots=${previous.expectedLots.toFixed(6)}, ${row.lots} lots=${expectedLots.toFixed(6)}`);
      }
      previous = { lots: row.lots, expectedLots };
    }
  }
}

if (process.exitCode) process.exit(process.exitCode);
console.log("prediction monotonic checks passed");
