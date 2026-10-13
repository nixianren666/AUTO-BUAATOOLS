# UBAA123 项目接管入口

整理时间：2026-10-12；GitHub 审查补全于 2026-10-13，北京时间。用途：让在本目录工作的后续 Codex 对话快速接手；这是一份可更新的项目记忆，不是全部聊天原文的副本。

**正在实施 v1.2.7 修复：** [V127_IMPLEMENTATION.md](V127_IMPLEMENTATION.md) 记录用户要求、禁止 WSL、隐私边界与尚未通过的发布闸门；逐项修复对应见 [V127_FIX_MATRIX.md](V127_FIX_MATRIX.md)。根目录已有未验收业务修改，不应直接作为可发布版本使用。

**最新状态（2026-10-14）：** [V126_REVIEW.md](V126_REVIEW.md) 完成 v1.2.6 多角度审查；[VERSION_WITHDRAWAL.md](VERSION_WITHDRAWAL.md) 记录实际 v1.3 下架。main/同级Git已恢复5158df8，v1.3 Release/标签已删除，默认EXE已换为核实的v1.2.6，错误发布流水线暂停。旧报告是时间快照，不能据它们认定v1.3仍为当前入口。

**签到/抢课技术机制优先阅读 [UPSTREAM_MECHANISMS.md](UPSTREAM_MECHANISMS.md)。** 2026-10-13 按用户要求抛开历史助手结论，重新固定两套上游源码研究；包含 UBAA 本地/中继链路、AutoBoya 真实后台时序、考勤/考核字段、当前代码差异，以及 55 项上游测试和 16 项独立离线探测。它是独立技术证据，不能与历史记录混为一类。

## 先掌握的事实

1. **产品是 AUTO-BUAATOOLS / AUTO-BUAA / BUAA Signin Pro。** 从 BUAASubnet/UBAA 的常规课堂签到功能独立开发，随后参考 AutoBoya 加入博雅选课、签到、签退。Python 服务 + 原生桌面窗口 + WebUI；支持 Windows、macOS、Linux/Headless、Docker。不是 UBAA 上游项目的完整移植。
2. **业务基线是 v1.2.6。** 用户曾认可其基本功能。2026-10-07 明确要求撤回整个 v1.3 系列；微信 Clawbot 只作为失败尝试留在历史记录，不能重新接回当前产品。
3. **最重要的约束：** 多账号切换不停止其他账号守护；常规自动签到限课前 10 分钟、最多三次尝试；自动博雅仅抢可线上自主签到/签退的课；禁止重复发包；本学期统计不能混入历史数据；成功操作后刷新官方状态。
4. **心跳要求有过更新。** 早期要求每十分钟输出态势；v1.2.6 用户改为课池概览只显示首条，后续同步静默执行。不能只读旧 AGENTS.md 的早期文字就恢复日志刷屏。
5. **最新工作是 UI 原型。** 用户要浅色、透亮、背景细节能穿透、边缘折射高光明显的液态玻璃。最后纠正：“不是背景的问题，是液态玻璃透明度不够。”最后助手提交了新预览，未发现之后的用户验收。
6. **目录仍需区分。** 当前 `ubaa` 没有 `.git`；`ubaa/Github库` 是旧分发快照；同级 `../Github库` 是Git仓库，2026-10-14 HEAD已恢复`5158df8`。当前UI和配置不能被旧内层快照覆盖。
7. **v1.3实际下架已执行。** main与v1.2.6标签一致，v1.3 Release/标签删除，根/dist/同级Git默认EXE哈希均匹配v1.2.6。Mac版本标识和错误发布配置仍需修复，工作流已暂停；下架不等于修好了全部业务。
8. **本版尚未完整验收。** 当前v1.2.6隔离suite为79项、78通过、1项CDP UI失败；另36后端与4前端探测，并由隔离Edge核对基本界面和点击注入。此前86项全通过针对已撤回main，不能混作本版结果。

## 按任务阅读

| 文档 | 解决的问题 |
| --- | --- |
| [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) | 产品功能、用户偏好、架构和字段含义 |
| [UPSTREAM_MECHANISMS.md](UPSTREAM_MECHANISMS.md) | 独立重研 UBAA / AutoBoya 的认证、自动抢选、签到签退、考核和本项目差异 |
| [upstream_mechanism_evidence.json](upstream_mechanism_evidence.json) | 固定上游 commit、源码指纹、55项测试及16项独立探测结果 |
| [HISTORY.md](HISTORY.md) | 版本演进、反复出现的故障、撤回决策、最近工作 |
| [CURRENT_STATE.md](CURRENT_STATE.md) | 当前源码比对结果、已发现的问题、验证边界 |
| [V126_REVIEW.md](V126_REVIEW.md) | 本版准确性、误操作、钓鱼/凭据、后台、多账号及修复优先级 |
| [v126_review_evidence.json](v126_review_evidence.json) | 本轮基线、测试/探测、浏览器、版本清理与隐私验证证据 |
| [VERSION_WITHDRAWAL.md](VERSION_WITHDRAWAL.md) | v1.3下架、main/默认EXE恢复、发布流水线暂停的验证记录 |
| [GITHUB_AUDIT.md](GITHUB_AUDIT.md) | 远端、发布资产、CI、13 个已复现边界问题和后续优先级 |
| [github_audit_evidence.json](github_audit_evidence.json) | 本次远端元数据、资产哈希、测试/Mock/隐私扫描证据 |
| [SOURCES.md](SOURCES.md) | 原始 Antigravity 存储位置、27 个会话索引、覆盖率及检索方法 |
| [USER_REQUEST_INDEX.md](USER_REQUEST_INDEX.md) | 两个主会话共 155 个用户输入记录的脱敏主题索引 |
| [source_manifest.json](source_manifest.json) | 机器可读来源计数、文件指纹、缺失步骤及源码快照指纹 |

## 接手方式

- 实现功能前，核对本次用户要求与这里的最新决策；旧助手的计划和断言不等于用户要求。
- 查一个历史问题时，用来源表中的会话 ID 和 `step_index` 定点读取，不必把一万多条工具记录全部装入上下文。
- 涉及发布时，先处理目录/版本/产物的对应关系。GitHub 在线仓库、Release 元数据与部分产物内部结构已核查；学校接口、用户远端服务器与各平台实机现状没有在本次重新验证。
- `config.json` 当前包含用户账号配置；不要输出内容、覆盖配置、直接启动带真实账号的自动任务，或将它复制为发布模板。
- 旧记录包含“推送成功”“全平台无问题”等过度肯定的说法。历史子任务自己承认部分 GUI/实机环节未测；以实际证据和当前复测为准。
- 初次接管和上游研究只更新文档；2026-10-14又按用户明确要求执行了v1.3下架和默认程序恢复。未改当前签到业务逻辑、未启动带真实账号的学校写操作、未操作用户远端部署服务器或发布新软件版本。

## 新对话如何获得这些内容

项目根目录 AGENTS.md 已指向此入口。后续在这个目录启动的 Codex 对话可依此读取项目背景；这依靠文件持久化，不依靠模型跨对话凭空记忆。新克隆或迁移目录时，需要一起带上 AGENTS.md 与 `docs/handoff/`。

这种做法依据 [OpenAI 官方 AGENTS.md 指南](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。没有修改影响其他项目的全局指令，也没有把旧聊天上传到外部服务。
