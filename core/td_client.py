"""Bounded campus TD transport. No CAS credentials, telemetry or count-query writes.

Protocol reference: AutoTD 0.1.15 (MIT, see THIRD_PARTY_NOTICES.md).
School acceptance and photo review are distinct from transport acknowledgement.
"""
import json
import re
import socket
import struct
import time

# Only the supported affirmative reply grammar may advance a phase. Unknown or
# contradictory prose is not an acknowledgement, even if it embeds “成功”.
NEGATIVE_REPLY = re.compile(r"未|不|失败|无效|拒绝|错误|超过|非法|重复|禁止|否|待核验|未知")
SUCCESS_REPLY = re.compile(
    r"\s*(?:刷卡|打卡|签到|签退)成功[!！。.]*"
    r"(?:[\s,，;；]*本学期锻炼次数\s*[:：]\s*([0-9]{1,4})\s*次?[!！。.]*)?\s*"
)

# Fixed campus devices published by AutoTD; never accept an arbitrary target URL.
DEVICES = {
    "学院路": (("2", "20211025001"), ("3", "20220301004"), ("4", "20230417001"),
               ("5", "20210421003"), ("6", "20210420002"), ("7", "20220301003")),
    "沙河": (("8", "20210511001"), ("9", "20210511002"), ("10", "20210511003"),
             ("11", "20220218001"), ("12", "20220218002"), ("13", "20220218003")),
}


class TDUncertain(RuntimeError):
    """No replay: the peer may already have accepted the request."""


class TDRejected(RuntimeError):
    """An explicit negative reply; a new round still consumes the daily budget."""


class TDClient:
    def __init__(self, socket_factory=socket.socket):
        self.socket_factory = socket_factory

    def request(self, kind, data, guard):
        deadline = time.monotonic() + 10
        def remaining(sock):
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError()
            sock.settimeout(seconds)
        def receive(sock, size):
            result = bytearray()
            while len(result) < size:
                remaining(sock)
                chunk = sock.recv(size - len(result))
                if not chunk:
                    raise ConnectionError()
                result.extend(chunk)
            return bytes(result)
        try:
            if not guard():
                raise TDUncertain("账号已暂停或允许时间已结束，未建立连接")
            with self.socket_factory(socket.AF_INET, socket.SOCK_STREAM) as sock:
                remaining(sock)
                sock.connect(("10.212.28.38", 8888))
                if not guard():
                    raise TDUncertain("账号已暂停或配对窗口已结束，未继续发送")
                remaining(sock)
                sock.sendall(struct.pack(">lB", len(data), kind) + data)
                size, code = struct.unpack(">lB", receive(sock, 5))
                if code != kind or not 1 <= size <= 65536:
                    raise ValueError()
                result = json.loads(receive(sock, size).decode("utf-8"))
                if not isinstance(result, dict):
                    raise ValueError()
                return result
        except TDUncertain:
            raise
        except Exception as exc:
            # Do not expose peer text, identifiers or socket internals to the UI.
            raise TDUncertain("连接或响应未确认；已停止重发，请核对官方记录") from exc

    def check(self, username, device, stamp, guard):
        if not re.fullmatch(r"[0-9]{5,16}", username):
            raise TDRejected("当前账号学号格式不支持 TD")
        payload = {"cardno": format(int(username), "X"), "userno": username,
                   "timestamp": str(int(stamp * 1000)), "type": 1,
                   "eventno": "802", "ln": device[0], "sn": device[1], "schoolno": "10006"}
        result = self.request(80, json.dumps(payload).encode(), guard)
        message = result.get("srvresp")
        if result.get("status") != "success" or not isinstance(message, str):
            raise TDUncertain("服务器未返回可确认的打卡结果")
        if NEGATIVE_REPLY.search(message):
            raise TDRejected("学校明确未接受本次请求；已暂停，请核对记录和规则")
        acknowledged = SUCCESS_REPLY.fullmatch(message)
        if not acknowledged:
            raise TDUncertain("学校响应含义未识别，不能当作成功")
        return int(acknowledged[1]) if acknowledged[1] is not None else None

    def photo(self, device, stamp, jpeg, guard):
        data = f"{device[1]}_{int(stamp * 1000)}".encode() + jpeg
        result = self.request(100, data, guard)
        message = result.get('srvresp')
        if (result.get("status") != "success"
            or (message is not None and not isinstance(message, str))
            or (isinstance(message, str) and NEGATIVE_REPLY.search(message))):
            raise TDUncertain("照片接收未确认，不能重发打卡或标记完成")
