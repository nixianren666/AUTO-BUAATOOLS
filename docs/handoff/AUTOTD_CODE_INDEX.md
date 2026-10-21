# AutoTD 逐文件与逐函数索引

2026-10-19。本索引定位实际审阅的代码；不是仅靠函数名作出结论。业务解释见[AUTOTD_MECHANISMS.md](AUTOTD_MECHANISMS.md)，风险见[AUTOTD_REVIEW.md](AUTOTD_REVIEW.md)。

Python基线为PyPI 0.1.15；云端基线为历史99fd3656。行号均对应未改动原件。函数/方法含内部函数，匿名JS回调按所属函数/事件链审阅，不将静态索引冒充动态分支覆盖。

## Python 发行程序

| 文件 | 行数 | 定义数 | 职责 |
|---|---:|---:|---|
| `auto_td/__init__.py` | 6 | 0 | 版本、测试/交互导出的 quick 子模块 |
| `auto_td/background.py` | 185 | 10 | 启动/停止/状态/PID解析、Windows tasklist/taskkill、Unix信号 |
| `auto_td/cli.py` | 425 | 29 | 命令解析、用户/图片/次数/运行/定时/遥测操作、后台worker与汇总 |
| `auto_td/client.py` | 151 | 11 | 裸TCP帧、打卡/照片、次数提取、时间窗口与响应判定 |
| `auto_td/constants.py` | 8 | 0 | 北京时间、缺省日内窗口、超时、轮询、目录常量 |
| `auto_td/limits.py` | 14 | 2 | 缓存32阈值与跳过说明 |
| `auto_td/logging_utils.py` | 80 | 6 | 按日期切日志、formatter、控制台/文件handler |
| `auto_td/models.py` | 109 | 8 | 用户验证/序列化、单次/单用户/批次结果模型 |
| `auto_td/paths.py` | 11 | 1 | AUTOTD_HOME及用户缺省目录 |
| `auto_td/quick.py` | 72 | 5 | 校区别名、设备方向过滤、随机机位/图片选择 |
| `auto_td/runner.py` | 115 | 4 | 前台逐用户完整流水线、计数记录、睡眠及逐用户异常隔离 |
| `auto_td/scheduler.py` | 468 | 26 | 日内窗口、逐日状态机、等待/入口/出口/错误/迁移/轮询/合并 |
| `auto_td/storage.py` | 264 | 32 | 初始化/迁移/导入、用户/图片CRUD、设置/状态/次数JSON读写 |
| `auto_td/telemetry.py` | 455 | 35 | 缺省开关、实例/密钥、事件快照、签名、入队/发送/失败恢复 |
| `auto_td/ui.py` | 350 | 25 | 本地HTTP服务、8种API操作、multipart、静态资源/图片与错误映射 |

共15个Python文件、194个函数/方法定义。

### auto_td/__init__.py

版本、测试/交互导出的 quick 子模块。

| 定义 | 起止行 |
|---|---|

### auto_td/background.py

启动/停止/状态/PID解析、Windows tasklist/taskkill、Unix信号。

| 定义 | 起止行 |
|---|---|
| `start_scheduler_process` | 37–53 |
| `stop_scheduler_process` | 56–82 |
| `get_scheduler_status` | 85–95 |
| `read_pid_file` | 98–104 |
| `write_pid_file` | 107–109 |
| `clear_pid_file` | 112–118 |
| `is_process_running` | 121–132 |
| `terminate_process` | 135–139 |
| `_is_process_running_windows` | 142–164 |
| `_terminate_process_windows` | 167–185 |

### auto_td/cli.py

命令解析、用户/图片/次数/运行/定时/遥测操作、后台worker与汇总。

