"""
Editorial Service — preprocessing, heading-match parsing, strict LLM fallback,
and categorical coach-mode resolution.
"""

import html
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.database import async_session_factory
from app.models.problem import Problem
from app.models.problem_knowledge import ProblemKnowledge
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)

# Categorical Trust Matrix: (source_type, extraction_method, validation_status) -> coach_mode
COACH_MODE_MATRIX = {
    ("official_editorial", "heading_match", "user_verified"): "full_coach",
    ("official_editorial", "heading_match", "unchecked"): "cautious_coach",
    ("official_editorial", "heading_match", "format_ok"): "cautious_coach",
    ("official_editorial", "llm_parsed", "*"): "peer_mode",
    ("llm_generated", "*", "*"): "peer_mode",
}


def resolve_coach_mode(knowledge: Optional[ProblemKnowledge]) -> str:
    """Categorical policy lookup mapping knowledge provenance to coach operating mode."""
    if not knowledge or knowledge.validation_status == "user_rejected":
        return "peer_mode"

    key = (knowledge.source_type, knowledge.extraction_method, knowledge.validation_status)
    if key in COACH_MODE_MATRIX:
        return COACH_MODE_MATRIX[key]

    wildcard_key = (knowledge.source_type, knowledge.extraction_method, "*")
    if wildcard_key in COACH_MODE_MATRIX:
        return COACH_MODE_MATRIX[wildcard_key]

    return "peer_mode"


def clean_editorial_html(raw_html: str) -> str:
    r"""
    Preprocesses editorial HTML/text:
    1. Preserves raw MathJax equations ($...$, $$...$$, \(...\), \[...\]).
    2. Strips author C++ code blocks to save token budget and prevent regurgitation.
    3. Strips non-content tags (script, style, svg, iframe, img).
    4. Unescapes HTML entities.
    """
    if not raw_html:
        return ""

    # 1. Protect MathJax formulas with placeholders
    mathjax_blocks: List[str] = []

    def save_math(match):
        idx = len(mathjax_blocks)
        mathjax_blocks.append(match.group(0))
        return f" __MATHJAX_{idx}__ "

    # Protect $$...$$, \[...\], \(...\), and $...$
    text = re.sub(r"\$\$.*?\$\$", save_math, raw_html, flags=re.DOTALL)
    text = re.sub(r"\\\[.*?\\\]", save_math, text, flags=re.DOTALL)
    text = re.sub(r"\\\(.*?\\\)", save_math, text, flags=re.DOTALL)
    text = re.sub(r"(?<!\\)\$([^\$\n]+?)\$", save_math, text)

    # 2. Strip code snippets and pre blocks (author's C++ solution code)
    text = re.sub(r"<pre\b[^>]*>.*?</pre>", " [Solution code omitted] ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<code\b[^>]*>.*?</code>", " [Code omitted] ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<div[^>]*class=["\'][^"\']*\b(source|program-source|spoiler-content)\b[^"\']*["\'][^>]*>.*?</div>', " [Code omitted] ", text, flags=re.DOTALL | re.IGNORECASE)

    # 3. Strip non-content / layout tags
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<svg\b[^>]*>.*?</svg>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<iframe\b[^>]*>.*?</iframe>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<img\b[^>]*>", " ", text, flags=re.IGNORECASE)

    # 4. Restore MathJax formulas
    for i, math_str in enumerate(mathjax_blocks):
        text = text.replace(f"__MATHJAX_{i}__", math_str)

    # 5. Clean up HTML entities and whitespace
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_problem_section_by_heading(
    cleaned_html: str,
    problem_index: Optional[str],
    problem_title: Optional[str] = None,
) -> Optional[str]:
    """
    Extracts the editorial section for a specific problem using regex on headings.
    Handles:
    - Standard headings: "Problem A. Title", "<h3>A. Title</h3>"
    - Combined problem headings: "Problems C1 and C2. Title", "C1, C2"
    - Spoiler containers: '<div class="spoiler-title">Problem B</div>'
    """
    if not cleaned_html or not problem_index:
        return None

    # Pattern identifying any problem heading:
    # Matches <h1-6>, <strong>, <b>, or spoiler tags with problem index (e.g. A, B1, C)
    # Also matches combined: C1 and C2, C1, C2, etc.
    heading_regex = re.compile(
        r"(?i)(?:<(?P<tag>h[1-6]|strong|b)\b[^>]*>|title=[\"']|class=[\"'][^\"']*spoiler-title[^\"']*[\"'][^>]*>)"
        r"\s*(?:Problems?\s*)?"
        r"(?P<index>[A-Z][0-9]?(?:\s*(?:and|&|,|-)\s*[A-Z][0-9]?)?)"
        r"(?:\s*[:.\-]\s*|\s+)"
        r"(?P<title>[^<\n\"']+)?",
        re.MULTILINE,
    )

    matches = list(heading_regex.finditer(cleaned_html))
    if not matches:
        return None

    target_clean = problem_index.upper().strip()

    target_match_idx = -1
    for i, m in enumerate(matches):
        raw_idx = m.group("index").upper()
        # Check if target index is in this heading (handles "C1" in "C1 AND C2")
        indices = [idx.upper() for idx in re.findall(r"[A-Z][0-9]?", raw_idx)]
        if target_clean in indices:
            target_match_idx = i
            break
        # Fallback check against title if provided
        if problem_title and problem_title.lower() in (m.group("title") or "").lower():
            target_match_idx = i
            break

    if target_match_idx == -1:
        return None

    start_pos = matches[target_match_idx].start()
    # Section ends at the next problem heading or EOF
    if target_match_idx + 1 < len(matches):
        end_pos = matches[target_match_idx + 1].start()
        section_text = cleaned_html[start_pos:end_pos]
    else:
        section_text = cleaned_html[start_pos:]

    # Remove residual HTML markup within the extracted section
    clean_section = re.sub(r"<[^>]+>", " ", section_text)
    clean_section = re.sub(r"\s+", " ", clean_section).strip()

    if len(clean_section) >= 30:
        return clean_section

    return None


