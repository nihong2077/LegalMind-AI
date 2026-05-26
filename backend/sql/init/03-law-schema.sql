\c law_db

CREATE EXTENSION IF NOT EXISTS vector;

-- 法律法规
CREATE TABLE IF NOT EXISTS legal_provisions (
    id SERIAL PRIMARY KEY,
    law_name VARCHAR(256) NOT NULL,
    law_type VARCHAR(64) NOT NULL,
    chapter VARCHAR(256),
    section VARCHAR(256),
    article_number VARCHAR(64),
    article_title VARCHAR(512),
    content TEXT NOT NULL,
    effective_date DATE,
    status VARCHAR(32) DEFAULT 'active',
    keywords JSONB DEFAULT '[]',
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_provisions_law ON legal_provisions(law_name, law_type);
CREATE INDEX IF NOT EXISTS idx_provisions_article ON legal_provisions(article_number) WHERE article_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_provisions_status ON legal_provisions(status);
CREATE INDEX IF NOT EXISTS idx_provisions_embedding ON legal_provisions USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_provisions_keywords ON legal_provisions USING gin (keywords);

-- 司法解释
CREATE TABLE IF NOT EXISTS judicial_interpretations (
    id SERIAL PRIMARY KEY,
    interpretation_number VARCHAR(128),
    title VARCHAR(512) NOT NULL,
    issuing_body VARCHAR(256),
    issue_date DATE,
    effective_date DATE,
    content TEXT NOT NULL,
    related_laws TEXT,
    keywords JSONB DEFAULT '[]',
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interpretations_date ON judicial_interpretations(issue_date);
CREATE INDEX IF NOT EXISTS idx_interpretations_embedding ON judicial_interpretations USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- 部门规章 / 行政法规
CREATE TABLE IF NOT EXISTS administrative_regulations (
    id SERIAL PRIMARY KEY,
    regulation_name VARCHAR(512) NOT NULL,
    issuing_body VARCHAR(256),
    document_number VARCHAR(128),
    issue_date DATE,
    effective_date DATE,
    content TEXT NOT NULL,
    category VARCHAR(128),
    keywords JSONB DEFAULT '[]',
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_regulations_category ON administrative_regulations(category);
CREATE INDEX IF NOT EXISTS idx_regulations_embedding ON administrative_regulations USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
