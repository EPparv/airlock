"""Local disclosure policy. No external model, telemetry or raw-source logs.

Detection is deliberately best effort, not an anonymity guarantee. Pseudonyms
are keyed per connection and their dictionary lives only in the encrypted vault.
Never-share policy is enforced by the caller before this layer sees a record.
"""
import hmac
import re

from .core import Denied, canonical
from .automatic import (clean, query_terms, words, PRIVATE_DOCUMENT,
                        SENSITIVE_LINE, SECRET, IDENTIFIER)

SENSITIVE = re.compile(
    r'\b(?:medical|diagnos\w*|prescription|patient|therapy|mental health|'
    r'bank statement|tax return|net worth|account balance|bank balance|'
    r'salary|income|debt|savings|sexual|religion|religious|political affiliation|'
    r'home address|date of birth|birth date|passport|social security|'
    r'confidential|unshared)\b', re.I)
AUTH_DOCUMENT = re.compile(
    r'\b(?:password reset|reset your password|one.time (?:password|passcode|code)|'
    r'verification code|authentication code|recovery (?:code|phrase)|seed phrase)\b', re.I)
JWT = re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b')
BEARER = re.compile(r'\bBearer\s+[A-Za-z0-9._~+/=-]{8,}', re.I)
EXTRA_SECRET = re.compile(r'\b(?:github_pat_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[A-Za-z0-9_-]{30,})\b')
# Explicit identity labels avoid pretending a regex is universal name recognition.
PERSON = re.compile(r'(?i:\b(?:full name|my name|contact name|patient name|person|name)\s*(?:is|:|=)\s*)'
                    r'([A-ZÀ-ÖØ-Þ][\w’\'-]+(?:[ \t]+[A-ZÀ-ÖØ-Þ][\w’\'-]+){0,3})')
ORGANIZATION = re.compile(r'(?i:\b(?:employer|company|organization|organisation)\s*[:=]\s*)'
                          r'([A-ZÀ-ÖØ-Þ][\w’\'-]+(?:[ \t]+[A-ZÀ-ÖØ-Þ][\w’\'-]+){0,3})')


def sensitive(value):
    value = clean(value)
    return bool(SENSITIVE.search(value) or SENSITIVE_LINE.search(value) or
                PRIVATE_DOCUMENT.search(value) or SECRET.search(value) or
                IDENTIFIER.search(value) or JWT.search(value) or BEARER.search(value) or
                EXTRA_SECRET.search(value))


def minimize(value, query):
    """Keep relevant sentences, retaining whole skills/core separately at caller.

    A broad/empty query retains the authorized filtered text. No extra facts are
    invented to bridge omissions. Selection happens before pseudonymization.
    """
    _, wanted = query_terms(query)
    chunks = re.split(r'(?<=[.!?])\s+|\n+', value)
    matches = [chunk for chunk in chunks if set(words(chunk)) & wanted or
               re.search(r'\b(?:not|never|no|only|unless|except|instead|but|however|correction|must)\b', chunk, re.I)]
    if wanted and matches and len(matches) < len(chunks):
        return '\n'.join(matches), True
    return value, False


class PrivacyEngine:
    def __init__(self, gateway, grant):
        self.g, self.grant = gateway, grant

    def pseudonym(self, kind, value):
        digest = hmac.digest(self.g.store.key,
                             canonical(['privacy-v1', self.grant['id'], kind, clean(value).casefold()]),
                             'sha256')[:10]
        # Letters only: aliases cannot be mistaken for credential/phone patterns.
        suffix = digest.hex().translate(str.maketrans('0123456789abcdef', 'abcdefghijklmnop'))
        return f'[{kind}-{suffix}]'

    def learn(self, texts):
        found = {}
        for text in texts:
            for kind, pattern in (('person', PERSON), ('organization', ORGANIZATION)):
                for match in pattern.finditer(clean(text)):
                    value = match.group(1).strip()
                    found[value.casefold()] = (value, self.pseudonym(kind, value))
        if not found:
            return
        with self.g.store.transaction() as data:
            aliases = data.setdefault('privacy_aliases', {}).setdefault(self.grant['id'], {})
            if len(set(aliases) | set(found)) > 2048:
                raise Denied('This connection reached its local identity limit. Create a new scoped connection.')
            for key, entry in found.items(): aliases.setdefault(key, entry)

    def pseudonymize(self, value):
        with self.g.store.transaction() as data:
            aliases = dict(data.get('privacy_aliases', {}).get(self.grant['id'], {}))
        # Single substitution prevents aliases from being interpreted as identities.
        if not aliases:
            return value
        pattern = r'(?<!\w)(?:' + '|'.join(re.escape(x) for x in sorted(aliases, key=len, reverse=True)) + r')(?!\w)'
        return re.sub(pattern, lambda m: aliases[m.group().casefold()][1], value, flags=re.I)

    def filter(self, value, *, query='', email=False, compute=False, core=False, skill=False):
        value = clean(value)
        if compute and AUTH_DOCUMENT.search(value):
            return None
        # Normalize/remove extra token families before passing the common sanitizer.
        value = JWT.sub('[credential withheld]', value)
        value = BEARER.sub('[credential withheld]', value)
        value = EXTRA_SECRET.sub('[credential withheld]', value)
        from .automatic import sanitize
        value = sanitize(value, self.g.sources.protected(), email=email, allow_sensitive=compute)
        if not value:
            return None
        if query and not core and not skill:
            value, _ = minimize(value, query)
        self.learn([value])
        return self.pseudonymize(value)

    def screen(self, value):
        """Owner-visible suggested release; no automatic approval of edited text."""
        if not isinstance(value, str) or not value.strip() or len(value) > 12000:
            raise Denied('Use a nonempty result of at most 12,000 characters.')
        safe = self.filter(value)
        if safe and sensitive(safe): safe = None
        # Sanitizer normalizes sentence breaks. Compare normalized whitespace so
        # formatting alone does not block a safe result or rewrite approved bytes.
        changed = safe is None or ' '.join(safe.split()) != ' '.join(clean(value).split())
        return {'text': safe or '', 'changed': changed, 'blocked': not bool(safe),
                'notice': 'Local screening is best effort. Review the meaning before release; contextual identification can remain.'}

    def require_safe_release(self, value):
        report = self.screen(value)
        if report['changed']:
            raise Denied('Output screening found private details. Review the screened suggestion in Airlock, edit if needed, and approve that exact text.')
        return value.strip()
