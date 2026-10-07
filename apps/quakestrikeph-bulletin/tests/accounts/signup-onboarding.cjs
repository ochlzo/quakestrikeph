// Uses the isolated Vite fixture; no live credentials or email requests.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    const trace = [];
    page.on('console', message => trace.push(message.text()));
    await page.goto(`${root}/sign-up?signed=0&resume-test=signup-profile`);
    await page.getByRole('textbox', { name: 'Email address' }).fill('fixture@example.invalid');
    await page.getByRole('textbox', { name: 'Password', exact: true }).fill('Abcdefg1');
    await page.getByRole('textbox', { name: 'Name', exact: true }).fill('john bENEDICT');
    await page.getByRole('textbox', { name: 'Name', exact: true }).press('Enter');
    await page.getByRole('heading', { name: 'Verify your email', exact: true }).waitFor();
    assert.equal(trace.some(line => line.startsWith('fixture:signup:saved-name:')), false);
    await page.getByRole('textbox', { name: 'Verification code' }).fill('999999');
    await page.getByRole('button', { name: 'Verify email', exact: true }).click();
    await page.locator('[data-slot="toast"]').filter({ hasText: 'That code did not work.' }).waitFor();
    assert.equal(trace.some(line => line.startsWith('fixture:signup:saved-name:')), false, 'Rejected email proof must not save the profile');
    await page.getByRole('textbox', { name: 'Verification code' }).fill('111111');
    await page.getByRole('button', { name: 'Verify email', exact: true }).click();
    await page.getByRole('heading', { name: 'How would you like to receive alerts?', exact: true }).waitFor();
    assert.deepEqual(trace.filter(line => line.startsWith('fixture:signup:saved-name:')), ['fixture:signup:saved-name:John BENEDICT']);
    assert.equal(trace.includes('fixture:resume:profile'), false, 'Signup must skip the redundant profile screen');
    assert.equal(trace.includes('fixture:resume:unavailable'), false);
    assert.equal(new URL(page.url()).pathname, '/onboarding');
    console.log('Verified signup saves the normalized name once and skips profile completion.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
