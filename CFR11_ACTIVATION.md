# Aktivacija 21 CFR Part 11 — Pharma Intelligence OS Next

Ova implementacija dodaje četiri pilastra usklađenosti sa 21 CFR Part 11 na
`pharma_next` FastAPI uslugu (case review / ICSR radni tok):

1. **Imutabilni vremenski pečateni audit trail sa kriptografskim potpisom**
   — svaki događaj (kreiranje, revizija, recenzija, odobrenje, izvoz) se
   upisuje u lancu gde svaki zapis povezuje prethodni `digest` (GENESIS
   korijen), potpisan je Ed25519 potpisom usluge i enkriptovan AES-256-GCM
   za čuvanje (at rest). `verify_chain()` ponovo računa lancu, provjerava
   potpise i otkvara bilo kakvu izmjenu, brisanje ili premještanje zapisa.

2. **E-potpisi za ljudska odobrenja** (11.100 / 11.200)
   — `POST /v1/cfr11/e-sign` povezuje potpis s korisnikom, svrhom, case-om i
   verzijom; potpis se može napraviti samo jednom po kombinaciji
   (korisnik, svrha, case, verzija) i nije ponovljiv. Potvrda:
   `GET /v1/cfr11/e-sign/{sig_id}/verify`.

3. **RBAC sa dual autorizacijom** (two-person rule)
   — uloge: `reader`, `editor`, `reviewer`, `approver`, `admin` (pohranjene,
   nemaju se poveriti zaglavljima). Recenzija treba biti nezavisna
   (ne smije ju napraviti editor tog case-a). Odobrenje izdavanja
   (draft → approved) zahtijeva dva **različita** approver-a (ili jednog ako
   je `CFR11_DUAL_AUTHORIZATION` isključen). Izvoz je mogao samo od
   `approved` case-a i samo od approver-a.

4. **Enkripcija audit traja u omeru i tranzitu**
   — at rest: AES-256-GCM sa po rednom nonce-om za svaki zapis tijela
   događaja i e-potpisa. In transit: middleware odbija ne-HTTPS zahtjeve
   kada je `CFR11_REQUIRE_TLS=1` i šalje HSTS (`Strict-Transport-Security`),
   `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` na svaki
   odgovor.

## Datoteke

Nova:
- `pharma_next/cfr11.py` — jezdro usklađenosti (trail, e-potpisi, RBAC, dual auth, enkripcija, verifikacija)
- `tests/test_cfr11_audit_chain.py` — lanc, detekcija tampra, verifikacija
- `tests/test_cfr11_e_signatures.py` — e-potpisi, veza s korisnikom/case-om, otpornost na tampra
- `tests/test_cfr11_rbac_dual_auth.py` — uloge, nezavisna recenzija, dva approver-a, izvoz
- `tests/test_cfr11_encryption.py` — enkripcija at rest, pogrešan ključ ne otvara
- `tests/test_cfr11_api.py` — HTTP nivel: auth, RBAC, dual auth, trail, e-potpisi, TLS middleware
- `CFR11_ACTIVATION.md` — ovaj dokument

Modifikovano:
- `pharma_next/store.py` — `CaseStore` prima `CFR11Compliance`; eventi idu kroz signovani/enkriptirani trail; nova metoda `approve()`; izvoz zahtijeva `approved` stanje kada je CFR 11 omogućen
- `pharma_next/__init__.py` — izvoz `CFR11Compliance`, `cfr11_enabled`
- `pharma_next/api.py` — autentikacija (`X-User-Id`), RBAC `require_role`, novi CFR 11 endpoints, TLS middleware, sigurnosna zaglavlja
- `pyproject.toml` — zavisnost `cryptography>=42,<51`

## Aktivacija (korak po korak)

### 1. Instaliraj zavisnosti

```bash
cd C:\Users\DT User\Pharma-Intelligence-Os-Next
pip install -e ".[test]"
```
(`cryptography` se povuče kroz `pyproject.toml`.)

### 2. Generiši ključeve

Signing ključ (Ed25519, 32 bajta, base64):

```bash
python - <<'EOF'
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
print(base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode())
EOF
```

Enkripcioni ključ (AES-256, 32 bajta, base64):

```bash
python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
```

Spremi ih u datoteke (preporučeno) ili okoline:

```powershell
# PowerShell primer — upiši generisane vrednosti u datoteke
Set-Content -Path C:\Users\DT User\Pharma-Intelligence-Os-Next\secrets\signing.key.b64 -Value "<BASE64-ED25519-SEED>"
Set-Content -Path C:\Users\DT User\Pharma-Intelligence-Os-Next\secrets\enc.key.b64 -Value "<BASE64-AES-256-KLJUČ>"
```

