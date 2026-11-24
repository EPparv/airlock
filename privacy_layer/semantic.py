"""On-device related-passage discovery, applied only to filtered, authorized text."""
from collections import Counter
import json
import math
from pathlib import Path
import re
from statistics import median
import subprocess
import sys

from .automatic import query_terms, words

MAX_MODEL_PASSAGES = 160
MAX_RELATED = 4
# Apple's cosine scores for real paraphrases can be around 0.25. Require
# both an absolute floor and separation from unrelated text on this query.
MIN_SIMILARITY = 0.16
BACKGROUND_MARGIN = 0.07
BACKGROUND = (
    'The participants arranged chairs before the meeting.',
    'How do I grow herbs on a windowsill?',
    'A musician chose a slower tempo for the encore.',
    'When is the next exhibition at the gallery?',
    'Smooth pebbles covered the riverbank.',
)
QUALIFIER = re.compile(r'\b(?:not|never|no|only|unless|except|instead|but|however|correction|must)\b', re.I)


def passages(text):
    return [part for part in re.split(r'(?<=[.!?])\s+|\n+', text) if part.strip()]


def apple_similarities(query, texts):
    """Run the system's installed English sentence embedding. Nothing is cached."""
    if sys.platform != 'darwin' or not texts:
        return None
    try:
        result = subprocess.run(
            ['/usr/bin/osascript', '-l', 'JavaScript', str(Path(__file__).with_name('semantic.js'))],
            input=json.dumps({'query': query, 'passages': texts}).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=6, check=True,
        )
        scores = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(scores, list) or len(scores) != len(texts):
        return None
    if any(type(score) not in (float, int) or not math.isfinite(score) or not -1 <= score <= 1
           for score in scores):
        return None
    return scores


def sample(items, limit):
    """Include both ends when the native model's request budget is exceeded."""
    if len(items) <= limit:
        return items
    return [items[i * (len(items) - 1) // (limit - 1)] for i in range(limit)]


def related_plan(rows, query, lexical):
    """Return only opaque row refs and passage indexes for encrypted pagination.

    Two uncommon terms must co-occur in a direct-match seed passage and a new
    passage to expand through the local corpus. There is no multi-hop expansion.
    """
    base, expanded = query_terms(query)
    plan = {'matches': [], 'model_passages': 0, 'model': None}
    if not base:
        return plan
    lexical_refs = {r['ref'] for r in lexical}
    candidates = [r for r in rows if r['ref'] not in lexical_refs and not r.get('core')]
    if not candidates:
        return plan

    counts = Counter(term for row in rows for term in set(words(row['text'])))
    anchors = []
    for seed in lexical[:5]:
        for sentence in passages(seed['text']):
            tokens = set(words(sentence))
            if not tokens & base:
                continue
            distinctive = {t for t in tokens - expanded
                           if len(t) >= 4 and 1 < counts[t] <= max(2, len(rows) // 5)}
            if len(distinctive) >= 2:
                anchors.append(distinctive)
            if len(anchors) == 12:
                break
        if len(anchors) == 12:
            break

    hits = {}
    model_candidates = []
    for row in candidates:
        reference = row['ref']
        segments = [(i, sentence) for i, sentence in enumerate(passages(row['text']))
                    if 2 <= len(sentence.split()) and len(sentence) <= 800]
        for index, sentence in segments:
            if not anchors:
                break
            tokens = set(words(sentence))
            overlap = max(len(tokens & anchor) for anchor in anchors)
            if overlap >= 2:
                # Limit the effect of a longer passage enumerating many terms.
                score = 0.65 + 0.03 * min(overlap, 5)
                if reference not in hits or score > hits[reference][0]:
                    hits[reference] = (score, index, 'related terms')
        model_candidates.extend((reference, index, sentence) for index, sentence in sample(segments, 3))

    model_candidates = sample(model_candidates, MAX_MODEL_PASSAGES)
    if model_candidates:
        texts = [sentence for _, _, sentence in model_candidates]
        scores = apple_similarities(query, [*texts, *BACKGROUND])
        if scores is not None:
            cutoff = max(MIN_SIMILARITY, median(scores[len(texts):]) + BACKGROUND_MARGIN)
            plan.update(model='Apple English sentence embedding', model_passages=len(texts))
            for (reference, index, _), score in zip(model_candidates, scores):
                if score >= cutoff and (reference not in hits or score > hits[reference][0]):
                    hits[reference] = (score, index, 'sentence similarity')

    for ref, (_, idx, basis) in sorted(hits.items(), key=lambda entry: -entry[1][0])[:MAX_RELATED]:
        plan['matches'].append([ref, idx, basis])
    return plan


def related_rows(rows, plan):
    by_ref = {row['ref']: row for row in rows}
    for ref, index, basis in plan['matches']:
        row = by_ref[ref]
        text = row['text']
        if row['kind'] != 'skills':
            parts = passages(text)
            chosen_terms = set(words(parts[index]))
            keep = [part for i, part in enumerate(parts)
                    if i == index or (QUALIFIER.search(part) and
                                      (abs(i - index) == 1 or chosen_terms & set(words(part))))]
            if len(keep) < len(parts):
                text = '\n[…]\n'.join(keep)
        yield {**row, 'text': text, 'match_basis': basis, 'context_minimized': text != row['text']}