| 定义 | 起止行 |
|---|---|
| `main` | 32–46 |
| `build_parser` | 49–131 |
| `cmd_init` | 134–140 |
| `cmd_user_add` | 143–154 |
| `cmd_user_list` | 157–165 |
| `cmd_user_show` | 168–174 |
| `cmd_user_update` | 177–200 |
| `cmd_user_delete` | 203–210 |
| `cmd_user_count` | 213–229 |
| `cmd_image_add` | 232–236 |
| `cmd_image_list` | 239–243 |
| `cmd_run` | 246–263 |
| `run_once_foreground` | 266–269 |
| `cmd_daemon_worker` | 272–293 |
| `cmd_daemon_worker.request_stop` | 277–278 |
| `cmd_stop` | 296–303 |
| `cmd_status` | 306–312 |
| `cmd_ui` | 315–316 |
| `cmd_schedule_show` | 319–322 |
| `cmd_schedule_set` | 325–336 |
| `cmd_telemetry_status` | 339–343 |
| `cmd_telemetry_enable` | 346–352 |
| `cmd_telemetry_disable` | 355–359 |
| `cmd_telemetry_sync` | 362–366 |
| `print_summary` | 369–373 |
| `_storage` | 376–380 |
| `_add_user_identity_args` | 383–393 |
| `_user_args_to_dict` | 396–407 |
| `_require_manual_user_args` | 410–421 |

### auto_td/client.py

裸TCP帧、打卡/照片、次数提取、时间窗口与响应判定。

| 定义 | 起止行 |
|---|---|
| `TDClient.__init__` | 18–31 |
| `TDClient.request` | 33–49 |
| `TDClient.check` | 51–77 |
| `TDClient.upload_photo` | 79–88 |
| `TDClient.query_count` | 90–104 |
| `TDClient.build_check_data` | 106–117 |
| `TDClient._connection_error_message` | 119–125 |
| `extract_exercise_count` | 128–132 |
| `clean_server_message` | 135–136 |
| `_recv_exact` | 139–146 |
| `_timestamp_in_allowed_windows` | 149–151 |

### auto_td/constants.py

北京时间、缺省日内窗口、超时、轮询、目录常量。

| 定义 | 起止行 |
|---|---|

### auto_td/limits.py

缓存32阈值与跳过说明。

| 定义 | 起止行 |
|---|---|
| `has_reached_td_limit` | 8–10 |
| `td_limit_message` | 13–14 |

### auto_td/logging_utils.py

按日期切日志、formatter、控制台/文件handler。

| 定义 | 起止行 |
|---|---|
| `DailyFileHandler.__init__` | 11–16 |
| `DailyFileHandler.emit` | 18–24 |
| `DailyFileHandler.setFormatter` | 26–29 |
| `DailyFileHandler.close` | 31–35 |
| `DailyFileHandler._ensure_handler` | 37–48 |
| `setup_logging` | 51–80 |

### auto_td/models.py

用户验证/序列化、单次/单用户/批次结果模型。

| 定义 | 起止行 |
|---|---|
| `User.from_dict` | 19–36 |
| `User.validated` | 38–47 |
| `User.to_dict` | 49–60 |
| `BatchResult.total` | 83–84 |
| `BatchResult.success_count` | 87–88 |
| `BatchResult.failure_count` | 91–92 |
| `_read_int` | 95–103 |
| `_image_name` | 106–109 |

### auto_td/paths.py

AUTOTD_HOME及用户缺省目录。

| 定义 | 起止行 |
|---|---|
| `get_app_home` | 7–11 |

### auto_td/quick.py

校区别名、设备方向过滤、随机机位/图片选择。

| 定义 | 起止行 |
|---|---|
| `build_quick_user` | 20–42 |
| `normalize_campus` | 45–49 |
| `_machine_pool` | 52–57 |
| `_is_campus_machine` | 60–64 |
| `_is_direction_machine` | 67–72 |

### auto_td/runner.py

前台逐用户完整流水线、计数记录、睡眠及逐用户异常隔离。

| 定义 | 起止行 |
|---|---|
| `run_user_pipeline` | 20–73 |
| `run_all_users` | 76–103 |
| `sleep_with_countdown` | 106–110 |
| `_record_count` | 113–115 |

### auto_td/scheduler.py

日内窗口、逐日状态机、等待/入口/出口/错误/迁移/轮询/合并。

