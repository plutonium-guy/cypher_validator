"""Seed the Neo4j database with complex biomedical research data."""

from __future__ import annotations


def seed_database(db, embed_fn=None):
    """Seed with realistic biomedical knowledge graph data."""

    def _exec(cypher, params=None):
        return db.execute(cypher, params or {})

    # Clear existing data
    _exec("MATCH (n) DETACH DELETE n")

    # -----------------------------------------------------------------------
    # Researchers
    # -----------------------------------------------------------------------
    researchers = [
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
    ]

    for r in researchers:
        if embed_fn:
            r["bio_embedding"] = embed_fn(r["bio"])
        _exec(
            "CREATE (r:Researcher {name: $name, orcid: $orcid, h_index: $h_index, "
            "specialization: $specialization, bio: $bio, bio_embedding: $bio_embedding})",
            {**r, "bio_embedding": r.get("bio_embedding", [])},
        )

    # -----------------------------------------------------------------------
    # Institutions
    # -----------------------------------------------------------------------
    institutions = [
        {"name": "MIT", "country": "USA", "type": "university"},
        {"name": "Stanford University", "country": "USA", "type": "university"},
        {"name": "University of Oxford", "country": "UK", "type": "university"},
        {"name": "Max Planck Institute", "country": "Germany", "type": "research"},
        {"name": "RIKEN", "country": "Japan", "type": "research"},
        {"name": "Institut Pasteur", "country": "France", "type": "research"},
        {"name": "Memorial Sloan Kettering", "country": "USA", "type": "hospital"},
        {"name": "Novartis", "country": "Switzerland", "type": "pharma"},
    ]

    for inst in institutions:
        _exec(
            "CREATE (:Institution {name: $name, country: $country, type: $type})",
            inst,
        )

    # -----------------------------------------------------------------------
    # Diseases
    # -----------------------------------------------------------------------
    diseases = [
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
    ]

    for d in diseases:
        if embed_fn:
            d["description_embedding"] = embed_fn(d["description"])
        _exec(
            "CREATE (:Disease {name: $name, icd_code: $icd_code, category: $category, "
            "description: $description, description_embedding: $description_embedding})",
            {**d, "description_embedding": d.get("description_embedding", [])},
        )

    # -----------------------------------------------------------------------
    # Genes
    # -----------------------------------------------------------------------
    genes = [
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
    ]

    for g in genes:
        _exec(
            "CREATE (:Gene {symbol: $symbol, full_name: $full_name, "
            "chromosome: $chromosome, pathway: $pathway})",
            g,
        )

    # -----------------------------------------------------------------------
    # Drugs
    # -----------------------------------------------------------------------
    drugs = [
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
    ]

    for d in drugs:
        _exec(
            "CREATE (:Drug {name: $name, drugbank_id: $drugbank_id, "
            "phase: $phase, mechanism: $mechanism})",
            d,
        )

    # -----------------------------------------------------------------------
    # Papers
    # -----------------------------------------------------------------------
    papers = [
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
        {"title": "Cryo-EM structure of the GLP-1 receptor–Gs complex reveals biased agonism",
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
    ]

    for p in papers:
        if embed_fn:
            p["abstract_embedding"] = embed_fn(p["abstract"])
        _exec(
            "CREATE (:Paper {title: $title, doi: $doi, year: $year, journal: $journal, "
            "citation_count: $citation_count, abstract: $abstract, abstract_embedding: $abstract_embedding})",
            {**p, "abstract_embedding": p.get("abstract_embedding", [])},
        )

    # -----------------------------------------------------------------------
    # Clinical Trials
    # -----------------------------------------------------------------------
    trials = [
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
    ]

    for t in trials:
        _exec(
            "CREATE (:ClinicalTrial {trial_id: $trial_id, title: $title, phase: $phase, "
            "status: $status, enrollment: $enrollment, start_year: $start_year})",
            t,
        )

    # -----------------------------------------------------------------------
    # Funding Agencies
    # -----------------------------------------------------------------------
    funders = [
        {"name": "NIH/NCI", "country": "USA", "type": "government"},
        {"name": "ERC", "country": "EU", "type": "government"},
        {"name": "Wellcome Trust", "country": "UK", "type": "foundation"},
        {"name": "Bill & Melinda Gates Foundation", "country": "USA", "type": "foundation"},
        {"name": "DARPA", "country": "USA", "type": "government"},
    ]

    for f in funders:
        _exec(
            "CREATE (:FundingAgency {name: $name, country: $country, type: $type})",
            f,
        )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------

    # Affiliations
    affiliations = [
        ("Dr. Sarah Chen", "MIT", "Assistant Professor", 2019),
        ("Prof. James Okafor", "Memorial Sloan Kettering", "Professor", 2012),
        ("Dr. Maria Santos", "University of Oxford", "Senior Researcher", 2016),
        ("Prof. Kenji Tanaka", "RIKEN", "Group Leader", 2014),
        ("Dr. Elena Petrova", "Max Planck Institute", "Postdoctoral Fellow", 2020),
        ("Prof. Ahmed Hassan", "Stanford University", "Associate Professor", 2017),
        ("Dr. Lisa Park", "MIT", "Research Scientist", 2021),
        ("Prof. David Müller", "Max Planck Institute", "Director", 2010),
    ]

    for name, inst, role, since in affiliations:
        _exec(
            "MATCH (r:Researcher {name: $name}), (i:Institution {name: $inst}) "
            "CREATE (r)-[:AFFILIATED_WITH {role: $role, since: $since}]->(i)",
            {"name": name, "inst": inst, "role": role, "since": since},
        )

    # Paper authorship
    authorships = [
        ("EGFR-mutant NSCLC%", "Dr. Sarah Chen", "first"),
        ("EGFR-mutant NSCLC%", "Prof. James Okafor", "last"),
        ("Single-cell atlas%", "Dr. Lisa Park", "first"),
        ("Single-cell atlas%", "Prof. James Okafor", "corresponding"),
        ("KRAS G12C%", "Prof. James Okafor", "first"),
        ("KRAS G12C%", "Dr. Sarah Chen", "middle"),
        ("Tau propagation%", "Dr. Maria Santos", "first"),
        ("Lecanemab phase III%", "Dr. Maria Santos", "middle"),
        ("Synthetic lethality%", "Dr. Elena Petrova", "first"),
        ("Synthetic lethality%", "Prof. James Okafor", "last"),
        ("FLT3 inhibitor%", "Prof. Ahmed Hassan", "first"),
        ("Graph neural networks%", "Prof. Ahmed Hassan", "first"),
        ("Graph neural networks%", "Dr. Sarah Chen", "last"),
        ("Cryo-EM structure%", "Prof. David Müller", "first"),
        ("Cryo-EM structure%", "Prof. Kenji Tanaka", "corresponding"),
        ("Temozolomide resistance%", "Dr. Elena Petrova", "first"),
        ("Temozolomide resistance%", "Dr. Maria Santos", "middle"),
        ("Spatial transcriptomics%", "Dr. Lisa Park", "first"),
        ("Spatial transcriptomics%", "Prof. David Müller", "last"),
        ("AI-driven de novo%", "Prof. Kenji Tanaka", "first"),
        ("AI-driven de novo%", "Dr. Sarah Chen", "middle"),
    ]

    for title_pat, author, position in authorships:
        _exec(
            "MATCH (p:Paper) WHERE p.title STARTS WITH $prefix "
            "MATCH (r:Researcher {name: $author}) "
            "CREATE (p)-[:AUTHORED_BY {position: $position}]->(r)",
            {"prefix": title_pat.rstrip("%"), "author": author, "position": position},
        )

    # Paper → Disease
    paper_diseases = [
        ("EGFR-mutant NSCLC%", "Non-Small Cell Lung Cancer"),
        ("Single-cell atlas%", "Non-Small Cell Lung Cancer"),
        ("KRAS G12C%", "Non-Small Cell Lung Cancer"),
        ("Tau propagation%", "Alzheimer's Disease"),
        ("Lecanemab phase III%", "Alzheimer's Disease"),
        ("Synthetic lethality%", "Triple-Negative Breast Cancer"),
        ("FLT3 inhibitor%", "Acute Myeloid Leukemia"),
        ("Temozolomide resistance%", "Glioblastoma Multiforme"),
        ("Spatial transcriptomics%", "Rheumatoid Arthritis"),
        ("AI-driven de novo%", "Glioblastoma Multiforme"),
        ("Cryo-EM structure%", "Type 2 Diabetes"),
    ]

    for title_pat, disease in paper_diseases:
        _exec(
            "MATCH (p:Paper) WHERE p.title STARTS WITH $prefix "
            "MATCH (d:Disease {name: $disease}) "
            "CREATE (p)-[:STUDIES]->(d)",
            {"prefix": title_pat.rstrip("%"), "disease": disease},
        )

    # Disease → Drug (TREATS_WITH)
    disease_drugs = [
        ("Non-Small Cell Lung Cancer", "Osimertinib", "high"),
        ("Non-Small Cell Lung Cancer", "Pembrolizumab", "moderate"),
        ("Non-Small Cell Lung Cancer", "Sotorasib", "moderate"),
        ("Alzheimer's Disease", "Lecanemab", "moderate"),
        ("Triple-Negative Breast Cancer", "Olaparib", "moderate"),
        ("Triple-Negative Breast Cancer", "Pembrolizumab", "moderate"),
        ("Acute Myeloid Leukemia", "Midostaurin", "high"),
        ("Glioblastoma Multiforme", "Temozolomide", "moderate"),
        ("Glioblastoma Multiforme", "Vorasidenib", "moderate"),
        ("Rheumatoid Arthritis", "Adalimumab", "high"),
        ("Type 2 Diabetes", "Semaglutide", "high"),
        ("Parkinson's Disease", "Lecanemab", "low"),
    ]

    for disease, drug, efficacy in disease_drugs:
        _exec(
            "MATCH (d:Disease {name: $disease}), (dr:Drug {name: $drug}) "
            "CREATE (d)-[:TREATS_WITH {efficacy: $efficacy}]->(dr)",
            {"disease": disease, "drug": drug, "efficacy": efficacy},
        )

    # Drug → Gene (TARGETS)
    drug_genes = [
        ("Osimertinib", "EGFR", "inhibitor"),
        ("Sotorasib", "KRAS", "inhibitor"),
        ("Olaparib", "BRCA1", "inhibitor"),
        ("Midostaurin", "FLT3", "inhibitor"),
        ("Lecanemab", "APP", "modulator"),
        ("Temozolomide", "MGMT", "modulator"),
        ("Adalimumab", "TNF", "antagonist"),
        ("Semaglutide", "GLP1R", "agonist"),
        ("Vorasidenib", "IDH1", "inhibitor"),
        ("Pembrolizumab", "TP53", "modulator"),
    ]

    for drug, gene, action in drug_genes:
        _exec(
            "MATCH (dr:Drug {name: $drug}), (g:Gene {symbol: $gene}) "
            "CREATE (dr)-[:TARGETS {action: $action}]->(g)",
            {"drug": drug, "gene": gene, "action": action},
        )

    # Disease → Gene (ASSOCIATED_WITH)
    disease_genes = [
        ("Non-Small Cell Lung Cancer", "EGFR", "strong"),
        ("Non-Small Cell Lung Cancer", "KRAS", "strong"),
        ("Non-Small Cell Lung Cancer", "TP53", "strong"),
        ("Alzheimer's Disease", "APP", "strong"),
        ("Alzheimer's Disease", "MAPT", "strong"),
        ("Triple-Negative Breast Cancer", "BRCA1", "strong"),
        ("Triple-Negative Breast Cancer", "TP53", "strong"),
        ("Acute Myeloid Leukemia", "FLT3", "strong"),
        ("Parkinson's Disease", "LRRK2", "strong"),
        ("Glioblastoma Multiforme", "IDH1", "moderate"),
        ("Glioblastoma Multiforme", "MGMT", "strong"),
        ("Rheumatoid Arthritis", "TNF", "strong"),
        ("Type 2 Diabetes", "GLP1R", "moderate"),
    ]

    for disease, gene, evidence in disease_genes:
        _exec(
            "MATCH (d:Disease {name: $disease}), (g:Gene {symbol: $gene}) "
            "CREATE (d)-[:ASSOCIATED_WITH {evidence_level: $evidence}]->(g)",
            {"disease": disease, "gene": gene, "evidence": evidence},
        )

    # Clinical Trial → Drug / Disease
    trial_links = [
        ("NCT05609578", "Osimertinib", "Non-Small Cell Lung Cancer"),
        ("NCT05252390", "Sotorasib", "Non-Small Cell Lung Cancer"),
        ("NCT04437420", "Lecanemab", "Alzheimer's Disease"),
        ("NCT05684731", "Midostaurin", "Acute Myeloid Leukemia"),
        ("NCT05838768", "Vorasidenib", "Glioblastoma Multiforme"),
    ]

    for tid, drug, disease in trial_links:
        _exec(
            "MATCH (ct:ClinicalTrial {trial_id: $tid}), (dr:Drug {name: $drug}) "
            "CREATE (ct)-[:TESTS]->(dr)",
            {"tid": tid, "drug": drug},
        )
        _exec(
            "MATCH (ct:ClinicalTrial {trial_id: $tid}), (d:Disease {name: $disease}) "
            "CREATE (ct)-[:TRIAL_FOR]->(d)",
            {"tid": tid, "disease": disease},
        )

    # Paper citations
    citations = [
        ("Single-cell atlas%", "EGFR-mutant NSCLC%", "background"),
        ("KRAS G12C%", "EGFR-mutant NSCLC%", "methodology"),
        ("Lecanemab phase III%", "Tau propagation%", "background"),
        ("Temozolomide resistance%", "Synthetic lethality%", "results"),
        ("AI-driven de novo%", "Graph neural networks%", "methodology"),
        ("AI-driven de novo%", "Temozolomide resistance%", "background"),
        ("Spatial transcriptomics%", "Single-cell atlas%", "methodology"),
    ]

    for src_pat, tgt_pat, context in citations:
        _exec(
            "MATCH (p1:Paper) WHERE p1.title STARTS WITH $src "
            "MATCH (p2:Paper) WHERE p2.title STARTS WITH $tgt "
            "CREATE (p1)-[:CITES {context: $context}]->(p2)",
            {"src": src_pat.rstrip("%"), "tgt": tgt_pat.rstrip("%"), "context": context},
        )

    # Funding
    funding = [
        ("EGFR-mutant NSCLC%", "NIH/NCI", "R01-CA234567", 1200000),
        ("Single-cell atlas%", "NIH/NCI", "U01-CA289012", 2500000),
        ("KRAS G12C%", "NIH/NCI", "R01-CA345678", 950000),
        ("Tau propagation%", "Wellcome Trust", "WT-209876", 800000),
        ("Lecanemab phase III%", "NIH/NCI", "U19-AG067890", 5000000),
        ("Graph neural networks%", "DARPA", "HR001122S0045", 3200000),
        ("Cryo-EM structure%", "ERC", "ERC-2023-SyG-951234", 1500000),
        ("Spatial transcriptomics%", "Wellcome Trust", "WT-215432", 600000),
        ("AI-driven de novo%", "DARPA", "HR001123C0067", 4100000),
    ]

    for title_pat, funder, grant, amount in funding:
        _exec(
            "MATCH (p:Paper) WHERE p.title STARTS WITH $prefix "
            "MATCH (f:FundingAgency {name: $funder}) "
            "CREATE (p)-[:FUNDED_BY {grant_id: $grant, amount_usd: $amount}]->(f)",
            {"prefix": title_pat.rstrip("%"), "funder": funder, "grant": grant, "amount": amount},
        )

    # Collaborations
    collabs = [
        ("Dr. Sarah Chen", "Prof. James Okafor", 3, 2020),
        ("Dr. Sarah Chen", "Prof. Ahmed Hassan", 1, 2023),
        ("Dr. Sarah Chen", "Prof. Kenji Tanaka", 1, 2024),
        ("Prof. James Okafor", "Dr. Elena Petrova", 1, 2023),
        ("Dr. Lisa Park", "Prof. David Müller", 1, 2024),
        ("Dr. Maria Santos", "Dr. Elena Petrova", 1, 2023),
        ("Prof. Kenji Tanaka", "Prof. David Müller", 1, 2024),
    ]

    for r1, r2, count, since in collabs:
        _exec(
            "MATCH (a:Researcher {name: $r1}), (b:Researcher {name: $r2}) "
            "CREATE (a)-[:COLLABORATES_WITH {paper_count: $count, since: $since}]->(b)",
            {"r1": r1, "r2": r2, "count": count, "since": since},
        )

    # Summary
    result = _exec("MATCH (n) RETURN count(n) AS nodes")
    node_count = result[0]["nodes"] if result else 0
    result = _exec("MATCH ()-[r]->() RETURN count(r) AS rels")
    rel_count = result[0]["rels"] if result else 0
    print(f"Seeded: {node_count} nodes, {rel_count} relationships")
    return node_count, rel_count


if __name__ == "__main__":
    from neo4j import GraphDatabase

    class SimpleDB:
        def __init__(self, uri, user, password):
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
        def execute(self, cypher, params=None):
            with self._driver.session() as s:
                return [dict(r) for r in s.run(cypher, params or {})]
        def close(self):
            self._driver.close()

    db = SimpleDB("bolt://localhost:7687", "neo4j", "testtest12")
    try:
        seed_database(db)
    finally:
        db.close()
