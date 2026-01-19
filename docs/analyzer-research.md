# Analyzer Improvement Research

Investigation date: 2026-01-19
Related: [analyzer-issues.md](./analyzer-issues.md)

## Overview

This document summarizes academic and industry research relevant to solving the pattern analyzer issues documented in `analyzer-issues.md`. Sources are weighted toward peer-reviewed publications, established conferences (NeurIPS, SIAM SDM, ACM), and well-cited foundational work.

---

## Issue 1: Pipeline Context Lost in N-gram Extraction

### Relevant Research

**Hierarchical/Multi-level Pattern Mining**

The foundational work by Srikant & Agrawal on generalizing sequential pattern mining introduced mining patterns with taxonomies (is-a hierarchies). This directly applies: `Bash:grep` could be classified under `Bash:pipeline:grep` vs `Bash:standalone:grep` in a concept hierarchy.

Key papers:
- Srikant, R., & Agrawal, R. (1996). "Mining sequential patterns: Generalizations and performance improvements." EDBT 1996. [Springer](https://link.springer.com/chapter/10.1007/BFb0014140)
- Plantevit, M., et al. (2010). "Mining multidimensional and multilevel sequential patterns." ACM TKDD. [ACM DL](https://dl.acm.org/doi/10.1145/1644873.1644877)

### Recommended Approach

Use a **concept hierarchy** rather than flat n-grams:

```
Bash
├── Bash:pipeline
│   ├── Bash:pipeline:grep
│   ├── Bash:pipeline:head
│   └── Bash:pipeline:awk
└── Bash:standalone
    ├── Bash:standalone:grep
    └── Bash:standalone:find
```

The M3SP algorithm (Plantevit et al.) specifically handles multidimensional and multilevel sequential patterns—mining patterns that respect hierarchical item relationships.

**Implementation:** Parse the bash command at extraction time. If `|` detected, annotate with `is_pipeline=True` and `pipeline_position`. This is cheap (string check) and preserves semantics lost in current normalization.

---

## Issue 2: LLM Classifier Lacks Claude Code Context

### Relevant Research

**Prompt Engineering for Domain-Specific Classification**

Key papers and resources:
- Sahoo, P., et al. (2024). "A Systematic Survey of Prompt Engineering in Large Language Models: Techniques and Applications." [arXiv:2402.07927](https://arxiv.org/abs/2402.07927)
- Schulhoff, S., et al. (2024). "The Prompt Report: A Systematic Survey of Prompting Techniques." [Website](https://sanderschulhoff.com/Prompt_Survey_Site/)
- Weng, L. (2023). "Prompt Engineering." [Lil'Log](https://lilianweng.github.io/posts/2023-03-15-prompt-engineering/)
- Ge, Y., et al. (2024). "An Empirical Evaluation of Prompting Strategies for LLMs in Zero-Shot Clinical NLP." JMIR Medical Informatics. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11036183/)

Key findings:
1. **Task-specific information is pivotal** for prompt design
2. The clinical NLP study showed task-specific prompts achieved 0.96 accuracy vs generic prompts
3. **Few-shot biases** (Zhao et al. 2021): LLMs suffer from majority label bias, recency bias, and common token bias

### Recommended Approach

1. Add explicit **decision criteria** to the prompt (not just tool descriptions):

```markdown
## When Bash is CORRECT (do not flag):
- Contains pipe operator `|`
- Uses features native tools lack: -exec, PCRE regex, -maxdepth
- Chains commands with && or ;

## When native tool MIGHT be better (flag for review):
- Standalone grep on a single file
- Simple find by filename pattern only
```

2. **Provide balanced few-shot examples** showing both "flag" and "don't flag" cases equally to counter majority label bias.

---

## Issue 3: Normal Workflows Flagged as Problems

### Relevant Research

**Contrast Pattern Mining / Discriminative Pattern Mining**

This is fundamentally a contrast pattern mining problem—finding patterns that discriminate between classes, not just frequent patterns.

Key papers:
- Loyola-González, O. (2022). "Contrast Pattern Mining: A Survey." [arXiv:2209.13556](https://arxiv.org/pdf/2209.13556)
- Bringmann, B., & Zimmermann, A. (2015). "Discriminative pattern mining and its applications in bioinformatics." Briefings in Bioinformatics. [Oxford Academic](https://academic.oup.com/bib/article/16/5/884/216950)
- (2025). "Finding the needle in the haystack—An interpretable sequential pattern mining method for classification problems." Frontiers in Big Data. [Frontiers](https://www.frontiersin.org/journals/big-data/articles/10.3389/fdata.2025.1604887/full)

Key insight: Frequency alone is meaningless. `Read → Read → Read` is frequent because it's *normal*, not because it's problematic.

### Recommended Approaches

1. **Contrastive mining**: Use algorithms like SCP-Miner or SeqScout that find patterns discriminating between positive/negative classes. Label some sessions as "good" vs "problematic" and mine patterns unique to problematic sessions.

2. **Discriminative pattern metrics** (replace raw frequency):
   - **Growth Rate (GR)**: ratio of pattern support in "bad" sessions vs "good" sessions
   - **Weighted Relative Accuracy (WRAcc)**: balances generality and discriminative power

   A pattern like `Read → Read → Read` would have GR ≈ 1.0 (appears equally in good/bad sessions) and wouldn't be flagged.

3. **Outcome-based filtering**: The 2025 Frontiers paper proposes ranking patterns by relevance to outcome, not frequency. Only surface patterns that correlate with negative outcomes (longer sessions, more errors, user frustration signals).

---

## Issue 4: N-gram Fixed Size Limitations

### Relevant Research

**Time Series Segmentation & Boundary Detection**

Key papers:
- Keogh, E., & Chu, S. "Segmenting Time Series: A Survey and Novel Approach." UC Irvine. [PDF](https://ics.uci.edu/~pazzani/Publications/survey.pdf)
- (2024). "Unsupervised Time Series Segmentation: A Survey on Recent Advances." CMC. [ScienceDirect](https://www.sciencedirect.com/org/science/article/pii/S1546221824005617)
- (2024). "Exploiting Representation Curvature for Boundary Detection in Time Series." NeurIPS 2024. [PDF](https://proceedings.neurips.cc/paper_files/paper/2024/file/0b7f639ef28a9035a71f7e0c04c1d681-Paper-Conference.pdf)
- (2024). "Pattern-based Time Series Semantic Segmentation with Gradual State Transitions." SIAM SDM 2024. [SIAM](https://epubs.siam.org/doi/10.1137/1.9781611978032.36)

The survey identifies three approaches: **Change Point Detection (CPD)**, **Boundary Detection (BD)**, and **State Detection (SD)**. The NeurIPS 2024 RECURVE paper introduces representation curvature for detecting gradual boundaries—useful since developer workflows don't have sharp boundaries.

**Session/Clickstream Analysis:**
- Wang, G., et al. "Clickstream User Behavior Models." [PDF](https://gangw.cs.illinois.edu/clickstream-tweb.pdf)

### Recommended Approaches

1. **Session-aware segmentation**: Use conversation turn boundaries or time gaps (>N seconds) as natural segment boundaries instead of fixed n-grams. Clickstream research shows time-based session boundaries capture user intent better than fixed windows.

2. **Variable-length pattern mining**: PrefixSpan naturally finds variable-length patterns and outperforms fixed approaches.

3. **Process mining abstractions**: Bose & van der Aalst's work on process mining abstractions proposes detecting "loop patterns," "tandem arrays," and other structural constructs. A `git status → git diff → git add → git commit` becomes a single `git-commit-workflow` abstraction.
   - Bose, R. P. J. C., & van der Aalst, W. M. P. (2009). "Abstractions in Process Mining: A Taxonomy of Patterns." [Springer](https://link.springer.com/chapter/10.1007/978-3-642-03848-8_12)

---

## Issue 5: Prompt Phrases Overwhelming Signal

### Relevant Research

**Interestingness Measures & Pattern Filtering**

Key resources:
- Han, J., et al. "Mining Frequent Patterns, Associations, and Correlations." Data Mining textbook, Chapter 6. [PDF](http://hanj.cs.illinois.edu/cs412/bk3/06.pdf)
- (2023). "Overview of frequent pattern mining." PMC. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9847378/)
- "Interestingness Measure" overview. [ScienceDirect](https://www.sciencedirect.com/topics/computer-science/interestingness-measure)

Key insight from Han: "even strong association rules can be uninteresting and misleading" when using support/confidence alone.

### Recommended Approaches

1. **Multi-dimensional filtering**:
   - Minimum project count (appears in 3+ distinct projects)
   - Minimum session count (appears in 10+ distinct sessions)
   - Cross-user validation (appears for 2+ distinct users)

2. **Correlation-based pruning**: Use **lift** metric. If `lift ≈ 1.0`, the co-occurrence is random. Phrases like "the," "and then" have lift ≈ 1.0 with everything.

3. **Separate analysis streams**: Don't mix prompt phrases with tool sequences in the same classification call. Different pattern types need different interestingness measures.

4. **Semantic deduplication**: Embed phrases and cluster semantically similar ones before counting. "please add" and "can you add" are one pattern.

---

## Algorithm Recommendations

### Sequential Pattern Mining Algorithms

Key comparison paper:
- "Sequential Pattern Mining: A Comparison between GSP, SPADE and PrefixSpan." [Semantic Scholar](https://www.semanticscholar.org/paper/Sequential-Pattern-Mining:-A-Comparison-between-and-Verma-Mehta/34a26642e6b202408b0c9663130f252605b6ffe6)

| Algorithm | Type | Strengths | Best For |
|-----------|------|-----------|----------|
| **PrefixSpan** | Pattern-growth | 9x faster than GSP, memory efficient via pseudo-projection | Variable-length patterns, limited RAM |
| **CM-SPADE** | Vertical format | Stable at low support, good memory control | Large datasets with varied parameters |
| **GSP** | Apriori-based | Simple, well-understood | Baseline comparison |

PrefixSpan reference:
- Pei, J., et al. (2001). "PrefixSpan: Mining Sequential Patterns Efficiently by Prefix-Projected Pattern Growth." [PDF](https://hanj.cs.illinois.edu/pdf/span01.pdf)

SPMF library provides implementations: [SPMF PrefixSpan](https://www.philippe-fournier-viger.com/spmf/PrefixSpan.php)

---

## Developer Behavior & IDE Mining

Relevant prior work on mining developer workflows:

- Damevski, K., et al. (2018). "Mining Developers' Workflows from IDE Usage." [Springer](https://link.springer.com/chapter/10.1007/978-3-319-92898-2_14)
- Vasilescu, B., et al. (2018). "Predicting future developer behavior in the IDE using topic models." [ResearchGate](https://www.researchgate.net/publication/325727252_Predicting_future_developer_behavior_in_the_IDE_using_topic_models)
- Murphy-Hill, E., et al. "A Practical Guide to Analyzing IDE Usage Data." [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/B9780124115194000057)
- Švábenský, V., et al. (2021). "Dataset of shell commands used by participants of hands-on cybersecurity training." Data in Brief. [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2352340921006806)

---

## Prioritized Implementation Recommendations

| Priority | Fix | Effort | Research Basis |
|----------|-----|--------|----------------|
| **1** | Add pipeline detection in normalization | Low | Hierarchical mining, concept taxonomies |
| **2** | Add domain decision criteria to classifier prompt | Low | Prompt engineering surveys, clinical NLP study |
| **3** | Use discriminative metrics (GR, WRAcc) not frequency | Medium | Contrast pattern mining survey |
| **4** | Filter phrases by project/session/user count | Low | Interestingness measures literature |
| **5** | Segment by conversation turn, not fixed n-grams | Medium | Session segmentation, time series BD research |
| **6** | Switch to PrefixSpan for variable-length patterns | Medium | Algorithm benchmarks |
| **7** | Add outcome correlation (did session succeed?) | Higher | Supervised/contrastive pattern mining |

---

## Additional Resources

### Curated Lists
- [Awesome Time Series Segmentation Papers](https://github.com/lzz19980125/awesome-time-series-segmentation-papers) - GitHub repository with categorized papers

### Benchmark Datasets
- **UCR-SEG**: Benchmark for univariate time series boundary detection
- **TSSB**: Superset of UCR-SEG with 98 time series for segmentation evaluation

### Software Libraries
- **SPMF**: Java library with 200+ pattern mining algorithms including PrefixSpan, SPADE, CM-SPADE
- **PM4Py**: Python process mining library for workflow analysis
