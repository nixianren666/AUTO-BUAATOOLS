# 接管现状（2026-10-14 更新）

业务问题尚未修复，未完成全平台实机验收。2026-10-14完成全面审查并按授权落实版本撤回；下方保留2026-10-13核查快照，不能将历史版本状态当当前状态。

## 最新结果（2026-10-14）

- [V126_REVIEW.md](V126_REVIEW.md) 记录本版多角度审查；36后端边界探测、4前端检查，以及隔离Edge真实HTML/JS验证。当前79项suite为78通过、1项CDP初始化失败待定位。
- 新确认关键问题包括考核假通过、同批抢课冲突、停止后继续发包、同名课程错用配置、未知账号回退、手动默认坐标/非法操作类型、退课换ID兜底、任意来源管理请求许可和点击处理器注入。
- main及同级Git均恢复到v1.2.6提交5158df8；GitHub v1.3.1/v1.3.2 Release与标签已删除，v1.2.6为Latest。本地v1.3标签删除，同级工作树最终干净。
- 根、dist、同级Git三个默认EXE都核实SHA-256为fea365ae…，对应v1.2.6。10个退役文件已删除/恢复；旧微信pyc、相关build和先前Temp v1.3审查源码副本已清理。
- 发布工作流disabled_manually，待修好目标/版本/错误语义再启用；下架未触发新版本发布。
- 当前根业务源码、用户配置与UI原型未改。下架范围及不可达Git对象/缓存限制见[VERSION_WITHDRAWAL.md](VERSION_WITHDRAWAL.md)。

## 独立上游机制核查补充（2026-10-13）

用户要求重新从 UBAA / AutoBoya 源码理解机制，已完成 [UPSTREAM_MECHANISMS.md](UPSTREAM_MECHANISMS.md)。上游固定为 UBAA e8a397f、AutoBoya c8fc785；未依据 Antigravity 的技术断言。

- 新增重要兼容差异：UBAA 的 WebVPN 8347 签到 POST 使用 `/app/course/stu_scan_sign.action`，有专门 Mock 测试；当前 `core/iclass.py` 8347 候选仍使用 `/eschool/app/...`。本轮尚未在线验证或修改，应优先核实。
- UBAA 联合考勤窗口、checkin/pass 控制动作，明确0—11考勤枚举；AutoBoya不以已通过字段防重，本项目也未完整应用该状态机。签到/签退记录与考勤/考核通过不能混淆。
- AutoBoya 上游原有55项pytest通过，独立16项离线探测确认13项边界行为和3项契约；与之前本项目86项测试是不同对象，不能相加称本项目141项通过。
- 本轮没有执行UBAA Kotlin测试（缺可用java/gradle命令），没有真实学校写操作。静态发现、离线Mock与现网验收在报告中分别注明。
- 当前业务源文件未改，上游代码研究副本和隔离依赖在Temp；持久化仅含报告、脱敏证据及合成数据复现脚本。

## 2026-10-13 的目录与版本快照（已被上方最新结果更新）

| 位置 | 本次观察 |
| --- | --- |
| 当前项目 `ubaa/` | 无 `.git`；业务标称 v1.2.6；有运行配置、源码、多代二进制与 UI 实验 |
| 当前项目内 `ubaa/Github库/` | 无 `.git`；与当前源码不同；其配置 accounts 为空；只是历史快照，不能直接当最新发布目录 |
| 同级 `../Github库/` | 有 `.git`；工作树检查无输出（干净）；HEAD `fcc5131`，提交主题为微信上下文续期/IDC 修补；保留 v1.3.1、v1.3.2 标签 |
| GitHub 在线状态 | 2026-10-13 补全核查：main=fcc5131，69 个 blob 与同级仓库一致；仍是 v1.3.2，详见 GITHUB_AUDIT.md |

与同级仓库 `v1.2.6` 标签按换行归一化比对：