### 3. Postavi okoline

Primjer (cmd.exe / PowerShell):

```powershell
$env:CFR11_ENABLE="1"
$env:CFR11_SIGNING_KEY_FILE="C:\Users\DT User\Pharma-Intelligence-Os-Next\secrets\signing.key.b64"
$env:CFR11_ENCRYPTION_KEY_FILE="C:\Users\DT User\Pharma-Intelligence-Os-Next\secrets\enc.key.b64"
$env:CFR11_REQUIRE_TLS="1"          # 1 u produkciji (zahtijeva HTTPS)
$env:CFR11_DUAL_AUTHORIZATION="1"   # 1 = dva approver-a za izdavanje
$env:CFR11_ROLE_SEED="eve:admin,tenant-a"   # opciono: seed uloge pri pokretanju
```

Ključne varijable:
| Varijabla | Značenje |
|---|---|
| `CFR11_ENABLE=1` | Uključi fail-closed način (potpis/enkripcija/RBAC obavezni) |
| `CFR11_SIGNING_KEY` / `_FILE` | Ed25519 signing ključ (obavezno ako je omogućen) |
| `CFR11_ENCRYPTION_KEY` / `_FILE` | AES-256 ključ za at-rest enkripciju (obavezno) |
| `CFR11_REQUIRE_TLS=1` | Odbija HTTP; zahtijeva HTTPS (ili `x-forwarded-proto: https` za proxy) |
| `CFR11_DUAL_AUTHORIZATION=1` | Dva različita approver-a za odobrenje izdavanja |
| `CFR11_ROLE_SEED` | `user:role,tenant;user:role,tenant` seed pri pokretanju |

### 4. Pokreni server

```bash
uvicorn pharma_next.main:application --factory --host 0.0.0.0 --port 8000
```
Docker build radi isto (`CMD` je već podešen); ključevi se proslijeđuju kroz okruženje kontejnera.

### 5. Autentikacija i RBAC kroz zaglavlja

Svi menjaći endpoints zahtijevaju:
- `X-User-Id` — identitet korisnika (obavezno kada je `CFR11_ENABLE=1`)
- `X-Tenant` — tenant (ili query parametar `tenant`)

Autoritativne uloge se pohranjuju i provode kroz API:

```bash
# admin dodeljuje uloge
curl -X POST http://localhost:8000/v1/cfr11/roles -H "X-User-Id: eve" \
  -H "Content-Type: application/json" -d '{"user_id":"alice","role":"editor","tenant":"tenant-a"}'

# pregled uloge
curl "http://localhost:8000/v1/cfr11/roles?user_id=alice&tenant=tenant-a" -H "X-User-Id: eve"
```

Dozvole po endpointu: `editor` (kreiraj/revidiraj), `reviewer` (neavisna recenzija), `approver` (dual autorizacija + izvoz), `admin` (dodjeljivanje uloga), `reader` (čitanje, audit trail, verifikacija).

### 6. Radni tok dual autorizacije (primjer)

```bash
alice (editor)       -> POST /v1/cases        -> case staje na draft
bob  (reviewer)      -> POST .../review       -> stanje reviewed (ne smije recenzirati sopstvenu reviziju)
carol (approver)     -> POST .../approve      -> 1. autorizacija, stanje ostaje reviewed
dave  (approver)     -> POST .../approve      -> 2. autorizacija, stanje approved
carol (approver)     -> GET  .../draft        -> izvoz (sha256 potpisani artefakt) samo ako je approved
```

### 7. Verifikacija

```bash
pytest tests/ -q
```
Očekivano: 27 passa. Cijela suit pokreće se i u CI (`.github/workflows/ci.yml`, Python tests job, koji sada instalira `cryptography` kroz `pyproject.toml`).

Provjera nepronikljivosti traja:

```bash
GET /v1/cfr11/audit/verify?tenant=tenant-a   -> {"ok": true, ...}
```

Bilo kakva izmjena u `cfr11_audit_events` ili `cfr11_e_signatures` čini `ok: false` i navodi `tampered` zapise.

### Napomena o legacy načinu

Kada `CFR11_ENABLE` nije postavljen (ili je `0`), usluga radi u starom načinu: nepotpisani hash-lanc u `audit` tabeli, bez RBAC-a i enkripcije, izvoz zahtijeva samo `reviewed`. Ovo je namenjeno razvojnim/legacy okruženjima; za regulatornu radnju uvijek pokreni sa `CFR11_ENABLE=1` i obje ključeva — u tome načinu kod je fail-closed (bez ključeva pokretanje baca grešku).
