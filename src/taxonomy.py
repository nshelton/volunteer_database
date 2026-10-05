"""Shared skill taxonomy for the SIGGRAPH volunteer database.

The model is HYBRID:
  * a fixed set of top-level CATEGORIES (below) so volunteers can be matched
    cleanly against committee needs, plus
  * free-form `skills` / `tools` keyword tags the LLM extracts per person for
    nuance.

Categories are intentionally SIGGRAPH-flavoured (they span both the technical
craft and the operational roles a conference needs). Edit this list and the
whole pipeline + UI follow.
"""

from __future__ import annotations

# key -> (human label, short description used in the extraction prompt)
CATEGORIES: dict[str, tuple[str, str]] = {
    "rendering_graphics": ("Rendering & Graphics", "ray tracing, shaders, real-time rendering, GPU programming, graphics APIs"),
    "animation": ("Animation & Rigging", "character animation, rigging, motion, keyframe/procedural animation"),
    "modeling_geometry": ("Modeling & Geometry", "3D modeling, geometry processing, meshes, CAD, sculpting"),
    "simulation_vfx": ("Simulation & VFX", "physics simulation, fluids, particles, visual effects, compositing"),
    "machine_learning": ("Machine Learning & AI", "deep learning, generative models, neural rendering, ML research"),
    "computer_vision": ("Computer Vision", "image processing, tracking, reconstruction, photogrammetry, perception"),
    "ar_vr_xr": ("AR / VR / XR", "augmented/virtual/mixed reality, immersive experiences, headsets"),
    "game_dev": ("Game Development", "game engines (Unity/Unreal), gameplay, interactive real-time apps"),
    "web_dev": ("Web Development", "frontend/backend web, JS frameworks, WebGL/WebGPU, full-stack"),
    "software_engineering": ("Software Engineering", "general programming, systems, infrastructure, tooling, devops"),
    "design_ux": ("Design & UX", "UX/UI design, interaction design, product design, graphic design"),
    "art_illustration": ("Art & Illustration", "concept art, illustration, traditional/digital art, art direction"),
    "audio": ("Audio & Music", "sound design, music, audio engineering, spatial audio"),
    "research_academic": ("Research & Academia", "academic research, publications, peer review, PhD-level scientific work"),
    "production_pipeline": ("Production & Pipeline", "pipeline/technical direction, production management, studio workflows"),
    "hardware_systems": ("Hardware & Systems", "hardware, embedded, robotics, displays, fabrication, sensors"),
    "project_management": ("Project & Program Management", "project/program management, producing, coordination, leadership"),
    "communication_outreach": ("Communication & Outreach", "writing, marketing, social media, public relations, public speaking, media strategy"),
    # --- Organizational / leadership competencies (added from gdrive heading analysis;
    #     these dominate the senior-volunteer cohort and had no clean home before) ---
    "governance_leadership": ("Governance & Executive Leadership", "board service, non-profit/institutional governance, executive leadership, organizational strategy, fiduciary & advisory oversight"),
    "events_operations": ("Events & Conference Operations", "large-scale event & conference operations, logistics, program/content curation, juried selection, volunteer program direction"),
    "business_finance": ("Business, Finance & Strategy", "financial management, budgeting, treasury/fiduciary duties, commercial & product strategy, entrepreneurship, M&A, business development"),
    "education_teaching": ("Education & Teaching", "teaching, curriculum design, pedagogy, technical training, student mentorship, academic program development"),
    "mentorship_community": ("Mentorship, Community & DEI", "mentorship, community building, chapters & volunteer development, diversity/equity/inclusion advocacy, professional development"),
}

CATEGORY_KEYS = list(CATEGORIES.keys())

# Higher-level groups ("overall type") for clustering/coloring in the Skills
# graph. (group_key -> (label, hex color; deepened to hold up on the white UI)).
GROUPS: dict[str, tuple[str, str]] = {
    "research_academia": ("Research & Education", "#7062b3"),
    "ai_vision": ("AI & Vision", "#0c948a"),
    "graphics_animation": ("Graphics & Animation", "#d4732f"),
    "engineering": ("Engineering & Software", "#3f6524"),
    "art_design": ("Art & Design", "#b7548a"),
    "production_comms": ("Production & Communications", "#a1801d"),
    "leadership_org": ("Leadership & Operations", "#3d6ea8"),
}

# Which group each category belongs to.
CATEGORY_GROUP: dict[str, str] = {
    "research_academic": "research_academia",
    "machine_learning": "ai_vision",
    "computer_vision": "ai_vision",
    "rendering_graphics": "graphics_animation",
    "animation": "graphics_animation",
    "modeling_geometry": "graphics_animation",
    "simulation_vfx": "graphics_animation",
    "software_engineering": "engineering",
    "web_dev": "engineering",
    "hardware_systems": "engineering",
    "game_dev": "engineering",
    "ar_vr_xr": "engineering",
    "design_ux": "art_design",
    "art_illustration": "art_design",
    "audio": "art_design",
    "production_pipeline": "production_comms",
    "project_management": "production_comms",
    "communication_outreach": "production_comms",
    "education_teaching": "research_academia",
    "governance_leadership": "leadership_org",
    "events_operations": "leadership_org",
    "business_finance": "leadership_org",
    "mentorship_community": "leadership_org",
}

LEVELS = ["familiar", "proficient", "expert"]
SENIORITY = ["student", "junior", "mid", "senior", "principal", "academic", "executive"]


def category_label(key: str) -> str:
    return CATEGORIES.get(key, (key, ""))[0]


def prompt_category_block() -> str:
    """Render the category list for inclusion in the extraction prompt."""
    return "\n".join(f'  - {k}: {desc}' for k, (label, desc) in CATEGORIES.items())
