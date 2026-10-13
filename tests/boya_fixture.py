"""Synthetic encrypted BYKC server, exercising the actual client and write budget."""
import json
import httpx
from core.boya_client import BoyaClient
from core.boya_crypto import BykcCrypto
from core.domain import now
from datetime import timedelta

class FixtureCrypto(BykcCrypto):
    def __init__(self):
        super().__init__(b"SYNTHETICKEY0001")

class FixtureBoyaClient(BoyaClient):
    def __init__(self, owner):
        super().__init__(token="fixture-boya-token")
        self.owner = owner
        self.operation_user = owner.username
        self.selected_ids = []
        self.signed_courses = []
        self.fail_on_select = False
        self.select_call_count = 0
        self.http_client.close()
        self.http_client = httpx.Client(transport=httpx.MockTransport(self._server),trust_env=False)
        self.semester_info = {"semesterStartDate": (now()-timedelta(days=60)).isoformat(), "semesterEndDate": (now()+timedelta(days=90)).isoformat(), "semesterName": "fixture-semester"}

    def _server(self, request):
        crypto = FixtureCrypto()
        payload = crypto.decrypt_response(request.content)
        action = request.url.path.rsplit("/",1)[-1]
        result = {"status":"0", "data":{}}
        if action == "getAllConfig":
            result["data"] = {"semester":[self.semester_info]}
        elif action == "queryChosenCourse":
            result["data"] = {"courseList":[{"id": c.get("chosenCourseId",10000+int(c.get("courseId") or c["id"])), "courseInfo":c} for c in self.owner.boya_selected_courses]}
        elif action == "queryStudentSemesterCourseByPage":
            pool = self.owner.boya_all_courses
            result["data"] = {"content":pool,"totalPages":1,"totalElements":len(pool),"last":True}
        elif action == "choseCourse":
            self.select_call_count += 1
            if self.fail_on_select:
                result = {"status":"rejected","errmsg":"synthetic full-state rejection"}
            else:
                cid = int(payload["courseId"])
                self.selected_ids.append(cid)
                chosen = dict(next(c for c in self.owner.boya_all_courses if int(c.get("courseId") or c["id"])==cid))
                chosen["courseId"] = cid
                self.owner.boya_selected_courses.append(chosen)
        elif action == "signCourseByUser":
            cid = int(payload["courseId"])
            self.signed_courses.append((cid,payload["signLat"],payload["signLng"],payload["signType"]))
            course = next(c for c in self.owner.boya_selected_courses if int(c.get("courseId") or c["id"])==cid)
            course["checkin"] = 5 if payload["signType"]==1 else 1
        else:
            result = {"status":"unsupported","errmsg":"synthetic endpoint not configured"}
        return httpx.Response(200,content=crypto.encrypt_plaintext(json.dumps(result,ensure_ascii=False).encode()))

def valid_course(cid, category="美育", current=None):
    current = current or now()
    fmt = lambda value: value.isoformat(sep=" ",timespec="seconds")
    return {"id":cid,"courseId":cid,"courseName":"synthetic-course","courseKind":category,"coursePosition":"北京", "courseCurrentCount":0,"courseMaxCount":20,"courseStartDate":fmt(current+timedelta(hours=2)),"courseEndDate":fmt(current+timedelta(hours=3)),"courseSelectStartDate":fmt(current-timedelta(minutes=10)),"courseSelectEndDate":fmt(current+timedelta(hours=1)),"checkin":0,"pass":None,"courseSignConfig":{"signPointList":[{"lat":39.9,"lng":116.3,"radius":30}],"signStartDate":fmt(current-timedelta(minutes=5)),"signEndDate":fmt(current+timedelta(minutes=10)),"signOutStartDate":fmt(current+timedelta(hours=2)),"signOutEndDate":fmt(current+timedelta(hours=4))}}
