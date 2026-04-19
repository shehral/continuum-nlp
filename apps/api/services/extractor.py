"""Decision and entity extraction with embedding-based knowledge graph.

KG-P0-2: LLM response caching to avoid redundant API calls
KG-P0-3: Relationship type validation before storing
KG-QW-4: Extraction reasoning logging for debugging and quality analysis
ML-P2-2: Specialized prompt templates for different decision types
ML-P2-3: Post-processing confidence calibration based on extraction quality
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

import redis.asyncio as redis
from neo4j.exceptions import ClientError, DatabaseError

from config import get_settings
from db.neo4j import get_neo4j_session
from models.ontology import (
    ENTITY_ONLY_RELATIONSHIPS,
    get_canonical_name,
    validate_entity_relationship,
)
from models.provenance import (
    Provenance,
    SourceType,
    create_llm_provenance,
)
from models.schemas import DecisionCreate, Entity
from services.embeddings import get_embedding_service
from services.entity_resolver import EntityResolver
from services.llm import get_llm_client
from services.parser import Conversation
from utils.json_extraction import extract_json_from_response
from utils.logging import get_logger
from utils.vectors import cosine_similarity

logger = get_logger(__name__)

# Default values for missing decision fields (ML-QW-3)
DEFAULT_DECISION_FIELDS = {
    "confidence": 0.5,
    "context": "",
    "rationale": "",
    "options": [],
    "trigger": "Unknown trigger",
    "decision": "",
}


def apply_decision_defaults(decision_data: dict) -> dict:
    """Apply default values for missing or None decision fields (ML-QW-3).

    This ensures that incomplete decision data from LLM extraction
    or cached responses doesn't cause errors during processing.

    Args:
        decision_data: Raw decision dict from LLM or cache

    Returns:
        Decision dict with defaults applied for missing fields
    """
    result = {}
    for key, default_value in DEFAULT_DECISION_FIELDS.items():
        value = decision_data.get(key)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            result[key] = default_value
        elif isinstance(default_value, list) and not isinstance(value, list):
            # Handle case where options might be a string or other type
            result[key] = default_value
        else:
            result[key] = value
    # Preserve any extra fields not in defaults
    for key, value in decision_data.items():
        if key not in result:
            result[key] = value
    return result


# Few-shot decision extraction prompt with Chain-of-Thought reasoning
DECISION_EXTRACTION_PROMPT = """Analyze this conversation and extract any technical decisions made.

## What constitutes a decision?
A decision is a choice that affects the project direction, architecture, or implementation. This includes:
- **Explicit decisions**: "Should we use X or Y? Let's use X because..."
- **Implicit decisions**: "Let's use X for this" (even without stated alternatives)
- **Technical choices**: Framework selections, architecture patterns, tool adoptions
- **Implementation strategies**: How to solve a problem, approach to take

Each decision should have:
- A trigger (problem, requirement, or question that prompted it)
- Context (background information, constraints)
- Options (alternatives considered - can be just one if no alternatives mentioned)
- The actual decision (what was chosen)
- Rationale (why this choice was made)

## Examples

### Example 1: Single clear decision
Conversation:
"We need to pick a database. I looked at PostgreSQL and MongoDB. PostgreSQL seems better for our relational data needs and the team already knows SQL. Let's go with PostgreSQL."

Output:
```json
[
  {{
    "trigger": "Need to select a database for the project",
    "context": "Team has SQL experience, data is relational in nature",
    "options": ["PostgreSQL", "MongoDB"],
    "decision": "Use PostgreSQL as the primary database",
    "rationale": "Better fit for relational data and team already has SQL expertise",
    "confidence": 0.95
  }}
]
```

### Example 2: Multiple decisions in one conversation
Conversation:
"For the frontend, React makes sense since we're already using it elsewhere. For styling, I considered Tailwind vs CSS modules. Tailwind will speed up development, so let's use that."

Output:
```json
[
  {{
    "trigger": "Need to choose frontend framework",
    "context": "Team already using React in other projects",
    "options": ["React"],
    "decision": "Use React for the frontend",
    "rationale": "Consistency with existing projects and team familiarity",
    "confidence": 0.9
  }},
  {{
    "trigger": "Need to choose a styling approach",
    "context": "Building frontend with React",
    "options": ["Tailwind CSS", "CSS modules"],
    "decision": "Use Tailwind CSS for styling",
    "rationale": "Faster development velocity with utility classes",
    "confidence": 0.85
  }}
]
```

### Example 3: Implicit decision (no alternatives stated)
Conversation:
"Let's add TypeScript to this component for better type safety. I'll update the imports and add interfaces."

Output:
```json
[
  {{
    "trigger": "Need for better type safety in component",
    "context": "Existing component lacks type checking",
    "options": ["TypeScript"],
    "decision": "Add TypeScript to the component",
    "rationale": "Improves type safety and code quality",
    "confidence": 0.85
  }}
]
```

### Example 4: No decisions (just discussion)
Conversation:
"What do you think about microservices? I've heard they can be complex but offer good scalability. We should probably discuss this more with the team before deciding anything."

Output:
```json
[]
```

## Instructions
For each decision found, provide:
- trigger: What prompted the decision (be specific)
- context: Relevant background (constraints, requirements, team situation)
- options: Alternatives considered (can be just [chosen_option] if no alternatives mentioned)
- decision: What was decided (clear statement)
- rationale: Why this choice (extract reasoning from context, or "Not explicitly stated" if unclear)
- confidence: 0.0-1.0 (how clear/complete the decision is)

**Important**:
- Extract both explicit decisions (X vs Y) and implicit ones ("Let's use X")
- Implementation choices count as decisions (e.g., "I'll refactor this using pattern X")
- If only one option is mentioned, that's still a decision
- If no clear decisions are found, return an empty array []

## Conversation to analyze:
{conversation_text}

Return ONLY valid JSON, no markdown code blocks or explanation."""


# ML-P2-2: Decision Type Enumeration
class DecisionType:
    """Enumeration of decision types for specialized extraction (ML-P2-2)."""

    ARCHITECTURE = "architecture"
    TECHNOLOGY = "technology"
    PROCESS = "process"
    GENERAL = "general"


# ML-P2-2: Specialized prompt for architecture decisions
ARCHITECTURE_DECISION_PROMPT = """Analyze this conversation for ARCHITECTURE DECISIONS.

Focus on: system structure, scalability, communication patterns, tradeoffs.

## Example
Conversation: "We decided to start with a modular monolith given our small team."
Output:
```json
[{{"trigger": "Deciding on system architecture", "context": "Small team", "options": ["Microservices", "Monolith"], "decision": "Modular monolith", "rationale": "Reduced complexity for small team", "confidence": 0.9, "decision_type": "architecture"}}]
```

