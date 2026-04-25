"""
SQLite 数据库初始化与连接管理
"""

import sqlite3
import logging
import os
from pathlib import Path

logger = logging.getLogger('finance-tools.db')


class DatabaseManager:
    """数据库管理器，负责初始化和连接管理"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_database()
    
    def _ensure_db_directory(self):
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            Path(db_dir).mkdir(parents=True, exist_ok=True)
    
    def _init_database(self):
        """初始化数据库表结构"""
        conn = self.get_connection()
        
        try:
            # 读取并执行建表 SQL 脚本
            from db.migrations import get_init_sql
            sql = get_init_sql()
            
            cursor = conn.cursor()
            # 分割多条 SQL 语句执行
            for statement in sql.split(';'):
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)

            # ===== 迁移：确保 merchants 表有 username/password/selectors 字段 =====
            self._migrate_merchants_schema(conn)

            # ===== 迁移：确保 credentials 表有 encrypted_storage_state 字段 =====
            self._migrate_credentials_schema(conn)

            # ===== 迁移：确保 tasks 表存在 =====
            self._migrate_tasks_table(conn)

            # ===== 迁移：确保 tasks 表有新字段（response_extract, pagination）=====
            self._migrate_tasks_new_columns(conn)

            # ===== 迁移：确保 collected_data 表有 task_id 字段 =====
            self._migrate_collected_data_task_id(conn)

            # ===== 迁移：清理旧 data_type 字段 + merchant_id → merchant_ids =====
            self._migrate_tasks_cleanup(conn)

            # ===== 迁移：删除废弃的 task_logs 表（日志改用前端内存存储）=====
            self._drop_task_logs_table(conn)

            # ===== 迁移：为 tasks 表添加 task_type + browser_config 字段（浏览器自动化模式）=====
            self._migrate_tasks_browser_mode(conn)

            # ===== 迁移：确保任务运行流水表存在（仪表盘真实统计）=====
            self._migrate_task_runs_table(conn)

            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")
            
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            raise
        finally:
            conn.close()

    def _migrate_merchants_schema(self, conn: sqlite3.Connection):
        """迁移 merchants 表：确保登录相关字段存在（username/password/selectors）
        
        SQLite 不支持直接 ADD COLUMN IF NOT EXISTS（3.35.0+ 才支持），
        需要重建表来添加缺失字段。
        """
        cursor = conn.cursor()
        
        # 检查当前列
        cursor.execute("PRAGMA table_info(merchants)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # 需要的字段
        required_fields = {
            'username': "TEXT DEFAULT ''",
            'password': "TEXT DEFAULT ''",
            'username_selector': "TEXT DEFAULT ''",
            'password_selector': "TEXT DEFAULT ''",
            'submit_selector': "TEXT DEFAULT ''",
        }
        
        # 检查是否有缺失字段
        missing_fields = {k: v for k, v in required_fields.items() if k not in columns}
        
        if not missing_fields:
            return
        
        logger.info(f"Migrating merchants table: adding {list(missing_fields.keys())}...")
        
        try:
            # 获取当前建表 SQL
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='merchants'")
            row = cursor.fetchone()
            if not row or not row[0]:
                return
            
            # 构建新表 DDL：在 is_deleted 之前插入新字段
            old_sql = row[0]
            # 在 created_at 之前插入新字段
            insert_before = 'created_at'
            new_cols_sql = ', '.join(f'{k} {v}' for k, v in missing_fields.items())
            if insert_before in old_sql:
                new_sql = old_sql.replace(insert_before, f"{new_cols_sql},\n    {insert_before}")
            else:
                new_sql = old_sql.rstrip(')') + f",\n    {new_cols_sql})"
            
            cursor.execute(f"CREATE TABLE IF NOT EXISTS merchants_new (\n{new_sql.split('(', 1)[1]}", ())
            
            # 复制数据（旧列原样复制，新列用默认值）
            all_cols = [row[1] for row in cursor.execute("PRAGMA table_info(merchants)").fetchall()]
            valid_cols = [c for c in all_cols if c != 'id' and c in columns]
            cols_str = 'id, ' + ', '.join(valid_cols) if valid_cols else 'id'
            
            cursor.execute(f"INSERT INTO merchants_new ({cols_str}) SELECT {cols_str} FROM merchants")
            
            # 删除旧表，重命名新表
            cursor.execute('DROP TABLE merchants')
            cursor.execute('ALTER TABLE merchants_new RENAME TO merchants')
            
            # 重建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_collected_merchant ON collected_data(merchant_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_collected_time ON collected_data(collected_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_credential_merchant ON credentials(merchant_id)")

            logger.info("Merchants schema migration completed successfully")
            
        except Exception as e:
            logger.warning(f"Merchants schema migration failed: {e}")
            conn.rollback()

    def _migrate_credentials_schema(self, conn: sqlite3.Connection):
        """迁移 credentials 表：确保 encrypted_storage_state 字段存在"""
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(credentials)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'encrypted_storage_state' in columns:
            return
        
        logger.info("Migrating credentials table: adding encrypted_storage_state...")
        
        try:
            cursor.execute("ALTER TABLE credentials ADD COLUMN encrypted_storage_state TEXT NOT NULL DEFAULT ''")
            logger.info("Credentials schema migration completed successfully")
        except Exception as e:
            logger.warning(f"Credentials schema migration failed: {e}")
            conn.rollback()

    def _migrate_tasks_table(self, conn: sqlite3.Connection):
        """迁移：创建 tasks 表（如果不存在）"""
        cursor = conn.cursor()

        # 检查 tasks 表是否已存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        if cursor.fetchone():
            return

        logger.info("Creating tasks table...")
        try:
            cursor.execute("""
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
                )
            """)
            logger.info("Tasks table created successfully")
        except Exception as e:
            logger.warning(f"Tasks table creation failed: {e}")
            conn.rollback()

    def _migrate_tasks_new_columns(self, conn: sqlite3.Connection):
        """迁移：为 tasks 表添加 response_extract 和 pagination 字段（如不存在）"""
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in cursor.fetchall()]

        new_columns = {
            'response_extract': "TEXT DEFAULT '{}'",
            'pagination': "TEXT DEFAULT '{}'",
        }

        for col_name, col_def in new_columns.items():
            if col_name not in columns:
                try:
                    cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_def}")
                    logger.info(f"Tasks table: added column {col_name}")
                except Exception as e:
                    logger.warning(f"Tasks migration failed for {col_name}: {e}")

    def _migrate_collected_data_task_id(self, conn: sqlite3.Connection):
        """迁移：为 collected_data 表添加 task_id 字段（如不存在）"""
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(collected_data)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'task_id' in columns:
            return

        logger.info("Migrating collected_data table: adding task_id...")
        try:
            cursor.execute("ALTER TABLE collected_data ADD COLUMN task_id TEXT NOT NULL DEFAULT ''")
            logger.info("Collected_data schema migration completed successfully")
        except Exception as e:
            logger.warning(f"Collected_data migration failed for task_id: {e}")

    def _migrate_tasks_cleanup(self, conn: sqlite3.Connection):
        """迁移：清理旧字段（data_type、merchant_id → merchant_ids）"""
        cursor = conn.cursor()

        # 1. 删除已废弃的 data_type 列（tasks 和 collected_data）
        for table in ['collected_data', 'tasks']:
            try:
                cursor.execute(f"ALTER TABLE {table} DROP COLUMN data_type")
                logger.info(f"Dropped data_type column from {table}")
            except Exception:
                pass  # 列不存在则忽略

        # 2. 迁移旧 merchant_id（单值）→ merchant_ids（JSON数组）
        try:
            cols = [row[1] for row in cursor.execute("PRAGMA table_info(tasks)").fetchall()]
            if 'merchant_id' in cols and 'merchant_ids' not in cols:
                logger.info("Migrating merchant_id -> merchant_ids (JSON array)...")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tasks_new (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        merchant_ids TEXT DEFAULT '[]',
                        curl_command TEXT DEFAULT '',
                        method TEXT DEFAULT 'GET',
                        url TEXT DEFAULT '',
                        headers TEXT DEFAULT '{}',
                        params TEXT DEFAULT '{}',
                        body TEXT DEFAULT '',
                        inject_credential INTEGER DEFAULT 1,
                        field_mapping TEXT DEFAULT '{}',
                        response_extract TEXT DEFAULT '{}',
                        pagination TEXT DEFAULT '{}',
                        cron_expression TEXT DEFAULT '',
                        status TEXT DEFAULT 'idle' CHECK(status IN ('idle','running','success','error','disabled')),
                        last_run_at INTEGER DEFAULT 0,
                        last_result TEXT DEFAULT '',
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        is_deleted INTEGER DEFAULT 0
                    )
                """)
                cursor.execute("""
                    INSERT INTO tasks_new (id,name,merchant_ids,curl_command,method,url,headers,params,body,
                    inject_credential,field_mapping,response_extract,pagination,cron_expression,status,
                    last_run_at,last_result,created_at,updated_at,is_deleted)
                    SELECT id,name,json_array(merchant_id),curl_command,method,url,headers,params,body,
                    inject_credential,field_mapping,response_extract,pagination,cron_expression,status,
                    last_run_at,last_result,created_at,updated_at,is_deleted FROM tasks
                """)
                cursor.execute('DROP TABLE tasks')
                cursor.execute('ALTER TABLE tasks_new RENAME TO tasks')
                logger.info("Migrated merchant_id -> merchant_ids (JSON array)")
            elif 'merchant_id' in cols and 'merchant_ids' in cols:
                # 两列都存在，只删旧的 merchant_id
                try:
                    cursor.execute("ALTER TABLE tasks DROP COLUMN merchant_id")
                    logger.info("Dropped legacy merchant_id column from tasks (merchant_ids already exists)")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Tasks cleanup migration failed: {e}")

    def _drop_task_logs_table(self, conn: sqlite3.Connection):
        """迁移：删除废弃的 task_logs 表（日志改用前端内存存储）"""
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_logs'")
            if cursor.fetchone():
                cursor.execute('DROP TABLE task_logs')
                logger.info("Dropped deprecated task_logs table")
        except Exception as e:
            logger.warning(f"Failed to drop task_logs table: {e}")

    def _migrate_tasks_browser_mode(self, conn: sqlite3.Connection):
        """迁移：为 tasks 表添加 task_type + browser_config 字段（浏览器自动化模式）"""
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(tasks)")
            columns = [row[1] for row in cursor.fetchall()]

            new_columns = {
                'task_type': "TEXT DEFAULT 'curl'",
                'browser_config': "TEXT DEFAULT '{}'",
            }

            for col_name, col_def in new_columns.items():
                if col_name not in columns:
                    try:
                        cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_def}")
                        logger.info(f"Tasks table: added column {col_name}")
                    except Exception as e:
                        logger.warning(f"Tasks migration failed for {col_name}: {e}")

        except Exception as e:
            logger.warning(f"Browser mode migration failed: {e}")

    def _migrate_task_runs_table(self, conn: sqlite3.Connection):
        """迁移：创建 task_runs 表（每次任务×商家执行流水）"""
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_runs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id         TEXT NOT NULL DEFAULT '',
                    task_name       TEXT NOT NULL DEFAULT '',
                    merchant_id     TEXT NOT NULL DEFAULT '',
                    merchant_name   TEXT NOT NULL DEFAULT '',
                    status          TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running', 'success', 'error')),
                    collected_count INTEGER NOT NULL DEFAULT 0,
                    message         TEXT NOT NULL DEFAULT '',
                    started_at      INTEGER NOT NULL,
                    finished_at     INTEGER NOT NULL DEFAULT 0,
                    duration_ms     INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_started_at ON task_runs(started_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_status ON task_runs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_merchant ON task_runs(merchant_id)")
        except Exception as e:
            logger.warning(f"Task runs migration failed: {e}")

    def get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        # 启用 WAL 模式以支持并发读写
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        
        return conn

    @staticmethod
    def dict_from_row(row: sqlite3.Row) -> dict:
        """将 Row 对象转换为字典"""
        return dict(row)


# 全局单例
_instance: DatabaseManager | None = None


def init_database(db_path: str = 'shared/db/finance_tools.db') -> DatabaseManager:
    """初始化全局数据库实例"""
    global _instance
    if _instance is None:
        _instance = DatabaseManager(db_path)
    return _instance


def get_db() -> DatabaseManager:
    """获取全局数据库实例"""
    if _instance is None:
        return init_database()
    return _instance
