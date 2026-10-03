```powershell
# MySQL80 is already on 127.0.0.1:3306, database time_grocer, user tg.
Set-Location persistance
docker compose up -d redis
```

```powershell
Set-Location persistance\backend
py -3.13 -m pip install -r requirements.txt
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8003
```

```powershell
Set-Location backend-policy
$env:DATABASE_URL = "mysql://tg:tg@127.0.0.1:3306/time_grocer"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
py -3.13 -m pip install -r requirements.txt
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8001
```

```powershell
Set-Location payment\backend
py -3.13 -m pip install -r requirements.txt
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
