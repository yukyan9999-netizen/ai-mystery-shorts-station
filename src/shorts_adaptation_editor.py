from __future__ import annotations

import re
from pathlib import Path

from src.knowledge_models import (
    KnowledgeScript,
    ShortsAdaptationResult,
)
from src.knowledge_runtime import KnowledgeRuntime


class ShortsAdaptationEditor:
    def __init__(self, root: Path) -> None:
        self.runtime = KnowledgeRuntime(root)

    def adapt(self, source_script: KnowledgeScript) -> ShortsAdaptationResult:
        payload = {
            "source_script": {
                "title": source_script.title,
                "category": source_script.category,
                "timed_script": source_script.timed_script.model_dump(
                    mode="json"
                ),
                "full_narration": source_script.full_narration,
                "fact_hypothesis_labels": list(
                    source_script.fact_hypothesis_labels
                ),
            },
            "isolation_rules": [
                "입력된 source_script 외에는 아무 자료도 사용하지 않는다.",
                "다른 AI의 평가, 보고서, 의견을 요청하거나 추측하지 않는다.",
                "검색하지 않는다.",
                "사실을 추가하거나 삭제하지 않는다.",
                "사실의 순서와 표현만 쇼츠에 맞게 바꾼다.",
            ],
        }
        last_error: RuntimeError | None = None
        for attempt in range(2):
            current_payload = dict(payload)
            if attempt and last_error:
                current_payload["same_editor_fact_preservation_retry"] = {
                    "problem": str(last_error),
                    "instruction": (
                        "다른 자료를 보지 말고 원본 대본에서 빠진 보호 정보를 "
                        "복원한 뒤 다시 각색한다."
                    ),
                }
            result = self.runtime.run_isolated_structured(
                "ShortsAdaptationEditor",
                ShortsAdaptationResult,
                current_payload,
                max_tokens=5500,
                max_turns=4,
                timeout_seconds=90,
            )
            if not isinstance(result, ShortsAdaptationResult):
                result = ShortsAdaptationResult.model_validate(result)
            try:
                self._validate_protected_content(
                    source_script,
                    result.adapted_script,
                )
            except RuntimeError as exc:
                last_error = exc
                continue
            result.adapted_script = result.adapted_script.model_copy(
                update={
                    "category": source_script.category,
                    "fact_hypothesis_labels": list(
                        source_script.fact_hypothesis_labels
                    ),
                    "reference_patterns_used": list(
                        source_script.reference_patterns_used
                    ),
                }
            )
            return result
        raise RuntimeError(
            "쇼츠 각색 에디터가 원본 사실을 모두 보존하지 못했습니다."
        ) from last_error

    @staticmethod
    def _script_text(script: KnowledgeScript) -> str:
        timed = script.timed_script
        return " ".join(
            [
                timed.hook_0_3,
                timed.background_3_12,
                *timed.facts_12_35,
                timed.mystery_35_50,
                timed.close_50_60,
                script.full_narration,
            ]
        )

    def _validate_protected_content(
        self,
        source: KnowledgeScript,
        adapted: KnowledgeScript,
    ) -> None:
        source_text = self._script_text(source)
        adapted_text = self._script_text(adapted)
        protected_numbers = set(
            re.findall(
                r"(?<![\w.])\d+(?:[.,]\d+)?(?:%|년|초|분|시간|배|명|개)?",
                source_text,
            )
        )
        missing_numbers = sorted(
            token for token in protected_numbers if token not in adapted_text
        )
        protected_acronyms = set(
            re.findall(r"\b[A-Z][A-Z0-9-]{1,}\b", source_text)
        )
        missing_acronyms = sorted(
            token for token in protected_acronyms if token not in adapted_text
        )
        if missing_numbers or missing_acronyms:
            missing = ", ".join([*missing_numbers, *missing_acronyms])
            raise RuntimeError(
                "쇼츠 각색 과정에서 원본의 보호 정보가 빠졌습니다: " + missing
            )
        source_length = len(re.sub(r"\s+", "", source.full_narration))
        adapted_length = len(re.sub(r"\s+", "", adapted.full_narration))
        if source_length and adapted_length < source_length * 0.55:
            raise RuntimeError(
                "각색본이 원본보다 지나치게 짧아 사실 누락 가능성이 있습니다."
            )
