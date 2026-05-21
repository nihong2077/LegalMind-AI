from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

JUDGMENT_REPORT_SYSTEM_PROMPT = """你是一位专业的法律文书撰写人，擅长根据法官裁决意见生成正式的判决书。你的职责包括：

1. **格式规范**：严格按照中国民事判决书格式撰写
2. **事实归纳**：准确归纳案件基本事实和审理经过
3. **理由阐述**：清晰阐述判决理由和法律依据
4. **判决主文**：明确判决结果，包括责任认定、赔偿金额、履行期限等
5. **权利告知**：告知当事人上诉权利和期限

判决书结构要求：
- 首部：法院名称、文书种类、案号、当事人信息
- 事实部分：原告诉称、被告辩称、审理查明的事实
- 理由部分：判决理由和法律依据
- 判决主文：具体的判决结果
- 尾部：上诉权利告知、审判人员署名、日期

请严格遵循中国民事判决书格式规范，确保文书的法律效力。"""


class JudgmentReportSkill:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.system_prompt = JUDGMENT_REPORT_SYSTEM_PROMPT

    async def generate_judgment(
        self,
        verdict: str,
        case_info: dict,
        plaintiff_args: list[str],
        defendant_args: list[str],
    ) -> str:
        """根据法官裁决意见生成正式判决书"""
        plaintiff_summary = "\n".join(plaintiff_args[-2:]) if plaintiff_args else "（无）"
        defendant_summary = "\n".join(defendant_args[-2:]) if defendant_args else "（无）"

        prompt = f"""请根据以下信息生成正式的民事判决书。

案件信息：
- 案由：{case_info.get('case_type', '合同纠纷')}
- 原告：{case_info.get('plaintiff_name', '原告')}
- 被告：{case_info.get('defendant_name', '被告')}

原告诉称摘要：
{plaintiff_summary}

被告辩称摘要：
{defendant_summary}

法官裁决意见：
{verdict}

请按照中国民事判决书标准格式，生成完整的判决书，包括：
1. 首部（法院名称、案号、当事人信息）
2. 原告诉称和被告辩称的归纳
3. 审理查明的事实
4. 判决理由和法律依据
5. 判决主文（具体判决结果）
6. 上诉权利告知和尾部"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def generate_mediation_agreement(
        self,
        mediation_result: str,
        case_info: dict,
    ) -> str:
        """根据调解结果生成调解协议书"""
        prompt = f"""请根据以下信息生成正式的调解协议书。

案件信息：
- 案由：{case_info.get('case_type', '合同纠纷')}
- 申请人：{case_info.get('plaintiff_name', '申请人')}
- 被申请人：{case_info.get('defendant_name', '被申请人')}

调解结果：
{mediation_result}

请按照调解协议书标准格式，生成完整的调解协议，包括：
1. 当事人信息
2. 纠纷事实和争议焦点
3. 调解达成的协议内容
4. 履行方式、期限和违约责任
5. 协议生效条款"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    async def generate_judgment_stream(
        self,
        verdict: str,
        case_info: dict,
        plaintiff_args: list[str],
        defendant_args: list[str],
    ):
        plaintiff_summary = "\n".join(plaintiff_args[-2:]) if plaintiff_args else "（无）"
        defendant_summary = "\n".join(defendant_args[-2:]) if defendant_args else "（无）"

        prompt = f"""请根据以下信息生成正式的民事判决书。

案件信息：
- 案由：{case_info.get('case_type', '合同纠纷')}
- 原告：{case_info.get('plaintiff_name', '原告')}
- 被告：{case_info.get('defendant_name', '被告')}

原告诉称摘要：
{plaintiff_summary}

被告辩称摘要：
{defendant_summary}

法官裁决意见：
{verdict}

请按照中国民事判决书标准格式，生成完整的判决书，包括：
1. 首部（法院名称、案号、当事人信息）
2. 原告诉称和被告辩称的归纳
3. 审理查明的事实
4. 判决理由和法律依据
5. 判决主文（具体判决结果）
6. 上诉权利告知和尾部"""
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
