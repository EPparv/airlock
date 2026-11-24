import io
import json
import subprocess
import sys
import zipfile

import pytest

from privacy_layer import semantic
from privacy_layer.agent_memory import AgentMemory
from privacy_layer.context import ContextHub, parse_context
from privacy_layer.core import Denied, EncryptedStore, Gateway
from privacy_layer.sources import LocalSources


@pytest.fixture
def env(tmp_path):
    source = LocalSources(key=b's' * 32, context_home=tmp_path / 'profile')
    store = EncryptedStore(tmp_path / 'context.enc', source.key)
    source.connection_store = store
    g = Gateway(store, source, lambda: 1800000000)
    return g, ContextHub(store, clock=g.clock)


def save(env, rows):
    g, hub = env
    p = hub.preview('records.json', json.dumps({'memories': rows}).encode())
    hub.commit(p['id'], list(range(len(p['items']))), g.sources.library())


def grant(g, name='codex'):
    return g.create(agent=name, purpose='Recall test', views=[], approved=True, mode='automatic', max_calls=100)


def read(g, agent, query):
    return g.call(agent['token'], 'get_private_context', {'query': query})


def test_local_associations_depend_on_granted_seed_and_minimize_returned_text(env, monkeypatch):
    monkeypatch.setattr(semantic, 'apple_similarities', lambda *_: None)
    g, _ = env
    save(env, ['My bicycle uses the saffron derailleur.',
               'Adjust the saffron derailleur tomorrow. The garden has tulips.',
               {'text': 'The saffron derailleur has a lilac marker.', 'device_only': True}])
    a, b = grant(g), grant(g, 'cursor')
    memory = AgentMemory(g)
    target = next(r for r, v in memory.snapshot().items() if 'tulips' in v['text'])
    memory.configure(b['id'], [target], disclose=True)
    result = read(g, a, 'bicycle')
    items = result['items']
    assert len(items) == 2
    assert items[1]['match_basis'] == 'related terms'
    assert items[1]['text'] == 'Adjust the saffron derailleur tomorrow.'
    assert items[1]['context_minimized'] and 'lilac' not in str(result) and 'tulips' not in str(result)
    assert not read(g, b, 'bicycle')['items']


def test_sentence_scores_can_find_no_overlap_and_never_receive_ungranted_records(env, monkeypatch):
    g, _ = env
    save(env, ['We repair bikes nearby. The garden has tulips.',
               'Tomorrow is sunny.', 'An unselected redwood record.',
               {'text': 'Top secret bicycle marker.', 'device_only': True}])
    a = grant(g)
    m = AgentMemory(g)
    refs = [r for r, v in m.snapshot().items() if 'redwood' not in v['text'] and not v['device_only']]
    m.configure(a['id'], refs, disclose=True)
    seen = []
    def score(query, texts):
        seen.append((query, texts))
        return [.82 if 'bikes' in text else .18 for text in texts]
    monkeypatch.setattr(semantic, 'apple_similarities', score)
    result = read(g, a, 'Where can I service my cycle?')
    assert 'bikes' in str(result['items']) and len(result['items']) == 1
    assert result['items'][0]['match_basis'] == 'sentence similarity'
    assert 'garden' not in str(result['items']) and 'redwood' not in str(seen) and 'secret' not in str(seen)
    assert result['recall']['sentence_model'] and seen


def test_native_bridge_uses_only_stdin_and_rejects_partial_or_invalid_results(monkeypatch):
    monkeypatch.setattr(semantic.sys, 'platform', 'darwin')
    returned = [.8]
    def run(command, **kwargs):
        assert 'private fixture' not in str(command)
        assert json.loads(kwargs['input']) == {'query': 'private fixture', 'passages': ['one passage']}
        assert kwargs['stderr'] == subprocess.DEVNULL
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(returned).encode())
    monkeypatch.setattr(semantic.subprocess, 'run', run)
    assert semantic.apple_similarities('private fixture', ['one passage']) == [.8]
    for bad in ([], [float('nan')], [True], [.1, .2], [7]):
        returned[:] = bad
        assert semantic.apple_similarities('private fixture', ['one passage']) is None


@pytest.mark.skipif(sys.platform != 'darwin', reason='Apple Natural Language needs macOS')
def test_installed_native_model_ranks_an_actual_paraphrase():
    scores = semantic.apple_similarities('How can I fix my bicycle?',
                                         ['Can someone help repair my bike?', 'The soup contains carrots.'])
    if scores is None:
        # Distinguish a missing OS model from a broken script or invalid bridge.
        probe = subprocess.run(['/usr/bin/swift', '-e',
                                'import NaturalLanguage; print(NLEmbedding.sentenceEmbedding(for: .english) == nil)'],
                               capture_output=True, text=True, check=True)
        if probe.stdout.strip() == 'true':
            pytest.skip('English sentence embedding is unavailable on this Mac')
        pytest.fail('The installed Apple sentence embedding returned no scores')
    assert scores[0] > scores[1]
    assert scores[0] >= semantic.MIN_SIMILARITY


