<div align="center">

<img src="server/static/images/app_logo.png" width="88" alt="AUTO-BUAA 标识">

# AUTO-BUAA

**常规课堂签到 · 博雅预约与考勤 · 多账号后台守护**

把课表、博雅课程和考勤状态，放进一个清晰的桌面。

[![Version](https://img.shields.io/badge/version-1.2.7-38bdf8)](https://github.com/nixianren666/AUTO-BUAATOOLS/releases/latest)
[![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-8b5cf6)](#下载与安装)
[![License](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![Downloads](https://img.shields.io/github/downloads/nixianren666/AUTO-BUAATOOLS/total?label=downloads&color=38bdf8)](https://github.com/nixianren666/AUTO-BUAATOOLS/releases)

[**下载客户端**](https://github.com/nixianren666/AUTO-BUAATOOLS/releases/latest) · [界面展示](#界面展示) · [功能介绍](#能帮你做什么) · [安全与隐私](#怎么减少漏选错选和重复操作) · [部署指南](#源码与后台部署) · [问题反馈](https://github.com/nixianren666/AUTO-BUAATOOLS/issues)

</div>

AUTO-BUAA 是面向北航学生的开源课程管理工具：同步今日课堂和博雅课池，在允许的窗口内执行签到、预约和签退，集中展示选课、考勤与学期进度。你可以在桌面使用，也可以部署为自己的后台服务，通过浏览器管理。

**适合希望减少重复操作、管理多个账号，并及时掌握官方课程状态的同学。** 程序协助管理，不替代课程参与、现场要求、作业和考核；考勤与最终达标请以学校官方记录为准。

## 界面展示

<div align="center">
<img src="docs/images/product-tour.gif" width="1120" alt="AUTO-BUAA 界面动图：博雅课池、已选课程、账号中心和常规课堂">
</div>

*动图来自实际运行的客户端界面，全部使用合成演示账号、课程与成绩，不含真实学生信息。*

<details>
<summary><b>查看静态截图：常规课堂、博雅课池与已选课程</b></summary>

**今日课堂：** 查看排课、签到状态和后台守护开关。

![常规课堂仪表盘，合成数据演示](docs/images/regular-dashboard.png)

**博雅课池：** 类别筛选、名额、校区与本学期进度集中呈现。

![博雅课程仪表盘，合成数据演示](docs/images/boya-dashboard.png)

**已选课程：** 分清签到、签退与考核状态，按官方条件开放操作按钮。

![博雅已选课程，合成数据演示](docs/images/boya-selected.png)

**账号中心：** 切换当前操作视图，保持其他账号的守护任务独立运行。

![账号管理中心，合成数据演示](docs/images/account-center.png)

</details>

## 能帮你做什么

| 功能 | 使用体验 |
| --- | --- |
| **今日课堂一览** | 自动读取本人今日课表，显示课程时间、教室、教师与签到状态；支持刷新和指定排课 ID 签到 |
| **课前自动签到** | 在开课前十分钟内安排签到，发送前再核实本人排课、官方时间与状态 |
| **博雅课程发现** | 同步全量课池，按德育、劳育、美育、安全健康筛选，支持课程/教师搜索、校区及名额筛选 |
| **按目标自动预约** | 各类别预约目标可单独设置；把已通过、已预约和待确认的课程纳入目标，减少重复抢选 |
| **博雅签到与签退** | 对有完整自主考勤配置的已选课程，依据教师开放窗口执行；手动操作和自动守护共用核验机制 |
| **学期与历史进度** | 区分本学期和历史课程，分别展示考勤、考核与最终通过；未知数据不会被填成达标 |
| **多账号独立守护** | 每个账号有独立开关和日志；切换当前界面不停止其他账号的后台任务 |
| **后台常驻与日志** | 支持托盘、单实例唤醒和自启动；按学生、常规课程、博雅分类查看操作及异常 |
| **清晰的桌面界面** | 深色卡片、动态背景、可调玻璃透光度；已完成、已过期或条件不足的操作有对应提示 |
| **多种运行方式** | Windows 安装/便携版、Mac 双架构 App、Linux 桌面、Headless 服务与 Docker 部署 |

默认预约目标为 **德育 2、劳育 2、美育 1、安全健康 1**，可按需求调整为每类 0–20 门；设为 0 表示不自动抢该类。这些数字是程序的预约目标，不能替代学校的培养与考核要求。

学校官网上已经选中的博雅课程也会同步到“已选修课程”。仅有有效自主考勤配置、本人已选且当前窗口开放的课程，才允许本程序执行对应签到/签退。

## 怎么减少漏选、错选和重复操作

### 持续发现新课和退课名额

博雅课池及已选记录每 **60 秒**同步，夜间也保持同步；后台每 **10 秒**检查操作窗口。自动抢选前会重新读取当前课池，避免拿启动时的旧名额提交。首次记录课池态势，后续重复信息静默处理；实际操作、故障和重要变化仍显示在日志中。

这能减少依赖旧缓存造成的遗漏，但不保证抢到所有课程：名额竞争、网络中断、认证失效和学校接口变化仍可能影响结果。

### 选课前，把条件核对清楚

| 自动抢选会核对什么 | 为什么需要这一步 |
| --- | --- |
| **本学期与所选校区** | 避免历史课和不匹配校区进入自动预约 |
| **官方选课窗口与剩余名额** | 未开放、已关闭、已满或容量不明时不提交 |
| **完整自主签到/签退配置** | 同时需要有效地点、半径及教师窗口；不会自动抢仅能现场刷卡/人工登记的课程，也没有放开此限制的开关 |
| **普通课堂、已选博雅与在途预约的时间** | 自动抢选比较三种时间冲突，避免刚抢到一门又撞上下一门 |
| **类别目标和已占用名额** | 目标已被已通过/预约/待确认课程覆盖时，停止额外抢选 |
| **课程本体 ID 与账号身份** | 按 ID 关联数据，不凭同名课程猜地点、窗口或选课身份 |

这些冲突、校区和类别目标保护针对**自动抢选**。手动选择也会检查最新课池、容量和选课窗口，但仍须自行核对课程适合度、时间冲突与参与要求。

### 签到前再确认，结果不明时先停住

- **常规课：** 仅本人北京时间当日排课、课前十分钟至开课时刻；读取与认证完成后、实际发送前再次核对。手动输入 ID 也不能补签已开课或未选课程。
- **博雅课：** 仅本人已选，检查官方考勤状态、教师签到/签退窗口与地点配置；缺少有效条件就暂停，不按课程时间自行猜窗口。
- **共享防重：** 手动按钮与后台使用同一套锁和本地持久操作账本；常规签到同账号、同课、同日最多三次实际提交。
- **超时不盲重发：** 请求已经发送而结果不明时，显示待确认并保留记录。待确认选课继续占用预约目标与冲突位置，重启后也不会直接当作未选重抢。
- **官方确认后更新界面：** 区分“请求已提交”和“学校记录已确认”；签到、签退或时间经过都不直接算成考核通过。

## 账号与隐私如何保护

**业务在你的设备或你自己的服务上运行。** 项目不要求把账号交给开发者托管；统一认证、课堂与博雅业务通过学校官方接口完成，源码可以公开审查。

| 保护机制 | 实际含义 |
| --- | --- |
| **HTTPS 与可信目标检查** | 学校通信验证 TLS 证书和允许的主机/端口，并检查官方 WebVPN 内层地址，减少错误跳转和凭据误发风险 |
| **记住密码时加密保存** | Windows 使用当前用户 DPAPI；Mac/Linux 使用可用系统凭据库，或当前用户独占的随机密钥加密，避免明文配置 |
| **会话只留在进程中** | Cookie/Token 用于业务访问；退出释放本地会话资源，但不代表学校已吊销所有凭据 |
| **本地管理默认回环** | 默认访问 `127.0.0.1:18346`，管理 API 有会话、Host/Origin 和 CSRF 检查；远程部署还需要独立管理密码 |
| **异常不覆盖秘密** | 密钥或配置读取失败时保留原文件并提示处理；不会为“恢复登录”把密码转存为明文 |
| **公开分发与个人配置分开** | 发布包不附带开发者/测试账号配置；源码与发布内容经过敏感信息检查，展示画面使用合成数据 |

界面会请求 Google Fonts 字体资源；受限网络下回退系统字体。学号和密码不会被拼入字体请求参数。后台学校业务不继承系统环境代理。

自己的配置、加密密钥和日志仍应妥善保管。迁移设备后，受原系统用户保护的密码可能需要重新输入；反馈问题时请遮住学号、姓名、Cookie、Token 和个人课程信息。

## 下载与安装

**优先从本仓库的 [GitHub Releases](https://github.com/nixianren666/AUTO-BUAATOOLS/releases/latest) 下载。** 每次发行提供对应平台的程序和 `SHA256SUMS.txt`，便于核对文件是否完整、是否与发行内容一致。

| 平台 | 当前下载文件 | 怎么选 |
| --- | --- | --- |
| Windows x64 安装版 | `BUAA-Signin-Setup-v1.2.7.exe` | 推荐日常使用，带安装向导、快捷方式和卸载入口 |
| Windows x64 便携版 | `BUAA-Signin-v1.2.7-portable.exe` | 希望免安装，放入自己的工具目录直接运行 |
| Mac Apple Silicon | `BUAA-Signin-v1.2.7-macOS-arm64.dmg` / `.zip` | M 系列芯片选 arm64 |
| Mac Intel | `BUAA-Signin-v1.2.7-macOS-x86_64.dmg` / `.zip` | Intel 芯片选 x86_64 |
| Linux x86_64 | `BUAA-Signin-v1.2.7-Linux-x86_64.tar.gz` | 桌面或无界面的 Linux 设备 |
| 源码 | `AUTO-BUAATOOLS-v1.2.7-source.zip` | 自行运行、部署或开发；也可克隆仓库 |

### Windows

1. 安装版双击 Setup 按向导安装；便携版放进可写目录后直接运行。
2. 添加账号，选“自动”网络模式，等待常规课堂与博雅分别完成认证。
3. 确认校区、预约目标和各项自动任务开关，再按需求开启守护。

安装、升级和卸载保留个人配置及无关文件。配置可能位于程序旁或 `%APPDATA%\BUAA-Signin`，取决于已有配置与目录可写性；不要把自己的配置分享为安装模板。重复打开同一配置会唤醒已有实例。

### macOS：安装和首次打开

1. 在“关于本机”确认是 Apple 芯片还是 Intel，下载对应架构。
2. DMG 打开后把 `BUAA-Signin.app` 拖到“应用程序”；ZIP 解压后也可把 App 移入该目录。
3. 启动 App，添加账号并检查认证状态。通常配置保存在 `~/Library/Application Support/BUAA-Signin`。

<details open>
<summary><b>提示“无法验证开发者”或“Apple 无法检查是否包含恶意软件”怎么办？</b></summary>

当前 Mac 应用采用本地签名，尚未经过 Apple 公证，首次打开可能出现门禁提示。确认文件来自本仓库 Release、摘要与发行清单一致后，可以只允许这个 App：

1. 先尝试打开一次 App。
2. 进入 **系统设置 → 隐私与安全性**，找到这次被阻止的 App，选择 **仍要打开**。
3. 按系统提示再次确认打开；后续通常可正常启动。

这为该 App 创建例外，无须关闭整个系统的门禁。步骤参考 [Apple 官方首次打开说明](https://support.apple.com/zh-cn/102445)。

如果提示“已损坏”或明确检测到恶意软件，先重新下载并核对摘要，附上已脱敏的提示提交 Issue；不要把所有安全提示一律当成可忽略的签名问题。

</details>

### Linux：桌面或 Headless

解压发行包，在程序目录运行：

```bash
tar -xzf BUAA-Signin-v1.2.7-Linux-x86_64.tar.gz
chmod +x BUAA-Signin
./BUAA-Signin
```

桌面版需要可用图形会话和 Qt6 对应系统库。Ubuntu/Debian 可按缺库提示安装，例如：

```bash
sudo apt-get install libegl1 libopengl0 libgl1 libxcb-cursor0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-shape0 \
  libxcb-render-util0 libxcb-xinerama0 libxkbcommon-x11-0 libpulse0
```

无桌面的服务器可直接运行：

```bash
./BUAA-Signin --headless --host 127.0.0.1 --port 18346
```

然后访问 `http://127.0.0.1:18346`。Linux 通常使用 `~/.config/buaa-signin/config.json`；已有程序旁/当前目录配置可能优先使用。当前 Linux 二进制为 x86_64，其他架构请按源码方式自行适配。

## 第一次使用：三步完成设置

1. **添加账号，确认接入。** 查看常规课堂、博雅各自认证状态；校内校外可选自动模式尝试校园网直连和官方 WebVPN。需要验证码时请手动处理。
2. **设置自己需要的任务。** 常规签到、博雅自动抢选、博雅签到签退分别控制；先核对账号、校区与预约目标，避免把“切换界面”误认为“暂停其他账号”。
3. **查看状态与官方记录。** 在今日课堂、已选课程和分类日志里核对结果。遇到“未同步”“待确认”，先核对学校官网，不要连续点击重试。

开启任务但配置保存失败时，程序撤回开启；暂停仍立即生效。若暂停后出现未保存提示，请重新保存，避免重启沿用磁盘里的旧开关。

## 源码与后台部署

### 源码运行

推荐 Python 3.12，使用独立虚拟环境。Windows 使用 `.venv\Scripts\python.exe`，Mac/Linux 使用 `.venv/bin/python`：

```bash
git clone https://github.com/nixianren666/AUTO-BUAATOOLS.git
cd AUTO-BUAATOOLS
python -m venv .venv
```

| 系统 | 安装依赖 | 启动 |
| --- | --- | --- |
| Windows | `.venv\Scripts\python.exe -m pip install -r requirements.txt` | `.venv\Scripts\python.exe run.py` |
| Mac/Linux | `.venv/bin/python -m pip install -r requirements.txt` | `.venv/bin/python run.py` |

Linux 源码桌面模式还需安装 `.venv/bin/python -m pip install 'pywebview[qt6]==6.2.1'` 和前述图形库。仅 Headless 运行可使用 `.venv/bin/python run.py --headless`。系统只有 `python3` 命令时，用 `python3 -m venv .venv` 创建环境。

需要隔离多个部署时，使用 `--config /你的路径/config.json` 或 `BUAA_CONFIG_FILE` 指定配置。加密密钥也应随部署妥善保存。

### Linux / macOS 用户后台服务

先完成上面的源码依赖安装，再以实际使用账号运行服务脚本，**不要 sudo/root 安装用户服务**：

```bash
# Linux
bash scripts/install_linux_service.sh install
bash scripts/install_linux_service.sh status
bash scripts/install_linux_service.sh logs

# macOS
bash scripts/install_macos_service.sh install
bash scripts/install_macos_service.sh status
```

两套脚本均支持 `start / stop / restart / status / uninstall / update`；Linux 的 `logs` 跟随 journal，Mac 操作日志请在软件界面查看。卸载服务保留配置。

Linux 单元为 `buaa-signin.service`，Mac LaunchAgent 为 `com.buaa.signin`。它们以当前用户运行、默认监听回环地址。无人值守、退出登录后继续运行或开机尚未登录时运行，取决于系统用户服务环境；不是勾选自启就能保证。

`update` 校验本项目 Git 来源、拒绝覆盖本地源码修改，只切到当前程序指定的固定发行标签，**不是自动追踪 main 或未来版本**。升级到新版本时请先查看对应 Release 的升级说明。

### Docker / NAS

在已安装 Docker 的设备上，在仓库目录使用 Compose：

```bash
# 在当前 shell 设置一个独立的应用管理密码，不要使用学校密码
export BUAA_ADMIN_PASSWORD='换成你自己的独立管理密码'
docker compose up --build -d
docker compose logs -f
```

PowerShell 使用 `$env:BUAA_ADMIN_PASSWORD = '你的独立管理密码'` 设置环境变量。配置和加密密钥保存在 `buaa-profile` 持久卷；镜像不复制开发者个人配置，容器以非 root 用户运行。

默认只映射宿主机回环 `127.0.0.1:18346`，本机浏览器访问即可。远程服务器优先通过 SSH 隧道访问：

```bash
ssh -L 18346:127.0.0.1:18346 你的用户@你的服务器
```

在自己电脑打开 `http://127.0.0.1:18346`。若要直接远程开放，必须配置独立管理密码、`BUAA_ALLOWED_HOSTS`，并自行设置 HTTPS 和访问控制。Docker 部署提供源码与配置方案，尚未完成本轮容器运行实测；Windows 客户端本身不需要 Docker 或 WSL。

## 项目怎么工作

桌面窗口与浏览器使用同一套 WebUI。FastAPI 汇总各账号状态，后台调度器定期读取课表/课池；手动操作与自动任务在共享规则和账本下执行。统一认证连接学校 SSO，校园网直连或官方 WebVPN 提供对应业务通道。

```mermaid
flowchart LR
  UI[桌面窗口 / 浏览器] --> API[本地 FastAPI]
  API --> Actions[账号与操作规则]
  Jobs[常规 / 博雅后台调度] --> Actions
  Actions --> Clients[学校接口客户端]
  Clients --> SSO[官方 SSO / iClass / 博雅]
  Actions --- Ledger[本地防重账本]
  Clients --> State[官方状态 / 同步结果]
  State --> API
```

```text
AUTO-BUAATOOLS/
├── run.py                      # 桌面 / Headless 统一启动入口
├── core/
│   ├── cas.py / webvpn.py       # SSO 与官方 WebVPN 认证通道
│   ├── iclass.py               # 常规课堂排课与签到
│   ├── boya_client.py          # 博雅官方数据和提交接口
│   ├── domain.py               # 身份、日期、状态与窗口契约
│   ├── boya_actions.py         # 手动 / 自动博雅操作预检
│   ├── operations.py           # 持久防重与待确认预约账本
│   ├── scheduler.py            # 常规课堂后台调度
│   ├── boya_scheduler.py       # 博雅同步、选课与考勤调度
│   ├── vault.py / profile.py   # 凭据保护与配置位置
│   └── autostart.py            # 跨平台自启动
├── server/
│   ├── app.py / management.py  # API、账号管理与管理面会话
│   └── static/                 # HTML / CSS / JavaScript 桌面界面
├── scripts/                    # 用户服务、构建与验证脚本
├── tests/                      # 规则、边界、并发与界面回归
├── installer/                  # Windows 安装包定义
├── docs/images/                # 合成数据界面截图与演示动图
├── config.example.json         # 空白配置示例；个人 config.json 不提交
├── requirements.txt            # 源码运行依赖
└── Dockerfile / docker-compose.yml
```

## 常见问题

**为什么登录成功，却暂时没有常规课或博雅数据？** 统一认证和两个业务系统的授权分开完成；查看各自状态及日志。失败时保留上次成功数据并标记未同步，不会拿演示课程填充你的账号。

**为什么有名额也不自动抢？** 可能不在选课窗口、不是本学期/所选校区、类别目标已占满、存在时间冲突，或没有完整自主考勤配置。数据无法核实也会暂停；请按日志说明核对。

**为什么已经签退，学期完成数还是没增加？** 签退只是考勤记录的一部分，最终通过依学校考勤与考核字段判定。作业、现场参与、考核审核等仍可能尚未完成。

**为什么某些课不能自动签到/退选？** 老师未开放窗口、考勤配置不完整、已有记录或课程已结束都会限制操作；线下刷卡/人工考勤需要按学校要求参与。已记录考勤、已通过或已结束的课不在程序中退选。

**退出或休眠后还能工作吗？** 程序彻底退出、设备关机或休眠时无法继续发请求。需要持续后台守护，应保持设备、网络和用户服务可用，并定期核对官方结果。

**遇到问题怎么反馈？** 在 [GitHub Issues](https://github.com/nixianren666/AUTO-BUAATOOLS/issues) 提供系统/架构、程序版本、操作步骤和脱敏后的提示即可；不要上传个人配置、账号密码、Token 或未遮挡的个人截图。

## 开源、贡献与致谢

代码以 [MIT License](LICENSE) 开源。欢迎反馈界面体验、协议兼容和规则边界问题，也欢迎提交改进。

机制研究与实现参考 [BUAASubnet/UBAA](https://github.com/BUAASubnet/UBAA) 和 [DeNeRATe-cool/AutoBoya](https://github.com/DeNeRATe-cool/AutoBoya)，感谢上游对北航认证、课堂与博雅协议的探索。本项目不是学校官方产品，与上游项目也不是同一个客户端。

**版本变化、修复内容与升级说明，请看 [Releases](https://github.com/nixianren666/AUTO-BUAATOOLS/releases)。** 开发与验证资料在 [docs/handoff](docs/handoff/README.md)，供参与开发时查阅。

请遵守学校的账号、课程出勤和选课规定。程序无法承诺百分之百抢课、免封或学期达标；网络、设备、学校规则与官方接口的变化都可能影响结果。

<div align="center">
<sub>Built for BUAAers · 开源、可审查，在自己的设备上运行</sub>
</div>
