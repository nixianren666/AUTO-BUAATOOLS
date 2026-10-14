# v1.2.7 已发布验收记录

2026-10-14，北京时间。用户授权的 bug 修复已发布：[v1.2.7](https://github.com/nixianren666/AUTO-BUAATOOLS/releases/tag/v1.2.7)，标记为 Latest。业务基线来自 v1.2.6，微信功能保持撤回，v1.3 Release/标签未恢复。

- 发布/二进制/源码包提交：`c379c018a66d882698051d01616d0700c3e46950`；最终原生流水线：[run 38521385980](https://github.com/nixianren666/AUTO-BUAATOOLS/actions/runs/38521385980)。
- 同次构建提供 Windows Setup/portable、Apple Silicon 与 Intel macOS 的 DMG/ZIP、Linux x86_64 tar.gz，共七份二进制；另含精确源码ZIP、四平台清单、验收JSON、公开自测向量核实依据和SHA256SUMS，共15份附件。全部GitHub上传摘要与本地核实值一致。
- 四个平台各143项源码，零失败/错误/跳过；各18项编译后检查，含11项真实浏览器、4项原生WebView交互、接口/会话身份及原生窗口。Windows已安装程序再次运行同验收。
- Windows新装/重装/升级/卸载保留用户文件，实际自启命令启动与移除；Linux systemd用户服务、Mac launchctl实际启动/停止/移除。两个DMG原生挂载、应用逐文件hash、plist及签名匹配。
- Windows成品使用computer-use实际操作；发现暗色目标表单、Escape与手动ID文案问题并修复，最后EXE再次检查常规签到、博雅签到/签退、账号隔离及修正文案。详细检查范围见Release验收JSON。
- 编译后的Windows程序使用授权测试账号完成现网SSO、身份匹配、课堂/博雅认证与只读查询。全部自动任务关闭；真实学校签到、签退、选课和退选写入0，凭据落盘0。未保存个人界面截图。
- 推送前全库深度扫描：619个Git可达对象、104个公开文件，已知真实隐私值及敏感模式零命中。产物解压扫描13份文件、2389个归档成员、3424个CArchive成员、4376个PYZ模块，真实隐私值零命中。一个libgnutls PEM模式候选内五段数据逐一匹配[GnuTLS官方公开自测源码](https://github.com/gnutls/gnutls/blob/3.8.3/lib/crypto-selftests-pk.c)，保留原始命中和指纹核实依据；未解释命中0。
- 根目录、dist及同级Git的默认EXE已换为上述最终便携包，SHA-256 `fddee0f48a4be64402ee5d8c23daccfb2081c35045f9e4badd9e8e4b3d0b9ceb`；用户配置和液态玻璃预览未覆盖。`ubaa/Github库`仍为旧分发快照，不能当作当前发布源。

本记录在发布后追加，属于文档提交；v1.2.7标签、精确源码ZIP和四平台二进制始终对应上述已验收提交，不因文档更新重新标记或混用构建。

## 验证边界

Linux原生GUI在Xvfb，无物理托盘宿主，验证可见窗口回退，未做Linux托盘点击；Mac/Linux未做人工桌面点击。未实测物理重启登录、数月挂机或Docker运行。macOS为临时本地签名，未Apple公证。现网只读不代表真实写入验收。隐私扫描不包含OCR或服务端不可达/已删除历史。未安装、下载或使用WSL。

53项缺陷契约见[V127_FIX_MATRIX.md](V127_FIX_MATRIX.md)，实现及六层影响见[V127_IMPLEMENTATION.md](V127_IMPLEMENTATION.md)。不能把“已修复已验证”解释为未来学校接口、网络或教务规则永不变化。
