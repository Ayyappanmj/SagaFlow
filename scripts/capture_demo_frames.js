const puppeteer = require('../frontend/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE_URL = 'http://localhost:3000';
const FRAMES_DIR = path.resolve(__dirname, '../docs/images/demo_frames');

if (!fs.existsSync(FRAMES_DIR)) {
  fs.mkdirSync(FRAMES_DIR, { recursive: true });
}

async function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

(async () => {
  console.log('Launching headless browser for demo capture...');
  const browser = await puppeteer.launch({
    executablePath: EDGE_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1280,850']
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 850 });

  // 1. Overview dashboard
  console.log('Frame 1: Overview');
  await page.goto(`${BASE_URL}/#overview`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(FRAMES_DIR, '01_overview.png') });

  // 2. Orders page - ready to place happy path order
  console.log('Frame 2: Orders form');
  await page.goto(`${BASE_URL}/#orders`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(FRAMES_DIR, '02_place_order_form.png') });

  // Place Happy Path order
  console.log('Submitting happy path order...');
  const submitBtn = await page.$('button:not(.secondary)');
  if (submitBtn) await submitBtn.click();
  await sleep(3000);
  await page.screenshot({ path: path.join(FRAMES_DIR, '03_happy_path_completed.png') });

  // 3. Trigger Shipping Failure order
  console.log('Frame 4: Selecting Shipping failure');
  await page.goto(`${BASE_URL}/#orders`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.select('#scn', 'Shipping failure');
  await sleep(800);
  await page.screenshot({ path: path.join(FRAMES_DIR, '04_shipping_fail_selected.png') });

  console.log('Submitting shipping failure order...');
  const submitFailBtn = await page.$('button:not(.secondary)');
  if (submitFailBtn) await submitFailBtn.click();
  await sleep(3500);
  await page.screenshot({ path: path.join(FRAMES_DIR, '05_shipping_failed_compensating.png') });

  // 4. Compensation completed
  console.log('Frame 6: Compensation completed');
  await sleep(2000);
  await page.screenshot({ path: path.join(FRAMES_DIR, '06_compensation_completed.png') });

  // 5. Trigger Compensation Failure (REQUIRES_ATTENTION)
  console.log('Frame 7: Selecting Shipping failure + payment-void failure');
  await page.goto(`${BASE_URL}/#orders`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.select('#scn', 'Shipping failure + payment-void failure');
  await sleep(800);
  await page.screenshot({ path: path.join(FRAMES_DIR, '07_attn_scenario_selected.png') });

  console.log('Submitting compensation failure order...');
  const submitAttnBtn = await page.$('button:not(.secondary)');
  if (submitAttnBtn) await submitAttnBtn.click();
  await sleep(3500);
  await page.screenshot({ path: path.join(FRAMES_DIR, '08_requires_attention_state.png') });

  // 6. View in Failed Workflows tab
  console.log('Frame 9: Failed Workflows tab');
  await page.goto(`${BASE_URL}/#failed`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  const failedLink = await page.$('table tbody tr td a');
  if (failedLink) await failedLink.click();
  await sleep(2000);
  await page.screenshot({ path: path.join(FRAMES_DIR, '09_failed_workflows_view.png') });

  // 7. Click Retry button
  console.log('Frame 10: Clicking Retry');
  const buttons = await page.$$('button');
  for (const b of buttons) {
    const text = await (await b.getProperty('innerText')).jsonValue();
    if (text.includes('Retry (clear injected fault)')) {
      await b.click();
      console.log('Clicked Retry!');
      break;
    }
  }
  await sleep(4000);
  await page.screenshot({ path: path.join(FRAMES_DIR, '10_recovered_compensated.png') });

  // 8. System Health
  console.log('Frame 11: System Health');
  await page.goto(`${BASE_URL}/#health`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  await page.screenshot({ path: path.join(FRAMES_DIR, '11_system_health.png') });

  await browser.close();
  console.log('All demo frames captured successfully!');
})();
