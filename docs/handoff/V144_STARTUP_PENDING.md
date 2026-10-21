**已完成：以下为历史暂停记录。** 默认程序已更新至1.4.4，最新状态与证据见V144_STARTUP.md及v144_startup_evidence.json。用户后续取消额度百分比暂停要求，不再据旧阈值停工或重放任务。

# v1.4.4 校徽归位动画被跳过：已复现，补丁待交付

2026-10-20，用户报告开机校徽缩放平移不见。当前默认程序仍为1.4.3，未修改运行源码、未构建或替换1.4.4，不得误报已交付。用户最新额度规则剩余45%即used>=55暂停；本轮额度工具连续返回“Could not read current usage limits”，不能猜测当前剩余。暂时仅做了小范围读取、复现和私有测试补丁，没有开展新一轮大量构建/回归。恢复条件：额度可读取且used<55即可继续；若used>=55保存当轮reset并待窗口重置恢复，不把旧5%或旧reset套用。

## 已取得的新证据

目录`C:/Users/cjt16/.codex/tmp/ubaa-v144-startup-20261020`：

- `reproduce.py`启动当前默认真实编译1.4.3的独立headless+smoke-profile（私有合成配置），用标准Playwright/Edge将fonts.googleapis.com字体CSS请求保持pending，其余外网中止；不使用真实账号、不发送学校请求，finally经/api/exit退出自建进程。
- `before-font-pending.json`：startupResult=boot-watchdog，phases仅drawing/resetting，emblemTransformSeen=false。真实编译成品中的现有脚本等待window.load，非必要字体资源一直等待导致16秒启动守卫直接删除动画层，未进入flying或burst。证明这是可复现的丢失路径，不假定用户设备的唯一原因。
- `startup-before.js`原始脚本，`startup-after.js`私有待应用补丁。仅将整页load就绪事件换为DOMContentLoaded，再沿用原有两次RAF首帧就绪；清理对应监听。校徽/校名/红字/粒子时间线、transform和所有业务不改，学校网络与字体/图片完成不应阻塞界面首帧就绪。
- `reproduce-after.py`与`after-font-pending.json`：同一成品、同一字体pending条件，仅由测试路由替换上述JS资产，结果complete，phases为drawing/flying/burst，emblemTransformSeen=true。此为测试补丁验证，**不是1.4.4已编译或原生实看通过**。两个自建进程均已正常退出。

## 恢复后必须完成

1. 先检查最新用户消息/本文件/项目外progress.json/当前源码，避免重复；若新交付已被其他操作完成不得覆盖。独立修复按用户规则升**1.4.4**，本地1.4.3为直接基线，当前公开GitHub仍1.3.9，不能重放旧发布。
2. 在项目外建立仅公开源码的精确1.4.3快照，保留默认/便携/dist和旧交接证据。将`startup-after.js`与当前脚本核对后应用；不要直接修改已交付EXE或把原型页面覆盖正式HTML。不要重建未改的TD签发器，不生成新私钥。
3. 修正`scripts/notice_acceptance.cjs`中“图片pending必须等待重画”的旧测试期望：非必要图片与字体未完成不该阻塞归位。增加持续pending字体/图片、显式检查真实校徽位置/尺寸趋近左上角logo、flying/burst/complete顺序、红字校名同步模糊淡出与清理的回归；保留慢本地脚本/未就绪的必要超时退路、减少动态、隐藏恢复、窗口尺寸、缺资源与首次登录/免责声明的保护。不要让启动动画改动触发任何学校请求或强制提交/焦点操作。
4. 统一core/version.py、run说明、HTML版本/cache参数、README候选、Mac spec、installer/setup.iss、version_info.txt、verify_compiled/native_service和相关测试中的版本元数据；不替换历史测试证据的旧版本字符串。执行check_release_format.py --tag v1.4.4。
5. 全回归（合成Mock），逐文件/编译模块验证除启动呈现/测试/版本外原认证、课堂、Boya、TD/许可/更新/渲染暂停代码保持。编译后验证、实际Windows computer-use检查缩放平移归位而非只看静态校徽或主界面；准确记录是否有原生连续录像，不能把浏览器样本冒充原生视频。现有1.4.3的289/79/95/30模块21资源仅基线，不能当本次通过。
6. 按现有隐私流程扫描源码/Git可达对象及解包成品，保留真实配置/图库/授权/签发私钥。受控备份+原子替换根默认EXE、新版本便携、dist；不杀用户程序，若占用如实说明。检查同级`C:/Users/cjt16/Desktop/Github库`预期未提交改动后同步本地源码/交接，不覆盖用户修改、不提交推送发布。旧1.4.3 final-local.py/followup deliver脚本不得直接重跑。
7. README只介绍项目，更新日志只在Release；同步AGENTS、交接当前状态和准确机器证据。无新Setup/macOS/Linux原生验收如实写，禁止WSL、微信恢复及窗口遮挡停绘。完成并核验后删除续作安排。

这次故障与已交付的TD照片分组、自然月离线激活和免费提示无关，不借机修改这些业务。近期需求核对报告中的只读次数/当前官方规则源/外部验收等未完成项继续保留，不因本启动修复宣称已补齐。
