"""
OASIS Agent Profile生成器
将Zep图谱中的实体转换为OASIS模拟平台所需的Agent Profile格式

优化改进：
1. 调用Zep检索功能二次丰富节点信息
2. 优化提示词生成非常详细的人设
3. 区分个人实体和抽象群体实体
"""

import json
import random
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from openai import OpenAI
from ..config import Config
from ..utils.logger import get_logger
from ..utils.json_files import write_json_atomic
from ..utils import pools
from ..utils.locale import get_locale, language_instruction_for, normalize_lang, set_locale, t
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
from ..utils.zep import (
    call_zep_read_with_retry,
    get_zep_client,
    is_local_memory_backend,
    is_retryable_zep_error,
    normalize_zep_search_query,
)
from .language_guard import ensure_language_many, foreign_script
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.oasis_profile')

# Where a citizen is from when neither the model nor the rest of the crowd says:
# every gathering is held in Athens. (MiroFish's default was China.) Written in
# the gathering's record language.
DEFAULT_COUNTRY = "Greece"
DEFAULT_COUNTRIES = {"en": DEFAULT_COUNTRY, "zh": "希腊"}

# Countries a model has named in Chinese, as an English record writes them
# (the upstream prompt asked for Chinese country names).
COUNTRY_NAMES_EN = {
    "希腊": "Greece", "古希腊": "Ancient Greece", "雅典": "Athens", "斯巴达": "Sparta",
    "普萨莫斯": "Psammos", "荷兰": "Netherlands", "埃及": "Egypt", "阿尔巴尼亚": "Albania",
    "俄罗斯": "Russia", "美国": "United States", "中国": "China", "英国": "United Kingdom",
    "法国": "France", "德国": "Germany", "意大利": "Italy", "日本": "Japan", "韩国": "South Korea",
    "土耳其": "Turkey", "波斯": "Persia", "马其顿": "Macedonia", "罗马": "Rome", "西班牙": "Spain",
}


def profile_language(generator: Any = None, language: Optional[str] = None) -> str:
    """The language profiles are written in: the one given, the generator's own, else the thread's."""

    chosen = language or getattr(generator, "language", None)
    return normalize_lang(chosen) if chosen else get_locale()


def country_in(country: Any, lang: str) -> Optional[str]:
    """A country as a record in ``lang`` writes it, or None when it cannot be.

    A Chinese record keeps what the model wrote. An English one gets a
    Chinese name in English (希腊 is Greece); a name still in another script
    is None, and the crowd's country (or Greece) is given instead.
    """

    text = _coerce_to_str(country).strip().strip("「」“”\"' ")
    if not text:
        return None
    if normalize_lang(lang) == "zh" or not foreign_script(text, lang):
        return text
    return COUNTRY_NAMES_EN.get(text)


def display_names(names: Any, lang: str, *, llm: Any = None) -> Dict[str, str]:
    """{name as the graph has it: name a reader of the record sees} for the names that need one.

    A Chinese record shows every name as the graph has it (an empty map).
    Any other record shows a name the graph has in Chinese in its usual form
    in the record language (苏格拉底 is Socrates), all of them in one
    translate-only call. A name that cannot be put in that language is left
    out, and its caller gives the citizen a stand-in name.
    """

    lang = normalize_lang(lang)
    wanted = list(dict.fromkeys(
        name for name in (names or ()) if isinstance(name, str) and foreign_script(name, lang)
    ))
    if lang == "zh" or not wanted:
        return {}
    shown = ensure_language_many(wanted, lang, llm=llm, context="the names of a crowd's citizens")
    found = {}
    for name, text in zip(wanted, shown):
        text = " ".join(text.split()) if isinstance(text, str) else ""
        if text and not foreign_script(text, lang):
            found[name] = text
    return found


def fallback_persona(entity_name: str, entity_type: str, lang: str) -> str:
    """The persona of an entity nothing more is known about, in the record language."""

    if normalize_lang(lang) == "zh":
        return f"{entity_name}是一个{entity_type}。"
    return f"{entity_name} is a {entity_type}."


def _coerce_to_str(value: Any) -> str:
    """Coerce a value to a plain string.

    Handles dict, list, and other non-string types that may be returned
    by LLM JSON parsing.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ('text', 'value', 'description', 'content', 'summary', 'name'):
            if key in value:
                candidate = _coerce_to_str(value[key])
                if candidate:
                    return candidate
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        str_items = [_coerce_to_str(item) for item in value]
        str_items = [item for item in str_items if item]
        return ', '.join(str_items)
    return str(value)


def _coerce_to_str_list(value: Any) -> List[str]:
    """Coerce a value to a list of strings.

    Handles nested structures that may be returned by LLM JSON parsing.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        result: List[str] = []
        for item in value:
            if isinstance(item, (list, tuple)):
                result.extend(_coerce_to_str_list(item))
            else:
                text = _coerce_to_str(item)
                if text:
                    result.append(text)
        return result
    text = _coerce_to_str(value)
    return [text] if text else []


