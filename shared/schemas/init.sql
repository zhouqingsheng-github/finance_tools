-- Finance Tools 数据库初始化脚本
-- SQLite Schema Definition

-- 商家配置表
CREATE TABLE IF NOT EXISTS merchants (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    login_url       TEXT NOT NULL DEFAULT '',
    username        TEXT DEFAULT '',
    password        TEXT DEFAULT '',
    username_selector TEXT DEFAULT '',
    password_selector TEXT DEFAULT '',
    submit_selector    TEXT DEFAULT '',
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

-- 凭证存储表（AES-256-GCM 加密存储 Cookie + StorageState）
CREATE TABLE IF NOT EXISTS credentials (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id         TEXT NOT NULL UNIQUE,
    encrypted_cookies   TEXT NOT NULL,
    encrypted_cookie_string TEXT NOT NULL DEFAULT '',
    encrypted_storage_state TEXT NOT NULL DEFAULT '',
    cookie_domains      TEXT DEFAULT '[]',
    expires_at          INTEGER NOT NULL,
    created_at          INTEGER NOT NULL,
                source_url           TEXT DEFAULT '',
    is_valid            INTEGER DEFAULT 1,
                updated_at          INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE
);

-- 采集数据存储表
CREATE TABLE IF NOT EXISTS collected_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL DEFAULT '',     -- 关联任务 ID
    merchant_id     TEXT NOT NULL,
    merchant_name   TEXT NOT NULL,
    raw_data        TEXT NOT NULL, -- JSON 格式（字段映射后的结构化数据）
    collected_at    INTEGER NOT NULL,
    FOREIGN KEY (merchant_id) REFERENCES merchants(id) ON DELETE CASCADE
);

-- 索引优化查询性能
CREATE INDEX IF NOT EXISTS idx_collected_merchant ON collected_data(merchant_id);
CREATE INDEX IF NOT EXISTS idx_collected_time ON collected_data(collected_at);
CREATE INDEX IF NOT EXISTS idx_credential_merchant ON credentials(merchant_id);

-- 任务配置表（用户创建的采集任务）
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    merchant_ids    TEXT DEFAULT '[]',       -- 关联商家ID列表（JSON数组，支持多选）
    curl_command    TEXT DEFAULT '',       -- 原始 CURL 命令
    method          TEXT DEFAULT 'GET',    -- HTTP 方法
    url             TEXT DEFAULT '',       -- 解析后的请求 URL
    headers         TEXT DEFAULT '{}',     -- 解析后的请求头 JSON
    params          TEXT DEFAULT '{}',     -- 请求参数 JSON
    body            TEXT DEFAULT '',       -- 请求体
    inject_credential INTEGER DEFAULT 1,  -- 是否注入登录凭证（Cookie）
    field_mapping   TEXT DEFAULT '{}',     -- 动态参数映射（执行时替换请求中的值）
    response_extract TEXT DEFAULT '{}',     -- 响应提取配置（从响应JSON提取哪些字段）
    pagination      TEXT DEFAULT '{}',     -- 分页配置（自动循环翻页）
    cron_expression TEXT DEFAULT '',       -- 定时表达式（预留）
    status          TEXT DEFAULT 'idle' CHECK(status IN ('idle', 'running', 'success', 'error', 'disabled')),
    last_run_at     INTEGER DEFAULT 0,
    last_result     TEXT DEFAULT '',       -- 最近一次执行结果摘要
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    is_deleted      INTEGER DEFAULT 0
);


