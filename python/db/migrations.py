"""
数据库 Schema 迁移脚本
定义所有表结构
"""

def get_init_sql() -> str:
    """获取初始化 SQL 脚本"""
    return """
    -- 商家配置表
    CREATE TABLE IF NOT EXISTS merchants (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        url             TEXT NOT NULL,
        login_url       TEXT NOT NULL DEFAULT '',
        cookie_domains  TEXT DEFAULT '[]',
        headers         TEXT DEFAULT '{}',
        api_endpoints   TEXT DEFAULT '[]',
        status          TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'error')),
        timeout         INTEGER DEFAULT 30,
        wait_after_login INTEGER DEFAULT 3,
        max_retries     INTEGER DEFAULT 3,
        last_login_at   INTEGER DEFAULT 0,
        credential_expires_at INTEGER DEFAULT 0,
        created_at      INTEGER NOT NULL,
        updated_at      INTEGER NOT NULL,
        is_deleted      INTEGER DEFAULT 0
    );

    -- 凭证存储表（加密存储 Cookie）
    CREATE TABLE IF NOT EXISTS credentials (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant_id         TEXT NOT NULL UNIQUE,
        encrypted_cookies   TEXT NOT NULL,
        encrypted_cookie_string TEXT NOT NULL DEFAULT '',
        cookie_domains      TEXT DEFAULT '[]',
        expires_at          INTEGER NOT NULL,
        created_at          INTEGER NOT NULL,
                source_url           TEXT DEFAULT '',
        is_valid            INTEGER DEFAULT 1,
                updated_at          INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE
    );

    -- 采集数据表
    CREATE TABLE IF NOT EXISTS collected_data (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id         TEXT NOT NULL DEFAULT '',
        merchant_id     TEXT NOT NULL,
        merchant_name   TEXT NOT NULL,
        raw_data        TEXT NOT NULL, -- JSON 格式（字段映射后的结构化数据）
        collected_at    INTEGER NOT NULL,
        FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE
    );
    
    -- 为 collected_data 创建索引以加速查询
    CREATE INDEX IF NOT EXISTS idx_collected_merchant ON collected_data(merchant_id);
    CREATE INDEX IF NOT EXISTS idx_collected_time ON collected_data(collected_at);



    -- 任务配置表
    CREATE TABLE IF NOT EXISTS tasks (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        merchant_ids    TEXT DEFAULT '[]',
        curl_command    TEXT DEFAULT '',
        method          TEXT DEFAULT 'GET',
        url             TEXT DEFAULT '',
        headers         TEXT DEFAULT '{}',
        params          TEXT DEFAULT '{}',
        body            TEXT DEFAULT '',
        inject_credential INTEGER DEFAULT 1,
        field_mapping   TEXT DEFAULT '{}',
        response_extract TEXT DEFAULT '{}',
        pagination      TEXT DEFAULT '{}',
        cron_expression TEXT DEFAULT '',
        status          TEXT DEFAULT 'idle' CHECK(status IN ('idle', 'running', 'success', 'error', 'disabled')),
        last_run_at     INTEGER DEFAULT 0,
        last_result     TEXT DEFAULT '',
        created_at      INTEGER NOT NULL,
        updated_at      INTEGER NOT NULL,
        is_deleted      INTEGER DEFAULT 0
    );
    """


def run_migrations(conn):
    """执行数据库迁移（增量更新）"""
    cursor = conn.cursor()

    # 检查并添加 tasks 表的新字段
    existing_columns = set()
    try:
        cols = conn.execute("PRAGMA table_info(tasks)").fetchall()
        for col in cols:
            existing_columns.add(col[1])
    except Exception:
        pass

    new_columns = {
        'response_extract': "TEXT DEFAULT '{}'",
        'pagination': "TEXT DEFAULT '{}'",
    }

    for column_name, column_def in new_columns.items():
        if column_name not in existing_columns:
            try:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {column_name} {column_def}")
                print(f"[Migration] Added column tasks.{column_name}")
            except Exception as e:
                print(f"[Migration] Skip tasks.{column_name}: {e}")

    # 检查并添加 collected_data 表的 task_id 字段
    data_existing_columns = set()
    try:
        data_cols = conn.execute("PRAGMA table_info(collected_data)").fetchall()
        for col in data_cols:
            data_existing_columns.add(col[1])
    except Exception:
        pass

    if 'task_id' not in data_existing_columns:
        try:
            conn.execute("ALTER TABLE collected_data ADD COLUMN task_id TEXT NOT NULL DEFAULT ''")
            print("[Migration] Added column collected_data.task_id")
        except Exception as e:
            print(f"[Migration] Skip collected_data.task_id: {e}")

    conn.commit()
