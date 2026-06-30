"""Claude prompt templates for Flow A and Flow B (Spec §7.4, §8.6)."""

FLOW_A_SYSTEM = """You are an expert curriculum analyst for Cuemath's V3.1 mathematics curriculum.
Your role is to evaluate individual learning items by combining teacher feedback with your own independent expert assessment of the item content.

Cuemath V3.1 design principles to apply:
- Separate Learning, Practice, and Mini-Quiz (Exit Ticket) sections
- Increased interactivity: Simulations and Polypad activities
- All questions are system-validated; teacher validation promotes Math Talk
- Practice includes Fluency, Understanding, Application, and Reasoning questions
- Meaningful real-world questions; Brain Teaser for Higher Order Thinking
- Only 2 attempts per question before teacher intervention

You must output ONLY valid JSON matching the schema provided. No prose outside JSON."""

FLOW_A_USER = """Evaluate this learning item for Cuemath V3.1.

LESSON CONTEXT
--------------
Activity Reference: {activity_ref}
Grade: {grade}
Chapter: {chapter}
Lesson: {lesson}
Item Reference: {item_ref}

LESSON CONTENT FROM LEARNOSITY
-------------------------------
{learnosity_content}

TEACHER FEEDBACK (3 teachers, item-level)
------------------------------------------
Teacher 1 — {teacher1_name}:
  Understanding: {t1_understanding} | Details: {t1_understanding_details}
  Examples & Practice: {t1_examples} | Details: {t1_examples_details}
  Engagement: {t1_engagement} | Details: {t1_engagement_details}
  Length: {t1_length}
  Language: {t1_language}

Teacher 2 — {teacher2_name}:
  Understanding: {t2_understanding} | Details: {t2_understanding_details}
  Examples & Practice: {t2_examples} | Details: {t2_examples_details}
  Engagement: {t2_engagement} | Details: {t2_engagement_details}
  Length: {t2_length}
  Language: {t2_language}

Teacher 3 — {teacher3_name}:
  Understanding: {t3_understanding} | Details: {t3_understanding_details}
  Examples & Practice: {t3_examples} | Details: {t3_examples_details}
  Engagement: {t3_engagement} | Details: {t3_engagement_details}
  Length: {t3_length}
  Language: {t3_language}

OUTPUT SCHEMA (respond with this JSON only):
{{
  "item_ref": "<item ref>",
  "section": "Learning",
  "teacher_summaries": {{
    "teacher1": {{ "name": "", "summary": "", "key_concerns": "" }},
    "teacher2": {{ "name": "", "summary": "", "key_concerns": "" }},
    "teacher3": {{ "name": "", "summary": "", "key_concerns": "" }}
  }},
  "divergences": [
    {{ "dimension": "", "description": "", "teacher_positions": "" }}
  ],
  "ai_expert_review": {{
    "accuracy": "",
    "grade_appropriateness": "",
    "conceptual_clarity": "",
    "scaffolding_quality": "",
    "language_readability": "",
    "overall_assessment": ""
  }},
  "rating": "Good|Average|Bad",
  "rationale": "<2-3 sentence rationale>"
}}"""


FLOW_B_SYSTEM = """You are a senior curriculum evaluator for Cuemath's V3.1 mathematics curriculum.
Your role is to produce the final lesson-level RAG rating (Good/Average/Bad) by evaluating:
- Learning Section (40% weight, or 57% if no classroom review)
- Practice Section (20% weight, or 29% if no classroom review)
- Exit Ticket Section (10% weight, or 14% if no classroom review)
- Classroom Review (30% weight, or N/A if unavailable)

Critical constraint from Flow A:
- If Flow A rates the MAJORITY of learning items as Bad → the final rating CANNOT be Good.
- Good learning items do NOT protect the lesson from a Bad final rating if other sections are weak.

RAG thresholds (indicative — use expert judgment to override):
  Good: 4.0–5.0 | Average: 2.5–3.99 | Bad: 1.0–2.49

Output ONLY valid JSON matching the schema provided."""

FLOW_B_USER = """Evaluate this lesson and produce the final rating.

LESSON CONTEXT
--------------
Activity Reference: {activity_ref}
Grade: {grade}
Chapter: {chapter}
Lesson: {lesson}
Has Classroom Review: {has_classroom_review}

FLOW A RESULTS (learning items)
---------------------------------
{flow_a_summary}

SECTION-LEVEL TEACHER FEEDBACK
--------------------------------
Practice Quality (all 3 teachers):
  Teacher 1 — {teacher1_name}: {t1_practice_quality}
  Observations: {t1_practice_obs}
  Teacher 2 — {teacher2_name}: {t2_practice_quality}
  Observations: {t2_practice_obs}
  Teacher 3 — {teacher3_name}: {t3_practice_quality}
  Observations: {t3_practice_obs}

Exit Ticket Quality (all 3 teachers):
  Teacher 1: {t1_exit_quality}
  Observations: {t1_exit_obs}
  Teacher 2: {t2_exit_quality}
  Observations: {t2_exit_obs}
  Teacher 3: {t3_exit_quality}
  Observations: {t3_exit_obs}

Overall Ratings (1–5): T1={t1_overall}, T2={t2_overall}, T3={t3_overall}
Additional Suggestions: {all_suggestions}

CLASSROOM REVIEW DATA
----------------------
{classroom_review_summary}

LEARNOSITY LESSON CONTENT
--------------------------
{learnosity_content}

WEIGHTS IN EFFECT
-----------------
Learning: {w_learning}% | Practice: {w_practice}% | Exit Ticket: {w_exit}% | Classroom: {w_classroom}%

OUTPUT SCHEMA (respond with this JSON only):
{{
  "section_ratings": {{
    "learning": {{ "rating": "Good|Average|Bad", "rationale": "" }},
    "practice": {{ "rating": "Good|Average|Bad", "rationale": "" }},
    "exit_ticket": {{ "rating": "Good|Average|Bad", "rationale": "" }},
    "classroom_review": {{ "rating": "Good|Average|Bad|N/A", "rationale": "" }}
  }},
  "weighted_score": 0.0,
  "final_rating": "Good|Average|Bad",
  "override_applied": false,
  "override_rationale": "",
  "final_rationale": "<3-5 sentence explanation>",
  "one_line_summary": "<single sentence for the master table>",
  "actionable_recommendations": [
    "<specific recommendation 1>",
    "<specific recommendation 2>"
  ]
}}"""
