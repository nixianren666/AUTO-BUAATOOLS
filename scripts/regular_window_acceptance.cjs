/* Render the real attendance UI at deterministic China-time boundaries. */
const assert = require('node:assert/strict');
exports.verifyRegularWindow = async (page, check) => {
  const render = async (offset, end='2026-10-17 10:00:00', status=0) => page.evaluate(({offset,end,status}) => {
    const original=Date.now;
    Date.now=()=>Date.parse('2026-10-17T09:00:00+08:00')+offset*1000;
    try { renderClassesList([{courseSchedId:'3001',courseName:'合成窗口验证课程',signStatus:status,classBeginTime:'2026-10-17 09:00:00',classEndTime:end}]); }
    finally { Date.now=original; }
  }, {offset,end,status});
  await check('regular-ui-before-preclass-window-disabled', async()=>{
    await render(-601); assert.equal(await page.locator('[data-action="regularSign"]').isDisabled(),true);
  });
  await check('regular-ui-ten-minute-start-and-inclass-enabled', async()=>{
    for (const offset of [-600,-1,0,1,1800,3600]) {
      await render(offset); assert.equal(await page.locator('[data-action="regularSign"]').isDisabled(),false,`offset ${offset}`);
    }
  });
  await check('regular-ui-lesson-end-and-unknown-end-closed', async()=>{
    await render(3601); assert.equal(await page.locator('[data-action="regularSign"]').isDisabled(),true);
    for(const end of [null,'invalid','2026-10-17 08:00:00']) {
      await render(1,end);assert.equal(await page.locator('[data-action="regularSign"]').isDisabled(),true);
      await render(-1,end);assert.equal(await page.locator('[data-action="regularSign"]').isDisabled(),false);
    }
  });
  await check('regular-ui-signed-and-unknown-status-never-resubmit', async()=>{
    await render(60,undefined,null);assert.equal(await page.locator('[data-action="regularSign"]').isDisabled(),true);
    await render(60,undefined,1);assert.equal(await page.locator('[data-action="regularSign"]').count(),0);
    assert.match(await page.locator('#classesFeed').textContent(),/已签到/);
  });
};
