from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


KnowledgeCategory = Literal[
    "역사 미스터리",
    "우주 미스터리",
    "고대문명과 놀라운 기술",
    "과학·자연 미스터리",
    "가상 시나리오",
]


class KnowledgeScore(BaseModel):
    hook: int = Field(ge=0, le=35)
    source_traceability: int = Field(ge=0, le=10)
    visualization: int = Field(ge=0, le=25)
    sixty_second_fit: int = Field(ge=0, le=20)
    comment_potential: int = Field(ge=0, le=10)

    @property
    def total(self) -> int:
        return (
            self.hook
            + self.source_traceability
            + self.visualization
            + self.sixty_second_fit
            + self.comment_potential
        )


class SelectionCriteria(BaseModel):
    title_curiosity: bool
    source_or_claim_traceable: bool
    explainable_in_60_seconds: bool
    easy_to_visualize: bool
    has_twist_or_misconception_resolution: bool
    has_comment_question: bool
    interesting_without_exaggeration: bool

    @property
    def passed_count(self) -> int:
        return sum(self.model_dump().values())


class KnowledgeCandidate(BaseModel):
    title: str
    category: KnowledgeCategory
    one_line_hook: str
    plain_language_summary: str = ""
    audience_difficulty: Literal["easy", "medium", "hard"] = "easy"
    required_background_seconds: int = Field(default=8, ge=0, le=60)
    unfamiliar_terms: list[str] = Field(default_factory=list, max_length=5)
    self_insert_question: str = ""
    core_facts: list[str] = Field(min_length=2, max_length=5)
    verification_points: list[str] = Field(default_factory=list)
    fact_hypothesis_distinction: str
    visualization_ideas: list[str] = Field(min_length=2, max_length=6)
    comment_question: str
    criteria: SelectionCriteria
    score: KnowledgeScore
    total_score: int = 0
    selection_status: Literal["rejected", "candidate", "priority"] = "rejected"
    rejection_reason: str = ""
    selection_override: Literal["", "user_direct_topic"] = ""

    @model_validator(mode="after")
    def calculate_selection(self) -> "KnowledgeCandidate":
        self.total_score = self.score.total
        if self.selection_override == "user_direct_topic":
            self.selection_status = (
                "priority" if self.total_score >= 85 else "candidate"
            )
            self.rejection_reason = ""
            return self
        complexity_markers = (
            "통계",
            "기계학습",
            "알고리즘",
            "프레임 분석",
            "레이더",
            "센서 보정",
            "생체 신호",
            "오가노이드",
            "윤리적",
            "존재론",
            "담론",
            "관할권",
            "문헌 해독",
            "패턴 분석",
            "UAP",
            "시공간 곡률",
        )
        topic_text = f"{self.title} {self.one_line_hook}"
        complexity_count = sum(
            marker.lower() in topic_text.lower() for marker in complexity_markers
        )
        if not self.plain_language_summary.strip():
            self.selection_status = "rejected"
            self.rejection_reason = "쉬운 한 줄 설명이 없음"
        elif not self.self_insert_question.strip():
            self.selection_status = "rejected"
            self.rejection_reason = "시청자가 자신을 대입할 질문이 없음"
        elif complexity_count >= 2:
            self.selection_status = "rejected"
            self.rejection_reason = "전문 분석 용어가 많아 주제가 어려움"
        elif self.audience_difficulty == "hard":
            self.selection_status = "rejected"
            self.rejection_reason = "일반 시청자 기준 난이도 높음"
        elif self.required_background_seconds > 10:
            self.selection_status = "rejected"
            self.rejection_reason = "이해에 필요한 배경 설명이 10초를 초과"
        elif len(self.unfamiliar_terms) > 2:
            self.selection_status = "rejected"
            self.rejection_reason = "낯선 전문용어가 2개를 초과"
        elif len(self.title) > 42:
            self.selection_status = "rejected"
            self.rejection_reason = "제목이 길고 복잡함"
        elif self.criteria.passed_count < 3:
            self.selection_status = "rejected"
            self.rejection_reason = "선정 조건 7개 중 3개 미만 충족"
        elif self.total_score < 60:
            self.selection_status = "rejected"
            self.rejection_reason = f"총점 {self.total_score}점으로 60점 미만"
        elif self.total_score >= 85:
            self.selection_status = "priority"
            self.rejection_reason = ""
        else:
            self.selection_status = "candidate"
            self.rejection_reason = ""
        return self


