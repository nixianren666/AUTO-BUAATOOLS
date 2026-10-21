> 当前状态已更新：默认/便携/dist为最终1.4.9；解锁后12项实际点击观察与隐私收尾已完成。先读[V149_SSO.md](V149_SSO.md)，以下为历史过程，禁止重复编译或交付。

# v1.4.9 SSO适配进行中（未交付）

2026-10-21用户明确要求重新分析[BUAASubnet/UBAA](https://github.com/BUAASubnet/UBAA/)，适配学校当天更改后的SSO，修复无法拉常规课表和博雅数据，完整测试。不是重新进行已结束的UU远程闪烁诊断，不改渲染/美术/TD许可或学校提交策略。

## 当前证据与源码状态

- 已固定上游main `155e8b56ae76348e67c70414e3a9ab7fa54f2dda`，对应登录修复`65000130309a4a819675d7774b33bdeb7f4d2cc7`。与上次基线`e8a397f`比较共23个文件，认证核心变化在CasTransport和LocalConnectionAuth；后续希冀独立修复不属于本软件业务。克隆在项目外`ubaa-v149-sso-20261021/upstream`。
- 上游当日审查见`docs/_audit/2026-10-21-login-har.md`：主要是UC→HTTP SSO→HTTPS升级→UC ticket回调。普通密码表单字段未改，没有证据需要新增指纹遥测或改密码加密。上游弃用中转，本软件原本只支持直连/WebVPN，不导入其旧服务端中转实现。
- 本次真实无账号只读GET证实UC `/api/login`返回302到`http://sso.buaa.edu.cn/login`；HTTPS SSO登录页200且有HSTS。未用真实配置/凭据，没有学校业务写请求，原始响应/票据不入项目。
- 生产基线的`trusted_url`会拒绝这个HTTP目标，直连和WebVPN包装均可复现。原客户端6条合成认证路径全部失败；第一轮传输修正后6条通过，但Mock还未严格检验票据Cookie及完整业务查询，不称整链路验收。
- 已新增`core/cas_transport.py`：只升级精确SSO默认HTTP端口，保留嵌套service编码，解包网关后校验再按模式包装。原`domain.trusted_url`仍拒绝HTTP，域名/端口/TLS安全规则未放宽。
- 当前已改`core/iclass.py`重定向解析、UC激活路由与loginName路径，`core/boya_client.py`密码/换票重定向；新增`tests/test_sso_transport_upgrade.py`。5项新传输单测＋原core9＋原安全23，共37通过。初次安全用例把userinfo先交给通用VPN编码器，编码器已丢弃userinfo，导致错误测试期望失败；修正为显式构造含userinfo的加密恶意authority后通过，不能误称修复了生产漏洞。
- 第一轮全源码unittest319项通过，日志在项目外`source-first.txt`，结束有sqlite连接ResourceWarning待归因；这不覆盖新增完整认证及最终成品。尚未做全认证重构/前端联调/编译/原生验收/交付，版本元数据及默认EXE仍1.4.8原哈希`0140c67cded79b6d2f57a7569ad1bf2c7c7740d13c93ca50807c17fca55bb123`；无1.4.9成品。127份公开源码基线和哈希在项目外baseline，原EXE备份沿用已核验的上一诊断目录。

## 全链路复核清单（继续执行）

1. 共同传输层：HTTP SSO原始/网关/相对/协议相对地址；保持service原编码；不出网关、不跟随陌生域名/非默认HTTP端口、无凭据外泄，TLS校验保持；验证码和学校风险提示不能绕过。
2. IclassClient：初始预登录302目前直接转UC激活，没有完整跟随；主POST和密码过期continue应共同限跳、308/缺Location/循环/非200/残留登录表单有明确失败，不留下旧成功身份。UC严格校验身份及票据Cookie后再接MyCenter→业务session→只读课表；不要更改签到端点/预算/规则。
3. BoyaClient：`acquire_token`的UC激活目前只GET且忽略异常，尚未改为完整限跳；密码expiry continue的后续链仍需复核。正确复用SSO Cookie，保留secure/expiry属性，按每学生隔离；只认BYKC目标的非空token，实际只读查询后才报ready，不泄露token/Location。
4. API/调度/UI：主登录、恢复登录、常规重连和博雅独立续期都必须用新链路，保持账号锁、维护态、60秒退避和验证码转人工；账号切换/移除/失败不展示迟到数据或假成功。核对`server/app.py`的sync_boya_login、connect_single_account、/api/login、/api/classes和博雅刷新；`core/*scheduler.py`及前端状态/日志同验。失败保留旧数据标stale，不能清成“今天没课”。
5. 新增严密Mock：直连/WebVPN、已有Cookie/密码登录、UC回调真实Cookie、Boya换票/过期重登、课表及博雅课池/已选/统计链、验证码/错密/续期/恶意跳转/超时/循环/并发/多账号；网络写入测试只合成，无真实考勤。上游测试通过不等于本软件通过。
6. 全回归后升1.4.9并统一版本/发行格式；编译成品模块/资源与源码一致、最终EXE模拟界面及Windows实际Computer Use；隐私扫描/公开Git对象；保留真实配置图库许可私钥备份受控更新默认/便携/dist和同级Git本地源码。旧314等不能冒充新验收。无新Setup/Mac/Linux原生则如实记录，不推送/发布、不终止用户程序、不改签发器密钥、不用WSL。

首次完整实际学校只读验收尚未进行；不能以匿名GET或合成测试宣称真实账号已经恢复。用户配置不是测试样例，后续必要人工验证应在可审阅候选完成后进行。

项目外进度：`C:/Users/cjt16/.codex/tmp/ubaa-v149-sso-20261021/progress.json`。当前用户剩余45%暂停规则继续有效，used>=55保存当前reset后等待五小时窗口重置满额续作；不要把旧无限额或5%规则恢复。

## 2026-10-21最新暂停检查点（覆盖上文旧进度/额度规则）

用户最新明确剩余20%即停止；真实五小时used=80%、reset=1792587408，已保存暂停并建立当前对话续作ubaa-v1-4-9-sso。此前45%/无限额不再生效。

源码已扩展完整UC票据跳转、SSO精确HTTPS升级、验证码手动输入/绑定账户通道、过期继续、Cookie属性保留、Boya token严格提取及退避/实际只读就绪；新增传输5项、完整认证13项及浏览器4项。还修复httpx重复大小写Authtoken被合并成重复值的问题。源版本元数据已1.4.9，默认/便携/dist仍1.4.8，无149成品，未交付/未发布。

最新source-final-first全源码332项0失败，集成浏览器新增4项通过。但隔离审计记录1次BoyaScheduler线程尝试外网，被阻止，未实际连接学校；尚未定位全局调度器由哪项测试启动，不能说已实现零外网意图。扩展45帧调用栈只有线程入口至_check_account/query_chosen_courses，继续查新API测试暴露合成账号时全局调度器是否已在运行。不要绕过隔离器。另需审查手动SSO失败是否留下旧Boya token令to_dict误显示已认证，未修不能称已通过。

已完成的测试不是最终交付证据：尚需上述边界、多账户/恢复、最终回归、编译模块资源一致/成品回归、实际Windows Computer Use与隐私扫描、保留配置图库许可私钥的默认/便携/dist替换和同级Git本地运行源码同步。没有真实账号业务只读验收，不冒称真实学校已恢复。保持原可见渲染、TD许可和学校提交策略，不重做旧闪烁诊断、不推送发布、不重建签发器。
