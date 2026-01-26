# Pattern Detection Research for Analyzer

Reference document for pattern detection algorithms and approaches.
Created: 2025-01 | Last updated: 2025-01

## Tool Sequence Detection

### Problem
Find recurring sequences of tool calls across sessions.
Input: List of sessions, each with ordered tool calls.
Output: Frequent patterns with occurrence counts and session coverage.

### Approach 1: Sliding Window N-grams (v1 - Recommended Start)

Simple, fast, good for fixed-length patterns.

```python
from collections import Counter

def extract_ngrams(tool_sequence: list[str], n: int = 3) -> list[tuple]:
    """Extract all n-grams from a tool sequence."""
    return [tuple(tool_sequence[i:i+n]) for i in range(len(tool_sequence) - n + 1)]

def find_frequent_sequences(sessions: list[list[str]], n: int = 3, min_count: int = 3):
    ngram_counts = Counter()
    ngram_sessions = defaultdict(set)

    for session_id, tools in sessions:
        for ngram in extract_ngrams(tools, n):
            ngram_counts[ngram] += 1
            ngram_sessions[ngram].add(session_id)

    return {
        ngram: {"count": count, "sessions": ngram_sessions[ngram]}
        for ngram, count in ngram_counts.items()
        if count >= min_count
    }
```

Pros: Simple, fast O(n), easy to understand and debug.
Cons: Fixed window size, misses variable-length patterns.

### Approach 2: PrefixSpan (v2+ - Variable Length)

Pattern-growth algorithm for finding frequent subsequences of any length.

