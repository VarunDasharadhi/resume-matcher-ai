"""Local resume <-> job-description analysis engine.

This module performs a real, dependency-free analysis: it extracts known
skills from free text using a curated skill library, compares the skills a
job description asks for against the skills present in a resume, and produces
a match score plus actionable suggestions.

It powers the app's offline / fallback mode so the product works end-to-end
even without an OpenAI API key, and it is also used to enrich the prompt sent
to GPT when a key is available.
"""
from __future__ import annotations

import re
from typing import Dict, List

# Canonical skill name -> list of aliases/spellings to match. The canonical
# name is what we report; any alias in the text counts as a hit. Aliases are
# case-insensitive unless written with an uppercase letter (see _alias_flags).
SKILL_LIBRARY: Dict[str, List[str]] = {
    # Languages
    "Python": ["python"],
    "JavaScript": ["javascript", "js", "ecmascript"],
    "TypeScript": ["typescript", "ts"],
    "Java": ["java"],
    "C++": [r"c\+\+", "cpp"],
    "C#": [r"c#", r"c♯", "csharp"],
    "Go": ["golang", "Go"],
    "Rust": ["rust"],
    "Ruby": ["ruby"],
    "PHP": ["php"],
    "Swift": ["Swift"],
    "Kotlin": ["kotlin"],
    "Scala": ["scala"],
    "R": [r"R(?!&)"],  # skip R&D
    "SQL": ["sql"],
    "Bash": ["bash", "shell scripting", "shell"],
    "HTML": ["html", "html5"],
    "CSS": ["css", "css3"],
    # Frontend
    "React": ["react", "react.js", "reactjs"],
    "Next.js": ["next.js", "nextjs"],
    "Vue": ["vue", "vue.js", "vuejs"],
    "Angular": ["angular", "angular.js", "angularjs"],
    "Svelte": ["svelte"],
    "Tailwind CSS": ["tailwind"],
    "Redux": ["redux"],
    "jQuery": ["jquery"],
    "Webpack": ["webpack"],
    "Vite": ["vite"],
    # Backend / frameworks
    "Node.js": ["node.js", "nodejs", "node"],
    "Express": ["express.js", "expressjs", "Express"],
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Spring": ["spring boot", r"Spring(?!\s+20\d\d)"],  # skip "Spring 2026"
    "Rails": ["ruby on rails", "Rails"],
    "Laravel": ["laravel"],
    ".NET": [r"\.net", "dotnet", "asp.net"],
    "GraphQL": ["graphql"],
    "REST APIs": ["rest api", "rest apis", "restful", "REST"],
    "gRPC": ["grpc"],
    "Microservices": ["microservice", "microservices"],
    # Data / ML
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "PyTorch": ["pytorch"],
    "TensorFlow": ["tensorflow"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"],
    "Data Analysis": ["data analysis", "data analytics"],
    "Data Science": ["data science"],
    "Spark": ["apache spark", "pyspark", "spark"],
    "Hadoop": ["hadoop"],
    "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"],
    "Excel": ["Excel", "microsoft excel", "ms excel"],
    "ETL": ["etl"],
    "Airflow": ["airflow"],
    # Databases
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "SQLite": ["sqlite"],
    "Elasticsearch": ["elasticsearch"],
    "DynamoDB": ["dynamodb"],
    "Cassandra": ["cassandra"],
    "Oracle": ["oracle db", "oracle"],
    # Cloud / DevOps
    "AWS": ["aws", "amazon web services"],
    "Azure": ["azure"],
    "GCP": ["gcp", "google cloud"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "Ansible": ["ansible"],
    "CI/CD": ["ci/cd", "cicd", "continuous integration", "continuous delivery"],
    "Jenkins": ["jenkins"],
    "GitHub Actions": ["github actions"],
    "Git": ["git"],
    "Linux": ["linux", "unix"],
    "Nginx": ["nginx"],
    "Kafka": ["kafka"],
    "RabbitMQ": ["rabbitmq"],
    # AI engineering / LLM stack
    "LLMs": ["llm", "llms", "large language model", "large language models"],
    "Prompt Engineering": ["prompt engineering", "prompting", "prompt design"],
    "AI Agents": ["ai agent", "ai agents", "agents", "agentic", "sub-agents", "subagents", "multi-agent"],
    "RAG": ["rag", "retrieval-augmented generation", "retrieval augmented generation"],
    "Embeddings": ["embedding", "embeddings", "vector search", "vector database", "vector databases"],
    "Fine-tuning": ["fine-tuning", "fine tuning", "finetuning"],
    "LLM Evaluation": ["evals", "evaluation framework", "evaluation frameworks", "llm evaluation"],
    "MCP": ["mcp", "model context protocol", "mcp server", "mcp servers"],
    "Claude API": ["claude", "anthropic api", "claude api", "claude code"],
    "OpenAI API": ["openai api", "gpt-4", "gpt-4o", "chatgpt api"],
    "Gemini": ["gemini"],
    "LangChain": ["langchain"],
    "LangGraph": ["langgraph"],
    "Generative AI": ["generative ai", "genai", "gen ai"],
    "Browser Automation": ["browser automation", "playwright", "puppeteer", "selenium"],
    "Workflow Orchestration": ["trigger.dev", "temporal", "workflow orchestration", "background jobs"],
    "Structured Outputs": ["structured output", "structured outputs", "function calling", "tool use", "tool calling"],
    # Practices / methods
    "Agile": ["agile"],
    "Scrum": ["scrum"],
    "TDD": ["tdd", "test-driven development", "test driven development"],
    "Unit Testing": ["unit testing", "unit tests"],
    "OOP": ["oop", "object-oriented", "object oriented"],
    "System Design": ["system design"],
    "API Design": ["api design"],
    # Design / product
    "Figma": ["figma"],
    "Adobe XD": ["adobe xd"],
    "Photoshop": ["photoshop"],
    "Illustrator": ["illustrator"],
    "UI/UX": ["ui/ux", "ux design", "ui design", "user experience"],
    "Product Management": ["product management", "product manager"],
    # Soft / professional skills
    "Communication": ["communication"],
    "Leadership": ["leadership", "team lead"],
    "Project Management": ["project management"],
    "Problem Solving": ["problem solving", "problem-solving"],
    "Collaboration": ["collaboration", "cross-functional"],
    "Mentoring": ["mentoring", "mentorship"],
}


def _alias_pattern(alias: str) -> str:
    """Build a word-boundary-aware regex for an alias.

    Aliases that already contain regex metacharacters (escaped manually in the
    library, e.g. ``c\\+\\+``) are used as-is; plain aliases get escaped and
    wrapped with boundaries so ``java`` does not match inside ``javascript``.
    """
    has_meta = any(ch in alias for ch in r"\.+*?()[]{}^$|")
    if has_meta:
        core = alias
    else:
        core = re.escape(alias)
    # Use lookarounds so symbols like + and # at edges still match correctly.
    return r"(?<![A-Za-z0-9])" + core + r"(?![A-Za-z0-9])"


def _alias_flags(alias: str) -> int:
    """Aliases written with an uppercase letter must match that exact casing.

    Words like ``Go``, ``Swift``, ``Excel`` or ``REST`` are also common
    English words; requiring the proper-noun casing avoids false positives
    ("go the extra mile", "excel at", "the rest of the team"). All-lowercase
    aliases keep matching case-insensitively.
    """
    return 0 if any(ch.isupper() for ch in alias) else re.IGNORECASE


# Pre-compile one combined check per canonical skill for speed.
_COMPILED: Dict[str, List[re.Pattern]] = {
    name: [re.compile(_alias_pattern(a), _alias_flags(a)) for a in aliases]
    for name, aliases in SKILL_LIBRARY.items()
}


def extract_skills(text: str) -> List[str]:
    """Return the canonical names of all known skills present in ``text``."""
    if not text:
        return []
    found: List[str] = []
    for name, patterns in _COMPILED.items():
        if any(p.search(text) for p in patterns):
            found.append(name)
    return found


def analyze_match(resume_text: str, job_description: str) -> Dict:
    """Compare a resume against a job description.

    Returns a dict with ``score`` (0-100 int), ``matching_skills``,
    ``missing_skills`` and ``suggestions``.
    """
    resume_text = resume_text or ""
    job_description = job_description or ""

    resume_skills = set(extract_skills(resume_text))
    job_skills = extract_skills(job_description)  # keep order of appearance

    matching = [s for s in job_skills if s in resume_skills]
    missing = [s for s in job_skills if s not in resume_skills]

    score = _score(matching, missing, resume_skills)
    suggestions = _suggestions(matching, missing, score, resume_text)

    return {
        "score": score,
        "matching_skills": matching,
        "missing_skills": missing,
        "suggestions": suggestions,
    }


def _score(matching: List[str], missing: List[str], resume_skills: set) -> int:
    """Compute a 0-100 match score.

    Primarily the share of the job's required skills the resume covers, with a
    small floor reflecting general overlap so a strong-but-imperfect resume is
    not punished too harshly, and a small bonus for relevant breadth.
    """
    required = len(matching) + len(missing)
    if required == 0:
        # No recognised skills in the JD: fall back to "is there any overlap?"
        return 60 if resume_skills else 40

    coverage = len(matching) / required
    base = coverage * 100

    # Breadth bonus: extra relevant skills on the resume beyond what's required.
    extra = len(resume_skills) - len(matching)
    bonus = min(8, max(0, extra)) if matching else 0

    score = int(round(base)) + bonus
    return max(0, min(100, score))


def _suggestions(
    matching: List[str], missing: List[str], score: int, resume_text: str
) -> List[str]:
    suggestions: List[str] = []

    if missing:
        top = ", ".join(missing[:6])
        suggestions.append(
            f"Add or highlight these in-demand skills the role asks for: {top}."
        )
        suggestions.append(
            "For each missing skill, add a concrete bullet point describing a "
            "project or task where you used it (or a related tool)."
        )
    if matching:
        kept = ", ".join(matching[:6])
        suggestions.append(
            f"Lead with your strongest matches ({kept}) near the top of the resume."
        )

    if not re.search(r"\d", resume_text):
        suggestions.append(
            "Quantify your impact with numbers (for example '%', 'x faster', "
            "'$ saved', 'users served'). Measurable results stand out."
        )

    if score >= 80:
        suggestions.append(
            "Strong fit. Tailor your summary statement to mirror the job's "
            "exact wording so it passes automated screeners (ATS)."
        )
    elif score >= 50:
        suggestions.append(
            "Decent fit. Close the remaining skill gaps and reorder your "
            "content so the most relevant experience appears first."
        )
    else:
        suggestions.append(
            "This role asks for skills not yet evident on your resume. Consider "
            "a short upskilling project, or target roles closer to your strengths."
        )

    return suggestions
