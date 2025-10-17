# Helm deployment

## Install

1. Set container image repositories/tags in `oscillink-latticedb/values.yaml` (defaults assume GHCR)
2. Install:

   helm upgrade --install latticedb ./oscillink-latticedb -n latticedb --create-namespace

## Configuration

- API env (JWT/JWKS, rate limiting, proxy headers, timeouts, concurrency, OTel) under `.api.env`
- Provide secrets via `.api.extraEnv` with `valueFrom` to a Secret if desired
- Enable Redis for rate limiting in-cluster: `--set redis.enabled=true --set api.env.LATTICEDB_RATE_LIMIT_ENABLED=true`
- Ingress: enable and set hosts/paths. UI defaults to `/`, API to `/api`
- PVC for DB root enabled by default; disable with `--set api.volume.enabled=false`

### TLS and split ingress

- Single ingress (default): set `ingress.enabled=true` and configure `ingress.hosts` with UI `/` and API `/api`
- Split ingress: set `ingress.enabled=true, ingress.split=true` to create separate resources with independent class/hosts/TLS

Examples:

  helm upgrade --install latticedb ./oscillink-latticedb -n latticedb \
    -f ./oscillink-latticedb/values.prod.yaml

### Security contexts and PDBs

- Default securityContext and podSecurityContext are enabled for API/UI. Override via `.api.securityContext`, `.api.podSecurityContext`, `.ui.securityContext`, `.ui.podSecurityContext`.
- PodDisruptionBudgets: toggle with `.pdb.api.enabled`/`.pdb.ui.enabled` and choose `minAvailable` or `maxUnavailable`.

### Scheduling knobs

- Expose `nodeSelector`, `tolerations`, `affinity`, and `topologySpreadConstraints` under `.api` and `.ui`.

### Environments

- Dev profile: `-f ./oscillink-latticedb/values.dev.yaml`
- Prod profile: `-f ./oscillink-latticedb/values.prod.yaml`

### SPD parameters and compose gating

- SPD solver envs (defaults in values.yaml under `.api.env`):
  - `LATTICEDB_SPD_DIM`, `LATTICEDB_SPD_K_NEIGHBORS`, `LATTICEDB_SPD_LAMBDA_G`, `LATTICEDB_SPD_LAMBDA_C`, `LATTICEDB_SPD_LAMBDA_Q`, `LATTICEDB_SPD_TOL`, `LATTICEDB_SPD_MAX_ITER`
- Override via `--set api.env.LATTICEDB_SPD_LAMBDA_C=0.75` etc., or by using dev/prod values files.
- The compose endpoint also accepts per-request overrides for SPD tuning and gating thresholds `epsilon` and `tau`.

### Embedding settings

- Embedding envs (defaults in values.yaml under `.api.env`):
  - `LATTICEDB_EMBED_MODEL` (e.g., `bge-small-en-v1.5`)
  - `LATTICEDB_EMBED_DEVICE` (`cpu` or `cuda`)
  - `LATTICEDB_EMBED_BATCH_SIZE` (e.g., `32`)
  - `LATTICEDB_EMBED_STRICT_HASH` (`true`/`false`)
- Override via `--set api.env.LATTICEDB_EMBED_MODEL=gte-base-en-v1.5` etc., or use dev/prod values files.

### NetworkPolicies (optional)

- Enable with `--set networkPolicy.enabled=true`
- Configure API ingress sources (ingress controllers or internal callers) via `.networkPolicy.api.ingress.from`
- API egress knobs:
  - `.networkPolicy.api.egress.allowClusterDNS` (UDP/TCP 53)
  - `.networkPolicy.api.egress.allowRedis` (to in-chart Redis)
  - `.networkPolicy.api.egress.extra` for additional destinations
- UI ingress/egress configured similarly under `.networkPolicy.ui.*`
- When `redis.enabled=true` and `networkPolicy.enabled=true`, a Redis NetworkPolicy only allows ingress from API pods on the Redis TCP port.
 - To restrict UI egress to only the API Service, set `.networkPolicy.ui.egress.allowAPIOnly=true` (DNS can remain enabled via `.allowClusterDNS`).

## Quick examples

- Enable JWT HS256:

  helm upgrade --install latticedb ./oscillink-latticedb -n latticedb \
    --set api.env.LATTICEDB_JWT_ENABLED=true \
    --set api.env.LATTICEDB_JWT_SECRET=supersecret

- Enable JWKS:

  helm upgrade --install latticedb ./oscillink-latticedb -n latticedb \
    --set api.env.LATTICEDB_JWT_ENABLED=true \
    --set api.env.LATTICEDB_JWT_JWKS_URL=https://issuer.example.com/.well-known/jwks.json \
    --set api.env.LATTICEDB_JWT_ALGORITHMS=RS256 \
    --set api.env.LATTICEDB_JWT_ISSUER=https://issuer.example.com \
    --set api.env.LATTICEDB_JWT_AUDIENCE=my-aud

- Enable Redis rate limiting in cluster:

  helm upgrade --install latticedb ./oscillink-latticedb -n latticedb \
    --set redis.enabled=true \
    --set api.env.LATTICEDB_RATE_LIMIT_ENABLED=true
