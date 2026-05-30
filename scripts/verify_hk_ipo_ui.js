const fs = require("fs");
const path = require("path");

const htmlPath = path.join(__dirname, "..", "hk-ipo.html");
const html = fs.readFileSync(htmlPath, "utf8");

function assert(condition, message) {
  if (!condition) {
    console.error(`FAIL: ${message}`);
    process.exitCode = 1;
  }
}

const activeSectionMatch = html.match(/<section class="section-block" id="sectionSubscribing">[\s\S]*?<\/section>/);
assert(Boolean(activeSectionMatch), "active IPO section should exist");

if (activeSectionMatch) {
  const activeSection = activeSectionMatch[0];
  assert(!activeSection.includes("<th>状态</th>"), "active IPO table should not show a duplicate status column");
}

assert(html.includes("官方截止"), "subscription deadline copy should use official cutoff wording");
assert(html.includes("券商通常 09:00-10:00"), "subscription deadline copy should warn that brokers usually close earlier");
assert(!html.includes("富途截止"), "subscription deadline copy should not imply a Futu-specific cutoff");

if (process.exitCode) process.exit(process.exitCode);
console.log("hk-ipo UI checks passed");