class DirectTopicPlan(BaseModel):
    user_topic: str
    topic_hunter_reply: str
    candidate: KnowledgeCandidate


class DailyTopicBatch(BaseModel):
    production_date: date
    schedule_reason: str
    category: KnowledgeCategory
    character_comment: str
    candidates: list[KnowledgeCandidate] = Field(min_length=1, max_length=3)


class TrendSignal(BaseModel):
    topic: str
    source_platforms: list[str]
    audience_demand: str
    why_now: str
    mystery_seed: str
    opportunity_score: int = Field(ge=0, le=100)


class TrendReport(BaseModel):
    production_date: date
    requested_direction: str = ""
    character_comment: str
    trending_topics: list[TrendSignal] = Field(min_length=3, max_length=12)


class ResearchEvidence(BaseModel):
    claim: str
    evidence: str
    source_title: str
    source_url: str
    evidence_type: Literal[
        "paper",
        "experiment",
        "data",
        "primary_record",
        "museum_object",
        "historical_analysis",
        "news_report",
    ]
    confidence: Literal["high", "medium", "low"]


class ResearchDossier(BaseModel):
    candidate_title: str
    researcher_role: Literal["scientific", "historical"]
    character_comment: str
    verified_anchor: str
    evidence: list[ResearchEvidence] = Field(min_length=2, max_length=12)
    scientists_or_historical_figures: list[str] = Field(default_factory=list)
    experiments_or_records: list[str] = Field(default_factory=list)
    unanswered_questions: list[str] = Field(min_length=1, max_length=8)
    forgotten_or_unusual_details: list[str] = Field(default_factory=list)


class CuriosityReport(BaseModel):
    character_comment: str
    why_strange: list[str] = Field(min_length=2, max_length=6)
    why_anyone_should_care: list[str] = Field(min_length=2, max_length=6)
    hidden_mystery: str
    weirdest_implication: str
    hooks: list[str] = Field(min_length=3, max_length=8)
    mystery_angles: list[str] = Field(min_length=3, max_length=8)
    reference_patterns_used: list[str] = Field(default_factory=list, max_length=3)


class ConsequenceItem(BaseModel):
    category: Literal[
        "biological",
        "psychological",
        "social",
        "economic",
        "political",
        "civilizational",
        "identity",
    ]
    consequence: str
    realism: Literal["likely", "plausible", "speculative"]
    impact_score: int = Field(ge=0, le=100)


class ConsequenceReport(BaseModel):
    character_comment: str
    consequences: list[ConsequenceItem] = Field(min_length=5, max_length=14)
    highest_impact_consequence: str
    human_consequence: str
    civilizational_consequence: str
    reference_patterns_used: list[str] = Field(default_factory=list, max_length=3)


class GihwanReport(BaseModel):
    character_comment: str
    question_chain: list[str] = Field(min_length=5, max_length=12)
    human_loss: str
    identity_change: str
    civilization_change: str
    unforgettable_core_question: str
    reference_patterns_used: list[str] = Field(default_factory=list, max_length=3)


class NarrativeArchitecture(BaseModel):
    character_comment: str
    hook: str
    mystery: str
    evidence: list[str] = Field(min_length=2, max_length=5)
    research: list[str] = Field(min_length=2, max_length=5)
    escalation: list[str] = Field(min_length=2, max_length=6)
    twist: str
    ending: str
    reveal_timing_rule: str
    reference_patterns_used: list[str] = Field(default_factory=list, max_length=3)


