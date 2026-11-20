# v1.4.19 iClass 签到协议适配与发布交付

## 1. 变更背景与核心机制修复

学校智慧课堂（iClass）升级了签到服务及安全策略，旧版签到端点（`/app/course/stu_sign.action`）在部分新场景下出现线下核实未生效的问题。对齐移动端最新官方协议规范后，完成以下修复：

1. **官方端点与端口规范化**：
   - 更新签到请求路径为官方标准移动端端点：`https://iclass.buaa.edu.cn:8181/app/course/stu_auto_sign.action`。
   - `core/domain.py` 中将 `iclass.buaa.edu.cn` 的 8181 端口纳入受信域名端口白名单。
2. **表单参数与头部结构对齐**：
   - 严格封装 6 项标准表单字段：`id`（课程签到记录 ID）、`courseSchedId`（排课日程 ID）、`routerInfo`（路由器 BSSID/网络标识）、`longitude`（经度）、`latitude`（纬度）、`machineInfo`（终端特征信息）。
   - 将 `sessionId` 作为请求 Header（`sessionId: <token>`）显式传递，移除原 URL 查询参数中多余的 `?sessionId=` 拼接。
   - 签到前强制校验 `sessionId` 有效性，未登录或失效时抛出明确安全异常，严禁伪造成功状态。
3. **测试套件与模拟桩同步**：
   - 同步更新 `core/smoke.py` 中的 Mock 服务路由与请求断言，支持 `stu_auto_sign.action`。
   - 更新 `tests/test_v127_safety.py` 中的端点白名单断言。

---

## 2. 验证边界与测试结果

| 验证项 | 工具 / 方式 | 结果 | 联网与写入边界 |
| :--- | :--- | :--- | :--- |
| **隔离源码契约** | `python scripts/test_isolated.py` | **575 passed, 0 failed, 0 error** | 环回审计拦截，外部联网 0 |
| **动态 UI 端到端交互** | `node scripts/ui_acceptance.cjs` | **136 passed, 0 failed** | 本地沙箱，真实学校写入 0 |
| **无头远程管理流程** | `scripts/verify_remote.py` | **13 passed, 0 failed** | 真实学校写入 0 |
| **首次管理与恢复流程** | `scripts/verify_management_setup.py` | **7 passed, 0 failed** | 真实学校写入 0 |
| **版本元数据格式** | `scripts/check_release_format.py` | **Valid (v1.4.19)** | 一致性校验通过 |
| **发布隐私与敏感词扫描** | `scripts/privacy_scan.py` | **0 findings, 1639 objects scanned** | 无敏感信息泄露 |

---

## 3. 服务器（10.130.152.67:18346）更新与保数据准则

- **保护边界**：
  - 宿主机运行环境不重启，宿主机内核、网卡、GPU、CPU/PID 限制不作变动。
  - 保持同机其他 Docker 容器（`astrbot`、`curryblog`、`napcat` 等）正常运行不受任何影响。
  - 严格保留宿主机数据卷 `auto-buaa_buaa-profile`，保留既有学生账号配置、照片、TD 授权与管理密码。
  - 严格保持 `.env`（权限 0600）及管理密钥。
- **平滑切换流程**：
  - 升级前执行 `server-quiescence` 确认无在途签到/抢课操作。
  - 在 `/opt/auto-buaatools-data-backups` 创建当前版本程序与卷快照。
  - 构建 `auto-buaa:v1.4.19-<commit>` 新镜像，更新 `compose.server.yml`，执行受控重启。
  - 检验 `http://10.130.152.67:18346/api/health` 确保新服务健康在线，版本报告为 `1.4.19`。