| 定义 | 起止行 |
|---|---|
| `in_any_window` | 22–29 |
| `parse_window` | 32–34 |
| `run_scheduler_once` | 37–117 |
| `run_forever` | 120–137 |
| `clear_today_errors` | 140–156 |
| `format_today_status` | 159–177 |
| `_hhmm_to_minutes` | 180–186 |
| `_sleep_with_stop` | 189–193 |
| `_load_today_user_states` | 196–216 |
| `_remove_deleted_user_states` | 219–224 |
| `_discard_due_actions_outside_window` | 227–255 |
| `_perform_due_action` | 258–276 |
| `_perform_entrance` | 279–322 |
| `_perform_exit` | 325–370 |
| `_discard_current_round` | 373–384 |
| `_mark_error` | 387–395 |
| `_status_batch` | 398–403 |
| `_new_user_state` | 406–415 |
| `_completed_user_state` | 418–432 |
| `_record_count` | 435–437 |
| `_merge_counts_from_disk` | 440–443 |
| `_random_wait_seconds` | 446–447 |
| `_action_label` | 450–451 |
| `_localize` | 454–457 |
| `_iso` | 460–461 |
| `_parse_due_at` | 464–468 |

### auto_td/storage.py

初始化/迁移/导入、用户/图片CRUD、设置/状态/次数JSON读写。

| 定义 | 起止行 |
|---|---|
| `AppStorage.__init__` | 14–23 |
| `AppStorage.initialize` | 25–45 |
| `AppStorage.load_config` | 47–48 |
| `AppStorage.save_config` | 50–51 |
| `AppStorage.load_users` | 53–55 |
| `AppStorage.save_users` | 57–58 |
| `AppStorage.list_users` | 60–61 |
| `AppStorage.get_user` | 63–64 |
| `AppStorage.get_user_model` | 66–70 |
| `AppStorage.save_user` | 72–76 |
| `AppStorage.delete_user` | 78–82 |
| `AppStorage.validate_user` | 84–92 |
| `AppStorage.add_image` | 94–106 |
| `AppStorage.list_images` | 108–111 |
| `AppStorage.delete_image` | 113–122 |
| `AppStorage.image_path` | 124–125 |
| `AppStorage.load_settings` | 127–130 |
| `AppStorage.save_settings` | 132–133 |
| `AppStorage.update_settings` | 135–138 |
| `AppStorage.load_state` | 140–141 |
| `AppStorage.save_state` | 143–144 |
| `AppStorage.set_last_count` | 146–163 |
| `AppStorage.get_last_count` | 165–169 |
| `AppStorage._import_legacy_project` | 171–198 |
| `AppStorage._write_template_config` | 200–202 |
| `AppStorage._migrate_localhost_server_default` | 204–215 |
| `default_settings` | 218–224 |
| `default_state` | 227–228 |
| `load_legacy_jsonl` | 231–244 |
| `_read_json` | 247–249 |
| `_write_json` | 252–256 |
| `_deep_update` | 259–264 |

### auto_td/telemetry.py

缺省开关、实例/密钥、事件快照、签名、入队/发送/失败恢复。

| 定义 | 起止行 |
|---|---|
| `TelemetryTransport.post_json` | 24–31 |
| `UrlJsonTransport.post_json` | 35–61 |
| `ensure_telemetry_state` | 64–89 |
| `enable_telemetry` | 92–105 |
| `disable_telemetry` | 108–118 |
| `get_telemetry_status` | 121–131 |
| `queue_length` | 134–138 |
| `enqueue_install_initialized` | 141–142 |
| `enqueue_run_requested` | 145–146 |
| `enqueue_daemon_started` | 149–150 |
| `enqueue_daemon_stopped` | 153–154 |
| `enqueue_stop_requested` | 157–158 |
| `enqueue_user_changed` | 161–172 |
| `enqueue_snapshot_event` | 175–180 |
| `enqueue_td_count_changed` | 183–216 |
| `enqueue_daily_midnight_snapshot` | 219–231 |
| `enqueue_event` | 234–255 |
| `flush_telemetry_queue` | 258–306 |
| `_registration_payload` | 309–317 |
| `_register_installation` | 320–333 |
| `_post_event` | 336–351 |
| `_snapshot_payload` | 354–368 |
| `_queue_path` | 371–372 |
| `_append_queue` | 375–380 |
| `_read_queue` | 383–391 |
| `_write_queue` | 394–404 |
| `_mark_registered` | 407–410 |
| `_mark_unregistered` | 413–416 |
| `_is_unknown_installation_error` | 419–420 |
| `_record_sent` | 423–428 |
| `_record_last_error` | 431–435 |
| `_url` | 438–439 |
| `_signature` | 442–443 |
| `_json_body` | 446–447 |
| `_local_now` | 450–455 |

