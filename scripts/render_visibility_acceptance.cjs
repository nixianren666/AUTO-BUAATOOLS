/* Real-browser presentation checks. Never infer pixel stability from these alone. */
const assert = require('node:assert/strict');
async function verifyRenderVisibility(page, check) {
  const base = new URL(page.url()).origin;
  let originalGlass;
  const glassStyle = () => page.locator('#glassPopover').evaluate(e => ({
    blur:getComputedStyle(e).backdropFilter,
    tint:getComputedStyle(e).backgroundColor,
    reduced:matchMedia('(prefers-reduced-transparency: reduce)').matches,
    supported:CSS.supports('backdrop-filter','blur(8px)')
  }));
  await check('visible-glass-material-and-platform-transparency-preference', async () => {
    await page.locator('#glassControlBtn').click();
    originalGlass=await glassStyle();
    if (originalGlass.reduced) assert.equal(originalGlass.blur,'none');
    else if (originalGlass.supported) assert.match(originalGlass.blur,/blur\(8px\)/);
    await page.keyboard.press('Escape');
  });
  await check('visible-render-hints-never-rewrite-root-or-hide-cards', async () => {
    const count = await page.evaluate(async () => {
      let count = 0;
      const observer = new MutationObserver(records => { count += records.length; });
      observer.observe(document.documentElement, { attributes: true });
      for (let i=0; i<300; i++) {
        BUAARenderLifecycle.setNativeVisible(true, 'visible');
        dispatchEvent(new PointerEvent('pointermove', {clientX:400+i%200,clientY:450,pointerType:'mouse'}));
      }
      await new Promise(resolve => setTimeout(resolve, 100));
      observer.disconnect(); return count;
    });
    assert.equal(count, 0);
    assert.equal(await page.evaluate(() => document.querySelector('.origin-app-layout').getBoundingClientRect().width > 0), true);
  });
  await page.evaluate(() => {
    window.__hiddenPaints=0;
    window.__originalPaintMethods={};
    for (const name of ['fill','fillRect','clearRect','drawImage','stroke']) {
      const original=CanvasRenderingContext2D.prototype[name];
      window.__originalPaintMethods[name]=original;
      CanvasRenderingContext2D.prototype[name]=function(...args){window.__hiddenPaints++;return original.apply(this,args);};
    }
  });
  const beforeSize = page.viewportSize();
  try {
    await check('minimized-hint-stops-canvas-even-with-hidden-input-and-resize', async () => {
      await page.evaluate(() => BUAARenderLifecycle.setNativeVisible(false, 'minimized'));
      await page.waitForTimeout(100);
      const count = await page.evaluate(() => __hiddenPaints);
      await page.setViewportSize({width:1400,height:900});
      await page.evaluate(() => {for(let i=0;i<100;i++)dispatchEvent(new PointerEvent('pointermove',{clientX:500+i,clientY:450,pointerType:'mouse'}));});
      await page.waitForTimeout(450);
      assert.equal(await page.evaluate(() => __hiddenPaints),count);
    });
    await check('hidden-window-disables-blur-and-decorative-animations', async () => {
      const result=await page.evaluate(() => ({
        animations:document.getAnimations().filter(a=>a.playState==='running').length,
        filters:[...document.querySelectorAll('.origin-hero,.origin-nav-item,#glassPopover,.origin-modal-backdrop')].map(e=>[getComputedStyle(e).filter,getComputedStyle(e).backdropFilter]),
        bodyHidden:getComputedStyle(document.body).visibility==='hidden'||getComputedStyle(document.body).contentVisibility==='hidden'
      }));
      assert.equal(result.animations,0);assert.equal(result.bodyHidden,false);
      assert.ok(result.filters.every(([f,b])=>f==='none'&&b==='none'));
      assert.equal((await page.request.get(base+'/api/health')).ok(),true);
    });
    await check('restore-resumes-original-renderer-and-glass', async () => {
      await page.evaluate(() => BUAARenderLifecycle.setNativeVisible(true, 'visible'));
      await page.waitForTimeout(100);
      const count=await page.evaluate(() => __hiddenPaints);
      await page.waitForFunction(count => __hiddenPaints > count, count, {timeout:10000});
      assert.ok(await page.evaluate(() => __hiddenPaints)>count);
      assert.equal(await page.evaluate(() => document.documentElement.classList.contains('buaa-render-paused')),false);
      // Chromium platforms need not compute backdrop filters for display:none.
      // Compare a genuinely displayed panel, preserving accessibility fallback.
      await page.locator('#glassControlBtn').click();
      assert.deepEqual(await glassStyle(),originalGlass);
      await page.keyboard.press('Escape');
    });
    await check('tray-pause-and-restore-do-not-clear-view-data', async () => {
      const before=await page.evaluate(()=>({username:appState.activeUsername,tab:appState.boyaTab,selected:appState.boyaSelected.map(c=>c.courseId||c.id)}));
      await page.evaluate(()=>BUAARenderLifecycle.setNativeVisible(false,'tray'));
      const count=await page.evaluate(()=>__hiddenPaints);await page.waitForTimeout(350);
      assert.equal(await page.evaluate(()=>__hiddenPaints),count);
      await page.evaluate(()=>BUAARenderLifecycle.setNativeVisible(true,'visible'));
      assert.deepEqual(await page.evaluate(()=>({username:appState.activeUsername,tab:appState.boyaTab,selected:appState.boyaSelected.map(c=>c.courseId||c.id)})),before);
    });
  } finally {
    await page.evaluate(() => {
      BUAARenderLifecycle.setNativeVisible(true,'visible');
      for(const[name,method]of Object.entries(__originalPaintMethods))CanvasRenderingContext2D.prototype[name]=method;
      delete window.__originalPaintMethods;delete window.__hiddenPaints;
    });
    await page.setViewportSize(beforeSize);
  }
}
module.exports={verifyRenderVisibility};
