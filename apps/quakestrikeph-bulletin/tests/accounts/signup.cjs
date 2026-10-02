// Isolated Clerk fixture regression; never submits credentials to a provider.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    await page.goto((process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332') + '/?initial=signup');
    await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Fixture Reader');
    await page.getByRole('textbox', { name: 'Email address' }).fill('fixture@example.invalid');
    for (const invalid of ['Abcdef1', 'abcdefg1', 'ABCDEFG1', 'Abcdefgh']) {
      await page.getByRole('textbox', { name: 'Password', exact: true }).fill(invalid);
      assert.equal(await page.locator('#password').evaluate(el => el.checkValidity()), false);
    }
    await page.getByRole('textbox', { name: 'Password', exact: true }).fill('Fixture-breached-password1');
    await page.getByRole('button', { name: 'Create account', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'This password has appeared in a data breach.' }).waitFor({ timeout: 3000 });
    assert.equal(await page.locator('#password').getAttribute('aria-invalid'), 'true');
    assert.equal(await page.locator('#password').getAttribute('aria-describedby'), 'password-error');
    await page.getByRole('textbox', { name: 'Password', exact: true }).fill('Abcdefg1');
    await page.getByRole('button', { name: 'Create account', exact: true }).click();
    await page.getByRole('heading', { name: 'Verify your email', exact: true }).waitFor();
    assert.equal(await page.getByText('This password has appeared in a data breach.', { exact: false }).count(), 0);
    console.log('Signup password rules, provider field error, and eight-character continuation passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
