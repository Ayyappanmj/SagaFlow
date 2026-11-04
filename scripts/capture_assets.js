const puppeteer = require('../frontend/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE_URL = 'http://localhost:3000';
const OUT_DIR = path.resolve(__dirname, '../docs/images');

if (!fs.existsSync(OUT_DIR)) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
}

async function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

(async () => {
  console.log('Launching headless browser...');
  const browser = await puppeteer.launch({
    executablePath: EDGE_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1280,850']
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 850 });

  // 1. Overview
  console.log('Capturing Overview...');
  await page.goto(`${BASE_URL}/#overview`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(OUT_DIR, 'overview.png') });

  // 2. System Health
  console.log('Capturing System Health...');
  await page.goto(`${BASE_URL}/#health`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(OUT_DIR, 'system_health.png') });

  // 3. Orders Simulation View
  console.log('Capturing Orders & Simulation...');
  await page.goto(`${BASE_URL}/#orders`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(OUT_DIR, 'orders_simulation.png') });

  // 4. Saga Explorer with COMPENSATED saga timeline
  console.log('Capturing COMPENSATED saga timeline...');
  await page.goto(`${BASE_URL}/#sagas`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  // Filter by state COMPENSATED
  await page.select('#st', 'COMPENSATED');
  await sleep(1500);
  // Click first link in the table
  const link = await page.$('table tbody tr td a');
  if (link) {
    await link.click();
    await sleep(2000);
    await page.screenshot({ path: path.join(OUT_DIR, 'saga_timeline_compensated.png') });
  }

  // 5. REQUIRES_ATTENTION saga before & after retry
  console.log('Capturing REQUIRES_ATTENTION saga before retry...');
  await page.goto(`${BASE_URL}/#failed`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  const failedLink = await page.$('table tbody tr td a');
  if (failedLink) {
    await failedLink.click();
    await sleep(2000);
    await page.screenshot({ path: path.join(OUT_DIR, 'requires_attention_before.png') });

    console.log('Clicking Retry button...');
    // Find button with text 'Retry (clear injected fault)'
    const buttons = await page.$$('button');
    for (const b of buttons) {
      const text = await (await b.getProperty('innerText')).jsonValue();
      if (text.includes('Retry (clear injected fault)')) {
        await b.click();
        console.log('Clicked Retry button!');
        break;
      }
    }

    // Wait for recovery to complete
    console.log('Waiting for recovery to transition state...');
    await sleep(4000);
    await page.screenshot({ path: path.join(OUT_DIR, 'requires_attention_after.png') });
  } else {
    console.log('No failed saga link found in #failed view');
  }

  await browser.close();
  console.log('All static screenshots captured successfully!');
})();
