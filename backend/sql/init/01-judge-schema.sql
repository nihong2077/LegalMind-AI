CREATE EXTENSION IF NOT EXISTS vector;

-- 裁判文书 / 判例
CREATE TABLE IF NOT EXISTS judge_cases (
    id SERIAL PRIMARY KEY,
    case_number VARCHAR(128) NOT NULL,
    case_name VARCHAR(512) NOT NULL,
    court_level VARCHAR(64),
    court_name VARCHAR(256),
    case_type VARCHAR(64),
    cause_of_action VARCHAR(256),
    judgment_date DATE,
    plaintiff_claim TEXT,
    defendant_defense TEXT,
    facts_summary TEXT,
    judgment_reasoning TEXT,
    judgment_result TEXT,
    applicable_laws TEXT,
    keywords JSONB DEFAULT '[]',
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_judge_cases_number ON judge_cases(case_number);
CREATE INDEX IF NOT EXISTS idx_judge_cases_type ON judge_cases(case_type);
CREATE INDEX IF NOT EXISTS idx_judge_cases_court ON judge_cases(court_level, court_name);
CREATE INDEX IF NOT EXISTS idx_judge_cases_embedding ON judge_cases USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- 量刑标准 / 审判指南
CREATE TABLE IF NOT EXISTS sentencing_guidelines (
    id SERIAL PRIMARY KEY,
    crime_category VARCHAR(256) NOT NULL,
    crime_subcategory VARCHAR(256),
    sentencing_range VARCHAR(128),
    aggravating_factors TEXT,
    mitigating_factors TEXT,
    typical_penalty TEXT,
    legal_basis TEXT,
    source_document VARCHAR(512),
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sentencing_category ON sentencing_guidelines(crime_category);
CREATE INDEX IF NOT EXISTS idx_sentencing_embedding ON sentencing_guidelines USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- 审判流程 / 程序规则
CREATE TABLE IF NOT EXISTS trial_procedures (
    id SERIAL PRIMARY KEY,
    procedure_type VARCHAR(128) NOT NULL,
    procedure_name VARCHAR(256) NOT NULL,
    stage VARCHAR(64),
    description TEXT,
    time_limit VARCHAR(128),
    legal_basis TEXT,
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_procedures_type ON trial_procedures(procedure_type);
CREATE INDEX IF NOT EXISTS idx_procedures_embedding ON trial_procedures USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
