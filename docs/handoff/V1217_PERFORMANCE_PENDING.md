# 历史检查点：v1.2.17已完成

本待续已被V1217_PERFORMANCE.md及v1217_performance_evidence.json取代，不重复构建、不覆盖配置、不降回1.2.16。默认EXE/便携及同级Git本地同步，未推送发布；当前剩余5%暂停线有效，禁止WSL。以下仅保留执行过程，所有“尚未/待完成”不代表当前待办。

---

# 进行中：1.2.17 渲染性能与不可见停绘

2026-10-17新授权，不重做已交付1.2.16；当前默认EXE仍1.2.16，开发源码1.2.17，未同步同级Git或发布。最新额度线剩余5%（usedPercent>=95），最近查询usedPercent24/resetsAt1792236197；旧45%已撤销。禁止WSL、保护当前配置、不自动发布。

已实现：core/render_lifecycle.py采用Windows实际Z序/不透明完整矩形覆盖检测，检查自身隐藏/最小化，跳过透明/分层/自身进程，前景及相关位置事件+500ms兜底；WebView2公开控件Visible切换，页面独立render-lifecycle.js停绘门控及CSS内容跳过。原Python服务/业务调度不挂起、不TrySuspend。点阵驻留900ms后停止无效重画，流体与鼠标分频定时唤醒；五条宽模糊带半分辨率，细反射保留全分辨率；NEW标签呼吸两轮停止（确认此无限动画会带动整层玻璃高刷合成）。原布局、玻璃材质、业务API/认证/调度不变。启动/控件/浮层/动效模块只补可见性门控。

私有目录C:/Users/cjt16/.codex/tmp/ubaa-v1217-performance-20261017，before92份精确1.2.16不可覆盖，source95份候选。baseline.json、prior-default.exe、配置仅哈希。已取得：旧159/新168项全部通过（新9项覆盖几何/策略）；source-render-check14；原生源码自动13项含最小化/托盘/外部全屏遮挡零帧及恢复、后台接口存活。不是computer-use人工通过：两次activate_window超时，暂未人工操作成功，不保存其他应用截图。

native-performance-summary.json真实本机WebView2指标：旧自身最忙GPU引擎14-16%，新可见静置/驻留2%，最小化/托盘/全屏覆盖四个采样各0%，流体帧数差0；是自身引擎计数，不是整卡利用率或其他机器保证。CPU标为所有自身进程/单核口径，不能错叫整机CPU。原生native-performance-test.py分别before/source顺序测试成功；前一次PS执行策略及hook未初始化异常的失败报告已保留attempt1，生产已初始化cover_hwnd修正。

两尺寸/三时间点逐像素画面对比：流体平均差0.14-0.19/255、p99=2、最大5，细光脊及颜色保留。headless基线及多轮分别记录；参考轮测量不能冒充硬件GPU测试。最终原始后台/业务AST核验check-source.cjs：73文件完全相同、10版本、9呈现/测试入口、3新增；19个发布1.2.7后端业务文件仍一致，app.js整体AST、原HTML/事件/布局、既有动效轨迹可精确逆转核对。

待完成：最新run.py增加Windows仅smoke-test内可见/最小化/托盘停绘与恢复5项，verify_compiled相应拓展23项；最终build正在重新编译（session19217），不要把之前中间产物18项当最终23。source启动/边界与既有31/37/22/21专项正在跑（session47906/30094），都需检查失败并正确修复；最终源码再回归、23成品、成品各专项/render14/同业务11步/整页24、privacy及原生computer-use尝试。source/before已换新端口18779/18777，编译HEADLESS另18738、原生18748，所有合成配置独立。只有最终全部源码/产物完整性一致、隐私验证、安装及同级Git守卫复制后，才能标交付。Mac/Linux没有本轮原生条件，必须如实记录。不要对用户实际默认程序/配置杀进程，不要重放历史GitHub删除/发布命令。