### auto_td/ui.py

本地HTTP服务、8种API操作、multipart、静态资源/图片与错误映射。

| 定义 | 起止行 |
|---|---|
| `UiService.__init__` | 39–40 |
| `UiService.get_state` | 42–75 |
| `UiService.list_images` | 77–91 |
| `UiService.save_uploaded_image` | 93–105 |
| `UiService.delete_image` | 107–109 |
| `UiService.add_user` | 111–124 |
| `UiService.delete_user` | 126–133 |
| `UiService.toggle_background` | 135–154 |
| `UiService.run_once` | 156–175 |
| `UiService._storage` | 177–181 |
| `serve_ui` | 184–198 |
| `_today_payload` | 201–218 |
| `_make_handler` | 221–350 |
| `_make_handler.UiRequestHandler.do_GET` | 223–241 |
| `_make_handler.UiRequestHandler.do_POST` | 243–259 |
| `_make_handler.UiRequestHandler.do_DELETE` | 261–271 |
| `_make_handler.UiRequestHandler.log_message` | 273–274 |
| `_make_handler.UiRequestHandler._read_json` | 276–281 |
| `_make_handler.UiRequestHandler._read_multipart_upload` | 283–304 |
| `_make_handler.UiRequestHandler._send_static` | 306–308 |
| `_make_handler.UiRequestHandler._send_image` | 310–320 |
| `_make_handler.UiRequestHandler._send_json` | 322–324 |
| `_make_handler.UiRequestHandler._send_error` | 326–327 |
| `_make_handler.UiRequestHandler._send_exception` | 329–335 |
| `_make_handler.UiRequestHandler._send_bytes` | 337–348 |

## 本地前端、模板与发行信息

| 文件 | 职责/审阅重点 |
|---|---|
| `ui_static/app.js` | 请求、busy、渲染、增删、后台toggle、即时批次、初始刷新；7项VM探测 |
| `ui_static/index.html` | 页面控件/ID/表单/无障碍标签与所有绑定入口 |
| `ui_static/styles.css` | 浅色变量、焦点、表格横向滚动、900px布局、reduced-motion；无业务判定 |
| `templates/config.json` | 服务/学校/事件及静态两校区机位模板；未作真实学校连接 |
| `templates/settings.json` | 三窗口与60秒轮询；与constants缺省值核对 |
| `pyproject.toml` / `setup.cfg` / `MANIFEST.in` | Python入口/版本/依赖/包资源与排除规则；没有把项目安装进用户环境 |
| wheel METADATA/WHEEL/entry_points/RECORD | 与sdist包内容核对；24条摘要和大小有效 |

### local-ui 命名函数

| 定义 | 行 |
|---|---|
| `setNotice` | 11 |
| `requestJson` | 16 |
| `badgeClass` | 30 |
| `statusLabel` | 37 |
| `actionLabel` | 47 |
| `renderUsers` | 55 |
| `renderImages` | 103 |
| `renderState` | 132 |
| `refresh` | 149 |
| `withBusy` | 155 |
| `deleteUser` | 172 |
| `deleteImage` | 179 |

### historical-worker 命名函数

| 定义 | 行 |
|---|---|
| `handleRequest` | 13 |
| `registerInstallation` | 60 |
| `acceptEvent` | 82 |
| `applyEvent` | 120 |
| `applySnapshot` | 154 |
| `normalizeUsers` | 166 |
| `eventFromRow` | 176 |
| `isAdmin` | 187 |
| `unauthorized` | 197 |
| `responseError` | 201 |
| `json` | 205 |
| `adminJson` | 210 |
| `requireString` | 214 |
| `signPayload` | 220 |
| `signText` | 224 |
| `timingSafeEqual` | 236 |
| `dayFrom` | 245 |
| `todayDay` | 249 |
| `adminHtml` | 258 |
| `loadJson` | 289 |
| `cell` | 294 |
| `upsertInstallationSql` | 316 |
| `markInstallationAbsentSql` | 329 |
| `upsertStudentSql` | 333 |
| `upsertInstallationStudentSql` | 345 |
| `insertDailyInstallationSnapshotSql` | 358 |
| `insertDailyStudentSnapshotSql` | 364 |
| `getInstallationSecretSql` | 376 |
| `getEventSql` | 380 |
| `insertEventSql` | 384 |
| `insertTdDeltaSql` | 390 |
| `summarySql` | 396 |
| `listUsersSql` | 407 |
| `listEventsSql` | 421 |
| `dailySql` | 429 |

