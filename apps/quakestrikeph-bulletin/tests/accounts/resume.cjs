// Start the isolated Vite server, then run: node tests/accounts/resume.cjs
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const outcome of ['profile', 'failure']) {
      const page = await browser.newPage();
      const unavailable = [];
      page.on('console', message => {
        if (message.text() === 'fixture:resume:unavailable') unavailable.push(message.text());
      });
      await page.goto(`${root}/sign-in?signed=0&resume-test=${outcome}`);
      await page.getByRole('textbox', { name: 'Email address' }).fill('fixture@example.invalid');
      await page.getByRole('textbox', { name: 'Password', exact: true }).fill('fixture-password');
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      await page.getByRole('textbox', { name: 'Verification code' }).fill('111111');
      await page.getByRole('button', { name: 'Verify email', exact: true }).click();
      await page.getByRole('status', { name: 'Loading account', exact: true }).waitFor();
      assert.equal(unavailable.length, 0, 'An unresolved profile must not show a failure');
      if (outcome === 'profile') {
        await page.getByRole('heading', { name: 'Complete your profile', exact: true }).waitFor();
        assert.equal(unavailable.length, 0, 'Successful profile loading must never show unavailable');
        assert.equal(new URL(page.url()).pathname, '/onboarding');
      } else {
        await page.getByText('Account settings unavailable', { exact: true }).waitFor();
        assert(unavailable.length > 0, 'Failed profile loading must still show unavailable');
      }
      await page.close();
    }
    console.log('Post-sign-in profile loading and genuine failure checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
