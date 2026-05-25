"""Seed the Neo4j database using cypher_validator ORM.

Demonstrates: GraphSession, BulkOps, NodeModel.create, RelationshipModel,
Query builder, SchemaDDL.apply_ddl, vector_search.
"""

from __future__ import annotations

from cypher_validator.models.session import GraphSession, BulkOps
from cypher_validator.models.schema import GraphSchema, SchemaDDL

from models import (
    Researcher, Institution, Paper, Disease, Drug, Gene,
    ClinicalTrial, FundingAgency,
    AuthoredBy, AffiliatedWith, Cites, StudiesDisease,
    TreatsWith, TargetsGene, AssociatedGene,
    TestsDrug, TrialForDisease, FundedBy, Collaborates,
    ALL_MODELS,
)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

RESEARCHERS = [
    {"name": "Dr. Sarah Chen", "orcid": "0000-0001-1234-5678", "h_index": 45,
     "specialization": "Computational Genomics",
     "bio": "Expert in machine learning approaches to genomic data analysis and precision medicine"},
    {"name": "Prof. James Okafor", "orcid": "0000-0002-2345-6789", "h_index": 62,
     "specialization": "Immuno-Oncology",
     "bio": "Pioneer in CAR-T cell therapy and immune checkpoint inhibitor research"},
    {"name": "Dr. Maria Santos", "orcid": "0000-0003-3456-7890", "h_index": 38,
     "specialization": "Neurodegenerative Diseases",
     "bio": "Focused on tau protein aggregation and novel biomarkers for early Alzheimer detection"},
    {"name": "Prof. Kenji Tanaka", "orcid": "0000-0004-4567-8901", "h_index": 55,
     "specialization": "Drug Discovery",
     "bio": "Computational chemistry and AI-driven drug design for kinase inhibitors"},
    {"name": "Dr. Elena Petrova", "orcid": "0000-0005-5678-9012", "h_index": 41,
     "specialization": "Epigenetics",
     "bio": "Studies DNA methylation patterns in cancer progression and therapeutic resistance"},
    {"name": "Prof. Ahmed Hassan", "orcid": "0000-0006-6789-0123", "h_index": 50,
     "specialization": "Clinical Pharmacology",
     "bio": "Pharmacokinetics modeling and drug-drug interaction prediction using graph neural networks"},
    {"name": "Dr. Lisa Park", "orcid": "0000-0007-7890-1234", "h_index": 33,
     "specialization": "Bioinformatics",
     "bio": "Single-cell RNA sequencing analysis and spatial transcriptomics"},
    {"name": "Prof. David Müller", "orcid": "0000-0008-8901-2345", "h_index": 58,
     "specialization": "Structural Biology",
     "bio": "Cryo-EM structural determination of membrane protein complexes and drug targets"},
    {"name": "Dr. Fatima Al-Rashid", "orcid": "0000-0009-9012-3456", "h_index": 36,
     "specialization": "Cancer Immunology",
     "bio": "Tumor microenvironment profiling and neoantigen vaccine development for solid tumors"},
    {"name": "Prof. Wei Zhang", "orcid": "0000-0010-0123-4567", "h_index": 67,
     "specialization": "Genomic Medicine",
     "bio": "Large-scale GWAS meta-analyses and polygenic risk score development for complex diseases"},
    {"name": "Dr. Catherine Dubois", "orcid": "0000-0011-1234-5678", "h_index": 44,
     "specialization": "Neuropharmacology",
     "bio": "Blood-brain barrier drug delivery and neuroprotective compound screening"},
    {"name": "Prof. Roberto Garcia", "orcid": "0000-0012-2345-6789", "h_index": 52,
     "specialization": "Systems Biology",
     "bio": "Multi-omics data integration and metabolic network modeling in cancer"},
    {"name": "Dr. Yuki Nakamura", "orcid": "0000-0013-3456-7890", "h_index": 39,
     "specialization": "RNA Biology",
     "bio": "mRNA therapeutics and non-coding RNA regulatory networks in disease"},
    {"name": "Prof. Ingrid Svensson", "orcid": "0000-0014-4567-8901", "h_index": 61,
     "specialization": "Clinical Trials",
     "bio": "Adaptive trial design and real-world evidence in oncology drug development"},
    {"name": "Dr. Michael Thompson", "orcid": "0000-0015-5678-9012", "h_index": 47,
     "specialization": "Proteomics",
     "bio": "Mass spectrometry-based proteomics and phosphoproteomics in signaling pathways"},
    {"name": "Prof. Aisha Patel", "orcid": "0000-0016-6789-0123", "h_index": 53,
     "specialization": "Genetic Epidemiology",
     "bio": "Mendelian randomization studies linking metabolic biomarkers to cardiovascular outcomes"},
]

INSTITUTIONS = [
    {"name": "MIT", "country": "USA", "type": "university"},
    {"name": "Stanford University", "country": "USA", "type": "university"},
    {"name": "University of Oxford", "country": "UK", "type": "university"},
    {"name": "Max Planck Institute", "country": "Germany", "type": "research"},
    {"name": "RIKEN", "country": "Japan", "type": "research"},
    {"name": "Institut Pasteur", "country": "France", "type": "research"},
    {"name": "Memorial Sloan Kettering", "country": "USA", "type": "hospital"},
    {"name": "Novartis", "country": "Switzerland", "type": "pharma"},
    {"name": "MD Anderson Cancer Center", "country": "USA", "type": "hospital"},
    {"name": "Karolinska Institutet", "country": "Sweden", "type": "university"},
    {"name": "Broad Institute", "country": "USA", "type": "research"},
    {"name": "Beijing Genomics Institute", "country": "China", "type": "research"},
    {"name": "University of Tokyo", "country": "Japan", "type": "university"},
    {"name": "Cambridge University", "country": "UK", "type": "university"},
]

