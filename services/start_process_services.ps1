$services = @(
  "python services/sbc_io_service.py",
  "python services/sbc_reader_service.py",
  "python services/sbc_writer_service.py",
  "python services/sbc_macro_service.py",
  "python services/sbc_model_service.py",
  "python services/sbc_ai_copilot_service.py"
)

foreach ($cmd in $services) {
  Start-Process -FilePath "powershell" -ArgumentList "-NoExit", "-Command", $cmd
}