### historical-pages 命名函数

| 定义 | 行 |
|---|---|
| `initialize` | 30 |
| `refreshDashboard` | 57 |
| `fetchAdminJson` | 91 |
| `renderLoading` | 107 |
| `renderOverview` | 122 |
| `renderChart` | 134 |
| `chartLabels` | 190 |
| `renderUsers` | 200 |
| `renderEvents` | 220 |
| `renderError` | 235 |
| `metricCard` | 250 |
| `tableMessage` | 254 |
| `payloadSummary` | 258 |
| `parsePayload` | 270 |
| `eventIsWarning` | 280 |
| `loadSettings` | 284 |
| `saveSettings` | 298 |
| `normalizeEndpoint` | 305 |
| `todayInShanghai` | 310 |
| `formatTime` | 323 |
| `formatClock` | 336 |
| `formatNumber` | 345 |
| `shortId` | 351 |
| `safeText` | 356 |
| `showToast` | 364 |
| `escapeHtml` | 374 |

## 历史云端及工程文件

| 文件/目录 | 审阅内容 |
|---|---|
| `telemetry-worker/src/index.js` | 全部路由、签名/管理员授权、注册、事件重放、快照、SQL、备用HTML |
| `telemetry-worker/migrations/0001_initial.sql` | 7表/主键/索引及与真实SQLite语义对应关系 |
| `telemetry-worker/wrangler.toml` | Worker入口、兼容日期、D1绑定；未部署、未访问真实D1 |
| `telemetry-worker/README.md` / package.json | 设计声明及测试入口；不执行部署说明、不读取文档中仓库外凭据路径 |
| `telemetry-worker/test/worker.test.js` | 原10测试与FakeD1的语义覆盖；新增真实SQLite 14项探测 |
| `telemetry-pages/app.js` | token存储/4接口/并行加载/日筛选/图表/搜索/HTML转义及日期回退 |
| `telemetry-pages/index.html` / styles.css | 管理令牌/endpoint表单、统计/表格/趋势、交互状态及断点 |
| `telemetry-pages/README.md` / package.json / test/static.test.js | 静态部署设计与原1项测试；未安装依赖或发布Pages |
| `.github/workflows/ci.yml` | 历史仅Ubuntu/Python3.10–3.12；没有当作当前全平台验证 |
| `.gitignore` / LICENSE / 历史pyproject.toml | 排除规则、历史MIT与当前发行元数据差异；不移除任何第三方许可 |

## 上游测试与本轮探测索引

原Python：57项；历史Node：11项。两组是上游已有测试。新增40+7+14=61项包含正向防护与边界复现，不是59个独立漏洞。

### 后端边界