DISEASES = [
    {"name": "Non-Small Cell Lung Cancer", "icd_code": "C34.9", "category": "Oncology",
     "description": "Most common type of lung cancer, driven by mutations in EGFR, ALK, KRAS pathways"},
    {"name": "Alzheimer's Disease", "icd_code": "G30", "category": "Neurology",
     "description": "Progressive neurodegenerative disorder characterized by amyloid plaques and tau tangles"},
    {"name": "Triple-Negative Breast Cancer", "icd_code": "C50", "category": "Oncology",
     "description": "Aggressive breast cancer lacking ER, PR, and HER2 expression with limited targeted therapy options"},
    {"name": "Acute Myeloid Leukemia", "icd_code": "C92.0", "category": "Hematology",
     "description": "Rapidly progressing blood cancer with FLT3 and IDH mutations as key therapeutic targets"},
    {"name": "Parkinson's Disease", "icd_code": "G20", "category": "Neurology",
     "description": "Movement disorder caused by dopaminergic neuron loss in the substantia nigra"},
    {"name": "Rheumatoid Arthritis", "icd_code": "M06.9", "category": "Immunology",
     "description": "Chronic autoimmune disease targeting synovial joints via TNF-alpha and IL-6 pathways"},
    {"name": "Glioblastoma Multiforme", "icd_code": "C71", "category": "Neuro-Oncology",
     "description": "Most aggressive primary brain tumor with poor prognosis and MGMT methylation as key biomarker"},
    {"name": "Type 2 Diabetes", "icd_code": "E11", "category": "Endocrinology",
     "description": "Metabolic disorder of insulin resistance involving GLP-1 and SGLT2 pathways"},
    {"name": "Pancreatic Ductal Adenocarcinoma", "icd_code": "C25.9", "category": "Oncology",
     "description": "Highly lethal cancer with KRAS G12D mutation in 90% of cases and dense desmoplastic stroma"},
    {"name": "Multiple Myeloma", "icd_code": "C90.0", "category": "Hematology",
     "description": "Plasma cell neoplasm with bone marrow infiltration responsive to proteasome inhibitors and immunomodulatory drugs"},
    {"name": "Chronic Lymphocytic Leukemia", "icd_code": "C91.1", "category": "Hematology",
     "description": "Indolent B-cell malignancy driven by BCL2 overexpression and BTK signaling"},
    {"name": "Hepatocellular Carcinoma", "icd_code": "C22.0", "category": "Oncology",
     "description": "Primary liver cancer associated with chronic hepatitis B/C and cirrhosis with emerging immunotherapy benefit"},
    {"name": "Systemic Lupus Erythematosus", "icd_code": "M32", "category": "Immunology",
     "description": "Complex autoimmune disease involving multiple organ systems with anti-dsDNA antibodies and complement activation"},
    {"name": "Amyotrophic Lateral Sclerosis", "icd_code": "G12.21", "category": "Neurology",
     "description": "Progressive motor neuron disease with SOD1 and C9orf72 mutations as genetic drivers"},
]

GENES = [
    {"symbol": "EGFR", "full_name": "Epidermal Growth Factor Receptor", "chromosome": "7p11.2", "pathway": "RTK/RAS/MAPK"},
    {"symbol": "TP53", "full_name": "Tumor Protein P53", "chromosome": "17p13.1", "pathway": "Cell Cycle/Apoptosis"},
    {"symbol": "BRCA1", "full_name": "BRCA1 DNA Repair Associated", "chromosome": "17q21.31", "pathway": "DNA Repair"},
    {"symbol": "KRAS", "full_name": "KRAS Proto-Oncogene", "chromosome": "12p12.1", "pathway": "RAS/MAPK"},
    {"symbol": "FLT3", "full_name": "Fms Related Receptor Tyrosine Kinase 3", "chromosome": "13q12.2", "pathway": "RTK/PI3K"},
    {"symbol": "APP", "full_name": "Amyloid Beta Precursor Protein", "chromosome": "21q21.3", "pathway": "Amyloid Processing"},
    {"symbol": "MAPT", "full_name": "Microtubule Associated Protein Tau", "chromosome": "17q21.31", "pathway": "Tau/Microtubule"},
    {"symbol": "LRRK2", "full_name": "Leucine Rich Repeat Kinase 2", "chromosome": "12q12", "pathway": "Autophagy/Lysosome"},
    {"symbol": "IDH1", "full_name": "Isocitrate Dehydrogenase 1", "chromosome": "2q34", "pathway": "Metabolic/Epigenetic"},
    {"symbol": "MGMT", "full_name": "O-6-Methylguanine-DNA Methyltransferase", "chromosome": "10q26.3", "pathway": "DNA Repair"},
    {"symbol": "TNF", "full_name": "Tumor Necrosis Factor", "chromosome": "6p21.33", "pathway": "NF-kB/Inflammation"},
    {"symbol": "GLP1R", "full_name": "Glucagon Like Peptide 1 Receptor", "chromosome": "6p21.2", "pathway": "Incretin/Insulin"},
    {"symbol": "ALK", "full_name": "Anaplastic Lymphoma Kinase", "chromosome": "2p23.2", "pathway": "RTK/RAS/MAPK"},
    {"symbol": "BCL2", "full_name": "BCL2 Apoptosis Regulator", "chromosome": "18q21.33", "pathway": "Apoptosis"},
    {"symbol": "BTK", "full_name": "Bruton Tyrosine Kinase", "chromosome": "Xq22.1", "pathway": "B-cell Receptor"},
    {"symbol": "SOD1", "full_name": "Superoxide Dismutase 1", "chromosome": "21q22.11", "pathway": "Oxidative Stress"},
    {"symbol": "C9orf72", "full_name": "C9orf72-SMCR8 Complex Subunit", "chromosome": "9p21.2", "pathway": "Autophagy"},
    {"symbol": "PIK3CA", "full_name": "PI3K Catalytic Subunit Alpha", "chromosome": "3q26.32", "pathway": "PI3K/AKT/mTOR"},
    {"symbol": "BRAF", "full_name": "B-Raf Proto-Oncogene", "chromosome": "7q34", "pathway": "RAS/MAPK"},
    {"symbol": "MET", "full_name": "MET Proto-Oncogene", "chromosome": "7q31.2", "pathway": "RTK/HGF"},
]

DRUGS = [
    {"name": "Osimertinib", "drugbank_id": "DB09330", "phase": "approved", "mechanism": "Third-gen EGFR-TKI selective for T790M mutation"},
    {"name": "Pembrolizumab", "drugbank_id": "DB09037", "phase": "approved", "mechanism": "Anti-PD-1 monoclonal antibody immune checkpoint inhibitor"},
    {"name": "Olaparib", "drugbank_id": "DB09074", "phase": "approved", "mechanism": "PARP inhibitor exploiting synthetic lethality in BRCA-mutant cancers"},
    {"name": "Sotorasib", "drugbank_id": "DB16726", "phase": "approved", "mechanism": "First-in-class covalent KRAS G12C inhibitor"},
    {"name": "Midostaurin", "drugbank_id": "DB06595", "phase": "approved", "mechanism": "Multi-kinase inhibitor targeting FLT3 and PKC"},
    {"name": "Lecanemab", "drugbank_id": "DB16649", "phase": "approved", "mechanism": "Anti-amyloid-beta protofibril monoclonal antibody"},
    {"name": "Temozolomide", "drugbank_id": "DB00853", "phase": "approved", "mechanism": "Alkylating agent crossing blood-brain barrier, efficacy depends on MGMT methylation"},
    {"name": "Adalimumab", "drugbank_id": "DB00051", "phase": "approved", "mechanism": "Anti-TNF-alpha monoclonal antibody for autoimmune diseases"},
    {"name": "Semaglutide", "drugbank_id": "DB13928", "phase": "approved", "mechanism": "GLP-1 receptor agonist for glucose control and weight management"},
    {"name": "Vorasidenib", "drugbank_id": "DB16851", "phase": "approved", "mechanism": "Dual IDH1/IDH2 inhibitor for low-grade glioma"},
    {"name": "Venetoclax", "drugbank_id": "DB11581", "phase": "approved", "mechanism": "Selective BCL2 inhibitor restoring apoptosis in CLL and AML"},
    {"name": "Ibrutinib", "drugbank_id": "DB09053", "phase": "approved", "mechanism": "Irreversible BTK inhibitor for B-cell malignancies"},
    {"name": "Alectinib", "drugbank_id": "DB11363", "phase": "approved", "mechanism": "Second-gen ALK inhibitor with CNS penetration for ALK+ NSCLC"},
    {"name": "Atezolizumab", "drugbank_id": "DB11595", "phase": "approved", "mechanism": "Anti-PD-L1 monoclonal antibody for multiple solid tumors"},
    {"name": "Tofersen", "drugbank_id": "DB16901", "phase": "approved", "mechanism": "Antisense oligonucleotide targeting SOD1 mRNA for ALS"},
    {"name": "Belimumab", "drugbank_id": "DB08879", "phase": "approved", "mechanism": "Anti-BAFF monoclonal antibody for systemic lupus erythematosus"},
    {"name": "Sorafenib", "drugbank_id": "DB00398", "phase": "approved", "mechanism": "Multi-kinase inhibitor targeting VEGFR, PDGFR, and RAF for HCC"},
    {"name": "Savolitinib", "drugbank_id": "DB15889", "phase": "phase3", "mechanism": "Selective MET inhibitor for MET-amplified or MET exon 14 skipping NSCLC"},
]

