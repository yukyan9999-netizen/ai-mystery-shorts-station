from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class EpisodeIdea(BaseModel):
    id: str
    topic: str
    country_or_region: str
    premise: str
    fictional_seed: bool = True
    source_note: str
    used: bool = False


class IdeaCandidate(BaseModel):
    topic: str
    country_or_region: str
    premise: str
    source_summary: str
    source_urls: list[str] = Field(default_factory=list)
    originality_rule: str
    facts_to_verify: list[str] = Field(default_factory=list)


class IdeaSearchResult(BaseModel):
    character_comment: str
    candidates: list[IdeaCandidate] = Field(min_length=3, max_length=5)


class StorySkeleton(BaseModel):
    character_comment: str
    working_title: str
    country_or_region: str
    core_item: str
    protagonist: str
    setup: str
    small_mistake: str
    escalation: str
    absurd_payoff: str
    originality_changes: list[str]
    facts_to_verify: list[str] = Field(default_factory=list)
    avoid_copying: list[str] = Field(default_factory=list)


class ProgrammingDirection(BaseModel):
    character_comment: str = ""
    selected_idea_id: str
    topic: str
    production_angle: str
    selection_reason: str
    originality_devices: list[str]
    duplicate_risk: Literal["low", "medium", "high"]
    facts_to_verify: list[str] = Field(default_factory=list)
    avoid_list: list[str] = Field(default_factory=list)


class ComicPanel(BaseModel):
    panel_number: int = Field(ge=1, le=10)
    story_beat: Literal[
        "ordinary_situation", "small_mistake", "misunderstanding_grows", "absurd_payoff"
    ]
    scene: str
    action: str
    dialogue: list[str]
    narration: str = ""
    image_prompt: str


class StoryDraft(BaseModel):
    character_comment: str = ""
    title_working: str
    logline: str
    fictional_notice: str
    characters: list[str]
    panels: list[ComicPanel]
    factual_claims: list[str] = Field(default_factory=list)
    revision_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_panel_count(self) -> "StoryDraft":
        if not 4 <= len(self.panels) <= 10:
            raise ValueError("The story must contain between 4 and 10 panels.")
        numbers = [panel.panel_number for panel in self.panels]
        if sorted(numbers) != list(range(1, len(self.panels) + 1)):
            raise ValueError("Panel numbers must be consecutive starting at 1.")
        return self


class ComedyRevision(BaseModel):
    character_comment: str = ""
    revised_story: StoryDraft
    strengthened_jokes: list[str]
    final_panel_twist: str
    change_summary: list[str]


class ResearchFinding(BaseModel):
    claim: str
    status: Literal["verified_internally", "needs_verification", "fictionalize", "remove"]
    reasoning: str
    suggested_change: str = ""


class TravelReview(BaseModel):
    character_comment: str = ""
    verdict: Literal["pass", "revise"]
    findings: list[ResearchFinding]
    cultural_safety_notes: list[str]
    required_changes: list[str] = Field(default_factory=list)
    verification_notice: str


class PanelPerformance(BaseModel):
    panel_number: int = Field(ge=1, le=10)
    expression: str
    pose: str
    gaze: str
    framing: str


class CharacterPlan(BaseModel):
    character_comment: str = ""
    protagonist_profile: str
    visual_identity: str
    personality: str
    consistency_token: str
    panel_performances: list[PanelPerformance]
    continuity_checklist: list[str]


class EditBeat(BaseModel):
    panel_number: int = Field(ge=1, le=10)
    duration_seconds: float = Field(gt=0)
    subtitle: str
    subtitle_position: Literal["top", "middle", "bottom"]
    subtitle_in_seconds: float = Field(ge=0)
    sound_effect: str
    transition: str


