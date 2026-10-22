"""FigureCrafter subprocess adapter. No third-party AutoFigure-Edit execution."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
VERSION = '2.5.1'
CONFIG_KEYS = {'model', 'reasoning_effort', 'timeout_seconds'}


def python_path():
    return os.environ.get('FIGURECRAFTER_PYTHON', str(REPO / '.venv-figurecrafter/bin/python'))


def configuration(overrides=None):
    if overrides is not None and not isinstance(overrides, dict):
        raise ValueError('绘图配置必须为 JSON 对象。')
    result = dict(overrides or {})
    if set(result) - CONFIG_KEYS:
        raise ValueError('FigureCrafter 配置仅支持 model、reasoning_effort、timeout_seconds；凭据由服务环境管理。')
    result.setdefault('model', os.environ.get('FIGURECRAFTER_MODEL') or os.environ.get('CODEX_MODEL', ''))
    result.setdefault('reasoning_effort', os.environ.get('FIGURECRAFTER_REASONING_EFFORT') or os.environ.get('CODEX_REASONING_EFFORT', 'medium'))
    result.setdefault('timeout_seconds', int(os.environ.get('FIGURECRAFTER_TIMEOUT_SECONDS', '3600')))
    if not isinstance(result['model'], str) or len(result['model']) > 150:
        raise ValueError('model 必须为模型名称。')
    if result['reasoning_effort'] not in {'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}:
        raise ValueError('不支持的推理强度。')
    if type(result['timeout_seconds']) is not int or not 60 <= result['timeout_seconds'] <= 14400:
        raise ValueError('绘图超时必须为 60–14400 秒。')
    return result


class ProcessGroup:
    def __init__(self, process):
        self.process = process
    def poll(self):
        return self.process.poll()
    def terminate(self):
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def runtime_environment():
    cache = REPO / '.cache/figurecrafter'
    temporary = REPO / 'assets/tmp/auto_figure'
    for p in (cache, temporary, REPO / ".cache/fc-ipc"):
        p.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for k, value in {
        'HF_HOME': cache / 'huggingface', 'TORCH_HOME': cache / 'torch',
        'XDG_CACHE_HOME': cache, 'XDG_CONFIG_HOME': cache / 'config',
        'XDG_DATA_HOME': cache / 'data', 'OSL_SOCKET_PATH': temporary, 'TMPDIR': temporary, 'TEMP': temporary, 'TMP': temporary,
        'PYTHONPYCACHEPREFIX': cache / 'pycache', 'MPLCONFIGDIR': cache / 'matplotlib',
        'TEXMFVAR': cache / 'texmf-var', 'TEXMFCONFIG': cache / 'texmf-config',
        'TEXMFCACHE': cache / 'texmf-cache',
    }.items():
        env[k] = str(value)
    soffice = env.get('DRAWING_SOFFICE') or shutil.which('soffice')
    wrapper = ROOT / 'tools/soffice'
    if soffice and Path(soffice).resolve() != wrapper.resolve():
        env['FIGURECRAFTER_SOFFICE_REAL'] = soffice
        env['DRAWING_SOFFICE'] = str(wrapper)
    compiler = env.get('LATEX_COMPILER', '')
    if compiler and Path(compiler).stem == 'tectonic' and Path(compiler).resolve() != (ROOT / 'tools/tectonic').resolve():
        env['FIGURECRAFTER_TECTONIC_REAL'] = compiler
        env['LATEX_COMPILER'] = str(ROOT / 'tools/tectonic')
    env['PYTHONUNBUFFERED'] = '1'
    return env


def health():
    return {'backend': 'FigureCrafter', 'version': VERSION,
            'python': Path(python_path()).is_file(),
            'codex_cli': bool(os.environ.get('CODEX_CLI') or shutil.which('codex')),
            'soffice': bool(shutil.which('soffice') or os.environ.get('DRAWING_SOFFICE')),
            'default_references': len(list((ROOT / 'default_references').glob('style-reference-*.png'))) == 3}


def run(inputs, destination, config, logs, job):
    job.check()
    destination.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    config_file = destination / 'generation-config.json'
    config_file.write_text(json.dumps(configuration(config), ensure_ascii=False, indent=2))
    command = [python_path(), str(ROOT / 'figurecrafter_worker.py'), str(inputs), str(destination), str(config_file), str(logs)]
    if not Path(command[0]).is_file():
        raise RuntimeError('FigureCrafter 独立环境未安装。')
    with (logs / 'generation.log').open('a') as log:
        process = subprocess.Popen(command, cwd=REPO, env=runtime_environment(), stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        group = ProcessGroup(process)
        job.set_process(group)
        deadline = time.monotonic() + config['timeout_seconds']
        try:
            while process.poll() is None:
                if job.cancelled.is_set() or time.monotonic() > deadline:
                    group.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    job.check()
                    raise RuntimeError('FigureCrafter 超时，已保留绘图工作目录，可继续。')
                time.sleep(.2)
        finally:
            job.set_process(None)
            group.terminate()
    job.check()
    result = destination / 'result.json'
    if process.returncode or not result.is_file():
        raise RuntimeError('FigureCrafter 未完成，请查看 generation.log 和 drawing-model 日志；中间稿已保留。')
    return json.loads(result.read_text())
