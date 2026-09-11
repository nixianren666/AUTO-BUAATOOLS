# AUTO-BUAA 课程独立签到助手 Pro (BUAA Signin Pro v1.2.0)

<div align="center">

![AUTO-BUAA Logo](server/static/buaa_logo.svg)

**北航师生专属的轻量化、多账号并发守护、博雅抢课打卡、Origin 极简质感全平台客户端**

[![Version](https://img.shields.io/badge/version-1.2.0--beta-blue.svg)](https://github.com/nixianren666/AUTO-BUAATOOLS)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-blue.svg)](https://github.com/nixianren666/AUTO-BUAATOOLS)

[免责声明](#-免责声明) • [项目介绍](#-项目介绍) • [核心特性](#-核心功能亮点) • [使用方法](#-使用方法) • [Linux & Docker 部署](#方案-5linux-服务器与-docker-极简部署247-云端守护-) • [测试说明与反馈](#-测试阶段说明与问题反馈) • [鸣谢致敬](#-致谢与鸣谢)

</div>

---

## ⚠️ 免责声明

1. **用途限制**：本程序仅供北京航空航天大学师生在日常学习、自动化运维研究及个人开发场景下交流测试使用，**严禁将本软件用于任何商业用途、非法营利或侵害学校正当教学秩序的行为**。
2. **责任边界**：使用本程序所产生的全部选课、签到、签退及出勤判定结果，均由**使用者本人独立承担全部责任与后果**。开发者团队及开源社区不对因软件故障、网络中断、学校官方接口升级或不可抗力等造成的未出勤、错过选课或其他衍生学业损失承担任何法律及民事责任。
3. **安全与协议合规**：本程序为 **100% 纯本地客户端/独立私有服务**，不设任何中心代理服务器，所有鉴权凭据及通信均直接与北航官方服务器（`sso.buaa.edu.cn`、`iclass.buaa.edu.cn`、`bykc.buaa.edu.cn`、`d.buaa.edu.cn`）进行 TLS 加密交互。首次启动将提示签署免责声明，用户须主动确认签署后方可进入使用。

---

## 📖 项目介绍

**AUTO-BUAA** (BUAA Signin Pro) 诞生于对北航师生日常教学与博雅课程管理痛点的深度解决。我们在继承前人优秀开源成果的基础上，对底层通讯协议与交互逻辑进行了彻底重构，打造出集**常规课堂智能守护**与**博雅选修课全生命周期自动化托管**于一体的双核心客户端。

程序前端基于 **Origin Web** 极致极简克制美学与 **Emil Kowalski 微动效系统**，搭配全流体背景粒子与毛玻璃可调透光质感；后端基于轻量高效的异步并发架构，兼顾 Windows/macOS 桌面原生体验，以及 Linux 服务器与 NAS 容器云端 24/7 无人值守守护。

---

## 🌟 核心功能亮点

### 1. 🎓 AUTO-BOYA 博雅选修课全自动托管
- **智能选课池与多维度筛选**：
  - 自动同步最新博雅课程池，支持按“美育”、“劳育”、“国家安全”、“德育”四大人格模块精准筛选；
  - 课程按开抢时间智能倒计时排序，呈现直观选课卡片流。
- **已选课程时序视图**：
  - 提供 `⏳ 未来及正在进行` 与 `📜 历史选课` 快捷过滤，告别繁杂混杂的过往记录。
- **线上托管与安全防御机制**：
  - **自动识别与过滤**：严格剔除需要线下现场核验的课程，仅对支持线上托管的课程启用自动打卡；
  - **全流程签到与签退**：同时覆盖开课签到与结课签退双节点；
  - **地理位置与时间窗口模拟**：严格校验开课签退时间窗口，并内置合规地理位置坐标校验，确保记录合法有效。

### 2. 👥 常规课程多学生并发独立守护
- **账号卡管理与多并发引擎**：
  - 支持同时录入并守护多个学生账号；
  - 各账号后台进程完全独立并发，切换当前操作视图绝不会让其他账号下线。
- **课前 10 分钟离散随机签到**：
  - 仅在各课程开课前 10 分钟至开课刻度区间内（`[课前10分钟, 上课]`）随机规划打卡时间点，杜绝过早抢跑或迟到，真实模拟自然打卡行为；
  - 遇到网络抖动时自动重试（上限 3 次），安全兜底。

### 3. 🌐 智能双模网络自适应
- **智能环境感知**：启动时自动探测网络可达性。若校园网专网（`8346` 端口）直连超时，在 2 秒内**全自动无缝回退至 WebVPN 外网安全通道**，校内校外畅行无阻。
- **加密合规**：内置 AES-128-CFB 动态加解密引擎与 CAS 统一认证流程。

### 4. 🎨 Origin 极简质感与 Emil Kowalski 动效美学
- 遵循 Origin 极简质感设计哲学与 Emil Kowalski 动效系统；
- **环境粒子与流体毛玻璃**：
  - 底层原生 Canvas 随机漂浮粒子动效；
  - 上层覆盖高质感毛玻璃（Backdrop Filter），设置中心提供**单个直观的透光度滑块**，可随心调节磨砂玻璃浓度；
  - 官方标准北航校徽矢量 Logo 与纯净文字标识。

### 5. 🖥️ 全平台深度原生融合与部署生态
- **Windows 原生集成**：托盘常驻守护、单实例防多开唤醒、注册表级免提权开机自启动；
- **macOS 原生适配**：Apple Silicon (M1~M4) / Intel 架构原生编译，支持 DMG 磁盘镜像拖拽安装与 LaunchAgents 开机自启守护；
- **Linux / Docker 云端部署**：全自动感知无显示环境并智能切换至 Headless 纯后端模式，支持通过 `http://<IP>:<PORT>` 局域网/公网远程 WebUI 访问。

---

## 🚀 使用方法

### 方案 1：Windows 标准安装向导（推荐 ⭐⭐⭐）
1. 下载安装包：`BUAA-Signin-Setup-v1.2.0.exe`；
2. 双击打开安装向导，按照提示选择安装路径；
3. 安装程序会自动在桌面与开始菜单创建快捷方式，并支持在 Windows“应用和功能”中一键干净卸载。

### 方案 2：Windows 绿色便携版（免安装 ⭐⭐⭐）
1. 下载可执行文件：`BUAA-Signin.exe` 或 `BUAA-Signin-v1.2.0-portable.exe`；
2. 将程序放置在任意目录（例如桌面或个人工具箱），双击即可直接运行；
3. 绿色便携版将配置文件保存在同级目录下，即插即用，随拷随走。

### 方案 3：macOS 官方独立版（DMG 镜像盘 & 绿色免安装 ZIP ⭐⭐⭐）
1. 在 [Releases 发布页](https://github.com/nixianren666/AUTO-BUAATOOLS/releases) 下载适合您 Mac 的分发包：
   - **Apple Silicon 芯片（M1 / M2 / M3 / M4 等，主流推荐）**：
     - 💿 **DMG 镜像盘**：`BUAA-Signin-macOS-arm64.dmg`（双击挂载磁盘，支持一键拖入 Applications 或直接点开）
     - 📦 **绿色便携 ZIP**：`BUAA-Signin-macOS-arm64.zip`（解压即得 `BUAA-Signin.app`）
   - **Intel 处理器芯片**：
     - 💿 **DMG 镜像盘**：`BUAA-Signin-macOS-x86_64.dmg`
     - 📦 **绿色便携 ZIP**：`BUAA-Signin-macOS-x86_64.zip`
2. **免安装随拷随用**：无论通过 DMG 运行还是解压出的 `BUAA-Signin.app`，都是原生独立应用，双击直接运行，**无需任何安装配置**；
3. **首次启动提示**：开源个人应用初次在 Mac 打开时，若系统 Gatekeeper 提示“无法打开未知开发者”，按住键盘 `Control` 键右键点击应用图标并选择“打开”即可正常运行。

### 方案 4：开发者源码跨平台运行 (Windows / macOS / Linux)
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

### 方案 5：Linux 服务器与 Docker 极简部署（24/7 云端守护 ⭐⭐⭐）

适合部署在 Linux 云服务器 (VPS)、家庭 NAS (群晖 Synology / 极空间 / 威联通 QNAP)、软路由或树莓派上，实现 24 小时全天候无人值守自动抢课签到。

通过浏览器直接访问 `http://<服务器IP>:18346`，即可在任何设备（手机、平板、电脑）上使用全功能 WebUI。

#### 方式 A：Docker Compose 一键部署（极力推荐）
1. 确保已安装 Docker 与 Docker Compose；
2. 在项目根目录下执行：
   ```bash
   docker compose up -d
   ```
3. 部署完成后，在浏览器中打开：
   ```
   http://<你的服务器IP>:18346
   ```
   > 💡 容器默认映射端口 `18346`，并将 `./config.json` 挂载到容器内，配置与账号数据在宿主机持久化保存，升级或重启容器不丢失配置。

#### 方式 B：Docker 原生镜像构建运行
```bash
# 1. 构建 Docker 镜像
docker build -t auto-buaa .

# 2. 后台启动容器并挂载配置
docker run -d \
  --name auto-buaa \
  --restart unless-stopped \
  -p 18346:18346 \
  -v $(pwd)/config.json:/app/config.json \
  auto-buaa
```

#### 方式 C：Linux 终端原生 Python 部署
无需 GUI 桌面环境，程序自动检测并以纯后端 Headless 模式运行：
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 命令行指定参数运行
python run.py --headless --host 0.0.0.0 --port 18346

# 或者直接使用预置启动脚本
chmod +x start-server.sh
./start-server.sh
```

#### 方式 D：Systemd 系统级常驻服务
项目内附带现成 Systemd 服务模板：
```bash
# 1. 拷贝配置文件
sudo cp systemd/auto-buaa.service /etc/systemd/system/

# 2. 根据实际路径调整 WorkingDirectory 和 ExecStart，然后启动
sudo systemctl daemon-reload
sudo systemctl enable --now auto-buaa
```

---

## 🧪 测试阶段说明与问题反馈

> [!IMPORTANT]
> **当前版本：v1.2.0-beta（公共测试版）**
> 
> 本程序目前正处于**公开测试与快速迭代阶段**。尽管核心选课抢课协议、多账号调度逻辑与网络容灾机制经过了严格的单元测试与沙箱验证，但面对学校服务器不同学期接口变动、节假日调休课表、极端弱网环境以及不同版本操作系统的显示缩放差异，软件的稳定性和部分功能体验**未必完全完美**。
> 
> 我们非常重视每一位同学与老师的实际使用体验！
> 如果您在测试过程中遇到以下任何情况：
> - 登录鉴权失败或验证码异常
> - 课表同步不完整或博雅课程池未加载
> - 选课/打卡未准时触发或报错
> - UI 布局错位、窗口缩放不适配或动效卡顿
> 
> **诚挚欢迎在 [GitHub Issues](https://github.com/nixianren666/AUTO-BUAATOOLS/issues) 中向我们提交反馈与建议！** 您的每一次 Issue 都是帮助本项目走向稳定与完善的重要推动力。

---

## 📂 项目工程目录

```
AUTO-BUAATOOLS/
├── BUAA-Signin-Setup-v1.2.0.exe     # Windows 官方安装向导程序
├── BUAA-Signin-v1.2.0-portable.exe  # Windows v1.2.0 绿色免安装便携版
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
│   ├── boya_scheduler.py            # 博雅自动化巡检、抢课与签到调度器
│   ├── cas.py                       # 北航统一认证 SSO CAS 登录与凭据提取
│   ├── iclass.py                    # 课堂签到接口鉴权、排课同步与打卡提交
│   ├── scheduler.py                 # 常规课堂课前10分钟随机规划调度器
│   └── webvpn.py                    # WebVPN 动态加解密与内外网通道适配
├── server/                          # 服务与前端渲染层
│   ├── app.py                       # FastAPI 状态控制中心与跨平台路径自适应
│   └── static/                      # 前端界面资产 (Origin 极简 + Emil Kowalski 微动效)
│       ├── buaa_logo.svg            # 北航高清矢量校徽
│       ├── index.html               # 交互界面结构
│       ├── css/style.css            # 极简质感拟态与流体动效样式
│       └── js/app.js                # 响应式前端状态管理与交互逻辑
├── systemd/                         # Linux 守护进程配置模版
│   └── auto-buaa.service            # Systemd 服务单元文件
├── tests/                           # 自动化单元测试与回归套件 (39 个测试 100% 通过)
│   ├── test_core.py                 # WebVPN、CAS 协议与加解密测试
│   ├── test_api.py                  # API 端点与静态路由集成测试
│   ├── test_autostart.py            # 跨平台自启动逻辑模拟测试 (Win/Mac/Linux)
│   ├── test_multi_account.py        # 多账号并发与调度测试
│   ├── test_boya_crypto.py          # 博雅解密算法测试
│   ├── test_boya_api.py             # 博雅 API 路由测试
│   └── test_boya_scheduler.py       # 博雅调度器测试
├── scripts/
│   └── smoke_test_mac.py            # macOS 自动化冒烟测试脚本
└── installer/                       # Inno Setup Windows 安装包制作配置
    └── setup.iss                    # 安装包编译向导脚本
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