- `core/scheduler.py`、`core/boya_scheduler.py`、`core/boya_client.py`、`server/app.py`、`requirements.txt`、`installer/setup.iss`、工作流正文一致。
- `run.py` 仅多出编码声明；`app.js` 仅尾部空行变化。
- `style.css` 增加 `.hidden { display: none !important; }`；这项更改可能与历史弹窗修复有关，不能因回退版本就机械删除。
- `index.html` 的账户导航按钮少了闭合 `</button>`，同时版本文字由 v1.2.5 改为 v1.2.6。
- 两个 `.spec` 均残留 `qrcode` / `qrcode.image.pil` hiddenimports，当前依赖文件不含 qrcode。不是证明打包必失败，但属于微信撤回后的残留。

## 仍待处理的实际问题

### A. 已从源码直接确认

| 问题 | 证据入口 | 后续影响 |
| --- | --- | --- |
| 回退后导航 HTML 少闭合标签 | `server/static/index.html`，`navBadgeAccounts` 后紧跟 `navBtnLogs` | 浏览器可能自动修复非法按钮嵌套；仍需修正结构并测试账户/日志点击，不应据容错认定无问题 |
| 发布脚本版本硬编码 | `.github/workflows/build-macos.yml` | 非 tag 触发回退到 `v1.2.2`；Windows job 上传固定 v1.2.2 文件；上传命令有 `|| true`，工作流绿灯不证明资产更新成功 |
| 旧版本文字/说明并存 | README、`run.py` 的参数描述与 Headless 启动文字 | v1.2.5/v1.2.2 与 v1.2.6 并存；README 的线上开关和每十分钟日志说法也已过期 |
| 博雅已选查询日期固定 | `core/boya_client.py::query_chosen_courses` | 默认 2024-01-01 至 2027-01-01，不能作为长期使用的动态学期范围 |
| 同步“全课池”实际有分页上限 | `core/boya_scheduler.py::tick` | 调用 `query_courses(max_pages=3)`；需确认服务端总页数，不能保证超过三页也不漏课 |
| 学期统计允许无法解析日期的记录继续计数 | `server/app.py::compute_semester_statistics` | 当前只在日期成功解析且越界时跳过；日期缺失/异常可能绕过严格学期范围 |
| 统计与候选策略学期口径不一致 | `core/boya_scheduler.py::_check_auto_select` | 候选需求使用推算学期，不读取官方 semesterInfo；需求数按已选而非最终达标计算 |
| 自动选课冲突比较只有已选博雅 | `core/boya_scheduler.py::_check_auto_select` | 遍历 `boya_selected_courses`，未见常规课表参与；README 声称兼顾常规课表，不能照此承诺 |
| 线上识别仅看非空点列表 | `has_autonomous_sign` | 没有在该函数核查每个点的数值、合法范围与完整窗口；非空不等于配置有效 |
| 状态集合生命周期缺少明显清理 | 两个 scheduler 的 signed/history/done/retry 集合 | 需评估长期挂机增长、日期跨越、退课后再选及注销/重新加入的行为 |
| 管理面缺少独立访问认证 | `server/app.py`、`run.py` Headless 分支 | Headless 默认监听全部网卡，CORS 宽泛；部署范围与防护需单独核实 |

这些是接管中发现的源码事实或由其直接引出的待验证场景，不是“已在线复现所有后果”的报告。比如缺日期计数可以静态看到，但真实学校是否返回缺日期记录还未检查。

### B. 历史与当前实测之间的空白

- 二进制文件存在不等于与当前源码一致。补全核查已静态读取根默认 EXE、命名 v1.2.6 的便携 EXE 和本地 Mac ZIP：默认 EXE 包含 v1.3.2 微信；v1.2.6 包不含微信且哈希匹配其 Release；Mac 资产三个版本相同、plist 仍标 1.2.5。没有执行这些 EXE、挂载 DMG、分析所有安装包或重新打包。
- 本地仍有旧 `wechat_clawbot` 和相关测试 `.pyc`、旧 build 目录、二维码 hiddenimports。当前核心源文件不再含微信模块；本次没有删除缓存或改写 Git 历史。
- 用户在 10 月要求清除 1.3，但同级 Git 历史和已核实的远端 main、Release 仍保留它；这项清理不能登记为“全域完成”。
- Mac smoke 脚本以 `--autostart` 启动并检查 HTTP；Windows 编译产物脚本走 Headless + Edge CDP。两者不能替代每个平台原生窗口、托盘、自启、安装/卸载实测。
- `.github/workflows/build-macos.yml` 列出了两个 Mac runner，但当前平台是否仍支持这些 runner 未在线核实；构建前应查询当时官方支持情况。
- 根配置含 1 个账号，内层分发快照配置含 0 个账号。只记录数量，不保存任何账号字段值。本次未删除用户配置，也没有做覆盖全库、Git Tree、二进制和图片的发布前零泄露认证。
- `.gitignore` 不能替代隐私扫描，当前根配置也不能直接复制到 Git。原始历史日志与截图中确实可能有隐私，交接目录不收录这些原件。