class EditorialService:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    async def ingest_editorial(
        self,
        problem_id: int,
        raw_editorial: str,
        editorial_url: Optional[str] = None,
    ) -> ProblemKnowledge:
        """
        Ingests editorial text for a problem:
        1. Preprocesses HTML (stripping C++ code, protecting MathJax).
        2. Attempts heading-match extraction.
        3. If heading-match fails, falls back to strict LLM extraction.
        4. Saves structured knowledge into problem_knowledge table.
        """
        async with async_session_factory() as session:
            prob_res = await session.execute(
                select(Problem).where(Problem.id == problem_id)
            )
            problem = prob_res.scalar_one_or_none()
            if not problem:
                raise ValueError(f"Problem {problem_id} not found")

        # 1. Preprocess HTML
        cleaned_text = clean_editorial_html(raw_editorial)

        # 2. Heading-Match Extraction
        section = extract_problem_section_by_heading(
            cleaned_text, problem.problem_index, problem.title
        )

        extraction_method = "heading_match" if section else "llm_parsed"

        # 3. LLM Extraction (Structured JSON)
        if extraction_method == "heading_match":
            system_prompt = (
                "You are an editorial knowledge extractor for competitive programming.\n"
                "Extract structured knowledge ONLY from the provided problem editorial section.\n"
                "Do NOT extrapolate, hallucinate, or add details not present in the text.\n"
                "Return a JSON object with keys:\n"
                "- 'approach_summary': string (2-3 sentences explaining the general idea)\n"
                "- 'key_insight': string (the fundamental conceptual or mathematical breakthrough)\n"
                "- 'techniques': list of strings (algorithm/data structure tags, e.g. ['greedy', 'dsu'])\n"
                "- 'common_pitfalls': list of strings (mistakes mentioned or time complexity pitfalls)\n"
            )
            user_prompt = f"Problem {problem.problem_index}: {problem.title}\nEditorial Text:\n{section}"
        else:
            system_prompt = (
                "You are an editorial knowledge extractor for competitive programming.\n"
                f"The provided text is an entire contest editorial. Extract the section specifically "
                f"for Problem {problem.problem_index} ({problem.title}).\n"
                "Extract ONLY from this text. Do NOT hallucinate. If not found, return empty strings.\n"
                "Return a JSON object with keys:\n"
                "- 'approach_summary': string\n"
                "- 'key_insight': string\n"
                "- 'techniques': list of strings\n"
                "- 'common_pitfalls': list of strings\n"
            )
            user_prompt = f"Target Problem: {problem.problem_index} - {problem.title}\nFull Editorial:\n{cleaned_text[:6000]}"

        llm_resp = await self.llm_client.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            response_json=True,
            caller="editorial_extractor",
        )

        try:
            data = llm_resp.json()
        except Exception:
            data = {
                "approach_summary": "Extracted approach",
                "key_insight": "Key observation",
                "techniques": problem.tags or [],
                "common_pitfalls": [],
            }

        # 4. Upsert into problem_knowledge
        async with async_session_factory() as session:
            stmt = insert(ProblemKnowledge).values(
                problem_id=problem_id,
                source_type="official_editorial",
                extraction_method=extraction_method,
                validation_status="unchecked",
                approach_summary=data.get("approach_summary", ""),
                key_insight=data.get("key_insight", ""),
                techniques=data.get("techniques", []),
                common_pitfalls=data.get("common_pitfalls", []),
                editorial_url=editorial_url,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["problem_id", "source_type"],
                set_={
                    "extraction_method": stmt.excluded.extraction_method,
                    "validation_status": "unchecked",
                    "approach_summary": stmt.excluded.approach_summary,
                    "key_insight": stmt.excluded.key_insight,
                    "techniques": stmt.excluded.techniques,
                    "common_pitfalls": stmt.excluded.common_pitfalls,
                    "editorial_url": stmt.excluded.editorial_url,
                },
            )
            await session.execute(stmt)
            await session.commit()

            res = await session.execute(
                select(ProblemKnowledge).where(
                    ProblemKnowledge.problem_id == problem_id,
                    ProblemKnowledge.source_type == "official_editorial",
                )
            )
            return res.scalar_one()
