"""AI image library for saving and reusing generated images across videos."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "space": [
        "space", "planet", "star", "galaxy", "moon", "sun", "mars", "pluto",
        "jupiter", "saturn", "asteroid", "comet", "nebula", "orbit", "rocket",
        "astronaut", "cosmos", "universe", "solar", "lunar", "meteor",
        "constellation", "black hole", "spacecraft", "telescope",
    ],
    "history": [
        "roman", "ancient", "medieval", "war", "empire", "egypt", "greek",
        "dynasty", "kingdom", "castle", "ruins", "artifact", "civilization",
        "pharaoh", "knight", "viking", "samurai", "temple", "pyramid",
        "colonial", "revolution", "battle", "emperor", "monarch",
    ],
    "science": [
        "dna", "brain", "cell", "experiment", "laboratory", "atom", "molecule",
        "chemical", "physics", "biology", "microscope", "quantum", "gene",
        "virus", "bacteria", "neuron", "protein", "evolution", "fossil",
        "electron", "radiation", "formula", "research",
    ],
    "nature": [
        "ocean", "volcano", "mountain", "forest", "river", "desert", "island",
        "cave", "glacier", "waterfall", "coral", "reef", "jungle", "aurora",
        "earthquake", "tsunami", "tornado", "hurricane", "wildlife", "animal",
        "tree", "flower", "lake", "cliff", "canyon",
    ],
    "mystery": [
        "mystery", "unknown", "unexplained", "paranormal", "ufo", "alien",
        "ghost", "legend", "myth", "cryptid", "bermuda", "atlantis",
        "conspiracy", "supernatural", "enigma", "phenomenon", "bizarre",
        "haunted", "curse", "prophecy", "omen", "ritual",
    ],
}


class ImageLibrary:
    """Manages a local library of AI-generated images for cross-video reuse."""

    def __init__(self, project_root: Path) -> None:
        self.root = project_root.resolve()
        self.library_dir = self.root / "library"
        self.index_path = self.library_dir / "index.json"

    def _load_index(self) -> list[dict]:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        return []

    def _save_index(self, index: list[dict]) -> None:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def detect_category(keywords: list[str]) -> str:
        """Auto-detect category from keywords."""
        lower_kw = [k.lower() for k in keywords]
        scores: dict[str, int] = {}
        for category, cat_words in CATEGORY_KEYWORDS.items():
            score = 0
            for kw in lower_kw:
                for cw in cat_words:
                    if cw in kw or kw in cw:
                        score += 1
                        break
            scores[category] = score
        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        if scores[best] == 0:
            return "mystery"  # default fallback
        return best

    def save(
        self,
        image_path: Path,
        keywords: list[str],
        prompt: str,
        category: str | None = None,
    ) -> None:
        """Save an image to the library with metadata."""
        image_path = Path(image_path)
        if not image_path.exists():
            return

        if category is None:
            category = self.detect_category(keywords)

        index = self._load_index()

        # Don't save duplicates (same prompt)
        for entry in index:
            if entry.get("prompt") == prompt:
                return

        # Determine filename
        cat_dir = self.library_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)

        existing = sorted(cat_dir.glob(f"*{image_path.suffix}"))
        next_num = len(existing) + 1
        # Build a short name from first keyword
        name_base = keywords[0].replace(" ", "_") if keywords else "image"
        dest_name = f"{name_base}_{next_num:03d}{image_path.suffix}"
        dest = cat_dir / dest_name

        shutil.copy2(str(image_path), str(dest))

        entry = {
            "file": str(dest.relative_to(self.root)),
            "keywords": [k.lower() for k in keywords],
            "prompt": prompt,
            "category": category,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        index.append(entry)
        self._save_index(index)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Search library by keyword matching. Returns matches with score."""
        index = self._load_index()
        if not index:
            return []

        query_words = [w.lower() for w in query.split() if len(w) >= 2]
        if not query_words:
            return []

        results: list[dict] = []
        for entry in index:
            entry_keywords = entry.get("keywords", [])
            prompt_lower = entry.get("prompt", "").lower()

            match_count = 0
            for qw in query_words:
                # Check keywords
                for ek in entry_keywords:
                    if qw in ek or ek in qw:
                        match_count += 1
                        break
                else:
                    # Check prompt as fallback
                    if qw in prompt_lower:
                        match_count += 0.5

            if match_count > 0:
                score = match_count / len(query_words)
                file_path = self.root / entry["file"]
                if file_path.exists():
                    results.append({
                        "file": str(file_path),
                        "score": round(score, 3),
                        "keywords": entry_keywords,
                        "prompt": entry.get("prompt", ""),
                        "category": entry.get("category", ""),
                    })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    @staticmethod
    def extract_keywords(prompt: str) -> list[str]:
        """Extract meaningful keywords from an image prompt."""
        import re

        # Remove common filler words
        stop_words = {
            "the", "a", "an", "in", "on", "at", "of", "and", "or", "with",
            "for", "to", "is", "are", "was", "were", "be", "been", "being",
            "no", "not", "this", "that", "it", "its", "from", "by", "as",
            "into", "very", "much", "any", "all", "some", "do", "does",
            "vertical", "cinematic", "composition", "camera", "angle",
            "absolutely", "anywhere", "captions", "labels", "signs",
            "letters", "words", "logos", "badges", "watermark", "text",
            "image", "visual", "documentary", "mystery", "style",
        }
        words = re.findall(r"[a-zA-Z]+", prompt.lower())
        keywords = [w for w in words if w not in stop_words and len(w) >= 3]
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for w in keywords:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        return unique[:10]
