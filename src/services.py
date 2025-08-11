from datetime import date, datetime
from typing import Optional, Dict, Any
import json
from db import get_conn


def create_user(username: str, email: str, api_key: str, tier: str = 'free') -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username,email,api_key,tier) VALUES (%s,%s,%s,%s)",
                    (username, email, api_key, tier))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE api_key=%s", (api_key,))
        return cur.fetchone()


def get_user_by_api_key(api_key: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE api_key=%s", (api_key,))
        return cur.fetchone()


def ensure_usage_row(user_id: int, for_date: date):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM usage_logs WHERE user_id=%s AND log_date=%s", (user_id, for_date))
        r = cur.fetchone()
        if not r:
            cur.execute("INSERT INTO usage_logs (user_id, log_date, calls_today, projects_this_month) VALUES (%s,%s,0,0)",
                        (user_id, for_date))
            conn.commit()


def increment_call_and_check_limit(user_id: int, daily_limit: int) -> bool:
    today = date.today()
    with get_conn() as conn:
        cur = conn.cursor()
        # ensure row exists
        cur.execute("SELECT id,calls_today FROM usage_logs WHERE user_id=%s AND log_date=%s", (user_id, today))
        r = cur.fetchone()
        if not r:
            cur.execute("INSERT INTO usage_logs (user_id, log_date, calls_today, projects_this_month) VALUES (%s,%s,1,0)", (user_id, today))
            conn.commit()
            return True
        if r['calls_today'] + 1 > daily_limit:
            return False
        cur.execute("UPDATE usage_logs SET calls_today=calls_today+1 WHERE id=%s", (r['id'],))
        conn.commit()
        return True


def increment_project_and_check_limit(user_id: int, month_limit: int) -> bool:
    today = date.today()
    first_of_month = date(today.year, today.month, 1)
    with get_conn() as conn:
        cur = conn.cursor()
        # sum projects_this_month for current month rows (we keep projects in single monthly counter per day rows)
        cur.execute("SELECT SUM(projects_this_month) as total FROM usage_logs WHERE user_id=%s AND log_date >= %s", (user_id, first_of_month))
        r = cur.fetchone()
        total = r['total'] or 0
        if total + 1 > month_limit:
            return False
        # increment today's row's projects_this_month
        cur.execute("SELECT id FROM usage_logs WHERE user_id=%s AND log_date=%s", (user_id, today))
        row = cur.fetchone()
        if not row:
            cur.execute("INSERT INTO usage_logs (user_id, log_date, calls_today, projects_this_month) VALUES (%s,%s,0,1)", (user_id, today))
        else:
            cur.execute("UPDATE usage_logs SET projects_this_month=projects_this_month+1 WHERE id=%s", (row['id'],))
        conn.commit()
        return True


def create_preset(user_id: int, name: str, template: str, git_init: bool, use_venv: bool, license_type: Optional[str]):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO presets (user_id,name,template,git_init,use_venv,license_type) VALUES (%s,%s,%s,%s,%s,%s)",
                    (user_id, name, template, int(git_init), int(use_venv), license_type))
        conn.commit()
        cur.execute("SELECT * FROM presets WHERE id = LAST_INSERT_ID()")
        return cur.fetchone()


def list_presets(user_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM presets WHERE user_id=%s", (user_id,))
        return cur.fetchall()


def get_preset(user_id: int, preset_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM presets WHERE id=%s AND user_id=%s", (preset_id, user_id))
        return cur.fetchone()


def update_preset(user_id: int, preset_id: int, data: dict):
    fields = []
    values = []
    for k, v in data.items():
        fields.append(f"{k}=%s")
        values.append(v)
    values.extend([preset_id, user_id])
    set_clause = ','.join(fields)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE presets SET {set_clause} WHERE id=%s AND user_id=%s", tuple(values))
        conn.commit()
        return get_preset(user_id, preset_id)


def delete_preset(user_id: int, preset_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM presets WHERE id=%s AND user_id=%s", (preset_id, user_id))
        conn.commit()
        return cur.rowcount > 0