"""Real synthetic-only NEAR verification; never opens an Airlock vault.

Discovery writes public measured configurations for inspection, not approval.
Run again with reviewed hash allowlists to perform exactly one inference call.
Keys come from a masked terminal prompt or NEARAI_API_KEY, never CLI arguments.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import getpass
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from privacy_layer import near_provider as provider
from privacy_layer.near_setup import NearSetup, PROBE_PROMPT


def safe_failure(error):
    """Structured diagnostic codes only; never exception strings or HTTP bodies."""
    from nearai_inference_sdk.utils.errors import get_sdk_error
    failure = get_sdk_error(error)
    result = {'exception_type': type(error).__name__}
    if failure:
        result['code'] = failure.failure.code
        # The official SDK exposes status as structured data. Exclude all
        # arbitrary response text, URLs, headers and traceback locals.
        details = failure.failure.details or {}
        for name in ('status', 'status_code'):
            if type(details.get(name)) is int: result[name] = details[name]
    return result


async def run(args, key):
    report = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'endpoint': provider.BASE_URL, 'model': provider.model_name(),
              'sdk_version': importlib.metadata.version('nearai-inference-sdk'),
              'synthetic_data_only': True, 'personal_sources_opened': False,
              'prompt': PROBE_PROMPT, 'prompt_sha256': hashlib.sha256(PROBE_PROMPT.encode()).hexdigest(),
              'passed': False, 'inference_calls': 0}
    if not key:
        report['blocker'] = 'NEARAI_API_KEY is missing; no network request attempted'
        return report
    if args.discover:
        deployments = []
        def observe(kind, deployment):
            raw = deployment.app_compose
            deployments.append({'kind': kind, 'sha256': hashlib.sha256(raw.encode()).hexdigest(),
                                'configuration': raw})
        try:
            async with asyncio.timeout(90):
                async with provider.sdk_client(key, observer=observe) as client:
                    evidence = await client.verify(provider.model_name())
                    report['checks'] = provider.validate_preflight(evidence)
                    report['verified_at'] = evidence.verified_at
            report['deployments'] = deployments
            report['status'] = 'hardware verified; deployment review required; inference not attempted'
        except Exception as error:
            report['failure'] = safe_failure(error)
            report['status'] = 'preflight blocked; no inference request sent'
    else:
        setup = NearSetup()
        setup.key = key
        try:
            state = await setup.probe(True)
            report.update(state['last_test'])
        except Exception as error:
            report['failure'] = safe_failure(error)
            report['inference_calls'] = None  # dispatch may have occurred; never report a false zero
            report['status'] = 'verification blocked; no success claim'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discover', action='store_true')
    parser.add_argument('--ask-key', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    key = getpass.getpass('NEAR key (hidden): ') if args.ask_key else os.environ.get('NEARAI_API_KEY', '')
    report = asyncio.run(run(args, key))
    key = ''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'deployments'}, indent=2))
    sys.exit(0 if report.get('passed') or report.get('deployments') else 2)
