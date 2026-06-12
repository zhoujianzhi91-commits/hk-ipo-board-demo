const fs = require("fs");
const path = require("path");

const htmlPath = path.join(__dirname, "..", "hk-ipo-board-demo.html");
const html = fs.readFileSync(htmlPath, "utf8");

function assert(condition, message) {
  if (!condition) {
    console.error(`FAIL: ${message}`);
    process.exitCode = 1;
  }
}

assert(html.includes(".detail-panel"), "detail panel styles should exist");
assert(html.includes(".detail-body"), "detail body styles should exist");
assert(
  /\.detail-panel\s*\{[\s\S]*overflow-y:\s*auto;/.test(html),
  "detail panel should support whole-column vertical scrolling"
);
assert(
  !/\.detail-hero\s*\{[^}]*position:\s*sticky;/.test(html),
  "detail hero should not stay pinned while the right column scrolls"
);
assert(
  /\.detail-body\s*\{[\s\S]*overflow-y:\s*visible;/.test(html),
  "detail body should stop acting as the inner scroll container"
);

if (process.exitCode) process.exit(process.exitCode);
console.log("board demo detail scroll checks passed");