class ShortsPlan(BaseModel):
    character_comment: str = ""
    aspect_ratio: Literal["9:16"] = "9:16"
    total_duration_seconds: float = Field(ge=20, le=35)
    hook: str
    beats: list[EditBeat]
    audio_direction: str
    accessibility_notes: list[str]

    @model_validator(mode="after")
    def validate_duration(self) -> "ShortsPlan":
        total = round(sum(beat.duration_seconds for beat in self.beats), 2)
        if not 4 <= len(self.beats) <= 10:
            raise ValueError("The shorts plan must contain between 4 and 10 edit beats.")
        numbers = [beat.panel_number for beat in self.beats]
        if sorted(numbers) != list(range(1, len(self.beats) + 1)):
            raise ValueError("Edit beat panel numbers must be consecutive starting at 1.")
        if abs(total - self.total_duration_seconds) > 0.05:
            raise ValueError("Beat durations must add up to the total duration.")
        return self


class VoiceCharacter(BaseModel):
    speaker_name: str
    role: Literal["protagonist", "staff", "companion", "narrator"]
    voice: Literal[
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "nova",
        "onyx",
        "sage",
        "shimmer",
        "verse",
        "marin",
        "cedar",
    ]
    acting_direction: str


class VoicePanelLine(BaseModel):
    panel_number: int = Field(ge=1, le=10)
    speaker_name: str
    spoken_text: str
    emotion: str


class VoiceCastPlan(BaseModel):
    character_comment: str
    cast: list[VoiceCharacter]
    panel_lines: list[VoicePanelLine]


class YouTubePackage(BaseModel):
    character_comment: str = ""
    title_candidates: list[str] = Field(min_length=5, max_length=5)
    thumbnail_text_candidates: list[str] = Field(min_length=5, max_length=5)
    description: str
    hashtags: list[str]


class RiskItem(BaseModel):
    category: Literal[
        "copyright",
        "privacy",
        "real_event_copy",
        "cultural_disparagement",
        "unverified_travel_info",
        "platform_misleading",
        "other",
    ]
    severity: Literal["low", "medium", "high"]
    evidence: str
    required_fix: str


class ComplianceReview(BaseModel):
    character_comment: str = ""
    verdict: Literal["pass", "hold", "discard"]
    summary: str
    risks: list[RiskItem] = Field(default_factory=list)
    revision_request_for_story_writer: list[str] = Field(default_factory=list)
    revision_request_for_comedy_writer: list[str] = Field(default_factory=list)
    human_review_checklist: list[str]


class ManagementIntervention(BaseModel):
    character_comment: str = ""
    delayed_role: str
    bottleneck_assessment: str
    keep_required: list[str]
    skip_or_shorten: list[str]
    urgent_instructions: list[str] = Field(min_length=1, max_length=3)
    reason: str


class HumanApproval(BaseModel):
    status: Literal["pending", "approved", "rejected"] = "pending"
    approver: str | None = None
    approved_at: str | None = None
    note: str = "사람 승인 전에는 업로드할 수 없습니다."

    @classmethod
    def approved(cls, approver: str) -> "HumanApproval":
        return cls(
            status="approved",
            approver=approver,
            approved_at=datetime.now(timezone.utc).isoformat(),
            note="사람 검토자가 승인했습니다.",
        )


class VideoAssets(BaseModel):
    status: Literal["not_rendered", "rendered", "failed"] = "not_rendered"
    panel_images: list[str] = Field(default_factory=list)
    panel_frames: list[str] = Field(default_factory=list)
    narration_files: list[str] = Field(default_factory=list)
    subtitles_file: str | None = None
    thumbnail_file: str | None = None
    final_video_file: str | None = None
    render_manifest_file: str | None = None
    ai_voice_disclosure: str = "이 영상에는 AI로 생성한 음성이 사용되었습니다."


class FinalEpisode(BaseModel):
    run_id: str
    topic: str
    production_direction: ProgrammingDirection
    story: StoryDraft
    # Legacy compatibility only. New productions no longer run a fact-check agent.
    travel_review: TravelReview | None = None
    character_direction: CharacterPlan
    shorts_editing_guide: ShortsPlan
    youtube_package: YouTubePackage
    compliance_review: ComplianceReview
    revision_count: int
    completion_status: Literal[
        "compliance_passed", "conditional_after_revision_limit"
    ] = "compliance_passed"
    mandatory_human_review: bool = True
    unresolved_review_items: list[str] = Field(default_factory=list)
    video_assets: VideoAssets = Field(default_factory=VideoAssets)
    human_approval: HumanApproval = Field(default_factory=HumanApproval)
    upload_ready: bool = False
