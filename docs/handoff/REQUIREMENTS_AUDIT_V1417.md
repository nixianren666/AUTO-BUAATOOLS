# v1.4.17 上传前需求核对

接续[全对话需求核对](REQUIREMENTS_AUDIT_20261024.md)、[1415需求](REQUIREMENTS_AUDIT_V1415.md)及本轮全部插话；已完成与撤销不重放。

| 本轮要求 | 最终证据 |
|---|---|
| ReadTimeout repeated alerts and unnecessary preflight load | 最终同提交源码、成品及交付验收，详见发行记录与机器证据 |
| Missed reminder and full WeChat lifecycle audit | 最终同提交源码、成品及交付验收，详见发行记录与机器证据 |
| Expected no-write full/window stop distinguished from genuine errors | 最终同提交源码、成品及交付验收，详见发行记录与机器证据 |
| Student/background isolation and no loss of normal automation | 最终同提交源码、成品及交付验收，详见发行记录与机器证据 |
| Final all-client/source/privacy/data preservation/release checks | 最终同提交源码、成品及交付验收，详见发行记录与机器证据 |
| 各学生后台常规/博雅/TD及微信不依赖前台选择 | 同提交558源码134浏览器、实际成品后台和各学生独立合同；真实其他学生未发送测试 |
| 博雅切学生缓存与迟到响应隔离 | 134浏览器与最终9项原生观察中的学生切换；旧缓存逻辑保留，未知后台状态诚实提示 |
| target_filled正常不推送 | 实际内嵌博雅分类11；正常满额/合法窗口变化另11，实际拒绝仍提示 |
| 平台内和外部自主退课不自动抢回 | 实际内嵌退课15；外部限已成功观察的完整同范围快照，未知历史不能反推 |
| 仅常规本学期整门课暂停且手动保留 | 实际内嵌单课14、最终原生暂停和第二学生隔离、触控19 |
| 密集重复刷新日志去重但不取消同步 | 实际内嵌日志6，原读取/认证/调度语义保持 |
| 耕趣农场劳动课全系列永久不自动抢 | 实际内嵌永久系列3，名称归一化与最终自动提交前守卫 |
| README突出TD与微信、侧栏三步与绿色成功标记、可选课前提醒 | 原功能保持；源码提醒17/通知结果25与最终触控19/原生微信步骤观察 |
| 无头触控手机专用布局、平板电脑原布局与玻璃风格 | 四平台134浏览器与最终成品触控19、真实Windows9；不等于实体Safari |
| SSO/TD授权配对时窗预算、首次密码恢复、STATUS2无课日窄修复 | 实际内嵌网络30/TD102、源及成品各13管理和7首次设置恢复 |
| 服务器彻底清理重装但保数据、指定管理密码 | 先前已完成不重跑；本次新备份应用更新、3学生及30保留检查/IP与HTTPS各13 |
| 宿主稳定、其他服务/网络/资源上限不改 | 同一boot、其他服务/容器/配置及30保留检查；未压测，不保证硬件永久稳定 |
| 全部插话接续原任务、上传前核对全部既有需求 | 接续20261024及V1415逐项审计，本表与明确外部边界；撤销功能不恢复，已完成交付不重复 |
| 本人身份/隐私/源码成品一致/15附件及旧发行保留 | 39模块24资源、隐私与最终owner身份门禁，15附件同摘要后发布，13旧发行复核 |
| 本次无视额度限制继续 | 2026-10-31用户最新授权已记入progress，关闭本次旧45%暂停 |

此前需求完整保留；15附件/Latest/新旧更新识别/旧发行保持通过。外部边界：Real school end-to-end behavior, read-only TD count API and current complete autumn rules remain unverified; no real school operations in tests；Physical Safari, user macOS/Linux desktop reboot and hardware longevity are not established by CI/browser emulation；Tencent error -2 is not a proven fixed TTL; new context and API submission do not guarantee delivery; no permanent proactive delivery promise；Individual historic reminder from the old registration-only format has no recoverable exact send result；No real multi-day or real scheduled preclass reminder receipt claim; owner test receipt is a separate test；No WSL, real CAPTCHA solving, personal declaration signing, new key generation or maintainer issuer distribution；Owner independent encrypted key backup and contributor sidebar caching remain external conditions。
