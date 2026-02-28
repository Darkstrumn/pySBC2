## Process Services

Process-isolated runtime components coordinated only by MQTT:

1. `sbc_io_service.py`
2. `sbc_reader_service.py`
3. `sbc_writer_service.py`
4. `sbc_macro_service.py`
5. `sbc_model_service.py`
6. `sbc_ai_copilot_service.py`

Start all in separate shells from repo root:

```bash
source .venv/bin/activate
python services/sbc_io_service.py
python services/sbc_reader_service.py
python services/sbc_writer_service.py
python services/sbc_macro_service.py
python services/sbc_model_service.py
python services/sbc_ai_copilot_service.py
```

Or from Windows PowerShell:

```powershell
. .\.venv\Scripts\Activate.ps1
python services/sbc_io_service.py
python services/sbc_reader_service.py
python services/sbc_writer_service.py
python services/sbc_macro_service.py
python services/sbc_model_service.py
python services/sbc_ai_copilot_service.py
```

Or launch separate windows quickly:

```powershell
powershell -ExecutionPolicy Bypass -File services/start_process_services.ps1
```

Fresh install helper:

- `scripts/install_rpi.sh`