PAPERS = [
    {"title": "EGFR-mutant NSCLC: third-generation TKI resistance mechanisms and combination strategies",
     "doi": "10.1038/s41568-023-00612-x", "year": 2023, "journal": "Nature Reviews Cancer",
     "citation_count": 342, "abstract": "Review of resistance mechanisms to osimertinib in EGFR-mutant non-small cell lung cancer including MET amplification C797S mutation and histological transformation with emerging combination therapy approaches"},
    {"title": "Single-cell atlas of the tumor immune microenvironment in NSCLC",
     "doi": "10.1016/j.cell.2023.05.012", "year": 2023, "journal": "Cell",
     "citation_count": 187, "abstract": "Comprehensive single-cell RNA sequencing of 500000 cells from 85 NSCLC patients revealing distinct immune cell states associated with immunotherapy response and resistance"},
    {"title": "KRAS G12C inhibitors: clinical outcomes and acquired resistance patterns",
     "doi": "10.1056/NEJMoa2302810", "year": 2024, "journal": "NEJM",
     "citation_count": 256, "abstract": "Phase III trial results of sotorasib versus docetaxel in previously treated KRAS G12C mutant NSCLC with analysis of on-target and bypass resistance mechanisms"},
    {"title": "Tau propagation in Alzheimer's: prion-like seeding across neural circuits",
     "doi": "10.1126/science.abm1234", "year": 2023, "journal": "Science",
     "citation_count": 198, "abstract": "Evidence for cell-to-cell transmission of pathological tau aggregates along anatomically connected brain regions with implications for therapeutic antibody targeting"},
    {"title": "Lecanemab phase III: amyloid clearance and clinical decline in early Alzheimer's",
     "doi": "10.1056/NEJMoa2301367", "year": 2023, "journal": "NEJM",
     "citation_count": 891, "abstract": "CLARITY AD trial showing 27% slowing of cognitive decline with lecanemab anti-amyloid antibody therapy in early Alzheimer's disease over 18 months with amyloid-related imaging abnormalities as key safety signal"},
    {"title": "Synthetic lethality beyond BRCA: expanding PARP inhibitor indications",
     "doi": "10.1038/s41571-024-00891-x", "year": 2024, "journal": "Nature Reviews Clinical Oncology",
     "citation_count": 145, "abstract": "Comprehensive review of homologous recombination deficiency biomarkers and PARP inhibitor combinations in ovarian breast pancreatic and prostate cancers beyond canonical BRCA1/2 mutations"},
    {"title": "FLT3 inhibitor combinations in newly diagnosed AML: a network meta-analysis",
     "doi": "10.1182/blood.2023-021456", "year": 2024, "journal": "Blood",
     "citation_count": 89, "abstract": "Systematic comparison of midostaurin gilteritinib and quizartinib combinations with intensive chemotherapy in FLT3-mutated acute myeloid leukemia from 15 randomized trials"},
    {"title": "Graph neural networks for drug-drug interaction prediction at scale",
     "doi": "10.1038/s42256-024-00812-y", "year": 2024, "journal": "Nature Machine Intelligence",
     "citation_count": 167, "abstract": "Novel graph attention network architecture trained on 2 million known DDIs achieving 94% AUROC on prospective validation with interpretable attention-based mechanism explanations"},
    {"title": "Cryo-EM structure of the GLP-1 receptor-Gs complex reveals biased agonism",
     "doi": "10.1038/s41586-024-07123-z", "year": 2024, "journal": "Nature",
     "citation_count": 234, "abstract": "High-resolution cryo-EM structures of GLP-1R bound to semaglutide and tirzepatide revealing differential G-protein and beta-arrestin coupling mechanisms underlying biased signaling"},
    {"title": "Temozolomide resistance in glioblastoma: MGMT-independent mechanisms and novel combinations",
     "doi": "10.1093/neuonc/noad123", "year": 2023, "journal": "Neuro-Oncology",
     "citation_count": 112, "abstract": "Identification of base excision repair and mismatch repair defects as MGMT-independent resistance drivers in recurrent glioblastoma with rationale for ATR and PARP inhibitor combinations"},
    {"title": "Spatial transcriptomics reveals TNF-driven inflammatory niches in rheumatoid synovium",
     "doi": "10.1038/s41591-024-02834-y", "year": 2024, "journal": "Nature Medicine",
     "citation_count": 78, "abstract": "Spatial multi-omics analysis of synovial biopsies from 120 RA patients identifying TNF-alpha driven inflammatory microenvironments predicting adalimumab response"},
    {"title": "AI-driven de novo drug design targeting IDH1-mutant gliomas",
     "doi": "10.1126/scitranslmed.abc9876", "year": 2024, "journal": "Science Translational Medicine",
     "citation_count": 95, "abstract": "Generative AI model designing novel IDH1 inhibitors with improved brain penetration validated through in vivo orthotopic glioma models showing 60% tumor reduction"},
    {"title": "Venetoclax plus azacitidine versus intensive chemotherapy in older AML patients",
     "doi": "10.1056/NEJMoa2310523", "year": 2024, "journal": "NEJM",
     "citation_count": 312, "abstract": "Randomized phase III trial demonstrating superior overall survival with venetoclax-azacitidine in newly diagnosed AML patients over 75 years compared to intensive chemotherapy with lower treatment-related mortality"},
    {"title": "Polygenic risk scores predict 10-year cardiovascular events in diverse populations",
     "doi": "10.1038/s41588-024-01692-x", "year": 2024, "journal": "Nature Genetics",
     "citation_count": 178, "abstract": "Multi-ancestry GWAS meta-analysis of 1.2 million individuals developing transferable polygenic risk scores for coronary artery disease validated across 5 biobanks"},
    {"title": "MET amplification as osimertinib resistance mechanism: savolitinib combination results",
     "doi": "10.1016/j.annonc.2024.01.012", "year": 2024, "journal": "Annals of Oncology",
     "citation_count": 134, "abstract": "Phase II trial of osimertinib plus savolitinib in EGFR-mutant NSCLC with acquired MET amplification showing 52% objective response rate and 9.1 month PFS"},
    {"title": "Tofersen slows motor neuron loss in SOD1-ALS: 52-week open-label extension",
     "doi": "10.1056/NEJMoa2402620", "year": 2024, "journal": "NEJM",
     "citation_count": 205, "abstract": "Open-label extension showing tofersen reduces SOD1 protein and neurofilament light chain with slowed functional decline in SOD1-ALS patients over 12 months"},
    {"title": "Tumor mutational burden and neoantigen vaccine response in solid tumors",
     "doi": "10.1038/s41586-024-07234-z", "year": 2024, "journal": "Nature",
     "citation_count": 156, "abstract": "Pan-cancer analysis of 5000 patients showing tumor mutational burden above 10 mut/Mb predicts neoantigen vaccine response with T-cell expansion correlating with clinical benefit"},
    {"title": "BTK degraders overcome ibrutinib resistance in CLL: first-in-human results",
     "doi": "10.1182/blood.2024-025678", "year": 2024, "journal": "Blood",
     "citation_count": 67, "abstract": "First clinical results of proteolysis-targeting chimera BTK degrader in ibrutinib-resistant CLL showing durable responses regardless of C481S mutation status"},
    {"title": "Multi-omics integration reveals metabolic vulnerabilities in pancreatic cancer",
     "doi": "10.1016/j.cell.2024.03.045", "year": 2024, "journal": "Cell",
     "citation_count": 143, "abstract": "Integrated transcriptomic proteomic and metabolomic profiling of 200 pancreatic tumors identifying cholesterol biosynthesis dependency exploitable by statin combinations"},
    {"title": "Belimumab plus rituximab for severe lupus nephritis: BLISS-BELIEVE trial",
     "doi": "10.1016/S0140-6736(24)00543-7", "year": 2024, "journal": "Lancet",
     "citation_count": 98, "abstract": "Phase III trial showing dual B-cell targeting with belimumab plus rituximab achieves complete renal response in 60% of lupus nephritis patients versus 35% with standard care"},
    {"title": "Atezolizumab plus bevacizumab in unresectable hepatocellular carcinoma: 3-year update",
     "doi": "10.1200/JCO.2024.42.567", "year": 2024, "journal": "Journal of Clinical Oncology",
     "citation_count": 189, "abstract": "Three-year follow-up of IMbrave150 confirming durable survival benefit of atezolizumab-bevacizumab versus sorafenib in first-line HCC with 30% 3-year OS rate"},
    {"title": "CRISPR base editing of PCSK9 for durable cholesterol reduction: phase I results",
     "doi": "10.1038/s41586-024-08012-x", "year": 2024, "journal": "Nature",
     "citation_count": 423, "abstract": "First-in-human in vivo base editing trial showing single-dose liver-targeted PCSK9 disruption achieving 55% LDL reduction sustained at 6 months without off-target edits"},
    {"title": "Alpha-synuclein seed amplification assay for early Parkinson's diagnosis",
     "doi": "10.1016/S1474-4422(24)00289-1", "year": 2024, "journal": "Lancet Neurology",
     "citation_count": 267, "abstract": "Validation of CSF alpha-synuclein seed amplification assay in 2000 participants showing 96% sensitivity and 98% specificity for prodromal Parkinson's disease enabling earlier intervention"},
    {"title": "Bispecific T-cell engagers for relapsed multiple myeloma: teclistamab 2-year data",
     "doi": "10.1182/blood.2024-026789", "year": 2024, "journal": "Blood",
     "citation_count": 124, "abstract": "Two-year follow-up of teclistamab showing deepening responses over time in relapsed multiple myeloma with 68% overall response rate and manageable cytokine release syndrome"},
]

