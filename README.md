How the four modules call each other: [docs/how-the-backend-fits.md](docs/how-the-backend-fits.md).

```powershell
Set-Location payment\backend
py -3.13 -m pip install -r requirements.txt
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8004
```

```powershell
Set-Location persistance
docker compose up -d
# Postgres :5432 · Redis :6379 · Persistance API :8003
# Or: Set-Location persistance\backend; py -3.13 -m pip install -r requirements.txt; py -3.13 migrate.py; py -3.13 -m uvicorn main:app --port 8003
```

```powershell
Set-Location backend-policy
$env:DATABASE_URL = "postgresql://tg:tg@127.0.0.1:5432/time_grocer"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
py -3.13 -m pip install -r requirements.txt
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8001
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
