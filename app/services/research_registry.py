from dataclasses import asdict, dataclass
from typing import Dict, List


@dataclass(frozen=True)
class BackboneSpec:
    key: str
    name: str
    family: str
    source: str
    original_datasets: List[str]
    intended_role: str
    deployment_status: str
    gpu_recommended: bool
    notes: str


@dataclass(frozen=True)
class AlgorithmSpec:
    key: str
    name: str
    inspired_by: List[str]
    main_backbones: List[str]
    original_datasets: List[str]
    classroom_inputs: List[str]
    classroom_outputs: List[str]
    current_status: str
    deployment_note: str


@dataclass(frozen=True)
class ClassroomDatasetSpec:
    key: str
    purpose: str
    required_fields: List[str]
    note: str


# These entries reflect the dual-mode runtime:
# - standard profile keeps the lightweight baseline path
# - enhanced profile can activate the research-adapted algorithm hooks
PRETRAINED_BACKBONES: Dict[str, BackboneSpec] = {
    "clip_vit_b16": BackboneSpec(
        key="clip_vit_b16",
        name="CLIP ViT-B/16",
        family="vision-language foundation model",
        source="Used by the local CLPC-main and P-CLIP-main research code.",
        original_datasets=["CLIP pretraining corpus", "CUHK-PEDES", "ICFG-PEDES", "RSTPReid"],
        intended_role=(
            "Research backbone for One-Shot MVG, CCM, CDL and CLPC-style refinement. "
            "Suitable for offline feature extraction, identity prototypes and cross-modal matching experiments."
        ),
        deployment_status="optional_local_asset",
        gpu_recommended=True,
        notes=(
            "This is the main pretrained backbone behind both local paper codebases. "
            "The classroom runtime now exposes One-Shot MVG / CCM / CDL hooks, while the actual live path "
            "still prioritizes existing face/voice embeddings and treats CLIP as an optional enhanced asset."
        ),
    ),
    "bge_m3": BackboneSpec(
        key="bge_m3",
        name="BGE-M3",
        family="text embedding model",
        source="Recommended classroom adaptation backbone for viewpoint clustering and knowledge-point grouping.",
        original_datasets=["general multilingual embedding training corpora"],
        intended_role=(
            "Optional classroom text embedding base for replacing pure prompt-only clustering "
            "with embedding clustering plus CLPC-style refinement."
        ),
        deployment_status="optional_local_asset",
        gpu_recommended=False,
        notes=(
            "This is not part of the original paper code, but it is the practical classroom text base used by "
            "the current PDL&CLPC adaptation when a local embedding model is present. The runtime falls back to "
            "deterministic hash embeddings if BGE assets are not deployed."
        ),
    ),
}