- `test_P01_success_substring_accepts_negative_sentence`
- `test_P02_count_refresh_uses_write_frame_outside_window`
- `test_P03_unbounded_response_length`
- `test_P04_end_minute_inclusive`
- `test_P05_no_academic_calendar_gate`
- `test_P06_prior_semester_count_still_stops_new_year`
- `test_P07_unobserved_external_count_not_refreshed`
- `test_P08_legacy_attempt_becomes_complete_without_success`
- `test_P09_all_users_reuse_poll_start_time`
- `test_P10_skipped_closed_window_keeps_stale_exit`
- `test_P11_exit_after_one_hour_not_locally_rejected`
- `test_P12_transient_error_remains_sticky`
- `test_P13_clearing_exit_error_restarts_entrance`
- `test_P14_state_save_failure_replays_entry`
- `test_P15_manual_pipeline_does_not_update_daily_progress`
- `test_P16_manual_reentry_has_no_daily_budget`
- `test_P17_pid_file_is_not_atomic_singleton`
- `test_P18_any_live_pid_is_trusted`
- `test_P19_stop_timeout_reports_stopped_true`
- `test_P20_scheduler_can_undo_concurrent_telemetry_disable`
- `test_P21_flush_drops_events_appended_during_send`
- `test_P22_telemetry_200_error_body_clears_queue`
- `test_P23_endpoint_change_keeps_registered_flag`
- `test_P24_non_https_telemetry_endpoint_is_accepted`
- `test_P25_broken_telemetry_queue_escapes_flush_try`
- `test_P26_one_invalid_user_blocks_all_before_per_user_guard`
- `test_P27_bad_schedule_is_saved_then_breaks_poll`
- `test_P28_deleting_referenced_photo_allows_entry_before_failure`
- `test_P29_direction_mismatch_accepted`
- `test_P30_arbitrary_html_accepted_as_image`
- `test_P31_cross_origin_and_foreign_host_no_auth`
- `test_P32_http_body_length_has_no_application_cap`
- `test_P33_telemetry_default_and_plain_identifier_snapshot`
- `test_P34_quick_flags_are_not_parsed_by_builder`
- `test_P35_completed_rounds_are_local_not_server_count`
- `test_P36_mid_round_user_edit_switches_exit_machine`
- `test_P37_same_identifier_readd_inherits_pending_action`
- `test_P38_stop_ui_label_can_claim_stopped_while_result_false`
- `test_P39_rounds_above_official_daily_max_is_accepted`
- `test_P40_wait_range_does_not_enforce_official_max_elapsed`

### 本地前端VM

- `F01-old-refresh-overwrites-new`：No request generation or response ordering guard
- `F02-delete-leaves-real-delete-button-enabled`：The busy state targets refreshButton; deletion has no exclusion guard
- `F03-manual-run-and-daemon-toggle-overlap`：Both operation requests can be pending concurrently
- `F04-entire-batch-failure-still-success-notice`：All-failure result is presented with success styling
- `F05-no-polling-or-request-timeout`：Only initial refresh, action refresh or manual refresh; hanging fetch has no application timeout
- `F06-http200-invalid-json-becomes-empty-object`：JSON parse failure on HTTP 200 is silently converted to {}
- `F07-render-text-is-not-innerHTML`：Positive protection: local user text is assigned via textContent

### 历史云端SQLite/VM

- `C01-unauthenticated-reregister-replaces-secret`：Knowing an installation ID is sufficient to replace its signing secret via registration
- `C02-signed-self-reported-delta-is-not-school-verified`：Delta and provenance are trusted from the client; no school verification or source restriction
- `C03-admin-absent-token-rejected`：Positive: admin data requires the configured token
- `C04-invalid-event-signature-rejected`：Positive: HMAC is checked for event intake
- `C05-older-duplicate-clears-current-presence`：Actual SQLite: an older signed duplicate resets present flags to zero despite newer snapshots
- `C06-duplicate-id-ownership-is-not-checked`：Given another installation event ID, duplicate processing can cross installation ownership and replace its secret
- `C07-admin-query-token-accepted`：Admin credential is accepted in the URL and embedded in inline JavaScript
- `C08-fallback-dashboard-HTML-not-escaped`：Stored text enters innerHTML unescaped; harmless markup injection reproduced, no live-service exploit attempted
- `C09-registration-timestamp-is-not-validated`：Untrusted registered_at is persisted as a date without format/range validation
- `C10-primary-dashboard-invalid-date-HTML-sink`：Primary Pages escapes user IDs but inserts invalid date fallback strings without escaping
- `C11-primary-dashboard-localStorage-token`：Persistent browser storage holds a reusable admin credential; bearer header is used for requests
- `C12-partial-DB-write-survives-request-failure`：No transaction: event row and presence reset persist despite HTTP 500
- `C13-SQL-parameter-binding-keeps-markup-literal`：Positive: SQL bind parameters prevent text from becoming SQL syntax
- `C14-deleting-local-user-does-not-delete-cloud-history`：Deletion snapshot marks absence while retaining historical student records

