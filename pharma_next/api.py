from dataclasses import dataclass
from typing import Literal
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pharma_next.store import CaseStore, Conflict


@dataclass(frozen=True)
class Identity:
    tenant: str
    subject: str
    role: Literal['editor', 'reviewer']


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(min_length=1, max_length=10000)
    source_refs: list[str] = Field(default_factory=list, max_length=50)


class Revision(Body):
    expected_version: int = Field(ge=1)


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)


def create_app(path, credentials: dict[str, Identity]):
    if not credentials or any(len(token) < 32 or not identity.tenant or not identity.subject or identity.role not in ('editor', 'reviewer') for token, identity in credentials.items()):
        raise ValueError('strong service credentials and identities required')
    store = CaseStore(path)
    app = FastAPI(title='Pharma Next review workspace', version='0.1.0')

    def identity(authorization: str = Header(default='')):
        token = authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
        principal = credentials.get(token)
        if principal is None:
            raise HTTPException(401, 'unauthorized')
        return principal

    def invoke(fn, *args):
        try:
            return fn(*args)
        except KeyError:
            raise HTTPException(404, 'case not found')
        except Conflict as exc:
            raise HTTPException(409, str(exc))
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.get('/health')
    def health():
        return {'status': 'ok', 'regulatory_transmission': False}

    @app.post('/v1/cases', status_code=201)
    def create(body: Body, principal=Depends(identity)):
        if principal.role != 'editor':
            raise HTTPException(403, 'editor required')
        return invoke(store.create, principal.tenant, principal.subject, body.model_dump())

    @app.get('/v1/cases/{case_id}')
    def get(case_id: str, principal=Depends(identity)):
        return invoke(store.get, principal.tenant, case_id)

    @app.put('/v1/cases/{case_id}')
    def revise(case_id: str, body: Revision, principal=Depends(identity)):
        if principal.role != 'editor':
            raise HTTPException(403, 'editor required')
        return invoke(store.revise, principal.tenant, principal.subject, case_id,
                      body.expected_version, body.model_dump(exclude={'expected_version'}))

    @app.post('/v1/cases/{case_id}/review')
    def review(case_id: str, body: Review, principal=Depends(identity)):
        if principal.role != 'reviewer':
            raise HTTPException(403, 'reviewer required')
        return invoke(store.review, principal.tenant, principal.subject, case_id, body.expected_version)

    @app.get('/v1/cases/{case_id}/history')
    def history(case_id: str, principal=Depends(identity)):
        return invoke(store.history, principal.tenant, case_id)

    @app.get('/v1/cases/{case_id}/draft')
    def export(case_id: str, principal=Depends(identity)):
        return invoke(store.export, principal.tenant, principal.subject, case_id)

    return app
