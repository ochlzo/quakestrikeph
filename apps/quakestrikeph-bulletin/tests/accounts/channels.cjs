// Isolated fake destinations only; no live Clerk or SMS requests.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const mode of ['email', 'sms', 'both', 'none', 'skip', 'failure']) {
      const page = await browser.newPage();
      const writes = [];
      page.on('console', message => {
        if (message.text().startsWith('fixture:channels:saved:'))
          writes.push(JSON.parse(message.text().slice('fixture:channels:saved:'.length)));
      });
      await page.goto(`${root}/onboarding?signed=1&channel-test=${mode}`);
      const sms = ['sms', 'both', 'skip'].includes(mode);
      const email = ['email', 'both', 'skip', 'failure'].includes(mode);
      await page.getByRole('checkbox', { name: 'SMS Verify a supported Philippine mobile number.' }).setChecked(sms);
      await page.getByRole('checkbox', { name: 'Email Use your verified account email.' }).setChecked(email);
      assert.equal(writes.length, 0, 'Draft choices must not write');
      await page.getByRole('button', { name: 'Continue', exact: true }).click();
      if (sms) await page.getByRole('heading', { name: 'Add your mobile number' }).waitFor();
      else await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      assert.equal(writes[0].emailEnabled, email);
      assert.equal(writes[0].smsEnabled, false);
      if (mode === 'skip') {
        await page.getByRole('button', { name: 'Continue without SMS', exact: true }).click();
      } else if (sms) {
        await page.getByRole('textbox', { name: 'Mobile number', exact: true }).fill('09171234567');
        await page.getByRole('button', { name: 'Send verification code', exact: true }).click();
        assert.equal(writes.length, 1, 'Sending a code must not enable SMS');
        await page.getByRole('textbox', { name: 'Verification code' }).fill('111111');
        await page.getByRole('button', { name: 'Verify code', exact: true }).click();
      }
      await page.getByRole('heading', { name: 'Alert preferences', exact: true }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Save preferences', exact: true }).count(), 0);
      assert.equal(writes.at(-1).smsEnabled, sms && mode !== 'skip');
      const emailSwitch = page.getByRole('switch', { name: 'Email alerts', exact: true });
      await page.getByLabel('Alert me for earthquakes of magnitude:').fill('6.0');
      await page.getByRole('button', { name: 'Discard magnitude changes' }).click();
      assert.equal(await page.locator('#magnitude').inputValue(), '4.5');
      await emailSwitch.click();
      if (mode === 'failure') {
        await page.getByText('Fixture save failed. Try again.', { exact: true }).waitFor();
        assert.equal(await emailSwitch.isChecked(), email);
        await emailSwitch.click();
      }
      await page.waitForTimeout(600);
      assert.equal(writes.at(-1).emailEnabled, !email);
      assert.equal(writes.at(-1).magnitude, 4.5);
      await page.getByLabel('Alert me for earthquakes of magnitude:').fill('6.0');
      await page.getByRole('button', { name: 'Save magnitude', exact: true }).click();
      await page.waitForTimeout(200);
      assert.equal(writes.at(-1).magnitude, 6);
      await page.reload();
      await emailSwitch.waitFor();
      assert.equal(await emailSwitch.isChecked(), !email);
      assert.equal(await page.locator('#magnitude').inputValue(), '6.0');
      await page.close();
    }
    console.log('Onboarding commits, verified SMS opt-in, background saves, discard and rollback passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
