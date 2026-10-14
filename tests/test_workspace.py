import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from pharma_next.api import create_app, Identity
from pharma_next.store import CaseStore, Conflict


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / 'cases.db'
    keys = {'e' * 32: Identity('one', 'alice', 'editor'),
            'r' * 32: Identity('one', 'bob', 'reviewer'),
            'x' * 32: Identity('two', 'eve', 'reviewer')}
    return path, TestClient(create_app(path, keys))


def headers(key='e'):
    return {'Authorization': 'Bearer ' + key * 32}


def create(client):
    response = client.post('/v1/cases', headers=headers(), json={'summary': 'Synthetic case', 'source_refs': ['fixture:1']})
    assert response.status_code == 201
    return response.json()


def test_auth_and_role_cannot_be_supplied_by_body(workspace):
    _, client = workspace
    assert client.post('/v1/cases', json={'summary': 'a'}).status_code == 401
    assert client.post('/v1/cases', headers=headers(), json={'summary': 'a', 'tenant': 'other', 'role': 'reviewer'}).status_code == 422


def test_cross_tenant_reads_and_review_fail(workspace):
    _, client = workspace
    case = create(client)
    assert client.get('/v1/cases/' + case['id'], headers=headers('x')).status_code == 404
    assert client.post('/v1/cases/' + case['id'] + '/review', headers=headers('x'), json={'expected_version': 1}).status_code == 404


def test_restart_preserves_case(workspace):
    path, client = workspace
    case = create(client)
    assert CaseStore(path).get('one', case['id'])['body']['summary'] == 'Synthetic case'


def test_stale_revision_rejected(workspace):
    _, client = workspace
    case = create(client)
    url = '/v1/cases/' + case['id']
    assert client.put(url, headers=headers(), json={'summary': 'updated', 'expected_version': 1}).status_code == 200
    assert client.put(url, headers=headers(), json={'summary': 'lost update', 'expected_version': 1}).status_code == 409


def test_review_role_and_independence(workspace):
    path, client = workspace
    case = create(client)
    url = '/v1/cases/' + case['id'] + '/review'
    assert client.post(url, headers=headers(), json={'expected_version': 1}).status_code == 403
    with pytest.raises(PermissionError):
        CaseStore(path).review('one', 'alice', case['id'], 1)
    assert client.post(url, headers=headers('r'), json={'expected_version': 1}).json()['state'] == 'reviewed'
    assert client.post(url, headers=headers('r'), json={'expected_version': 1}).status_code == 409


def test_export_requires_review_and_is_explicit_draft(workspace):
    _, client = workspace
    case = create(client)
    root = '/v1/cases/' + case['id']
    assert client.get(root + '/draft', headers=headers()).status_code == 409
    assert client.post(root + '/review', headers=headers('r'), json={'expected_version': 1}).status_code == 200
    response = client.get(root + '/draft', headers=headers()).json()
    assert response['artifact']['regulatory_validated'] is False
    assert response['artifact']['transmitted'] is False
    assert response['sha256'] == hashlib.sha256(json.dumps(response['artifact'], sort_keys=True, allow_nan=False).encode()).hexdigest()


def test_revision_invalidates_old_review(workspace):
    _, client = workspace
    case = create(client)
    root = '/v1/cases/' + case['id']
    client.post(root + '/review', headers=headers('r'), json={'expected_version': 1})
    assert client.put(root, headers=headers(), json={'summary': 'new evidence', 'expected_version': 2}).json()['state'] == 'draft'
    assert client.get(root + '/draft', headers=headers()).status_code == 409
    assert [r['version'] for r in client.get(root + '/history', headers=headers()).json()] == [1, 2, 3]


def test_config_requires_strong_keys(tmp_path):
    with pytest.raises(ValueError):
        create_app(tmp_path / 'test.db', {'short': Identity('one', 'a', 'editor')})