TRIALS = [
    {"trial_id": "NCT05609578", "title": "Osimertinib + savolitinib in EGFR-mutant MET-amplified NSCLC",
     "phase": "Phase 3", "status": "recruiting", "enrollment": 450, "start_year": 2023},
    {"trial_id": "NCT05252390", "title": "Sotorasib + pembrolizumab in KRAS G12C NSCLC",
     "phase": "Phase 2", "status": "active", "enrollment": 200, "start_year": 2022},
    {"trial_id": "NCT04437420", "title": "Lecanemab subcutaneous in early Alzheimer's",
     "phase": "Phase 3", "status": "recruiting", "enrollment": 1566, "start_year": 2023},
    {"trial_id": "NCT05684731", "title": "Midostaurin + venetoclax in FLT3+ AML",
     "phase": "Phase 2", "status": "active", "enrollment": 180, "start_year": 2023},
    {"trial_id": "NCT05838768", "title": "Vorasidenib in recurrent IDH-mutant glioma",
     "phase": "Phase 3", "status": "completed", "enrollment": 331, "start_year": 2022},
    {"trial_id": "NCT05624281", "title": "Venetoclax + azacitidine maintenance in AML remission",
     "phase": "Phase 3", "status": "recruiting", "enrollment": 800, "start_year": 2023},
    {"trial_id": "NCT06012345", "title": "Tofersen early initiation in presymptomatic SOD1 carriers",
     "phase": "Phase 3", "status": "recruiting", "enrollment": 150, "start_year": 2024},
    {"trial_id": "NCT05789012", "title": "Neoantigen vaccine + pembrolizumab in TMB-high solid tumors",
     "phase": "Phase 2", "status": "active", "enrollment": 300, "start_year": 2023},
    {"trial_id": "NCT05901234", "title": "BTK degrader NX-2127 in ibrutinib-resistant CLL",
     "phase": "Phase 1/2", "status": "recruiting", "enrollment": 120, "start_year": 2024},
    {"trial_id": "NCT06123456", "title": "CRISPR PCSK9 editing for familial hypercholesterolemia",
     "phase": "Phase 1", "status": "active", "enrollment": 40, "start_year": 2024},
    {"trial_id": "NCT05456789", "title": "Atezolizumab + bevacizumab adjuvant in resected HCC",
     "phase": "Phase 3", "status": "recruiting", "enrollment": 650, "start_year": 2023},
    {"trial_id": "NCT05567890", "title": "Teclistamab + daratumumab in newly diagnosed myeloma",
     "phase": "Phase 2", "status": "recruiting", "enrollment": 250, "start_year": 2024},
]

FUNDERS = [
    {"name": "NIH/NCI", "country": "USA", "type": "government"},
    {"name": "ERC", "country": "EU", "type": "government"},
    {"name": "Wellcome Trust", "country": "UK", "type": "foundation"},
    {"name": "Bill & Melinda Gates Foundation", "country": "USA", "type": "foundation"},
    {"name": "DARPA", "country": "USA", "type": "government"},
    {"name": "Howard Hughes Medical Institute", "country": "USA", "type": "foundation"},
    {"name": "Cancer Research UK", "country": "UK", "type": "foundation"},
    {"name": "Japan Agency for Medical Research", "country": "Japan", "type": "government"},
]

