# AUTO-BUAATOOLS · 1.2.7

北航常规课堂签到与博雅课程管理工具。1.2.7 是以已认可的 1.2.6 为基线的修复版本；已撤回的微信功能没有恢复。源码、桌面客户端及 Headless 服务共用同一套提交规则。

## 功能与操作边界

- 多账号分别守护。切换界面只切换当前视图；每次写操作绑定明确账号与课程本体 ID。
- 常规签到限北京时间当日开课前 10 分钟至开课时刻。提交前重新读取本人课表、核对官方时间和官方签到状态；同账号、同排课、同日最多 3 次实际提交。
- 自动博雅抢选仅限有有效地点、半径及完整签到/签退窗口的自主考勤课程。没有线下课自动抢选开关。课程要求的现场参与、作业与考核仍须由使用者完成。
- 自动选课每次提交前核对官方容量、选课窗口、当前学期、校区、普通课表、已选博雅及在途预约的时间冲突。未知时间、未知容量或校历不同步时暂停本门自动操作。
- 默认预约目标为德育 2、劳育 2、美育 1、安全健康 1，可在界面设置 0–20 门。已通过、已预约和结果待确认的名额占用目标；0 表示不自动抢此类。这是自动预约目标，不修改学校考核要求。
- 签到、签退都基于本人官方已选记录与教师开放窗口。界面不会根据时间经过、空 `signInfo` 或单次请求成功推断最终考核通过。
- 博雅课池和已选记录每 60 秒同步，夜间也同步。课池概览只显示首条；故障变化和实际操作透明记录，重复态势不刷屏。
- 手动按钮与后台共用操作账本。超时、解密失败或服务器错误造成写入结果不确定时暂停重发，等待官方记录确认；不确定选课保留预约占位，重启后也参与冲突核对。

## 安全与状态

学校通信启用 TLS 证书验证，仅接受规定的学校 HTTPS 主机/端口，包含 WebVPN 内层目标验证；不继承环境代理。登录过程中出现验证码时暂停自动认证，请在界面手动处理。登录成功与各业务接口就绪分开显示。

本地管理面默认仅监听 `127.0.0.1:18346`，API 使用同源管理会话、HttpOnly Cookie 与 CSRF 校验，并核对 Host/Origin。远程部署必须设置独立应用管理密码和允许的主机。该管理密码不是学校密码。

选择记住密码时，Windows 使用当前用户 DPAPI；macOS/Linux 使用可用的系统凭据库，或由当前用户独占的 0600 随机密钥加密。旧版密文只作读取兼容，保存时升级。秘密解密失败会保留原密文并提示重新登录；配置损坏时不覆盖原文件。会话只在进程内使用；退出会释放本地会话资源，不等于向学校吊销所有已签发凭据。

网络失败返回“数据未同步/上次成功数据”，登录账号不会混入演示课程。学校接受请求而官方记录未更新时显示“待确认”。本学期统计只采用官方校历范围内日期完整的课程，考勤与考核均以官方字段为准；历史累计单独展示。默认类别指标是本项目基线，最终学业判定以学校要求为准。

## Windows / macOS / Linux

正式分发见 [GitHub Releases](https://github.com/nixianren666/AUTO-BUAATOOLS/releases)。发布前必须完成对应原生平台与编译后验证，不能将历史程序换文件名后分发。

Windows 提供安装程序与便携程序；安装、升级和卸载保留用户配置及无关文件。macOS 提供 Apple Silicon 与 Intel 的 DMG/ZIP；应用使用临时本地签名，未承诺 Apple 公证。Linux 提供 x86_64 压缩包，支持 Qt6 桌面及 Headless 模式。相同配置按系统互斥锁/文件锁只启动一个实例，即使端口不同；锁失败停止启动。端口属于无关服务时明确报错。

源码运行（Python 3.12，建议独立虚拟环境）：

```bash
python -m pip install -r requirements.txt
python run.py
# Linux 桌面额外安装 Qt6 后端：
python -m pip install 'pywebview[qt6]==6.2.1'
# 无图形界面：
python run.py --headless --host 127.0.0.1 --port 18346
```

可以用 `BUAA_CONFIG_FILE` 指定独立配置路径。首次使用通过界面添加账号，不把自己的配置文件复制进源码或安装目录模板。

Linux/macOS 用户服务使用与界面相同的 `buaa-signin.service` / `com.buaa.signin`，无需 sudo：

```bash
bash scripts/install_linux_service.sh install
bash scripts/install_linux_service.sh status
# macOS 使用 scripts/install_macos_service.sh，相同命令
# 支持 start / stop / restart / uninstall / update
```

更新入口仅拉取版本常量对应的固定 Release 标签；有本地源码修改时拒绝覆盖，不拉取 main。用户服务需要登录会话/用户服务管理器；登录前运行与退出登录后持续运行取决于系统配置，不能由启用开关保证。

Docker 使用单独持久卷保存配置和加密密钥，不复制开发者配置进镜像。`docker compose up --build -d` 前在环境中设置 `BUAA_ADMIN_PASSWORD`；默认端口只映射到宿主机回环。远程访问需自行配置 HTTPS、允许的 Host 和访问控制。

## 验证与发布

```bash
python scripts/test_isolated.py
python scripts/build_release.py
```

完整测试在临时空配置中执行，阻止学校/第三方网络与注册表写入。UI 使用真实浏览器驱动，学校读写使用合成加密接口。GitHub 手动流水线使用 Windows、Ubuntu、macOS ARM/Intel 原生 runner；逐个平台运行源码、编译后接口、浏览器、原生窗口，以及适用的安装/服务验收，再保存带提交、架构、依赖和 SHA-256 的清单。流水线不自动写 Release。

受控现网已验证认证、身份匹配及只读接口；真实学校签到/选课/退选写入未执行。Mock 和原生程序测试不能保证学校未来接口、网络与教务规则不变。当前工作与逐项验收记录见 [交接入口](docs/handoff/README.md) 与 [1.2.7 修复记录](docs/handoff/V127_IMPLEMENTATION.md)。发布前执行源码、Git 可达对象与构建包敏感信息扫描，截图只使用合成账号。

## 使用约定与来源

用户应遵守学校有关课程出勤、选课、账号和自动化使用的规定。程序不保证免封、百分之百签到或学期达标。网络中断、窗口关闭和学校规则变化都可能影响结果，使用者应核对学校官方记录。

基础机制参考 [BUAASubnet/UBAA](https://github.com/BUAASubnet/UBAA) 与 [DeNeRATe-cool/AutoBoya](https://github.com/DeNeRATe-cool/AutoBoya)。协议研究、历史决策和验证证据见交接文档。许可见 [LICENSE](LICENSE)。
