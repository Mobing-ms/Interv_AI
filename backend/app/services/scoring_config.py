"""
Scoring Configuration Module (Phase 5.2).
Provides a centralized, fully configurable repository of weights, thresholds,
and tolerances for all three scoring modules and session aggregation.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List


@dataclass
class FacePostureConfig:
    """Configurable weights and thresholds for face and posture scoring."""
    # Module component weights (must sum to 1.0)
    weight_eye_contact: float = 0.30
    weight_expression_stability: float = 0.15
    weight_head_pose_stability: float = 0.25
    weight_posture: float = 0.20
    weight_fidgeting: float = 0.10

    # Thresholds & tolerances
    target_eye_contact_ratio: float = 0.85  # Target ratio vs calibration baseline
    min_acceptable_eye_contact: float = 0.40  # Below this, eye contact score is 0
    max_yaw_dev_deg: float = 20.0  # Max acceptable yaw deviation from baseline
    max_pitch_dev_deg: float = 18.0  # Max acceptable pitch deviation from baseline
    max_roll_dev_deg: float = 15.0  # Max acceptable roll deviation from baseline
    target_posture: float = 0.85  # Target posture alignment ratio
    min_posture: float = 0.50  # Minimum acceptable posture alignment ratio
    fidgeting_tolerance: float = 0.06  # Movement level <= tolerance incurs no penalty
    fidgeting_max_penalty_threshold: float = 0.22  # Above this, maximum penalty applies


@dataclass
class SpeechConfidenceConfig:
    """Configurable weights and thresholds for speech confidence scoring."""
    # Module component weights (must sum to 1.0)
    weight_pace: float = 0.25
    weight_fillers: float = 0.25
    weight_pauses: float = 0.15
    weight_pitch: float = 0.10
    weight_volume: float = 0.10
    weight_clarity: float = 0.15

    # Pace thresholds (words per minute)
    ideal_pace_min_wpm: float = 120.0
    ideal_pace_max_wpm: float = 160.0
    acceptable_pace_min_wpm: float = 85.0
    acceptable_pace_max_wpm: float = 210.0

    # Filler word thresholds (filler count / total words)
    target_filler_rate: float = 0.02  # <= 2% filler words: 0 deduction
    max_filler_rate: float = 0.08  # >= 8% filler words: full deduction

    # Pause thresholds
    ideal_pause_length_min_sec: float = 0.4
    ideal_pause_length_max_sec: float = 2.2
    excessive_pause_threshold_sec: float = 3.5

    # Pitch & volume dynamics
    ideal_pitch_variance_min: float = 15.0  # Below 15 indicates monotone delivery
    ideal_pitch_variance_max: float = 80.0  # Above 80 indicates erratic vocal pitch
    ideal_volume_variability_min: float = 10.0  # Below 10 indicates flat/muffled volume
    ideal_volume_variability_max: float = 50.0

    # Clarity threshold (voiced energy ratio)
    target_clarity: float = 0.80


@dataclass
class ContentRubricConfig:
    """Configurable weights and thresholds for content scoring (rubric)."""
    # Technical question component weights (sum to 1.0)
    weight_technical_accuracy: float = 0.35
    weight_technical_depth: float = 0.25
    weight_technical_keywords: float = 0.25
    weight_technical_examples: float = 0.15

    # Behavioral question component weights (sum to 1.0)
    weight_behavioral_accuracy: float = 0.20
    weight_behavioral_depth: float = 0.20
    weight_behavioral_keywords: float = 0.15
    weight_behavioral_star: float = 0.30
    weight_behavioral_examples: float = 0.15

    # Target thresholds
    target_keyword_coverage: float = 0.80  # 80%+ keywords covered receives full score
    star_element_points: float = 2.5  # 2.5 pts per element in 10-pt scale (Situation, Task, Action, Result)
    example_marker_keywords: List[str] = field(default_factory=lambda: [
        "for example", "for instance", "such as", "specifically", "in my previous role",
        "in our project", "we achieved", "resulting in", "increased by", "reduced by",
        "metric", "%", "instance", "case study", "built a", "implemented a"
    ])


@dataclass
class SessionScoringWeights:
    """Weights used to combine the three modules into an overall composite session score."""
    content_weight: float = 0.50
    speech_confidence_weight: float = 0.30
    face_posture_weight: float = 0.20


@dataclass
class ScoringConfig:
    """
    Master scoring configuration class containing all weights, thresholds,
    and tolerances across all scoring modules.
    """
    face_posture: FacePostureConfig = field(default_factory=FacePostureConfig)
    speech_confidence: SpeechConfidenceConfig = field(default_factory=SpeechConfidenceConfig)
    content_rubric: ContentRubricConfig = field(default_factory=ContentRubricConfig)
    session_weights: SessionScoringWeights = field(default_factory=SessionScoringWeights)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes configuration to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ScoringConfig":
        """Constructs a ScoringConfig instance from an optional dictionary."""
        if not data:
            return cls()

        face_cfg = FacePostureConfig(**data.get("face_posture", {})) if "face_posture" in data else FacePostureConfig()
        speech_cfg = SpeechConfidenceConfig(**data.get("speech_confidence", {})) if "speech_confidence" in data else SpeechConfidenceConfig()
        content_cfg = ContentRubricConfig(**data.get("content_rubric", {})) if "content_rubric" in data else ContentRubricConfig()
        session_w = SessionScoringWeights(**data.get("session_weights", {})) if "session_weights" in data else SessionScoringWeights()

        return cls(
            face_posture=face_cfg,
            speech_confidence=speech_cfg,
            content_rubric=content_cfg,
            session_weights=session_w,
        )


# Global default configuration instance
DEFAULT_SCORING_CONFIG = ScoringConfig()