# Relationship data (src_key, tgt_key, rel_props)
AFFILIATIONS = [
    {"src_name": "Dr. Sarah Chen", "tgt_name": "MIT", "role": "Assistant Professor", "since": 2019},
    {"src_name": "Prof. James Okafor", "tgt_name": "Memorial Sloan Kettering", "role": "Professor", "since": 2012},
    {"src_name": "Dr. Maria Santos", "tgt_name": "University of Oxford", "role": "Senior Researcher", "since": 2016},
    {"src_name": "Prof. Kenji Tanaka", "tgt_name": "RIKEN", "role": "Group Leader", "since": 2014},
    {"src_name": "Dr. Elena Petrova", "tgt_name": "Max Planck Institute", "role": "Postdoctoral Fellow", "since": 2020},
    {"src_name": "Prof. Ahmed Hassan", "tgt_name": "Stanford University", "role": "Associate Professor", "since": 2017},
    {"src_name": "Dr. Lisa Park", "tgt_name": "MIT", "role": "Research Scientist", "since": 2021},
    {"src_name": "Prof. David Müller", "tgt_name": "Max Planck Institute", "role": "Director", "since": 2010},
    {"src_name": "Dr. Fatima Al-Rashid", "tgt_name": "MD Anderson Cancer Center", "role": "Assistant Professor", "since": 2021},
    {"src_name": "Prof. Wei Zhang", "tgt_name": "Broad Institute", "role": "Senior Associate", "since": 2018},
    {"src_name": "Dr. Catherine Dubois", "tgt_name": "Institut Pasteur", "role": "Group Leader", "since": 2019},
    {"src_name": "Prof. Roberto Garcia", "tgt_name": "Stanford University", "role": "Professor", "since": 2015},
    {"src_name": "Dr. Yuki Nakamura", "tgt_name": "University of Tokyo", "role": "Associate Professor", "since": 2020},
    {"src_name": "Prof. Ingrid Svensson", "tgt_name": "Karolinska Institutet", "role": "Professor", "since": 2013},
    {"src_name": "Dr. Michael Thompson", "tgt_name": "Broad Institute", "role": "Research Scientist", "since": 2020},
    {"src_name": "Prof. Aisha Patel", "tgt_name": "Cambridge University", "role": "Professor", "since": 2016},
]

DISEASE_DRUGS = [
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_name": "Osimertinib", "efficacy": "high"},
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_name": "Pembrolizumab", "efficacy": "moderate"},
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_name": "Sotorasib", "efficacy": "moderate"},
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_name": "Alectinib", "efficacy": "high"},
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_name": "Atezolizumab", "efficacy": "moderate"},
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_name": "Savolitinib", "efficacy": "moderate"},
    {"src_name": "Alzheimer's Disease", "tgt_name": "Lecanemab", "efficacy": "moderate"},
    {"src_name": "Triple-Negative Breast Cancer", "tgt_name": "Olaparib", "efficacy": "moderate"},
    {"src_name": "Triple-Negative Breast Cancer", "tgt_name": "Pembrolizumab", "efficacy": "moderate"},
    {"src_name": "Acute Myeloid Leukemia", "tgt_name": "Midostaurin", "efficacy": "high"},
    {"src_name": "Acute Myeloid Leukemia", "tgt_name": "Venetoclax", "efficacy": "high"},
    {"src_name": "Glioblastoma Multiforme", "tgt_name": "Temozolomide", "efficacy": "moderate"},
    {"src_name": "Glioblastoma Multiforme", "tgt_name": "Vorasidenib", "efficacy": "moderate"},
    {"src_name": "Rheumatoid Arthritis", "tgt_name": "Adalimumab", "efficacy": "high"},
    {"src_name": "Type 2 Diabetes", "tgt_name": "Semaglutide", "efficacy": "high"},
    {"src_name": "Parkinson's Disease", "tgt_name": "Lecanemab", "efficacy": "low"},
    {"src_name": "Chronic Lymphocytic Leukemia", "tgt_name": "Ibrutinib", "efficacy": "high"},
    {"src_name": "Chronic Lymphocytic Leukemia", "tgt_name": "Venetoclax", "efficacy": "high"},
    {"src_name": "Hepatocellular Carcinoma", "tgt_name": "Sorafenib", "efficacy": "moderate"},
    {"src_name": "Hepatocellular Carcinoma", "tgt_name": "Atezolizumab", "efficacy": "moderate"},
    {"src_name": "Multiple Myeloma", "tgt_name": "Venetoclax", "efficacy": "moderate"},
    {"src_name": "Systemic Lupus Erythematosus", "tgt_name": "Belimumab", "efficacy": "moderate"},
    {"src_name": "Amyotrophic Lateral Sclerosis", "tgt_name": "Tofersen", "efficacy": "moderate"},
    {"src_name": "Pancreatic Ductal Adenocarcinoma", "tgt_name": "Pembrolizumab", "efficacy": "low"},
]

DRUG_GENES = [
    {"src_name": "Osimertinib", "tgt_symbol": "EGFR", "action": "inhibitor"},
    {"src_name": "Sotorasib", "tgt_symbol": "KRAS", "action": "inhibitor"},
    {"src_name": "Olaparib", "tgt_symbol": "BRCA1", "action": "inhibitor"},
    {"src_name": "Midostaurin", "tgt_symbol": "FLT3", "action": "inhibitor"},
    {"src_name": "Lecanemab", "tgt_symbol": "APP", "action": "modulator"},
    {"src_name": "Temozolomide", "tgt_symbol": "MGMT", "action": "modulator"},
    {"src_name": "Adalimumab", "tgt_symbol": "TNF", "action": "antagonist"},
    {"src_name": "Semaglutide", "tgt_symbol": "GLP1R", "action": "agonist"},
    {"src_name": "Vorasidenib", "tgt_symbol": "IDH1", "action": "inhibitor"},
    {"src_name": "Pembrolizumab", "tgt_symbol": "TP53", "action": "modulator"},
    {"src_name": "Venetoclax", "tgt_symbol": "BCL2", "action": "inhibitor"},
    {"src_name": "Ibrutinib", "tgt_symbol": "BTK", "action": "inhibitor"},
    {"src_name": "Alectinib", "tgt_symbol": "ALK", "action": "inhibitor"},
    {"src_name": "Atezolizumab", "tgt_symbol": "TP53", "action": "modulator"},
    {"src_name": "Tofersen", "tgt_symbol": "SOD1", "action": "inhibitor"},
    {"src_name": "Sorafenib", "tgt_symbol": "BRAF", "action": "inhibitor"},
    {"src_name": "Savolitinib", "tgt_symbol": "MET", "action": "inhibitor"},
    {"src_name": "Belimumab", "tgt_symbol": "TNF", "action": "modulator"},
]

