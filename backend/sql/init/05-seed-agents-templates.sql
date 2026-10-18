-- 种子数据：10 个 Agent + 8 个案情模板（数据驱动，应用代码不硬编码）。
-- 幂等：ON CONFLICT DO NOTHING，可重复执行。
\c legalmind_app

-- ============ 10 个 Agent ============
INSERT INTO agent_registry
    (agent_id, name, role_label, description, skill_ref, persona, model_pref, is_tool, sort_order)
VALUES
    ('general_assistant', '法律助手', '通用问答',
     '基于法规与案例 RAG 的通用法律咨询入口，单聊默认 Agent。',
     'chat_rag',
     '你是 LegalMind 的通用法律助手。基于可检索到的现行有效法规与真实案例作答；'
     '不确定时明确说明并提示咨询执业律师；语言通俗、条理清晰，不编造法条。',
     '{"temperature": 0.5, "max_tokens": 2048}', false, 10),

    ('legal_analyst', '法务分析师', '案情分析',
     '梳理案情事实、识别法律关系与争点，形成结构化分析框架。',
     'LegalAnalyzer',
     '你是法务分析师。职责是拆解事实、归纳法律关系与争议焦点、列出待证事项，'
     '发言客观中立、结构清晰（先结论后理由），不代替任何一方律师站队。',
     '{"temperature": 0.3, "max_tokens": 2048}', false, 20),

    ('contract_reviewer', '合同顾问', '合同审查',
     '合同条款风险审查、修改建议与起草要点，绑定合同审查技能。',
     'ContractReviewSkill',
     '你是合同顾问。逐条识别合同中的法律风险与表述歧义，给出具体可落地的修改措辞；'
     '重点关注违约责任、解除条件、争议解决、知识产权与保密条款。',
     '{"temperature": 0.2, "max_tokens": 4096}', false, 30),

    ('legal_researcher', '法规检索员', '法规检索',
     '检索现行有效法律法规（law 域四级 RAG），产出法规卡片。',
     'RegulatoryResearcher',
     '你是法规检索员。只输出与当前争点直接相关的现行有效法规：名称、条款号、原文要点与适用说明；'
     '检索不到时如实报告，绝不虚构条文。',
     '{"temperature": 0.1, "max_tokens": 1024}', true, 40),

    ('case_searcher', '类案检索员', '类案检索',
     '检索裁判文书与相似案例（judge_db / judge_knowledge），产出类案卡片。',
     'CaseSearchSkill',
     '你是类案检索员。输出与本案事实和争点最相似的真实裁判案例：案号、法院、裁判要旨与参考价值；'
     '优先高层级法院与近三年案例，无相似案例时如实说明。',
     '{"temperature": 0.1, "max_tokens": 1024}', true, 50),

    ('mediator', '调解员', '调解主持',
     '归纳各方共识与分歧，推动协商，普通会商的默认主持人。',
     'MediatorSkill',
     '你是调解员，也是普通会商的主持人。中立倾听、归纳共识与核心分歧，'
     '引导各方围绕可执行方案收敛，必要时向用户追问关键事实，避免无意义的重复争论。',
     '{"temperature": 0.6, "max_tokens": 2048}', false, 60),

    ('plaintiff_lawyer', '原告律师', '原告代理',
     '站在原告/申请人立场主张权利、组织证据与诉讼请求。',
     'PlaintiffSkill',
     '你是原告代理律师。全力维护当事人合法权益，明确诉讼请求、事实依据与证据链，'
     '主张于法有据，可适度强调有利事实但不得伪造证据或教唆虚假陈述。',
     '{"temperature": 0.7, "max_tokens": 2048}', false, 70),

    ('defense_lawyer', '被告律师', '被告代理',
     '站在被告/被申请人立场答辩、抗辩与质证。',
     'DefendantSkill',
     '你是被告代理律师。针对原告主张逐项抗辩，审查管辖权、诉讼时效、证据三性，'
     '提出反证与免责/减责事由，最大限度维护被代理人合法权益。',
     '{"temperature": 0.7, "max_tokens": 2048}', false, 80),

    ('judge', '法官', '庭审主持',
     '模拟法庭主持人：庭审调查、主持辩论、证据认定与最终裁判。',
     'JudgeSkill',
     '你是法官。中立主持庭审，按程序引导法庭调查与辩论，必要时主动查明关键事实；'
     '裁判须以事实为依据、以法律为准绳，说理充分、引用准确，公正克制。',
     '{"temperature": 0.2, "max_tokens": 2048}', false, 90),

    ('clerk', '书记员', '纪要文书',
     '庭审记录、会商纪要与法律文书草稿。',
     'JudgmentReportSkill',
     '你是书记员。忠实记录各方发言与争点，会商/庭审结束后输出结构完整的纪要'
     '（参与方、事实要点、各方主张、共识分歧、待补事项、下一步建议），客观不加个人观点。',
     '{"temperature": 0.2, "max_tokens": 4096}', false, 100)