ALGORITHM_SPECS: Dict[str, AlgorithmSpec] = {
    "one_shot_mvg": AlgorithmSpec(
        key="one_shot_mvg",
        name="One-Shot MVG",
        inspired_by=[
            "P-CLIP: Progressive Discrepancy Learning for One-Shot Text-to-Image Person Re-Identification",
        ],
        main_backbones=["clip_vit_b16"],
        original_datasets=["CUHK-PEDES", "ICFG-PEDES", "RSTPReid"],
        classroom_inputs=["face crop sequence", "mouth ROI sequence", "student_id seed frame", "timestamp"],
        classroom_outputs=["restored identity track", "state continuity score", "relinked visual fragments"],
        current_status="runtime_adapted_optional",
        deployment_note=(
            "Implemented as an enhanced runtime hook in research_runtime.py. "
            "The current classroom adaptation uses progressive prototype update and state relinking logic, "
            "while optional CLIP assets remain available for deeper offline experiments."
        ),
    ),
    "ccm": AlgorithmSpec(
        key="ccm",
        name="CCM",
        inspired_by=[
            "P-CLIP compact cross-modal matching loss",
        ],
        main_backbones=["clip_vit_b16"],
        original_datasets=["CUHK-PEDES", "ICFG-PEDES", "RSTPReid"],
        classroom_inputs=["face features", "mouth movement features", "speaker candidate window"],
        classroom_outputs=["speaker identity confidence", "cross-modal speaker lock"],
        current_status="runtime_adapted_optional",
        deployment_note=(
            "Implemented as a cross-modal identity attribution hook in the enhanced runtime. "
            "It consumes pyannote / WeSpeaker / TalkNet-ASD / InsightFace evidence and remains optional in "
            "judge-friendly standard deployments."
        ),
    ),
    "cdl": AlgorithmSpec(
        key="cdl",
        name="CDL",
        inspired_by=[
            "P-CLIP cross-view discrepancy learning",
            "project-specific classroom cross-modal correction design",
        ],
        main_backbones=["clip_vit_b16"],
        original_datasets=["CUHK-PEDES", "ICFG-PEDES", "RSTPReid"],
        classroom_inputs=["speech semantics", "facial emotion", "body activity", "recent classroom context"],
        classroom_outputs=["cross-modal consistency score", "participation weight correction"],
        current_status="runtime_adapted_optional",
        deployment_note=(
            "Implemented as a classroom cross-modal correction layer in the enhanced runtime. "
            "It adjusts participation weight and consistency using semantic, visual and active-speaker evidence."
        ),
    ),
    "clpc_viewpoint_refinement": AlgorithmSpec(
        key="clpc_viewpoint_refinement",
        name="PDL&CLPC",
        inspired_by=[
            "Consensus Labeling: Prompt-Guided Clustering Refinement for Weakly Supervised Text-Based Person Re-Identification",
        ],
        main_backbones=["clip_vit_b16", "bge_m3"],
        original_datasets=["CUHK-PEDES", "ICFG-PEDES", "RSTPReid"],
        classroom_inputs=["speech text", "topic", "current goals", "speaker list"],
        classroom_outputs=["soft speech distributions", "viewpoint clusters", "refined pseudo labels", "supporter lists"],
        current_status="runtime_adapted_optional",
        deployment_note=(
            "Implemented in two places: PDL soft scoring is applied to single-speech assessment, and CLPC-style "
            "pseudo-label refinement is applied after the LLM seed viewpoints are generated."
        ),
    ),
    "ipa": AlgorithmSpec(
        key="ipa",
        name="IPA",
        inspired_by=[
            "project-specific Intelligent Personalized Assessment design",
        ],
        main_backbones=["bge_m3"],
        original_datasets=["classroom interaction logs", "student performance traces"],
        classroom_inputs=["speech count", "quality trajectory", "viewpoint participation", "emotion summary"],
        classroom_outputs=["student diagnosis profile", "diagnostic tags", "personalized suggestions"],
        current_status="runtime_adapted_optional",
        deployment_note=(
            "Implemented as a post-analysis report enrichment hook. "
            "It builds per-student diagnostic profiles from classroom process evidence and injects them into the report."
        ),
    ),
}


CLASSROOM_DATASETS: Dict[str, ClassroomDatasetSpec] = {
    "classroom_identity_track": ClassroomDatasetSpec(
        key="classroom_identity_track",
        purpose="Support One-Shot MVG and CCM adaptation.",
        required_fields=[
            "student_id",
            "video_path",
            "face_bbox",
            "mouth_bbox",
            "timestamp",
            "is_speaking",
        ],
        note="Needed if the team later wants a real classroom identity restoration branch.",
    ),
    "classroom_viewpoint_cluster": ClassroomDatasetSpec(
        key="classroom_viewpoint_cluster",
        purpose="Support CLPC-style clustering refinement.",
        required_fields=[
            "meeting_id",
            "topic",
            "utterance_text",
            "speaker_name",
            "viewpoint_label",
            "cluster_id",
        ],
        note="Needed if the team upgrades from prompt-only clustering to embedding plus refinement.",
    ),
}


def get_backbone_registry() -> Dict[str, Dict]:
    return {key: asdict(spec) for key, spec in PRETRAINED_BACKBONES.items()}


def get_algorithm_registry() -> Dict[str, Dict]:
    return {key: asdict(spec) for key, spec in ALGORITHM_SPECS.items()}


def get_classroom_dataset_registry() -> Dict[str, Dict]:
    return {key: asdict(spec) for key, spec in CLASSROOM_DATASETS.items()}


def get_research_summary() -> Dict[str, Dict]:
    return {
        "default_mode": "documented_only",
        "runtime_enabled_by_default": False,
        "backbones": get_backbone_registry(),
        "algorithms": get_algorithm_registry(),
        "classroom_datasets": get_classroom_dataset_registry(),
    }
