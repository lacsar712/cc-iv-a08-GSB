import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.response import Response
from litestar.status_codes import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from passlib.context import CryptContext

from db import SCHEMA, connect
from rules import judge

SECRET = os.environ.get("JWT_SECRET", "pvivscan-dev-secret")
GOLDEN_WINDOW = timedelta(minutes=10)
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "scanner": {"role": "writer", "password_hash": pwd.hash("scan123456")},
    "watcher": {"role": "reader", "password_hash": pwd.hash("watch123456")},
}


def dump(row):
    out = dict(row)
    for key, val in list(out.items()):
        if hasattr(val, "isoformat"):
            out[key] = val.isoformat()
    return out


def seed():
    with connect() as conn:
        conn.execute(SCHEMA)
        # 逆变器启动时刻：整窗只钉这一次，进程重启也不重开黄金窗。
        conn.execute(
            """INSERT INTO app_meta (meta_key, meta_value)
               VALUES ('inverter_booted_at', %s)
               ON CONFLICT (meta_key) DO NOTHING""",
            (datetime.now(timezone.utc),),
        )
        n = conn.execute("SELECT COUNT(*) AS n FROM iv_scans").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            samples = [
                ("阵列A-串03", 41.2, 9.1, 0.78, "合格"),
                ("阵列B-串11", 38.0, 8.4, 0.61, "衰减"),
            ]
            for code, voc, isc, ff, expect in samples:
                verdict, reason = judge(ff)
                assert verdict == expect
                conn.execute(
                    """INSERT INTO iv_scans
                       (string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                        created_by, created_at, processed_at)
                       VALUES (%s,%s,%s,%s,'done',%s,%s,'scanner',%s,%s)""",
                    (code, voc, isc, ff, verdict, reason, now, now),
                )
        conn.commit()


seed()


def user_from(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(auth.split(" ", 1)[1].strip(), SECRET, algorithms=["HS256"])
    except JWTError:
        return None
    sub = payload.get("sub")
    if sub not in USERS:
        return None
    return {"username": sub, "role": payload.get("role")}


def need_login(request: Request):
    user = user_from(request)
    if user is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未登录")
    return user


def need_writer(request: Request):
    user = need_login(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅扫描员可提交IV扫描")
    return user


@get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "pv-string-iv-scan"}


@post("/api/auth/login")
async def login(request: Request) -> dict:
    data = await request.json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = USERS.get(username)
    if not user or not pwd.verify(password, user["password_hash"]):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp}, SECRET, algorithm="HS256"
    )
    return {"access_token": token, "username": username, "role": user["role"]}


@get("/api/logs")
async def list_logs(request: Request) -> list:
    need_login(request)
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                      created_by, created_at, processed_at
               FROM iv_scans ORDER BY id DESC"""
        ).fetchall()
        return [dump(r) for r in rows]


@post("/api/logs", status_code=201)
async def create_log(request: Request) -> dict:
    user = need_writer(request)
    data = await request.json()
    code = (data.get("string_code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="组串编号不能为空")
    try:
        voc = float(data.get("voc_v"))
        isc = float(data.get("isc_a"))
        ff = float(data.get("fill_factor"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="电压电流与填充因子必须是数字")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO iv_scans
               (string_code, voc_v, isc_a, fill_factor, status, created_by, created_at)
               VALUES (%s,%s,%s,%s,'pending',%s,%s)
               RETURNING id, string_code, voc_v, isc_a, fill_factor, status, verdict, reason,
                         created_by, created_at, processed_at""",
            (code, voc, isc, ff, user["username"], now),
        ).fetchone()
        conn.commit()
        return dump(row)


def _aware(val):
    return val if val.tzinfo else val.replace(tzinfo=timezone.utc)


