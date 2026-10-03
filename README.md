```powershell
Set-Location backend-policy
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