## Conversation to analyze:
{conversation_text}

Return ONLY valid JSON, no markdown code blocks or explanation."""


# ML-P2-2: Specialized prompt for technology choice decisions
TECHNOLOGY_DECISION_PROMPT = """Analyze this conversation for TECHNOLOGY CHOICE DECISIONS.

Focus on: tools, frameworks, alternatives considered, compatibility, team skills.

## Example
Conversation: "We chose PostgreSQL over MongoDB for ACID compliance."
Output:
```json
[{{"trigger": "Selecting database", "context": "Need ACID compliance", "options": ["PostgreSQL", "MongoDB"], "decision": "PostgreSQL", "rationale": "Better transactional support", "confidence": 0.95, "decision_type": "technology"}}]
```

## Conversation to analyze:
{conversation_text}

Return ONLY valid JSON, no markdown code blocks or explanation."""


# ML-P2-2: Specialized prompt for process decisions
PROCESS_DECISION_PROMPT = """Analyze this conversation for PROCESS and WORKFLOW DECISIONS.

Focus on: team workflows, deployment practices, quality assurance, collaboration.

## Example
Conversation: "We are implementing mandatory code reviews with CODEOWNERS."
Output:
```json
[{{"trigger": "Establishing code review practices", "context": "Need quality improvement", "options": ["Optional reviews", "Mandatory reviews"], "decision": "Mandatory reviews with CODEOWNERS", "rationale": "Ensures expert review", "confidence": 0.85, "decision_type": "process"}}]
```

## Conversation to analyze:
{conversation_text}

Return ONLY valid JSON, no markdown code blocks or explanation."""


# ML-P2-2: Map decision types to prompts
DECISION_TYPE_PROMPTS = {
    DecisionType.ARCHITECTURE: ARCHITECTURE_DECISION_PROMPT,
    DecisionType.TECHNOLOGY: TECHNOLOGY_DECISION_PROMPT,
    DecisionType.PROCESS: PROCESS_DECISION_PROMPT,
    DecisionType.GENERAL: None,  # Use default DECISION_EXTRACTION_PROMPT
}


# ML-P2-2: Keywords for auto-detecting decision type
DECISION_TYPE_KEYWORDS = {
    DecisionType.ARCHITECTURE: [
        "architecture",
        "microservice",
        "monolith",
        "distributed",
        "scalability",
        "api gateway",
        "event-driven",
        "message queue",
        "load balancer",
    ],
    DecisionType.TECHNOLOGY: [
        "framework",
        "library",
        "database",
        "postgres",
        "mongodb",
        "redis",
        "react",
        "vue",
        "python",
        "typescript",
        "aws",
        "docker",
    ],
    DecisionType.PROCESS: [
        "workflow",
        "process",
        "ci/cd",
        "deployment",
        "code review",
        "branching",
        "agile",
        "sprint",
        "release",
    ],
}


def detect_decision_type(text: str) -> str:
    """Auto-detect the decision type based on keywords in the text (ML-P2-2).

    Args:
        text: The conversation or decision text to analyze

    Returns:
        The detected decision type string
    """
    text_lower = text.lower()
    scores = {dtype: 0 for dtype in DECISION_TYPE_KEYWORDS}

    for dtype, keywords in DECISION_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                scores[dtype] += 1

    max_score = max(scores.values())
    if max_score >= 2:  # Require at least 2 keyword matches
        for dtype, score in scores.items():
            if score == max_score:
                return dtype

    return DecisionType.GENERAL


def calibrate_confidence(decision_data: dict) -> float:
    """Calibrate confidence score based on extraction completeness (ML-P2-3).

    Adjusts the raw LLM confidence based on:
    - Completeness of extracted fields
    - Number of options/entities mentioned
    - Quality indicators in rationale

    Args:
        decision_data: The extracted decision dictionary

    Returns:
        Calibrated confidence score (0.0 to 1.0)
    """
    raw_confidence = decision_data.get("confidence", 0.5)
    calibrated = raw_confidence

    # Penalty for missing required fields
    required_fields = ["trigger", "decision", "rationale"]
    missing_required = sum(1 for f in required_fields if not decision_data.get(f))
    calibrated -= missing_required * 0.15

    # Bonus for having options (indicates careful consideration)
    options = decision_data.get("options", [])
    if len(options) >= 2:
        calibrated += 0.05
    if len(options) >= 3:
        calibrated += 0.03

    # Bonus for detailed rationale
    rationale = decision_data.get("rationale", "")
    rationale_words = len(rationale.split()) if rationale else 0
    if rationale_words >= 20:
        calibrated += 0.05
    elif rationale_words >= 10:
        calibrated += 0.02
    elif rationale_words < 5:
        calibrated -= 0.10

    # Bonus for having context
    context = decision_data.get("context", "")
    if context and len(context.split()) >= 5:
        calibrated += 0.03

    # Quality phrases bonus
    quality_phrases = [
        "because",
        "since",
        "due to",
        "trade-off",
        "benefit",
        "compared to",
    ]
    rationale_lower = rationale.lower()
    quality_matches = sum(1 for p in quality_phrases if p in rationale_lower)
    calibrated += min(quality_matches * 0.02, 0.08)

    return round(max(0.1, min(1.0, calibrated)), 3)


# Few-shot entity extraction prompt with Chain-of-Thought reasoning
ENTITY_EXTRACTION_PROMPT = """Extract technical entities from this decision text.

## Entity Types
- technology: Specific tools, languages, frameworks, databases (e.g., PostgreSQL, React, Python)
- concept: Abstract ideas, principles, methodologies (e.g., microservices, REST API, caching)
- pattern: Design and architectural patterns (e.g., singleton, repository pattern, CQRS)
- system: Software systems, services, components (e.g., authentication system, payment gateway)
- person: People mentioned (team members, stakeholders)
- organization: Companies, teams, departments

## Examples

Input: "We chose React over Vue for the frontend"
Output:
{{
  "entities": [
    {{"name": "React", "type": "technology", "confidence": 0.95}},
    {{"name": "Vue", "type": "technology", "confidence": 0.95}},
    {{"name": "frontend", "type": "concept", "confidence": 0.85}}
  ],
  "reasoning": "React and Vue are frontend frameworks (technology). Frontend is the general concept being discussed."
}}