class AudienceSimulation(BaseModel):
    character_comment: str
    predicted_ctr_score: int = Field(ge=0, le=100)
    predicted_retention_score: int = Field(ge=0, le=100)
    predicted_comment_score: int = Field(ge=0, le=100)
    keep: list[str]
    improve: list[str]
    remove: list[str]
    weak_points: list[str]
    likely_confusion: list[str]
    verdict: Literal["strong", "revise", "weak"]
    reference_pattern_assessment: str = ""


class FactSource(BaseModel):
    title: str
    url: str
    publisher: str
    source_type: Literal[
        "primary",
        "academic",
        "government",
        "museum",
        "reputable_reference",
        "news",
        "historical_text",
        "archive",
        "community_record",
    ]


class VerifiedClaim(BaseModel):
    claim: str
    classification: Literal[
        "verified_fact",
        "current_hypothesis",
        "historical_record",
        "legend_or_folklore",
        "reported_claim",
        "uncertain",
        "simulation",
    ]
    evidence_summary: str
    safe_narration: str
    source_urls: list[str] = Field(min_length=1)


class FactCheckReport(BaseModel):
    candidate_title: str
    character_comment: str
    verdict: Literal["pass", "revise", "reject"]
    verified_claims: list[VerifiedClaim] = Field(min_length=2, max_length=8)
    prohibited_or_removed_claims: list[str] = Field(default_factory=list, max_length=8)
    required_caveats: list[str] = Field(default_factory=list, max_length=8)
    sources: list[FactSource] = Field(min_length=2, max_length=12)
    entertainment_value_note: str
    required_on_screen_labels: list[str] = Field(default_factory=list, max_length=8)
    blocking_safety_issue: bool = False
    dramatization_allowed: bool = True


class ResearchSource(BaseModel):
    title: str
    page_url: str
    direct_media_url: str = ""
    publisher_or_community: str
    source_kind: Literal[
        "official",
        "academic",
        "museum_archive",
        "news",
        "community",
        "open_media_library",
    ]
    role: Literal[
        "fact_evidence",
        "visual_asset",
        "community_lead",
        "audience_reaction",
    ]
    media_type: Literal[
        "article",
        "image",
        "video",
        "document",
        "map",
        "diagram",
        "text_post",
    ]
    license_status: Literal[
        "public_domain",
        "cc0",
        "cc_by",
        "cc_by_sa",
        "official_reuse_allowed",
        "permission_required",
        "editorial_only",
        "unknown",
    ]
    license_evidence_url: str = ""
    usable_in_final_video: bool
    suggested_use: str
    attribution_text: str = ""
    reliability_note: str


class SourceResearchReport(BaseModel):
    candidate_title: str
    character_comment: str
    research_summary: str
    sources: list[ResearchSource] = Field(min_length=6, max_length=20)
    international_community_leads: list[str] = Field(default_factory=list)
    usable_visual_asset_count: int = Field(ge=0)
    real_media_target_percent: int = Field(default=65, ge=50, le=85)
    rights_warnings: list[str] = Field(default_factory=list)


class TimedScript(BaseModel):
    hook_0_3: str
    background_3_12: str
    facts_12_35: list[str] = Field(min_length=2, max_length=3)
    mystery_35_50: str
    close_50_60: str


class KnowledgeScript(BaseModel):
    title: str
    category: KnowledgeCategory
    character_comment: str
    timed_script: TimedScript
    full_narration: str
    fact_hypothesis_labels: list[str]
    reference_patterns_used: list[str] = Field(default_factory=list, max_length=3)


class ShortsAdaptationChecks(BaseModel):
    elementary_language: bool
    sounds_like_a_friend: bool
    hooks_within_three_seconds: bool
    has_midpoint_twist_or_question: bool
    leaves_final_afterthought: bool
    feels_like_shorts_not_documentary: bool
    preserves_all_facts: bool


