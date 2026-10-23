/* Actual HTTP/cookie/CSRF first setup and recovery on a disposable empty profile. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const [url,browserPath,report]=process.argv.slice(2),checks=[];
  const browser=await chromium.launch({headless:true,...(browserPath?{executablePath:browserPath}:{})});
  const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,reducedMotion:'reduce'});
  await context.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  try {
    await page.goto(url+'#setup='+encodeURIComponent(process.env.BUAA_ACCEPTANCE_SETUP),{waitUntil:'domcontentloaded'});
    await page.locator('#managementConfirm').waitFor({state:'visible'});
    assert.equal(new URL(page.url()).hash,'');checks.push('private-setup-fragment-removed-before-further-use');
    assert.equal(await page.locator('#managementForgot').isVisible(),false);
    for(const viewport of [{width:320,height:568},{width:390,height:844},{width:844,height:390}]){
      await page.setViewportSize(viewport);
      for(const id of ['managementPassword','managementConfirm']){
        await page.locator('#'+id).focus();await page.locator('#'+id).scrollIntoViewIfNeeded();
        const box=await page.locator('#'+id).boundingBox();
        assert.ok(box.x>=-1&&box.x+box.width<=viewport.width+1,JSON.stringify(box));
      }
    }
    await page.setViewportSize({width:390,height:844});checks.push('phone-setup-fields-fit-and-hidden-controls-stay-hidden');
    await page.locator('#managementPassword').fill('synthetic-first-password');
    await page.locator('#managementConfirm').fill('synthetic-first-password');
    await page.locator('#managementLoginSubmit').click();
    await page.locator('#managementRecoveryCode').waitFor({state:'visible'});
    const recovery=await page.locator('#managementRecoveryCode').inputValue();assert.ok(recovery.length>=40);
    await page.locator('#managementLoginSubmit').click();
    assert.equal(await page.locator('#managementLoginModal').isVisible(),true);
    await page.locator('#managementRecoverySaved').check();await page.locator('#managementLoginSubmit').click();
    await page.locator('#managementLoginModal').waitFor({state:'hidden'});checks.push('first-password-recovery-code-and-explicit-save-confirmation');
    assert.equal(await page.locator('#managementRecoveryCode').inputValue(),'');checks.push('recovery-secret-cleared-from-dom-after-acknowledgement');
    await page.evaluate(()=>{void changeManagementPassword();});
    await page.locator('#managementCancel').waitFor({state:'visible'});
    await page.locator('#managementCancel').click();
    await page.locator('#managementLoginModal').waitFor({state:'hidden'});
    assert.equal((await context.request.get(url+'api/accounts')).status(),200);
    assert.equal(await page.locator('#managementProof').inputValue(),'');checks.push('cancel-password-change-keeps-original-session-and-clears-fields');
    const session=await (await context.request.get(url+'api/session')).json();
    assert.ok(session.csrf);await context.request.delete(url+'api/session',{headers:{'X-BUAA-CSRF':session.csrf}});
    await page.reload({waitUntil:'domcontentloaded'});await page.locator('#managementForgot').waitFor({state:'visible'});
    await page.locator('#managementForgot').click();
    await page.locator('#managementProof').fill(recovery);
    await page.locator('#managementPassword').fill('synthetic-reset-password');await page.locator('#managementConfirm').fill('synthetic-reset-password');
    await page.locator('#managementLoginSubmit').click();await page.locator('#managementRecoveryCode').waitFor({state:'visible'});
    assert.notEqual(await page.locator('#managementRecoveryCode').inputValue(),recovery);
    await page.locator('#managementRecoverySaved').check();await page.locator('#managementLoginSubmit').click();
    await page.locator('#managementLoginModal').waitFor({state:'hidden'});checks.push('real-recovery-reset-rotates-recovery-code');
    const old=await context.request.post(url+'api/session',{data:{password:'synthetic-first-password'}});assert.equal(old.status(),401);
    const good=await context.request.post(url+'api/session',{data:{password:'synthetic-reset-password'}});assert.equal(good.status(),200);
    checks.push('old-password-rejected-new-password-accepted');
    assert.equal(errors.length,0,errors.join('\n'));
    fs.writeFileSync(report,JSON.stringify({passed:true,checks,script_errors:errors,school_writes:0},null,2));
  }catch(error){fs.writeFileSync(report,JSON.stringify({passed:false,checks,script_errors:errors,error:error.message},null,2));throw error;}
  finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
