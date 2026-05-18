import logging
from datetime import datetime
from flask import Blueprint, jsonify

from app.db.arango import get_db, COLLECTIONS
from app.core.mistral_client import get_mistral_client

logger = logging.getLogger(__name__)

technical_design_bp = Blueprint("technical_design", __name__)

# Use larger output window than the default _chat helper allows (4096).
_LLM_MAX_TOKENS = 8192


# ═════════════════════════════════════════════════════════════════════════════
# 1.  CONTEXT RESOLVER
# ═════════════════════════════════════════════════════════════════════════════
def _resolve_doc_context(suggestion_key: str) -> dict:
    now = datetime.utcnow()
    ctx = {
        "suggestion_key": suggestion_key,
        "suggestion": None, "step": None, "process": None,
        "process_steps": [], "erp_module": None,
        "date": now.strftime("%B %Y"),
        "year": now.year,
        "organization": "PwC",
        "found": False,
    }
    try:
        db = get_db()
        col = db.collection

        suggestion = col(COLLECTIONS["suggestions"]).get(suggestion_key)
        if not suggestion:
            return ctx
        ctx["suggestion"] = suggestion
        ctx["found"] = True

        step_key = suggestion.get("step_key")
        if step_key:
            try:
                ctx["step"] = col(COLLECTIONS["steps"]).get(step_key)
            except Exception:
                pass

        process_key = suggestion.get("process_key")
        if process_key:
            try:
                ctx["process"] = col(COLLECTIONS["documents"]).get(process_key)
            except Exception:
                pass
            try:
                ctx["process_steps"] = list(db.aql(
                    "FOR s IN process_steps FILTER s.process_key == @key "
                    "SORT s.step_number RETURN s",
                    {"key": process_key},
                ))
            except Exception:
                pass
            try:
                erp_modules = list(db.aql(
                    "FOR m IN erp_modules FILTER m.process_key == @key RETURN m",
                    {"key": process_key},
                ))
                if erp_modules:
                    ctx["erp_module"] = erp_modules[0]
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[technical-design] context resolve failed: {e}")
    return ctx