DISEASE_GENES = [
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_symbol": "EGFR", "evidence_level": "strong"},
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_symbol": "KRAS", "evidence_level": "strong"},
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_symbol": "TP53", "evidence_level": "strong"},
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_symbol": "ALK", "evidence_level": "strong"},
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_symbol": "MET", "evidence_level": "moderate"},
    {"src_name": "Non-Small Cell Lung Cancer", "tgt_symbol": "BRAF", "evidence_level": "moderate"},
    {"src_name": "Alzheimer's Disease", "tgt_symbol": "APP", "evidence_level": "strong"},
    {"src_name": "Alzheimer's Disease", "tgt_symbol": "MAPT", "evidence_level": "strong"},
    {"src_name": "Triple-Negative Breast Cancer", "tgt_symbol": "BRCA1", "evidence_level": "strong"},
    {"src_name": "Triple-Negative Breast Cancer", "tgt_symbol": "TP53", "evidence_level": "strong"},
    {"src_name": "Triple-Negative Breast Cancer", "tgt_symbol": "PIK3CA", "evidence_level": "moderate"},
    {"src_name": "Acute Myeloid Leukemia", "tgt_symbol": "FLT3", "evidence_level": "strong"},
    {"src_name": "Acute Myeloid Leukemia", "tgt_symbol": "IDH1", "evidence_level": "strong"},
    {"src_name": "Acute Myeloid Leukemia", "tgt_symbol": "TP53", "evidence_level": "moderate"},
    {"src_name": "Parkinson's Disease", "tgt_symbol": "LRRK2", "evidence_level": "strong"},
    {"src_name": "Glioblastoma Multiforme", "tgt_symbol": "IDH1", "evidence_level": "moderate"},
    {"src_name": "Glioblastoma Multiforme", "tgt_symbol": "MGMT", "evidence_level": "strong"},
    {"src_name": "Glioblastoma Multiforme", "tgt_symbol": "EGFR", "evidence_level": "moderate"},
    {"src_name": "Rheumatoid Arthritis", "tgt_symbol": "TNF", "evidence_level": "strong"},
    {"src_name": "Type 2 Diabetes", "tgt_symbol": "GLP1R", "evidence_level": "moderate"},
    {"src_name": "Chronic Lymphocytic Leukemia", "tgt_symbol": "BCL2", "evidence_level": "strong"},
    {"src_name": "Chronic Lymphocytic Leukemia", "tgt_symbol": "BTK", "evidence_level": "strong"},
    {"src_name": "Chronic Lymphocytic Leukemia", "tgt_symbol": "TP53", "evidence_level": "moderate"},
    {"src_name": "Hepatocellular Carcinoma", "tgt_symbol": "TP53", "evidence_level": "strong"},
    {"src_name": "Hepatocellular Carcinoma", "tgt_symbol": "BRAF", "evidence_level": "moderate"},
    {"src_name": "Amyotrophic Lateral Sclerosis", "tgt_symbol": "SOD1", "evidence_level": "strong"},
    {"src_name": "Amyotrophic Lateral Sclerosis", "tgt_symbol": "C9orf72", "evidence_level": "strong"},
    {"src_name": "Pancreatic Ductal Adenocarcinoma", "tgt_symbol": "KRAS", "evidence_level": "strong"},
    {"src_name": "Pancreatic Ductal Adenocarcinoma", "tgt_symbol": "TP53", "evidence_level": "strong"},
    {"src_name": "Multiple Myeloma", "tgt_symbol": "BCL2", "evidence_level": "moderate"},
]

COLLABORATIONS = [
    {"src_name": "Dr. Sarah Chen", "tgt_name": "Prof. James Okafor", "paper_count": 4, "since": 2020},
    {"src_name": "Dr. Sarah Chen", "tgt_name": "Prof. Ahmed Hassan", "paper_count": 2, "since": 2023},
    {"src_name": "Dr. Sarah Chen", "tgt_name": "Prof. Kenji Tanaka", "paper_count": 1, "since": 2024},
    {"src_name": "Prof. James Okafor", "tgt_name": "Dr. Elena Petrova", "paper_count": 1, "since": 2023},
    {"src_name": "Prof. James Okafor", "tgt_name": "Dr. Fatima Al-Rashid", "paper_count": 2, "since": 2023},
    {"src_name": "Dr. Lisa Park", "tgt_name": "Prof. David Müller", "paper_count": 1, "since": 2024},
    {"src_name": "Dr. Maria Santos", "tgt_name": "Dr. Elena Petrova", "paper_count": 1, "since": 2023},
    {"src_name": "Dr. Maria Santos", "tgt_name": "Dr. Catherine Dubois", "paper_count": 3, "since": 2022},
    {"src_name": "Prof. Kenji Tanaka", "tgt_name": "Prof. David Müller", "paper_count": 1, "since": 2024},
    {"src_name": "Prof. Ahmed Hassan", "tgt_name": "Prof. Ingrid Svensson", "paper_count": 2, "since": 2023},
    {"src_name": "Prof. Wei Zhang", "tgt_name": "Prof. Aisha Patel", "paper_count": 2, "since": 2022},
    {"src_name": "Prof. Wei Zhang", "tgt_name": "Dr. Yuki Nakamura", "paper_count": 1, "since": 2024},
    {"src_name": "Dr. Fatima Al-Rashid", "tgt_name": "Prof. Ingrid Svensson", "paper_count": 1, "since": 2024},
    {"src_name": "Prof. Roberto Garcia", "tgt_name": "Dr. Michael Thompson", "paper_count": 2, "since": 2022},
    {"src_name": "Dr. Catherine Dubois", "tgt_name": "Dr. Maria Santos", "paper_count": 2, "since": 2022},
]


# ---------------------------------------------------------------------------
# Seed function using ORM
# ---------------------------------------------------------------------------


def seed_database(db, embed_fn=None):
    """Seed using cypher_validator ORM: GraphSession + BulkOps + SchemaDDL.

    Demonstrates:
    - GraphSchema.from_models() — introspect models
    - SchemaDDL.generate_all() — apply constraints/indexes
    - BulkOps.bulk_create_nodes() — efficient UNWIND inserts
    - BulkOps.bulk_create_relationships() — relationship batch creation
    - GraphSession.execute() — raw fallback when needed
    """
    schema = GraphSchema.from_models(ALL_MODELS)
    session = GraphSession(db, schema)

    # 1. Clear existing data
    session.execute("MATCH (n) DETACH DELETE n")

    # 2. Apply schema DDL (constraints + indexes)
    ddl = SchemaDDL(schema)
    for stmt in ddl.generate_all():
        try:
            session.execute(stmt)
        except Exception:
            pass  # indexes may already exist

    # 3. Bulk create nodes
    # Add embeddings if embed_fn provided
    researchers = [{**r} for r in RESEARCHERS]
    papers = [{**p} for p in PAPERS]
    diseases = [{**d} for d in DISEASES]

    if embed_fn:
        for r in researchers:
            r["bio_embedding"] = embed_fn(r["bio"])
        for p in papers:
            p["abstract_embedding"] = embed_fn(p["abstract"])
        for d in diseases:
            d["description_embedding"] = embed_fn(d["description"])
    else:
        for r in researchers:
            r["bio_embedding"] = []
        for p in papers:
            p["abstract_embedding"] = []
        for d in diseases:
            d["description_embedding"] = []

    # BulkOps generates efficient UNWIND Cypher
    cypher, params = BulkOps.bulk_create_nodes(Researcher, researchers)
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_nodes(Institution, INSTITUTIONS)
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_nodes(Disease, diseases)
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_nodes(Gene, GENES)
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_nodes(Drug, DRUGS)
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_nodes(Paper, papers)
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_nodes(ClinicalTrial, TRIALS)
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_nodes(FundingAgency, FUNDERS)
    session.execute(cypher, params)

    # 4. Bulk create relationships using ORM BulkOps
    cypher, params = BulkOps.bulk_create_relationships(
        AffiliatedWith, AFFILIATIONS, src_key="src_name", tgt_key="tgt_name"
    )
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_relationships(
        TreatsWith, DISEASE_DRUGS, src_key="src_name", tgt_key="tgt_name"
    )
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_relationships(
        TargetsGene, DRUG_GENES, src_key="src_name", tgt_key="tgt_symbol"
    )
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_relationships(
        AssociatedGene, DISEASE_GENES, src_key="src_name", tgt_key="tgt_symbol"
    )
    session.execute(cypher, params)

    cypher, params = BulkOps.bulk_create_relationships(
        Collaborates, COLLABORATIONS, src_key="src_name", tgt_key="tgt_name"
    )
    session.execute(cypher, params)

    # Paper relationships use title prefix matching (not simple key match)
    # Use session.execute with parameterized Cypher for these
    _seed_paper_authorships(session)
    _seed_paper_studies(session)
    _seed_paper_citations(session)
    _seed_paper_funding(session)
    _seed_trial_links(session)

    # 5. Summary using ORM Query
    result = session.execute("MATCH (n) RETURN count(n) AS nodes")
    node_count = result[0]["nodes"] if result else 0
    result = session.execute("MATCH ()-[r]->() RETURN count(r) AS rels")
    rel_count = result[0]["rels"] if result else 0
    print(f"Seeded: {node_count} nodes, {rel_count} relationships")
    return node_count, rel_count


