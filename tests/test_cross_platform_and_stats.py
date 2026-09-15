# -*- coding: utf-8 -*-
"""
跨平台平权、学期校历精准切片达标与全景体验自动化测试套件
覆盖：
1. 官方校历学期范围切片与防全学程历史累计污染测试
2. Windows 单实例命名互斥锁与托盘防多开逻辑
3. macOS Apple Silicon spec 配置、Launchd plist 及 Gatekeeper 修复脚本语法
4. Linux systemd 服务脚本与 Dockerfile 配置合法性
5. 全量选课池中现场考勤（线下核验）课程可选性与容量字段兼容测试
"""
import unittest
import os
import sys
import datetime
from typing import Dict, Any, List

# 将项目根目录加入 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from server.app import compute_semester_statistics, get_current_semester_range
from core.boya_scheduler import is_auto_select_candidate, course_matches_campus
from run import acquire_single_instance, release_single_instance, setup_tray


class TestCrossPlatformAndSemesterStats(unittest.TestCase):

    def test_semester_stats_scoping_excludes_historical_years(self):
        """测试本学期统计严格限制在校历时间内，完全隔离 2024/2025 等往届历史课程"""
        sso_stats = {
            "semesterInfo": {
                "semesterName": "2026-2027学年第一学期（秋季）",
                "semesterStartDate": "2026-08-31 00:00:00",
                "semesterEndDate": "2027-01-03 00:00:00"
            },
            "validCount": 1,
            # 模拟官方 SSO 全学程毕业考核累计树（德2 劳2 美3 安3，累计10门）
            "statistical": {
                "60|博雅课程": {
                    "德育类": {"completeAssessmentCount": 2},
                    "劳育类": {"completeAssessmentCount": 2},
                    "美育类": {"completeAssessmentCount": 3},
                    "安全健康类": {"completeAssessmentCount": 3},
                }
            }
        }

        # 用户的历史和本学期选课混合列表
        selected_courses = [
            # 往届 2024 年历史课（已考勤通过，应被彻底排除）
            {
                "id": 1001,
                "courseName": "2024德育讲座",
                "courseKind": "德育",
                "courseStartDate": "2024-10-15 14:00:00",
                "courseEndDate": "2024-10-15 16:00:00",
                "final_passed": True,
            },
            # 往届 2025 年春季课（已考勤通过，应被彻底排除）
            {
                "id": 1002,
                "courseName": "2025劳动实践",
                "courseKind": "劳育",
                "courseStartDate": "2025-04-10 09:00:00",
                "courseEndDate": "2025-04-10 11:00:00",
                "final_passed": True,
            },
            # 本学期 2026-09-13 通过的《北京一号》（应被正确计入美育）
            {
                "id": 1003,
                "courseName": "北京一号",
                "courseKind": "美育",
                "courseStartDate": "2026-09-13 14:00:00",
                "courseEndDate": "2026-09-13 16:00:00",
                "final_passed": True,
            },
            # 本学期 2026-09-16 的《心肺复苏CPR》（尚未考核通过，不计入通过）
            {
                "id": 1004,
                "courseName": "心肺复苏CPR与AED",
                "courseKind": "安全健康",
                "courseStartDate": "2026-09-16 19:00:00",
                "courseEndDate": "2026-09-16 21:00:00",
                "final_passed": False,
            },
        ]

        stats = compute_semester_statistics(selected_courses, sso_stats)

        # 严格断言：本学期达标数据绝不受全学程累计树污染
        self.assertEqual(stats["moral_completed"], 0, "德育本学期应为0门")
        self.assertEqual(stats["labor_completed"], 0, "劳育本学期应为0门")
        self.assertEqual(stats["art_completed"], 1, "美育本学期应为1门")
        self.assertEqual(stats["security_health_completed"], 0, "安全健康本学期应为0门")

        # 达标总数与完成率断言
        self.assertEqual(stats["semester_passed_total"], 1, "本学期已达标总数必须为1门")
        self.assertEqual(stats["semester_required_total"], 6, "本学期达标基准必须为6门")
        self.assertEqual(stats["semester_compliance_rate"], 17, "完成度必须为 17% (1/6)")
        self.assertEqual(stats["valid_count"], 1, "官方 validCount 必须与本学期一致")

        # 全学程历史统计应独立保存
        self.assertIn("all_time_stats", stats)
        self.assertEqual(stats["all_time_stats"]["total"], 10, "全学程历史累计修读总数必须保留为10门")

    def test_semester_date_fallback_beihang_calendar(self):
        """测试离线或缺少 semesterInfo 时，基于北航官方校历的基准推算"""
        start, end, name = get_current_semester_range()
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        self.assertTrue(start < end)
        self.assertIn("学年", name)

    def test_offline_checkin_course_can_be_selected(self):
        """严格安全性原则验证：默认严禁自动抢选现场刷卡考勤课程，防止因无法自动线上打卡导致旷课记过"""
        now = datetime.datetime(2026, 9, 14, 10, 0, 0)
        offline_course = {
            "id": 2001,
            "courseName": "正念沙龙——正念融入生活",
            "courseKind": "安全健康",
            "coursePosition": "学院路知行北楼313",
            "courseSelectStartDate": "2026-09-10 09:00:00",
            "courseSelectEndDate": "2026-09-20 18:00:00",
            "courseCurrentCount": 0,
            "courseMaxCount": 20,
            "signConfig": None,  # 无 GPS 线上定位打卡点，属于现场刷卡课
        }

        # 默认调用必须开启严格安全护栏（require_auto_sign 默认为 True），严禁代抢现场考勤课！
        can_default = is_auto_select_candidate(offline_course, now, campus="北京")
        self.assertFalse(can_default, "默认参数必须严正拦截现场刷卡考勤课，防止学生旷课违约")

        # 当明确限制线上自主打卡时
        can_auto_sign = is_auto_select_candidate(offline_course, now, campus="北京", require_auto_sign=True)
        self.assertFalse(can_auto_sign, "限制线上打卡时应正确判定为非定位签到课程")

        # 铁律：自动秒抢完全去除线下课开关，严禁代抢非线上自主打卡课程
        can_select = is_auto_select_candidate(offline_course, now, campus="北京", require_auto_sign=False)
        self.assertFalse(can_select, "无论参数如何，底座均坚决拦截非线上自主打卡课程，彻底消除旷课风险")

    def test_course_capacity_fields_compatibility(self):
        """测试北航接口中 courseCurrentCount / courseCurrentNum / currentCount 等多种名额字段兼容"""
        now = datetime.datetime(2026, 9, 14, 10, 0, 0)
        c1 = {
            "courseName": "容量测试课A",
            "courseSelectStartDate": "2026-09-10 09:00:00",
            "courseSelectEndDate": "2026-09-20 18:00:00",
            "courseCurrentNum": 50,
            "courseMaxNum": 50,
            "courseSignConfig": '{"signPointList":[{"lat":39.9,"lng":116.3}]}',
        }
        self.assertFalse(is_auto_select_candidate(c1, now, campus="北京"), "满额课程不可选")

        c2 = {
            "courseName": "容量测试课B",
            "courseSelectStartDate": "2026-09-10 09:00:00",
            "courseSelectEndDate": "2026-09-20 18:00:00",
            "currentCount": 10,
            "maxCount": 50,
            "courseSignConfig": '{"signPointList":[{"lat":39.9,"lng":116.3}]}',
        }
        self.assertTrue(is_auto_select_candidate(c2, now, campus="北京"), "有名额课程可选")

    def test_windows_single_instance_lock(self):
        """测试单实例互斥锁能够正常获取与安全释放"""
        lock = acquire_single_instance("BUAA_Signin_Test_Mutex")
        self.assertIsNotNone(lock, "首次获取单实例锁必须成功")
        release_single_instance(lock)

    def test_single_instance_mutual_exclusion(self):
        """测试单实例互斥机制：重复获取被拦截并能安全释放重用"""
        tag = "BUAA_Signin_Mutual_Exclusion_Test"
        first = acquire_single_instance(tag)
        self.assertTrue(first, "首次获取锁必须成功")
        second = acquire_single_instance(tag)
        self.assertFalse(second, "重复获取必须被互斥锁拦截")
        release_single_instance()
        third = acquire_single_instance(tag)
        self.assertTrue(third, "释放后重新获取必须成功")
        release_single_instance()

    def test_tray_menu_structure_has_restore_and_exit(self):
        """测试托盘菜单配置：必须包含【显示主界面】与【退出应用】，杜绝 macOS 死锁"""
        import run
        if run.pystray is not None:
            tray = run.setup_tray(run_now=False)
            if tray and hasattr(tray, "menu") and tray.menu is not None:
                item_texts = [str(item.text) for item in tray.menu.items]
                self.assertIn("显示主界面", item_texts, "托盘必须包含恢复窗口菜单项")
                self.assertIn("退出应用", item_texts, "托盘必须包含退出应用菜单项")

    def test_macos_spec_and_scripts_integrity(self):
        """跨平台检查：macOS 打包 spec 与 Gatekeeper 修复脚本语法与完整性"""
        mac_spec_path = os.path.join(BASE_DIR, "BUAA-Signin-mac.spec")
        self.assertTrue(os.path.exists(mac_spec_path), "BUAA-Signin-mac.spec 必须存在")
        with open(mac_spec_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("BUNDLE", content, "macOS spec 必须包含 BUNDLE 打包配置")
            self.assertIn("tray_icon.png", content)

        gatekeeper_script = os.path.join(BASE_DIR, "scripts", "fix_macos_gatekeeper.sh")
        self.assertTrue(os.path.exists(gatekeeper_script), "fix_macos_gatekeeper.sh 必须存在")
        with open(gatekeeper_script, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("xattr -rd com.apple.quarantine", content, "Gatekeeper 修复脚本必须包含隔离属性清除指令")

    def test_linux_service_and_docker_integrity(self):
        """跨平台检查：Linux systemd 服务脚本与 Dockerfile 配置合法性"""
        systemd_script = os.path.join(BASE_DIR, "scripts", "install_linux_service.sh")
        self.assertTrue(os.path.exists(systemd_script), "install_linux_service.sh 必须存在")
        with open(systemd_script, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("systemd", content)
            self.assertIn("Restart=always", content)

        docker_file = os.path.join(BASE_DIR, "Dockerfile")
        self.assertTrue(os.path.exists(docker_file), "Dockerfile 必须存在")

    def test_courses_time_overlap_detection(self):
        """测试博雅课程防选错：精准判断上课时间区间重叠冲突"""
        from core.boya_scheduler import courses_time_overlap

        # 1. 重叠情况：14:00-16:00 与 15:00-17:00
        c1 = {"courseStartDate": "2026-09-14", "courseStartTime": "14:00:00", "courseEndDate": "2026-09-14", "courseEndTime": "16:00:00"}
        c2 = {"courseStartDate": "2026-09-14", "courseStartTime": "15:00:00", "courseEndDate": "2026-09-14", "courseEndTime": "17:00:00"}
        self.assertTrue(courses_time_overlap(c1, c2), "有重叠区间的课程应判定为冲突")

        # 2. 完全包含情况：13:00-17:00 包含 14:00-15:00
        c3 = {"courseStartDate": "2026-09-14", "courseStartTime": "13:00:00", "courseEndDate": "2026-09-14", "courseEndTime": "17:00:00"}
        c4 = {"courseStartDate": "2026-09-14", "courseStartTime": "14:00:00", "courseEndDate": "2026-09-14", "courseEndTime": "15:00:00"}
        self.assertTrue(courses_time_overlap(c3, c4), "包含区间的课程应判定为冲突")

        # 3. 相邻不重叠情况：14:00-16:00 与 16:00-18:00
        c5 = {"courseStartDate": "2026-09-14", "courseStartTime": "16:00:00", "courseEndDate": "2026-09-14", "courseEndTime": "18:00:00"}
        self.assertFalse(courses_time_overlap(c1, c5), "紧邻起止但无交集的课程不应判定为冲突")

        # 4. 不同日期情况
        c6 = {"courseStartDate": "2026-09-15", "courseStartTime": "14:00:00", "courseEndDate": "2026-09-15", "courseEndTime": "16:00:00"}
        self.assertFalse(courses_time_overlap(c1, c6), "不同日期的课程不应判定为冲突")

    def test_category_demands_and_priority_sorting(self):
        """测试素养板块达标缺口计算与候选课程优先级权重排序"""
        from core.boya_scheduler import get_user_category_demands, calculate_candidate_priority

        # 假设学生当前美育已满 1 门，但德育 0/2，劳育 0/2，安全 0/1
        selected = [
            {"courseKind": "美育", "courseStartDate": "2026-09-10 14:00:00", "final_passed": True}
        ]
        demands = get_user_category_demands(selected)
        self.assertEqual(demands["美育"]["remaining"], 0, "美育已满额，缺口应为0")
        self.assertEqual(demands["德育"]["remaining"], 2, "德育未修，缺口应为2")
        self.assertEqual(demands["劳育"]["remaining"], 2, "劳育未修，缺口应为2")
        self.assertEqual(demands["安全健康"]["remaining"], 1, "安全健康未修，缺口应为1")

        moral_course = {"courseName": "德育讲座", "courseKind": "德育"}
        art_course = {"courseName": "美学赏析", "courseKind": "美育"}
        self.assertGreater(
            calculate_candidate_priority(moral_course, demands),
            calculate_candidate_priority(art_course, demands),
            "未达标板块课程优先级必须高于已达标板块课程"
        )

    def test_candidate_safety_guards(self):
        """测试不选选不了的课：取消、停开、已结束课程过滤"""
        now = datetime.datetime(2026, 9, 14, 10, 0, 0)
        c_cancelled = {
            "courseName": "已停开课程",
            "courseStatus": "已停开",
            "courseSelectStartDate": "2026-09-10 09:00:00",
            "courseSelectEndDate": "2026-09-20 18:00:00",
            "courseCurrentCount": 0,
            "courseMaxCount": 50,
        }
        self.assertFalse(is_auto_select_candidate(c_cancelled, now), "已停开课程不可选")

        c_past = {
            "courseName": "昨天已上完的课",
            "courseSelectStartDate": "2026-09-10 09:00:00",
            "courseSelectEndDate": "2026-09-20 18:00:00",
            "courseStartDate": "2026-09-13",
            "courseEndDate": "2026-09-13",
            "courseEndTime": "18:00:00",
            "courseCurrentCount": 0,
            "courseMaxCount": 50,
        }
        self.assertFalse(is_auto_select_candidate(c_past, now), "已过上课时间的课程不可选")

    def test_app_icon_assets_integrity(self):
        """全平台图标与静态资源文件完整性检查"""
        required_assets = [
            os.path.join(BASE_DIR, "app_icon.ico"),
            os.path.join(BASE_DIR, "app_icon.icns"),
            os.path.join(BASE_DIR, "tray_icon.png"),
            os.path.join(BASE_DIR, "server", "static", "favicon.ico"),
            os.path.join(BASE_DIR, "server", "static", "images", "app_logo.png"),
        ]
        for path in required_assets:
            self.assertTrue(os.path.exists(path), f"资源文件必须存在: {path}")
            self.assertGreater(os.path.getsize(path), 100, f"资源文件不可为空: {path}")


if __name__ == "__main__":
    unittest.main()