Input: "JWT tokens stored in Redis for session management"
Output:
{{
  "entities": [
    {{"name": "JWT", "type": "technology", "confidence": 0.95}},
    {{"name": "Redis", "type": "technology", "confidence": 0.95}},
    {{"name": "session management", "type": "concept", "confidence": 0.85}}
  ],
  "reasoning": "JWT is an authentication token standard (technology). Redis is a database (technology). Session management is the concept being implemented."
}}

Input: "Implementing the repository pattern with SQLAlchemy for data access"
Output:
{{
  "entities": [
    {{"name": "repository pattern", "type": "pattern", "confidence": 0.95}},
    {{"name": "SQLAlchemy", "type": "technology", "confidence": 0.95}},
    {{"name": "data access", "type": "concept", "confidence": 0.8}}
  ],
  "reasoning": "Repository pattern is a design pattern. SQLAlchemy is an ORM technology. Data access is the concept being addressed."
}}

## Decision Text
{decision_text}

Extract entities with your reasoning. Return ONLY valid JSON:
{{
  "entities": [{{"name": "string", "type": "entity_type", "confidence": 0.0-1.0}}, ...],
  "reasoning": "Brief explanation of your categorization"
}}"""


# Few-shot entity relationship extraction prompt
ENTITY_RELATIONSHIP_PROMPT = """Identify relationships between these entities.

## Relationship Types
- IS_A: X is a type/category of Y (e.g., "PostgreSQL IS_A Database")
- PART_OF: X is a component of Y (e.g., "React Flow PART_OF React ecosystem")
- DEPENDS_ON: X requires/depends on Y (e.g., "Next.js DEPENDS_ON React")
- RELATED_TO: X is generally related to Y (e.g., "FastAPI RELATED_TO Python")
- ALTERNATIVE_TO: X can be used instead of Y (e.g., "MongoDB ALTERNATIVE_TO PostgreSQL")

## Examples

Entities: ["React", "Vue", "frontend"]
Context: "We chose React over Vue for the frontend"
Output:
{{
  "relationships": [
    {{"from": "React", "to": "frontend", "type": "PART_OF", "confidence": 0.9}},
    {{"from": "Vue", "to": "frontend", "type": "PART_OF", "confidence": 0.9}},
    {{"from": "React", "to": "Vue", "type": "ALTERNATIVE_TO", "confidence": 0.95}}
  ],
  "reasoning": "React and Vue are both frontend frameworks (PART_OF frontend). They were considered as alternatives."
}}

Entities: ["PostgreSQL", "Redis", "caching", "database"]
Context: "Using PostgreSQL as the primary database with Redis for caching"
Output:
{{
  "relationships": [
    {{"from": "PostgreSQL", "to": "database", "type": "IS_A", "confidence": 0.95}},
    {{"from": "Redis", "to": "caching", "type": "PART_OF", "confidence": 0.9}},
    {{"from": "Redis", "to": "database", "type": "IS_A", "confidence": 0.85}}
  ],
  "reasoning": "PostgreSQL is a relational database. Redis is used for caching but is also a database (key-value store)."
}}

Entities: ["Next.js", "React", "TypeScript", "frontend"]
Context: "Building the frontend with Next.js and TypeScript"
Output:
{{
  "relationships": [
    {{"from": "Next.js", "to": "React", "type": "DEPENDS_ON", "confidence": 0.95}},
    {{"from": "Next.js", "to": "frontend", "type": "PART_OF", "confidence": 0.9}},
    {{"from": "TypeScript", "to": "frontend", "type": "PART_OF", "confidence": 0.85}}
  ],
  "reasoning": "Next.js is built on top of React (DEPENDS_ON). Both Next.js and TypeScript are part of the frontend stack."
}}

## Entities: {entities}
## Context: {context}

Identify relationships. Only include relationships you're confident about (>0.7 confidence).
Return ONLY valid JSON:
{{
  "relationships": [{{"from": "entity", "to": "entity", "type": "RELATIONSHIP_TYPE", "confidence": 0.0-1.0}}, ...],
  "reasoning": "Brief explanation"
}}"""


# Decision-to-decision relationship extraction prompt
DECISION_RELATIONSHIP_PROMPT = """Analyze if these two decisions have a significant relationship.

## Relationship Types
- SUPERSEDES: The newer decision explicitly replaces or changes the older decision
- CONTRADICTS: The decisions fundamentally conflict (choosing opposite approaches)

## Examples

Decision A (Jan 15): "Using PostgreSQL for the primary database"
Decision B (Mar 20): "Migrating to MongoDB for horizontal scaling needs"
Output:
{{
  "relationship": "SUPERSEDES",
  "confidence": 0.9,
  "reasoning": "Decision B explicitly changes the database choice from PostgreSQL to MongoDB, superseding Decision A."
}}

Decision A (Feb 1): "REST API for all client communication"
Decision B (Feb 15): "GraphQL for mobile app queries to reduce overfetching"
Output:
{{
  "relationship": null,
  "confidence": 0.0,
  "reasoning": "These decisions are complementary - GraphQL is added for mobile while REST remains for other clients."
}}

Decision A (Jan 10): "Monolithic architecture for faster initial development"
Decision B (Jun 1): "Breaking into microservices for better scaling"
Output:
{{
  "relationship": "SUPERSEDES",
  "confidence": 0.85,
  "reasoning": "Decision B transitions from the monolithic approach in Decision A to microservices."
}}

Decision A (Mar 1): "Using JWT for stateless authentication"
Decision B (Mar 5): "Using session cookies for authentication"
Output:
{{
  "relationship": "CONTRADICTS",
  "confidence": 0.9,
  "reasoning": "JWT (stateless) and session cookies (stateful) are conflicting authentication approaches."
}}

## Decision A ({decision_a_date}):
Trigger: {decision_a_trigger}
Decision: {decision_a_text}
Rationale: {decision_a_rationale}

## Decision B ({decision_b_date}):
Trigger: {decision_b_trigger}
Decision: {decision_b_text}
Rationale: {decision_b_rationale}

