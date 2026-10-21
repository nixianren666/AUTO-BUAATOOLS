"""Explicit isolated acceptance profile. All school traffic uses MockTransport."""
import json
import threading
import sys
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
from core.domain import now, CHINA

def seed(backend):
    def forbid_school_traffic(event, args):
        if event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple) and str(address[0]) not in ("127.0.0.1", "localhost", "::1"):
                raise PermissionError("Acceptance profile permits loopback traffic only")
    sys.addaudithook(forbid_school_traffic)
    from core.boya_crypto import BykcCrypto
    from core import boya_client
    crypto_local = threading.local()
    class FixtureCrypto(BykcCrypto):
        def __init__(self):
            super().__init__()
            crypto_local.current = self
    boya_client.BykcCrypto = FixtureCrypto
    current = now()
    def text(delta):
        return (current + delta).isoformat(sep=" ", timespec="seconds")
    def course(cid, category, checkin=0, passed=None):
        return {"id": cid, "courseId": cid, "chosenCourseId": cid+10000, "courseName": "模拟课程 " + str(cid), "courseKind": category, "coursePosition": "模拟北京教室", "teacherName": "模拟主讲人", "courseStartDate": text(timedelta(minutes=20)), "courseEndDate": text(timedelta(minutes=80)), "courseCurrentCount": 2, "courseMaxCount": 20, "courseSelectStartDate": text(timedelta(days=-1)), "courseSelectEndDate": text(timedelta(days=1)), "checkin": checkin, "pass": passed, "courseSignConfig": {"signPointList": [{"lat": 39.9, "lng": 116.3, "radius": 30}], "signStartDate": text(timedelta(minutes=-10)), "signEndDate": text(timedelta(minutes=10)), "signOutStartDate": text(timedelta(minutes=-5)), "signOutEndDate": text(timedelta(minutes=90))}}
    pool = [course(2001,"美育"),course(2002,"劳育",5),course(2003,"德育"),course(2004,"安全健康")]
    for index in (1, 2):
        username = "fixture-account-" + str(index)
        account = backend.AccountState(username, name="模拟账号 " + str(index), remember=False, auto_checkin=False)
        account.client.operation_user = username
        account.client.user_info = {"schoolid": username, "name": account.name}
        account.client.user_id = "fixture-user-" + str(index)
        account.client.session_id = "fixture-session-" + str(index)
        classes = [{"id": "100" + str(index), "courseSchedId": "100" + str(index), "courseName": "模拟常规课堂 " + str(index), "classBeginTime": text(timedelta(minutes=5)), "classEndTime": text(timedelta(minutes=65)), "signStatus": 0, "classroomName": "模拟教室", "teacherName": "模拟教师"}]
        chosen = [dict(pool[0]),dict(pool[1])]
        def regular(request, classes=classes):
            if "get_timestamp" in request.url.path:
                return httpx.Response(200,json={"STATUS":"0","timestamp":str(int(now().replace(tzinfo=CHINA).timestamp()*1000))})
            if request.method == "POST" and "stu_scan_sign" in request.url.path:
                classes[0]["signStatus"] = 1
                return httpx.Response(200,json={"STATUS":"0","result":{"stuSignStatus":1}})
            if "get_stu_course_sched" in request.url.path:
                return httpx.Response(200,json={"STATUS":"0","result":classes})
            return httpx.Response(403,json={"STATUS":"blocked"})
        account.client._client = httpx.AsyncClient(transport=httpx.MockTransport(regular),trust_env=False)
        def boya(request, chosen=chosen):
            crypto = crypto_local.current
            payload = crypto.decrypt_response(request.content)
            action = request.url.path.rsplit("/",1)[-1]
            data = {}
            if action == "getAllConfig":
                data = {"semester":[{"semesterStartDate":text(timedelta(days=-60)),"semesterEndDate":text(timedelta(days=90)),"semesterName":"模拟学期"}]}
            elif action == "queryChosenCourse":
                data = {"courseList":[{"id":c["chosenCourseId"],"courseInfo":c,"checkin":c["checkin"],"pass":c["pass"]} for c in chosen]}
            elif action == "queryStudentSemesterCourseByPage":
                data = {"content":pool,"totalPages":1,"totalElements":len(pool),"last":True}
            elif action == "queryStatisticByUserId":
                data = {"validCount":0,"totalCredit":0,"requiredCredit":6}
            elif action == "choseCourse":
                cid = int(payload["courseId"])
                item = next(c for c in pool if c["id"]==cid)
                if not any(c["id"]==cid for c in chosen):chosen.append(dict(item))
            elif action == "delChosenCourse":
                chosen[:] = [c for c in chosen if c["id"]!=int(payload["id"])]
            elif action == "signCourseByUser":
                cid = int(payload["courseId"])
                item = next(c for c in chosen if c["id"]==cid)
                item["checkin"] = 5 if payload["signType"]==1 else 1
            else:
                return httpx.Response(400,json={"error":"unsupported synthetic endpoint"})
            return httpx.Response(200,content=crypto.encrypt_plaintext(json.dumps({"status":"0","data":data},ensure_ascii=False).encode()))
        account.boya_client.http_client.close()
        account.boya_client.http_client = httpx.Client(transport=httpx.MockTransport(boya),trust_env=False)
        account.boya_client.token = "fixture-token-" + str(index)
        account.last_classes = classes
        account.boya_all_courses = pool
        account.boya_selected_courses = chosen
        account.boya_statistics = account.boya_client.query_statistics()
        backend.accounts[username] = account
    backend.active_username = "fixture-account-1"
    backend.config["disclaimer_accepted"] = True
    backend.config["disclaimer_commitment_version"] = backend.COMMITMENT_VERSION
