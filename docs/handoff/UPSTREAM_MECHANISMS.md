# UBAA / AutoBoya 独立机制研究

研究日期：2026-10-13，北京时间。此次重新获取两套上游源码，从认证、协议、数据模型、调度、UI 和测试逐层分析。**本报告的技术结论不以 Antigravity 会话、旧助手说明或本项目代码注释为依据。** 最后单独对照当前工作区，明确哪些是本项目自行增加或改变的行为。

## 1. 证据范围与最重要的区分

| 对象 | 固定源码版本 | 本次核查范围 |
| --- | --- | --- |
| [BUAASubnet/UBAA](https://github.com/BUAASubnet/UBAA/tree/e8a397fcb35a68147eee65a94c66ffb84e2f09fe) | `e8a397fcb35a68147eee65a94c66ffb84e2f09fe`，2026-09-18 提交 | Kotlin 本地与服务端课堂签到、博雅实现、Compose 相关界面、模型、认证、对应测试和功能文档 |
| [DeNeRATe-cool/AutoBoya](https://github.com/DeNeRATe-cool/AutoBoya/tree/c8fc785bbc07178bfbd79d99b89b5358e021b23b) | `c8fc785bbc07178bfbd79d99b89b5358e021b23b`，0.1.5，2026-09-14 提交 | Python CLI、认证、加密、API、缓存、自动规则、后台循环、存储、55 项原有测试及 16 项独立探测 |
| 当前 AUTO-BUAATOOLS 工作区 | 此次读取的业务文件 SHA-256 见 [证据清单](upstream_mechanism_evidence.json) | `core/iclass.py`、`scheduler.py`、`boya_client.py`、`boya_crypto.py`、`boya_scheduler.py`、`server/app.py` |

这里研究的是 **iClass 常规课堂签到** 和 **BYKC 博雅课程系统**。不能把它们泛称为同一个“每日健康打卡/晨午检”系统；这两套链路有不同身份、接口、ID 和成功条件。

UBAA 提供界面触发的常规签到、博雅选退课和签到签退。此次核查的签到/博雅业务路径中，没有发现自动抢课、课前随机签到或常驻后台签到调度器。博雅详情页每 5 秒更新一次本地时钟以调整按钮，这是 UI 时间重算，不会自动发起选课/签到，也不是网络刷新。

AutoBoya 是博雅 CLI 和后台自动化工具，不包含 iClass 常规课堂签到。当前项目把两条协议链路组合起来，并自行增加常规课调度、博雅策略和桌面 UI；不能将这些扩展反推为上游原有行为。

## 2. 两套身份链路：SSO 登录不能代替业务登录

### 2.1 基础 SSO 和连接方式

二者均先建立北航 CAS/SSO Cookie 会话，再进入具体业务系统。登录页中的 `execution` 和隐藏字段参与表单提交；验证码出现时需要有效验证码，源码没有保证后台自动解决验证码。密码过期提示页可能走 `ignoreAndContinue` 继续认证，这仍取决于学校允许的页面流程。

UBAA 有 DIRECT、WEBVPN、SERVER_RELAY 三种路径：前两种由设备直接调用上游；中继模式由 UBAA 服务端持有学校会话，客户端通过自己的 API/JWT 调用服务器。**UBAA JWT、CAS Cookie、iClass sessionId、博雅 auth_token 是不同层的凭证。** `SigninRoutes` 从认证会话读取 schoolid；博雅路由使用 JWT 关联用户名，不能让任意请求随意指定另一个学生身份。

AutoBoya 默认 `use_vpn=True`，把学校地址转成 `https://d.buaa.edu.cn/...`。WebVPN 的固定 AES-CFB key/IV 用于网关主机名路由编码，路径同时编码 HTTP/HTTPS 及非标准端口，保留业务 path/query。它不是用户密码加密，也不是 BYKC 请求体加密，更不能替代有效网关 Cookie。AutoBoya 提交 SSO 表单后激活 UC，再访问博雅 CAS 入口，在重定向 URL/Location 中提取 `token`；一个入口失败再试空 token 入口，换票链最多 10 次重定向。

AutoBoya 的普通登录重定向处理使用嵌套 `while`，没有同样的次数上限；网络 timeout 是单次请求限制，不能证明循环重定向一定及时终止。UBAA iClass 登录名跳转设 8 次上限。

源码：[UBAA 本地认证](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/shared/src/commonMain/kotlin/cn/edu/ubaa/api/local/LocalConnectionAuth.kt)、[AutoBoya 认证](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/autoboya/auth.py)、[WebVPN 路由](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/autoboya/webvpn.py)。

### 2.2 会话保存与恢复

UBAA 本地 Cookie/会话按连接模式存储；Cookie 发包检查 domain/path/secure/expiry。iClass 另有按学生缓存的业务 session。服务端 SigninService 和 BykcService 支持空闲缓存清理并释放上下文；默认 30 分钟空闲阈值不是学校凭证有效期。

AutoBoya 默认数据根为 `~/.autoboya`，允许 `AUTOBOYA_HOME` 覆盖。密码优先使用系统 keyring；明确选择不安全存储时写入 secrets.json。`sessions/<user>.json` 保存博雅 token 和 Cookie JSON，并设置 mode 0600；这是文件权限措施，**内容没有凭证保险箱加密，Windows 下也不能将 chmod 等同于完整 ACL 防护**。恢复 Cookie 时只恢复 name/value/domain/path，没有完整保留 secure/expires。

每次 `ensure_bykc_client` 会新建客户端，发现保存的 token 即使用，没有先验证实际有效性。自动操作只有收到 `SessionExpired` 才强制重新登录并重做一次操作；后台没有验证码输入者，遇验证码会失败，需用户重新登录。未见自动操作路径及时关闭所有新建 HTTP 客户端的统一生命周期管理。

源码：[AutoBoya session](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/autoboya/session.py)、[存储](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/autoboya/storage.py)。

## 3. UBAA 常规课堂签到：完整调用链

### 3.1 从学校账号到课堂身份

1. 使用已登录 SSO Cookie 访问 `https://iclass.buaa.edu.cn:8346/?type=jumpMyCenter`。
2. 读取最终 URL 或 Location 中的 `loginName`；保持原始地址，仅发包时进行 WebVPN 包装，处理相对重定向并解包网关地址。
3. 请求 `https://iclass.buaa.edu.cn:8347/app/user/login.action`，参数是 `phone=loginName`、空 password、`userLevel=1`、`verificationType=2`、空 verificationUrl。
4. 要求 HTTP 成功且业务 `STATUS` 属于 `0/200/success`，取得 `result.id` 和 `result.sessionId`。

空 password 是这个已接入 SSO 的业务调用路径的实现，不说明未认证用户可凭学号任意登录。`loginName` 是业务身份映射结果；不能凭字段名字直接假定总是用户名/手机号/学号。

### 3.2 查询今天的排课

请求 `GET https://iclass.buaa.edu.cn:8347/app/course/get_stu_course_sched.action`：

- Header：业务 `sessionId`。
- Query：`id=课堂用户ID`、`dateStr=yyyyMMdd`。
- 今日日期取设备/服务器当前本地时区，没有强制 Asia/Shanghai。
- 课程 DTO 中名为 `courseId` 的值来自返回对象 **`id`**；提交时它实际代表 `courseSchedId`，即排课实例，不能替换成课程目录 ID。

### 3.3 获取服务器时间，再提交签到

| 连接模式 | 获取 timestamp | 提交签到 |
| --- | --- | --- |
| 校园网直连 | `http://iclass.buaa.edu.cn:8081/app/common/get_timestamp.action` | `http://iclass.buaa.edu.cn:8081/eschool/app/course/stu_scan_sign.action` |
| WebVPN 的原始业务目标 | `https://iclass.buaa.edu.cn:8347/app/common/get_timestamp.action` | `https://iclass.buaa.edu.cn:8347/app/course/stu_scan_sign.action` |

**8347 提交路径没有 `/eschool` 前缀。端口、协议、路径必须一起选择。** 上游本地/服务端实现和专门的 WebVPN Mock 测试均明确这一点。

签到提交为 POST 表单：Header `sessionId`，Query `courseSchedId + timestamp`，Form `id=课堂用户ID`。本链路没有博雅 GPS 经度纬度、Ak/Sk 等字段。timestamp 从接口取回原样使用；缺失就返回“获取服务器时间失败”，不会自行填一个本地时间继续提交。

成功要求同时成立：`STATUS ∈ {0,200,success}` 且 `result.stuSignStatus == 1`，兼容数字/字符串。HTTP 200、能解析 JSON、`ERRMSG` 出现“签到”都不足以单独判成功。学校返回登录失效信息时清掉业务 session，重新登录并重做一次整个签到流程，包括重新获取 timestamp。

### 3.4 上游触发方式和缺陷

`SigninScreen` 点击调用 `SigninViewModel.performSignin`，成功再拉今日课表。没有“提前 10 分钟自动签到”或固定三次总重试；学校是否接受某一时刻的提交，仍由上游判断。现有业务会话仅凭非空值复用，未设置学校 session 的明确 TTL。

本地与服务端查询均存在把登录/网络/解析失败转换为空课表的路径，再包装“获取成功”。这会混淆“今天没有课”和“没查到数据”；对于人工页面已经不理想，移植到守护调度器后影响更大。服务端 iClass 专用 HTTP client 使用宽松 TLS trust manager，也是需要区分的上游实现事实。

源码：[LocalSigninApi.kt](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/shared/src/commonMain/kotlin/cn/edu/ubaa/api/local/LocalSigninApi.kt#L113)、[SigninClient.kt](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/server/src/main/kotlin/cn/edu/ubaa/signin/SigninClient.kt)、[WebVPN 路径测试](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/shared/src/commonTest/kotlin/cn/edu/ubaa/api/LocalSigninApiBackendTest.kt#L556)、[触发 ViewModel](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/composeApp/src/commonMain/kotlin/cn/edu/ubaa/ui/screens/signin/SigninViewModel.kt)。

## 4. BYKC 博雅协议：身份、加密和 API

### 4.1 博雅 token 与每次请求的加密

登录博雅 CAS 后从跳转取得业务 auth_token。学校 Cookie 保证 CAS/WebVPN 会话，auth_token 标识博雅业务身份，两者不可互换。UBAA 客户端的 login fallback 有“未取得非空 token 仍返回 true”的路径，所以 login 函数返回 true 本身也不是充分认证证据。

两套上游采用相同的协议算法骨架：

1. 为请求生成随机 16 字节 ASCII AES key；AutoBoya 使用 `secrets`，UBAA 的实现使用 Kotlin Random。
2. 将业务 payload 序列化为 UTF-8 JSON，按 AES-128-ECB + block padding 加密，再 Base64。
3. `Ak` 是 AES key 经学校 RSA-1024 公钥、PKCS#1 v1.5 加密后 Base64。
4. 对 **原始 JSON 明文字节** 做 SHA-1，转小写十六进制 ASCII，再 RSA 加密并 Base64 得到 `Sk`。
5. `Ts` 是当前本地毫秒时间戳；学校可否容忍时钟偏差，源码不能证明。
6. 响应用 **此次请求的同一个 AES key** 解密，去 padding，再 JSON 解析。

`Sk` 的函数名虽然常称“签名”，代码实际是 RSA **公钥加密摘要**，不能解释成客户端持有私钥的标准数字签名。仓库里的 RSA 公钥/WebVPN 路由常量不是用户私密凭证；本项目固定本地密码保险箱 key 是另一回事。

**线上字节包装有差别：** AutoBoya 将 Base64 密文再包装为 JSON 字符串（带引号）作为 request body；UBAA `setBody(encryptedData)` 直接使用 Base64 String。响应上，UBAA 解密失败时可回退到原文本继续解析；AutoBoya 解密失败抛错误并尝试识别 HTML 登录页。不能仅据算法相同宣称请求完全等价或服务端必接受两种包装。

源码：[UBAA crypto](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/server/src/main/kotlin/cn/edu/ubaa/bykc/BykcCrypto.kt)、[UBAA 本地 client](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/shared/src/commonMain/kotlin/cn/edu/ubaa/api/local/LocalBykcApi.kt#L448)、[AutoBoya crypto](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/autoboya/crypto.py)。

### 4.2 必须记牢的接口与 ID

以下都是业务目标 `https://bykc.buaa.edu.cn/sscv/<接口名>` 下的 POST，经上述加密封装；不是 UBAA 自己的 `/api/v1/...` 路由。

| 学校接口 | 明文 payload | 用途 |
| --- | --- | --- |
| `getUserProfile` | `{}` | 博雅身份资料；UBAA 使用 |
| `getAllConfig` | `{}` | 学期、分类等配置 |
| `queryStudentSemesterCourseByPage` | `pageNumber, pageSize` | 分页课池，第一页为 1 |
| `queryCourseById` | `id=课程本体ID` | 单课详情/考勤配置 |
| `queryChosenCourse` | `startDate,endDate` | 日期范围内的学生报名记录 |
| `queryStatisticByUserId` | `{}` | 官方修读统计，不带学期日期参数 |
| `choseCourse` | `courseId=课程本体ID` | 报名/抢选 |
| `delChosenCourse` | `id=课程本体ID`，按两套上游调用路径 | 退选；不能因字段名 id 就换成报名记录 ID |
| `signCourseByUser` | `courseId,signLat,signLng,signType` | signType=1 签到，2 签退 |

`queryChosenCourse` 返回外层 `id` 是报名记录 ID，内层 `courseInfo.id` 才是课程本体 ID。UBAA DTO 保留 `id` 和 `courseId` 两字段；AutoBoya 把内层课程 ID 作为 BoyaCourse.id，将外层保存为 raw.chosenCourseId。AutoBoya 手动退选测试特意使用两个不同 ID 并断言发送课程本体 ID。这个证据说明代码契约，不等同于本次已在线验证学校退选接口。

源码：[AutoBoya bykc.py](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/autoboya/bykc.py)、[退选 ID 测试](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/tests/test_manual_operations.py#L51)、[UBAA DTO](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/shared/src/commonMain/kotlin/cn/edu/ubaa/model/dto/Bykc.kt)。

### 4.3 成功和错误语义并不一致

UBAA 博雅成功要求 `status == "0"`。签到响应使用任意 JsonElement data，避免把非固定 data 类型当失败；报名/退选仍解析其动作模型。AutoBoya 接受 status 为字符串/数字 0、200，甚至 **缺失/None**。独立 Mock 证明仅带错误文字但无 status 的返回会被接受。因此两套代码不应混用成功条件。

AutoBoya `raise_for_status` 在解密前执行：HTTP 401/403 会抛 HTTPStatusError，不会自动映射为 SessionExpired。业务状态/文字或 HTML 登录页可映射 SessionExpired；其他错误细分为满额、未开放、报名限制、已报名、考勤窗口关闭等。UBAA 底层 request/decode 阶段抛一般异常时会强制登录后重发一次；已经解密、在外层模型检查中才认定的业务失败，不一定进入这个重发分支。

**对写操作而言，网络超时不是“学校未处理”。** 上游没有事务 ID、幂等键或服务端操作回执查询机制，重发必须结合真实已选/考勤状态才能判断；最多一次重试也不是“绝不会重复 POST”。

## 5. UBAA 博雅：手动操作与状态机

### 5.1 课池与选退课

列表按页读取，UI `loadMoreCourses` 追加下一页，默认每页 20；`all/includeExpired` 控制是否过滤选课已结束和上课已过期记录。它没有自行扫全池后台抢选。

状态计算有优先顺序：已过开课时间 → EXPIRED；已选 → SELECTED；已过选课结束 → ENDED；满额 → FULL；尚未开放 → PREVIEW；其他 → AVAILABLE。异常回退 AVAILABLE，所以状态标签不等于完整准入证明。

详情页选择按钮还检查人数、已选、选课开始/截止时间和状态；点击后 client 直接提交课程 ID，最终由学校裁定资格、容量和冲突。退选按钮的实现重点限制 EXPIRED；不能把这解释成完备执行 courseCancelEndDate 截止校验。选/退成功，ViewModel 刷新详情、已选、课程列表；没有顺带刷新统计的统一动作。

### 5.2 签到和签退窗口

`courseSignConfig` 包含四个独立时间字段：`signStartDate/signEndDate` 和 `signOutStartDate/signOutEndDate`，另有 `signPointList`。所有窗口比较为闭区间；缺任一端就不可执行。`courseStartDate/courseEndDate` 是上课区间，**不能代替老师设置的考勤窗口**。

UBAA 执行签到前重新查询当前学期已选课，按 `courseInfo.id` 匹配，找不到就拒绝。优先读已选的签到配置，缺失才请求课程详情补齐。动作判定为：

| 条件 | 签到 | 签退 |
| --- | --- | --- |
| `pass == 1` | 阻止 | 阻止 |
| `checkin` 为 null/0 | 在签到窗口可执行 | 在签退窗口可执行 |
| `checkin` 为 5/6 | 阻止再次签到 | 在签退窗口可执行 |
| 其他非零 checkin | 阻止 | 阻止 |

这意味着“未签到仍可尝试签退”是上游有意允许的分支；不能想当然给它增加“必须先成功签到”的绝对规则。允许提交签退也不表示学校会给考勤通过。

详情 UI 用 `后端 canSign OR 本地实时计算` 激活按钮，因此旧后端 true 可能在窗口结束后暂时仍使按钮可点；真正写操作路径重新检查状态/窗口，能再次拦截。自动化不能只复用按钮状态。

### 5.3 定位数据来源

UBAA 从学校配置点中随机选一个，要求 radius>0；在圆内按 `radius*sqrt(U)` 选距离、均匀角度，使用地球半径 6,371,000m 的球面公式计算坐标。没有有效半径点时可使用调用者显式提供的 fallback lat/lng；两者都没有就失败。

AutoBoya 选 **最后一个点**，按内侧 65% 半径的小范围平面近似生成坐标。两者均不是每次读取设备实际 GPS；源码层面是根据学校配置构造请求坐标。`signPointList` 非空只能说明实现识别到自主定位考勤配置，不能由此推出课程是远程授课、免到场或一定完成所有考核要求。

源码：[UBAA BykcService](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/server/src/main/kotlin/cn/edu/ubaa/bykc/BykcService.kt#L244)、[本地状态判定](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/shared/src/commonMain/kotlin/cn/edu/ubaa/api/local/LocalBykcApi.kt#L647)、[界面动作逻辑](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/composeApp/src/commonMain/kotlin/cn/edu/ubaa/ui/screens/bykc/BykcTimeFormatters.kt#L116)。

## 6. AutoBoya 后台自动抢选、签到、签退

### 6.1 时序和缓存，不能误读“一分钟”

`run` 启动独立 worker 进程。worker 写 PID 文件、清除旧 stop 文件，循环如下：

```text
首次/距上次完整刷新达到 3600 秒
  → 随机选择一个 enabled 账号，查询配置和全分页课池
  → 用同一配置的学期区间，逐账号刷新已选和官方统计
每轮
  → 从磁盘缓存扫描候选与考勤窗口
  → 每个 enabled 账号记录 heartbeat
  → 串行执行决策，持久化动作日志
  → sleep 60 秒，再循环
```

这是“每小时网络全量刷新 + 每分钟缓存扫描”；一次循环本身耗时也计入实际周期，因此不是固定每 60 秒准时触发。外部手机选课、退课名额、新课发布、老师修改考勤窗口可能最长约一小时才纳入缓存。自动写操作成功后另有该账号的即时已选/统计刷新。

课池分页持续读取，依据 last、totalElements、totalPages、空页、没有元数据时的不足一页结束；没有本项目的三页上限。不过多个账号共享随机账号看到的课池；不同年级/学院可见课程差异，源码没有保证“随机一人课池等于所有人课池”。

`refresh_once` 按账号串行处理，某一个账号异常可中断整个刷新，后续账号本轮不更新。外围捕获只使进程继续，不能等同于每账号任务隔离。

### 6.2 自动选课候选规则

同时满足：选课窗口完整且当前在窗口内；若人数两字段均已知则 current<max；`signPointList` 是非空 list；类别不等于“其他方面”。扫描共享池时 `ignore_selected=True`，因为池中 selected 可能属于用于查询课池的那个人；真正执行时再查每个学生自己的已选缓存。

执行前还按账号校区排除：字符串出现“杭州”判杭州课；北京账号选非杭州，杭州账号选杭州。这是文字启发式，不是严格校区主键校验。手动 select 没有套用这套自动过滤。

AutoBoya 不做四类缺口优先级、不比对普通课/博雅课时间冲突、不校验课程取消状态或上课已结束；`courseSignType` 只是保留字段，没有决定自主识别。容量缺失/无法解析按未知处理，而非拒绝；非空点 `[{}]` 也会通过候选筛选。

它逐课程逐 enabled 学生立即调用 `choseCourse`，没有毫秒倒计时、并行竞抢或请求抖动机制。可见时间窗开放不等于能抢中，学校会再次验证容量、对象、重复和限制。

### 6.3 自动签到/签退规则

仅对缓存中的已选课程扫描，要求非空自主点列表；按对应官方窗口生成 sign/signout 决策。缺官方窗口不生成动作；没有课前/课后固定分钟兜底，也没有从课池自动补齐已选缺失配置的分支。

**不会因 `checkin==1`、`pass==1` 或 signInfo 已完成直接跳过。** 模型 raw 中保留这些字段，但 decide_actions 没使用；主要靠本地动作日志减少重复。学校网页/手机完成的操作若本地没有 journal，窗口内仍可能尝试发包。签到/签退窗口重叠时可以同轮产生两种动作。

执行时读取最后一个点的 lat/lng，radius 缺失或 0 用 8m 默认值；负半径/非法坐标没有完整范围验证。坐标转换发生在单动作 try 之前，错误可逃逸，导致当前 batch 中断，且尚未落盘的 journal 可能丢失。

### 6.4 防重、重试与持久化

- 成功键：`日期:用户名:动作:课程ID`。选择、签到、签退分开记录，保存至 `cache/action_journal.json`。重启后保留；换一天是新键。
- 选课失败键：`用户名:select_failed:课程ID`，没有日期。业务错误计数达 3 后后续停止自动抢该课；网络等临时异常不计次数。AlreadySelected 在此实现中仍按失败累计，不会直接登记成功。
- 签到/签退失败没有三次总上限；每轮窗口仍满足且无成功日志时可继续尝试。
- 凭证失效映射为 SessionExpired 时重登录并重新执行一次；HTTP 401/403 并不进入这条自动重登录路径。
- **写操作成功后必须先完成缓存刷新，函数才返回 ok=true，之后才记 journal。** 如果学校写成功而读刷新失败，它返回失败且不记成功，下一轮可能再写一次；本次 Mock 已确认。
- journal 在整个决策 batch 末尾写盘，原子文件替换避免半文件；它没有提供跨进程事务锁，不能避免两个 worker 同时读取旧日志、重复写操作或覆盖彼此更新。
- PID 文件不是互斥锁；`run` 没见先检查 PID 活性/锁定的单例门禁。重复启动还会删除同一个 stop 文件，退出时删除公共 PID 文件。以上属于源码静态发现，未在本次启动真实后台进程验证。
- 缓存内停用/已移除学生没有统一剔除：选择分支过滤 enabled；考勤决策取全部 selected 缓存，execute 的 sign 分支不重新核对 enabled。本次用停用的合成账号确认仍调用签到 Mock。
- execute 不重新验证扫描时的窗口。排队、重登录、网络慢、前面账号耗时都可能令真正 POST 时已不在窗口；本次通过已过期配置确认仍发起 Mock。

### 6.5 手动操作和心跳的实际含义

CLI select/drop 需 `--yes`，并指定 `--user` 或 `--all-users`；sign/signout 直接执行，没有同样 yes 参数。手动 sign 首先要求已选缓存存在该课程；配置缺失可退回课池点。它不经过自动窗口判断，最终学校裁定。手动签到路径没有自动 runner 同样的即时缓存刷新/journal 记录，不能假定二者防重一致。

heartbeat 的 `auto_boya_check` 是该账号本轮处于签到/签退窗口的课程去重数，**不是查询发包数、成功数、待抢名额或所有守护课程数**，且生成时未扣掉 journal 已完成动作。AutoBoya 每分钟打印这一行，与本项目当前“重复课池日志首条后静默”的产品要求不同。

源码：[scheduler.py](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/autoboya/scheduler.py)、[rules.py](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/autoboya/rules.py)、[CLI](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/autoboya/cli.py)、[cache.py](https://github.com/DeNeRATe-cool/AutoBoya/blob/c8fc785bbc07178bfbd79d99b89b5358e021b23b/autoboya/cache.py)。

## 7. 考勤、考核、累计统计、本学期统计必须分开

### 7.1 上游界面使用的考勤枚举

以下是 UBAA UI 对学校返回值的解释，不能声称学校后台完整状态规范已由本次核准：

| checkin | UBAA 显示 |
| --- | --- |
| 0/未知 | 待考勤 |
| 1 | 考勤通过 |
| 2 / 3 / 4 | 迟到 / 早退 / 缺勤 |
| 5 / 6 | 已签到、未签退 / 已签到异常、未签退 |
| 7 / 8 | 未签到、已签退 / 未签到、已签退异常 |
| 9 / 10 / 11 | 两次动作已记录，但签到、签退之一或两者异常 |

`pass==1` 为考核通过，0 为考核未通过，null/其他为待考核。score 和 homework 独立；上游显示作业要求，没有自动做作业或保证教师考核通过。signInfo 是考勤细节，不能仅因字符串包含 `signIn` 就认定已经有效签到，更不能据此替代 `checkin==1`。

**请求成功只证明该接口此次接受动作；不是学期有效修读到账证明。** 同一课程至少要区分：已选、签到记录、签退记录、考勤结论、考核结论、官方统计结论。

源码：[UBAA 已选 UI 枚举](https://github.com/BUAASubnet/UBAA/blob/e8a397fcb35a68147eee65a94c66ffb84e2f09fe/composeApp/src/commonMain/kotlin/cn/edu/ubaa/ui/screens/bykc/BykcChosenCoursesScreen.kt#L243)。

### 7.2 学期选择和统计

UBAA 查已选前取 getAllConfig.semester，优先选当前时间在 start/end 内的学期；无匹配则选结束时间最新者；空配置报错。比直接拿第一个更严谨，但“最新”也可能是未来学期，不能当绝对正确的当前学期兜底。

AutoBoya 直接取 **semester[0]**，没有验证其包含今天；缺字段则回退硬编码 `2026-03-01 00:00:00` 到 `2026-06-21 00:00:00`。在 2026 年秋季使用这段回退可能查不到应守护的课程。本次独立探测分别确认第一条学期和硬编码回退行为。

官方统计接口没有 date/semester 参数：UBAA 将 validCount 作为累计有效数，各类 assessmentCount 为要求、completeAssessmentCount 为完成，比较完成>=要求；AutoBoya 展示官方 select/complete/fail/undone/validCount，未据课程独立计算四类本学期 2+2+1+1。**两套上游都没有给当前项目本学期“六次达标进度”提供一个可直接照抄的完整算法。** 是否有接口隐含的账号/年级统计范围需学校返回或文档核实，不能据名称就把 validCount 填进本学期进度。

## 8. 当前项目与两套上游逐项对照

此节只来自此次当前文件读取。当前认可业务基线仍为 v1.2.6；没有应用任何上游改动，也没有恢复已撤回的微信功能。

| 机制 | 上游事实 | 当前项目实现/差异 |
| --- | --- | --- |
| 常规签到触发 | UBAA 点击触发 | `core/scheduler.py` 每轮巡检，默认 20s、下限10s，按账号遍历；新增课前10min随机计划和最多3次逻辑尝试 |
| 时间判定 | UBAA 获取学校 timestamp，缺失失败 | `core/iclass.py` 学校 timestamp 缺失回退本地毫秒；scheduler 的 now 在整轮查询前取得，提交前未重取，可因慢请求越窗 |
| iClass 登录 | UBAA 8346 MyCenter 换 loginName，8347 app 登录 | 本项目先试8346 `/esp/auth/signIn`，再8347 app；loginName 解析失败又用 schoolid；这些是额外分支 |
| WebVPN 写路径 | UBAA 8347 `/app/course/stu_scan_sign.action` | 本项目8346/8347候选都带 `/eschool/app/...`，与新版上游明确不一致；需优先校核 |
| 实际 POST 次数 | UBAA认证失败重做一次 | 本项目每逻辑尝试有多个 endpoint 与重新登录提交；三次逻辑尝试不等于三次网络写请求 |
| 空课表 | UBAA也有失败返回空列表缺陷 | 本项目同样有空列表吞错；不能因为上游如此就认可自动调度的错误语义 |
| BYKC TLS | AutoBoya 默认验证TLS | 本项目两个网络 client 有 verify=False；协议加密不能消除TLS身份验证风险 |
| 课池更新 | AutoBoya默认1h完整刷新，1min缓存扫描 | 本项目白天60s网络同步、已选300s；23:30—07:00间隔为1800s，同期调度等待180s |
| 分页 | AutoBoya依据分页元数据持续读取 | 本项目client默认至多10页，守护调用仅3页；缺totalPages默认1，可能更早截断 |
| 已选范围 | 两套上游显式学期start/end | 本项目client默认2024-01-01至2027-01-01；守护通常使用默认，不是严格当前学期查询 |
| 自主判定 | AutoBoya只看非空point list | 本项目同样粗筛，非空无效点可放行；自动模式强制执行该规则，没有业务允许线下的开关 |
| 选课策略 | AutoBoya无缺口排序/冲突检查 | 本项目新增校区、状态、5s临近开放等待、博雅时间冲突、四类缺口排序和0.5—1.2s抖动 |
| 冲突范围 | AutoBoya未检查 | 本项目只比已选博雅，不比普通课表；缺时间视为无冲突；候选列表生成后批次执行，不能假定新抢课程已经参与所有后续冲突判定 |
| 缺口意义 | 上游展示官方统计 | 本项目排序用已选数而非最终通过数，缺日期继续计数；达标类别只是低优先级，并未停止抢该类 |
| 点生成 | UBAA随机点/全半径球面；AutoBoya末点/65%半径近似 | 本项目末点、支持两组字段别名、默认15m、65%圆盘、round6位；注释“高斯分布”错误，公式是面积均匀分布 |
| 考勤前置 | UBAA checkin/pass+窗口；AutoBoya主要窗口+journal | 本项目用若干signStatus和signInfo判动作完成，没有完整应用0—11枚举/pass约束 |
| 缺签到配置 | UBAA可查详情；AutoBoya自动分支不补齐 | 本项目从课池按ID或同名补齐；同名不保证同一节课程，可能用错配置 |
| 缺时间窗口 | 两上游考勤规则要求完整官方窗口 | 本项目缺start时尝试课程起/止前15min到后30min；仅拆分日期+时间字段能解析的特定分支触发，不是官方窗口保证 |
| 失败次数 | AutoBoya选课3次业务失败，考勤不限3次 | 本项目选课业务错误3次；签到/签退异常各3次；网络重认证及内部发包仍需另计 |
| 防重持久化 | AutoBoya磁盘journal，仍有刷新失败重复问题 | 本项目选课history、考勤done、失败计数主要在内存；重启丢失，长期清理不足；ID与课程名混合防重可误挡同名不同课 |
| 操作后刷新 | AutoBoya刷新失败会遮蔽写成功 | 本项目先登记done/history，再尝试刷新，刷新失败仅debug；减少立即重复但可留下UI/统计陈旧，需要独立标识“写成功、读待同步” |
| 学期进度 | 上游未实现当前四类六次算法 | 本项目优先读取统计semesterInfo，否则推算；2+2+1+1硬编码；缺日期、`"signIn" in str(...)` 会造成误计风险 |
| 心跳 | AutoBoya每轮按人打印窗口课程数 | 本项目课池概览首条后静默；日志里的“毫秒级巡检”不符合60s/夜间180s的实际循环 |

本项目推算学期函数的注释描述夏季，但实际除9—1月之外都落春季分支；8月日期也可能落到已结束的春季区间。校历必须来自官方元数据或明确的可核查校历，不能从函数名/注释推断已经严格对齐。

## 9. 本次验证：55 原有测试 + 16 独立离线探测

AutoBoya 的 55 项原有 pytest 全通过，0 跳过。独立探测 16/16 符合实际观察，其中 3 项核实协议/算法契约、13 项确认边界行为。测试运行时禁止真实 socket 连接和系统凭据读写，隔离 AUTOBOYA_HOME；没有学校请求，未触发被阻止的 socket 尝试。

| 探测 | 观察 |
| --- | --- |
| 内外课程 ID 不同 | 保留本体ID和报名ID，未混淆 |
| 点列表只有空对象 | 仍进入自动候选 |
| 容量不可解析 | 仍进入候选 |
| 已取消/已结束课程 | 只要选课窗和点满足仍进入候选 |
| checkin/pass均通过 | 仍生成签到决策 |
| 缺官方签到窗口 | 不生成自动签到（无固定分钟兜底） |
| 当前学期在配置第二项 | 仍使用第一项 |
| 配置缺失 | 使用固定2026春季日期 |
| 写成功但刷新失败 | 返回失败，重复调用可再次写 |
| 账号enabled=false且残留已选缓存 | 执行签到决策仍调用Mock |
| 执行前配置窗口已过期 | execute不复验，仍调用Mock |
| 点对象缺lat/lng | KeyError逃逸单动作异常处理 |
| HTTP401 | 抛HTTPStatusError，非SessionExpired |
| 返回错误文字但缺status | 接受为成功返回 |
| 1000种seed坐标采样 | 均在内65%半径范围 |
| 刷新首个学生异常 | 下一个学生未执行本轮刷新 |

复现入口：[verify_upstreams.py](verification/verify_upstreams.py)，运行需 Python>=3.11、上游固定commit的AutoBoya源码及其依赖。设置 `UPSTREAM_STUDY_ROOT` 指向独立临时研究目录，在该目录的 `autoboya/` 下放上游源码；缓存与合成数据也写入该临时目录。脚本不含真实账号，只使用 demo、second 和合成数据。[机器可读结果](upstream_mechanism_evidence.json) 包含版本、结果、源文件哈希及脚本哈希。

UBAA Kotlin 测试本次只核读源码契约，**未执行**：当前环境未找到可用 java/gradle 命令，不在本任务为运行测试安装完整 Android/Kotlin 工具链。不能把上述 Python 测试计入 UBAA，更不能说真实学校接口、各平台原生 GUI 或学生实际达标已经通过。

## 10. 对后续实现的技术结论与优先级

本轮交付研究，不自动修改业务。未来修复首先应统一以下契约，然后沿 API、调度、统计、前端、通知验证全链路：

1. **身份/ID/路径：** iClass排课实例与博雅本体/报名ID分离；核对WebVPN 8347新路径；认证失败、网络故障、空课表分开返回。禁止用本地timestamp悄然掩盖取学校时间失败。
2. **写操作状态：** HTTP、解密、业务status、动作记录、最终考勤/考核五层分开；不能缺status默认成功。写成功但刷新失败需要明确待同步状态，不能变成失败重写。
3. **真正防重：** 操作前重新验证账号启用、最新窗口/状态；串行锁+持久日志+成功后官方复核；统计实际POST预算，区分网络不确定和明确失败。PID与原子JSON文件都不是跨进程操作锁。
4. **有效配置与同步：** 校验GPS点/半径/窗口，不让非空列表代表有效；完整分页、按账号可见范围同步；手机自选课及时纳入；账号故障隔离与短窗口及时性共同设计。
5. **学期和完成：** 官方校历优先，无法定学期/课程日期时标记未知；checkin/pass/signInfo分开；类别要求的来源可追溯；已选占位与最终达标不要混算。
6. **长期与多平台：** 清理历史集合、关闭HTTP资源、实际进程单例、休眠恢复/时区/系统时钟变化；后续修复要分别验证Windows、macOS、Linux相关运行行为，不能从Mock推导平台验收。

需现网受控验证的部分：学校当前端口/路径、timestamp单位与容忍偏差、crypto字节包装、课程可见范围、courseSignType具体枚举、status/checkin最新字段契约、学期接口排序和统计真实范围。**源码告诉我们客户端如何尝试，学校响应才决定今天是否接受；最终有效修读以官方结果为准。**
