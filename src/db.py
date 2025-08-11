import os
import queue
import threading
from contextlib import contextmanager
import pymysql
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv('MYSQL_HOST', 'mysql.railway.internal')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'BbVIcArOMINDXbUyuEkhrflgFDtvzwve')
MYSQLDATABASE = os.getenv('MYSQLDATABASE', 'bootstrapper')
POOL_MIN = int(os.getenv('POOL_MIN_CONN', '1'))
POOL_MAX = int(os.getenv('POOL_MAX_CONN', '5'))

_pool_lock = threading.Lock()
_pool = None


def _create_connection():
    return pymysql.connect(host=MYSQL_HOST,
                           port=MYSQL_PORT,
                           user=MYSQL_USER,
                           password=MYSQL_PASSWORD,
                           db=MYSQL_DB,
                           charset='utf8mb4',
                           cursorclass=pymysql.cursors.DictCursor,
                           autocommit=False)


def init_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            return
        q = queue.Queue(maxsize=POOL_MAX)
        for _ in range(POOL_MIN):
            q.put(_create_connection())
        _pool = q


@contextmanager
def get_conn():
    global _pool
    if _pool is None:
        init_pool()
    try:
        conn = _pool.get(block=True, timeout=5)
    except Exception:
        # fallback to direct connection
        conn = _create_connection()
        borrowed = False
    else:
        borrowed = True
    try:
        yield conn
    finally:
        try:
            if borrowed:
                # return connection to pool if still open
                if conn.open:
                    _pool.put(conn)
                else:
                    # replace dead connection
                    _pool.put(_create_connection())
            else:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception:
            pass