Analyze the relationship. Return ONLY valid JSON:
{{
  "relationship": "SUPERSEDES" | "CONTRADICTS" | null,
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation"
}}"""


class LLMResponseCache:
    """Redis-based cache for LLM extraction responses (KG-P0-2).

    Caches LLM responses keyed by:
    - Hash of input text
    - Prompt template version
    - Extraction type (decision, entity, relationship)

    This avoids redundant API calls when reprocessing the same content.
    """

    def __init__(self):
        self._redis: redis.Redis | None = None
        self._settings = get_settings()

    async def _get_redis(self) -> redis.Redis | None:
        """Get or create Redis connection for caching."""
        if self._redis is None:
            try:
                self._redis = redis.from_url(
                    self._settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await self._redis.ping()
            except Exception as e:
                logger.warning(f"LLM cache Redis connection failed: {e}")
                self._redis = None
        return self._redis

    def _get_cache_key(self, text: str, extraction_type: str) -> str:
        """Generate a cache key for the LLM response.

        Format: llm:{version}:{type}:{hash(text)}
        """
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        version = self._settings.llm_extraction_prompt_version
        return f"llm:{version}:{extraction_type}:{text_hash}"

    async def get(self, text: str, extraction_type: str) -> dict | list | None:
        """Get cached LLM response if available."""
        if not self._settings.llm_cache_enabled:
            return None

        redis_client = await self._get_redis()
        if redis_client is None:
            return None

        try:
            cache_key = self._get_cache_key(text, extraction_type)
            cached = await redis_client.get(cache_key)
            if cached:
                logger.debug(f"LLM cache hit for {extraction_type}")
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"LLM cache read error: {e}")

        return None

    async def set(self, text: str, extraction_type: str, response: dict | list) -> None:
        """Cache an LLM response."""
        if not self._settings.llm_cache_enabled:
            return

        redis_client = await self._get_redis()
        if redis_client is None:
            return

        try:
            cache_key = self._get_cache_key(text, extraction_type)
            await redis_client.setex(
                cache_key,
                self._settings.llm_cache_ttl,
                json.dumps(response),
            )
            logger.debug(f"LLM cache set for {extraction_type}")
        except Exception as e:
            logger.warning(f"LLM cache write error: {e}")


class DecisionExtractor:
    """Extract decisions and entities from conversations using LLM.

    Enhanced with:
    - Few-shot Chain-of-Thought prompts for better extraction
    - Entity resolution to prevent duplicates
    - ALTERNATIVE_TO relationship detection
    - SUPERSEDES and CONTRADICTS relationship analysis
    - Embedding generation for semantic search
    - Multi-tenant user isolation via user_id
    - Robust JSON parsing for LLM responses
    - Configurable similarity threshold
    - LLM response caching (KG-P0-2)
    - Relationship type validation (KG-P0-3)
    """

    def __init__(self):
        self.llm = get_llm_client()
        self.embedding_service = get_embedding_service()
        self.cache = LLMResponseCache()
        settings = get_settings()
        self.similarity_threshold = settings.similarity_threshold
        self.high_confidence_threshold = settings.high_confidence_similarity_threshold

    async def extract_decisions(
        self,
        conversation: Conversation,
        bypass_cache: bool = False,
        decision_type: str | None = None,
    ) -> list[DecisionCreate]:
        """Extract decision traces from a conversation using few-shot CoT prompt.

        Supports specialized prompts for different decision types (ML-P2-2) and
        applies confidence calibration post-processing (ML-P2-3).

        Args:
            conversation: The conversation to extract decisions from
            bypass_cache: If True, skip cache lookup and force fresh extraction
            decision_type: Optional decision type override (architecture, technology, process)
                          If None, auto-detects based on keywords (ML-P2-2)
        """
        conversation_text = conversation.get_full_text()

        # ML-P2-2: Auto-detect decision type if not specified
        if decision_type is None:
            decision_type = detect_decision_type(conversation_text)
        logger.debug(f"Using decision type: {decision_type}")

        # Check cache first (KG-P0-2) - include decision_type in cache key
        cache_key = f"{decision_type}:{conversation_text}"
        if not bypass_cache:
            cached = await self.cache.get(cache_key, "decisions")
            if cached is not None:
                logger.info(f"Using cached decision extraction (type={decision_type})")
                # Apply defaults and calibration for missing fields (ML-QW-3, ML-P2-3)
                return [
                    DecisionCreate(
                        **{
                            k: v
                            for k, v in apply_decision_defaults(d).items()
                            if k
                            in (
                                "trigger",
                                "context",
                                "options",
                                "decision",
                                "rationale",
                                "confidence",
                            )
                        }
                    )
                    for d in cached
                    if apply_decision_defaults(d).get("decision")
                ]

        # ML-P2-2: Select appropriate prompt based on decision type
        specialized_prompt = DECISION_TYPE_PROMPTS.get(decision_type)
        if specialized_prompt is not None:
            prompt = specialized_prompt.format(conversation_text=conversation_text)
        else:
            prompt = DECISION_EXTRACTION_PROMPT.format(
                conversation_text=conversation_text
            )

        try:
            response = await self.llm.generate(prompt, temperature=0.3, sanitize_input=False)

            # Use robust JSON extraction
            decisions_data = extract_json_from_response(response)

            if decisions_data is None:
                logger.warning("Failed to parse decisions from LLM response")
                return []

            # Ensure we have a list
            if not isinstance(decisions_data, list):
                logger.warning(f"Expected list, got {type(decisions_data)}")
                return []

            # ML-P2-3: Apply confidence calibration to each decision
            for d in decisions_data:
                raw_confidence = d.get("confidence", 0.5)
                calibrated = calibrate_confidence(d)
                d["confidence"] = calibrated
                d["raw_confidence"] = raw_confidence  # Preserve original for debugging

            # Cache the result (KG-P0-2)
            await self.cache.set(cache_key, "decisions", decisions_data)

            # Log extraction summary (KG-QW-4: Extraction reasoning logging)
            if decisions_data:
                confidence_scores = [d.get("confidence", 0.5) for d in decisions_data]
                raw_scores = [
                    d.get("raw_confidence", d.get("confidence", 0.5))
                    for d in decisions_data
                ]
                avg_confidence = (
                    sum(confidence_scores) / len(confidence_scores)
                    if confidence_scores
                    else 0
                )
                avg_raw = sum(raw_scores) / len(raw_scores) if raw_scores else 0
                logger.info(
                    "Decision extraction completed",
                    extra={
                        "extraction_type": "decisions",
                        "decision_type": decision_type,
                        "count": len(decisions_data),
                        "avg_confidence": round(avg_confidence, 3),
                        "avg_raw_confidence": round(avg_raw, 3),
                        "calibration_delta": round(avg_confidence - avg_raw, 3),
                        "confidence_range": {
                            "min": round(min(confidence_scores), 3)
                            if confidence_scores
                            else 0,
                            "max": round(max(confidence_scores), 3)
                            if confidence_scores
                            else 0,
                        },
                        "decisions_summary": [
                            {
                                "trigger_preview": d.get("trigger", "")[:50],
                                "confidence": d.get("confidence", 0.5),
                                "raw_confidence": d.get(
                                    "raw_confidence", d.get("confidence", 0.5)
                                ),
                            }
                            for d in decisions_data[:5]  # Limit to first 5 for log size
                        ],
                    },
                )

            # Apply defaults for missing fields (ML-QW-3)
            return [
                DecisionCreate(
                    **{
                        k: v
                        for k, v in apply_decision_defaults(d).items()
                        if k
                        in (
                            "trigger",
                            "context",
                            "options",
                            "decision",
                            "rationale",
                            "confidence",
                        )
                    }
                )
                for d in decisions_data
                if apply_decision_defaults(d).get(
                    "decision"
                )  # Skip entries without a decision
            ]

        except (TimeoutError, ConnectionError) as e:
            logger.error(f"LLM connection error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error extracting decisions: {e}")
            return []

    async def extract_entities(
        self, text: str, bypass_cache: bool = False
    ) -> list[dict]:
        """Extract entities from text using few-shot CoT prompt.

        Args:
            text: The text to extract entities from
            bypass_cache: If True, skip cache lookup and force fresh extraction

        Returns list of dicts with name, type, and confidence.
        """
        # Check cache first (KG-P0-2)
        if not bypass_cache:
            cached = await self.cache.get(text, "entities")
            if cached is not None:
                logger.info("Using cached entity extraction")
                return cached

        prompt = ENTITY_EXTRACTION_PROMPT.format(decision_text=text)

        try:
            response = await self.llm.generate(prompt, temperature=0.3, sanitize_input=False)

            # Use robust JSON extraction
            result = extract_json_from_response(response)

            if result is None:
                logger.warning("Failed to parse entity extraction response")
                return []

            entities = result.get("entities", [])
            reasoning = result.get("reasoning", "")

            # Log extraction with structured data (KG-QW-4: Extraction reasoning logging)
            if entities:
                # Group entities by type for summary
                type_counts = {}
                confidence_by_type = {}
                for e in entities:
                    etype = e.get("type", "unknown")
                    type_counts[etype] = type_counts.get(etype, 0) + 1
                    if etype not in confidence_by_type:
                        confidence_by_type[etype] = []
                    confidence_by_type[etype].append(e.get("confidence", 0.8))

                avg_confidence_by_type = {
                    t: round(sum(scores) / len(scores), 3)
                    for t, scores in confidence_by_type.items()
                }

                logger.info(
                    "Entity extraction completed",
                    extra={
                        "extraction_type": "entities",
                        "count": len(entities),
                        "type_distribution": type_counts,
                        "avg_confidence_by_type": avg_confidence_by_type,
                        "entities": [
                            {
                                "name": e.get("name"),
                                "type": e.get("type"),
                                "confidence": e.get("confidence"),
                            }
                            for e in entities
                        ],
                        "llm_reasoning": reasoning[:500]
                        if reasoning
                        else None,  # Truncate for log size
                    },
                )
            else:
                logger.debug(
                    "No entities extracted from text",
                    extra={
                        "text_length": len(text),
                        "llm_reasoning": reasoning[:200] if reasoning else None,
                    },
                )

            # Cache the result (KG-P0-2)
            await self.cache.set(text, "entities", entities)

            return entities

        except (TimeoutError, ConnectionError) as e:
            logger.error(f"LLM connection error during entity extraction: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error during entity extraction: {e}")
            return []

    async def extract_entity_relationships(
        self, entities: list[Entity], context: str = "", bypass_cache: bool = False
    ) -> list[dict]:
        """Extract relationships between entities using few-shot CoT prompt.

        Includes relationship type validation (KG-P0-3).
        """
        if len(entities) < 2:
            return []

        import json as json_module

        entity_names = [
            e.name if hasattr(e, "name") else e.get("name", "") for e in entities
        ]

        # Build entity type lookup for validation
        entity_types = {}
        for e in entities:
            name = e.name if hasattr(e, "name") else e.get("name", "")
            etype = e.type if hasattr(e, "type") else e.get("type", "concept")
            entity_types[name.lower()] = etype

        # Cache key includes entities and context
        cache_text = f"{json_module.dumps(sorted(entity_names))}|{context}"

        # Check cache first (KG-P0-2)
        if not bypass_cache:
            cached = await self.cache.get(cache_text, "relationships")
            if cached is not None:
                logger.info("Using cached relationship extraction")
                return cached

        prompt = ENTITY_RELATIONSHIP_PROMPT.format(
            entities=json_module.dumps(entity_names),
            context=context or "General technical discussion",
        )

        try:
            response = await self.llm.generate(prompt, temperature=0.3, sanitize_input=False)

            # Use robust JSON extraction
            result = extract_json_from_response(response)

            if result is None:
                logger.warning("Failed to parse relationship extraction response")
                return []

            relationships = result.get("relationships", [])
            reasoning = result.get("reasoning", "")

            # Log raw extraction (KG-QW-4: Extraction reasoning logging)
            logger.debug(
                "Raw relationship extraction from LLM",
                extra={
                    "extraction_type": "relationships_raw",
                    "count": len(relationships),
                    "entity_count": len(entity_names),
                    "llm_reasoning": reasoning[:500] if reasoning else None,
                },
            )

            # Validate and filter relationships (KG-P0-3)
            validated_relationships = []
            validation_stats = {"valid": 0, "invalid": 0, "fallback": 0}
            for rel in relationships:
                rel_type = rel.get("type", "RELATED_TO")
                from_name = rel.get("from", "")
                to_name = rel.get("to", "")
                confidence = rel.get("confidence", 0.8)

                # Get entity types for validation
                from_type = entity_types.get(from_name.lower(), "concept")
                to_type = entity_types.get(to_name.lower(), "concept")

                # Validate the relationship (KG-P0-3)
                is_valid, error_msg = validate_entity_relationship(
                    rel_type, from_type, to_type
                )

                if is_valid:
                    validated_relationships.append(rel)
                    validation_stats["valid"] += 1
                else:
                    validation_stats["invalid"] += 1
                    # Log invalid relationship for review
                    logger.debug(
                        "Invalid relationship skipped",
                        extra={
                            "from_entity": from_name,
                            "from_type": from_type,
                            "to_entity": to_name,
                            "to_type": to_type,
                            "relationship_type": rel_type,
                            "error": error_msg,
                        },
                    )
                    # Try to suggest a valid alternative
                    if rel_type in ENTITY_ONLY_RELATIONSHIPS:
                        # Fall back to RELATED_TO if the specific type doesn't work
                        validated_relationships.append(
                            {
                                "from": from_name,
                                "to": to_name,
                                "type": "RELATED_TO",
                                "confidence": confidence
                                * 0.8,  # Lower confidence for fallback
                            }
                        )
                        validation_stats["fallback"] += 1
                        logger.debug(
                            "Relationship type fallback applied",
                            extra={
                                "from_entity": from_name,
                                "to_entity": to_name,
                                "original_type": rel_type,
                                "fallback_type": "RELATED_TO",
                            },
                        )

            # Log relationship extraction summary (KG-QW-4)
            if validated_relationships:
                type_distribution = {}
                for r in validated_relationships:
                    rtype = r.get("type", "RELATED_TO")
                    type_distribution[rtype] = type_distribution.get(rtype, 0) + 1

                logger.info(
                    "Relationship extraction completed",
                    extra={
                        "extraction_type": "relationships",
                        "raw_count": len(relationships),
                        "validated_count": len(validated_relationships),
                        "validation_stats": validation_stats,
                        "type_distribution": type_distribution,
                        "relationships": [
                            {
                                "from": r.get("from"),
                                "to": r.get("to"),
                                "type": r.get("type"),
                                "confidence": r.get("confidence"),
                            }
                            for r in validated_relationships
                        ],
                    },
                )

            # Cache the validated result (KG-P0-2)
            await self.cache.set(cache_text, "relationships", validated_relationships)

            return validated_relationships

        except (TimeoutError, ConnectionError) as e:
            logger.error(f"LLM connection error during relationship extraction: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error during relationship extraction: {e}")
            return []

    async def extract_decision_relationship(
        self, decision_a: dict, decision_b: dict
    ) -> Optional[dict]:
        """Analyze two decisions for SUPERSEDES or CONTRADICTS relationship."""
        prompt = DECISION_RELATIONSHIP_PROMPT.format(
            decision_a_date=decision_a.get("created_at", "unknown"),
            decision_a_trigger=decision_a.get("trigger", ""),
            decision_a_text=decision_a.get("decision", ""),
            decision_a_rationale=decision_a.get("rationale", ""),
            decision_b_date=decision_b.get("created_at", "unknown"),
            decision_b_trigger=decision_b.get("trigger", ""),
            decision_b_text=decision_b.get("decision", ""),
            decision_b_rationale=decision_b.get("rationale", ""),
        )

        try:
            response = await self.llm.generate(prompt, temperature=0.3, sanitize_input=False)

            # Use robust JSON extraction
            result = extract_json_from_response(response)

            if result is None:
                logger.warning("Failed to parse decision relationship response")
                return None

            if result.get("relationship") is None:
                return None

            return {
                "type": result.get("relationship"),
                "confidence": result.get("confidence", 0.5),
                "reasoning": result.get("reasoning", ""),
            }

        except (TimeoutError, ConnectionError) as e:
            logger.error(
                f"LLM connection error during decision relationship analysis: {e}"
            )
            return None
        except Exception as e:
            logger.error(f"Unexpected error during decision relationship analysis: {e}")
            return None

    async def save_decision(
        self,
        decision: DecisionCreate,
        source: str = "unknown",
        user_id: str = "anonymous",
        provenance: Optional[Provenance] = None,
        source_path: Optional[str] = None,
        message_index: Optional[int] = None,
        project_name: Optional[str] = None,
    ) -> str:
        """Save a decision to Neo4j with embeddings, rich relationships, and provenance (KG-P2-4).

        Uses entity resolution to prevent duplicates and canonicalize names.
        Includes user_id for multi-tenant data isolation.
        Tracks provenance information for data lineage.

        Args:
            decision: The decision to save
            source: Where this decision came from ('claude_logs', 'interview', 'manual')
            user_id: The user ID for multi-tenant isolation (default: "anonymous")
            provenance: Optional provenance information for data lineage (KG-P2-4)
            source_path: Optional path to source file for provenance tracking
            message_index: Optional index of message in conversation
            project_name: Optional project this decision belongs to

        Returns:
            The ID of the created decision
        """
        decision_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        # Use source parameter (decisions from LLM don't include source field)
        decision_source = source
        # Use project_name from decision if provided, otherwise use parameter
        decision_project = getattr(decision, "project_name", None) or project_name
        # Normalize project name to lowercase for consistency
        if decision_project:
            decision_project = decision_project.lower()

        # KG-P2-4: Build provenance if not provided
        if provenance is None:
            source_type_map = {
                "claude_logs": SourceType.CLAUDE_LOG,
                "interview": SourceType.INTERVIEW,
                "manual": SourceType.MANUAL,
                "unknown": SourceType.MANUAL,
            }
            provenance = create_llm_provenance(
                source_type=source_type_map.get(decision_source, SourceType.MANUAL),
                source_path=source_path,
                model_name=self.llm.model if hasattr(self.llm, "model") else None,
                prompt_version=get_settings().llm_extraction_prompt_version,
                confidence=decision.confidence,
                created_by=user_id,
                message_index=message_index,
            )

        # Serialize provenance for storage
        provenance_json = json.dumps(provenance.to_dict()) if provenance else None

        # Generate embedding for the decision
        decision_dict = {
            "trigger": decision.trigger,
            "context": decision.context,
            "options": decision.options,
            "decision": decision.agent_decision,
            "rationale": decision.agent_rationale,
        }

        try:
            embedding = await self.embedding_service.embed_decision(decision_dict)
            logger.debug(f"Generated embedding with {len(embedding)} dimensions")
        except (TimeoutError, ConnectionError) as e:
            logger.warning(f"Embedding service connection failed: {e}")
            embedding = None
        except ValueError as e:
            logger.warning(f"Invalid embedding input: {e}")
            embedding = None

        session = await get_neo4j_session()
        async with session:
            # Create decision node with embedding, user_id, and provenance (KG-P2-4)
            if embedding:
                await session.run(
                    """
                    CREATE (d:DecisionTrace {
                        id: $id,
                        trigger: $trigger,
                        context: $context,
                        options: $options,
                        agent_decision: $agent_decision,
                        agent_rationale: $agent_rationale,
                        confidence: $confidence,
                        created_at: $created_at,
                        source: $source,
                        user_id: $user_id,
                        project_name: $project_name,
                        embedding: $embedding,
                        provenance: $provenance,
                        extraction_method: $extraction_method,
                        created_by: $created_by
                    })
                    """,
                    id=decision_id,
                    trigger=decision.trigger,
                    context=decision.context,
                    options=decision.options,
                    agent_decision=decision.agent_decision,
                    agent_rationale=decision.agent_rationale,
                    confidence=decision.confidence,
                    created_at=created_at,
                    source=decision_source,
                    user_id=user_id,
                    project_name=decision_project,
                    embedding=embedding,
                    provenance=provenance_json,
                    extraction_method=provenance.extraction.method.value
                    if provenance
                    else "unknown",
                    created_by=provenance.created_by if provenance else user_id,
                )
            else:
                await session.run(
                    """
                    CREATE (d:DecisionTrace {
                        id: $id,
                        trigger: $trigger,
                        context: $context,
                        options: $options,
                        agent_decision: $agent_decision,
                        agent_rationale: $agent_rationale,
                        confidence: $confidence,
                        created_at: $created_at,
                        source: $source,
                        user_id: $user_id,
                        project_name: $project_name,
                        provenance: $provenance,
                        extraction_method: $extraction_method,
                        created_by: $created_by
                    })
                    """,
                    id=decision_id,
                    trigger=decision.trigger,
                    context=decision.context,
                    options=decision.options,
                    agent_decision=decision.agent_decision,
                    agent_rationale=decision.agent_rationale,
                    confidence=decision.confidence,
                    created_at=created_at,
                    source=decision_source,
                    user_id=user_id,
                    project_name=decision_project,
                    provenance=provenance_json,
                    extraction_method=provenance.extraction.method.value
                    if provenance
                    else "unknown",
                    created_by=provenance.created_by if provenance else user_id,
                )

            logger.info(f"Created decision {decision_id} for user {user_id}")

            # Extract entities with enhanced prompt
            full_text = f"{decision.trigger} {decision.context} {decision.agent_decision} {decision.agent_rationale}"
            entities_data = await self.extract_entities(full_text)
            logger.debug(
                "Entities data extracted from text",
                extra={
                    "decision_id": decision_id,
                    "entity_count": len(entities_data),
                    "text_length": len(full_text),
                },
            )

            # Create entity resolver for this session
            resolver = EntityResolver(session)

            # Resolve and create/link entities
            resolved_entities = []
            for entity_data in entities_data:
                name = entity_data.get("name", "")
                entity_type = entity_data.get("type", "concept")
                confidence = entity_data.get("confidence", 0.8)

                if not name:
                    continue

                # Resolve entity (finds existing or creates new)
                resolved = await resolver.resolve(name, entity_type)
                resolved_entities.append(resolved)

                # Generate entity embedding for new entities
                entity_embedding = None
                if resolved.is_new:
                    try:
                        entity_embedding = await self.embedding_service.embed_entity(
                            {
                                "name": resolved.name,
                                "type": resolved.type,
                            }
                        )
                    except (TimeoutError, ConnectionError, ValueError):
                        pass

                # Create or update entity node
                if resolved.is_new:
                    if entity_embedding:
                        await session.run(
                            """
                            CREATE (e:Entity {
                                id: $id,
                                name: $name,
                                type: $type,
                                aliases: $aliases,
                                embedding: $embedding
                            })
                            WITH e
                            MATCH (d:DecisionTrace {id: $decision_id})
                            CREATE (d)-[:INVOLVES {weight: $confidence}]->(e)
                            """,
                            id=resolved.id,
                            name=resolved.name,
                            type=resolved.type,
                            aliases=resolved.aliases,
                            embedding=entity_embedding,
                            decision_id=decision_id,
                            confidence=confidence,
                        )
                    else:
                        await session.run(
                            """
                            CREATE (e:Entity {
                                id: $id,
                                name: $name,
                                type: $type,
                                aliases: $aliases
                            })
                            WITH e
                            MATCH (d:DecisionTrace {id: $decision_id})
                            CREATE (d)-[:INVOLVES {weight: $confidence}]->(e)
                            """,
                            id=resolved.id,
                            name=resolved.name,
                            type=resolved.type,
                            aliases=resolved.aliases,
                            decision_id=decision_id,
                            confidence=confidence,
                        )
                    logger.debug(
                        "Created new entity",
                        extra={
                            "entity_name": resolved.name,
                            "entity_type": resolved.type,
                            "entity_id": resolved.id,
                            "aliases": resolved.aliases,
                        },
                    )
                else:
                    # Link to existing entity
                    await session.run(
                        """
                        MATCH (e:Entity {id: $entity_id})
                        MATCH (d:DecisionTrace {id: $decision_id})
                        MERGE (d)-[:INVOLVES {weight: $confidence}]->(e)
                        """,
                        entity_id=resolved.id,
                        decision_id=decision_id,
                        confidence=confidence,
                    )
                    logger.debug(
                        "Linked to existing entity",
                        extra={
                            "entity_name": resolved.name,
                            "entity_type": resolved.type,
                            "match_method": resolved.match_method,
                            "confidence": resolved.confidence,
                            "entity_id": resolved.id,
                        },
                    )

            # Log entity resolution summary (KG-QW-4: Extraction reasoning logging)
            if resolved_entities:
                resolution_summary = {
                    "total_extracted": len(entities_data),
                    "total_resolved": len(resolved_entities),
                    "new_entities": sum(1 for e in resolved_entities if e.is_new),
                    "existing_entities": sum(
                        1 for e in resolved_entities if not e.is_new
                    ),
                    "match_methods": {},
                }
                for e in resolved_entities:
                    method = e.match_method
                    resolution_summary["match_methods"][method] = (
                        resolution_summary["match_methods"].get(method, 0) + 1
                    )

                logger.info(
                    "Entity resolution completed",
                    extra={
                        "decision_id": decision_id,
                        "resolution_summary": resolution_summary,
                        "resolved_entities": [
                            {
                                "name": e.name,
                                "type": e.type,
                                "is_new": e.is_new,
                                "match_method": e.match_method,
                                "confidence": round(e.confidence, 3),
                            }
                            for e in resolved_entities
                        ],
                    },
                )

            # Extract and create entity-to-entity relationships
            if len(resolved_entities) >= 2:
                entity_rels = await self.extract_entity_relationships(
                    [{"name": e.name, "type": e.type} for e in resolved_entities],
                    context=full_text,
                )
                logger.debug(
                    "Entity relationships extracted for decision",
                    extra={
                        "decision_id": decision_id,
                        "relationship_count": len(entity_rels),
                        "entity_count": len(resolved_entities),
                    },
                )

                for rel in entity_rels:
                    rel_type = rel.get("type", "RELATED_TO")
                    confidence = rel.get("confidence", 0.8)
                    from_name = rel.get("from")
                    to_name = rel.get("to")

                    # Validate relationship type (already done in extract_entity_relationships)
                    # KG-P2-1: Include extended relationship types
                    valid_types = [
                        "IS_A",
                        "PART_OF",
                        "RELATED_TO",
                        "DEPENDS_ON",
                        "ALTERNATIVE_TO",
                        "ENABLES",
                        "PREVENTS",
                        "REQUIRES",
                        "REFINES",
                    ]
                    if rel_type not in valid_types:
                        rel_type = "RELATED_TO"

                    # Resolve entity names to canonical forms
                    from_canonical = (
                        get_canonical_name(from_name) if from_name else None
                    )
                    to_canonical = get_canonical_name(to_name) if to_name else None

                    if from_canonical and to_canonical:
                        await session.run(
                            f"""
                            MATCH (e1:Entity)
                            WHERE toLower(e1.name) = toLower($from_name)
                               OR ANY(alias IN COALESCE(e1.aliases, []) WHERE toLower(alias) = toLower($from_name))
                            MATCH (e2:Entity)
                            WHERE toLower(e2.name) = toLower($to_name)
                               OR ANY(alias IN COALESCE(e2.aliases, []) WHERE toLower(alias) = toLower($to_name))
                            WITH e1, e2
                            WHERE e1 <> e2
                            MERGE (e1)-[r:{rel_type}]->(e2)
                            SET r.confidence = $confidence
                            """,
                            from_name=from_name,
                            to_name=to_name,
                            confidence=confidence,
                        )

            # Find and link similar decisions (if embedding exists)
            # Only compare with decisions from the same user for isolation
            if embedding:
                await self._link_similar_decisions(
                    session, decision_id, embedding, user_id
                )

            # Create temporal chains (INFLUENCED_BY)
            # Only within the same user's decisions
            await self._create_temporal_chains(session, decision_id, user_id)

        return decision_id

    async def _link_similar_decisions(
        self,
        session,
        decision_id: str,
        embedding: list[float],
        user_id: str,
    ):
        """Find semantically similar decisions and create SIMILAR_TO edges.

        Only compares within the same user's decisions for multi-tenant isolation.
        Uses configurable similarity threshold from settings.
        """
        try:
            # Use Neo4j vector search to find similar decisions within user scope
            result = await session.run(
                """
                MATCH (d:DecisionTrace)
                WHERE d.id <> $id AND d.embedding IS NOT NULL
                  AND (d.user_id = $user_id OR d.user_id IS NULL)
                WITH d, gds.similarity.cosine(d.embedding, $embedding) AS similarity
                WHERE similarity > $threshold
                RETURN d.id AS similar_id, similarity
                ORDER BY similarity DESC
                LIMIT 5
                """,
                id=decision_id,
                embedding=embedding,
                threshold=self.similarity_threshold,
                user_id=user_id,
            )

            records = [r async for r in result]

            for record in records:
                similar_id = record["similar_id"]
                similarity = record["similarity"]

                # Determine confidence tier
                confidence_tier = (
                    "high"
                    if similarity >= self.high_confidence_threshold
                    else "moderate"
                )

                await session.run(
                    """
                    MATCH (d1:DecisionTrace {id: $id1})
                    MATCH (d2:DecisionTrace {id: $id2})
                    MERGE (d1)-[r:SIMILAR_TO]->(d2)
                    SET r.score = $score, r.confidence_tier = $tier
                    """,
                    id1=decision_id,
                    id2=similar_id,
                    score=similarity,
                    tier=confidence_tier,
                )
                logger.info(
                    f"Linked similar decision {similar_id} (score: {similarity:.3f}, tier: {confidence_tier})"
                )

        except (ClientError, DatabaseError) as e:
            # GDS library may not be installed, fall back to manual calculation
            logger.debug(f"Vector search failed (GDS may not be installed): {e}")
            await self._link_similar_decisions_manual(
                session, decision_id, embedding, user_id
            )

    async def _link_similar_decisions_manual(
        self,
        session,
        decision_id: str,
        embedding: list[float],
        user_id: str,
    ):
        """Fallback: Calculate similarity manually without GDS.

        Only compares within the same user's decisions.
        """
        try:
            result = await session.run(
                """
                MATCH (d:DecisionTrace)
                WHERE d.id <> $id AND d.embedding IS NOT NULL
                  AND (d.user_id = $user_id OR d.user_id IS NULL)
                RETURN d.id AS other_id, d.embedding AS other_embedding
                """,
                id=decision_id,
                user_id=user_id,
            )

            records = [r async for r in result]

            for record in records:
                other_id = record["other_id"]
                other_embedding = record["other_embedding"]

                # Calculate cosine similarity
                similarity = cosine_similarity(embedding, other_embedding)

                if similarity > self.similarity_threshold:
                    # Determine confidence tier
                    confidence_tier = (
                        "high"
                        if similarity >= self.high_confidence_threshold
                        else "moderate"
                    )

                    await session.run(
                        """
                        MATCH (d1:DecisionTrace {id: $id1})
                        MATCH (d2:DecisionTrace {id: $id2})
                        MERGE (d1)-[r:SIMILAR_TO]->(d2)
                        SET r.score = $score, r.confidence_tier = $tier
                        """,
                        id1=decision_id,
                        id2=other_id,
                        score=similarity,
                        tier=confidence_tier,
                    )
                    logger.info(
                        f"Linked similar decision {other_id} (score: {similarity:.3f}, tier: {confidence_tier})"
                    )

        except (ClientError, DatabaseError) as e:
            logger.error(f"Manual similarity linking failed: {e}")

    async def _create_temporal_chains(self, session, decision_id: str, user_id: str):
        """Create INFLUENCED_BY edges based on shared entities and temporal order.

        Only creates chains within the same user's decisions.
        """
        try:
            # Find older decisions that share entities with this one (within user scope)
            await session.run(
                """
                MATCH (d_new:DecisionTrace {id: $new_id})
                MATCH (d_old:DecisionTrace)-[:INVOLVES]->(e:Entity)<-[:INVOLVES]-(d_new)
                WHERE d_old.id <> d_new.id AND d_old.created_at < d_new.created_at
                  AND (d_old.user_id = $user_id OR d_old.user_id IS NULL)
                WITH d_new, d_old, count(DISTINCT e) AS shared_count
                WHERE shared_count >= 2
                MERGE (d_new)-[r:INFLUENCED_BY]->(d_old)
                SET r.shared_entities = shared_count
                """,
                new_id=decision_id,
                user_id=user_id,
            )
            logger.debug(f"Created temporal chains for decision {decision_id}")
        except (ClientError, DatabaseError) as e:
            logger.error(f"Temporal chain creation failed: {e}")


# Singleton instance
_extractor: Optional[DecisionExtractor] = None


def get_extractor() -> DecisionExtractor:
    """Get the decision extractor singleton."""
    global _extractor
    if _extractor is None:
        _extractor = DecisionExtractor()
    return _extractor