References:
- [PrefixSpan Paper (Han et al.)](https://hanj.cs.illinois.edu/pdf/span01.pdf)
- [SPMF Library](http://www.philippe-fournier-viger.com/spmf/)

```python
# Using prefixspan library: pip install prefixspan
from prefixspan import PrefixSpan

def find_variable_patterns(sessions: list[list[str]], min_support: int = 3):
    """Find frequent subsequences of any length."""
    ps = PrefixSpan(sessions)
    # Returns patterns with at least min_support occurrences
    return ps.frequent(min_support)
```

When to upgrade: When users report missing patterns that span variable lengths,
e.g., "git status → [varying middle steps] → git commit"

### Approach 3: GSP (Generalized Sequential Patterns)

Candidate-generation approach, breadth-first. Works well with high min_support.
Slower than PrefixSpan for low support thresholds.

When to consider: Large itemsets, dense databases where PrefixSpan struggles.

---

## Prompt Pattern Detection

### Problem
Find similar user prompts across sessions to identify recurring requests.
Input: List of user messages.
Output: Clusters of similar prompts with counts.

### Approach 1: Normalized Prefix Matching (v1 - Recommended Start)

Fast exact matching on normalized text prefixes.

```python
import re
from collections import Counter, defaultdict

def normalize_prompt(text: str) -> str:
    """Normalize prompt for pattern matching."""
    text = text.lower()
    # Remove URLs
    text = re.sub(r'https?://\S+', '<url>', text)
    # Normalize paths - option A: replace with placeholder
    text = re.sub(r'(/[\w\-./]+)+', '<path>', text)
    # Option B: Normalize to relative form
    # text = re.sub(r'/Users/\w+/', '~/', text)
    # Remove extra whitespace
    text = ' '.join(text.split())
    return text

def extract_prefix(text: str, n_tokens: int = 5) -> str:
    """Extract first N tokens as pattern key."""
    tokens = text.split()[:n_tokens]
    return ' '.join(tokens)

def find_prompt_patterns(messages: list[str], min_count: int = 3):
    prefix_groups = defaultdict(list)

    for msg in messages:
        normalized = normalize_prompt(msg)
        prefix = extract_prefix(normalized)
        prefix_groups[prefix].append(msg)

    return {
        prefix: examples
        for prefix, examples in prefix_groups.items()
        if len(examples) >= min_count
    }
```

Pros: Fast, deterministic, easy to debug.
Cons: Misses semantically similar but lexically different prompts.

### Approach 2: Jaccard Similarity with Shingling (v2)

Compare prompts using word-level Jaccard similarity.

```python
def word_shingles(text: str, k: int = 2) -> set:
    """Create k-word shingles from text."""
    words = text.lower().split()
    return {tuple(words[i:i+k]) for i in range(len(words) - k + 1)}

def jaccard_similarity(set1: set, set2: set) -> float:
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0

def cluster_by_similarity(messages: list[str], threshold: float = 0.5):
    """Cluster messages with Jaccard similarity >= threshold."""
    # O(n^2) - fine for small datasets
    clusters = []
    used = set()

    for i, msg1 in enumerate(messages):
        if i in used:
            continue
        cluster = [msg1]
        shingles1 = word_shingles(normalize_prompt(msg1))

        for j, msg2 in enumerate(messages[i+1:], i+1):
            if j in used:
                continue
            shingles2 = word_shingles(normalize_prompt(msg2))
            if jaccard_similarity(shingles1, shingles2) >= threshold:
                cluster.append(msg2)
                used.add(j)

        if len(cluster) >= 3:
            clusters.append(cluster)
        used.add(i)

    return clusters
```

When to upgrade: When prefix matching produces too many false negatives,
users report "these prompts should be grouped together."

### Approach 3: MinHash + LSH (v3 - Scale)

Locality Sensitive Hashing for O(n) approximate similarity search.

References:
- [Pinecone LSH Guide](https://www.pinecone.io/learn/series/faiss/locality-sensitive-hashing/)
- [datasketch library](https://github.com/ekzhu/datasketch)

```python
from datasketch import MinHash, MinHashLSH

def minhash_from_text(text: str, num_perm: int = 128) -> MinHash:
    """Create MinHash signature from text."""
    m = MinHash(num_perm=num_perm)
    for shingle in word_shingles(normalize_prompt(text)):
        m.update(' '.join(shingle).encode('utf-8'))
    return m

def find_similar_prompts_lsh(messages: list[str], threshold: float = 0.5):
    """Find similar prompts using MinHash LSH."""
    lsh = MinHashLSH(threshold=threshold, num_perm=128)
    minhashes = {}

    for i, msg in enumerate(messages):
        mh = minhash_from_text(msg)
        minhashes[i] = mh
        lsh.insert(str(i), mh)

    # Find candidate pairs
    clusters = []
    for i, mh in minhashes.items():
        candidates = lsh.query(mh)
        if len(candidates) >= 3:
            clusters.append([messages[int(c)] for c in candidates])

    return clusters
```

When to upgrade: When corpus exceeds ~10k messages and O(n^2) becomes slow.

---

## Path Normalization Strategies

### Option A: Replace with placeholder
```python
text = re.sub(r'(/[\w\-./]+)+', '<path>', text)
# "/Users/john/code/foo.py" -> "<path>"
```
Pros: Clean, removes all path noise.
Cons: Loses info about file types, relative depth.

### Option B: Normalize to home-relative
```python
text = re.sub(r'/Users/\w+/', '~/', text)
text = re.sub(r'/home/\w+/', '~/', text)
# "/Users/john/code/foo.py" -> "~/code/foo.py"
```
Pros: Preserves relative structure.
Cons: Still has path noise.

### Option C: Extract extension/type only
```python
def normalize_path(path: str) -> str:
    ext = Path(path).suffix or 'dir'
    return f'<{ext.lstrip(".")}>'
# "/Users/john/code/foo.py" -> "<py>"
# "/Users/john/code/src" -> "<dir>"
```
Pros: Captures what type of file without noise.
Cons: Loses context about which file.

Recommendation: Test A and C, compare pattern quality.

---

## Useful Libraries

| Library | Purpose | Install |
|---------|---------|---------|
| `datasketch` | MinHash, LSH | `pip install datasketch` |
| `prefixspan` | Sequential pattern mining | `pip install prefixspan` |
| `nltk` | Tokenization, stemming | `pip install nltk` |
| `scikit-learn` | TF-IDF, clustering | `pip install scikit-learn` |

---

## Evaluation Metrics

### Pattern Quality
- **Support**: Number of occurrences
- **Coverage**: Number of distinct sessions containing pattern
- **Confidence**: For A→B patterns, P(B|A)

### Clustering Quality
- **Silhouette score**: How similar items are to own cluster vs others
- **Manual inspection**: Sample clusters, check coherence

---

## Open Questions / Future Work

1. **Variable-length tool sequences**: PrefixSpan when fixed windows insufficient
2. **Semantic prompt similarity**: Embeddings (sentence-transformers) for meaning-based clustering
3. **Temporal decay**: Weight recent patterns higher than old ones
4. **Cross-project vs single-project**: Different thresholds for scope detection
5. **Tool call parameters**: Should `Read(foo.py)` and `Read(bar.py)` be same or different?
