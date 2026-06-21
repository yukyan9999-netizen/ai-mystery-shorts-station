"""Crawl Hacker News, Wikipedia, and Korean sources for trending topics."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
_TIMEOUT = 10


def _fetch_json(url: str, headers: dict[str, str] | None = None) -> Any:
    hdrs = {"User-Agent": _USER_AGENT, **(headers or {})}
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


_HN_SCIENCE_KEYWORDS = re.compile(
    r"space|universe|black.?hole|quantum|brain|dna|fossil|ancient|"
    r"dinosaur|mars|nasa|ocean|volcano|earthquake|asteroid|comet|"
    r"mystery|secret|discovery|unexplained|history|roman|egypt|"
    r"maya|civilization|physics|biology|evolution|genetic|virus|"
    r"ai|robot|nuclear|climate|deep.?sea|moon|sun|star|galaxy|"
    r"pyramid|archaeology|neuro|sleep|dream|memory|gravity",
    re.IGNORECASE,
)


class TopicCrawler:
    def __init__(self) -> None:
        pass

    def crawl_all(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        results.extend(self.crawl_hacker_news())
        results.extend(self.crawl_wikipedia_featured())
        results.extend(self.crawl_korean_wikipedia_good())

        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in results:
            key = re.sub(r"\s+", "", item["title"].lower())
            if key not in seen:
                seen.add(key)
                unique.append(item)

        unique.sort(key=lambda x: x.get("score", 0), reverse=True)
        return unique[:30]

    def crawl_hacker_news(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            ids = _fetch_json(
                "https://hacker-news.firebaseio.com/v0/topstories.json"
            )[:80]
            for sid in ids:
                try:
                    item = _fetch_json(
                        f"https://hacker-news.firebaseio.com/v0/item/{sid}.json"
                    )
                    title = item.get("title", "")
                    score = item.get("score", 0)
                    if score < 100 or not _HN_SCIENCE_KEYWORDS.search(title):
                        continue
                    results.append({
                        "title": title,
                        "source": "hackernews",
                        "score": score,
                        "category": "과학·자연 미스터리",
                        "url": item.get("url", ""),
                    })
                    if len(results) >= 10:
                        break
                except Exception:
                    continue
        except Exception:
            logger.debug("Failed to crawl Hacker News", exc_info=True)
        return results

    def crawl_wikipedia_featured(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            data = _fetch_json(
                "https://en.wikipedia.org/w/api.php?"
                + urllib.parse.urlencode({
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": "Category:Featured articles",
                    "cmlimit": "50",
                    "cmtype": "page",
                    "cmsort": "timestamp",
                    "cmdir": "desc",
                    "format": "json",
                })
            )
            science_pattern = re.compile(
                r"black.?hole|quantum|ancient|dinosaur|mars|nasa|ocean|"
                r"volcano|asteroid|history|roman|egypt|pyramid|mystery|"
                r"universe|evolution|nuclear|moon|sun|virus|brain|"
                r"civilization|archaeology|physics|fossil|comet|galaxy",
                re.IGNORECASE,
            )
            for member in data.get("query", {}).get("categorymembers", []):
                title = member.get("title", "")
                if science_pattern.search(title):
                    results.append({
                        "title": title,
                        "source": "wikipedia_featured",
                        "score": 200,
                        "category": "과학·자연 미스터리",
                        "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}",
                    })
                    if len(results) >= 8:
                        break
        except Exception:
            logger.debug("Failed to crawl Wikipedia featured", exc_info=True)
        return results

    def crawl_korean_wikipedia_good(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            data = _fetch_json(
                "https://ko.wikipedia.org/w/api.php?"
                + urllib.parse.urlencode({
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": "분류:알찬 글",
                    "cmlimit": "50",
                    "cmtype": "page",
                    "cmsort": "timestamp",
                    "cmdir": "desc",
                    "format": "json",
                })
            )
            science_pattern = re.compile(
                r"우주|행성|블랙홀|화성|달|태양|공룡|화산|지진|"
                r"소행성|역사|로마|이집트|피라미드|미스터리|"
                r"핵|바이러스|뇌|진화|유전|고대|문명|물리|"
                r"화학|생물|천문|은하|성운|중력|양자|전쟁|"
                r"제국|왕조|발견|실험|과학",
            )
            for member in data.get("query", {}).get("categorymembers", []):
                title = member.get("title", "")
                if science_pattern.search(title):
                    results.append({
                        "title": title,
                        "source": "ko_wikipedia",
                        "score": 150,
                        "category": "한국 위키 알찬 글",
                        "url": f"https://ko.wikipedia.org/wiki/{urllib.parse.quote(title)}",
                    })
                    if len(results) >= 8:
                        break
        except Exception:
            logger.debug("Failed to crawl Korean Wikipedia", exc_info=True)
        return results