def _seed_paper_authorships(session: GraphSession):
    """Paper→Researcher AUTHORED_BY relationships (title prefix matching)."""
    authorships = [
        ("EGFR-mutant NSCLC", "Dr. Sarah Chen", "first"),
        ("EGFR-mutant NSCLC", "Prof. James Okafor", "last"),
        ("Single-cell atlas", "Dr. Lisa Park", "first"),
        ("Single-cell atlas", "Prof. James Okafor", "corresponding"),
        ("KRAS G12C", "Prof. James Okafor", "first"),
        ("KRAS G12C", "Dr. Sarah Chen", "middle"),
        ("Tau propagation", "Dr. Maria Santos", "first"),
        ("Lecanemab phase III", "Dr. Maria Santos", "middle"),
        ("Lecanemab phase III", "Dr. Catherine Dubois", "last"),
        ("Synthetic lethality", "Dr. Elena Petrova", "first"),
        ("Synthetic lethality", "Prof. James Okafor", "last"),
        ("FLT3 inhibitor", "Prof. Ahmed Hassan", "first"),
        ("FLT3 inhibitor", "Prof. Ingrid Svensson", "last"),
        ("Graph neural networks", "Prof. Ahmed Hassan", "first"),
        ("Graph neural networks", "Dr. Sarah Chen", "last"),
        ("Cryo-EM structure", "Prof. David Müller", "first"),
        ("Cryo-EM structure", "Prof. Kenji Tanaka", "corresponding"),
        ("Temozolomide resistance", "Dr. Elena Petrova", "first"),
        ("Temozolomide resistance", "Dr. Maria Santos", "middle"),
        ("Spatial transcriptomics", "Dr. Lisa Park", "first"),
        ("Spatial transcriptomics", "Prof. David Müller", "last"),
        ("AI-driven de novo", "Prof. Kenji Tanaka", "first"),
        ("AI-driven de novo", "Dr. Sarah Chen", "middle"),
        ("Venetoclax plus azacitidine", "Prof. Ingrid Svensson", "first"),
        ("Venetoclax plus azacitidine", "Prof. Ahmed Hassan", "last"),
        ("Polygenic risk scores", "Prof. Wei Zhang", "first"),
        ("Polygenic risk scores", "Prof. Aisha Patel", "last"),
        ("MET amplification", "Dr. Sarah Chen", "first"),
        ("MET amplification", "Prof. James Okafor", "corresponding"),
        ("Tofersen slows", "Dr. Catherine Dubois", "first"),
        ("Tofersen slows", "Dr. Maria Santos", "middle"),
        ("Tumor mutational burden", "Dr. Fatima Al-Rashid", "first"),
        ("Tumor mutational burden", "Prof. James Okafor", "last"),
        ("BTK degraders", "Prof. Ahmed Hassan", "first"),
        ("BTK degraders", "Prof. Ingrid Svensson", "corresponding"),
        ("Multi-omics integration", "Prof. Roberto Garcia", "first"),
        ("Multi-omics integration", "Dr. Michael Thompson", "last"),
        ("Belimumab plus rituximab", "Prof. Ingrid Svensson", "first"),
        ("Atezolizumab plus bevacizumab", "Dr. Fatima Al-Rashid", "first"),
        ("Atezolizumab plus bevacizumab", "Prof. James Okafor", "middle"),
        ("CRISPR base editing", "Prof. Wei Zhang", "first"),
        ("CRISPR base editing", "Dr. Yuki Nakamura", "last"),
        ("Alpha-synuclein seed", "Dr. Maria Santos", "first"),
        ("Alpha-synuclein seed", "Dr. Catherine Dubois", "corresponding"),
        ("Bispecific T-cell", "Prof. Ingrid Svensson", "first"),
        ("Bispecific T-cell", "Dr. Fatima Al-Rashid", "middle"),
    ]
    for prefix, author, position in authorships:
        session.execute(
            "MATCH (p:Paper) WHERE p.title STARTS WITH $prefix "
            "MATCH (r:Researcher {name: $author}) "
            "CREATE (p)-[:AUTHORED_BY {position: $position}]->(r)",
            {"prefix": prefix, "author": author, "position": position},
        )


def _seed_paper_studies(session: GraphSession):
    """Paper→Disease STUDIES relationships."""
    links = [
        ("EGFR-mutant NSCLC", "Non-Small Cell Lung Cancer"),
        ("Single-cell atlas", "Non-Small Cell Lung Cancer"),
        ("KRAS G12C", "Non-Small Cell Lung Cancer"),
        ("Tau propagation", "Alzheimer's Disease"),
        ("Lecanemab phase III", "Alzheimer's Disease"),
        ("Synthetic lethality", "Triple-Negative Breast Cancer"),
        ("FLT3 inhibitor", "Acute Myeloid Leukemia"),
        ("Temozolomide resistance", "Glioblastoma Multiforme"),
        ("Spatial transcriptomics", "Rheumatoid Arthritis"),
        ("AI-driven de novo", "Glioblastoma Multiforme"),
        ("Cryo-EM structure", "Type 2 Diabetes"),
        ("Venetoclax plus azacitidine", "Acute Myeloid Leukemia"),
        ("MET amplification", "Non-Small Cell Lung Cancer"),
        ("Tofersen slows", "Amyotrophic Lateral Sclerosis"),
        ("Tumor mutational burden", "Non-Small Cell Lung Cancer"),
        ("Tumor mutational burden", "Triple-Negative Breast Cancer"),
        ("BTK degraders", "Chronic Lymphocytic Leukemia"),
        ("Multi-omics integration", "Pancreatic Ductal Adenocarcinoma"),
        ("Belimumab plus rituximab", "Systemic Lupus Erythematosus"),
        ("Atezolizumab plus bevacizumab", "Hepatocellular Carcinoma"),
        ("Alpha-synuclein seed", "Parkinson's Disease"),
        ("Bispecific T-cell", "Multiple Myeloma"),
        ("Polygenic risk scores", "Type 2 Diabetes"),
    ]
    for prefix, disease in links:
        session.execute(
            "MATCH (p:Paper) WHERE p.title STARTS WITH $prefix "
            "MATCH (d:Disease {name: $disease}) "
            "CREATE (p)-[:STUDIES]->(d)",
            {"prefix": prefix, "disease": disease},
        )