## 最新 UI 工作的具体落点

- 正式 UI：`server/static/index.html` + `js/app.js` + `css/style.css`，仍是原生 Origin 风格界面。
- 新原型：根 `preview_liquid_ui.html`。未见其调用业务 `/api/` 或加载正式 app.js；不能当成已经接好账号、签到、抢课的完整产品。
- 预览参数：`--glass-tint: rgba(255,255,255,0.04)`、blur 0.5px、saturate 155%、brightness 108%；与历史最后一轮报告相符。
- 相关文件：`FIGMA_DESIGN_PROMPT.md`、`figma_generator_script.js`、`test_wxperia_exact.html`、`test_shuding.html`、`test_filter_edge.html`、`test_juejin_dock.html`、displacement 贴图与背景图片。
- `preview_crystal_final.png` 等只是历史渲染产物。本次没有逐张审查私有图片，不能给它们出具可公开发布的隐私保证。
- 最后用户需求仍是提高玻璃本身的透亮/通透；最后一轮修改没有用户验收。后续继续 UI 时先展示并比较原型，保留 v1.2.6 行为，再讨论正式接入。

## 本轮实际验证

- 依据 Antigravity 项目配置精确筛选 `ubaa123`，解析其 27 个会话完整日志文件，建立计数、时间、父子关系和内容指纹。
- 核读两个主会话的用户输入主题、主开发会话关键回复、子任务调查报告、恢复日志和关键发布/回退记录；没有逐字逐图人工验收全部工具输出。
- 交叉比对当前源码、历史 v1.2.6 标签和同级 Git HEAD；保存重要差异。
- 对 29 个业务、测试与工具 Python 文件进行 AST 解析：无语法错误。静态找到 79 个 `test_*` 方法；**这不是运行了 79 项测试**。
- `node --check server/static/js/app.js` 通过：只能证明 JS 语法可解析，不能证明 DOM 结构和业务交互正确。
- 初次接管未运行完整 unittest。2026-10-13 补全审查在空账号、限制网络与注册表写入的远端 main 隔离副本运行了现有 86 项测试，全部通过；独立验证又复现 12 个后端边界场景和 1 个前端竞态。没有启动带真实账号的程序、调用学校签到/选课、运行编译 EXE 的 E2E、操作用户远端服务器、发布或推送。
- 对本轮新增文档与 AGENTS 增量执行路径引用、清单一致性与敏感模式检查；此检查不等于全项目发布前深度隐私审计。

补全审查的完整结果、跨平台证据边界、可达 Git 历史隐私扫描以及修复优先级，见 [GITHUB_AUDIT.md](GITHUB_AUDIT.md)。其中微信专属缺陷只适用于已撤回系列；多数核心业务场景也存在于 v1.2.6 共享实现，后续应在该基线回归。

## 后续工作建议顺序

1. 用户确定具体任务后，以 v1.2.6 为基线识别工作目录；保留当前修改，避免从旧 main 整体覆盖。
2. 如准备继续业务或发布，先处理目录与流水线版本不一致、HTML 结构、配置隔离，再执行有意义的回归。
3. 涉及调度/学期时，优先检查表中的长期边界与官方接口返回值；更新六层相关逻辑和测试。
4. 如继续 UI，则先处理通透度与真实视觉对比；验收原型后再接入正式 API 和多尺寸交互。
5. 发布前按 AGENTS.md 进行全库与 Git Tree 隐私扫描，并分别核对 Windows 安装/便携、Mac DMG/ZIP 与源码的版本、哈希和构建时间。
