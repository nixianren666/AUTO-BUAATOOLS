/* Browser regressions for view-local Boya filters, using synthetic data only. */
const assert = require('node:assert/strict');

async function verifyBoyaFilters(page, check) {
  const saved = await page.evaluate(() => ({
    state: Object.fromEntries(['boyaTab', 'boyaCourses', 'boyaSelected', 'boyaCategoryFilter', 'boyaSelectedTimeFilter', 'boyaAutoSignOnly', 'boyaAvailableOnly', 'boyaSearchKeyword', 'boyaDataStale'].map(k => [k, appState[k]])),
    search: document.getElementById('boyaSearchInput').value,
    classes: [...document.querySelectorAll('#boyaFilterMatrix button, #selectedTimeFilterStrip button, #tabBoyaAll, #tabBoyaSelected')].map(e => e.className)
  }));
  const course = (id, category, available, autonomous, past = false) => ({
    id, courseId: id, courseName: `filter-fixture-${id}`, category_key: category,
    teacherName: 'synthetic-teacher', coursePosition: 'synthetic-room',
    courseStartDate: past ? '2000-01-01 08:00:00' : '2099-01-01 08:00:00',
    courseEndDate: past ? '2000-01-01 10:00:00' : '2099-01-01 10:00:00',
    courseSelectStartDate: '2000-01-01 00:00:00', courseSelectEndDate: '2099-01-01 07:00:00',
    capacity_available: available, capacity_current: available ? 1 : 20, capacity_maximum: 20,
    autonomous_config_valid: autonomous, can_sign_in: false, can_sign_out: false, can_drop: false
  });
  const pool = [course(99001, '德育', false, false), course(99002, '美育', false, true), course(99003, '劳育', true, false), course(99004, '美育', true, true)];
  const selected = [pool[0], { ...course(99005, '安全健康', false, false), capacity_current: null, capacity_maximum: null }, course(99006, '美育', false, true, true)];
  const poolRoute = r => r.fulfill({ json: { courses: pool, stale: false } });
  const selectedRoute = r => r.fulfill({ json: { selected, stale: false } });
  const mutations = [];
  const onRequest = r => { if (!['GET', 'HEAD'].includes(r.method())) mutations.push(new URL(r.url()).pathname); };
  const names = async expected => assert.deepEqual(await page.locator('#boyaCoursesFeed .feed-title').allTextContents(), expected.map(id => `filter-fixture-${id}`));
  const setPoolFilters = async (auto, available, category = '全部') => {
    await page.locator('#tabBoyaAll').click();
    const state = await page.evaluate(() => ({ auto: appState.boyaAutoSignOnly, available: appState.boyaAvailableOnly }));
    if (state.auto !== auto) await page.locator('#btnFilterAutoSign').click();
    if (state.available !== available) await page.locator('#btnFilterAvailable').click();
    await page.locator('#boyaFilterMatrix .filter-category-group button').filter({ hasText: category === '全部' ? '全部类别' : category }).click();
  };
  try {
    await page.route('**/api/boya/courses**', poolRoute);
    await page.route('**/api/boya/selected**', selectedRoute);
    page.on('request', onRequest);
    await page.evaluate(({ pool, selected }) => {
      Object.assign(appState, { boyaCourses: pool, boyaSelected: selected, boyaSearchKeyword: '', boyaSelectedTimeFilter: 'upcoming', boyaAutoSignOnly: false, boyaAvailableOnly: false, boyaCategoryFilter: '全部', boyaDataStale: false });
      document.getElementById('boyaSearchInput').value = '';
      document.querySelectorAll('#boyaFilterMatrix .feature-toggle-pill').forEach(e => e.classList.remove('active'));
      filterSelectedTime('upcoming', document.getElementById('btnFilterOngoingUpcoming'));
      switchBoyaTab('all');
    }, { pool, selected });
    for (const [auto, available, expected] of [[false,false,[99001,99002,99003,99004]],[true,false,[99002,99004]],[false,true,[99003,99004]],[true,true,[99004]]]) {
      await check(`pool-filter-combination-${auto}-${available}-stays-local`, async () => {
        await setPoolFilters(auto, available);
        await names(expected);
        await page.locator('#tabBoyaSelected').click();
        await names([99001,99005]); // Full, unknown-capacity and offline selected courses remain visible.
        assert.equal(await page.locator('#boyaFilterMatrix').isVisible(), false);
        assert.equal(await page.locator('#selectedTimeFilterStrip').isVisible(), true);
        await page.locator('#tabBoyaAll').click();
        await names(expected);
        assert.deepEqual(await page.evaluate(() => [appState.boyaCourses, appState.boyaSelected]), [pool,selected]);
        assert.equal(await page.locator('#btnFilterAutoSign').evaluate(e => e.classList.contains('active')), auto);
        assert.equal(await page.locator('#btnFilterAvailable').evaluate(e => e.classList.contains('active')), available);
      });
    }
    await check('hidden-pool-category-does-not-filter-selected', async () => {
      await setPoolFilters(true, true, '美育'); await names([99004]);
      await page.locator('#tabBoyaSelected').click(); await names([99001,99005]);
      await page.locator('#btnFilterPast').click(); await names([99006]);
      await page.locator('#btnFilterAllSelected').click(); await names([99001,99005,99006]);
      await page.locator('#tabBoyaAll').click(); await names([99004]);
    });
    await check('selected-time-filter-does-not-filter-pool', async () => {
      await page.locator('#tabBoyaSelected').click(); await page.locator('#btnFilterPast').click(); await names([99006]);
      await setPoolFilters(false,false); await names([99001,99002,99003,99004]);
      await page.locator('#tabBoyaSelected').click(); await names([99006]);
    });
    await check('shared-visible-search-works-on-both-tabs-and-clears', async () => {
      await page.locator('#btnFilterAllSelected').click();
      await page.locator('#boyaSearchInput').fill('99001'); await names([99001]);
      await page.locator('#tabBoyaAll').click(); await names([99001]);
      await page.locator('#boyaSearchInput').fill('no-synthetic-match'); await names([]);
      await page.locator('#tabBoyaSelected').click(); await names([]);
      assert.match(await page.locator('#boyaCoursesFeed').textContent(), /当前条件下暂无匹配的已选课程/);
      assert.match(await page.locator('#boyaCoursesFeed').textContent(), /已有选课记录/);
      await page.locator('#boyaSearchInput').fill(''); await names([99001,99005,99006]);
    });
    await check('empty-time-subset-is-not-an-empty-enrollment', async () => {
      await page.evaluate(() => { appState.boyaSelected = appState.boyaSelected.filter(c => c.id !== 99006); });
      await page.locator('#btnFilterPast').click(); await names([]);
      assert.match(await page.locator('#boyaCoursesFeed').textContent(), /当前条件下暂无匹配/);
      assert.equal(await page.locator('#countBoyaSelected').textContent(), '2');
      await page.locator('#btnFilterAllSelected').click(); await names([99001,99005]);
    });
    await check('stale-cache-with-no-search-match-is-not-missing-data', async () => {
      await page.evaluate(() => { appState.boyaDataStale = true; });
      await page.locator('#boyaSearchInput').fill('no-synthetic-match'); await names([]);
      assert.match(await page.locator('#boyaCoursesFeed').textContent(), /当前条件下暂无匹配/);
      await page.locator('#boyaSearchInput').fill(''); await names([99001,99005]);
    });
    await check('genuinely-empty-and-unsynced-enrollment-have-distinct-copy', async () => {
      await page.evaluate(() => { appState.boyaSelected = []; appState.boyaDataStale = false; renderBoyaFeed(); });
      assert.match(await page.locator('#boyaCoursesFeed .empty-title').textContent(), /^暂无已选修课程$/);
      await page.evaluate(() => { appState.boyaDataStale = true; renderBoyaFeed(); });
      assert.match(await page.locator('#boyaCoursesFeed .empty-title').textContent(), /尚未同步/);
    });
    await check('sign-in-cutoff-does-not-move-live-course-to-history', async () => {
      const facts = await page.evaluate(() => {
        const live = { courseStartDate: '2000-01-01 08:00:00', courseEndDate: '2099-01-01 10:00:00', courseSignConfig: { signEndDate: '2000-01-01 09:00:00', signOutEndDate: '2000-01-01 09:30:00' }, is_ended: false };
        return [isCourseEnded(live), isCourseEnded({ courseSignConfig: { signEndDate: '2000-01-01 09:00:00' } }), isCourseEnded({ courseSignConfig: { signOutEndDate: '2000-01-01 09:00:00' } }), isCourseEnded({ ...live, is_ended: true }), isCourseEnded({ courseEndDate: '2000-01-01 10:00:00' }), isCourseEnded({ courseEndDate: '2099-01-01', courseEndTime: '10:00:00' }), isCourseEnded({ courseEndDate: 'invalid' })];
      });
      assert.deepEqual(facts, [false,false,true,true,true,false,false]);
    });
    await check('refresh-keeps-view-local-filter-rules-and-raw-data', async () => {
      await page.locator('#boyaSearchInput').fill('');
      await setPoolFilters(true,true,'美育');
      await page.locator('#tabBoyaSelected').click(); await page.locator('#btnFilterAllSelected').click();
      await page.evaluate(() => fetchBoyaData(false)); await names([99001,99005,99006]);
      assert.deepEqual(await page.evaluate(() => [appState.boyaSelected.length,appState.boyaCourses.length]), [3,4]);
      await page.locator('#tabBoyaAll').click(); await names([99004]);
    });
    await check('filtering-never-submits-school-or-preference-writes', async () => assert.deepEqual(mutations, []));
  } finally {
    page.off('request', onRequest);
    await page.unroute('**/api/boya/courses**', poolRoute);
    await page.unroute('**/api/boya/selected**', selectedRoute);
    await page.evaluate(saved => {
      Object.assign(appState, saved.state);
      document.getElementById('boyaSearchInput').value = saved.search;
      switchBoyaTab(saved.state.boyaTab);
      [...document.querySelectorAll('#boyaFilterMatrix button, #selectedTimeFilterStrip button, #tabBoyaAll, #tabBoyaSelected')].forEach((e,i) => { e.className = saved.classes[i]; });
    }, saved);
  }
}
module.exports = { verifyBoyaFilters };
