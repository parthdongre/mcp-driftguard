$ErrorActionPreference = "Stop"

# Keep the runtime and environment in the local checkout. The CUDA wheel is
# selected explicitly for the RTX 5060 Laptop GPU / CUDA 13.0 runtime.
uv python install 3.12 --install-dir .runtime\python --cache-dir .runtime\uv-cache --no-registry
$pythonInstall = Resolve-Path .runtime\python\cpython-3.12.15-windows-x86_64-none\python.exe
uv venv .venv --python $pythonInstall
$trainPython = ".\.venv\Scripts\python.exe"
uv pip install --python $trainPython "torch==2.12.1" --index-url https://download.pytorch.org/whl/cu130
uv pip install --python $trainPython transformers accelerate datasets huggingface_hub scikit-learn safetensors sentencepiece joblib numpy
& $trainPython -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0), torch.cuda.get_device_capability()); x=torch.rand(512,512,device='cuda'); print((x@x).mean().item())"
