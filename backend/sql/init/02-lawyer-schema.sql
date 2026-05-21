\c lawyer_db

CREATE EXTENSION IF NOT EXISTS vector;

-- 辩护策略 / 代理词
CREATE TABLE IF NOT EXISTS defense_strategies (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(256) NOT NULL,
    case_type VARCHAR(128),
    applicable_scenario TEXT,
    argument_template TEXT,
    evidence_requirements TEXT,
    success_rate VARCHAR(32),
    reference_cases TEXT,
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_defense_strategy_type ON defense_strategies(case_type);
CREATE INDEX IF NOT EXISTS idx_defense_strategy_embedding ON defense_strategies USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- 证据规则 / 举证指引
CREATE TABLE IF NOT EXISTS evidence_rules (
    id SERIAL PRIMARY KEY,
    rule_name VARCHAR(256) NOT NULL,
    evidence_type VARCHAR(128),
    admissibility_criteria TEXT,
    burden_of_proof TEXT,
    exclusion_rules TEXT,
    legal_basis TEXT,
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_rules_type ON evidence_rules(evidence_type);
CREATE INDEX IF NOT EXISTS idx_evidence_rules_embedding ON evidence_rules USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- 合同审查模板
CREATE TABLE IF NOT EXISTS contract_review_templates (
    id SERIAL PRIMARY KEY,
    contract_type VARCHAR(128) NOT NULL,
    contract_subtype VARCHAR(128),
    clause_category VARCHAR(128),
    risk_level VARCHAR(16),
    review_checkpoint TEXT,
    suggested_wording TEXT,
    legal_basis TEXT,
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contract_review_type ON contract_review_templates(contract_type);
CREATE INDEX IF NOT EXISTS idx_contract_review_risk ON contract_review_templates(risk_level);
CREATE INDEX IF NOT EXISTS idx_contract_review_embedding ON contract_review_templates USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- 代理词 / 法律意见书模板
CREATE TABLE IF NOT EXISTS legal_opinions (
    id SERIAL PRIMARY KEY,
    opinion_type VARCHAR(128) NOT NULL,
    case_type VARCHAR(128),
    title VARCHAR(512),
    content TEXT NOT NULL,
    key_arguments TEXT,
    embedding vector(1024),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_legal_opinions_type ON legal_opinions(opinion_type);
CREATE INDEX IF NOT EXISTS idx_legal_opinions_embedding ON legal_opinions USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
