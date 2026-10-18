// Isolated account UI checks. Clerk and account operations use local fixtures.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { join } = require('node:path');
const { tmpdir } = require('node:os');
const root = process.env.ACCOUNTS_FIXTURE_URL || 'http://127.0.0.1:4332';
const account = { userId:'fixture-user', displayName:'Fixture Reader', email:'fixture@example.invalid',
 phone:'+639171234567', onboardingCompleted:true, status:'active', emailEnabled:true, smsEnabled:true,
 magnitude:4.5, nearbyOnly:false, latitude:null, longitude:null, distanceKm:null };
const visit = (page, path) => page.goto(`${root}${path}`, { waitUntil:'domcontentloaded', timeout:60000 });
const heading = (page, name) => page.getByRole('heading', {name,exact:true}).waitFor();
const button = (page, name) => page.getByRole('button', {name,exact:true});
const management = page => page.getByRole('dialog', {name:'Mobile number',exact:true});
async function proof(page) {
 await button(page,'Send verification code').click();
 await heading(page,'Verify your identity again');
 await page.locator('#code').fill('111111');
 await button(page,'Verify identity').click();
}
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}), errors=[];
 try { for(const width of [1440,390,320]) {
  const page=await browser.newPage({viewport:{width,height:900},reducedMotion:'reduce'});
  page.setDefaultTimeout(15000);
  page.on('pageerror',e=>errors.push(e.message));
  await page.clock.install();
  let hasPhone=true; const requests=[];
  await page.route('**/api/v1/account**',r=>{
   requests.push(r.request().method());
   return r.fulfill({json:{account:{...account,phone:hasPhone?account.phone:null},pending:null,nextStep:'complete'}});
  });
  await visit(page,'/account?signed=1'); await heading(page,'Account settings');
  const mobile=page.locator('.account-row').filter({hasText:'Mobile number'});
  const manage=mobile.getByRole('button',{name:'Manage',exact:true});
  await manage.focus(); await page.keyboard.press('Enter');
  await management(page).waitFor();
  assert.equal(new URL(page.url()).pathname,'/account');
  assert.deepEqual(await management(page).locator('.phone-management-actions button').allTextContents(),['Remove number','Change number']);
  await management(page).getByText('Manage the number you use for SMS alerts.', {exact:true}).waitFor();
  await management(page).getByText(account.phone, {exact:true}).waitFor();
  assert.equal(await management(page).locator('dt').count(),0,'Do not repeat the mobile-number label');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:join(tmpdir(),`phone-management-modal-${width}.png`)});
  await page.keyboard.press('Escape'); await management(page).waitFor({state:'hidden'});
  await heading(page,'Account settings');
  assert.equal(await manage.evaluate(el=>el===document.activeElement),true,'Escape restores Manage focus');
  await manage.click(); await management(page).waitFor();
  await management(page).getByRole('button',{name:'Close',exact:true}).click();
  await management(page).waitFor({state:'hidden'}); await heading(page,'Account settings');
  await manage.click(); await management(page).getByRole('button',{name:'Change number',exact:true}).click();
  await heading(page,'Verify your identity'); assert.equal(new URL(page.url()).pathname,'/account/phone');
  await button(page,'Back').click(); await management(page).waitFor();
  await management(page).getByRole('button',{name:'Remove number',exact:true}).click();
  await heading(page,'Verify your identity'); assert.equal(new URL(page.url()).pathname,'/account/phone/remove');
  assert.deepEqual(await page.evaluate(()=>window.clerkFixture.calls.map(c=>c.method)),['getToken']);
  await proof(page); await heading(page,'Remove your mobile number?');
  assert.equal(await button(page,'Remove number').isDisabled(),true);
  await button(page,'Cancel').click(); await management(page).waitFor();
  await management(page).getByRole('button',{name:'Change number',exact:true}).click();
  await heading(page,'Change your mobile number');
  await button(page,'Back').click(); await management(page).waitFor();
  await page.clock.fastForward(300000);
  await management(page).getByRole('button',{name:'Remove number',exact:true}).click();
  await heading(page,'Verify your identity');
  assert.equal(await page.evaluate(()=>window.clerkFixture.calls.filter(c=>c.method==='startVerification').length),1);
  await proof(page); await heading(page,'Remove your mobile number?');
  await button(page,'Cancel').click(); await management(page).waitFor();
  await management(page).getByRole('button',{name:'Remove number',exact:true}).click();
  await heading(page,'Remove your mobile number?');
  assert.equal(await page.evaluate(()=>window.clerkFixture.calls.filter(c=>c.method==='startVerification').length),2);
  assert.deepEqual(requests,['GET'],'No removal mutation or extra account fetch');
  await button(page,'Back').click(); await management(page).waitFor();
  await page.keyboard.press('Escape'); await heading(page,'Account settings');
  await page.locator('.account-row').filter({hasText:'Signed-in devices'}).getByRole('button',{name:'Manage',exact:true}).click();
  await heading(page,'Signed-in devices'); assert.equal(new URL(page.url()).pathname,'/account/devices');
  assert.equal(await button(page,'Sign out other devices').isDisabled(),true);
  const paths=[['/account/phone/remove','Verify your identity'],['/account/devices','Signed-in devices'],['/account/email','Email change is unavailable'],['/account/remove','Account removal is unavailable']];
  for(const [path,title] of paths) {
   await visit(page,`${path}?signed=1`); await heading(page,title);
   assert.equal(new URL(page.url()).pathname,path);
   await page.reload({waitUntil:'domcontentloaded',timeout:60000}); await heading(page,title);
   await visit(page,`${path}?signed=0`); await heading(page,'Sign in'); assert.equal(new URL(page.url()).pathname,'/sign-in');
  }
  await visit(page,'/account?signed=1'); await heading(page,'Account settings');
  await manage.click(); await management(page).getByRole('button',{name:'Remove number',exact:true}).click();
  await heading(page,'Verify your identity'); await page.goBack(); await heading(page,'Account settings');
  await page.goForward(); await heading(page,'Verify your identity');
  hasPhone=false; await visit(page,'/account/phone/remove?signed=1'); await heading(page,'Account settings');
  assert.equal(new URL(page.url()).pathname,'/account'); assert.equal(await mobile.getByRole('button',{name:'Manage',exact:true}).count(),0);
  await button(page,'Add').waitFor(); await page.close();
  console.log(`PASS ${width}: modal, Escape/focus, both OTP gates, five-minute reuse/expiry, routes/history, disabled removal`);
 }
 assert.deepEqual(errors,[]);
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
