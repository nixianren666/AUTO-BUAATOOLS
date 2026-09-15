"""
多账号自动打卡与定时巡检后台任务模块
严格限制在上课前 10 分钟随机分布时间打卡，失败最多重试 3 次
"""

import asyncio
import datetime
import logging
import random
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("buaa_signin_scheduler")


class SigninScheduler:
    def __init__(
        self,
        get_active_accounts: Callable[[], List[Dict[str, Any]]],
        on_event_log: Optional[Callable[[str, str, Optional[str], Optional[str]], None]] = None,
        reconnect_account: Optional[Callable[[Any], Any]] = None,
    ):
        """
        get_active_accounts: 回调函数，返回所有启用了自动签到的账号字典列表:
            [{"username": "...", "name": "...", "client": IclassClient, ...}]
        on_event_log: 日志回调 (level, message, username, user_name)
        reconnect_account: 异步账号重连回调
        """
        self.get_active_accounts = get_active_accounts
        self.on_event_log = on_event_log or (lambda level, msg, uname, rname: None)
        self.reconnect_account = reconnect_account
        self.enabled = False
        self._task: Optional[asyncio.Task] = None
        self.interval_seconds = 20  # 巡检轮询频率（默认20秒检查一次）

        # 状态追踪字典，以 (username, course_id) 为键
        self.signed_courses: Set[Tuple[str, str]] = set()
        self.retry_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        self.planned_targets: Dict[Tuple[str, str], datetime.datetime] = {}
        self.failed_permanently: Set[Tuple[str, str]] = set()

    def log(
        self,
        message: str,
        level: str = "info",
        username: Optional[str] = None,
        user_name: Optional[str] = None,
    ):
        self.on_event_log(level, message, username, user_name)
        if level == "error":
            logger.error(f"[{username or '系统'}] {message}")
        else:
            logger.info(f"[{username or '系统'}] {message}")

    def start(self, interval_seconds: int = 20):
        if self.enabled:
            return
        self.enabled = True
        self.interval_seconds = max(10, interval_seconds)
        self._task = asyncio.create_task(self._run_loop())
        self.log("多账号自动签到巡检守护已启动（严格执行上课前10分钟内随机打卡策略）。", "info")

    def stop(self):
        if not self.enabled:
            return
        self.enabled = False
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        self.log("多账号自动签到巡检守护已暂停。", "info")

    async def _run_loop(self):
        while self.enabled:
            try:
                await self._check_and_sign_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log(f"后台巡检轮询异常: {e}", level="error")

            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break

    async def tick(self):
        """单次巡检执行入口（供测试与即时触发）"""
        await self._check_and_sign_all()

    async def _check_and_sign_all(self):
        accounts = self.get_active_accounts()
        if not accounts:
            return

        now = datetime.datetime.now()

        for acc in accounts:
            username = acc.get("username", "")
            user_name = acc.get("name") or username
            client = acc.get("client")

            if not client or not client.is_authenticated():
                acc_obj = acc.get("account")
                if acc_obj and getattr(acc_obj, "password", None) and self.reconnect_account:
                    try:
                        await self.reconnect_account(acc_obj)
                    except Exception:
                        pass
                if not client or not client.is_authenticated():
                    continue

            try:
                classes = await client.get_today_classes()
            except Exception as e:
                acc_obj = acc.get("account")
                if acc_obj and getattr(acc_obj, "password", None) and self.reconnect_account:
                    try:
                        ok = await self.reconnect_account(acc_obj)
                        if ok:
                            classes = await client.get_today_classes()
                        else:
                            continue
                    except Exception:
                        continue
                else:
                    logger.warning(f"Failed to fetch classes for {username}: {e}")
                    continue

            acc_obj = acc.get("account")
            if acc_obj and classes is not None:
                acc_obj.last_classes = classes
                acc_obj.last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")

            for clazz in classes:
                sched_id = str(clazz.get("courseSchedId") or clazz.get("id") or clazz.get("courseId", ""))
                if not sched_id:
                    continue
                course_name = str(clazz.get("courseName", "课堂课程"))
                sign_status = clazz.get("signStatus", 0)
                begin_str = str(clazz.get("classBeginTime", "")).strip()

                key = (username, sched_id)

                if sign_status == 1:
                    self.signed_courses.add(key)
                    continue

                if key in self.signed_courses or key in self.failed_permanently:
                    continue

                # 解析课程开始时间
                course_start_dt = self._parse_course_time(begin_str, now)
                if not course_start_dt:
                    continue

                # 严格限制打卡窗口：仅在上课前 10 分钟 至 上课时刻
                window_start = course_start_dt - datetime.timedelta(minutes=10)
                window_end = course_start_dt

                # 还没到上课前 10 分钟区间
                if now < window_start:
                    continue

                # 已经超过上课时刻（严格不签开课后的时间）
                if now > window_end:
                    # 超过上课时间且未签到，标记跳过
                    if key not in self.signed_courses:
                        self.failed_permanently.add(key)
                        self.log(
                            f"《{course_name}》已过开课时刻 ({begin_str})，超出上课前10分钟签到区间，不再自动签到。",
                            level="warning",
                            username=username,
                            user_name=user_name,
                        )
                    continue

                # 当前处于上课前 10 分钟区间内！
                # 检查是否已为该课程生成计划触发时间
                if key not in self.planned_targets:
                    # 在当前时间与上课时刻之间随机分配一个时间点（预留至少20秒缓冲）
                    rem_seconds = (window_end - now).total_seconds()
                    if rem_seconds > 25:
                        offset_sec = random.uniform(5, rem_seconds - 15)
                    else:
                        offset_sec = 0

                    planned_dt = now + datetime.timedelta(seconds=offset_sec)
                    self.planned_targets[key] = planned_dt
                    self.log(
                        f"检测到《{course_name}》({begin_str}上课)，已随机规划打卡时间点为: {planned_dt.strftime('%H:%M:%S')}",
                        level="info",
                        username=username,
                        user_name=user_name,
                    )

                target_time = self.planned_targets[key]

                # 到了预定随机时间，开始打卡
                if now >= target_time:
                    attempt_num = self.retry_counts[key] + 1
                    self.log(
                        f"正在执行《{course_name}》课前自动签到 (第 {attempt_num} 次)...",
                        level="info",
                        username=username,
                        user_name=user_name,
                    )

                    try:
                        success, msg = await client.perform_signin(sched_id)
                    except Exception as e:
                        success, msg = False, str(e)

                    if success:
                        self.signed_courses.add(key)
                        self.log(
                            f"《{course_name}》课前随机签到成功！反馈: {msg}",
                            level="success",
                            username=username,
                            user_name=user_name,
                        )
                        # 步骤完成铁律：签到成功后立即向学校拉取最新课表，即刻刷新内存与界面状态
                        try:
                            refreshed_classes = await client.get_today_classes()
                            if acc_obj and refreshed_classes is not None:
                                acc_obj.last_classes = refreshed_classes
                                acc_obj.last_refresh_time = datetime.datetime.now().strftime("%H:%M:%S")
                        except Exception as ref_err:
                            logger.debug(f"Post-signin schedule refresh error for {username}: {ref_err}")
                    else:
                        self.retry_counts[key] = attempt_num
                        if attempt_num < 3:
                            # 失败后还有重试机会，计算重试时间（在上课前 20~40 秒内随机）
                            retry_gap = random.randint(20, 40)
                            next_retry_dt = now + datetime.timedelta(seconds=retry_gap)
                            # 如果超过了开课时间，则限制在开课前 5 秒
                            if next_retry_dt >= window_end:
                                next_retry_dt = max(now + datetime.timedelta(seconds=5), window_end - datetime.timedelta(seconds=5))

                            self.planned_targets[key] = next_retry_dt
                            self.log(
                                f"《{course_name}》第 {attempt_num} 次签到反馈: {msg}，将在 {next_retry_dt.strftime('%H:%M:%S')} 进行第 {attempt_num + 1} 次重试",
                                level="warning",
                                username=username,
                                user_name=user_name,
                            )
                        else:
                            self.failed_permanently.add(key)
                            self.log(
                                f"《{course_name}》连续 3 次签到尝试均未成功 (最后反馈: {msg})，已达到最大重试限制，停止自动打卡。",
                                level="error",
                                username=username,
                                user_name=user_name,
                            )

    def _parse_course_time(self, begin_str: str, now: datetime.datetime) -> Optional[datetime.datetime]:
        """解析如 '08:00' 或 '2026-09-10 08:00:00' 格式的时间字符串"""
        if not begin_str:
            return None
        try:
            # 完整格式 YYYY-MM-DD HH:MM[:SS]
            if " " in begin_str:
                date_part, time_part = begin_str.strip().split(" ", 1)
                d_parts = [int(p) for p in date_part.split("-")[:3]]
                t_parts = [int(p) for p in time_part.split(":")[:2]]
                return datetime.datetime(d_parts[0], d_parts[1], d_parts[2], t_parts[0], t_parts[1], 0)
            else:
                parts = [int(p) for p in begin_str.strip().split(":")[:2]]
                return datetime.datetime(now.year, now.month, now.day, parts[0], parts[1], 0)
        except Exception:
            return None
