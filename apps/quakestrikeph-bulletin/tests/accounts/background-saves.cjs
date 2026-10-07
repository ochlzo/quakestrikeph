// Actual Astro navigation with fake account and identity adapters.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_ASTRO_FIXTURE_URL || 'http://127.0.0.1:4333';
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    let unloads = 0;
    page.on('console', message => { if (message.text() === 'fixture:navigation:document-unload') unloads++; });
    await page.goto(`${root}/onboarding?signed=1&channel-test=delayed-failure`);
    await page.getByRole('checkbox', { name: 'SMS Verify a supported Philippine mobile number.' }).uncheck();
    await page.getByRole('checkbox', { name: 'Email Use your verified account email.' }).check();
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
    await page.getByRole('switch', { name: 'Email alerts', exact: true }).press('Space');
    await page.getByRole('link', { name: 'Back to Bulletin' }).click();
    await page.waitForURL(`${root}/`);
    await page.getByText('Fixture save failed. Try again.', { exact: true }).waitFor();
    await page.getByRole('link', { name: 'Alert settings', exact: true }).click();
    await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
    assert.equal(unloads, 0, 'Navigation must preserve the background runtime');
    assert.equal(await page.getByRole('switch', { name: 'Email alerts', exact: true }).isChecked(), true);
    assert.equal(await page.getByText('Fixture save failed. Try again.', { exact: true }).isVisible(), true);
    console.log('Failure toast and rollback survived account/Bulletin navigation.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