# ═════════════════════════════════════════════════════════════════════════════
# 2.  HEADER FIELDS (deterministic — never LLM)
# ═════════════════════════════════════════════════════════════════════════════
def _derive_header_fields(ctx: dict) -> dict:
    suggestion = ctx.get("suggestion") or {}
    process = ctx.get("process") or {}
    erp = ctx.get("erp_module") or {}

    suggestion_title = (
        suggestion.get("title") or suggestion.get("name") or "Agentic AI Solution"
    )
    process_title = process.get("title") or process.get("name")
    erp_name = erp.get("name") or process.get("erp")

    parts = ["Agentic AI"]
    if process_title:
        parts.append(process_title)
    parts.append(suggestion_title)
    parts.append("Technical Design")
    doc_title = " – ".join(parts)

    return {
        "doc_title": doc_title,
        "subtitle": suggestion_title,
        "process_title": process_title or "Business Process",
        "suggestion_title": suggestion_title,
        "erp_name": erp_name,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 3.  MEGA-PROMPT BUILDER — asks for EVERY dynamic field
# ═════════════════════════════════════════════════════════════════════════════
def _build_full_prompt(ctx: dict, header: dict) -> str:
    suggestion = ctx.get("suggestion") or {}
    step = ctx.get("step") or {}
    process_steps = ctx.get("process_steps") or []

    suggestion_desc = suggestion.get("description") or suggestion.get("summary") or ""
    step_title = step.get("title") or ""
    step_desc = step.get("description") or ""

    step_lines = []
    for s in process_steps[:25]:
        step_lines.append(f"  - Step {s.get('step_number','?')}: {s.get('title','')}")
    steps_block = "\n".join(step_lines) or "  (no steps available)"

    return f"""You are a principal AI platform architect generating a FULL Technical Design
Document for a specific Agentic AI solution. Return ONLY a valid JSON object —
no markdown, no fences, no commentary. Output MUST start with {{ and end with }}.

==================== CONTEXT ====================
Process:               {header['process_title']}
Suggestion / Use-Case: {header['suggestion_title']}
ERP / Platform:        {header['erp_name'] or 'N/A'}
Step focus:            {step_title or 'N/A'}
Step description:      {step_desc or 'N/A'}
Suggestion notes:      {suggestion_desc or 'N/A'}

Process Steps:
{steps_block}

==================== REQUIRED JSON SHAPE ====================
Every field below MUST be present and tailored to the CONTEXT.

{{
  "domain": "<short domain tag, e.g. 'Agentic AI / SAP P2P / Invoice Processing'>",

  "exec_summary": {{
    "purpose": "<2 sentence purpose tailored to this use-case>",
    "problem_statement": "<concrete business problem this solves>",
    "primary_goals": ["<g1>", "<g2>", "<g3>", "<g4>", "<g5>"],
    "design_philosophy": "<one-sentence statement of design philosophy>"
  }},

  "design_principle_apps": {{
    "Context is King": "<how applied to this domain>",
    "System Prompts are Architecture": "<how applied>",
    "Agent Loop as Control System": "<how applied>",
    "Plan-and-Execute Reasoning": "<how applied>",
    "Design for Multi-Agent from Day One": "<how applied>",
    "Guardrails are Load-Bearing Walls": "<how applied>",
    "Evals are the Test Suite": "<how applied>"
  }},

  "agent_categories": [
    {{"type": "Advisory Agent",       "description": "<domain-specific>"}},
    {{"type": "Conversational Agent", "description": "<domain-specific>"}}
  ],

  "presentation_components": [
    {{"component_name": "<name>", "type": "<type>", "features": ["<f1>","<f2>","<f3>"]}}
  ],
  "presentation_supported_formats": ["PDF","DOCX","XLSX","CSV","TXT"],
  "frontend_stack": {{
    "framework": "<framework>", "language": "<lang>",
    "state_management": ["<sm1>","<sm2>"],
    "styling": ["<s1>","<s2>"],
    "chat_ui": ["<c1>","<c2>"],
    "document_viewer": "<viewer>",
    "api_communication": ["<a1>","<a2>","<a3>"]
  }},

  "api_gateway_components": [
    {{"component_name": "API Gateway", "technologies": ["<t1>","<t2>"], "responsibilities": ["<r1>","<r2>","<r3>"]}},
    {{"component_name": "Session Manager", "responsibilities": ["<r1>","<r2>"]}},
    {{"component_name": "Request Router",  "responsibilities": ["<r1>","<r2>"]}}
  ],
  "backend_server": {{
    "runtime": ["<r1>","<r2>"], "language": "Python",
    "features": ["<f1>","<f2>","<f3>","<f4>"]
  }},

  "orchestration_pattern": {{"type": "<pattern>", "workflow": "<workflow style>"}},

  "agents": [
    {{
      "agent_id": 1, "name": "Orchestrator Agent", "role": "Central coordinator",
      "reasoning_framework": "Plan-and-Execute", "model_tier": "<model>",
      "responsibilities": ["<r1>","<r2>","<r3>","<r4>"]
    }}
    // 5–7 agents total, derived from the process steps above
  ],

  "analysis_dimensions": ["<d1>","<d2>","<d3>","<d4>","<d5>","<d6>"],

  "rag_pipeline": [
    {{"stage": 1, "name": "<stage name>", "components": ["<c1>","<c2>"]}}
    // 5–7 stages
  ],
  "knowledge_stores": [
    {{"store_type": "Vector Database",  "technologies": ["<t1>","<t2>"]}},
    {{"store_type": "Knowledge Graph",  "technologies": ["<t1>"]}},
    {{"store_type": "Document Store",   "technologies": ["<t1>"]}},
    {{"store_type": "Metadata Store",   "technologies": ["<t1>"]}}
  ],
  "chunking_strategies": [
    {{"type": "<type>", "use_case": "<use_case>"}}
  ],

  "frameworks": {{
    "orchestration": [{{"name": "<n>", "role": "<r>", "features": ["<f1>","<f2>"]}}],
    "rag_frameworks": [{{"name": "<n>", "role": "<r>"}}],
    "protocols": [{{"name": "<n>", "full_form": "<ff>", "purpose": "<p>"}}],
    "guardrails": [{{"name": "<n>"}}],
    "evaluation_tools": [{{"name": "<n>"}}]
  }},

  "tools": [
    {{"tool_name": "<name>", "invoked_by": "<agent>", "purpose": "<purpose>"}}
    // 6–10 tools relevant to this domain
  ],

  "guardrails": [
    {{"rail_type": "Input Rails",     "functions": ["<f1>","<f2>"]}},
    {{"rail_type": "Dialog Rails",    "functions": ["<f1>","<f2>"]}},
    {{"rail_type": "Retrieval Rails", "functions": ["<f1>","<f2>"]}},
    {{"rail_type": "Execution Rails", "functions": ["<f1>","<f2>"]}},
    {{"rail_type": "Output Rails",    "functions": ["<f1>","<f2>"]}}
  ],
  "observability": {{
    "structured_logging": true, "distributed_tracing": true,
    "metrics_dashboard": true,  "anomaly_detection": true
  }},
  "governance": {{
    "prompt_registry": true, "eval_pipeline": true,
    "incident_response": true, "audit_trail": true
  }},

  "report_structure": ["Cover Page","Executive Summary","<s3>","<s4>","<s5>","<s6>","Recommended Actions","Appendices"],

  "workflows": [
    {{"workflow_name": "<workflow 1 specific to this use-case>"}},
    {{"workflow_name": "<workflow 2 specific to this use-case>"}}
  ],

  "memory_architecture": [
    {{"memory_type": "Episodic Memory",   "contents": ["<c1>","<c2>","<c3>"], "storage": ["<s1>","<s2>"]}},
    {{"memory_type": "Semantic Memory",   "contents": ["<c1>","<c2>","<c3>"], "storage": ["<s1>","<s2>"]}},
    {{"memory_type": "Procedural Memory", "contents": ["<c1>","<c2>","<c3>"], "storage": ["<s1>","<s2>"]}}
  ],
  "memory_critical_practices": ["<p1>","<p2>","<p3>","<p4>"],

  "tech_stack": {{
    "frontend":         ["<t1>","<t2>","<t3>","<t4>"],
    "api_gateway":      ["<t1>","<t2>"],
    "backend":          ["<t1>","<t2>","<t3>"],
    "llm_models":       ["<m1>","<m2>","<m3>"],
    "vector_db":        ["<v1>"],
    "knowledge_graph":  ["<k1>"],
    "storage":          ["<s1>","<s2>"],
    "session_db":       ["<s1>"],
    "guardrails":       ["<g1>","<g2>"],
    "observability":    ["<o1>","<o2>"],
    "containerization": ["<c1>","<c2>"]
  }},

  "eval_metrics": [
    {{"metric": "<name>", "target": "<target>"}}
    // 5–7 metrics: accuracy, faithfulness, latency, hallucination, satisfaction
  ],

  "chatbot": {{
    "termination_conditions": ["<c1>","<c2>","<c3>","<c4>","<c5>"],
    "loop_prevention":        ["<p1>","<p2>","<p3>"],
    "recovery_strategies":    ["<r1>","<r2>","<r3>","<r4>"],
    "compression_strategies": ["<s1>","<s2>","<s3>","<s4>","<s5>"],
    "budget_allocation": {{
      "system_prompt": "<%>", "domain_knowledge": "<%>",
      "conversation_summary": "<%>", "recent_turns": "<%>",
      "retrieved_chunks": "<%>", "tool_outputs": "<%>", "safety_buffer": "<%>"
    }},
    "overflow_prevention": ["<o1>","<o2>","<o3>","<o4>","<o5>"]
  }}
}}

==================== HARD RULES ====================
- Output MUST be ONE valid JSON object. No comments. No trailing commas.
- 5 presentation_components (Selector, Upload, Dashboard, Chatbot, Risk Summary equivalents — RENAME for this domain).
- 5–7 agents. First = Orchestrator. Include a conversational/assistant agent.
- 6–10 tools.
- 5–7 stages in rag_pipeline.
- 5–7 eval_metrics.
- budget_allocation percentages must sum to 100%.
- TAILOR every string to the CONTEXT. Avoid generic KT-risk wording unless this
  suggestion is genuinely about KT risk.
""".strip()


# ═════════════════════════════════════════════════════════════════════════════
# 4.  LLM CALL — direct client access for max_tokens=8192
# ═════════════════════════════════════════════════════════════════════════════
def _call_llm_full(prompt: str) -> dict:
    """One LLM call with extended max_tokens. Returns {} on any failure."""
    try:
        llm = get_mistral_client()
        response = llm.client.chat.complete(
            model=llm.model,
            messages=[
                {"role": "system",
                 "content": "You are an expert agentic-AI platform architect. Return ONLY valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=_LLM_MAX_TOKENS,
        )
        raw = response.choices[0].message.content
        parsed = llm._parse_json(raw)
        if isinstance(parsed, dict) and parsed:
            return parsed
        logger.warning("[technical-design] LLM returned non-dict — falling back")
    except Exception as e:
        logger.warning(f"[technical-design] LLM call failed: {e}")
    return {}


# ═════════════════════════════════════════════════════════════════════════════
# 5.  CANONICAL DEFAULTS — per-field fallback when LLM omits anything
# ═════════════════════════════════════════════════════════════════════════════
_DEF_EXEC_SUMMARY = {
    "purpose": "Agentic AI application for KT risk moderation during managed services engagements.",
    "problem_statement": "Gap between KT documentation and actual execution realities.",
    "primary_goals": [
        "Identify risks proactively", "Highlight SLA risks",
        "Detect failure-prone areas", "Generate structured Word reports",
        "Provide chatbot for post-KT support",
    ],
    "design_philosophy": (
        "AI agents are distributed software systems built around reasoning engines, "
        "context management, memory systems, tool ecosystems, and governance frameworks."
    ),
}

_DEF_PRINCIPLE_APPS = {
    "Context is King": "Context engineering across KT documents, ticket logs, and process knowledge",
    "System Prompts are Architecture": "Production-grade system prompts with boundaries and safety guardrails",
    "Agent Loop as Control System": "Observe → Reason → Plan → Act → Evaluate → Update Memory",
    "Plan-and-Execute Reasoning": "Structured multi-step workflow orchestration",
    "Design for Multi-Agent from Day One": "Architect for specialist sub-agents",
    "Guardrails are Load-Bearing Walls": "Enterprise-grade safety implementation",
    "Evals are the Test Suite": "Eval-driven development using RAGAS",
}

_DEF_AGENT_CATEGORIES = [
    {"type": "Advisory Agent",       "description": "Proactive risk identification and SLA advisory"},
    {"type": "Conversational Agent", "description": "Post-KT chatbot for ongoing support"},
]

_DEF_PRESENTATION_COMPONENTS = [
    {"component_name": "Application Selector Panel", "type": "Dropdown Interface",
     "features": ["Application type dropdown", "Dynamic application instance loading", "Metadata-driven population"]},
    {"component_name": "Document Upload Module", "type": "File Ingestion",
     "features": ["Drag-and-drop upload", "Connector selection", "Progress indicators", "Validation status"]},
    {"component_name": "Report Generation Dashboard", "type": "Workflow Dashboard",
     "features": ["One-click report generation", "Real-time progress tracking", "Downloadable Word output"]},
    {"component_name": "Embedded Chatbot Panel", "type": "Conversational UI",
     "features": ["Persistent chat window", "Conversation history", "Context awareness", "Follow-up support"]},
    {"component_name": "Risk Summary View", "type": "Visualization Dashboard",
     "features": ["Risk heat map", "Key findings cards", "SLA severity indicators"]},
]

_DEF_FRONTEND_STACK = {
    "framework": "React JS", "language": "TypeScript",
    "state_management": ["Redux Toolkit", "Zustand"],
    "styling": ["Tailwind CSS", "Ant Design"],
    "chat_ui": ["Chatscope", "Custom Widget"],
    "document_viewer": "React-PDF",
    "api_communication": ["Axios", "React Query", "WebSocket"],
}

_DEF_API_GATEWAY_COMPONENTS = [
    {"component_name": "API Gateway", "technologies": ["Kong", "AWS API Gateway"],
     "responsibilities": ["Route management", "Authentication", "Authorization", "Rate limiting", "Logging", "CORS"]},
    {"component_name": "Session Manager",
     "responsibilities": ["User session tracking", "Context mapping", "Session cleanup"]},
    {"component_name": "Request Router",
     "responsibilities": ["Intent classification", "Pipeline routing"]},
]

_DEF_BACKEND_SERVER = {
    "runtime": ["FastAPI", "Flask"], "language": "Python",
    "features": ["Async processing", "WebSocket streaming", "Celery queues", "Redis integration"],
}

_DEF_ORCHESTRATION_PATTERN = {"type": "Hierarchical Orchestrator", "workflow": "Sequential Sub-Pipelines"}

_DEF_AGENTS = [
    {"agent_id": 1, "name": "Orchestrator Agent", "role": "Central coordinator",
     "reasoning_framework": "Plan-and-Execute", "model_tier": "GPT-4o / Claude Sonnet",
     "responsibilities": ["Task decomposition", "Sub-agent delegation", "Error handling", "Termination management"]},
    {"agent_id": 2, "name": "Document Intake & Process Agent", "role": "Document ingestion and parsing",
     "processing_pipeline": ["Document type detection", "OCR extraction", "Metadata extraction", "Semantic chunking", "Entity extraction"],
     "supported_inputs": ["KT Documents", "Ticket Logs", "ServiceNow exports", "Unstructured documents"],
     "model_tier": "GPT-4o-mini"},
    {"agent_id": 3, "name": "Knowledge Base Builder Agent", "role": "Build vector store and knowledge graph",
     "responsibilities": ["Generate embeddings", "Index vector DB", "Build knowledge graph", "Freshness scoring", "TTL management"]},
    {"agent_id": 4, "name": "Risk Analysis Agent", "role": "Core analytical intelligence",
     "reasoning_framework": "Reflexion / Self-Refine"},
    {"agent_id": 5, "name": "Report Generator Agent", "role": "Generate formatted Word document",
     "output_format": ["Structured JSON", "Markdown", "DOCX"], "tool": "python-docx"},
    {"agent_id": 6, "name": "Chat Bot Agent", "role": "Conversational assistant",
     "reasoning_framework": "ReAct",
     "capabilities": ["Question answering", "Context retrieval", "Clarification support", "Human escalation"]},
]

_DEF_ANALYSIS_DIMENSIONS = [
    "KT coverage gaps", "Historical pain points", "SLA risk flags",
    "Knowledge dependency risks", "Severity classification", "Mitigation recommendations",
]

_DEF_RAG_PIPELINE = [
    {"stage": 1, "name": "Query Analysis",     "components": ["Intent Detector", "Entity Extractor"]},
    {"stage": 2, "name": "Query Rewriting",    "components": ["Query Reformulator"]},
    {"stage": 3, "name": "Hybrid Retrieval",   "components": ["Dense Retrieval", "Sparse Retrieval", "RRF"]},
    {"stage": 4, "name": "Metadata Filtering", "components": ["Filter Engine"]},
    {"stage": 5, "name": "Re-Ranking",         "components": ["Cross-Encoder Re-Ranker"]},
    {"stage": 6, "name": "GraphRAG",           "components": ["Knowledge Graph Traversal"]},
    {"stage": 7, "name": "Retrieval Rails",    "components": ["Safety Filter", "Freshness Validation"]},
]

_DEF_KNOWLEDGE_STORES = [
    {"store_type": "Vector Database", "technologies": ["Pinecone", "Weaviate", "ChromaDB"]},
    {"store_type": "Knowledge Graph", "technologies": ["Neo4j", "Amazon Neptune"]},
    {"store_type": "Document Store",  "technologies": ["AWS S3", "Azure Blob"]},
    {"store_type": "Metadata Store",  "technologies": ["PostgreSQL"]},
]

_DEF_CHUNKING = [
    {"type": "Semantic Chunking",     "use_case": "Process knowledge documents"},
    {"type": "Parent-Child Chunking", "use_case": "Ticket logs"},
    {"type": "Fixed-Size Chunking",   "use_case": "CSV/XLSX exports"},
]

_DEF_FRAMEWORKS = {
    "orchestration": [
        {"name": "LangGraph", "role": "Primary orchestration engine",
         "features": ["Stateful workflows", "Cyclic graphs", "Human-in-the-loop", "Streaming"]},
        {"name": "LangChain", "role": "LLM abstraction and tooling",
         "features": ["Prompt templates", "Tool calling", "Document loaders", "Output parsing"]},
    ],
    "rag_frameworks": [
        {"name": "LlamaIndex",           "role": "Advanced RAG pipeline"},
        {"name": "LangChain Retrievers", "role": "Lightweight retrieval"},
    ],
    "protocols": [
        {"name": "MCP", "full_form": "Model Context Protocol",  "purpose": "Tool connectivity"},
        {"name": "A2A", "full_form": "Agent-to-Agent Protocol", "purpose": "Cross-agent communication"},
    ],
    "guardrails":       [{"name": "NVIDIA NeMo Guardrails"}, {"name": "Guardrails AI"}, {"name": "Llama Guard"}],
    "evaluation_tools": [{"name": "RAGAS"}, {"name": "LangSmith"}, {"name": "OpenTelemetry"}],
}

_DEF_TOOLS = [
    {"tool_name": "Document Parser Tool",              "invoked_by": "Document Intake Agent",  "purpose": "Parse structured and unstructured documents"},
    {"tool_name": "ServiceNow Connector",              "invoked_by": "Document Intake Agent",  "purpose": "Fetch issue logs"},
    {"tool_name": "SharePoint / Confluence Connector", "invoked_by": "Document Intake Agent",  "purpose": "Fetch process documents"},
    {"tool_name": "Embedding Generator Tool",          "invoked_by": "Knowledge Base Builder", "purpose": "Generate embeddings"},
    {"tool_name": "Vector DB CRUD Tool",               "invoked_by": "RAG Pipeline",           "purpose": "Manage vector operations"},
    {"tool_name": "Knowledge Graph Tool",              "invoked_by": "Risk Analysis Agent",    "purpose": "Entity relationship operations"},
    {"tool_name": "Word Document Generator Tool",      "invoked_by": "Report Generator Agent", "purpose": "Generate DOCX"},
    {"tool_name": "Web Search Tool",                   "invoked_by": "Risk Analysis Agent",    "purpose": "Fetch external advisories"},
]

_DEF_GUARDRAILS = [
    {"rail_type": "Input Rails",     "functions": ["PII detection", "Injection detection", "Topic filtering"]},
    {"rail_type": "Dialog Rails",    "functions": ["Conversation control", "Behavior enforcement"]},
    {"rail_type": "Retrieval Rails", "functions": ["Relevance filtering", "Freshness validation"]},
    {"rail_type": "Execution Rails", "functions": ["Tool parameter validation", "Permission checks"]},
    {"rail_type": "Output Rails",    "functions": ["Hallucination detection", "PII scrubbing", "Compliance checks"]},
]

_DEF_OBSERVABILITY = {"structured_logging": True, "distributed_tracing": True,
                       "metrics_dashboard": True, "anomaly_detection": True}
_DEF_GOVERNANCE    = {"prompt_registry": True, "eval_pipeline": True,
                       "incident_response": True, "audit_trail": True}

_DEF_REPORT_STRUCTURE = [
    "Cover Page", "Executive Summary", "Risk Register Table",
    "Application-Wise Findings", "KT Coverage Gap Analysis", "SLA Risk Flags",
    "Recommended Actions", "Appendices",
]

_DEF_WORKFLOWS = [
    {"workflow_name": "Report Generation Flow"},
    {"workflow_name": "ChatBot Query Flow"},
]

_DEF_MEMORY_ARCH = [
    {"memory_type": "Episodic Memory",   "contents": ["Conversation history", "Past sessions", "Interaction logs"], "storage": ["Redis", "PostgreSQL"]},
    {"memory_type": "Semantic Memory",   "contents": ["Knowledge base", "SLA libraries", "Risk patterns"],          "storage": ["Vector DB", "Knowledge Graph"]},
    {"memory_type": "Procedural Memory", "contents": ["Learned workflows", "Response templates", "Retrieval strategies"], "storage": ["Prompt configurations", "Fine-tuning store"]},
]
_DEF_MEMORY_PRACTICES = ["TTL on memories", "Relevance scoring", "Memory poisoning defense", "Tenant isolation"]

_DEF_TECH_STACK = {
    "frontend":         ["React JS", "TypeScript", "Redux", "Tailwind CSS"],
    "api_gateway":      ["Kong", "AWS API Gateway"],
    "backend":          ["FastAPI", "Celery", "Redis"],
    "llm_models":       ["GPT-4o", "Claude Sonnet", "GPT-4o-mini"],
    "vector_db":        ["Pinecone", "Weaviate", "ChromaDB"],
    "knowledge_graph":  ["Neo4j", "Amazon Neptune"],
    "storage":          ["AWS S3", "Azure Blob"],
    "session_db":       ["PostgreSQL"],
    "guardrails":       ["NeMo Guardrails", "Guardrails AI"],
    "observability":    ["OpenTelemetry", "Datadog", "Jaeger"],
    "containerization": ["Docker", "Kubernetes"],
}

_DEF_EVAL_METRICS = [
    {"metric": "Risk Identification Accuracy", "target": ">= 85%"},
    {"metric": "Faithfulness (RAGAS)",         "target": ">= 0.90"},
    {"metric": "Context Precision",            "target": ">= 0.85"},
    {"metric": "Report Generation Time",       "target": "< 3 minutes"},
    {"metric": "Chatbot Answer Relevancy",     "target": ">= 0.85"},
    {"metric": "User Satisfaction",            "target": ">= 4.0 / 5.0"},
    {"metric": "Hallucination Rate",           "target": "< 5%"},
]

_DEF_CHATBOT = {
    "termination_conditions": [
        "Maximum iteration limit", "Confidence threshold", "Task completion signal",
        "User-initiated stop", "Timeout threshold", "Token budget exhaustion",
    ],
    "loop_prevention":    ["Repetition detector", "Progress tracker", "Observation anomaly monitor"],
    "recovery_strategies":["Retry with reformulation", "Fallback retrieval", "Human handoff", "Manus principle"],
    "compression_strategies": [
        "Sliding window", "Summarization chains", "Note-taking pattern",
        "Self-baking context", "Stable prefix/dynamic suffix",
    ],
    "budget_allocation": {
        "system_prompt": "15%", "domain_knowledge": "10%",
        "conversation_summary": "10%", "recent_turns": "20%",
        "retrieved_chunks": "30%", "tool_outputs": "10%", "safety_buffer": "5%",
    },
    "overflow_prevention": [
        "Pre-assembly token counting", "Aggressive summarization",
        "Retrieval chunk limiting", "Tool output truncation", "Circuit breaker",
    ],
}


def _pick(value, default):
    """Use value if non-empty list/dict/str, else default."""
    if value is None:
        return default
    if isinstance(value, (list, dict, str)) and not value:
        return default
    return value


def _merge_dict(value, default):
    """Like _pick for dicts, but per-key fallback (dict union)."""
    if not isinstance(value, dict) or not value:
        return default
    out = dict(default)
    for k, v in value.items():
        if v is None or (isinstance(v, (list, dict, str)) and not v):
            continue
        out[k] = v
    return out


# ═════════════════════════════════════════════════════════════════════════════
# 6.  PAYLOAD BUILDER — assembles final JSON from dynamic + canonical
# ═════════════════════════════════════════════════════════════════════════════
def _build_technical_design(ctx: dict, header: dict, dyn: dict) -> dict:
    org   = ctx["organization"]
    date  = ctx["date"]
    year  = ctx["year"]
    title = header["doc_title"]

    # ── Per-field merge with defaults ────────────────────────────────────────
    domain                = _pick(dyn.get("domain"), f"Agentic AI / {header['process_title']}")
    exec_summary          = _merge_dict(dyn.get("exec_summary"), _DEF_EXEC_SUMMARY)
    principle_apps        = _merge_dict(dyn.get("design_principle_apps"), _DEF_PRINCIPLE_APPS)
    agent_categories      = _pick(dyn.get("agent_categories"), _DEF_AGENT_CATEGORIES)
    pres_components       = _pick(dyn.get("presentation_components"), _DEF_PRESENTATION_COMPONENTS)
    pres_formats          = _pick(dyn.get("presentation_supported_formats"), ["PDF","DOCX","XLSX","CSV","TXT"])
    frontend_stack        = _merge_dict(dyn.get("frontend_stack"), _DEF_FRONTEND_STACK)
    api_gw_components     = _pick(dyn.get("api_gateway_components"), _DEF_API_GATEWAY_COMPONENTS)
    backend_server        = _merge_dict(dyn.get("backend_server"), _DEF_BACKEND_SERVER)
    orchestration_pattern = _merge_dict(dyn.get("orchestration_pattern"), _DEF_ORCHESTRATION_PATTERN)
    agents                = _pick(dyn.get("agents"), _DEF_AGENTS)
    analysis_dimensions   = _pick(dyn.get("analysis_dimensions"), _DEF_ANALYSIS_DIMENSIONS)
    rag_pipeline          = _pick(dyn.get("rag_pipeline"), _DEF_RAG_PIPELINE)
    knowledge_stores      = _pick(dyn.get("knowledge_stores"), _DEF_KNOWLEDGE_STORES)
    chunking_strategies   = _pick(dyn.get("chunking_strategies"), _DEF_CHUNKING)
    frameworks            = _merge_dict(dyn.get("frameworks"), _DEF_FRAMEWORKS)
    tools                 = _pick(dyn.get("tools"), _DEF_TOOLS)
    guardrails            = _pick(dyn.get("guardrails"), _DEF_GUARDRAILS)
    observability         = _merge_dict(dyn.get("observability"), _DEF_OBSERVABILITY)
    governance            = _merge_dict(dyn.get("governance"), _DEF_GOVERNANCE)
    report_structure      = _pick(dyn.get("report_structure"), _DEF_REPORT_STRUCTURE)
    workflows             = _pick(dyn.get("workflows"), _DEF_WORKFLOWS)
    memory_architecture   = _pick(dyn.get("memory_architecture"), _DEF_MEMORY_ARCH)
    memory_practices      = _pick(dyn.get("memory_critical_practices"), _DEF_MEMORY_PRACTICES)
    tech_stack            = _merge_dict(dyn.get("tech_stack"), _DEF_TECH_STACK)
    eval_metrics          = _pick(dyn.get("eval_metrics"), _DEF_EVAL_METRICS)
    chatbot               = _merge_dict(dyn.get("chatbot"), _DEF_CHATBOT)

    # Inject the document_viewer + supported_formats into the Upload component
    for c in pres_components:
        if "Upload" in c.get("component_name", "") and "supported_formats" not in c:
            c["supported_formats"] = pres_formats

    # Inject analysis_dimensions + rag_integration into the Risk Analysis Agent
    for a in agents:
        if a.get("agent_id") == 4 and "analysis_dimensions" not in a:
            a["analysis_dimensions"] = analysis_dimensions
            a["rag_integration"] = {
                "retrieval_type": "Hybrid Retrieval",
                "techniques": ["Dense retrieval", "Sparse retrieval", "Cross-encoder reranking", "GraphRAG"],
            }

    # Build principles list in canonical order from the LLM's applications map
    principles = [
        {"id": i + 1, "name": name,
         "application": principle_apps.get(name, _DEF_PRINCIPLE_APPS[name])}
        for i, name in enumerate(_DEF_PRINCIPLE_APPS.keys())
    ]

    return {
        "document_metadata": {
            "title": title,
            "version": "Draft V1.0",
            "date": date,
            "organization": org,
            "document_type": "Technical Design Document",
            "pages": 34,
            "classification": "Draft",
            "domain": domain,
        },
        "cover_page": {
            "title": title,
            "subtitle": header["subtitle"],
            "version": "Draft V1.0",
            "date": date,
            "organization": org,
        },
        "table_of_contents": [
            {"section_number": "1", "title": "Executive Summary", "page": 4},
            {"section_number": "2", "title": "Solution Overview & Design Principles", "page": 5,
             "subsections": [
                 {"section_number": "2.1", "title": "Design Principles Aligned to Best Practices"},
                 {"section_number": "2.2", "title": "Agent Category Classification"},
             ]},
            {"section_number": "3", "title": "Core Architecture Design", "page": 6,
             "subsections": [
                 {"section_number": "3.1", "title": "High-Level Architecture Layers"},
                 {"section_number": "3.2", "title": "Presentation Layer (React JS Front-End)"},
                 {"section_number": "3.3", "title": "API Gateway & Orchestration Layer"},
                 {"section_number": "3.4", "title": "Layer 3 Agentic Core (Multi-Agent Orchestrator)"},
                 {"section_number": "3.5", "title": "Special Considerations for Chat Bot"},
                 {"section_number": "3.6", "title": "RAG and Knowledge Systems"},
             ]},
            {"section_number": "4",  "title": "Agentic Frameworks and SDK Selection",     "page": 20},
            {"section_number": "5",  "title": "Tool Ecosystem and Integrations",          "page": 24},
            {"section_number": "6",  "title": "Guardrails, Observability and Governance", "page": 25},
            {"section_number": "8",  "title": "End-to-End Workflows",                     "page": 29},
            {"section_number": "9",  "title": "Memory",                                   "page": 30},
            {"section_number": "10", "title": "Tech Stack Summary",                       "page": 31},
            {"section_number": "11", "title": "Success Criteria and Eval Metrics",        "page": 32},
        ],
        "sections": [
            # ── 1. Executive Summary ─────────────────────────────────────────
            {
                "section_number": "1",
                "title": "Executive Summary",
                "content": {
                    "purpose":           exec_summary.get("purpose"),
                    "problem_statement": exec_summary.get("problem_statement"),
                    "primary_goals":     exec_summary.get("primary_goals"),
                    "design_philosophy": {"statement": exec_summary.get("design_philosophy")},
                },
            },
            # ── 2. Solution Overview & Design Principles ─────────────────────
            {
                "section_number": "2",
                "title": "Solution Overview & Design Principles",
                "subsections": [
                    {"section_number": "2.1", "title": "Design Principles Aligned to Best Practices", "principles": principles},
                    {"section_number": "2.2", "title": "Agent Category Classification", "categories": agent_categories},
                ],
            },
            # ── 3. Core Architecture Design ──────────────────────────────────
            {
                "section_number": "3",
                "title": "Core Architecture Design",
                "architecture_layers": [
                    {"layer_id": 1, "name": "Presentation Layer",
                     "components": pres_components,
                     "frontend_stack": frontend_stack},
                    {"layer_id": 2, "name": "API Gateway & Orchestration Layer",
                     "components": api_gw_components,
                     "backend_server": backend_server},
                    {"layer_id": 3, "name": "Agentic Core",
                     "orchestration_pattern": orchestration_pattern,
                     "agents": agents},
                    {"layer_id": 4, "name": "RAG and Knowledge Systems",
                     "rag_pipeline": rag_pipeline,
                     "knowledge_stores": knowledge_stores,
                     "chunking_strategies": chunking_strategies},
                ],
            },
            # ── 4. Frameworks ────────────────────────────────────────────────
            {"section_number": "4", "title": "Agentic Frameworks and SDK Selection", "frameworks": frameworks},
            # ── 5. Tools ─────────────────────────────────────────────────────
            {"section_number": "5", "title": "Tool Ecosystem and Integrations",
             "tools": tools,
             "tool_interface_standards": {"protocol": "MCP-inspired", "schema_validation": True, "execution_rails": True}},
            # ── 6. Guardrails / Observability / Governance ───────────────────
            {"section_number": "6", "title": "Guardrails, Observability and Governance",
             "guardrails": guardrails,
             "observability": observability,
             "governance": governance},
            # ── 7. Word Report Generation ────────────────────────────────────
            {"section_number": "7", "title": "Word Report Generation",
             "report_structure": report_structure,
             "formatting_rules": {
                 "headings": ["Heading 1", "Heading 2", "Heading 3"],
                 "tables": {"bordered": True, "alternating_rows": True, "severity_color_coding": True},
                 "branding": f"{org} Standards",
                 "generation_tool": "python-docx",
             }},
            # ── 8. Workflows ─────────────────────────────────────────────────
            {"section_number": "8", "title": "End-to-End Workflows", "workflows": workflows},
            # ── 9. Memory ────────────────────────────────────────────────────
            {"section_number": "9", "title": "Memory",
             "memory_architecture": memory_architecture,
             "critical_practices": memory_practices},
            # ── 10. Tech Stack Summary ───────────────────────────────────────
            {"section_number": "10", "title": "Tech Stack Summary", "stack": tech_stack},
            # ── 11. Eval Metrics ─────────────────────────────────────────────
            {"section_number": "11", "title": "Success Criteria and Eval Metrics", "metrics": eval_metrics},
        ],
        "chatbot_special_considerations": {
            "termination_design": {"conditions": chatbot.get("termination_conditions")},
            "loop_prevention":     chatbot.get("loop_prevention"),
            "recovery_strategies": chatbot.get("recovery_strategies"),
            "context_compression": {
                "strategies":         chatbot.get("compression_strategies"),
                "budget_allocation":  chatbot.get("budget_allocation"),
            },
            "overflow_prevention":  chatbot.get("overflow_prevention"),
        },
        "document_generation_schema": {
            "input": {
                "application_name": header["suggestion_title"],
                "uploaded_documents": [], "ticket_logs": [], "risk_analysis_results": [],
            },
            "intermediate_output": {
                "structured_json": {
                    "executive_summary": {}, "risk_register": [],
                    "application_findings": [], "sla_flags": [],
                    "recommended_actions": [], "appendices": [],
                }
            },
            "final_output": {"format": "DOCX", "generator": "python-docx"},
        },
        "footer": {
            "data_classification": "[ ]",
            "legal_notice": f"© {year} PricewaterhouseCoopers Private Limited. All rights reserved.",
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# 7.  ROUTE
# ═════════════════════════════════════════════════════════════════════════════
@technical_design_bp.get("/suggestions/<suggestion_key>/technical-design")
def get_technical_design(suggestion_key: str):
    """
    GET /api/suggestions/<suggestion_key>/technical-design
    Returns a fully LLM-generated Technical Design Document JSON.
    """
    try:
        ctx = _resolve_doc_context(suggestion_key)
        header = _derive_header_fields(ctx)

        # Single mega-call to the LLM for ALL dynamic content
        dyn = {}
        if ctx["found"]:
            dyn = _call_llm_full(_build_full_prompt(ctx, header))

        payload = _build_technical_design(ctx, header, dyn)

        # debug breadcrumbs (safe to remove)
        payload["document_metadata"]["suggestion_key"] = suggestion_key
        payload["document_metadata"]["suggestion_resolved"] = ctx["found"]
        payload["document_metadata"]["llm_generated"] = bool(dyn)

        return jsonify(payload), 200

    except Exception as e:
        logger.error(
            f"[technical-design] failed for suggestion_key={suggestion_key}: {e}",
            exc_info=True,
        )
        return jsonify({
            "status": False,
            "message": "Could not build technical design",
            "data": None,
        }), 500