"""
Zep检索工具服务
封装图谱搜索、节点读取、边查询等工具，供Report Agent使用

核心检索工具（优化后）：
1. InsightForge（深度洞察检索）- 最强大的混合检索，自动生成子问题并多维度检索
2. PanoramaSearch（广度搜索）- 获取全貌，包括过期内容
3. QuickSearch（简单搜索）- 快速检索
"""

import re
import time
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from zep_cloud import NotFoundError

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.locale import get_locale, language_instruction_for, normalize_lang, t
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.zep import (
    call_zep_read_with_retry,
    get_zep_client,
    normalize_zep_search_limit,
    normalize_zep_search_query,
)
from .language_guard import (
    LANGUAGE_NAMES,
    ensure_language,
    ensure_language_many,
    foreign_script,
    record_language,
)

logger = get_logger('mirofish.zep_tools')


# ── The words of the tools' texts ──
#
# The Scribe reads these texts and the agent log keeps them, so they are
# written in the record's language: the upstream Chinese for a Chinese
# record (report_agent's _OBSERVATION_LABELS relabels those), English for
# every other. A text's language is the one its result carries, else the
# thread's (the report's worker sets it to the record's).
_WORDS = {
    'zh': {
        'search_query': '搜索查询: {query}',
        'search_found': '找到 {count} 条相关信息',
        'search_facts': '\n### 相关事实:',
        'unknown_type': '未知类型',
        'node': '实体: {name} (类型: {type})\n摘要: {summary}',
        'edge': '关系: {source} --[{name}]--> {target}\n事实: {fact}',
        'unknown': '未知',
        'until_now': '至今',
        'valid': '\n时效: {start} - {end}',
        'expired': ' (已过期: {at})',
        'entity': '实体',
        'forge_heading': '## 未来预测深度分析',
        'forge_query': '分析问题: {query}',
        'forge_scene': '预测场景: {requirement}',
        'forge_stats': '\n### 预测数据统计',
        'forge_facts_count': '- 相关预测事实: {n}条',
        'forge_entities_count': '- 涉及实体: {n}个',
        'forge_chains_count': '- 关系链: {n}条',
        'forge_sub': '\n### 分析的子问题',
        'forge_key_facts': '\n### 【关键事实】(请在报告中引用这些原文)',
        'forge_entities': '\n### 【核心实体】',
        'forge_summary': '  摘要: "{summary}"',
        'forge_related': '  相关事实: {n}条',
        'forge_chains': '\n### 【关系链】',
        'panorama_heading': '## 广度搜索结果（未来全景视图）',
        'panorama_query': '查询: {query}',
        'panorama_stats': '\n### 统计信息',
        'panorama_nodes': '- 总节点数: {n}',
        'panorama_edges': '- 总边数: {n}',
        'panorama_active_count': '- 当前有效事实: {n}条',
        'panorama_historical_count': '- 历史/过期事实: {n}条',
        'panorama_active': '\n### 【当前有效事实】(模拟结果原文)',
        'panorama_historical': '\n### 【历史/过期事实】(演变过程记录)',
        'panorama_entities': '\n### 【涉及实体】',
        'bio': '_简介: {bio}_\n\n',
        'key_quotes': '\n**关键引言:**\n',
        'interview_heading': '## 深度采访报告',
        'interview_topic': '**采访主题:** {topic}',
        'interview_count': '**采访人数:** {done} / {total} 位模拟Agent',
        'interview_why': '\n### 采访对象选择理由',
        'interview_auto': '（自动选择）',
        'interview_record': '\n### 采访实录',
        'interview_one': '\n#### 采访 #{index}: {name}',
        'interview_none': '（无采访记录）\n\n---',
        'interview_summary': '\n### 采访摘要与核心观点',
        'interview_no_summary': '（无摘要）',
        'on_twitter': '【Twitter平台回答】',
        'on_reddit': '【Reddit平台回答】',
        'no_answer': '（该平台未获得回复）',
        'no_profiles': '未找到可采访的Agent人设文件',
        'unknown_error': '未知错误',
        'api_failed': '采访API调用失败：{error}。请检查OASIS模拟环境状态。',
        'env_closed': '采访失败：{error}。模拟环境可能已关闭，请确保OASIS环境正在运行。',
        'interview_error': '采访过程发生错误：{error}',
        'error_unreadable': '模拟环境没有回应',
        'timed_out': '模拟环境未在规定时间内回应',
        'chose_by_relevance': '基于相关性自动选择',
        'chose_by_default': '使用默认选择策略',
        'not_given': '未提供',
        'no_interviews': '未完成任何采访',
        'summary_fallback': '共采访了{n}位受访者，包括：{names}',
        'names_joiner': '、',
        'summary_item': '【{name}（{role}）】\n{answer}',
        'quote_marks': '引用受访者原话时使用中文引号「」',
    },
    'en': {
        'search_query': 'Search query: {query}',
        'search_found': 'Found {count} related items',
        'search_facts': '\n### Related facts:',
        'unknown_type': 'unknown type',
        'node': 'Entity: {name} (type: {type})\nSummary: {summary}',
        'edge': 'Relation: {source} --[{name}]--> {target}\nFact: {fact}',
        'unknown': 'unknown',
        'until_now': 'now',
        'valid': '\nHeld: {start} - {end}',
        'expired': ' (expired: {at})',
        'entity': 'entity',
        'forge_heading': '## Deep reading',
        'forge_query': 'Question: {query}',
        'forge_scene': 'The question put to the city: {requirement}',
        'forge_stats': '\n### Counts',
        'forge_facts_count': '- Relevant facts: {n}',
        'forge_entities_count': '- Entities involved: {n}',
        'forge_chains_count': '- Relation chains: {n}',
        'forge_sub': '\n### Sub-questions analysed',
        'forge_key_facts': '\n### [Key facts] (the record\'s own words, to quote by name)',
        'forge_entities': '\n### [Core entities]',
        'forge_summary': '  Summary: "{summary}"',
        'forge_related': '  Related facts: {n}',
        'forge_chains': '\n### [Relation chains]',
        'panorama_heading': '## Panorama',
        'panorama_query': 'Query: {query}',
        'panorama_stats': '\n### Counts',
        'panorama_nodes': '- Entities: {n}',
        'panorama_edges': '- Relations: {n}',
        'panorama_active_count': '- Active facts: {n}',
        'panorama_historical_count': '- Earlier facts (expired or superseded): {n}',
        'panorama_active': '\n### [Active facts] (the record\'s own words)',
        'panorama_historical': '\n### [Earlier facts] (how it changed)',
        'panorama_entities': '\n### [Entities involved]',
        'bio': '_Bio: {bio}_\n\n',
        'key_quotes': '\n**Key quotes:**\n',
        'interview_heading': '## Interviews',
        'interview_topic': '**Topic:** {topic}',
        'interview_count': '**Interviewed:** {done} / {total} citizens',
        'interview_why': '\n### Why these citizens',
        'interview_auto': '(chosen automatically)',
        'interview_record': '\n### The interviews',
        'interview_one': '\n#### Interview #{index}: {name}',
        'interview_none': '(no interviews)\n\n---',
        'interview_summary': '\n### Summary and main views',
        'interview_no_summary': '(no summary)',
        'on_twitter': '[On Twitter]',
        'on_reddit': '[On Reddit]',
        'no_answer': '(no answer here)',
        'no_profiles': 'No roll of citizens was found to interview.',
        'unknown_error': 'unknown error',
        'api_failed': 'The interviews could not be held: {error}. Check that the square is still open.',
        'env_closed': (
            'The interviews failed: {error}. The square may have closed; citizens can be interviewed '
            'only while it is open.'
        ),
        'interview_error': 'The interviews ran into an error: {error}',
        'error_unreadable': 'the square did not answer',
        'timed_out': 'the square did not answer in time',
        'chose_by_relevance': 'Chosen by relevance to the topic.',
        'chose_by_default': 'The first citizens on the roll (the default choice).',
        'not_given': 'Not given',
        'no_interviews': 'No interviews were completed.',
        'summary_fallback': 'Interviewed {n} citizens: {names}',
        'names_joiner': ', ',
        'summary_item': '[{name} ({role})]\n{answer}',
        'quote_marks': 'Use quotation marks "" when quoting interviewees',
    },
}


