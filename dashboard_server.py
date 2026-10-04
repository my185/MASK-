# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Professional Web Dashboard & Real-Time EXP Tracker
External HTML Template: TEMPLETE/AFT.HTML
"""

import asyncio
import json
import os
import time
import hashlib
from typing import Dict, List, Any, Optional
from aiohttp import web

# Account level eta ba tar beshi hole BR theke automatic Lone Wolf. 0 dile bondho.
try:
    AUTO_LW_LEVEL = int(os.environ.get("AUTO_LW_LEVEL", "3"))
except Exception:
    AUTO_LW_LEVEL = 3

# ==================== BASE DIRECTORY ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
import glob as _glob

def get_all_account_files_dashboard():
    files = sorted(_glob.glob(os.path.join(BASE_DIR, "accounts*.json")))
    if not files:
        files = [os.path.join(BASE_DIR, "accounts.json")]
    return files

ACCOUNTS_FILE_PATH = os.path.join(BASE_DIR, "accounts.json")

# ==================== DASHBOARD HTML FILE ====================
DASHBOARD_HTML_FILE = os.path.join(BASE_DIR, "TEMPLETE", "AFT.HTML")

# ==================== LOGIN CREDENTIALS ====================
DASH_USER = os.environ.get("DASH_USER", "BRX")
DASH_PASS = os.environ.get("DASH_PASS", "BRX9X")


# ==================== BOT STATE ====================
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self.deleted_uids: set = set()
        self.match_types: Dict[str, str] = {}
        self.global_running: bool = True
        self.exp_limit: int = 45000
        self.auto_delete_queue: set = set()
        self.paused_uids: set = set()

    def is_paused(self, uid: str) -> bool:
        return str(uid) in self.paused_uids

    def pause_account(self, uid: str):
        uid_str = str(uid)
        self.paused_uids.add(uid_str)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = "PAUSED"
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
        self.log(f"[PAUSE] UID {uid_str} paused", "warning", uid_str)

    def resume_account(self, uid: str):
        uid_str = str(uid)
        self.paused_uids.discard(uid_str)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = "ONLINE"
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
        self.log(f"[RESUME] UID {uid_str} resumed", "success", uid_str)

    def set_match_type(self, uid: str, match_type: str):
        uid_str = str(uid)
        allowed = {"BR", "LONE_WOLF"}
        if match_type not in allowed:
            match_type = "LONE_WOLF"
        self.match_types[uid_str] = match_type
        if uid_str in self.accounts:
            self.accounts[uid_str]["match_type"] = match_type
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def get_match_type(self, uid: str) -> str:
        uid_str = str(uid)
        lvl = self.get_account_level(uid_str)
        if lvl == 2:
            if self.match_types.get(uid_str) != "BR":
                self.match_types[uid_str] = "BR"
                if uid_str in self.accounts:
                    self.accounts[uid_str]["match_type"] = "BR"
                try:
                    self.log(f"[AUTO] UID {uid_str} Level {lvl} → Battle Royale (BR)", "success", uid_str)
                except Exception:
                    pass
            return "BR"
        mt = self.match_types.get(uid_str, "LONE_WOLF")
        if mt == "BR" and AUTO_LW_LEVEL > 0 and lvl >= AUTO_LW_LEVEL:
            self.set_match_type(uid_str, "LONE_WOLF")
            try:
                self.log(f"[AUTO] UID {uid_str} Level {lvl} >= {AUTO_LW_LEVEL} → Lone Wolf", "success", uid_str)
            except Exception:
                pass
            return "LONE_WOLF"
        return mt

    async def _async_auto_delete(self, uid_str: str):
        try:
            short_key = uid_str.replace("tok_", "")[:10]
            self.accounts.pop(uid_str, None)
            self.recalc_totals()
            for accounts_file in get_all_account_files_dashboard():
                if not os.path.exists(accounts_file):
                    continue
                try:
                    with open(accounts_file, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    if not isinstance(existing, list):
                        continue
                    new_list = [
                        acc for acc in existing
                        if str(acc.get("uid", "")).strip() != uid_str
                        and str(acc.get("token", ""))[:10] != short_key
                    ]
                    if len(new_list) < len(existing):
                        tmp_file = accounts_file + ".tmp"
                        with open(tmp_file, "w", encoding="utf-8") as f:
                            json.dump(new_list, f, indent=2, ensure_ascii=False)
                        os.replace(tmp_file, accounts_file)
                except Exception:
                    pass
            for worker_key in [uid_str, short_key]:
                if worker_key in self.account_workers:
                    task = self.account_workers.pop(worker_key)
                    task.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                        pass
            self.auto_delete_queue.discard(uid_str)
            self.log(f"[AUTO-DELETE] UID {uid_str} → EXP লিমিট পূর্ণ। আইডি মুছে ফেলা হয়েছে।", "warning", uid_str)
        except Exception as e:
            self.log(f"[AUTO-DELETE ERROR] UID {uid_str}: {e}", "error", uid_str)

    def get_account_level(self, uid: str) -> int:
        uid_str = str(uid)
        if uid_str in self.accounts:
            return int(self.accounts[uid_str].get("level", 1) or 1)
        return 1

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": uid
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int, likes: int = 0):
        uid_str = str(uid)
        if uid_str in self.deleted_uids:
            return
        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "BD",
                "level": level or 1,
                "initial_exp": exp,
                "current_exp": exp,
                "gained_exp": 0,
                "likes": likes or 0,
                "status": "ONLINE",
                "matches_played": 0,
                "active_matches": 0,
                "last_match_time": None,
                "last_updated": time.strftime("%H:%M:%S"),
                "match_type": self.match_types.get(uid_str, "LONE_WOLF"),
                "started_at": time.time(),
            }
        else:
            acc = self.accounts[uid_str]
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level:
                acc["level"] = level
                self.get_match_type(uid_str)
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["likes"] = likes
            acc["status"] = "ONLINE"
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.deleted_uids:
            return
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            acc["current_exp"] = current_exp
            if level is not None and level > 0:
                acc["level"] = level
                self.get_match_type(uid_str)
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])
            acc["last_updated"] = time.strftime("%H:%M:%S")
            diff = current_exp - old_exp
            if diff > 0:
                self.log(f"Account {acc['nickname']} ({uid_str}) gained +{diff} EXP! Total: +{acc['gained_exp']}", "success", uid_str)
            self.recalc_totals()

            if self.exp_limit > 0 and acc["gained_exp"] >= self.exp_limit and uid_str not in self.auto_delete_queue:
                self.auto_delete_queue.add(uid_str)
                nickname = acc.get("nickname", uid_str)
                self.log(
                    f"[AUTO-DELETE] {nickname} ({uid_str}) → {acc['gained_exp']} EXP অর্জন করেছে (লিমিট: {self.exp_limit})। অটো ডিলিট...",
                    "warning", uid_str
                )
                self.deleted_uids.add(uid_str)
                self.match_types.pop(uid_str, None)
                try:
                    asyncio.get_event_loop().create_task(
                        self._async_auto_delete(uid_str)
                    )
                except RuntimeError:
                    pass

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.deleted_uids:
            return
        if uid_str in self.accounts:
            if uid_str in self.paused_uids and status not in ("PAUSED", "OFFLINE", "ERROR"):
                return
            self.accounts[uid_str]["status"] = status
            if status in ("ONLINE", "IN_MATCH", "SEARCHING"):
                self.accounts[uid_str].pop("last_error", None)
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def set_error(self, uid: str, message: str):
        uid_str = str(uid)
        if uid_str in self.deleted_uids:
            return
        if uid_str in self.accounts:
            self.accounts[uid_str]["last_error"] = f"{time.strftime('%H:%M:%S')} - {message}"[:300]

    def set_info(self, uid: str, message: str):
        uid_str = str(uid)
        if uid_str in self.deleted_uids:
            return
        if uid_str in self.accounts:
            self.accounts[uid_str]["last_info"] = f"{time.strftime('%H:%M:%S')} - {message}"[:300]

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            self.log(f"Account {self.accounts[uid_str]['nickname']} finished Match #{self.accounts[uid_str]['matches_played']}", "info", uid_str)

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())


bot_state = BotState()


# ==================== HTTP HANDLERS ====================

async def handle_index(request: web.Request) -> web.Response:
    try:
        with open(DASHBOARD_HTML_FILE, "r", encoding="utf-8") as f:
            html = f.read()
        return web.Response(text=html, content_type="text/html", charset="utf-8")
    except FileNotFoundError:
        return web.Response(
            text=(
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<title>Template Not Found</title></head>"
                "<body style='font-family:sans-serif;background:#000;color:#fff;padding:40px;'>"
                "<h1 style='color:#ff1f3d;'>⚠ TEMPLETE/AFT.HTML not found</h1>"
                "<p style='color:#888;line-height:1.6;'>"
                "Make sure <code>TEMPLETE/AFT.HTML</code> exists next to <code>dashboard_server.py</code>"
                "</p><p style='color:#555;'>Expected path: <code>" + DASHBOARD_HTML_FILE + "</code></p>"
                "</body></html>"
            ),
            content_type="text/html",
            status=404
        )


async def handle_login(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", "")).strip()
        if username == DASH_USER and password == DASH_PASS:
            token = hashlib.sha256(f"{username}:{password}:{time.time()}".encode()).hexdigest()
            bot_state.log(f"[AUTH] Login successful: {username}", "success")
            return web.json_response({"status": "ok", "token": token})
        bot_state.log(f"[AUTH] Failed login attempt: {username}", "warning")
        return web.json_response({"status": "error", "error": "Invalid username or password"}, status=401)
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = list(bot_state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_gained_exp": bot_state.total_gained_exp,
        "accounts": accounts_data,
        "logs": bot_state.logs[-60:],
        "uptime": int(time.time() - bot_state.start_time),
        "global_running": bot_state.global_running,
        "exp_limit": bot_state.exp_limit
    })


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        accounts_file = ACCOUNTS_FILE_PATH
        existing = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password required"})
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            existing.append({"uid": uid, "password": pwd})
            bot_state.deleted_uids.discard(uid)
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token required"})
            existing = [acc for acc in existing if acc.get("token") != token]
            existing.append({"token": token})
            bot_state.deleted_uids.discard(token[:10])
            bot_state.deleted_uids.discard(f"tok_{token[:10]}")
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        bot_state.log(f"New account added: {data.get('uid') or 'Token'}", "success")

        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "uid missing"})
        short_key = uid.replace("tok_", "")[:10]

        for accounts_file in get_all_account_files_dashboard():
            if not os.path.exists(accounts_file):
                continue
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if not isinstance(existing, list):
                    continue
                new_list = [
                    acc for acc in existing
                    if str(acc.get("uid", "")).strip() != uid
                    and str(acc.get("token", ""))[:10] != short_key
                ]
                if len(new_list) < len(existing):
                    tmp_file = accounts_file + ".tmp"
                    with open(tmp_file, "w", encoding="utf-8") as f:
                        json.dump(new_list, f, indent=2, ensure_ascii=False)
                    os.replace(tmp_file, accounts_file)
            except Exception:
                pass

        bot_state.deleted_uids.add(uid)
        bot_state.deleted_uids.add(short_key)
        bot_state.paused_uids.discard(uid)

        if uid in bot_state.accounts:
            del bot_state.accounts[uid]
            bot_state.recalc_totals()

        for worker_key in [uid, short_key]:
            if worker_key in bot_state.account_workers:
                task = bot_state.account_workers.pop(worker_key)
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass

        bot_state.log(f"Account {uid} deleted.", "warning", uid)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_reload_accounts(request: web.Request) -> web.Response:
    try:
        cleared = len(bot_state.deleted_uids)
        bot_state.deleted_uids.clear()
        added = 0
        if "on_reload_accounts" in bot_state.refresh_callbacks:
            added = await bot_state.refresh_callbacks["on_reload_accounts"]()
        msg = f"Reload complete: {cleared} blacklisted UIDs cleared, {added} new account(s) started."
        bot_state.log(msg, "success")
        return web.json_response({"status": "ok", "message": msg, "cleared": cleared, "started": added})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


# ═══════════════════════════════════════════════════════════════
# ✅ UPLOAD ACCOUNTS — bulk JSON upload from user
# Accepts: [{uid, password, name?, region?, token?, access_token?}, ...]
# ═══════════════════════════════════════════════════════════════
async def handle_upload_accounts(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        accounts_list = data.get("accounts", [])
        if not isinstance(accounts_list, list):
            return web.json_response(
                {"status": "error", "error": "accounts must be a list"},
                status=400
            )

        accounts_file = ACCOUNTS_FILE_PATH

        # ---- Load existing accounts.json ----
        existing: List[Dict[str, Any]] = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    existing = loaded
            except Exception:
                existing = []

        existing_uids = {
            str(acc.get("uid", "")).strip()
            for acc in existing
            if acc.get("uid")
        }
        existing_tokens = {
            str(acc.get("token", "")).strip()
            for acc in existing
            if acc.get("token")
        }

        added = 0
        skipped = 0
        added_uids: List[str] = []

        for acc in accounts_list:
            if not isinstance(acc, dict):
                skipped += 1
                continue

            uid = str(acc.get("uid", "") or "").strip()
            password = str(acc.get("password", "") or "").strip()
            token = str(acc.get("token", "") or acc.get("access_token", "") or "").strip()

            # Case 1: uid + password
            if uid and password:
                if uid in existing_uids:
                    skipped += 1
                    continue
                entry: Dict[str, Any] = {"uid": uid, "password": password}
                region = str(acc.get("region", "") or "").strip()
                if region:
                    entry["region"] = region
                name = str(acc.get("name", "") or acc.get("nickname", "") or "").strip()
                if name:
                    entry["name"] = name
                existing.append(entry)
                existing_uids.add(uid)
                bot_state.deleted_uids.discard(uid)
                added_uids.append(uid)
                added += 1
                continue

            # Case 2: token only
            if token and not password:
                if token in existing_tokens:
                    skipped += 1
                    continue
                entry = {"token": token}
                region = str(acc.get("region", "") or "").strip()
                if region:
                    entry["region"] = region
                existing.append(entry)
                existing_tokens.add(token)
                short_key = token[:10]
                bot_state.deleted_uids.discard(short_key)
                bot_state.deleted_uids.discard(f"tok_{short_key}")
                added_uids.append(short_key)
                added += 1
                continue

            # Missing credentials
            skipped += 1

        # ---- Save ----
        if added > 0:
            tmp_file = accounts_file + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, accounts_file)

            # Trigger bot refresh so new accounts start immediately
            if "on_reload_accounts" in bot_state.refresh_callbacks:
                try:
                    await bot_state.refresh_callbacks["on_reload_accounts"]()
                except Exception as cb_err:
                    bot_state.log(f"[UPLOAD] reload callback error: {cb_err}", "warning")

        bot_state.log(
            f"[UPLOAD] JSON upload → added {added}, skipped {skipped}, total {len(existing)}",
            "success" if added > 0 else "warning"
        )

        return web.json_response({
            "status": "ok",
            "added": added,
            "skipped": skipped,
            "total": len(existing),
            "uids": added_uids[:50]
        })

    except Exception as e:
        bot_state.log(f"[UPLOAD ERROR] {e}", "error")
        return web.json_response({"status": "error", "error": str(e)}, status=500)


# ═══════════════════════════════════════════════════════════════
# ✅ DOWNLOAD ALL ACCOUNTS — returns everything currently running
# ═══════════════════════════════════════════════════════════════
async def handle_download_accounts(request: web.Request) -> web.Response:
    try:
        result: List[Dict[str, Any]] = []
        seen_keys: set = set()

        # 1) From running bot_state (live accounts)
        for uid_str, acc in bot_state.accounts.items():
            if uid_str in bot_state.deleted_uids:
                continue
            entry = {
                "uid": str(acc.get("uid", uid_str)),
                "nickname": acc.get("nickname", ""),
                "region": acc.get("region", "BD"),
                "level": acc.get("level", 1),
                "gained_exp": acc.get("gained_exp", 0),
                "current_exp": acc.get("current_exp", 0),
            }
            creds = bot_state.account_credentials.get(uid_str, {})
            if creds.get("password"):
                entry["password"] = creds["password"]
            if creds.get("token"):
                entry["token"] = creds["token"]
            result.append(entry)
            seen_keys.add(uid_str)

        # 2) Fallback: read from all accounts*.json files
        for accounts_file in get_all_account_files_dashboard():
            if not os.path.exists(accounts_file):
                continue
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    file_accounts = json.load(f)
                if not isinstance(file_accounts, list):
                    continue
                for acc in file_accounts:
                    if not isinstance(acc, dict):
                        continue
                    uid = str(acc.get("uid", "") or "").strip()
                    token = str(acc.get("token", "") or acc.get("access_token", "") or "").strip()
                    key = uid or f"tok_{token[:10]}"

                    if key in seen_keys:
                        continue
                    if uid and uid in bot_state.deleted_uids:
                        continue
                    if not uid and token[:10] in bot_state.deleted_uids:
                        continue

                    entry = {}
                    if uid: entry["uid"] = uid
                    if acc.get("password"): entry["password"] = str(acc["password"])
                    if token: entry["token"] = token
                    if acc.get("region"): entry["region"] = str(acc["region"])
                    if acc.get("name"): entry["name"] = str(acc["name"])
                    elif acc.get("nickname"): entry["name"] = str(acc["nickname"])

                    if entry:
                        result.append(entry)
                        seen_keys.add(key)
            except Exception:
                continue

        bot_state.log(f"[DOWNLOAD] Exported {len(result)} account(s)", "info")

        return web.json_response({
            "status": "ok",
            "count": len(result),
            "accounts": result
        })

    except Exception as e:
        bot_state.log(f"[DOWNLOAD ERROR] {e}", "error")
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_set_match_type(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        match_type = str(data.get("match_type", "LONE_WOLF")).strip().upper()
        if not uid:
            return web.json_response({"status": "error", "error": "UID required"}, status=400)
        if match_type not in ("BR", "LONE_WOLF"):
            return web.json_response({"status": "error", "error": "Invalid match_type"}, status=400)
        bot_state.set_match_type(uid, match_type)
        label = "⚔ Battle Royale" if match_type == "BR" else "🐺 Lone Wolf"
        bot_state.log(f"[MATCH TYPE] UID {uid} → {label}", "info", uid)
        return web.json_response({"status": "ok", "uid": uid, "match_type": match_type})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_toggle_global(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        running = bool(data.get("running", True))
        bot_state.global_running = running
        state_str = "চালু (ON)" if running else "বন্ধ (OFF)"
        bot_state.log(f"[GLOBAL] সব বট {state_str} করা হয়েছে", "success" if running else "warning")

        if not running:
            for uid_str in list(bot_state.accounts.keys()):
                if uid_str not in bot_state.deleted_uids:
                    status = bot_state.accounts[uid_str].get("status", "ONLINE")
                    if status not in ("OFFLINE", "ERROR", "CONNECTING", "PAUSED"):
                        bot_state.accounts[uid_str]["status"] = "PAUSED"
        else:
            for uid_str in list(bot_state.accounts.keys()):
                if uid_str not in bot_state.deleted_uids and uid_str not in bot_state.paused_uids:
                    if bot_state.accounts[uid_str].get("status") == "PAUSED":
                        bot_state.accounts[uid_str]["status"] = "ONLINE"
        return web.json_response({"status": "ok", "running": running})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_set_all_mode(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        mode = str(data.get("mode", "LONE_WOLF")).strip().upper()
        if mode not in ("BR", "LONE_WOLF", "AUTO"):
            return web.json_response({"status": "error", "error": "Invalid mode"}, status=400)

        changed = 0
        if mode == "AUTO":
            for uid_str in list(bot_state.accounts.keys()):
                if uid_str not in bot_state.deleted_uids:
                    bot_state.match_types.pop(uid_str, None)
                    if uid_str in bot_state.accounts:
                        lvl = bot_state.get_account_level(uid_str)
                        auto_mt = "BR" if lvl == 2 else "LONE_WOLF"
                        bot_state.accounts[uid_str]["match_type"] = auto_mt
                    changed += 1
            label = "🔄 Auto Level Mode"
        else:
            for uid_str in list(bot_state.accounts.keys()):
                if uid_str not in bot_state.deleted_uids:
                    bot_state.set_match_type(uid_str, mode)
                    changed += 1
            label = "⚔ Battle Royale" if mode == "BR" else "🐺 Lone Wolf"

        bot_state.log(f"[GLOBAL MODE] সব {changed}টি আইডি → {label}", "success")
        return web.json_response({"status": "ok", "mode": mode, "changed": changed})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_set_exp_limit(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        raw = data.get("exp_limit", None)
        if raw is None:
            return web.json_response({"status": "error", "error": "exp_limit missing"}, status=400)
        try:
            limit = int(str(raw).strip().replace(",", ""))
        except (ValueError, TypeError):
            return web.json_response({"status": "error", "error": "exp_limit must be number"}, status=400)
        if limit < 0:
            return web.json_response({"status": "error", "error": "cannot be negative"}, status=400)
        bot_state.exp_limit = limit
        msg = f"EXP লিমিট সেট: {limit:,}" if limit > 0 else "EXP লিমিট বন্ধ"
        bot_state.log(f"[EXP LIMIT] {msg}", "success")
        return web.json_response({"status": "ok", "exp_limit": limit})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_pause_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "uid required"}, status=400)
        bot_state.pause_account(uid)
        return web.json_response({"status": "ok", "uid": uid, "paused": True})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_resume_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "uid required"}, status=400)
        bot_state.resume_account(uid)
        return web.json_response({"status": "ok", "uid": uid, "paused": False})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/login", handle_login)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/account/pause", handle_pause_account)
    app.router.add_post("/api/account/resume", handle_resume_account)
    app.router.add_post("/api/accounts/reload", handle_reload_accounts)
    app.router.add_post("/api/accounts/upload", handle_upload_accounts)
    app.router.add_get("/api/accounts/download", handle_download_accounts)
    app.router.add_post("/api/account/match-type", handle_set_match_type)
    app.router.add_post("/api/bot/toggle", handle_toggle_global)
    app.router.add_post("/api/accounts/set-all-mode", handle_set_all_mode)
    app.router.add_post("/api/settings/exp-limit", handle_set_exp_limit)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] AFT FF LEVEL dashboard → http://localhost:{port}\033[0m")
    print(f"\033[92m[+] Template: {DASHBOARD_HTML_FILE}\033[0m")
    print(f"\033[92m[+] Login: {DASH_USER} / {DASH_PASS}\033[0m")