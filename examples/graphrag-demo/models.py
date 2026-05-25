"""Biomedical Research Knowledge Graph — complex domain models."""

from cypher_validator.models.orm import NodeModel, RelationshipModel, VectorProperty


# ---------------------------------------------------------------------------
# Node models
# ---------------------------------------------------------------------------


class Researcher(NodeModel):
    __label__ = "Researcher"
    __description__ = "A scientist or principal investigator"
    __vector_indexes__ = {
        "bio_embedding": VectorProperty(dimensions=384, similarity="cosine"),
    }
    name: str
    orcid: str = ""
    h_index: int = 0
    specialization: str = ""
    bio: str = ""
    bio_embedding: list[float] = []


class Institution(NodeModel):
    __label__ = "Institution"
    __description__ = "University, hospital, or research institute"
    name: str
    country: str = ""
    type: str = ""  # university, hospital, pharma, government


class Paper(NodeModel):
    __label__ = "Paper"
    __description__ = "A published research paper"
    __vector_indexes__ = {
        "abstract_embedding": VectorProperty(dimensions=384, similarity="cosine"),
    }
    title: str
    doi: str = ""
    year: int = 0
    journal: str = ""
    citation_count: int = 0
    abstract: str = ""
    abstract_embedding: list[float] = []


class Disease(NodeModel):
    __label__ = "Disease"
    __description__ = "A medical condition or disease"
    __vector_indexes__ = {
        "description_embedding": VectorProperty(dimensions=384, similarity="cosine"),
    }
    name: str
    icd_code: str = ""
    category: str = ""
    description: str = ""
    description_embedding: list[float] = []


class Drug(NodeModel):
    __label__ = "Drug"
    __description__ = "A pharmaceutical compound"
    name: str
    drugbank_id: str = ""
    phase: str = ""  # preclinical, phase1, phase2, phase3, approved
    mechanism: str = ""


class Gene(NodeModel):
    __label__ = "Gene"
    __description__ = "A human gene involved in disease pathways"
    symbol: str
    full_name: str = ""
    chromosome: str = ""
    pathway: str = ""


class ClinicalTrial(NodeModel):
    __label__ = "ClinicalTrial"
    __description__ = "A registered clinical trial"
    trial_id: str
    title: str = ""
    phase: str = ""
    status: str = ""  # recruiting, active, completed, terminated
    enrollment: int = 0
    start_year: int = 0


class FundingAgency(NodeModel):
    __label__ = "FundingAgency"
    __description__ = "Organization that funds research"
    name: str
    country: str = ""
    type: str = ""  # government, foundation, industry


# ---------------------------------------------------------------------------
# Relationship models
# ---------------------------------------------------------------------------


class AuthoredBy(RelationshipModel):
    __source__ = Paper
    __target__ = Researcher
    __rel_type__ = "AUTHORED_BY"
    position: str = ""  # first, middle, last, corresponding


class AffiliatedWith(RelationshipModel):
    __source__ = Researcher
    __target__ = Institution
    __rel_type__ = "AFFILIATED_WITH"
    role: str = ""  # professor, postdoc, researcher
    since: int = 0


class Cites(RelationshipModel):
    __source__ = Paper
    __target__ = Paper
    __rel_type__ = "CITES"
    context: str = ""  # methodology, results, background


class StudiesDisease(RelationshipModel):
    __source__ = Paper
    __target__ = Disease
    __rel_type__ = "STUDIES"


class TreatsWith(RelationshipModel):
    __source__ = Disease
    __target__ = Drug
    __rel_type__ = "TREATS_WITH"
    efficacy: str = ""  # high, moderate, low


class TargetsGene(RelationshipModel):
    __source__ = Drug
    __target__ = Gene
    __rel_type__ = "TARGETS"
    action: str = ""  # inhibitor, agonist, antagonist, modulator


class AssociatedGene(RelationshipModel):
    __source__ = Disease
    __target__ = Gene
    __rel_type__ = "ASSOCIATED_WITH"
    evidence_level: str = ""  # strong, moderate, suggestive


class TestsDrug(RelationshipModel):
    __source__ = ClinicalTrial
    __target__ = Drug
    __rel_type__ = "TESTS"


class TrialForDisease(RelationshipModel):
    __source__ = ClinicalTrial
    __target__ = Disease
    __rel_type__ = "TRIAL_FOR"


class FundedBy(RelationshipModel):
    __source__ = Paper
    __target__ = FundingAgency
    __rel_type__ = "FUNDED_BY"
    grant_id: str = ""
    amount_usd: int = 0


class Collaborates(RelationshipModel):
    __source__ = Researcher
    __target__ = Researcher
    __rel_type__ = "COLLABORATES_WITH"
    paper_count: int = 0
    since: int = 0


ALL_MODELS = [
    Researcher, Institution, Paper, Disease, Drug, Gene,
    ClinicalTrial, FundingAgency,
    AuthoredBy, AffiliatedWith, Cites, StudiesDisease,
    TreatsWith, TargetsGene, AssociatedGene,
    TestsDrug, TrialForDisease, FundedBy, Collaborates,
]