def _lang_of(language: Optional[str] = None) -> str:
    """'en' or 'zh': the language given, else this thread's or request's."""

    return normalize_lang(language) if language else get_locale()


def _w(lang: Optional[str], key: str, **kwargs) -> str:
    """One of the tools' texts in a reading language (anything but Chinese reads English)."""

    words = _WORDS['zh' if normalize_lang(lang) == 'zh' else 'en'][key]
    return words.format(**kwargs) if kwargs else words


def _said(error: Any, lang: str) -> str:
    """An error's own words for a text in lang: a message in another script is not passed on."""

    if isinstance(error, TimeoutError):
        return _w(lang, 'timed_out')  # the IPC's own words are the log's, in English
    text = str(error or '').strip() or type(error).__name__
    return _w(lang, 'error_unreadable') if foreign_script(text, lang) else text


# ── Interviews made for the Chronicle ──
#
# The citizens are interviewed in the record's language: the prefix asks for
# it, and whatever still comes back in another script is translated before
# the Scribe reads it (she quotes these answers into the Chronicle).
INTERVIEW_PREFIX_ZH = (
    "你正在接受一次采访。请结合你的人设、所有的过往记忆与行动，"
    "以纯文本方式直接回答以下问题。\n"
    "回复要求：\n"
    "1. 直接用自然语言回答，不要调用任何工具\n"
    "2. 不要返回JSON格式或工具调用格式\n"
    "3. 不要使用Markdown标题（如#、##、###）\n"
    "4. 按问题编号逐一回答，每个回答以「问题X：」开头（X为问题编号）\n"
    "5. 每个问题的回答之间用空行分隔\n"
    "6. 回答要有实质内容，每个问题至少回答2-3句话\n\n"
)
INTERVIEW_PREFIX_EN = (
    "You are being interviewed. Drawing on your persona and all your past memories and actions, "
    "answer the questions below directly, in plain text.\n"
    "How to answer:\n"
    "1. Answer in natural language; do not call any tools\n"
    "2. Do not answer in JSON or in a tool-call format\n"
    "3. Do not use Markdown headings (such as #, ##, ###)\n"
    "4. Answer the questions in order, starting each answer with \"Question X:\" (X is the question's number)\n"
    "5. Leave a blank line between answers\n"
    "6. Give each answer substance: at least 2-3 sentences for every question\n"
    "7. Answer in English, even where a question or your own memories are in another language\n"
    + language_instruction_for('en') + "\n\n"
)


def interview_prefix(lang: Optional[str]) -> str:
    """The prefix of an interview for the Chronicle, in the record's language."""

    return INTERVIEW_PREFIX_ZH if normalize_lang(lang) == 'zh' else INTERVIEW_PREFIX_EN


# What is not a quotable sentence in an answer: headings, tool calls, markup
# runs, the answers' own numbering and the platforms' labels.
_QUOTE_NOISE = (
    re.compile(r'#{1,6}\s+'),
    re.compile(r'\{[^}]*tool_name[^}]*\}'),
    re.compile(r'[*_`|>~\-]{2,}'),
    re.compile(r'(?:问题\s*\d+|Question\s*\d+|Q\s*\d+)\s*[：:.)]\s*', re.I),
    re.compile(r'【[^】]+】|\[On (?:Twitter|Reddit)\]', re.I),
)
# A Chinese sentence ends with its own mark; any other at a stop and a space.
_SENTENCE_BREAK = {
    'zh': re.compile(r'(?<=[。！？])'),
    'en': re.compile(r'(?<=[.!?])\s+|(?<=[。！？])'),
}
# The length of a key quote: a Chinese character carries about three English ones.
QUOTE_LENGTHS = {'zh': (20, 150), 'en': (40, 300)}
_ZH_SENTENCE_END = '。！？'


def extract_key_quotes(responses: List[str], lang: Optional[str], limit: int = 3) -> List[str]:
    """Up to limit whole sentences worth quoting from a citizen's answers, in the answers' own words.

    Sentences are cut where the language ends them (a Chinese sentence at
    。！？, any other at . ! or ? and a space); a sentence keeps its own
    closing mark and none is added to it, except a Chinese one left without.
    For a target other than Chinese a sentence in another script is never kept.
    """

    lang = 'zh' if normalize_lang(lang) == 'zh' else 'en'
    text = ' '.join(r for r in responses if isinstance(r, str) and r)
    for pattern in _QUOTE_NOISE:
        text = pattern.sub('', text)
    low, high = QUOTE_LENGTHS[lang]
    sentences = [s.strip() for s in _SENTENCE_BREAK[lang].split(text)]
    meaningful = [
        s for s in sentences
        if low <= len(s) <= high
        and not re.match(r'^[\s\W，,；;：:、]+', s)
        and not s.startswith(('{', '问题', 'Question'))
        and not foreign_script(s, lang)
    ]
    meaningful = list(dict.fromkeys(meaningful))  # both squares may have heard the same words
    meaningful.sort(key=len, reverse=True)
    quotes = [
        s + '。' if lang == 'zh' and s[-1] not in _ZH_SENTENCE_END else s
        for s in meaningful[:limit]
    ]
    if not quotes:
        # Words the citizen set in quotation marks.
        paired = re.findall(r'\u201c([^\u201c\u201d]{15,100})\u201d', text)
        paired += re.findall(r'\u300c([^\u300c\u300d]{15,100})\u300d', text)
        quotes = [
            q for q in paired
            if not re.match(r'^[，,；;：:、]', q) and not foreign_script(q, lang)
        ][:limit]
    return quotes


