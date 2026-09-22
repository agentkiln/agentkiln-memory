# Deployment

This directory contains the public deployment surface for AgentKiln Memory.

Required runtime values:

- `AML_DOMAIN`: public hostname that points to the deployment.
- `AML_API_KEY`: long random value used by the platform to call Add and Search.
- `OPENAI_API_KEY`: runtime model credential. Do not place it in the repository.
- `AML_PRODUCTION=1`: prevents production startup in `off` or `dev_mock` mode.
- `AML_LLM_MODE=competition`.
- `AML_ADD_CONCURRENCY=16` and `AML_SEARCH_CONCURRENCY=32` as the default capacity limits.

Start the service:

```bash
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/health
```

Put Caddy in front of the service so the submitted endpoint is HTTPS:

```bash
AML_DOMAIN=memory.example.com caddy run --config deploy/Caddyfile
```

Run the contract checks against the public endpoint:

```bash
python scripts/ops_contract.py \
  --base-url https://memory.example.com \
  --api-key "$MEMORY_SYSTEM_KEY"
```

The platform receives these live endpoints and the matching authentication mode:

- `POST https://memory.example.com/add`
- `POST https://memory.example.com/search`
- `GET https://memory.example.com/health`

Keep the container, volume, commit, image tag, and environment settings frozen once a production deployment is accepted.