@dataclass
class OasisAgentProfile:
    """OASIS Agent Profile数据结构"""
    # 通用字段
    user_id: int
    user_name: str
    name: str
    bio: str
    persona: str

    # 可选字段 - Reddit风格
    karma: int = 1000
    
    # 可选字段 - Twitter风格
    friend_count: int = 100
    follower_count: int = 150
    statuses_count: int = 500
    
    # 额外人设信息
    age: Optional[int] = None
    gender: Optional[str] = None
    mbti: Optional[str] = None
    country: Optional[str] = None
    profession: Optional[str] = None
    interested_topics: List[str] = field(default_factory=list)
    
    # 来源实体信息
    source_entity_uuid: Optional[str] = None
    source_entity_type: Optional[str] = None
    
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    
    def __post_init__(self):
        """Normalize structured LLM fields once at the profile boundary."""
        self.bio = _coerce_to_str(self.bio) or self.name
        self.persona = _coerce_to_str(self.persona) or (
            f"{self.name} is a participant in social discussions."
        )
        self.country = _coerce_to_str(self.country) or None
        self.profession = _coerce_to_str(self.profession) or None
        self.gender = _coerce_to_str(self.gender) or None
        self.mbti = _coerce_to_str(self.mbti) or None
        self.interested_topics = _coerce_to_str_list(self.interested_topics)

    def to_reddit_format(self) -> Dict[str, Any]:
        """转换为Reddit平台格式"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS 库要求字段名为 username（无下划线）
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "created_at": self.created_at,
        }
        
        # 添加额外人设信息（如果有）
        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics
        
        return profile
    
    def to_twitter_format(self) -> Dict[str, Any]:
        """转换为Twitter平台格式"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS 库要求字段名为 username（无下划线）
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "created_at": self.created_at,
        }
        
        # 添加额外人设信息
        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics
        
        return profile
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为完整字典格式"""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "age": self.age,
            "gender": self.gender,
            "mbti": self.mbti,
            "country": self.country,
            "profession": self.profession,
            "interested_topics": self.interested_topics,
            "source_entity_uuid": self.source_entity_uuid,
            "source_entity_type": self.source_entity_type,
            "created_at": self.created_at,
        }


class OasisProfileGenerator:
    """
    OASIS Profile生成器
    
    将Zep图谱中的实体转换为OASIS模拟所需的Agent Profile
    
    优化特性：
    1. 调用Zep图谱检索功能获取更丰富的上下文
    2. 生成非常详细的人设（包括基本信息、职业经历、性格特征、社交媒体行为等）
    3. 区分个人实体和抽象群体实体
    """
    
    # MBTI类型列表
    MBTI_TYPES = [
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP"
    ]
    
    # 常见国家列表
    COUNTRIES = [
        "China", "US", "UK", "Japan", "Germany", "France", 
        "Canada", "Australia", "Brazil", "India", "South Korea"
    ]
    
    # 个人类型实体（需要生成具体人设）
    INDIVIDUAL_ENTITY_TYPES = [
        "student", "alumni", "professor", "person", "publicfigure", 
        "expert", "faculty", "official", "journalist", "activist"
    ]
    
    # 群体/机构类型实体（需要生成群体代表人设）
    GROUP_ENTITY_TYPES = [
        "university", "governmentagency", "organization", "ngo", 
        "mediaoutlet", "company", "institution", "group", "community"
    ]
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        zep_api_key: Optional[str] = None,
        graph_id: Optional[str] = None,
        language: Optional[str] = None,
    ):
        """``language`` is the gathering's record language: every field of
        every profile is written in it. None means the thread's locale."""
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME
        self.language = profile_language(language=language)
        # Graph name -> the name the record shows ('' when none could be found).
        self._shown_names: Dict[str, str] = {}

        if not self.api_key:
            raise ValueError("LLM_API_KEY is not configured")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        # Zep客户端用于检索丰富上下文
        self.zep_api_key = zep_api_key or Config.ZEP_API_KEY
        self.zep_client = None
        self.graph_id = graph_id
        
        if self.zep_api_key or is_local_memory_backend():
            try:
                self.zep_client = get_zep_client(self.zep_api_key)
            except Exception as e:
                logger.warning(f"Zep客户端初始化失败: {e}")
    
    def generate_profile_from_entity(
        self, 
        entity: EntityNode, 
        user_id: int,
        use_llm: bool = True
    ) -> OasisAgentProfile:
        """
        从Zep实体生成OASIS Agent Profile
        
        Args:
            entity: Zep实体节点
            user_id: 用户ID（用于OASIS）
            use_llm: 是否使用LLM生成详细人设
            
        Returns:
            OasisAgentProfile
        """
        entity_type = entity.get_entity_type() or "Entity"

        # 基础信息: the name the record shows; the graph keeps its own (joined by the uuid)
        name = self.shown_name(entity.name, user_id)
        user_name = self._generate_username(name)

        # 构建上下文信息
        context = self._build_entity_context(entity)

        if use_llm:
            # 使用LLM生成详细人设
            profile_data = self._generate_profile_with_llm(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes,
                context=context,
                source_name=entity.name,
            )
        else:
            # 使用规则生成基础人设
            profile_data = self._generate_profile_rule_based(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes
            )
        
        profile_data = self._in_record_language(profile_data, name)

        return OasisAgentProfile(
            user_id=user_id,
            user_name=user_name,
            name=name,
            bio=profile_data.get("bio", f"{entity_type}: {name}"),
            persona=profile_data.get("persona", entity.summary or f"A {entity_type} named {name}."),
            karma=profile_data.get("karma", random.randint(500, 5000)),
            friend_count=profile_data.get("friend_count", random.randint(50, 500)),
            follower_count=profile_data.get("follower_count", random.randint(100, 1000)),
            statuses_count=profile_data.get("statuses_count", random.randint(100, 2000)),
            age=profile_data.get("age"),
            gender=profile_data.get("gender"),
            mbti=profile_data.get("mbti"),
            country=profile_data.get("country"),
            profession=profile_data.get("profession"),
            interested_topics=profile_data.get("interested_topics", []),
            source_entity_uuid=entity.uuid,
            source_entity_type=entity_type,
        )
    
    def shown_name(self, name: str, user_id: int) -> str:
        """The citizen's name as the record shows it: the graph's, in the record language.

        A Chinese record, or a name with no Chinese in it, keeps the graph's
        name. Otherwise the name is put in the record language once
        (display_names) and reused by every card, the Symposium, the Web and
        the Chronicle; "Citizen <id>" when it cannot be. The graph keeps its
        own name: the profile's source_entity_uuid and the configuration's
        entity_uuid join the two.
        """

        lang = profile_language(self)
        if lang == "zh" or not foreign_script(name, lang):
            return name
        self._learn_names([name])
        return self._known_names().get(name) or f"Citizen {user_id}"

    def _known_names(self) -> Dict[str, str]:
        return self.__dict__.setdefault("_shown_names", {})

    def _learn_names(self, names: List[str]) -> None:
        """Find the shown names of those not yet asked for, in one call."""

        lang = profile_language(self)
        known = self._known_names()
        wanted = [name for name in dict.fromkeys(names)
                  if isinstance(name, str) and name not in known and foreign_script(name, lang)]
        if lang == "zh" or not wanted:
            return
        found = display_names(wanted, lang)
        known.update({name: found.get(name, "") for name in wanted})

    # The fields a profile shows or hands to its citizen (the name: shown_name).
    RECORD_FIELDS = ("bio", "persona", "country", "profession")

    def _in_record_language(self, data: Dict[str, Any], name: str) -> Dict[str, Any]:
        """The profile's fields in the record language (the last-line guard).

        A Chinese country name is put in English without a model call; any
        other field still carrying Chinese for an English record is
        translated, all in one call. A Chinese record is left as written.
        """
        lang = profile_language(self)
        if lang == "zh" or not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("country"):
            data["country"] = country_in(data["country"], lang) or data["country"]
        fields = [key for key in self.RECORD_FIELDS if isinstance(data.get(key), str)]
        topics = _coerce_to_str_list(data.get("interested_topics"))
        texts = [data[key] for key in fields] + topics
        if not any(foreign_script(text, lang) for text in texts):
            return data
        fixed = ensure_language_many(texts, lang, context=f"a citizen's profile ({name})")
        for key, text in zip(fields, fixed):
            data[key] = text
        if topics:
            data["interested_topics"] = [text for text in fixed[len(fields):] if text]
        if data.get("country") and not country_in(data["country"], lang):
            data["country"] = None  # the crowd's country is given when the profiles are saved
        return data

    def _generate_username(self, name: str) -> str:
        """生成用户名"""
        # 移除特殊字符，转换为小写
        username = name.lower().replace(" ", "_")
        username = ''.join(c for c in username if c.isalnum() or c == '_')
        
        # 添加随机后缀避免重复
        suffix = random.randint(100, 999)
        return f"{username}_{suffix}"
    
    def _search_zep_for_entity(self, entity: EntityNode) -> Dict[str, Any]:
        """
        使用Zep图谱混合搜索功能获取实体相关的丰富信息
        
        Zep没有内置混合搜索接口，需要分别搜索edges和nodes然后合并结果。
        使用并行请求同时搜索，提高效率。
        
        Args:
            entity: 实体节点对象
            
        Returns:
            包含facts, node_summaries, context的字典
        """
        import concurrent.futures
        
        if not self.zep_client:
            return {"facts": [], "node_summaries": [], "context": ""}
        
        entity_name = entity.name
        
        results = {
            "facts": [],
            "node_summaries": [],
            "context": ""
        }
        
        # 必须有graph_id才能进行搜索
        if not self.graph_id:
            logger.debug(f"跳过Zep检索：未设置graph_id")
            return results
        
        # The memory is written in the record language: ask it in that language.
        comprehensive_query = normalize_zep_search_query(
            t('progress.zepSearchQuery', locale=profile_language(self), name=entity_name)
        )
        
        def search_edges():
            """搜索边（事实/关系）- 带重试机制"""
            return call_zep_read_with_retry(
                lambda: self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=30,
                        scope="edges",
                        reranker="rrf"
                ),
                operation_name=f"profile edge search ({entity.uuid})",
            )
        
        def search_nodes():
            """搜索节点（实体摘要）- 带重试机制"""
            return call_zep_read_with_retry(
                lambda: self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=20,
                        scope="nodes",
                        reranker="rrf"
                ),
                operation_name=f"profile node search ({entity.uuid})",
            )
        
        try:
            # 并行执行edges和nodes搜索
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                edge_future = executor.submit(search_edges)
                node_future = executor.submit(search_nodes)
                
                # 获取结果
                # Each request already has the configured HTTP timeout and
                # typed retry budget. A second hard-coded 30s future timeout
                # discarded late successes while the executor still waited.
                edge_result = edge_future.result()
                node_result = node_future.result()
            
            # 处理边搜索结果
            all_facts = set()
            if edge_result and hasattr(edge_result, 'edges') and edge_result.edges:
                for edge in edge_result.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        all_facts.add(edge.fact)
            results["facts"] = list(all_facts)
            
            # 处理节点搜索结果
            all_summaries = set()
            if node_result and hasattr(node_result, 'nodes') and node_result.nodes:
                for node in node_result.nodes:
                    if hasattr(node, 'summary') and node.summary:
                        all_summaries.add(node.summary)
                    if hasattr(node, 'name') and node.name and node.name != entity_name:
                        all_summaries.add(f"Related entity: {node.name}")
            results["node_summaries"] = list(all_summaries)
            
            # 构建综合上下文
            context_parts = []
            if results["facts"]:
                context_parts.append("Facts:\n" + "\n".join(f"- {f}" for f in results["facts"][:20]))
            if results["node_summaries"]:
                context_parts.append("Related entities:\n" + "\n".join(f"- {s}" for s in results["node_summaries"][:10]))
            results["context"] = "\n\n".join(context_parts)
            
            logger.info(f"Zep混合检索完成: {entity_name}, 获取 {len(results['facts'])} 条事实, {len(results['node_summaries'])} 个相关节点")
            
        except Exception as e:
            logger.warning(f"Zep检索失败 ({entity_name}): {e}")
            if not is_retryable_zep_error(e):
                raise
        
        return results
    
    def _build_entity_context(self, entity: EntityNode) -> str:
        """
        构建实体的完整上下文信息
        
        包括：
        1. 实体本身的边信息（事实）
        2. 关联节点的详细信息
        3. Zep混合检索到的丰富信息
        """
        context_parts = []
        
        # 1. 添加实体属性信息
        if entity.attributes:
            attrs = []
            for key, value in entity.attributes.items():
                if value and str(value).strip():
                    attrs.append(f"- {key}: {value}")
            if attrs:
                context_parts.append("### Entity attributes\n" + "\n".join(attrs))
        
        # 2. 添加相关边信息（事实/关系）
        existing_facts = set()
        if entity.related_edges:
            relationships = []
            for edge in entity.related_edges:  # 不限制数量
                fact = edge.get("fact", "")
                edge_name = edge.get("edge_name", "")
                direction = edge.get("direction", "")
                
                if fact:
                    relationships.append(f"- {fact}")
                    existing_facts.add(fact)
                elif edge_name:
                    if direction == "outgoing":
                        relationships.append(f"- {entity.name} --[{edge_name}]--> (a related entity)")
                    else:
                        relationships.append(f"- (a related entity) --[{edge_name}]--> {entity.name}")
            
            if relationships:
                context_parts.append("### Related facts and relationships\n" + "\n".join(relationships))
        
        # 3. 添加关联节点的详细信息
        if entity.related_nodes:
            related_info = []
            for node in entity.related_nodes:  # 不限制数量
                node_name = node.get("name", "")
                node_labels = node.get("labels", [])
                node_summary = node.get("summary", "")
                
                # 过滤掉默认标签
                custom_labels = [l for l in node_labels if l not in ["Entity", "Node"]]
                label_str = f" ({', '.join(custom_labels)})" if custom_labels else ""
                
                if node_summary:
                    related_info.append(f"- **{node_name}**{label_str}: {node_summary}")
                else:
                    related_info.append(f"- **{node_name}**{label_str}")
            
            if related_info:
                context_parts.append("### Related entities\n" + "\n".join(related_info))
        
        # 4. 使用Zep混合检索获取更丰富的信息
        zep_results = self._search_zep_for_entity(entity)
        
        if zep_results.get("facts"):
            # 去重：排除已存在的事实
            new_facts = [f for f in zep_results["facts"] if f not in existing_facts]
            if new_facts:
                context_parts.append("### Facts found in memory\n" + "\n".join(f"- {f}" for f in new_facts[:15]))
        
        if zep_results.get("node_summaries"):
            context_parts.append("### Related nodes found in memory\n" + "\n".join(f"- {s}" for s in zep_results["node_summaries"][:10]))
        
        return "\n\n".join(context_parts)
    
    def _is_individual_entity(self, entity_type: str) -> bool:
        """判断是否是个人类型实体"""
        return entity_type.lower() in self.INDIVIDUAL_ENTITY_TYPES
    
    def _is_group_entity(self, entity_type: str) -> bool:
        """判断是否是群体/机构类型实体"""
        return entity_type.lower() in self.GROUP_ENTITY_TYPES
    
    def _generate_profile_with_llm(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str,
        source_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        使用LLM生成非常详细的人设
        
        根据实体类型区分：
        - 个人实体：生成具体的人物设定
        - 群体/机构实体：生成代表性账号设定

        ``entity_name`` is the name the record shows; ``source_name`` the
        graph's, when it differs (the context writes that one).
        """
        
        is_individual = self._is_individual_entity(entity_type)
        
        if is_individual:
            prompt = self._build_individual_persona_prompt(
                entity_name, entity_type, entity_summary, entity_attributes, context,
                source_name=source_name,
            )
        else:
            prompt = self._build_group_persona_prompt(
                entity_name, entity_type, entity_summary, entity_attributes, context,
                source_name=source_name,
            )

        # 尝试多次生成，直到成功或达到最大重试次数
        max_attempts = 3
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                response = create_chat_completion(
                    self.client,
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": self._get_system_prompt(is_individual)},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1),  # 每次重试降低温度
                    # 不设置max_tokens，让LLM自由发挥
                )
                
                content = extract_chat_completion_text(response)
                
                # 检查是否被截断（finish_reason不是'stop'）
                finish_reason = response.choices[0].finish_reason
                if finish_reason == 'length':
                    logger.warning(f"LLM输出被截断 (attempt {attempt+1}), 尝试修复...")
                    content = self._fix_truncated_json(content)
                
                # 尝试解析JSON
                try:
                    result = json.loads(content)
                    
                    # 验证必需字段
                    if "bio" not in result or not result["bio"]:
                        result["bio"] = entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}"
                    if "persona" not in result or not result["persona"]:
                        result["persona"] = entity_summary or fallback_persona(
                            entity_name, entity_type, profile_language(self)
                        )
                    
                    return result
                    
                except json.JSONDecodeError as je:
                    logger.warning(f"JSON解析失败 (attempt {attempt+1}): {str(je)[:80]}")
                    
                    # 尝试修复JSON
                    result = self._try_fix_json(content, entity_name, entity_type, entity_summary)
                    if result.get("_fixed"):
                        del result["_fixed"]
                        return result
                    
                    last_error = je
                    
            except Exception as e:
                logger.warning(f"LLM调用失败 (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(1 * (attempt + 1))  # 指数退避
        
        logger.warning(f"LLM生成人设失败（{max_attempts}次尝试）: {last_error}, 使用规则生成")
        return self._generate_profile_rule_based(
            entity_name, entity_type, entity_summary, entity_attributes
        )
    
    def _fix_truncated_json(self, content: str) -> str:
        """修复被截断的JSON（输出被max_tokens限制截断）"""
        import re
        
        # 如果JSON被截断，尝试闭合它
        content = content.strip()
        
        # 计算未闭合的括号
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # 检查是否有未闭合的字符串
        # 简单检查：如果最后一个引号后没有逗号或闭合括号，可能是字符串被截断
        if content and content[-1] not in '",}]':
            # 尝试闭合字符串
            content += '"'
        
        # 闭合括号
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_json(self, content: str, entity_name: str, entity_type: str, entity_summary: str = "") -> Dict[str, Any]:
        """尝试修复损坏的JSON"""
        import re
        
        # 1. 首先尝试修复被截断的情况
        content = self._fix_truncated_json(content)
        
        # 2. 尝试提取JSON部分
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # 3. 处理字符串中的换行符问题
            # 找到所有字符串值并替换其中的换行符
            def fix_string_newlines(match):
                s = match.group(0)
                # 替换字符串内的实际换行符为空格
                s = s.replace('\n', ' ').replace('\r', ' ')
                # 替换多余空格
                s = re.sub(r'\s+', ' ', s)
                return s
            
            # 匹配JSON字符串值
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string_newlines, json_str)
            
            # 4. 尝试解析
            try:
                result = json.loads(json_str)
                result["_fixed"] = True
                return result
            except json.JSONDecodeError as e:
                # 5. 如果还是失败，尝试更激进的修复
                try:
                    # 移除所有控制字符
                    json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                    # 替换所有连续空白
                    json_str = re.sub(r'\s+', ' ', json_str)
                    result = json.loads(json_str)
                    result["_fixed"] = True
                    return result
                except:
                    pass
        
        # 6. 尝试从内容中提取部分信息
        bio_match = re.search(r'"bio"\s*:\s*"([^"]*)"', content)
        persona_match = re.search(r'"persona"\s*:\s*"([^"]*)', content)  # 可能被截断
        
        bio = bio_match.group(1) if bio_match else (entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}")
        persona = persona_match.group(1) if persona_match else (
            entity_summary or fallback_persona(entity_name, entity_type, profile_language(self))
        )
        
        # 如果提取到了有意义的内容，标记为已修复
        if bio_match or persona_match:
            logger.info(f"从损坏的JSON中提取了部分信息")
            return {
                "bio": bio,
                "persona": persona,
                "_fixed": True
            }
        
        # 7. 完全失败，返回基础结构
        logger.warning(f"JSON修复失败，返回基础结构")
        return {
            "bio": entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}",
            "persona": entity_summary or fallback_persona(entity_name, entity_type, profile_language(self))
        }
    
    def _get_system_prompt(self, is_individual: bool) -> str:
        """获取系统提示词"""
        base_prompt = (
            "You are an expert in social media user profiles. Write detailed, realistic personas for an "
            "opinion simulation, as close to the known facts as you can. Return valid JSON; no string value "
            "may contain an unescaped line break."
        )
        return f"{base_prompt}\n\n{language_instruction_for(profile_language(self))}"

    @staticmethod
    def _language_rule(lang: str, gender_rule: str) -> str:
        """The prompt's last rule: every written field in the record language, and why.

        A Chinese record keeps names as the context writes them; any other
        writes a Chinese name in its usual form (the entity's own as given
        above), as the cards and the Chronicle show it.
        """
        names = ("keeping names as they are" if normalize_lang(lang) == "zh"
                 else "writing a name the context gives in Chinese in its usual English form "
                      "(the entity's own name exactly as given above)")
        return (
            "- Write bio, persona, country, profession and interested_topics in the gathering's language, "
            f"translating anything the context quotes in another language and {names} "
            f"({gender_rule}).\n"
            f"- {language_instruction_for(lang)}"
        )

    @staticmethod
    def _name_lines(entity_name: str, source_name: Optional[str]) -> str:
        """The prompt's name, and the graph's when the record shows another."""
        line = f"Entity name: {entity_name}"
        if source_name and source_name != entity_name:
            line += f"\nThe context writes this name as: {source_name}"
        return line

    def _build_individual_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str,
        language: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> str:
        """构建个人实体的详细人设提示词"""
        
        lang = profile_language(self, language)
        home = DEFAULT_COUNTRIES[lang]
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "none"
        context_str = context[:3000] if context else "no further context"
        
        return f"""Write a detailed social media persona for this entity, as close to the known facts as you can.

{OasisProfileGenerator._name_lines(entity_name, source_name)}
Entity type: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context:
{context_str}

Return JSON with these fields:

1. bio: the social media bio, about 200 characters
2. persona: a detailed persona (plain text, about 2000 characters) covering:
   - basic facts (age, occupation, education, where they live)
   - background (important experiences, their tie to the events, their relationships)
   - character (MBTI type, core temperament, how they show feeling)
   - social media habits (how often they post, what they post, how they engage, how they speak)
   - positions (their view of the question, what angers or moves them)
   - particular traits (sayings, notable experiences, pastimes)
   - personal memory (the heart of the persona: this person's tie to the events, and what they have already done and said in them)
3. age: age as a whole number
4. gender: in English, "male" or "female"
5. mbti: MBTI type (e.g. INTJ, ENFP)
6. country: the country or city-state this person belongs to, inferred from the entity and the context (a citizen of Athens: "{home}"); "{home}" when the context does not say
7. profession: occupation
8. interested_topics: an array of the topics they care about

Important:
- Every field value is a string or a number, with no line breaks
- persona is one continuous description
- persona says this person never uses #hashtags or @handles and always speaks plainly, as themselves
- The content agrees with the entity information
- age is a valid whole number; gender is "male" or "female"
{OasisProfileGenerator._language_rule(lang, 'gender stays in English: male or female')}
"""

    def _build_group_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str,
        language: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> str:
        """构建群体/机构实体的详细人设提示词"""
        
        lang = profile_language(self, language)
        home = DEFAULT_COUNTRIES[lang]
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "none"
        context_str = context[:3000] if context else "no further context"
        
        return f"""Write a detailed social media account for this institution or group, as close to the known facts as you can.

{OasisProfileGenerator._name_lines(entity_name, source_name)}
Entity type: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context:
{context_str}

Return JSON with these fields:

1. bio: the official account's bio, about 200 characters, professional and fitting
2. persona: a detailed account description (plain text, about 2000 characters) covering:
   - the institution (full name, what kind of body it is, how it came to be, what it does)
   - the account (what kind of account, its audience, what it is for)
   - its voice (how it speaks, what it often says, what it will not talk about)
   - what it posts (kinds of posts, how often, when it is active)
   - its positions (its official view of the question, how it handles controversy)
   - particulars (who it speaks for, how it is run)
   - institutional memory (the heart of the account: the institution's tie to the events, and what it has already done and said in them)
3. age: always 30 (the account's nominal age)
4. gender: always "other" (an institution is not a person)
5. mbti: an MBTI type for the account's style, e.g. ISTJ for strict and conservative
6. country: the country or city-state the institution is in, inferred from the entity and the context (an institution of Athens: "{home}"); "{home}" when the context does not say
7. profession: what the institution does
8. interested_topics: an array of the fields it follows

Important:
- Every field value is a string or a number; no null values
- persona is one continuous description, with no line breaks
- persona says this account never uses #hashtags or @handles and always speaks plainly, as the institution itself
- age is the whole number 30; gender is the string "other"
- The account speaks as fits its standing
{OasisProfileGenerator._language_rule(lang, 'gender stays in English: "other"')}"""
    
    def _generate_profile_rule_based(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """使用规则生成基础人设"""
        
        # 根据实体类型生成不同的人设
        entity_type_lower = entity_type.lower()
        
        if entity_type_lower in ["student", "alumni"]:
            return {
                "bio": f"{entity_type} with interests in academics and social issues.",
                "persona": f"{entity_name} is a {entity_type.lower()} who is actively engaged in academic and social discussions. They enjoy sharing perspectives and connecting with peers.",
                "age": random.randint(18, 30),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                "country": None,  # the crowd's own country is given when the profiles are saved
                "profession": "Student",
                "interested_topics": ["Education", "Social Issues", "Technology"],
            }
        
        elif entity_type_lower in ["publicfigure", "expert", "faculty"]:
            return {
                "bio": f"Expert and thought leader in their field.",
                "persona": f"{entity_name} is a recognized {entity_type.lower()} who shares insights and opinions on important matters. They are known for their expertise and influence in public discourse.",
                "age": random.randint(35, 60),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(["ENTJ", "INTJ", "ENTP", "INTP"]),
                "country": None,  # the crowd's own country is given when the profiles are saved
                "profession": entity_attributes.get("occupation", "Expert"),
                "interested_topics": ["Politics", "Economics", "Culture & Society"],
            }
        
        elif entity_type_lower in ["mediaoutlet", "socialmediaplatform"]:
            return {
                "bio": f"Official account for {entity_name}. News and updates.",
                "persona": f"{entity_name} is a media entity that reports news and facilitates public discourse. The account shares timely updates and engages with the audience on current events.",
                "age": 30,  # 机构虚拟年龄
                "gender": "other",  # 机构使用other
                "mbti": "ISTJ",  # 机构风格：严谨保守
                "country": None,
                "profession": "Media",
                "interested_topics": ["General News", "Current Events", "Public Affairs"],
            }
        
        elif entity_type_lower in ["university", "governmentagency", "ngo", "organization"]:
            return {
                "bio": f"Official account of {entity_name}.",
                "persona": f"{entity_name} is an institutional entity that communicates official positions, announcements, and engages with stakeholders on relevant matters.",
                "age": 30,  # 机构虚拟年龄
                "gender": "other",  # 机构使用other
                "mbti": "ISTJ",  # 机构风格：严谨保守
                "country": None,
                "profession": entity_type,
                "interested_topics": ["Public Policy", "Community", "Official Announcements"],
            }
        
        else:
            # 默认人设
            return {
                "bio": entity_summary[:150] if entity_summary else f"{entity_type}: {entity_name}",
                "persona": entity_summary or f"{entity_name} is a {entity_type.lower()} participating in social discussions.",
                "age": random.randint(25, 50),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                "country": None,  # the crowd's own country is given when the profiles are saved
                "profession": entity_type,
                "interested_topics": ["General", "Social Issues"],
            }
    
    def set_graph_id(self, graph_id: str):
        """设置图谱ID用于Zep检索"""
        self.graph_id = graph_id
    
    def generate_profiles_from_entities(
        self,
        entities: List[EntityNode],
        use_llm: bool = True,
        progress_callback: Optional[callable] = None,
        graph_id: Optional[str] = None,
        parallel_count: int = 5,
        realtime_output_path: Optional[str] = None,
        output_platform: str = "reddit"
    ) -> List[OasisAgentProfile]:
        """
        批量从实体生成Agent Profile（支持并行生成）
        
        Args:
            entities: 实体列表
            use_llm: 是否使用LLM生成详细人设
            progress_callback: 进度回调函数 (current, total, message)
            graph_id: 图谱ID，用于Zep检索获取更丰富上下文
            parallel_count: 并行生成数量，默认5
            realtime_output_path: 实时写入的文件路径（如果提供，每生成一个就写入一次）
            output_platform: 输出平台格式 ("reddit" 或 "twitter")
            
        Returns:
            Agent Profile列表
        """
        import concurrent.futures
        from threading import Lock
        
        # 设置graph_id用于Zep检索
        if graph_id:
            self.graph_id = graph_id
        
        total = len(entities)
        profiles = [None] * total  # 预分配列表保持顺序
        completed_count = [0]  # 使用列表以便在闭包中修改
        lock = Lock()
        
        # 实时写入文件的辅助函数
        def save_profiles_realtime():
            """实时保存已生成的 profiles 到文件"""
            if not realtime_output_path:
                return
            
            with lock:
                # 过滤出已生成的 profiles
                existing_profiles = [p for p in profiles if p is not None]
                if not existing_profiles:
                    return
                
                try:
                    if output_platform == "reddit":
                        # Reddit JSON 格式
                        profiles_data = [p.to_reddit_format() for p in existing_profiles]
                        # All at once: the Gathering reads this file while it grows.
                        write_json_atomic(realtime_output_path, profiles_data)
                    else:
                        # Twitter CSV 格式
                        import csv
                        profiles_data = [p.to_twitter_format() for p in existing_profiles]
                        if profiles_data:
                            fieldnames = list(profiles_data[0].keys())
                            with open(realtime_output_path, 'w', encoding='utf-8', newline='') as f:
                                writer = csv.DictWriter(f, fieldnames=fieldnames)
                                writer.writeheader()
                                writer.writerows(profiles_data)
                except Exception as e:
                    logger.warning(f"实时保存 profiles 失败: {e}")
        
        # The workers write the record: in its language, not the asker's.
        record_locale = profile_language(self)
        # Every name the record shows, found in one call before the workers start.
        self._learn_names([entity.name for entity in entities])

        def generate_single_profile(idx: int, entity: EntityNode) -> tuple:
            """生成单个profile的工作函数"""
            set_locale(record_locale)
            entity_type = entity.get_entity_type() or "Entity"
            
            try:
                profile = self.generate_profile_from_entity(
                    entity=entity,
                    user_id=idx,
                    use_llm=use_llm
                )
                
                # 实时输出生成的人设到控制台和日志
                self._print_generated_profile(profile.name, entity_type, profile)
                
                return idx, profile, None
                
            except Exception as e:
                logger.error(f"生成实体 {entity.name} 的人设失败: {str(e)}")
                # 创建一个基础profile
                return idx, self._stand_in_profile(idx, entity, entity_type), str(e)
        
        logger.info(f"开始并行生成 {total} 个Agent人设（并行数: {parallel_count}）...")
        print(f"\n{'='*60}")
        print(f"开始生成Agent人设 - 共 {total} 个实体，并行数: {parallel_count}")
        print(f"{'='*60}\n")
        
        # 使用线程池并行执行
        # On the public steps a stop cancels what is still queued (utils/pools.py).
        with pools.cancel_on_exit(
            concurrent.futures.ThreadPoolExecutor(max_workers=parallel_count)
        ) as executor:
            # 提交所有任务
            future_to_entity = {
                executor.submit(generate_single_profile, idx, entity): (idx, entity)
                for idx, entity in enumerate(entities)
            }
            
            # 收集结果
            for future in pools.as_completed(future_to_entity):
                idx, entity = future_to_entity[future]
                entity_type = entity.get_entity_type() or "Entity"
                if future.cancelled():
                    # Only a stop cancels these: no stand-in pasts for the rest of the crowd.
                    raise pools.Interrupted('The process is stopping.')
                
                try:
                    result_idx, profile, error = future.result()
                    profiles[result_idx] = profile
                    
                    with lock:
                        completed_count[0] += 1
                        current = completed_count[0]
                    
                    # 实时写入文件
                    save_profiles_realtime()
                    
                    if progress_callback:
                        progress_callback(
                            current, 
                            total, 
                            t('progress.profileDone', current=current, total=total,
                              name=profile.name if profile else entity.name, type=entity_type)
                        )
                    
                    if error:
                        logger.warning(f"[{current}/{total}] {entity.name} 使用备用人设: {error}")
                    else:
                        logger.info(f"[{current}/{total}] 成功生成人设: {entity.name} ({entity_type})")
                        
                except Exception as e:
                    logger.error(f"处理实体 {entity.name} 时发生异常: {str(e)}")
                    with lock:
                        completed_count[0] += 1
                    profiles[idx] = self._stand_in_profile(idx, entity, entity_type)
                    # 实时写入文件（即使是备用人设）
                    save_profiles_realtime()
        
        print(f"\n{'='*60}")
        print(f"人设生成完成！共生成 {len([p for p in profiles if p])} 个Agent")
        print(f"{'='*60}\n")
        
        return profiles
    
    def _stand_in_profile(self, idx: int, entity: EntityNode, entity_type: str) -> OasisAgentProfile:
        """The basic profile of a citizen whose own could not be written (its summary in the record language)."""
        name = self.shown_name(entity.name, idx)
        data = self._in_record_language({
            "bio": f"{entity_type}: {name}",
            "persona": entity.summary or "A participant in social discussions.",
        }, name)
        return OasisAgentProfile(
            user_id=idx,
            user_name=self._generate_username(name),
            name=name,
            bio=data["bio"],
            persona=data["persona"],
            source_entity_uuid=entity.uuid,
            source_entity_type=entity_type,
        )

    def _print_generated_profile(self, entity_name: str, entity_type: str, profile: OasisAgentProfile):
        """实时输出生成的人设到控制台（完整内容，不截断）"""
        separator = "-" * 70
        
        # 构建完整输出内容（不截断）
        topics_str = ', '.join(profile.interested_topics) if profile.interested_topics else '无'
        
        output_lines = [
            f"\n{separator}",
            t('progress.profileGenerated', name=entity_name, type=entity_type),
            f"{separator}",
            f"用户名: {profile.user_name}",
            f"",
            f"【简介】",
            f"{profile.bio}",
            f"",
            f"【详细人设】",
            f"{profile.persona}",
            f"",
            f"【基本属性】",
            f"年龄: {profile.age} | 性别: {profile.gender} | MBTI: {profile.mbti}",
            f"职业: {profile.profession} | 国家: {profile.country}",
            f"兴趣话题: {topics_str}",
            separator
        ]
        
        output = "\n".join(output_lines)
        
        # 只输出到控制台（避免重复，logger不再输出完整内容）
        print(output)
    
    def save_profiles(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """
        保存Profile到文件（根据平台选择正确格式）
        
        OASIS平台格式要求：
        - Twitter: CSV格式
        - Reddit: JSON格式
        
        Args:
            profiles: Profile列表
            file_path: 文件路径
            platform: 平台类型 ("reddit" 或 "twitter")
        """
        if platform == "twitter":
            self._save_twitter_csv(profiles, file_path)
        else:
            self._save_reddit_json(profiles, file_path)
    
    def _save_twitter_csv(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        保存Twitter Profile为CSV格式（符合OASIS官方要求）
        
        OASIS Twitter要求的CSV字段：
        - user_id: 用户ID（根据CSV顺序从0开始）
        - name: 用户真实姓名
        - username: 系统中的用户名
        - user_char: 详细人设描述（注入到LLM系统提示中，指导Agent行为）
        - description: 简短的公开简介（显示在用户资料页面）
        
        user_char vs description 区别：
        - user_char: 内部使用，LLM系统提示，决定Agent如何思考和行动
        - description: 外部显示，其他用户可见的简介
        """
        import csv
        
        # 确保文件扩展名是.csv
        if not file_path.endswith('.csv'):
            file_path = file_path.replace('.json', '.csv')
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入OASIS要求的表头
            headers = ['user_id', 'name', 'username', 'user_char', 'description']
            writer.writerow(headers)
            
            # 写入数据行
            for idx, profile in enumerate(profiles):
                # user_char: 完整人设（bio + persona），用于LLM系统提示
                user_char = profile.bio
                if profile.persona and profile.persona != profile.bio:
                    user_char = f"{profile.bio} {profile.persona}"
                # 处理换行符（CSV中用空格替代）
                user_char = user_char.replace('\n', ' ').replace('\r', ' ')
                
                # description: 简短简介，用于外部显示
                description = profile.bio.replace('\n', ' ').replace('\r', ' ')
                
                row = [
                    idx,                    # user_id: 从0开始的顺序ID
                    profile.name,           # name: 真实姓名
                    profile.user_name,      # username: 用户名
                    user_char,              # user_char: 完整人设（内部LLM使用）
                    description             # description: 简短简介（外部显示）
                ]
                writer.writerow(row)
        
        logger.info(f"已保存 {len(profiles)} 个Twitter Profile到 {file_path} (OASIS CSV格式)")
    
    @staticmethod
    def crowd_country(profiles: List[OasisAgentProfile], default: str = DEFAULT_COUNTRY) -> str:
        """The country most of the crowd gave, or ``default`` (Greece: the city is Athens)."""

        counts: Dict[str, int] = {}
        for profile in profiles:
            country = (profile.country or '').strip() if isinstance(profile.country, str) else ''
            if country:
                counts[country] = counts.get(country, 0) + 1
        if not counts:
            return default
        return max(counts.items(), key=lambda item: item[1])[0]

    def _normalize_gender(self, gender: Optional[str]) -> str:
        """
        标准化gender字段为OASIS要求的英文格式
        
        OASIS要求: male, female, other
        """
        if not gender:
            return "other"
        
        gender_lower = gender.lower().strip()
        
        # 中文映射
        gender_map = {
            "男": "male",
            "女": "female",
            "机构": "other",
            "其他": "other",
            # 英文已有
            "male": "male",
            "female": "female",
            "other": "other",
        }
        
        return gender_map.get(gender_lower, "other")
    
    def _save_reddit_json(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        保存Reddit Profile为JSON格式
        
        使用与 to_reddit_format() 一致的格式，确保 OASIS 能正确读取。
        必须包含 user_id 字段，这是 OASIS agent_graph.get_agent() 匹配的关键！
        
        必需字段：
        - user_id: 用户ID（整数，用于匹配 initial_posts 中的 poster_agent_id）
        - username: 用户名
        - name: 显示名称
        - bio: 简介
        - persona: 详细人设
        - age: 年龄（整数）
        - gender: "male", "female", 或 "other"
        - mbti: MBTI类型
        - country: 国家
        """
        data = []
        # A generator that knows its record language writes every country in
        # it (希腊 is Greece in an English record); one made without that
        # (only tests) keeps what the profiles say.
        lang = getattr(self, "language", None)
        if lang:
            for profile in profiles:
                profile.country = country_in(profile.country, lang)
        # OASIS tells each citizen where they are from; one the model left
        # without a country is from where the rest of the crowd is.
        crowd_country = self.crowd_country(profiles, DEFAULT_COUNTRIES.get(lang or "en", DEFAULT_COUNTRY))
        for idx, profile in enumerate(profiles):
            # 使用与 to_reddit_format() 一致的格式
            item = {
                "user_id": profile.user_id if profile.user_id is not None else idx,  # 关键：必须包含 user_id
                "username": profile.user_name,
                "name": profile.name,
                "bio": profile.bio[:150],
                "persona": profile.persona,
                "karma": profile.karma if profile.karma else 1000,
                "created_at": profile.created_at,
                # OASIS必需字段 - 确保都有默认值
                "age": profile.age if profile.age else 30,
                "gender": self._normalize_gender(profile.gender),
                "mbti": profile.mbti if profile.mbti else "ISTJ",
                "country": profile.country if profile.country else crowd_country,
            }
            
            # 可选字段
            if profile.profession:
                item["profession"] = profile.profession
            if profile.interested_topics:
                item["interested_topics"] = profile.interested_topics
            
            data.append(item)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"已保存 {len(profiles)} 个Reddit Profile到 {file_path} (JSON格式，包含user_id字段)")
    
    # 保留旧方法名作为别名，保持向后兼容
    def save_profiles_to_json(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """[已废弃] 请使用 save_profiles() 方法"""
        logger.warning("save_profiles_to_json已废弃，请使用save_profiles方法")
        self.save_profiles(profiles, file_path, platform)