def _seed_paper_citations(session: GraphSession):
    """Paper→Paper CITES relationships."""
    citations = [
        ("Single-cell atlas", "EGFR-mutant NSCLC", "background"),
        ("KRAS G12C", "EGFR-mutant NSCLC", "methodology"),
        ("Lecanemab phase III", "Tau propagation", "background"),
        ("Temozolomide resistance", "Synthetic lethality", "results"),
        ("AI-driven de novo", "Graph neural networks", "methodology"),
        ("AI-driven de novo", "Temozolomide resistance", "background"),
        ("Spatial transcriptomics", "Single-cell atlas", "methodology"),
        ("MET amplification", "EGFR-mutant NSCLC", "background"),
        ("Venetoclax plus azacitidine", "FLT3 inhibitor", "background"),
        ("Tumor mutational burden", "Single-cell atlas", "methodology"),
        ("BTK degraders", "Venetoclax plus azacitidine", "methodology"),
        ("Multi-omics integration", "Graph neural networks", "methodology"),
        ("Atezolizumab plus bevacizumab", "Tumor mutational burden", "background"),
        ("CRISPR base editing", "Polygenic risk scores", "background"),
        ("Alpha-synuclein seed", "Tau propagation", "methodology"),
        ("Bispecific T-cell", "Venetoclax plus azacitidine", "background"),
        ("Tofersen slows", "Alpha-synuclein seed", "methodology"),
        ("Belimumab plus rituximab", "Spatial transcriptomics", "methodology"),
    ]
    for src, tgt, context in citations:
        session.execute(
            "MATCH (p1:Paper) WHERE p1.title STARTS WITH $src "
            "MATCH (p2:Paper) WHERE p2.title STARTS WITH $tgt "
            "CREATE (p1)-[:CITES {context: $context}]->(p2)",
            {"src": src, "tgt": tgt, "context": context},
        )


def _seed_paper_funding(session: GraphSession):
    """Paper→FundingAgency FUNDED_BY relationships."""
    funding = [
        ("EGFR-mutant NSCLC", "NIH/NCI", "R01-CA234567", 1200000),
        ("Single-cell atlas", "NIH/NCI", "U01-CA289012", 2500000),
        ("KRAS G12C", "NIH/NCI", "R01-CA345678", 950000),
        ("Tau propagation", "Wellcome Trust", "WT-209876", 800000),
        ("Lecanemab phase III", "NIH/NCI", "U19-AG067890", 5000000),
        ("Graph neural networks", "DARPA", "HR001122S0045", 3200000),
        ("Cryo-EM structure", "ERC", "ERC-2023-SyG-951234", 1500000),
        ("Spatial transcriptomics", "Wellcome Trust", "WT-215432", 600000),
        ("AI-driven de novo", "DARPA", "HR001123C0067", 4100000),
        ("Venetoclax plus azacitidine", "Cancer Research UK", "CRUK-A29834", 1800000),
        ("Polygenic risk scores", "NIH/NCI", "R01-HG012345", 1400000),
        ("MET amplification", "NIH/NCI", "P50-CA256789", 2200000),
        ("Tofersen slows", "Howard Hughes Medical Institute", "HHMI-2023-0456", 900000),
        ("Tumor mutational burden", "NIH/NCI", "R01-CA456789", 1600000),
        ("CRISPR base editing", "Howard Hughes Medical Institute", "HHMI-2024-0123", 5500000),
        ("Multi-omics integration", "Cancer Research UK", "CRUK-A31567", 1100000),
        ("Alpha-synuclein seed", "Wellcome Trust", "WT-220987", 750000),
        ("Bispecific T-cell", "ERC", "ERC-2024-CoG-892345", 2000000),
        ("Belimumab plus rituximab", "NIH/NCI", "U01-AR078901", 3000000),
        ("Atezolizumab plus bevacizumab", "Japan Agency for Medical Research", "AMED-2023-GI-045", 1300000),
    ]
    for prefix, funder, grant_id, amount in funding:
        session.execute(
            "MATCH (p:Paper) WHERE p.title STARTS WITH $prefix "
            "MATCH (f:FundingAgency {name: $funder}) "
            "CREATE (p)-[:FUNDED_BY {grant_id: $grant_id, amount_usd: $amount_usd}]->(f)",
            {"prefix": prefix, "funder": funder, "grant_id": grant_id, "amount_usd": amount},
        )


def _seed_trial_links(session: GraphSession):
    """ClinicalTrial→Drug TESTS and ClinicalTrial→Disease TRIAL_FOR."""
    links = [
        ("NCT05609578", "Osimertinib", "Non-Small Cell Lung Cancer"),
        ("NCT05609578", "Savolitinib", "Non-Small Cell Lung Cancer"),
        ("NCT05252390", "Sotorasib", "Non-Small Cell Lung Cancer"),
        ("NCT05252390", "Pembrolizumab", "Non-Small Cell Lung Cancer"),
        ("NCT04437420", "Lecanemab", "Alzheimer's Disease"),
        ("NCT05684731", "Midostaurin", "Acute Myeloid Leukemia"),
        ("NCT05684731", "Venetoclax", "Acute Myeloid Leukemia"),
        ("NCT05838768", "Vorasidenib", "Glioblastoma Multiforme"),
        ("NCT05624281", "Venetoclax", "Acute Myeloid Leukemia"),
        ("NCT06012345", "Tofersen", "Amyotrophic Lateral Sclerosis"),
        ("NCT05789012", "Pembrolizumab", "Non-Small Cell Lung Cancer"),
        ("NCT05901234", "Ibrutinib", "Chronic Lymphocytic Leukemia"),
        ("NCT05456789", "Atezolizumab", "Hepatocellular Carcinoma"),
        ("NCT05567890", "Venetoclax", "Multiple Myeloma"),
    ]
    for tid, drug, disease in links:
        session.execute(
            "MATCH (ct:ClinicalTrial {trial_id: $tid}), (dr:Drug {name: $drug}) "
            "CREATE (ct)-[:TESTS]->(dr)",
            {"tid": tid, "drug": drug},
        )
        session.execute(
            "MATCH (ct:ClinicalTrial {trial_id: $tid}), (d:Disease {name: $disease}) "
            "CREATE (ct)-[:TRIAL_FOR]->(d)",
            {"tid": tid, "disease": disease},
        )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from neo4j import GraphDatabase
    from sentence_transformers import SentenceTransformer

    class Neo4jDB:
        def __init__(self, uri, user, password):
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
        def execute(self, cypher, params=None):
            with self._driver.session() as s:
                return [dict(r) for r in s.run(cypher, params or {})]
        def close(self):
            self._driver.close()

    model = SentenceTransformer("all-MiniLM-L6-v2")
    embed_fn = lambda text: model.encode(text).tolist()

    db = Neo4jDB("bolt://localhost:7687", "neo4j", "testtest12")
    try:
        seed_database(db, embed_fn=embed_fn)
    finally:
        db.close()
