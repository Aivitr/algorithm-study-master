"""
[EMOJI]
[EMOJI],[EMOJI]
"""
import json
from typing import List, Dict, Any
from datetime import datetime
from app.services.llm_service import llm

class KnowledgeGraphService:
    def __init__(self):
        self.llm = llm
    
    def extract_concepts_from_conversation(
        self, 
        topic: str, 
        conversations: List[Dict[str, str]],
        existing_graph: Dict = None
    ) -> Dict[str, Any]:
        """
        [EMOJI]
        
        Args:
            topic: [EMOJI]
            conversations: [EMOJI] [{"username": "[EMOJI]", "content": "..."}]
            existing_graph: [EMOJI]
        
        Returns:
            {"nodes": [...], "edges": [...]}
        """
        # [EMOJI]
        conversation_text = "\n".join([
            f"{c['username']}: {c['content']}" 
            for c in conversations
        ])
        
        # [EMOJI]
        existing_desc = ""
        if existing_graph and existing_graph.get("nodes"):
            node_labels = [n["label"] for n in existing_graph["nodes"]]
            existing_desc = f"[EMOJI]: {', '.join(node_labels[:10])}"
        
        prompt = f"""[EMOJI],[EMOJI]

[EMOJI]:
1. [EMOJI]([EMOJI])
2. [EMOJI]([EMOJI])
3. [EMOJI]

[EMOJI]: {topic}
{existing_desc}

[EMOJI]:
{conversation_text}

[EMOJI]JSON[EMOJI]:
{{
  "nodes": [
    {{
      "id": "concept_[EMOJI]",
      "label": "[EMOJI]",
      "type": "[EMOJI]",
      "description": "[EMOJI]"
    }}
  ],
  "edges": [
    {{
      "source": "concept_[EMOJI]",
      "target": "concept_[EMOJI]",
      "relation": "[EMOJI]",
      "weight": 0.8,
      "evidence": "[EMOJI]A[EMOJI]:[EMOJI]"
    }}
  ]
}}

[EMOJI]:
- [EMOJI]
- [EMOJI]5-15[EMOJI]
- [EMOJI]
- [EMOJI]
- id[EMOJI]: concept_[EMOJI]
"""
        
        try:
            response = self.llm.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "[EMOJI]JSON[EMOJI]"},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )
            
            result = json.loads(response.choices[0].message.content)
            return result
        except Exception as e:
            print(f"[EMOJI]: {e}")
            return {"nodes": [], "edges": []}
    
    def merge_graphs(
        self, 
        existing_graph: Dict, 
        new_graph: Dict,
        speakers: Dict[str, List[str]]  # {concept_id: [speaker1, speaker2]}
    ) -> Dict[str, Any]:
        """
        [EMOJI]
        
        Args:
            existing_graph: [EMOJI]
            new_graph: [EMOJI]
            speakers: [EMOJI]
        
        Returns:
            [EMOJI]
        """
        if not existing_graph or not existing_graph.get("nodes"):
            # [EMOJI],[EMOJI]
            for node in new_graph.get("nodes", []):
                node["frequency"] = 1
                node["speakers"] = speakers.get(node["id"], [])
                node["first_mentioned"] = datetime.now().isoformat()
            return new_graph
        
        merged_nodes = {n["id"]: n for n in existing_graph.get("nodes", [])}
        merged_edges = {f"{e['source']}_{e['target']}_{e['relation']}": e 
                       for e in existing_graph.get("edges", [])}
        
        # [EMOJI]
        for new_node in new_graph.get("nodes", []):
            node_id = new_node["id"]
            if node_id in merged_nodes:
                # [EMOJI]
                merged_nodes[node_id]["frequency"] += 1
                # [EMOJI]
                existing_speakers = set(merged_nodes[node_id].get("speakers", []))
                new_speakers = set(speakers.get(node_id, []))
                merged_nodes[node_id]["speakers"] = list(existing_speakers | new_speakers)
            else:
                # [EMOJI]
                new_node["frequency"] = 1
                new_node["speakers"] = speakers.get(node_id, [])
                new_node["first_mentioned"] = datetime.now().isoformat()
                merged_nodes[node_id] = new_node
        
        # [EMOJI]
        for new_edge in new_graph.get("edges", []):
            edge_key = f"{new_edge['source']}_{new_edge['target']}_{new_edge['relation']}"
            if edge_key in merged_edges:
                # [EMOJI]
                current_weight = merged_edges[edge_key]["weight"]
                merged_edges[edge_key]["weight"] = min(current_weight + 0.1, 1.0)
            else:
                # [EMOJI]
                merged_edges[edge_key] = new_edge
        
        return {
            "nodes": list(merged_nodes.values()),
            "edges": list(merged_edges.values())
        }
    
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        [EMOJI]([EMOJI])
        [EMOJI]BERT
        """
        words1 = set(text1.lower())
        words2 = set(text2.lower())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union)
    
    def generate_graph_visualization_data(self, graph_data: Dict) -> Dict:
        """
        [EMOJI]
        [EMOJI]D3.js/ECharts
        """
        nodes = []
        for node in graph_data.get("nodes", []):
            nodes.append({
                "id": node["id"],
                "name": node["label"],
                "value": node.get("frequency", 1),  # [EMOJI]
                "category": node.get("type", "[EMOJI]"),
                "symbolSize": min(20 + node.get("frequency", 1) * 5, 80),  # [EMOJI]
                "label": {
                    "show": True,
                    "fontSize": 12 + min(node.get("frequency", 1), 5)
                },
                "tooltip": {
                    "formatter": f"{node['label']}<br/>[EMOJI]: {node.get('frequency', 1)}<br/>{node.get('description', '')}"
                }
            })
        
        links = []
        for edge in graph_data.get("edges", []):
            links.append({
                "source": edge["source"],
                "target": edge["target"],
                "value": edge.get("weight", 0.5),
                "lineStyle": {
                    "width": max(1, edge.get("weight", 0.5) * 5),
                    "curveness": 0.2
                },
                "label": {
                    "show": True,
                    "formatter": edge.get("relation", "")
                }
            })
        
        return {
            "nodes": nodes,
            "links": links,
            "categories": [
                {"name": "[EMOJI]"},
                {"name": "[EMOJI]"},
                {"name": "[EMOJI]"},
                {"name": "[EMOJI]"}
            ]
        }

# [EMOJI]
kg_service = KnowledgeGraphService()