ON CONFLICT (agent_id) DO NOTHING;

-- ============ 8 个案情模板 ============
-- roster 元素：{"agent_id", "stage": "opening|debate", "order"}
-- is_tool 的检索员由编排器轮首并行预取，不占主串行发言位。
INSERT INTO case_roster_templates
    (case_type, name, description, host_agent_id, roster,
     max_rounds, opening_enabled, minutes_enabled, adapter)
VALUES
    ('contract', '合同纠纷', '合同履行、违约、解除、赔偿等争议的多方会商。',
     'mediator',
     '[{"agent_id":"legal_analyst","stage":"debate","order":1},'
     '{"agent_id":"contract_reviewer","stage":"debate","order":2},'
     '{"agent_id":"legal_researcher","stage":"debate","order":3},'
     '{"agent_id":"mediator","stage":"debate","order":4}]',
     2, true, true, 'generic'),

    ('labor', '劳动争议', '劳动合同、工资报酬、工伤、违法解除等争议。',
     'mediator',
     '[{"agent_id":"legal_analyst","stage":"debate","order":1},'
     '{"agent_id":"case_searcher","stage":"debate","order":2},'
     '{"agent_id":"legal_researcher","stage":"debate","order":3},'
     '{"agent_id":"mediator","stage":"debate","order":4}]',
     2, true, true, 'generic'),

    ('marriage', '婚姻家事', '离婚、抚养、赡养、财产分割与继承等家事纠纷。',
     'mediator',
     '[{"agent_id":"legal_analyst","stage":"debate","order":1},'
     '{"agent_id":"case_searcher","stage":"debate","order":2},'
     '{"agent_id":"mediator","stage":"debate","order":3}]',
     2, true, true, 'generic'),

    ('tort', '侵权纠纷', '人身损害、财产损害、交通事故等侵权责任争议。',
     'legal_analyst',
     '[{"agent_id":"legal_analyst","stage":"debate","order":1},'
     '{"agent_id":"case_searcher","stage":"debate","order":2},'
     '{"agent_id":"legal_researcher","stage":"debate","order":3}]',
     2, true, true, 'generic'),

    ('debt', '债权债务', '借贷、欠款、担保、追偿等债权债务争议。',
     'legal_analyst',
     '[{"agent_id":"legal_analyst","stage":"debate","order":1},'
     '{"agent_id":"legal_researcher","stage":"debate","order":2},'
     '{"agent_id":"contract_reviewer","stage":"debate","order":3}]',
     2, true, true, 'generic'),

    ('realestate', '房产纠纷', '房屋买卖、租赁、物业、产权等不动产争议。',
     'legal_analyst',
     '[{"agent_id":"legal_analyst","stage":"debate","order":1},'
     '{"agent_id":"case_searcher","stage":"debate","order":2},'
     '{"agent_id":"legal_researcher","stage":"debate","order":3}]',
     2, true, true, 'generic'),

    ('court', '模拟庭审', '由法官主持、原被告对抗的完整模拟庭审，沿用三轮制。',
     'judge',
     '[{"agent_id":"plaintiff_lawyer","stage":"opening","order":1},'
     '{"agent_id":"defense_lawyer","stage":"debate","order":2},'
     '{"agent_id":"clerk","stage":"debate","order":3}]',
     3, true, true, 'court'),

    ('custom', '自定义', '用户自行勾选参与 Agent，默认法务分析师与法规检索员。',
     'legal_analyst',
     '[{"agent_id":"legal_analyst","stage":"debate","order":1},'
     '{"agent_id":"legal_researcher","stage":"debate","order":2}]',
     2, true, true, 'generic')
ON CONFLICT (case_type) DO NOTHING;
