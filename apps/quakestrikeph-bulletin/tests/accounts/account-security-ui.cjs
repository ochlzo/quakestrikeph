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
async function accountWithoutManagement(page) {
 await heading(page,'Account settings');
 await management(page).waitFor({state:'hidden'});
}
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
   const method=r.request().method(); requests.push(method);
   if(method==='DELETE'&&new URL(r.request().url()).pathname.endsWith('/account/phone')){
    hasPhone=false; return r.fulfill({json:{...account,phone:null}});
   }
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
  await button(page,'Back').click(); await accountWithoutManagement(page);
  await manage.click(); await management(page).waitFor();
  await management(page).getByRole('button',{name:'Remove number',exact:true}).click();
  await heading(page,'Verify your identity'); assert.equal(new URL(page.url()).pathname,'/account/phone/remove');
  assert.equal(await page.evaluate(()=>window.clerkFixture.calls.every(c=>c.method==='getToken')),true,'Entry checks freshness without sending a code');
  await proof(page); await heading(page,'Remove your mobile number?');
  assert.equal(await button(page,'Remove number').isDisabled(),false);
  await button(page,'Cancel').click(); await accountWithoutManagement(page);
  await manage.click(); await management(page).waitFor();
  await management(page).getByRole('button',{name:'Change number',exact:true}).click();
  await heading(page,'Change your mobile number');
  await button(page,'Back').click(); await accountWithoutManagement(page);
  await page.clock.fastForward(300000);
  await manage.click(); await management(page).waitFor();
  await management(page).getByRole('button',{name:'Remove number',exact:true}).click();
  await heading(page,'Verify your identity');
  assert.equal(await page.evaluate(()=>window.clerkFixture.calls.filter(c=>c.method==='startVerification').length),1);
  await proof(page); await heading(page,'Remove your mobile number?');
  await button(page,'Cancel').click(); await accountWithoutManagement(page);
  await manage.click(); await management(page).waitFor();
  await management(page).getByRole('button',{name:'Remove number',exact:true}).click();
  await heading(page,'Remove your mobile number?');
  assert.equal(await page.evaluate(()=>window.clerkFixture.calls.filter(c=>c.method==='startVerification').length),2);
  assert.deepEqual(requests,['GET'],'No removal mutation or extra account fetch');
  await button(page,'Back').click(); await accountWithoutManagement(page);
  await page.locator('.account-row').filter({hasText:'Signed-in devices'}).getByRole('button',{name:'Manage',exact:true}).click();
  await heading(page,'Signed-in devices'); assert.equal(new URL(page.url()).pathname,'/account/devices');
  await page.getByText('This device',{exact:true}).waitFor();
  await page.getByText('Mobile · Safari').waitFor();
  await button(page,'Sign out other devices').waitFor();
  await page.evaluate(()=>window.clerkFixture.queue('revoke',{reverify:true}));
  await page.locator('.other-devices .device-session').first().getByRole('button',{name:'Sign out',exact:true}).click();
  await heading(page,'Verify your identity');
  await proof(page); await heading(page,'Signed-in devices');
  assert.equal(await page.evaluate(()=>window.clerkFixture.calls.filter(c=>c.method==='revoke').length),1,
    'A provider challenge forces OTP despite recent fva and never retries revocation automatically');
  await page.locator('.other-devices .device-session').first().getByRole('button',{name:'Sign out',exact:true}).click();
  await page.getByText('No other signed-in devices.',{exact:true}).waitFor();
  assert.equal(await button(page,'Sign out other devices').count(),0,'The bulk action hides when no other devices remain');
  await button(page,'Back').click(); await heading(page,'Account settings');
  await page.evaluate(()=>window.clerkFixture.queue('getSessions',{fail:true}));
  await page.locator('.account-row').filter({hasText:'Signed-in devices'}).getByRole('button',{name:'Manage',exact:true}).click();
  await heading(page,'Signed-in devices');
  await page.getByText('Signed-in devices could not be loaded.',{exact:true}).waitFor();
  await button(page,'Retry').click();
  await page.getByText('This device',{exact:true}).waitFor();
  await button(page,'Back').click(); await heading(page,'Account settings');
  await page.clock.fastForward(300000);
  const paths=[['/account/phone/remove','Verify your identity'],['/account/devices','Signed-in devices'],['/account/email','Email change is unavailable'],['/account/remove','Account removal is unavailable']];
  for(const [path,title] of paths) {
   await visit(page,`${path}?signed=1`); await heading(page,title);
   assert.equal(new URL(page.url()).pathname,path);
   await page.reload({waitUntil:'domcontentloaded',timeout:60000}); await heading(page,title);
   await visit(page,`${path}?signed=0`); await heading(page,'Sign in'); assert.equal(new URL(page.url()).pathname,'/sign-in');
  }
  await visit(page,'/account?signed=1'); await heading(page,'Account settings');
  await manage.click(); await management(page).getByRole('button',{name:'Remove number',exact:true}).click();
  await heading(page,'Verify your identity'); await page.goBack(); await accountWithoutManagement(page);
  await page.goForward(); await heading(page,'Verify your identity');
  await visit(page,'/account?signed=1'); await heading(page,'Account settings');
  await manage.click(); await management(page).getByRole('button',{name:'Remove number',exact:true}).click();
  await heading(page,'Verify your identity');
  await proof(page); await heading(page,'Remove your mobile number?');
  await button(page,'Remove number').click();
  await heading(page,'Account settings'); assert.equal(new URL(page.url()).pathname,'/account');
  assert.ok(requests.includes('DELETE'),'Removal issues the DELETE mutation');
  assert.equal(await mobile.getByRole('button',{name:'Manage',exact:true}).count(),0);
  await button(page,'Add').waitFor();
  await visit(page,'/account/phone/remove?signed=1'); await heading(page,'Account settings');
  assert.equal(new URL(page.url()).pathname,'/account');
  await page.close();
  console.log(`PASS ${width}: modal, Escape/focus, both OTP gates, five-minute reuse/expiry, removal mutation, devices, routes/history`);
 }
 assert.deepEqual(errors,[]);
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