def test_cursor_reuses_original_semantic_selection_when_model_availability_changes(env, monkeypatch):
    g, _ = env
    save(env, [f'Bicycle checkpoint {i} is open.' for i in range(14)] + ['We repair bikes nearby.'])
    monkeypatch.setattr(semantic, 'apple_similarities', lambda q, texts: [.84] * len(texts))
    a = grant(g)
    result = read(g, a, 'bicycle')
    assert result['more_available']
    monkeypatch.setattr(semantic, 'apple_similarities', lambda *_: pytest.fail('rescored an open cursor'))
    page = read(g, a, result['next_query'])
    assert 'repair bikes' in str(result['items'])
    assert len(result['items']) + len(page['items']) == 15
    assert not set(r['ref'] for r in result['items']) & set(r['ref'] for r in page['items'])


def message(role, *parts, hidden=False):
    return {'author': {'role': role}, 'content': {'content_type': 'text', 'parts': list(parts)},
            'metadata': {'is_visually_hidden_from_conversation': hidden}}


def test_chatgpt_active_branch_only_and_owner_commit(env):
    g, hub = env
    a = grant(g)
    nodes = {'a': {'parent': None, 'message': message('system', 'omitted-1')},
             'b': {'parent': 'a', 'message': message('user', 'Bicycle repair is tomorrow.', {'asset': 'omitted-2'})},
             'c': {'parent': 'b', 'message': message('assistant', 'omitted-3')},
             'd': {'parent': 'c', 'message': message('user', 'omitted-4', hidden=True)},
             'e': {'parent': 'd', 'message': message('user', '[CORE] A past question?')},
             'f': {'parent': 'd', 'message': message('user', 'omitted-5')}}
    data = json.dumps([{'mapping': nodes, 'current_node': 'e', 'title': 'omitted-6'}]).encode()
    p = hub.preview('conversations.json', data, 'chat')
    assert len(p['items']) == 2 and all(row['chat_source'] == 'ChatGPT' and not row['core'] for row in p['items'])
    assert 'omitted-' not in str(p)
    assert not read(g, a, 'Bicycle')['items']
    hub.commit(p['id'], [0], g.sources.library())
    item, = read(g, a, 'Bicycle')['items']
    assert item['text'] == 'Bicycle repair is tomorrow.' and 'conversation excerpt' in item['evidence_type']
    assert 'past question' not in str(g.sources.library()) and b'Bicycle' not in g.store.path.read_bytes()
    m = AgentMemory(g)
    m.configure(a['id'], list(m.snapshot()), disclose=True)
    assert 'conversation excerpt' in read(g, a, 'Bicycle')['items'][0]['evidence_type']


def test_claude_export_in_archive_and_unsupported_inputs():
    chat = {'chat_messages': [
        {'sender': 'assistant', 'text': 'omitted'},
        {'sender': 'human', 'text': 'What about the budget?'},
        {'sender': 'human', 'text': 'omitted fallback', 'content': [
            {'type': 'tool_result', 'content': 'omitted value'}, {'type': 'text', 'text': 'Repair notes.'}]},
        {'sender': 'human', 'text': 'x' * 12001}]}
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('folder/conversations-0001.json', json.dumps([chat]))
        archive.writestr('accounts.json', 'omitted')
    parsed = parse_context('export.zip', out.getvalue())
    assert [x['text'] for x in parsed['items']] == ['What about the budget?', 'Repair notes.']
    assert all(x['chat_source'] == 'Claude' for x in parsed['items'])
    assert 'omitted' not in str(parsed) and 'Skipped 1' in parsed['scope']
    with pytest.raises(Denied):
        parse_context('conversations.json', json.dumps(chat).encode(), 'skills')
    with pytest.raises(Denied):
        parse_context('broken.json', b'{"mapping":{"x":{"parent":"x"}},"current_node":"x"}')


def test_compute_only_stays_outside_model_input_and_empty_question_bypasses_model(env, monkeypatch):
    g, _ = env
    save(env, ['An approved atlas check.', 'Medical diagnosis details require private handling.'])
    a = grant(g)
    memory = AgentMemory(g)
    refs = list(memory.snapshot())
    memory.configure(a['id'], refs, compute=True)
    monkeypatch.setattr(semantic, 'apple_similarities', lambda *_: pytest.fail('unnecessary model read'))
    with pytest.raises(Denied, match='compute-only'):
        read(g, a, 'atlas')
    safe = [r for r in refs if 'approved' in memory.snapshot()[r]['text']]
    memory.configure(a['id'], refs, compute=True, disclose=True, disclose_records=safe)
    items = read(g, a, '')['items']
    assert len(items) == 1 and 'approved' in items[0]['text']


def test_unsupported_message_metadata_and_attachments_never_create_records():
    photo = {'author': {'role': 'user'}, 'content': {'content_type': 'multimodal_text',
             'parts': [{'asset_pointer': 'image'}, 'My past question?']}}
    custom = {'author': {'role': 'user'}, 'content': {'content_type': 'user_editable_context',
              'parts': ['unreviewed private preferences']}}
    export = {'mapping': {'1': {'parent': None, 'message': custom},
                          '2': {'parent': '1', 'message': photo}}, 'current_node': '2'}
    parsed = parse_context('conversation.json', json.dumps(export).encode())
    assert [r['text'] for r in parsed['items']] == ['My past question?']
    assert 'asset_pointer' not in str(parsed) and 'unreviewed' not in str(parsed)
