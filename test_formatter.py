# Run from the repo's parent dir: python -m openflow.test_formatter
from openflow.engine.formatter import TextFormatter

f = TextFormatter([{"phrase_match": "open flow", "replace_with": "OpenFlow"}])
assert f.format("um so like hello world") == "So hello world."
assert f.format("is it done question mark") == "Is it done?"
assert f.format("send it monday scratch that send it friday") == "Send it friday."
assert f.format("a comma b") == "A, b."
assert f.format("first new paragraph second") == "First\n\nSecond."
assert f.format("i love open flow") == "I love OpenFlow."
assert f.format("hola mundo", language="es") == "hola mundo"
assert f.format("   ") == ""
print("formatter OK")
assert f.format("camel case user name", "developer") == "userName."
assert f.format("see you soon", "chat") == "See you soon"
print("presets OK")


from openflow.engine import hardware
from openflow.engine.transcriber import resolve_model_name
hardware.detect()
real = hardware._nvidia_smi
flipped = {} if hardware.detect()["cuda_ok"] else {"name": "GPU", "vram_gb": 6.0}
hardware._nvidia_smi = lambda: flipped
assert hardware.gpu_changed() and not hardware.gpu_changed()
hardware._nvidia_smi = real
assert resolve_model_name("distil-large-v3", "hi") == "medium"
print("gpu switch OK")
