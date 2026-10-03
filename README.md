```powershell
Set-Location persistance
docker compose up -d redis
# App database is host MySQL on port 3306, database time_grocer.
# Start only redis. A bare docker compose up also starts Postgres on 5432 and points the API at it.
# Redis :6379 · Persistance API :8003
# Or: Set-Location persistance\backend; py -3.13 -m pip install -r requirements.txt; py -3.13 migrate.py; py -3.13 load_catalog.py; py -3.13 -m uvicorn main:app --port 8003
```

```powershell
Set-Location backend-policy
# Host MySQL on port 3306. User tg needs privileges on database time_grocer.
$env:DATABASE_URL = "mysql://tg:tg@127.0.0.1:3306/time_grocer"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
py -3.13 -m pip install -r requirements.txt
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8001
```

```powershell
Set-Location payment\backend
py -3.13 -m pip install -r requirements.txt
# Uses MySQL time_grocer when it answers. payments and payment_jti live there.
# An empty DATABASE_URL keeps the in-memory store.
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8004
```

```powershell
Set-Location agent-brain\backend
py -3.13 -m pip install -r requirements.txt
py -3.13 server.py
```

```powershell
Set-Location frontend
npm install
npm run dev
```
