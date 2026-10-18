-- legalmind_app：协同会话 / Agent 注册表 / 长期记忆 / 编排台账
-- 全新 compose up 时由 00-create-dbs.sql 建库后自动执行；
-- 已存在的数据卷需手动执行本文件（psql）。
-- 全部时间字段使用 TIMESTAMPTZ；UUID 主键由 PG13+ 内置 gen_random_uuid() 生成。
\c legalmind_app

-- ============ 会话 ============
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     VARCHAR(64)  NOT NULL,
    type        VARCHAR(16)  NOT NULL CHECK (type IN ('direct', 'group')),
    case_type   VARCHAR(32),                              -- 模板标识：contract/labor/.../custom
    title       VARCHAR(256),
    status      VARCHAR(16)  NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'archived')),
    my_role           VARCHAR(64),                        -- B3 用户扮演的 agent_id（空＝不扮演，仅 group）
    target_agent_id   VARCHAR(64),                        -- B1 单聊目标 Agent（仅 direct）
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 已有数据卷的幂等迁移（新建库走上方 CREATE TABLE，无需重复执行）
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS my_role VARCHAR(64);
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS target_agent_id VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_conversations_user
    ON conversations (user_id, status, updated_at DESC);

-- ============ 会话成员（Agent） ============
CREATE TABLE IF NOT EXISTS conversation_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    agent_id        VARCHAR(64) NOT NULL,
    role            VARCHAR(32) NOT NULL DEFAULT 'member',  -- host / member
    is_auto         BOOLEAN     NOT NULL DEFAULT true,      -- 模板自动拉入 / 用户手动添加
    joined_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_members_conversation
    ON conversation_members (conversation_id);

-- ============ 消息（统一 transcript：user/agent/tool/system） ============
CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_type     VARCHAR(16) NOT NULL
                    CHECK (sender_type IN ('user', 'agent', 'tool', 'system')),
    sender_id       VARCHAR(64) NOT NULL,
    sender_name     VARCHAR(128),
    content         TEXT NOT NULL DEFAULT '',
    msg_type        VARCHAR(16) NOT NULL DEFAULT 'text'
                    CHECK (msg_type IN ('text', 'tool', 'card', 'minutes', 'notice', 'directive')),
    round           INTEGER NOT NULL DEFAULT 0,
    -- 确定性幂等键：{turn_id}:r{round}:{agent_id}:{seq}（T1.5，INSERT ... ON CONFLICT DO NOTHING）
    event_key       VARCHAR(128),
    -- 时间旅行：fork 分支消息指向父分支原消息（F12）
    fork_parent_message_id UUID,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 已有数据卷的幂等迁移
ALTER TABLE messages ADD COLUMN IF NOT EXISTS event_key VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
    ON messages (conversation_id, created_at);
-- 幂等键唯一（PG 唯一索引中多行 NULL 互不冲突，无需部分索引；
-- 且 store 使用 `ON CONFLICT (event_key)`，部分索引无法被 PG 推断）
CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_event_key
    ON messages (event_key);
CREATE INDEX IF NOT EXISTS idx_messages_fork_parent
    ON messages (fork_parent_message_id)
    WHERE fork_parent_message_id IS NOT NULL;

