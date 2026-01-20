import json
from db_exec import exec_returning

cfg = {"num_episodes": 5}

exec_returning(
    "UPDATE suites SET config_json = CAST(:cfg AS jsonb) WHERE id = :id RETURNING id",
    {"id": 1, "cfg": json.dumps(cfg)},
)

print("ok")