@dataclass
class SearchResult:
    """搜索结果"""
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int
    # The language of to_text(): None reads in the thread's.
    language: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count
        }
    
    def to_text(self) -> str:
        """转换为文本格式，供LLM理解"""
        lang = _lang_of(self.language)
        text_parts = [_w(lang, 'search_query', query=self.query), _w(lang, 'search_found', count=self.total_count)]
        
        if self.facts:
            text_parts.append(_w(lang, 'search_facts'))
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")
        
        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    """节点信息"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes
        }
    
    def to_text(self, language: Optional[str] = None) -> str:
        """转换为文本格式"""
        lang = _lang_of(language)
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), _w(lang, 'unknown_type'))
        return _w(lang, 'node', name=self.name, type=entity_type, summary=self.summary)


@dataclass
class EdgeInfo:
    """边信息"""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    # 时间信息
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at
        }
    
    def to_text(self, include_temporal: bool = False, language: Optional[str] = None) -> str:
        """转换为文本格式"""
        lang = _lang_of(language)
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = _w(lang, 'edge', source=source, name=self.name, target=target, fact=self.fact)
        
        if include_temporal:
            valid_at = self.valid_at or _w(lang, 'unknown')
            invalid_at = self.invalid_at or _w(lang, 'until_now')
            base_text += _w(lang, 'valid', start=valid_at, end=invalid_at)
            if self.expired_at:
                base_text += _w(lang, 'expired', at=self.expired_at)
        
        return base_text
    
    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        return self.expired_at is not None
    
    @property
    def is_invalid(self) -> bool:
        """是否已失效"""
        return self.invalid_at is not None


@dataclass
class InsightForgeResult:
    """
    深度洞察检索结果 (InsightForge)
    包含多个子问题的检索结果，以及综合分析
    """
    query: str
    simulation_requirement: str
    sub_queries: List[str]
    
    # 各维度检索结果
    semantic_facts: List[str] = field(default_factory=list)  # 语义搜索结果
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)  # 实体洞察
    relationship_chains: List[str] = field(default_factory=list)  # 关系链
    
    # 统计信息
    total_facts: int = 0
    total_entities: int = 0
    total_relationships: int = 0
    # The language of to_text(): None reads in the thread's.
    language: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "simulation_requirement": self.simulation_requirement,
            "sub_queries": self.sub_queries,
            "semantic_facts": self.semantic_facts,
            "entity_insights": self.entity_insights,
            "relationship_chains": self.relationship_chains,
            "total_facts": self.total_facts,
            "total_entities": self.total_entities,
            "total_relationships": self.total_relationships
        }
    
    def to_text(self) -> str:
        """转换为详细的文本格式，供LLM理解"""
        lang = _lang_of(self.language)
        text_parts = [
            _w(lang, 'forge_heading'),
            _w(lang, 'forge_query', query=self.query),
            _w(lang, 'forge_scene', requirement=self.simulation_requirement),
            _w(lang, 'forge_stats'),
            _w(lang, 'forge_facts_count', n=self.total_facts),
            _w(lang, 'forge_entities_count', n=self.total_entities),
            _w(lang, 'forge_chains_count', n=self.total_relationships),
        ]
        
        # 子问题
        if self.sub_queries:
            text_parts.append(_w(lang, 'forge_sub'))
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")
        
        # 语义搜索结果
        if self.semantic_facts:
            text_parts.append(_w(lang, 'forge_key_facts'))
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # 实体洞察
        if self.entity_insights:
            text_parts.append(_w(lang, 'forge_entities'))
            for entity in self.entity_insights:
                name = entity.get('name', _w(lang, 'unknown'))
                text_parts.append(f"- **{name}** ({entity.get('type', _w(lang, 'entity'))})")
                if entity.get('summary'):
                    text_parts.append(_w(lang, 'forge_summary', summary=entity.get('summary')))
                if entity.get('related_facts'):
                    text_parts.append(_w(lang, 'forge_related', n=len(entity.get('related_facts', []))))
        
        # 关系链
        if self.relationship_chains:
            text_parts.append(_w(lang, 'forge_chains'))
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")
        
        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    """
    广度搜索结果 (Panorama)
    包含所有相关信息，包括过期内容
    """
    query: str
    
    # 全部节点
    all_nodes: List[NodeInfo] = field(default_factory=list)
    # 全部边（包括过期的）
    all_edges: List[EdgeInfo] = field(default_factory=list)
    # 当前有效的事实
    active_facts: List[str] = field(default_factory=list)
    # 已过期/失效的事实（历史记录）
    historical_facts: List[str] = field(default_factory=list)
    
    # 统计
    total_nodes: int = 0
    total_edges: int = 0
    active_count: int = 0
    historical_count: int = 0
    # The language of to_text(): None reads in the thread's.
    language: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "all_nodes": [n.to_dict() for n in self.all_nodes],
            "all_edges": [e.to_dict() for e in self.all_edges],
            "active_facts": self.active_facts,
            "historical_facts": self.historical_facts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "active_count": self.active_count,
            "historical_count": self.historical_count
        }
    
    def to_text(self) -> str:
        """转换为文本格式（完整版本，不截断）"""
        lang = _lang_of(self.language)
        text_parts = [
            _w(lang, 'panorama_heading'),
            _w(lang, 'panorama_query', query=self.query),
            _w(lang, 'panorama_stats'),
            _w(lang, 'panorama_nodes', n=self.total_nodes),
            _w(lang, 'panorama_edges', n=self.total_edges),
            _w(lang, 'panorama_active_count', n=self.active_count),
            _w(lang, 'panorama_historical_count', n=self.historical_count),
        ]
        
        # 当前有效的事实（完整输出，不截断）
        if self.active_facts:
            text_parts.append(_w(lang, 'panorama_active'))
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # 历史/过期事实（完整输出，不截断）
        if self.historical_facts:
            text_parts.append(_w(lang, 'panorama_historical'))
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # 关键实体（完整输出，不截断）
        if self.all_nodes:
            text_parts.append(_w(lang, 'panorama_entities'))
            for node in self.all_nodes:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), _w(lang, 'entity'))
                text_parts.append(f"- **{node.name}** ({entity_type})")
        
        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    """单个Agent的采访结果"""
    agent_name: str
    agent_role: str  # 角色类型（如：学生、教师、媒体等）
    agent_bio: str  # 简介
    question: str  # 采访问题
    response: str  # 采访回答
    key_quotes: List[str] = field(default_factory=list)  # 关键引言
    # The language of to_text(): None reads in the thread's.
    language: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes
        }
    
    def to_text(self, language: Optional[str] = None) -> str:
        lang = _lang_of(language or self.language)
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        # 显示完整的agent_bio，不截断
        text += _w(lang, 'bio', bio=self.agent_bio)
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += _w(lang, 'key_quotes')
            for quote in self.key_quotes:
                clean_quote = _quotable(quote, lang)
                if clean_quote and len(clean_quote) >= 10:
                    text += f'> "{clean_quote}"\n'
        return text


# A quote's own numbering ("问题1", "Question 1") marks the answer's scaffolding, not its words.
_NUMBERED = re.compile(r'\u95ee\u9898[1-9]|\bQuestion\s*[1-9]', re.I)


def _quotable(quote: str, lang: str) -> str:
    """A key quote as the Scribe is shown it: no quotation marks or leading marks, not too long; '' to skip."""

    # 清理各种引号
    clean_quote = quote.replace('\u201c', '').replace('\u201d', '').replace('"', '')
    clean_quote = clean_quote.replace('\u300c', '').replace('\u300d', '')
    clean_quote = clean_quote.strip()
    # 去掉开头的标点
    while clean_quote and clean_quote[0] in '，,；;：:、。！？.!?\n\r\t ':
        clean_quote = clean_quote[1:]
    # 过滤包含问题编号的垃圾内容
    if _NUMBERED.search(clean_quote):
        return ''
    # 截断过长内容（按句号截断，而非硬截断）
    if normalize_lang(lang) == 'zh':
        if len(clean_quote) > 150:
            dot_pos = clean_quote.find('\u3002', 80)
            if dot_pos > 0:
                clean_quote = clean_quote[:dot_pos + 1]
            else:
                clean_quote = clean_quote[:147] + "..."
    elif len(clean_quote) > 300:
        stop = max(clean_quote.rfind(mark, 160, 300) for mark in ('. ', '! ', '? '))
        if stop > 0:
            clean_quote = clean_quote[:stop + 1]
        else:
            clean_quote = clean_quote[:297].rsplit(' ', 1)[0] + "..."
    return clean_quote


@dataclass
class InterviewResult:
    """
    采访结果 (Interview)
    包含多个模拟Agent的采访回答
    """
    interview_topic: str  # 采访主题
    interview_questions: List[str]  # 采访问题列表
    
    # 采访选择的Agent
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    # 各Agent的采访回答
    interviews: List[AgentInterview] = field(default_factory=list)
    
    # 选择Agent的理由
    selection_reasoning: str = ""
    # 整合后的采访摘要
    summary: str = ""
    
    # 统计
    total_agents: int = 0
    interviewed_count: int = 0
    # The record's language: to_text() and the interviews are in it (None reads in the thread's).
    language: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count
        }
    
    def to_text(self) -> str:
        """转换为详细的文本格式，供LLM理解和报告引用"""
        lang = _lang_of(self.language)
        text_parts = [
            _w(lang, 'interview_heading'),
            _w(lang, 'interview_topic', topic=self.interview_topic),
            _w(lang, 'interview_count', done=self.interviewed_count, total=self.total_agents),
            _w(lang, 'interview_why'),
            self.selection_reasoning or _w(lang, 'interview_auto'),
            "\n---",
            _w(lang, 'interview_record'),
        ]

        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(_w(lang, 'interview_one', index=i, name=interview.agent_name))
                text_parts.append(interview.to_text(lang))
                text_parts.append("\n---")
        else:
            text_parts.append(_w(lang, 'interview_none'))

        text_parts.append(_w(lang, 'interview_summary'))
        text_parts.append(self.summary or _w(lang, 'interview_no_summary'))

        return "\n".join(text_parts)


class ZepToolsService:
    """
    Zep检索工具服务
    
    【核心检索工具 - 优化后】
    1. insight_forge - 深度洞察检索（最强大，自动生成子问题，多维度检索）
    2. panorama_search - 广度搜索（获取全貌，包括过期内容）
    3. quick_search - 简单搜索（快速检索）
    4. interview_agents - 深度采访（采访模拟Agent，获取多视角观点）
    
    【基础工具】
    - search_graph - 图谱语义搜索
    - get_all_nodes - 获取图谱所有节点
    - get_all_edges - 获取图谱所有边（含时间信息）
    - get_node_detail - 获取节点详细信息
    - get_node_edges - 获取节点相关的边
    - get_entities_by_type - 按类型获取实体
    - get_entity_summary - 获取实体的关系摘要
    """
    
    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    
    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None,
                 translator: Any = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key and Config.memory_backend(self.api_key) == "zep":
            raise ValueError("ZEP_API_KEY is not set")
        
        self.client = get_zep_client(self.api_key)
        # LLM客户端用于InsightForge生成子问题
        self._llm_client = llm_client
        # The language guard's model (None: language_guard's default translator).
        self._translator = translator
        logger.info(t("console.zepToolsInitialized"))

    def _guard(self, texts: List[Any], lang: str, context: str) -> List[Any]:
        """texts in lang (language_guard.ensure_language_many): one translate call at most, never raises."""

        return ensure_language_many(texts, lang, llm=getattr(self, '_translator', None), context=context)
    
    @property
    def llm(self) -> LLMClient:
        """延迟初始化LLM客户端"""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client
    
    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """Retry one safe read using typed Zep/HTTPX error classification."""

        return call_zep_read_with_retry(
            func,
            operation_name=operation_name,
            max_attempts=max_retries or self.MAX_RETRIES,
            initial_delay=self.RETRY_DELAY,
        )
    
    def search_graph(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        图谱语义搜索
        
        使用混合搜索（语义+BM25）在图谱中搜索相关信息。
        如果Zep Cloud的search API不可用，则降级为本地关键词匹配。
        
        Args:
            graph_id: 图谱ID (Standalone Graph)
            query: 搜索查询
            limit: 返回结果数量
            scope: 搜索范围，"edges" 或 "nodes"
            
        Returns:
            SearchResult: 搜索结果
        """
        logger.info(t("console.graphSearch", graphId=graph_id, query=query[:50]))
        
        zep_query = normalize_zep_search_query(query)
        zep_limit = normalize_zep_search_limit(limit)

        try:
            search_results = self._call_with_retry(
                func=lambda: self.client.graph.search(
                    graph_id=graph_id,
                    query=zep_query,
                    limit=zep_limit,
                    scope=scope,
                    reranker="cross_encoder"
                ),
                operation_name=t("console.graphSearchOp", graphId=graph_id)
            )
            
            facts = []
            edges = []
            nodes = []
            
            # 解析边搜索结果
            if hasattr(search_results, 'edges') and search_results.edges:
                for edge in search_results.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        facts.append(edge.fact)
                    edges.append({
                        "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                        "name": getattr(edge, 'name', ''),
                        "fact": getattr(edge, 'fact', ''),
                        "source_node_uuid": getattr(edge, 'source_node_uuid', ''),
                        "target_node_uuid": getattr(edge, 'target_node_uuid', ''),
                    })
            
            # 解析节点搜索结果
            if hasattr(search_results, 'nodes') and search_results.nodes:
                for node in search_results.nodes:
                    nodes.append({
                        "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                        "name": getattr(node, 'name', ''),
                        "labels": getattr(node, 'labels', []),
                        "summary": getattr(node, 'summary', ''),
                    })
                    # 节点摘要也算作事实
                    if hasattr(node, 'summary') and node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(t("console.searchComplete", count=len(facts)))
            
            return SearchResult(
                facts=facts,
                edges=edges,
                nodes=nodes,
                query=query,
                total_count=len(facts)
            )
            
        except Exception as e:
            # Authentication, invalid input, missing graphs, and exhausted
            # transient failures must remain visible to the report workflow.
            logger.error(t("console.zepSearchApiFallback", error=str(e)))
            raise
    
    def _local_search(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        本地关键词匹配搜索（作为Zep Search API的降级方案）
        
        获取所有边/节点，然后在本地进行关键词匹配
        
        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: 返回结果数量
            scope: 搜索范围
            
        Returns:
            SearchResult: 搜索结果
        """
        logger.info(t("console.usingLocalSearch", query=query[:30]))
        
        facts = []
        edges_result = []
        nodes_result = []
        
        # 提取查询关键词（简单分词）
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def match_score(text: str) -> int:
            """计算文本与查询的匹配分数"""
            if not text:
                return 0
            text_lower = text.lower()
            # 完全匹配查询
            if query_lower in text_lower:
                return 100
            # 关键词匹配
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 10
            return score
        
        try:
            if scope in ["edges", "both"]:
                # 获取所有边并匹配
                all_edges = self.get_all_edges(graph_id)
                scored_edges = []
                for edge in all_edges:
                    score = match_score(edge.fact) + match_score(edge.name)
                    if score > 0:
                        scored_edges.append((score, edge))
                
                # 按分数排序
                scored_edges.sort(key=lambda x: x[0], reverse=True)
                
                for score, edge in scored_edges[:limit]:
                    if edge.fact:
                        facts.append(edge.fact)
                    edges_result.append({
                        "uuid": edge.uuid,
                        "name": edge.name,
                        "fact": edge.fact,
                        "source_node_uuid": edge.source_node_uuid,
                        "target_node_uuid": edge.target_node_uuid,
                    })
            
            if scope in ["nodes", "both"]:
                # 获取所有节点并匹配
                all_nodes = self.get_all_nodes(graph_id)
                scored_nodes = []
                for node in all_nodes:
                    score = match_score(node.name) + match_score(node.summary)
                    if score > 0:
                        scored_nodes.append((score, node))
                
                scored_nodes.sort(key=lambda x: x[0], reverse=True)
                
                for score, node in scored_nodes[:limit]:
                    nodes_result.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "labels": node.labels,
                        "summary": node.summary,
                    })
                    if node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(t("console.localSearchComplete", count=len(facts)))
            
        except Exception as e:
            logger.error(t("console.localSearchFailed", error=str(e)))
        
        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts)
        )
    
    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """
        获取图谱的所有节点（分页获取）

        Args:
            graph_id: 图谱ID

        Returns:
            节点列表
        """
        logger.info(t("console.fetchingAllNodes", graphId=graph_id))

        nodes = fetch_all_nodes(self.client, graph_id)

        result = []
        for node in nodes:
            node_uuid = getattr(node, 'uuid_', None) or getattr(node, 'uuid', None) or ""
            result.append(NodeInfo(
                uuid=str(node_uuid) if node_uuid else "",
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            ))

        logger.info(t("console.fetchedNodes", count=len(result)))
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """
        获取图谱的所有边（分页获取，包含时间信息）

        Args:
            graph_id: 图谱ID
            include_temporal: 是否包含时间信息（默认True）

        Returns:
            边列表（包含created_at, valid_at, invalid_at, expired_at）
        """
        logger.info(t("console.fetchingAllEdges", graphId=graph_id))

        edges = fetch_all_edges(self.client, graph_id)

        result = []
        for edge in edges:
            edge_uuid = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', None) or ""
            edge_info = EdgeInfo(
                uuid=str(edge_uuid) if edge_uuid else "",
                name=edge.name or "",
                fact=edge.fact or "",
                source_node_uuid=edge.source_node_uuid or "",
                target_node_uuid=edge.target_node_uuid or ""
            )

            # 添加时间信息
            if include_temporal:
                edge_info.created_at = getattr(edge, 'created_at', None)
                edge_info.valid_at = getattr(edge, 'valid_at', None)
                edge_info.invalid_at = getattr(edge, 'invalid_at', None)
                edge_info.expired_at = getattr(edge, 'expired_at', None)

            result.append(edge_info)

        logger.info(t("console.fetchedEdges", count=len(result)))
        return result
    
    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """
        获取单个节点的详细信息
        
        Args:
            node_uuid: 节点UUID
            
        Returns:
            节点信息或None
        """
        logger.info(t("console.fetchingNodeDetail", uuid=node_uuid[:8]))
        
        try:
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=node_uuid),
                operation_name=t("console.fetchNodeDetailOp", uuid=node_uuid[:8])
            )
            
            if not node:
                return None
            
            return NodeInfo(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            )
        except NotFoundError:
            return None
        except Exception as e:
            logger.error(t("console.fetchNodeDetailFailed", error=str(e)))
            raise
    
    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """
        获取节点相关的所有边
        
        通过获取图谱所有边，然后过滤出与指定节点相关的边
        
        Args:
            graph_id: 图谱ID
            node_uuid: 节点UUID
            
        Returns:
            边列表
        """
        logger.info(t("console.fetchingNodeEdges", uuid=node_uuid[:8]))
        
        try:
            # 获取图谱所有边，然后过滤
            all_edges = self.get_all_edges(graph_id)
            
            result = []
            for edge in all_edges:
                # 检查边是否与指定节点相关（作为源或目标）
                if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid:
                    result.append(edge)
            
            logger.info(t("console.foundNodeEdges", count=len(result)))
            return result
            
        except Exception as e:
            logger.error(t("console.fetchNodeEdgesFailed", error=str(e)))
            raise
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str
    ) -> List[NodeInfo]:
        """
        按类型获取实体
        
        Args:
            graph_id: 图谱ID
            entity_type: 实体类型（如 Student, PublicFigure 等）
            
        Returns:
            符合类型的实体列表
        """
        logger.info(t("console.fetchingEntitiesByType", type=entity_type))
        
        all_nodes = self.get_all_nodes(graph_id)
        
        filtered = []
        for node in all_nodes:
            # 检查labels是否包含指定类型
            if entity_type in node.labels:
                filtered.append(node)
        
        logger.info(t("console.foundEntitiesByType", count=len(filtered), type=entity_type))
        return filtered
    
    def get_entity_summary(
        self, 
        graph_id: str, 
        entity_name: str
    ) -> Dict[str, Any]:
        """
        获取指定实体的关系摘要
        
        搜索与该实体相关的所有信息，并生成摘要
        
        Args:
            graph_id: 图谱ID
            entity_name: 实体名称
            
        Returns:
            实体摘要信息
        """
        logger.info(t("console.fetchingEntitySummary", name=entity_name))
        
        # 先搜索该实体相关的信息
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )
        
        # 尝试在所有节点中找到该实体
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break
        
        related_edges = []
        if entity_node:
            # 传入graph_id参数
            related_edges = self.get_node_edges(graph_id, entity_node.uuid)
        
        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [e.to_dict() for e in related_edges],
            "total_relations": len(related_edges)
        }
    
    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        """
        获取图谱的统计信息
        
        Args:
            graph_id: 图谱ID
            
        Returns:
            统计信息
        """
        logger.info(t("console.fetchingGraphStats", graphId=graph_id))
        
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        
        # 统计实体类型分布
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1
        
        # 统计关系类型分布
        relation_types = {}
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1
        
        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types
        }
    
    def get_simulation_context(
        self, 
        graph_id: str,
        simulation_requirement: str,
        limit: int = 30
    ) -> Dict[str, Any]:
        """
        获取模拟相关的上下文信息
        
        综合搜索与模拟需求相关的所有信息
        
        Args:
            graph_id: 图谱ID
            simulation_requirement: 模拟需求描述
            limit: 每类信息的数量限制
            
        Returns:
            模拟上下文信息
        """
        logger.info(t("console.fetchingSimContext", requirement=simulation_requirement[:50]))
        
        # 搜索与模拟需求相关的信息
        search_result = self.search_graph(
            graph_id=graph_id,
            query=simulation_requirement,
            limit=limit
        )
        
        # 获取图谱统计
        stats = self.get_graph_statistics(graph_id)
        
        # 获取所有实体节点
        all_nodes = self.get_all_nodes(graph_id)
        
        # 筛选有实际类型的实体（非纯Entity节点）
        entities = []
        for node in all_nodes:
            custom_labels = [l for l in node.labels if l not in ["Entity", "Node"]]
            if custom_labels:
                entities.append({
                    "name": node.name,
                    "type": custom_labels[0],
                    "summary": node.summary
                })
        
        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search_result.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],  # 限制数量
            "total_entities": len(entities)
        }
    
    # ========== 核心检索工具（优化后） ==========
    
    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5,
        language: Optional[str] = None
    ) -> InsightForgeResult:
        """
        【InsightForge - 深度洞察检索】
        
        最强大的混合检索函数，自动分解问题并多维度检索：
        1. 使用LLM将问题分解为多个子问题
        2. 对每个子问题进行语义搜索
        3. 提取相关实体并获取其详细信息
        4. 追踪关系链
        5. 整合所有结果，生成深度洞察
        
        Args:
            graph_id: 图谱ID
            query: 用户问题
            simulation_requirement: 模拟需求描述
            report_context: 报告上下文（可选，用于更精准的子问题生成）
            max_sub_queries: 最大子问题数量
            language: the record's language ('en'/'zh'); None reads in the thread's
            
        Returns:
            InsightForgeResult: 深度洞察检索结果
        """
        logger.info(t("console.insightForgeStart", query=query[:50]))
        lang = _lang_of(language)
        
        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[],
            language=lang
        )
        
        # Step 1: 使用LLM生成子问题
        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries,
            language=lang
        )
        result.sub_queries = sub_queries
        logger.info(t("console.generatedSubQueries", count=len(sub_queries)))
        
        # Step 2: 对每个子问题进行语义搜索
        all_facts = []
        all_edges = []
        seen_facts = set()
        
        for sub_query in sub_queries:
            search_result = self.search_graph(
                graph_id=graph_id,
                query=sub_query,
                limit=15,
                scope="edges"
            )
            
            for fact in search_result.facts:
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)
            
            all_edges.extend(search_result.edges)
        
        # 对原始问题也进行搜索
        main_search = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=20,
            scope="edges"
        )
        for fact in main_search.facts:
            if fact not in seen_facts:
                all_facts.append(fact)
                seen_facts.add(fact)
        
        result.semantic_facts = all_facts
        result.total_facts = len(all_facts)
        
        # Step 3: 从边中提取相关实体UUID，只获取这些实体的信息（不获取全部节点）
        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                if source_uuid:
                    entity_uuids.add(source_uuid)
                if target_uuid:
                    entity_uuids.add(target_uuid)
        
        # 获取所有相关实体的详情（不限制数量，完整输出）
        entity_insights = []
        node_map = {}  # 用于后续关系链构建
        
        for uuid in list(entity_uuids):  # 处理所有实体，不截断
            if not uuid:
                continue
            try:
                # 单独获取每个相关节点的信息
                node = self.get_node_detail(uuid)
                if node:
                    node_map[uuid] = node
                    entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), _w(lang, 'entity'))
                    
                    # 获取该实体相关的所有事实（不截断）
                    related_facts = [
                        f for f in all_facts 
                        if node.name.lower() in f.lower()
                    ]
                    
                    entity_insights.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "type": entity_type,
                        "summary": node.summary,
                        "related_facts": related_facts  # 完整输出，不截断
                    })
            except Exception as e:
                logger.debug(f"Could not read node {uuid}: {e}")
                continue
        
        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)
        
        # Step 4: 构建所有关系链（不限制数量）
        relationship_chains = []
        for edge_data in all_edges:  # 处理所有边，不截断
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                relation_name = edge_data.get('name', '')
                
                source_name = node_map.get(source_uuid, NodeInfo('', '', [], '', {})).name or source_uuid[:8]
                target_name = node_map.get(target_uuid, NodeInfo('', '', [], '', {})).name or target_uuid[:8]
                
                chain = f"{source_name} --[{relation_name}]--> {target_name}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)
        
        result.relationship_chains = relationship_chains
        result.total_relationships = len(relationship_chains)
        
        logger.info(t("console.insightForgeComplete", facts=result.total_facts, entities=result.total_entities, relationships=result.total_relationships))
        return result
    
    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5,
        language: Optional[str] = None
    ) -> List[str]:
        """
        使用LLM生成子问题
        
        将复杂问题分解为多个可以独立检索的子问题, written in the record's language
        (the city's memory holds its facts in it).
        """
        lang = _lang_of(language)
        name = LANGUAGE_NAMES[lang]
        system_prompt = f"""You analyse questions. Break a complex question into sub-questions that can each be looked for on their own in the record of the argument.

The sub-questions:
1. Each concrete enough to match something the citizens did or said
2. Together covering the question's sides (who, what, why, how, when, where)
3. Bearing on the question put to the city
4. Written in {name}, whatever the language of the question
Return JSON: {{"sub_queries": ["sub-question 1", "sub-question 2", ...]}}
{language_instruction_for(lang)}"""

        context = f"Context from the Chronicle so far:\n{report_context[:500]}\n\n" if report_context else ""
        user_prompt = f"""The question put to the city (background):
{simulation_requirement}

{context}Break this question into {max_queries} sub-questions:
{query}

Return the sub-questions as JSON."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            sub_queries = response.get("sub_queries", [])
            # 确保是字符串列表
            sub_queries = [str(sq) for sq in sub_queries[:max_queries]]
            # The Scribe reads them too: in the record's language.
            return [sq for sq in self._guard(sub_queries, lang, 'search questions') if sq.strip()]
            
        except Exception as e:
            logger.warning(t("console.generateSubQueriesFailed", error=str(e)))
            # 降级：返回基于原问题的变体
            if lang == 'zh':
                variants = [f"{query} 的主要参与者", f"{query} 的原因和影响", f"{query} 的发展过程"]
            else:
                variants = [f"{query}: who took part", f"{query}: causes and effects", f"{query}: how it unfolded"]
            return [query, *variants][:max_queries]
    
    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50,
        language: Optional[str] = None
    ) -> PanoramaResult:
        """
        【PanoramaSearch - 广度搜索】
        
        获取全貌视图，包括所有相关内容和历史/过期信息：
        1. 获取所有相关节点
        2. 获取所有边（包括已过期/失效的）
        3. 分类整理当前有效和历史信息
        
        这个工具适用于需要了解事件全貌、追踪演变过程的场景。
        
        Args:
            graph_id: 图谱ID
            query: 搜索查询（用于相关性排序）
            include_expired: 是否包含过期内容（默认True）
            limit: 返回结果数量限制
            language: the record's language ('en'/'zh'); None reads in the thread's
            
        Returns:
            PanoramaResult: 广度搜索结果
        """
        logger.info(t("console.panoramaSearchStart", query=query[:50]))
        lang = _lang_of(language)
        
        result = PanoramaResult(query=query, language=lang)
        
        # 获取所有节点
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)
        
        # 获取所有边（包含时间信息）
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)
        
        # 分类事实
        active_facts = []
        historical_facts = []
        
        for edge in all_edges:
            if not edge.fact:
                continue
            
            # 为事实添加实体名称
            source_name = node_map.get(edge.source_node_uuid, NodeInfo('', '', [], '', {})).name or edge.source_node_uuid[:8]
            target_name = node_map.get(edge.target_node_uuid, NodeInfo('', '', [], '', {})).name or edge.target_node_uuid[:8]
            
            # 判断是否过期/失效
            is_historical = edge.is_expired or edge.is_invalid
            
            if is_historical:
                # 历史/过期事实，添加时间标记
                valid_at = edge.valid_at or _w(lang, 'unknown')
                invalid_at = edge.invalid_at or edge.expired_at or _w(lang, 'unknown')
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                # 当前有效事实
                active_facts.append(edge.fact)
        
        # 基于查询进行相关性排序
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score
        
        # 排序并限制数量
        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)
        
        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)
        
        logger.info(t("console.panoramaSearchComplete", active=result.active_count, historical=result.historical_count))
        return result
    
    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        language: Optional[str] = None
    ) -> SearchResult:
        """
        【QuickSearch - 简单搜索】
        
        快速、轻量级的检索工具：
        1. 直接调用Zep语义搜索
        2. 返回最相关的结果
        3. 适用于简单、直接的检索需求
        
        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: 返回结果数量
            language: the record's language ('en'/'zh'); None reads in the thread's
            
        Returns:
            SearchResult: 搜索结果
        """
        logger.info(t("console.quickSearchStart", query=query[:50]))
        
        # 直接调用现有的search_graph方法
        result = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope="edges"
        )
        result.language = _lang_of(language)
        
        logger.info(t("console.quickSearchComplete", count=result.total_count))
        return result
    
    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None,
        language: Optional[str] = None
    ) -> InterviewResult:
        """
        【InterviewAgents - 深度采访】
        
        调用真实的OASIS采访API，采访模拟中正在运行的Agent：
        1. 自动读取人设文件，了解所有模拟Agent
        2. 使用LLM分析采访需求，智能选择最相关的Agent
        3. 使用LLM生成采访问题
        4. 调用 /api/simulation/interview/batch 接口进行真实采访（双平台同时采访）
        5. 整合所有采访结果，生成采访报告
        
        【重要】此功能需要模拟环境处于运行状态（OASIS环境未关闭）
        
        【使用场景】
        - 需要从不同角色视角了解事件看法
        - 需要收集多方意见和观点
        - 需要获取模拟Agent的真实回答（非LLM模拟）

        Everything is in one language: the one given, else the gathering's
        record language (never the thread's or the request's). The questions
        and the prefix ask the citizens for it, and every answer, role and
        bio the Scribe will read is passed through the language guard first,
        so the words she quotes are already in the Chronicle's language.
        
        Args:
            simulation_id: 模拟ID（用于定位人设文件和调用采访API）
            interview_requirement: 采访需求描述（非结构化，如"了解学生对事件的看法"）
            simulation_requirement: 模拟需求背景（可选）
            max_agents: 最多采访的Agent数量
            custom_questions: 自定义采访问题（可选，若不提供则自动生成）
            language: 'en' or 'zh'; None reads the record's (record_language)
            
        Returns:
            InterviewResult: 采访结果
        """
        from .simulation_runner import SimulationRunner
        
        logger.info(t("console.interviewAgentsStart", requirement=interview_requirement[:50]))
        lang = normalize_lang(language) if language else record_language(simulation_id=simulation_id)
        
        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or [],
            language=lang
        )
        
        # Step 1: 读取人设文件
        profiles = self._load_agent_profiles(simulation_id)
        
        if not profiles:
            logger.warning(t("console.profilesNotFound", simId=simulation_id))
            result.summary = _w(lang, 'no_profiles')
            return result
        
        result.total_agents = len(profiles)
        logger.info(t("console.loadedProfiles", count=len(profiles)))
        
        # Step 2: 使用LLM选择要采访的Agent（返回agent_id列表）
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents,
            language=lang
        )
        
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        logger.info(t("console.selectedAgentsForInterview", count=len(selected_agents), indices=selected_indices))
        
        # Step 3: 生成采访问题（如果没有提供）
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents,
                language=lang
            )
            logger.info(t("console.generatedInterviewQuestions", count=len(result.interview_questions)))

        # The questions go to the citizens and the topic and reasoning to the
        # Scribe: all of them in the record's language before anyone reads them.
        questions = [str(q) for q in result.interview_questions if str(q or '').strip()]
        guarded = self._guard(
            [result.interview_topic, result.selection_reasoning, *questions], lang,
            'the questions of an interview for a Chronicle',
        )
        result.interview_topic, result.selection_reasoning = guarded[0], guarded[1]
        result.interview_questions = [q for q in guarded[2:] if q.strip()] or self._fallback_questions(
            result.interview_topic, lang
        )
        
        # 将问题合并为一个采访prompt
        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])
        
        # 添加优化前缀，约束Agent回复格式（in the record's language）
        optimized_prompt = f"{interview_prefix(lang)}{combined_prompt}"
        
        # Step 4: 调用真实的采访API（不指定platform，默认双平台同时采访）
        try:
            # 构建批量采访列表（不指定platform，双平台采访）
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt  # 使用优化后的prompt
                    # 不指定platform，API会在twitter和reddit两个平台都采访
                })
            
            logger.info(t("console.callingBatchInterviewApi", count=len(interviews_request)))
            
            # 调用 SimulationRunner 的批量采访方法（不传platform，双平台采访）
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,  # 不指定platform，双平台采访
                timeout=180.0   # 双平台需要更长超时
            )
            
            logger.info(t("console.interviewApiReturned", count=api_result.get('interviews_count', 0), success=api_result.get('success')))
            
            # 检查API调用是否成功
            if not api_result.get("success", False):
                error_msg = _said(api_result.get("error") or _w(lang, 'unknown_error'), lang)
                logger.warning(t("console.interviewApiReturnedFailure", error=error_msg))
                result.summary = _w(lang, 'api_failed', error=error_msg)
                return result
            
            # Step 5: 解析API返回结果，构建AgentInterview对象
            # 双平台模式返回格式: {"twitter_0": {...}, "reddit_0": {...}, "twitter_1": {...}, ...}
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}

            # Each citizen's two answers, role and bio: (name, twitter, reddit, role, bio).
            heard = []
            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession") or _w(lang, 'unknown')
                agent_bio = str(agent.get("bio") or "")[:1000]  # 扩大bio长度限制
                
                # 获取该Agent在两个平台的采访结果
                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})
                
                # 清理可能的工具调用 JSON 包裹
                twitter_response = self._clean_tool_call_response(twitter_result.get("response", "") or "")
                reddit_response = self._clean_tool_call_response(reddit_result.get("response", "") or "")
                heard.append((agent_name, twitter_response, reddit_response, str(agent_role), agent_bio))

            # One translate call for everything the citizens said that the Scribe can't read.
            flat = [text for _name, *texts in heard for text in texts]
            flat = self._guard(flat, lang, "citizens' answers in an interview for a Chronicle")

            for i, (agent_name, *_texts) in enumerate(heard):
                twitter_response, reddit_response, agent_role, agent_bio = flat[4 * i:4 * i + 4]

                # 始终输出双平台标记
                twitter_text = twitter_response if twitter_response else _w(lang, 'no_answer')
                reddit_text = reddit_response if reddit_response else _w(lang, 'no_answer')
                response_text = (
                    f"{_w(lang, 'on_twitter')}\n{twitter_text}\n\n{_w(lang, 'on_reddit')}\n{reddit_text}"
                )

                # 提取关键引言（从两个平台的回答中, in the answers' language）
                key_quotes = extract_key_quotes([twitter_response, reddit_response], lang)
                
                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio,
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5],
                    language=lang
                )
                result.interviews.append(interview)
            
            result.interviewed_count = len(result.interviews)
            
        except ValueError as e:
            # 模拟环境未运行
            logger.warning(t("console.interviewApiCallFailed", error=e))
            result.summary = _w(lang, 'env_closed', error=_said(e, lang))
            return result
        except Exception as e:
            logger.error(t("console.interviewApiCallException", error=e))
            import traceback
            logger.error(traceback.format_exc())
            result.summary = _w(lang, 'interview_error', error=_said(e, lang))
            return result
        
        # Step 6: 生成采访摘要
        if result.interviews:
            summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=result.interview_topic,
                language=lang
            )
            result.summary = ensure_language(
                summary, lang, llm=getattr(self, '_translator', None), context='an interview summary for a Chronicle'
            )
        
        logger.info(t("console.interviewAgentsComplete", count=result.interviewed_count))
        return result
    
    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        """清理 Agent 回复中的 JSON 工具调用包裹，提取实际内容"""
        if not response or not response.strip().startswith('{'):
            return response
        text = response.strip()
        if 'tool_name' not in text[:80]:
            return response
        import re as _re
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'arguments' in data:
                for key in ('content', 'text', 'body', 'message', 'reply'):
                    if key in data['arguments']:
                        return str(data['arguments'][key])
        except (json.JSONDecodeError, KeyError, TypeError):
            match = _re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\n', '\n').replace('\\"', '"')
        return response

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        """加载模拟的Agent人设文件"""
        import os
        import csv
        
        # 构建人设文件路径
        sim_dir = (
            os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id) if Config.DATA_DIR
            else os.path.join(
                os.path.dirname(__file__), 
                f'../../uploads/simulations/{simulation_id}'
            )
        )
        
        profiles = []
        
        # 优先尝试读取Reddit JSON格式
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                logger.info(t("console.loadedRedditProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readRedditProfilesFailed", error=e))
        
        # 尝试读取Twitter CSV格式
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # CSV格式转换为统一格式
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": ""
                        })
                logger.info(t("console.loadedTwitterProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readTwitterProfilesFailed", error=e))
        
        return profiles
    
    def _select_agents_for_interview(
        self,
        profiles: List[Dict[str, Any]],
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int,
        language: Optional[str] = None
    ) -> tuple:
        """
        使用LLM选择要采访的Agent (the reasoning in the record's language)
        
        Returns:
            tuple: (selected_agents, selected_indices, reasoning)
                - selected_agents: 选中Agent的完整信息列表
                - selected_indices: 选中Agent的索引列表（用于API调用）
                - reasoning: 选择理由
        """
        lang = _lang_of(language)
        
        # 构建Agent摘要列表
        agent_summaries = []
        for i, profile in enumerate(profiles):
            summary = {
                "index": i,
                "name": profile.get("realname", profile.get("username", f"Agent_{i}")),
                "profession": profile.get("profession") or _w(lang, 'unknown'),
                "bio": str(profile.get("bio") or "")[:200],
                "interested_topics": profile.get("interested_topics", [])
            }
            agent_summaries.append(summary)
        
        system_prompt = f"""You plan interviews. From the list of citizens, choose the ones best placed to be interviewed on the brief.

How to choose:
1. Their identity or work bears on the subject
2. They may hold a distinct or valuable view
3. Choose a range of views (for, against, neutral, expert and so on)
4. Prefer those directly involved in the events

Write the reasoning in {LANGUAGE_NAMES[lang]}.
Return JSON:
{{
    "selected_indices": [the indices of the chosen citizens],
    "reasoning": "why these citizens were chosen"
}}
{language_instruction_for(lang)}"""

        user_prompt = f"""Interview brief:
{interview_requirement}

Background (the question put to the city):
{simulation_requirement if simulation_requirement else _w(lang, 'not_given')}

The citizens to choose from ({len(agent_summaries)}):
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

Choose at most {max_agents} citizens to interview and say why."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning") or _w(lang, 'chose_by_relevance')
            
            # 获取选中的Agent完整信息
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)
            
            return selected_agents, valid_indices, str(reasoning)
            
        except Exception as e:
            logger.warning(t("console.llmSelectAgentFailed", error=e))
            # 降级：选择前N个
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, _w(lang, 'chose_by_default')
    
    @staticmethod
    def _fallback_questions(interview_requirement: str, lang: str) -> List[str]:
        """The questions asked when none could be written, in the record's language."""

        if normalize_lang(lang) == 'zh':
            return [
                f"关于{interview_requirement}，您的观点是什么？",
                "这件事对您或您所代表的群体有什么影响？",
                "您认为应该如何解决或改进这个问题？"
            ]
        return [
            f"What is your view on {interview_requirement}?",
            "What did it mean for you, or for the people you speak for?",
            "How do you think it should be settled or improved?"
        ]

    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]],
        language: Optional[str] = None
    ) -> List[str]:
        """使用LLM生成采访问题 (in the record's language: the citizens answer in the questions' language)"""
        
        lang = _lang_of(language)
        name = LANGUAGE_NAMES[lang]
        agent_roles = [str(a.get("profession") or _w(lang, 'unknown')) for a in selected_agents]
        
        system_prompt = f"""You are an experienced interviewer. From the interview brief, write 3-5 searching interview questions.

The questions:
1. Open questions that invite a full answer
2. Questions that different people could answer differently
3. Covering facts, views and feelings
4. Natural, as in a real interview
5. Each short and clear (under 25 words)
6. Asked directly, with no background or preamble
7. Written in {name}, whatever the language of the brief

Return JSON: {{"questions": ["question 1", "question 2", ...]}}
{language_instruction_for(lang)}"""

        user_prompt = f"""Interview brief: {interview_requirement}

Background (the question put to the city): {simulation_requirement if simulation_requirement else _w(lang, 'not_given')}

The interviewees' roles: {', '.join(agent_roles)}

Write 3-5 interview questions in {name}."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5
            )
            
            questions = response.get("questions")
            questions = [str(q) for q in questions if str(q or '').strip()] if isinstance(questions, list) else []
            return questions or self._fallback_questions(interview_requirement, lang)[:1]
            
        except Exception as e:
            logger.warning(t("console.generateInterviewQuestionsFailed", error=e))
            return self._fallback_questions(interview_requirement, lang)
    
    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str,
        language: Optional[str] = None
    ) -> str:
        """生成采访摘要 (in the record's language)"""
        
        lang = _lang_of(language)
        if not interviews:
            return _w(lang, 'no_interviews')
        
        # 收集所有采访内容
        interview_texts = []
        for interview in interviews:
            interview_texts.append(_w(
                lang, 'summary_item', name=interview.agent_name, role=interview.agent_role,
                answer=interview.response[:500],
            ))
        
        name = LANGUAGE_NAMES[lang]
        system_prompt = f"""You are a news editor. From several interviewees' answers, write a summary of the interviews.

The summary:
1. Draws out each side's main views
2. Notes where they agree and where they differ
3. Brings out the telling quotations
4. Is objective and even-handed
5. Stays under 600 words

Format (required):
- Plain paragraphs, separated by blank lines
- No Markdown headings (such as #, ##, ###)
- No dividers (such as ---, ***)
- {_w(lang, 'quote_marks')}
- **Bold** for key words is allowed; no other Markdown

Write the summary in {name}. A quotation from an answer in another language is translated into {name}.
{language_instruction_for(lang)}"""

        user_prompt = f"""Topic: {interview_requirement}

The interviews:
{chr(10).join(interview_texts)}

Write the summary."""

        try:
            summary = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            return summary
            
        except Exception as e:
            logger.warning(t("console.generateInterviewSummaryFailed", error=e))
            # 降级：简单拼接
            names = _w(lang, 'names_joiner').join([i.agent_name for i in interviews])
            return _w(lang, 'summary_fallback', n=len(interviews), names=names)