-- ============ Agent 注册表（数据驱动，不硬编码） ============
CREATE TABLE IF NOT EXISTS agent_registry (
    agent_id    VARCHAR(64) PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    avatar      VARCHAR(256),                              -- 前端可按 agent_id 自映射
    role_label  VARCHAR(64)  NOT NULL,
    description TEXT,
    skill_ref   VARCHAR(128),                              -- 绑定的现有 Skill
    persona     TEXT,                                      -- 人设 system prompt
    model_pref  JSONB NOT NULL DEFAULT '{}',               -- {temperature, max_tokens, model?}
    is_tool     BOOLEAN NOT NULL DEFAULT false,            -- 检索类：轮首并行预取，不占串行位
    sort_order  INTEGER NOT NULL DEFAULT 100,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ 案情模板（表驱动，新增模板=插一行） ============
CREATE TABLE IF NOT EXISTS case_roster_templates (
    case_type       VARCHAR(32) PRIMARY KEY,               -- contract/labor/marriage/tort/debt/realestate/court/custom
    name            VARCHAR(128) NOT NULL,
    icon            VARCHAR(32),
    description     TEXT,
    host_agent_id   VARCHAR(64) NOT NULL,                  -- 主持人 agent_id
    roster          JSONB NOT NULL DEFAULT '[]',
                    -- 元素：{"agent_id": "...", "stage": "opening|debate", "order": 1}
    max_rounds      INTEGER NOT NULL DEFAULT 2,            -- court=3，其余=2
    opening_enabled BOOLEAN NOT NULL DEFAULT true,         -- round=1 主持人是否发开场
    minutes_enabled BOOLEAN NOT NULL DEFAULT true,         -- 收敛后是否自动出会商纪要
    adapter         VARCHAR(32) NOT NULL DEFAULT 'generic'
                    CHECK (adapter IN ('generic', 'court')),
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ 长期记忆（内容 PG，向量在 Qdrant user_memories） ============
CREATE TABLE IF NOT EXISTS memories (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 VARCHAR(64) NOT NULL,
    scope                   VARCHAR(16) NOT NULL CHECK (scope IN ('user', 'case')),
    case_id                 UUID,                           -- scope=case 时
    memory_type             VARCHAR(32) NOT NULL,          -- fact/preference/background/...
    content                 TEXT NOT NULL,
    summary                 TEXT,
    importance              SMALLINT NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    source_conversation_id  UUID,
    source_message_id       UUID,
    status                  VARCHAR(16) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'archived')),
    embedding_status        VARCHAR(16) NOT NULL DEFAULT 'pending'
                            CHECK (embedding_status IN ('pending', 'done', 'failed')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memories_user
    ON memories (user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_case
    ON memories (case_id)
    WHERE case_id IS NOT NULL;

-- ============ 编排执行台账（恢复与幂等的权威依据，T0.9 起使用） ============
CREATE TABLE IF NOT EXISTS collab_turns (
    turn_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id             VARCHAR(64) NOT NULL,
    trigger_message_id  UUID,
    status              VARCHAR(16) NOT NULL
                        CHECK (status IN ('running', 'interrupted', 'completed', 'failed')),
    mode                VARCHAR(16) NOT NULL DEFAULT 'inprocess'
                        CHECK (mode IN ('kafka', 'inprocess')),
    worker_id           VARCHAR(128),
    worker_heartbeat    TIMESTAMPTZ,
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_checkpoint_id  VARCHAR(128),                      -- 最近成功 super-step
    error               JSONB,                             -- {code, message, request_id}
    forked_from_turn_id UUID,                              -- 时间旅行 fork 来源
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_turns_conversation
    ON collab_turns (conversation_id, created_at DESC);
-- worker 心跳扫描：认领 running 但心跳超时的 turn
CREATE INDEX IF NOT EXISTS idx_turns_status_heartbeat
    ON collab_turns (status, worker_heartbeat)
    WHERE status IN ('running', 'interrupted');

-- ============ 主持人决策审计（"法官为什么让他发言"） ============
CREATE TABLE IF NOT EXISTS host_decisions (
    id                BIGSERIAL PRIMARY KEY,
    turn_id           UUID NOT NULL REFERENCES collab_turns(turn_id) ON DELETE CASCADE,
    conversation_id   UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    round             INTEGER NOT NULL,
    host_agent_id     VARCHAR(64) NOT NULL,
    raw_output        TEXT,
    parsed_directive  JSONB,
    accepted          BOOLEAN NOT NULL DEFAULT true,
    rejection_reason  VARCHAR(64),                         -- whitelist/max_rounds/budget/bad_format/...
    request_id        VARCHAR(64),
    latency_ms        INTEGER,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_host_decisions_turn
    ON host_decisions (turn_id);
CREATE INDEX IF NOT EXISTS idx_host_decisions_conversation
    ON host_decisions (conversation_id, created_at DESC);