@get("/api/golden/state")
async def golden_state(request: Request) -> dict:
    need_login(request)
    now = datetime.now(timezone.utc)
    with connect() as conn:
        booted = _aware(
            conn.execute(
                "SELECT meta_value FROM app_meta WHERE meta_key = 'inverter_booted_at'"
            ).fetchone()["meta_value"]
        )
        closes_at = booted + GOLDEN_WINDOW
        in_flight = conn.execute(
            """SELECT id, string_code, voc_v, isc_a, fill_factor, created_by, created_at
               FROM iv_scans WHERE status = 'pending' ORDER BY id"""
        ).fetchall()
        albums = conn.execute(
            """SELECT id, window_name, sealed_by, sealed_at, window_opened_at, point_count
               FROM golden_albums ORDER BY id DESC"""
        ).fetchall()
        return {
            "window_opened_at": booted.isoformat(),
            "window_closes_at": closes_at.isoformat(),
            "server_now": now.isoformat(),
            "in_window": now < closes_at,
            "in_flight": [dump(r) for r in in_flight],
            "albums": [dump(r) for r in albums],
        }


@get("/api/golden/albums/{album_id:int}")
async def get_golden_album(request: Request, album_id: int) -> dict:
    need_login(request)
    with connect() as conn:
        album = conn.execute(
            "SELECT * FROM golden_albums WHERE id = %s", (album_id,)
        ).fetchone()
        if album is None:
            raise HTTPException(status_code=404, detail="曲线册不存在")
        points = conn.execute(
            """SELECT id, scan_id, string_code, voc_v, isc_a, fill_factor,
                      reading_created_at, captured_at
               FROM golden_album_points WHERE album_id = %s ORDER BY id""",
            (album_id,),
        ).fetchall()
        out = dump(album)
        out["points"] = [dump(p) for p in points]
        return out


@post("/api/golden/seal", status_code=201)
async def seal_golden_album(request: Request) -> dict:
    user = need_login(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅扫描员可封存黄金窗曲线册")
    data = await request.json()
    name = (data.get("window_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="窗名不能为空")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        try:
            with conn.transaction():
                booted = _aware(
                    conn.execute(
                        "SELECT meta_value FROM app_meta WHERE meta_key = 'inverter_booted_at'"
                    ).fetchone()["meta_value"]
                )
                if now >= booted + GOLDEN_WINDOW:
                    raise HTTPException(status_code=400, detail="黄金窗已关闭，无法封存")
                # 行锁与工人的办结互斥：封存瞬间不会有在途单被刮走或漏抄。
                rows = conn.execute(
                    """SELECT id, string_code, voc_v, isc_a, fill_factor, created_at
                       FROM iv_scans WHERE status = 'pending' ORDER BY id
                       FOR UPDATE"""
                ).fetchall()
                if not rows:
                    raise HTTPException(status_code=400, detail="此刻没有在途读数，无法封存曲线册")
                album = conn.execute(
                    """INSERT INTO golden_albums
                       (window_name, sealed_by, sealed_at, window_opened_at, point_count)
                       VALUES (%s,%s,%s,%s,%s) RETURNING *""",
                    (name, user["username"], now, booted, len(rows)),
                ).fetchone()
                with conn.cursor() as cur:
                    cur.executemany(
                        """INSERT INTO golden_album_points
                           (album_id, scan_id, string_code, voc_v, isc_a, fill_factor,
                            reading_created_at, captured_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        [
                            (
                                album["id"], r["id"], r["string_code"], r["voc_v"],
                                r["isc_a"], r["fill_factor"], r["created_at"], now,
                            )
                            for r in rows
                        ],
                    )
        except HTTPException:
            raise
        conn.commit()
        out = dump(album)
        out["points"] = [
            {
                "scan_id": r["id"], "string_code": r["string_code"],
                "voc_v": r["voc_v"], "isc_a": r["isc_a"],
                "fill_factor": r["fill_factor"],
                "reading_created_at": r["created_at"].isoformat()
                if hasattr(r["created_at"], "isoformat") else r["created_at"],
                "captured_at": now.isoformat(),
            }
            for r in rows
        ]
        return out


app = Litestar(route_handlers=[
    health, login, list_logs, create_log,
    golden_state, get_golden_album, seal_golden_album,
])
