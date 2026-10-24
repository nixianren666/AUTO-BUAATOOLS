# v1.4.14上传前需求核对

接续[此前全对话需求表](REQUIREMENTS_AUDIT_20261024.md)和本轮全部用户消息。此前已完成或撤销工作不重放；本版本最终验收及发布结果见[V1414_RELEASE.md](V1414_RELEASE.md)。

| 用户要求 | 本轮最终证据 |
|---|---|
| README首屏自动TD（Beta）及微信助手突出 | canonical README.md and synthetic assistant image; final source/archive integrity |
| 侧栏微信助手、学生独立选择、保留风格 | 117 browser contracts; actual final native window and compiled touch checks |
| 明显三步：扫码、发送开始接收、本人确认收信；绿字对勾 | binding/context/user-checkbox boundaries verified; API accepted never means received |
| 可选独立课前约15分钟提醒、课程教师时间地点校历周 | 17 actual embedded reminder contracts each platform; deadline/idempotence/failure/independent-reader coverage |
| 全部学生后台独立，查看学生不决定任务归属，博雅缓存保留 | prior1413 completed audit plus current440 source/117 browser/installed service regression; new reminder reader ignores active student |
| TD队列/安全窗/配对/共享预算/不确定不重放保持 | 102 actual embedded TD contracts per platform; no real school writes |
| 原SSO/网络退避/人工验证码暂停与空课日窄修复保持 | 30 embedded network contracts and full source regressions; no real CAPTCHA solved |
| 无头管理初始化及恢复、原服务器密码保持 | source/compiled7 setup and13 management flows; live IP and trusted proxy login/logout; .env hash unchanged |
| 手机专用布局、平板/桌面原排布与玻璃风格保持 | 117 browser checks and15 final compiled touch checks plus screenshots; not physical Safari |
| 服务器清理重装已完成，不重复破坏数据；最新版仅应用更新 | prior clean reinstall handoff; current new program/profile rollback backup, existing volume/account/photo/license/password preservation audit |
| 各客户端、实际内嵌代码、安装服务容器及隐私/源码一致 | four same-commit CI jobs, release-gate/final-integrity/artifact-privacy |
| 发布前核对全部旧对话需求与新增消息 | prior complete conversation audit REQUIREMENTS_AUDIT_20261024.md, current V1414_PENDING and this explicit new-requirements audit |
| 额度剩余45%停止；本窗口用户继续例外，重置后恢复 | private progress current-window exception tied to reset1792839769 |

原9正式版、预发行与旧私有草稿保持；15附件/Latest摘要和真实新旧更新识别通过。外部条件仍开放：Reliable read-only TD count API and current complete official autumn rules/temporary closures；Actual user Mac third-party TUN root cause and real school acceptance；Physical phone Safari and user multi-platform reboot/long-term hardware stability；Owner independent-media encrypted private-key backup；GitHub contributor sidebar cache。新增提醒未由真人再次确认收信；接口接受不等于送达。
