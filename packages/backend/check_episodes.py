from db_exec import create_run_episode, list_run_episodes

RUN_ID = 1  # use a real run_id that exists in your DB

eid = create_run_episode(RUN_ID, 0)
print("created episode:", eid)

print(list_run_episodes(RUN_ID))
