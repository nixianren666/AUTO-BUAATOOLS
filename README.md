# AUTO-BUAA 北航学生自动托管签到及自动博雅系统 (BUAA Signin Pro v1.2.6)

<div align="center">

![AUTO-BUAA Logo](server/static/buaa_logo.svg)

**北航师生专属的轻量化、多账号并发守护、博雅抢课打卡、Origin 极简质感全平台客户端**

[![Version](https://img.shields.io/badge/version-1.2.6-blue.svg)](https://github.com/nixianren666/AUTO-BUAATOOLS)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-blue.svg)](https://github.com/nixianren666/AUTO-BUAATOOLS)

[免责声明](#-免责声明) • [安全与防封机制](#-核心安全与防封护栏机制消除一切安全顾虑) • [项目介绍](#-项目介绍) • [核心特性](#-核心功能亮点) • [使用方法](#-使用方法) • [Linux & macOS 守护服务](#-linux--macos-247-后台守护服务) • [测试说明与反馈](#-测试阶段说明与问题反馈) • [鸣谢致敬](#-致谢与鸣谢)

</div>

---

## ⚠️ 免责声明

1. **用途限制**：本程序仅供北京航空航天大学师生在日常学习、自动化运维研究及个人开发场景下交流测试使用，**严禁将本软件用于任何商业用途、非法营利或侵害学校正当教学秩序的行为**。
2. **责任边界**：使用本程序所产生的全部选课、签到、签退及出勤判定结果，均由**使用者本人独立承担全部责任与后果**。开发者团队及开源社区不对因软件故障、网络中断、学校官方接口升级或不可抗力等造成的未出勤、错过选课或其他衍生学业损失承担任何法律及民事责任。
3. **安全与协议合规**：本程序为 **100% 纯本地客户端/独立私有服务**，不设任何中心代理服务器，所有鉴权凭据及通信均直接与北航官方服务器（`sso.buaa.edu.cn`、`iclass.buaa.edu.cn`、`bykc.buaa.edu.cn`、`d.buaa.edu.cn`）进行 TLS 加密交互。首次启动将提示签署免责声明，用户须主动确认签署后方可进入使用。

---

## 🛡️ 核心安全与防封护栏机制（消除一切安全顾虑）

针对广大北航同学最为关心的**“账号是否会被封”、“密码是否会泄露”、“网络通信是否安全”、“会不会抢错课导致撞车或旷课”**等核心担忧，AUTO-BUAA 在架构底层确立了**五维安全防线**与**防封风控护栏**：

### 1. 🔒 绝对零隐私泄露与本地私密保障（Zero-Leak Architecture）
- **100% 纯本地私有运行**：本软件为完全独立的离线/本地服务，**绝对不包含任何第三方数据采集、监控、回传代码**，没有任何所谓的“中心服务器”。
- **凭据与密码安全隔离**：用户的学号、统一身份认证密码仅留存在本地 `config.json` 中，绝不会上传至任何外网服务器；会话凭证（Cookie/Session/Token）仅用于与北航官方接口通信，进程退出或用户点击登出时即刻失效。
- **全透明代码开源**：代码 100% 开源并接受全校师生地毯式取证审计，杜绝任何暗门、外挂及恶意行为。

### 2. 🌐 校园专网端到端加密直连，拒绝任何第三方代理中转
- **官方 TLS/HTTPS 直连**：客户端所有 HTTP/HTTPS 网络请求直接发送至北航官方权威服务器：
  - 统一身份认证：`https://sso.buaa.edu.cn`
  - 智慧教学平台：`https://iclass.buaa.edu.cn`
  - 博雅选课平台：`https://bykc.buaa.edu.cn`
  - WebVPN 安全网关：`https://d.buaa.edu.cn`
- **链路完全等同浏览器**：网络通信报文与您在个人电脑 Edge/Chrome 浏览器中直接登录北航官网完全一致，绝不经过任何个人 VPS、爬虫代理池或中间人节点，通信安全受学校官方证书与 TLS 协议严格保护。

### 3. 🛡️ 拟人化抖动与智能频控（Anti-Ban & Anti-Flood）
- **真随机拟人抖动（Jitter Delay）**：每次发起抢课提交、课程签到与状态轮询之间，系统均强制注入 `0.5s ~ 1.2s` 的真随机浮动延时，完全消除机械化、固定周期的请求特征，模拟真实用户的自然点击行为。
- **智能三级熔断与防重机制**：
  - 单门课程抢选连续失败达到 3 次，立即主动触发熔断并跳过该课程，坚决不向学校服务器发送高频无效请求；
  - 若学校接口返回“已选过”、“选课成功”或“不可重复提交”，自动写入历史防重清单，永久停止重复发包，避免触发学校防火墙风控封禁 IP 或账号。
- **夜间自适应降频休眠（Night Quiet Mode）**：
  - 每日 23:30 至次日 07:00 校园就寝及教务系统休眠维护期间，自动进入低功耗低频心跳模式，同步周期自动拉长至 30 分钟，既保护账号安全又符合学生正常作息。

### 4. 🚫 防选错与防撞车：上课时间重叠冲突检测（Overlap Guard）
- **场景痛点**：若程序盲目抢课，抢到了与已有课表（或已选博雅）时间重叠的课程，将导致“分身乏术”、时间冲突与考勤缺席。
- **加固机制**：
  - 在抢课判定前，自动提取候选课程的具体上课时间（`courseStartDate` + `courseStartTime` 至 `courseEndDate` + `courseEndTime`）；
  - 自动遍历对比当前学生的所有常规课堂课表及已选博雅课程，执行严格的时间重叠检测（开区间交集：`max(start1, start2) < min(end1, end2)`）；
  - 只要命中时间冲突，**系统坚决不选并记录跳过日志**，彻底杜绝选错撞车课程。

### 5. 🎯 防选偏与保达标：学期缺口智能优先级权重（Smart Scoping）
- **北航校历精准锁定**：自动对齐北航官方教务校历元数据（`semesterStartDate` 与 `semesterEndDate`），所有历史学期选课完全隔离，绝不跨学期误计入当前进度。
- **动态达标缺口计算**：实时扫描当前学期“德育（缺2）、劳育（缺2）、美育（缺1）、安全健康（缺1）”的完成情况。已修满的板块课程自动降权沉底（权重10），尚未达标的板块赋予最高优先级（`100 + 缺口*10`），将宝贵的网络与算力集中用于帮助同学补齐尚未达标的素养门类。
- **状态与校区全维度熔断**：课程状态若含“已停开”、“已取消”、“未发布”、“已结课”或容量为 0，坚决不选；严格隔离北京校区与杭州国际校区，绝不跨校区错选。

### 6. 🚨 防旷课记过铁律：严格线上自主打卡与线下刷卡考勤隔离护栏（对齐 AutoBoya 机制）
- **致命安全性痛点分析**：
  北航博雅课程中存在大量讲座与沙龙（如各类线下非遗实操工坊、正念心理沙龙等）采用**主办方线下刷卡/纸质核验考勤**，此类课程在官方教务接口中**不配置任何经纬度打卡定位点（`signPointList` 为空）**。如果自动抢课程序盲目将其抢中，软件由于接口客观限制**根本无法为其执行线上自动打卡签到签退**。若学生因未察觉或未亲临现场刷卡，将直接导致博雅旷课违约被学校按《处分办法》记过扣分！
- **对齐 AutoBoya 与核心机制重构**：
  全面重构与吸收 `DeNeRATe-cool/AutoBoya` 的核心设计机制：
  1. **自主签到智能识别（`has_autonomous_sign`）**：严格解析并提取 `courseSignConfig` / `signConfig` 中的 `signPointList` 坐标点集，仅在确认存在有效 GPS 定位点时才判定为线上自主打卡课；
  2. **强制安全防线（`require_auto_sign=True` 默认开启）**：在 `core/boya_scheduler.py` 候选课程筛选中建立强制安全护栏，默认全面拦截所有无位置配置的线下人工/刷卡考勤课，绝不将其加入自动代抢候选；
  3. **透明态势审计心跳**：守护引擎每 10 分钟在个人审计日志中汇报`【全校课池共 X 门（... X门非线上打卡安全排除 ...）】`，杜绝任何暗箱代抢；
  4. **全链路容错回显**：UI 前端清晰标识`[⚡ 线上自主打卡]`与`[🔥 现场刷卡考勤]`，并提供`🛡️ 仅限线上打卡`防误触开关与二次风险警示确认弹窗。

---

## 📖 项目介绍

**AUTO-BUAA** (BUAA Signin Pro) 诞生于对北航师生日常教学签到与博雅课程管理痛点的深度解决。我们在继承前人优秀开源成果的基础上，对底层通讯协议与交互逻辑进行了彻底重构，打造出集**常规课堂智能守护**与**博雅选修课全生命周期自动化托管**于一体的双核心全平台客户端。

程序前端基于 **Origin Web** 极致极简克制美学与 **Emil Kowalski 微动效系统**，搭配全流体背景粒子与毛玻璃可调透光质感；后端基于轻量高效的异步并发架构，兼顾 Windows/macOS 桌面原生体验，以及 Linux 服务器与 macOS 终端 24/7 无人值守常驻守护。

---

## 🌟 核心功能亮点

### 1. 🎓 AUTO-BOYA 博雅选修课全自动托管
- **智能选课池与多维度筛选**：
  - 自动同步最新博雅课程池，支持按“美育”、“劳育”、“安全健康”、“德育”四大素养模块精准筛选；
  - 课程按开抢时间智能倒计时排序，呈现直观抢课卡片流。
- **自主选课与自动抢课全生命周期守护**：
  - 无论是由程序**全自动秒抢**的课程，还是**同学在学校官方选课网站自主选中**的博雅课程，系统均会自动检测识别并同步纳入守护；
  - 严格剔除需要现场核验的非线上课程，仅对支持线上托管的课程启用自动打卡；
  - 周期性轮询北航 SSO 鉴权状态与排课数据，内置合规动态地理坐标兜底，自动完成开课签到与结课签退。
- **课程时序状态流转与真实状态反馈**：
  - **严格时序流转**：结课课程严格自动下线，从“未来及正在进行”流转至“历史选课”，杜绝结课后误留退选、签到操作；
  - **实时状态显示**：在“未来及正在进行”中，卡片操作按钮实时联动学校 SSO 真实状态，动态呈现禁用态“✅ 已签到”与“🏁 已签退”，防止误触与重复打卡。
- **历史选课全维度考核看板**：
  - 在“历史选课”中为每门课程透出清晰的官方考核指标：**考勤是否通过**、**考核是否通过**以及**最终考核双通过（达标）**状态。
- **本学期博雅素养达标考核统计**：
  - 依照北航官方每学期博雅素养考核标准构建考核看板（德育 2 门、劳育 2 门、美育 1 门、安全健康 1 门，基准共 6 门）；
  - 动态呈现四大模块完成进度徽章与学期综合达标完成百分比，一目了然掌握当学期学分素养达标状态。
- **防重复风控与多维度日志隔离**：
  - 自动阻断已抢成功课程的重复轮询提交，避免高频请求触发学校服务器风控；
  - 日志系统针对不同学生完全隔离，并分设“当前学生总日志”、“常规课程日志”与“自动博雅日志”三类视图，排错一目了然。

### 2. 👥 常规课程多学生并发独立守护
- **账号卡管理与多并发引擎**：
  - 支持同时录入并守护多个学生账号；
  - 各账号后台守护线程完全独立并发，切换当前操作视图绝不会中断其他账号的守护。
- **课前 10 分钟离散随机签到**：
  - 仅在各课程开课前 10 分钟至开课刻度区间内（`[课前10分钟, 上课]`）随机规划打卡时间点，杜绝过早抢跑或迟到，真实模拟自然打卡行为；
  - 遇到网络抖动时自动重试（上限 3 次），安全兜底。

### 3. 🌐 智能双模网络自适应
- **智能环境感知**：启动时自动探测网络可达性。直连模式与 WebVPN 模式双向互备：在校内直连专网（`8346` 端口），若校外或网络受限则 2 秒内**全自动无缝回退至 WebVPN 外网安全通道**，校内校外畅行无阻。
- **加密合规**：内置 AES-128-CFB 动态加解密引擎与 CAS 统一认证流程。

### 4. 🎨 Origin 极简质感与 Emil Kowalski 动效美学
- 遵循 Origin 极简质感设计哲学与 Emil Kowalski 动效系统；
- **环境粒子与流体毛玻璃**：
  - 底层原生 Canvas 随机漂浮粒子动效；
  - 上层覆盖高质感毛玻璃（Backdrop Filter），设置中心提供**单个直观的透光度滑块**，可随心调节磨砂玻璃浓度；
  - 官方标准北航校徽矢量 Logo 与纯净文字标识。

### 5. 🖥️ 全平台深度原生融合与 24/7 守护生态
- **Windows 原生集成**：托盘常驻守护、单实例防多开唤醒、注册表级免提权开机自启动；
- **macOS 原生适配**：Apple Silicon (M1~M4) / Intel 双架构独立 App、DMG 镜像安装、LaunchAgent 24/7 系统级后台守护服务，并附带 Gatekeeper 免拦截一键修复工具；
- **Linux / Docker 云端部署**：全自动感知无显示环境并智能切换至 Headless 纯后端模式，提供一键式 Systemd 守护服务管理脚本与 Docker Compose 容器化支持，通过 `http://<IP>:18346` 远程 WebUI 访问。

---

## 🚀 使用方法

### 方案 1：Windows 标准安装向导（推荐 ⭐⭐⭐）
1. 在 [Releases 发布页](https://github.com/nixianren666/AUTO-BUAATOOLS/releases) 下载安装包：`BUAA-Signin-Setup-v1.2.5.exe`；
2. 双击打开安装向导，按照提示选择安装路径；
3. 安装程序会自动在桌面与开始菜单创建快捷方式，并支持在 Windows“应用和功能”中一键干净卸载。

### 方案 2：Windows 绿色便携版（免安装 ⭐⭐⭐）
1. 下载可执行文件：`BUAA-Signin.exe` 或 `BUAA-Signin-v1.2.5-portable.exe`；
2. 将程序放置在任意目录（例如桌面或个人工具箱），双击即可直接运行；
3. 绿色便携版将配置文件保存在同级目录下，即插即用，随拷随走。

### 方案 3：macOS 官方独立版（DMG 镜像盘 & 绿色便携 ZIP ⭐⭐⭐）
1. 在 [Releases 发布页](https://github.com/nixianren666/AUTO-BUAATOOLS/releases) 下载适合您 Mac 的分发包：
   - **Apple Silicon 芯片（M1 / M2 / M3 / M4 等，主流推荐）**：
     - 💿 **DMG 镜像盘**：`BUAA-Signin-macOS-arm64.dmg`（双击挂载磁盘，支持一键拖入 Applications 或直接点开）
     - 📦 **绿色便携 ZIP**：`BUAA-Signin-macOS-arm64.zip`（解压即得 `BUAA-Signin.app`）
   - **Intel 处理器芯片**：
     - 💿 **DMG 镜像盘**：`BUAA-Signin-macOS-x86_64.dmg`
     - 📦 **绿色便携 ZIP**：`BUAA-Signin-macOS-x86_64.zip`
2. **免安装随拷随用**：无论通过 DMG 拖拽至“应用程序”运行还是解压出的 `BUAA-Signin.app`，都是原生独立应用，双击直接运行；
3. **彻底解决 Gatekeeper“已损坏”或“无法验证开发者”拦截**：
   - **方法 A（项目自带一键修复脚本）**：
     ```bash
     bash scripts/fix_macos_gatekeeper.sh
     ```
   - **方法 B（终端原生单行命令）**：
     ```bash
     sudo xattr -rd com.apple.quarantine /Applications/BUAA-Signin.app
     ```
   - **方法 C（访达图形界面方式）**：
     在访达（Finder）中找到该应用，按住键盘 `Control` 键同时右键点击应用图标，在弹出菜单中点击“打开”，并在弹出对话框中再次确认“打开”即可，系统后续将永久记住并允许直接启动。

---

## 🛠️ Linux & macOS 24/7 后台守护服务

针对希望将本系统部署在家庭 NAS、Linux 云服务器 (VPS)、软路由、树莓派或长期不关机的 Mac 上的同学，我们提供了**开箱即用的系统级 24/7 守护脚本**，支持开机自启、故障自动拉起、后台静默运行与一键在线升级。

### 1. Linux 服务器：Systemd 一键服务管理

项目提供一站式管理脚本 `scripts/install_linux_service.sh`：

```bash
# 1. 克隆代码并进入目录
git clone https://github.com/nixianren666/AUTO-BUAATOOLS.git
cd AUTO-BUAATOOLS

# 2. 一键安装并启动 24/7 后台服务（开机自启、自动安装依赖）
bash scripts/install_linux_service.sh install

# 3. 日常运维命令
bash scripts/install_linux_service.sh status     # 查看服务运行状态
bash scripts/install_linux_service.sh logs       # 实时跟踪滚动日志
bash scripts/install_linux_service.sh restart    # 重启服务
bash scripts/install_linux_service.sh update     # 拉取最新代码并平滑重启服务
bash scripts/install_linux_service.sh uninstall  # 干净卸载后台服务
```

服务启动后，通过浏览器访问 `http://<服务器IP>:18346` 即可在任意设备上使用全功能 WebUI。

### 2. macOS 终端：LaunchAgent 一键服务管理

项目为 Mac 终端环境提供了原生的 launchd 用户级常驻守护脚本 `scripts/install_macos_service.sh`：

```bash
# 1. 克隆代码并进入目录
git clone https://github.com/nixianren666/AUTO-BUAATOOLS.git
cd AUTO-BUAATOOLS

# 2. 一键安装 LaunchAgent 常驻后台服务
bash scripts/install_macos_service.sh install

# 3. 日常运维命令
bash scripts/install_macos_service.sh status     # 查看运行状态与 PID
bash scripts/install_macos_service.sh logs       # 跟踪日志输出
bash scripts/install_macos_service.sh update     # 拉取最新 git 代码并自动重启
bash scripts/install_macos_service.sh restart    # 重启后台守护
bash scripts/install_macos_service.sh uninstall  # 卸载后台守护
```

### 3. Docker & Docker Compose 容器化部署

```bash
# 方式 A：Docker Compose 一键部署
docker compose up -d

# 方式 B：Docker 原生构建运行
docker build -t auto-buaa:v1.2.5 .
docker run -d \
  --name auto-buaa \
  --restart unless-stopped \
  -p 18346:18346 \
  -v $(pwd)/config.json:/app/config.json \
  auto-buaa:v1.2.5
```

---

## 💻 开发者源码跨平台运行

1. **克隆代码并进入目录**：
   ```bash
   git clone https://github.com/nixianren666/AUTO-BUAATOOLS.git
   cd AUTO-BUAATOOLS
   ```
2. **安装 Python 运行依赖**（推荐 Python 3.10+）：
   ```bash
   pip install -r requirements.txt
   ```
3. **启动客户端**：
   ```bash
   python run.py
   ```
   Windows 下亦可双击 `start.bat` / `启动签到软件.bat`。

---

## 🧪 测试阶段说明与问题反馈

> [!IMPORTANT]
> **当前版本：v1.2.5（安全防护与博雅护栏重大增强版）**
> 
> 本版本重点进行了核心安全性重构：
> 1. **博雅自动抢课安全护栏（对齐 AutoBoya 机制）**：自动抢课引擎默认开启 `🛡️ 仅限线上打卡`（`require_auto_sign=True`），严格排除现场刷卡考勤课程，坚决杜绝因无法自动线上打卡而导致旷课记过扣分；
> 2. **态势感知与心跳审计透明化**：个人审计日志每 10 分钟汇报全校课池态势及安全排除门数，消除一切暗箱代抢顾虑；
> 3. **常规课程签到机制对齐 UBAA**：强化会话过期自动刷新与请求重试容错；
> 4. **全套自动化测试 100% 通过**：包含 77 项全链路测试与 Headless Edge 端到端真实运行验证。
> 
> 我们非常重视每一位同学与老师的实际使用体验！
> 如果您在日常使用过程中遇到任何问题或有改进建议：
> 
> **诚挚欢迎在 [GitHub Issues](https://github.com/nixianren666/AUTO-BUAATOOLS/issues) 中向我们提交反馈！** 您的每一次反馈都是本项目不断精进的重要动力。

---

## 📂 项目工程目录

```
AUTO-BUAATOOLS/
├── BUAA-Signin-Setup-v1.2.5.exe     # Windows 官方安装向导程序
├── BUAA-Signin-v1.2.5-portable.exe  # Windows v1.2.5 绿色免安装便携版
├── BUAA-Signin.exe                  # Windows 单文件绿色版主程序
├── BUAA-Signin.spec                 # Windows PyInstaller 一键打包规格
├── BUAA-Signin-mac.spec             # macOS PyInstaller 独立 App 打包规格
├── Dockerfile                       # Linux / Docker 容器化构建文件
├── docker-compose.yml               # Docker Compose 一键式编排模版
├── start-server.sh                  # Linux 极简后台服务启动脚本
├── README.md                        # 项目详细说明文档、多平台使用指南与免责条款
├── config.json                      # 纯净配置文件模板（严格脱敏，无任何隐私泄露）
├── requirements.txt                 # Python 跨平台运行时依赖列表
├── run.py                           # 统一启动入口（自动感知 GUI/Headless 环境）
├── start.bat / 启动签到软件.bat      # Windows 极简双击启动脚本
├── tray_icon.png                    # 系统托盘图标资产
├── .github/workflows/
│   └── build-macos.yml              # macOS 多架构 CI/CD 自动构建及发布工作流
├── core/                            # 核心底层业务与网络通讯协议
│   ├── autostart.py                 # 跨平台自启动管理 (Windows / macOS / Linux)
│   ├── boya_client.py               # 博雅选课池拉取、抢课提交与打卡签退
│   ├── boya_crypto.py               # 博雅平台 AES-128-ECB 动态解密
│   ├── boya_scheduler.py            # 博雅自动化巡检、抢课与签到调度器（支持自主选课守护与防旷课护栏）
│   ├── cas.py                       # 北航统一认证 SSO CAS 登录与凭据提取
│   ├── iclass.py                    # 课堂签到接口鉴权、排课同步与打卡提交
│   ├── scheduler.py                 # 常规课堂课前10分钟随机规划调度器
│   └── webvpn.py                    # WebVPN 动态加解密与内外网通道适配
├── server/                          # 服务与前端渲染层
│   ├── app.py                       # FastAPI 状态控制中心与多维数据聚合 (v1.2.5)
│   └── static/                      # 前端界面资产 (Origin 极简 + Emil Kowalski 微动效)
│       ├── buaa_logo.svg            # 北航高清矢量校徽
│       ├── index.html               # 交互界面结构 (v1.2.5 学期达标统计 + 实时状态 + 防旷课护栏)
│       ├── css/style.css            # 极简质感拟态与流体动效样式
│       └── js/app.js                # 响应式前端状态管理与时序流转逻辑
├── systemd/                         # Linux 守护进程配置模版
│   └── auto-buaa.service            # Systemd 服务单元文件
├── scripts/                         # 自动化运维与多平台工具脚本
│   ├── install_linux_service.sh     # Linux 24/7 Systemd 服务全生命周期管理
│   ├── install_macos_service.sh     # macOS 24/7 LaunchAgent 服务全生命周期管理
│   ├── fix_macos_gatekeeper.sh      # macOS Gatekeeper 免拦截一键修复工具
│   └── smoke_test_mac.py            # macOS 自动化冒烟测试脚本
├── tests/                           # 自动化单元测试与回归套件 (77 个测试 100% 通过)
│   ├── test_core.py                 # WebVPN、CAS 协议与加解密测试
│   ├── test_api.py                  # API 端点与静态路由集成测试
│   ├── test_autostart.py            # 跨平台自启动逻辑模拟测试 (Win/Mac/Linux)
│   ├── test_multi_account.py        # 多账号并发与调度测试
│   ├── test_boya_crypto.py          # 博雅解密算法测试
│   ├── test_boya_api.py             # 博雅 API 路由测试
│   ├── test_boya_scheduler.py       # 博雅调度器与防旷课护栏测试
│   ├── test_boya_categories_and_filters.py # 安全健康四大模块筛选测试
│   └── test_boya_lifecycle.py       # 博雅生命周期流转、考核与学期达标统计测试
└── installer/                       # Inno Setup Windows 安装包制作配置
    └── setup.iss                    # 安装包编译向导脚本 (v1.2.5)
```

---

## 🔒 隐私安全与数据保护

- **本地化存储**：所有账号密码均仅保存在您本地设备中，绝不向任何第三方服务器上传任何身份数据；
- **开源可审查**：全部业务代码、加解密逻辑与通信细节 100% 开源，欢迎审计审查；
- **配置纯净**：发布版本中的 `config.json` 经严格脱敏重置，零残留任何开发或测试人员的隐私数据。

---

## 🙏 致谢与鸣谢

本项目的诞生与进化离不开北航开源先驱们的卓越探索。我们在此对以下开源项目致以崇高的敬意与由衷的感谢：

1. **[UBAA](https://github.com/BUAASubnet/UBAA/)**：
   - 感谢 BUAASubnet 团队在北航校园网络接入、统一认证 CAS 表单提取以及日常课堂打卡协议层面的深入研究与先驱贡献，为本项目的常规课程自动化打卡体系奠定了坚实的基础。
2. **[autoboya](https://github.com/)**：
   - 感谢 autoboya 项目在北航博雅选修课选课机制、加解密算法以及线上签到签退流程上的先锋探索，为本项目构建智能博雅托管与选课安全过滤机制提供了不可替代的灵感与技术参考。

---

<div align="center">
  <sub>Built with ❤️ for BUAAers</sub>
</div>
