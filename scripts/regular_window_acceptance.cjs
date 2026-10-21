/* Render the real attendance UI at deterministic China-time boundaries. */
const assert = require('node:assert/strict');
exports.verifyRegularWindow = async (page, check) => {
  const render = async (offset, end='2026-10-17 10:00:00', status=0) => page.evaluate(({offset,end,status}) => {
    const original=Date.now;
    Date.now=()=>Date.parse('2026-10-17T09:00:00+08:00')+offset*1000;
    try {
      renderClassesList([{courseSchedId:'3001',courseName:'合成窗口验证课程',signStatus:status,classBeginTime:'2026-10-17 09:00:00',classEndTime:end}]);
      // Read the result atomically with this synthetic clock. Normal polling
      // must not replace the fixture between render and a separate locator call.
      const button=document.querySelector('[data-action="regularSign"]');
      return {disabled:button?.disabled??null,text:document.getElementById('classesFeed').textContent};
    }
    finally { Date.now=original; }
  }, {offset,end,status});
  await check('regular-ui-before-preclass-window-disabled', async()=>{
    assert.equal((await render(-601)).disabled,true);
  });
  await check('regular-ui-ten-minute-start-and-inclass-enabled', async()=>{
    for (const offset of [-600,-1,0,1,1800,3600]) {
      assert.equal((await render(offset)).disabled,false,`offset ${offset}`);
    }
  });
  await check('regular-ui-lesson-end-and-unknown-end-closed', async()=>{
    assert.equal((await render(3601)).disabled,true);
    for(const end of [null,'invalid','2026-10-17 08:00:00']) {
      assert.equal((await render(1,end)).disabled,true);
      assert.equal((await render(-1,end)).disabled,false);
    }
  });
  await check('regular-ui-signed-and-unknown-status-never-resubmit', async()=>{
    assert.equal((await render(60,undefined,null)).disabled,true);
    const signed=await render(60,undefined,1);assert.equal(signed.disabled,null);
    assert.match(signed.text,/已签到/);
  });
};