class ShortsAdaptationResult(BaseModel):
    character_comment: str
    adapted_script: KnowledgeScript
    checks: ShortsAdaptationChecks
    factual_change_detected: bool = False
    omitted_facts: list[str] = Field(default_factory=list)
    added_facts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_completed_adaptation(self) -> "ShortsAdaptationResult":
        if not all(self.checks.model_dump().values()):
            raise ValueError("쇼츠 각색 최종 점검을 모두 통과해야 합니다.")
        if (
            self.factual_change_detected
            or self.omitted_facts
            or self.added_facts
        ):
            raise ValueError("기존 대본의 사실을 추가하거나 삭제할 수 없습니다.")
        return self


class KnowledgeScene(BaseModel):
    scene_number: int = Field(ge=1, le=20)
    time_range: str
    visual_description: str
    image_prompt: str
    subtitle: str
    narration: str
    excluded_source_urls: list[str] = Field(default_factory=list)


class VisualPackage(BaseModel):
    character_comment: str
    scenes: list[KnowledgeScene] = Field(min_length=5, max_length=14)
    thumbnail_text_candidates: list[str] = Field(min_length=5, max_length=5)
    hashtags: list[str]
    fact_check_checklist: list[str]


class SceneAssetPlan(BaseModel):
    scene_number: int = Field(ge=1, le=20)
    asset_mode: Literal[
        "licensed_real_media",
        "official_media",
        "community_reference_only",
        "ai_reconstruction",
        "motion_graphics",
    ]
    source_page_url: str = ""
    license_status: str
    usage_instruction: str
    crop_and_motion: str
    on_screen_source_label: str = ""
    fallback_ai_prompt: str = ""


class MixedMediaPlan(BaseModel):
    character_comment: str
    target_real_media_percent: int = Field(ge=50, le=85)
    planned_real_media_percent: int = Field(ge=0, le=100)
    scene_assets: list[SceneAssetPlan] = Field(min_length=5, max_length=14)
    global_editing_rules: list[str]
    attribution_end_card: list[str]
    blocked_assets: list[str] = Field(default_factory=list)


class VideoSceneRevision(BaseModel):
    scene_number: int = Field(ge=1, le=20)
    action: Literal[
        "replace_visual",
        "recover_missing",
        "prefer_video",
        "prefer_image",
        "adjust_visual_timing",
    ]
    instruction: str
    preferred_media: Literal[
        "external_video",
        "official_media",
        "ai_image",
        "motion_graphics",
        "any",
    ] = "any"
    preserve_narration: bool = True
    preserve_subtitle: bool = True


class VideoRevisionPlan(BaseModel):
    character_comment: str
    summary: str
    scene_changes: list[VideoSceneRevision] = Field(min_length=1, max_length=12)
    preserve_script: bool = True
    preserve_voice: bool = True
    preserve_music: bool = True


class KnowledgeProductionPackage(BaseModel):
    run_id: str
    production_date: date
    category: KnowledgeCategory
    selected_candidate: KnowledgeCandidate
    trend_report: TrendReport | None = None
    scientific_research: ResearchDossier | None = None
    historical_research: ResearchDossier | None = None
    curiosity_report: CuriosityReport | None = None
    consequence_report: ConsequenceReport | None = None
    gihwan_report: GihwanReport | None = None
    narrative_architecture: NarrativeArchitecture | None = None
    audience_simulation: AudienceSimulation | None = None
    reference_brief: dict[str, Any] | None = None
    fact_check: FactCheckReport
    source_research: SourceResearchReport
    script: KnowledgeScript
    shorts_adaptation: ShortsAdaptationResult | None = None
    visual_package: VisualPackage
    mixed_media_plan: MixedMediaPlan
    human_approval_required: bool = True
    upload_ready: bool = False
    human_approval: dict[str, Any] | None = None
    video_assets: dict[str, Any] | None = None
