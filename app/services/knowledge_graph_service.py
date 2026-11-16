"""课堂知识图谱：概念抽取、增量合并与 ECharts 可视化数据。

LLM 只负责从对话中抽取概念和关系；本模块负责校验输出结构，保证缺失
id/type、空节点、悬空边以及历史脏数据不会传到前端。
"""

import json
from datetime import datetime
from typing import Any, Dict, List

from app.services.llm_service import llm

_CATEGORIES = ("概念", "人物", "方法", "关系")
_CATEGORY_SET = set(_CATEGORIES)


class KnowledgeGraphService:
    def __init__(self):
        self.llm = llm

    def extract_concepts_from_conversation(
        self,
        topic: str,
        conversations: List[Dict[str, str]],
        existing_graph: Dict = None,
    ) -> Dict[str, Any]:
        """从课堂对话中抽取概念与关系。

        Returns:
            {"nodes": [...], "edges": [...]}
        """
        conversation_text = "\n".join(
            f"{c.get('username', '')}: {c.get('content', '')}"
            for c in conversations
        )

        existing_desc = ""
        if existing_graph and existing_graph.get("nodes"):
            node_labels = [
                str(n.get("label", "")).strip()
                for n in existing_graph["nodes"]
                if n.get("label") and "[EMOJI]" not in str(n.get("label"))
            ]
            if node_labels:
                existing_desc = f"已有概念: {', '.join(node_labels[:10])}"

        prompt = f"""你是一名教育知识图谱构建助手。请从课堂对话中提取核心概念及其关系。

要求：
1. 提取对话中出现的核心概念、术语、人物、方法或关系，数量 1-15 个。
2. 只提取对话中有依据的内容，不要编造。对话很短时可以只提取 1-3 个。
3. 概念类型只能是以下四类之一：概念、人物、方法、关系。
4. 关系应来自对话中的明确表达或合理推断；没有关系时 edges 返回空数组。

课程主题：{topic}
{existing_desc}

课堂对话：
{conversation_text}

只输出 JSON，不要 markdown、不要解释，格式：
{{
  "nodes": [
    {{
      "id": "concept_1",
      "label": "概念名称",
      "type": "概念",
      "description": "一句话说明"
    }}
  ],
  "edges": [
    {{
      "source": "concept_1",
      "target": "concept_2",
      "relation": "关系说明",
      "weight": 0.8,
      "evidence": "某学生: 原话"
    }}
  ]
}}

约束：
- id 使用 concept_1、concept_2……
- type 只能是 概念/人物/方法/关系
- weight 在 0-1 之间
- 只引用 nodes 中存在的 id
"""

        try:
            response = self.llm.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是教育知识图谱构建助手，只输出合法 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            result = json.loads(response.choices[0].message.content)
            return self._normalize_graph(result)
        except Exception as e:
            print(f"[ERROR] 知识图谱抽取失败: {e}")
            return {"nodes": [], "edges": []}

    @staticmethod
    def _normalize_graph(result: Any) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {"nodes": [], "edges": []}

        nodes: List[Dict[str, Any]] = []
        node_ids = set()
        for index, node in enumerate(result.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            label = str(node.get("label") or "").strip()
            if not label or "[EMOJI]" in label:
                continue
            node_id = str(node.get("id") or f"concept_{index + 1}").strip()
            if not node_id or node_id in node_ids:
                continue
            node_type = str(node.get("type") or "概念").strip()
            if node_type not in _CATEGORY_SET:
                node_type = "概念"
            nodes.append(
                {
                    "id": node_id,
                    "label": label[:200],
                    "type": node_type,
                    "description": str(node.get("description") or "").strip()[:500],
                }
            )
            node_ids.add(node_id)
            if len(nodes) >= 15:
                break

        edges: List[Dict[str, Any]] = []
        seen_edges = set()
        for edge in result.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source") or "").strip()
            target = str(edge.get("target") or "").strip()
            if source not in node_ids or target not in node_ids or source == target:
                continue
            relation = str(edge.get("relation") or "").strip() or "相关"
            key = (source, target, relation)
            if key in seen_edges:
                continue
            try:
                weight = float(edge.get("weight", 0.5))
            except (TypeError, ValueError):
                weight = 0.5
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "weight": max(0.0, min(1.0, weight)),
                    "evidence": str(edge.get("evidence") or "").strip()[:500],
                }
            )
            seen_edges.add(key)

        return {"nodes": nodes, "edges": edges}

    def merge_graphs(
        self,
        existing_graph: Dict,
        new_graph: Dict,
        speakers: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """把新抽取的图谱合并进已有图谱。"""
        if not existing_graph or not existing_graph.get("nodes"):
            for node in new_graph.get("nodes", []):
                node["frequency"] = 1
                node["speakers"] = speakers.get(node["id"], [])
                node["first_mentioned"] = datetime.now().isoformat()
            return new_graph

        merged_nodes = {
            n["id"]: n
            for n in existing_graph.get("nodes", [])
            if n.get("id")
        }
        merged_edges = {
            f"{e['source']}_{e['target']}_{e['relation']}": e
            for e in existing_graph.get("edges", [])
            if e.get("source") and e.get("target") and e.get("relation")
        }

        for new_node in new_graph.get("nodes", []):
            node_id = new_node["id"]
            if node_id in merged_nodes:
                merged_nodes[node_id]["frequency"] = (
                    int(merged_nodes[node_id].get("frequency", 1)) + 1
                )
                existing_speakers = set(merged_nodes[node_id].get("speakers", []))
                new_speakers = set(speakers.get(node_id, []))
                merged_nodes[node_id]["speakers"] = list(
                    existing_speakers | new_speakers
                )
            else:
                new_node["frequency"] = 1
                new_node["speakers"] = speakers.get(node_id, [])
                new_node["first_mentioned"] = datetime.now().isoformat()
                merged_nodes[node_id] = new_node

        for new_edge in new_graph.get("edges", []):
            edge_key = (
                f"{new_edge['source']}_{new_edge['target']}_{new_edge['relation']}"
            )
            if edge_key in merged_edges:
                current_weight = float(merged_edges[edge_key].get("weight", 0.5))
                merged_edges[edge_key]["weight"] = min(current_weight + 0.1, 1.0)
            else:
                merged_edges[edge_key] = new_edge

        return {
            "nodes": list(merged_nodes.values()),
            "edges": list(merged_edges.values()),
        }

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """字符级 Jaccard 相似度（轻量兜底，不依赖 BERT）。"""
        words1 = set(text1.lower())
        words2 = set(text2.lower())
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / len(words1 | words2)

    def generate_graph_visualization_data(self, graph_data: Dict) -> Dict:
        """把图谱数据转换成 ECharts graph 需要的结构。"""
        nodes = []
        node_ids = set()
        for node in graph_data.get("nodes", []):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "").strip()
            label = str(node.get("label") or "").strip()
            if not node_id or not label or "[EMOJI]" in label:
                continue
            node_type = str(node.get("type") or "概念").strip()
            if node_type not in _CATEGORY_SET:
                node_type = "概念"
            try:
                frequency = max(1, int(node.get("frequency") or 1))
            except (TypeError, ValueError):
                frequency = 1
            node_ids.add(node_id)
            nodes.append(
                {
                    "id": node_id,
                    "name": label,
                    "value": frequency,
                    "category": node_type,
                    "symbolSize": min(24 + frequency * 6, 80),
                    "label": {
                        "show": True,
                        "fontSize": 12 + min(frequency, 5),
                    },
                    "tooltip": {
                        "formatter": (
                            f"{label}<br/>出现次数: {frequency}"
                            f"<br/>{node.get('description', '')}"
                        )
                    },
                }
            )

        links = []
        for edge in graph_data.get("edges", []):
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source") or "").strip()
            target = str(edge.get("target") or "").strip()
            if source not in node_ids or target not in node_ids:
                continue
            weight = float(edge.get("weight", 0.5) or 0.5)
            links.append(
                {
                    "source": source,
                    "target": target,
                    "value": weight,
                    "lineStyle": {
                        "width": max(1, weight * 5),
                        "curveness": 0.2,
                    },
                    "label": {
                        "show": True,
                        "formatter": edge.get("relation", ""),
                    },
                }
            )

        return {
            "nodes": nodes,
            "links": links,
            "categories": [{"name": name} for name in _CATEGORIES],
        }


kg_service = KnowledgeGraphService()
