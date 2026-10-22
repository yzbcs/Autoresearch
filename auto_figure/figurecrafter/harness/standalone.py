"""Model-led tool loop and CLI bridge, independent of any agent application."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pymupdf
from PIL import Image
from . import model_led_drawing as core
from .providers import create

PACKAGE = Path(__file__).resolve().parents[1]
VERSION = '2.5.1'


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def schema(name, description, fields, required=None):
    return {'name': name, 'description': description, 'parameters': {
        'type': 'object', 'properties': fields, 'required': required or list(fields),
        'additionalProperties': False}}


S = {'type': 'string'}
TOOLS = [
    schema('list_files', 'List current workspace files, never another sample.', {}),
    schema('read_text', 'Read a UTF-8 workspace file including guides or PDF text.', {'path': S}),
    schema('view_image', 'View actual image pixels. The model must inspect all references and final render.', {'path': S}),
    schema('pdf_page', 'Render one input PDF page to pixels; page is 1-based.', {'page': {'type': 'integer'}}),
    schema('pdf_crop', 'Crop a model-selected input PDF rectangle, in page points. Record its intended role in notes.',
           {'page': {'type': 'integer'}, 'rect': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4}, 'output': S}),
    schema('write_file', 'Write model-authored code or notes inside work/. No layouts are supplied by the framework.', {'path': S, 'content': S}),
    schema('execute', 'Execute model-authored Python builder using public packages and render actual PPTX. Retain every attempt.',
           {'builder': S, 'decision': S, 'understanding': S, 'representation': S}),
    schema('inspect', 'Inspect native objects of an iteration. Geometry is not scientific acceptance.', {'iteration': S}),
    schema('review', 'Record the model visual review after observing this iteration rendered pixels.', {'iteration': S, 'path': S}),
    schema('finish', 'Explicit model selection, delivery and hash freezing. Requires visual review and input observations.',
           {'iteration': S, 'caption': S})
]


def configure(soffice=None):
    if not soffice and not os.environ.get('DRAWING_SOFFICE'):
        candidates = [PACKAGE / 'runtime/LibreOffice.app/Contents/MacOS/soffice',
                      Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')]
        soffice = next((str(p) for p in candidates if p.is_file()), None)
    if soffice:
        path = Path(soffice).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError('Configured LibreOffice binary does not exist')
        os.environ['DRAWING_SOFFICE'] = str(path)
    # The builder inherits only ordinary Python/public package and system paths.
    os.environ['PYTHONNOUSERSITE'] = '1'
    os.environ['PYTHONPATH'] = str(PACKAGE)


class Session:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.run = self.root / 'run'
        self.events = self.root / 'events.jsonl'

    def path(self, value, writable=False):
        p = (self.root / value).resolve()
        allowed = self.root / 'work' if writable else self.root
        if not p.is_relative_to(allowed.resolve()):
            raise ValueError('Path outside permitted workspace scope')
        return p

    def log(self, value):
        with self.events.open('a') as stream:
            stream.write(json.dumps({'time': datetime.now(timezone.utc).isoformat(), **value}, ensure_ascii=False) + '\n')

    def observed(self, path):
        sha = core.digest(path)
        self.log({'type': 'image_observed', 'path': str(Path(path).relative_to(self.root)), 'sha256': sha})
        return {'path': str(Path(path).relative_to(self.root)), 'sha256': sha,
                'image_path': str(path), 'observation': 'pixels supplied; interpretation remains model responsibility'}

    def call(self, name, a):
        if (self.root / 'freeze.json').exists():
            raise ValueError('Session frozen; create a new run for further production')
        if name not in {t['name'] for t in TOOLS}:
            raise ValueError('Unknown tool')
        spec = next(t['parameters'] for t in TOOLS if t['name'] == name)
        if set(a) - set(spec['properties']) or set(spec['required']) - set(a):
            raise ValueError('Unexpected or missing tool arguments')
        self.log({'type': 'tool_call', 'name': name, 'arguments': a})
        try:
            result = self.dispatch(name, a)
        except Exception as error:
            self.log({'type': 'tool_error', 'name': name, 'error': str(error)})
            raise
        # Freeze must include its own finish call/result, so snapshot only afterwards.
        self.log({'type': 'tool_result', 'name': name, 'result': result})
        if name == 'finish':
            dump(self.root / 'freeze.json', {'version': VERSION, 'selected_iteration': a['iteration'],
                 'files': {str(p.relative_to(self.root)): core.digest(p) for p in self.root.rglob('*') if p.is_file()},
                 'quality': 'model reviewed; human acceptance pending',
                 'isolation': 'workspace-scoped tools; arbitrary builder code is not an OS sandbox'})
        return result

    def dispatch(self, name, a):
        if name == 'list_files':
            return {'files': [str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file()]}
        if name == 'read_text':
            return {'text': self.path(a['path']).read_text()}
        if name == 'write_file':
            p = self.path(a['path'], True)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(a['content'])
            return {'path': a['path'], 'sha256': core.digest(p)}
        if name == 'view_image':
            p = self.path(a['path'])
            if p.suffix.lower() != '.png':
                raise ValueError('Pixel tool currently accepts PNG')
            with Image.open(p) as img:
                img.verify()
            return self.observed(p)
        if name in {'pdf_page', 'pdf_crop'}:
            with pymupdf.open(self.run / 'inputs/paper-without-main-figure.pdf') as doc:
                page = doc[a['page'] - 1] if 1 <= a['page'] <= len(doc) else None
                if page is None:
                    raise ValueError('PDF page out of range')
                p = self.path(a['output'], True) if name == 'pdf_crop' else self.root / 'work' / f'pdf-page-{a["page"]:02d}.png'
                if p.suffix != '.png':
                    raise ValueError('Raster output must be PNG')
                p.parent.mkdir(parents=True, exist_ok=True)
                rect = pymupdf.Rect(a['rect']) if name == 'pdf_crop' else page.rect
                if rect.is_empty or not page.rect.contains(rect):
                    raise ValueError('PDF crop outside page')
                page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=rect).save(p)
            self.log({'type': 'pdf_view', 'page': a['page'], 'crop': a.get('rect')})
            return self.observed(p)
        if name == 'execute':
            notes = {k: self.path(a[k]) for k in ['understanding', 'representation']}
            folder = core.execute(self.run, self.path(a['builder']),
                [sys.executable, '{builder}', '{output}'], self.path(a['decision']), notes)
            iteration = Path(folder).name
            return {'iteration': iteration, 'render': f'run/iterations/{iteration}/render/slide-01.png',
                    'objects': f'run/iterations/{iteration}/native-objects.json'}
        if name in {'inspect', 'review', 'finish'}:
            i = a['iteration']
            if len(i) != 3 or not i.isdigit():
                raise ValueError('Iteration must be a three-digit index')
            folder = self.run / 'iterations' / i
            if name == 'inspect':
                return core.inventory(folder / 'candidate.pptx')
            events = [json.loads(line) for line in self.events.read_text().splitlines()]
            seen = {e['sha256'] for e in events if e['type'] == 'image_observed'}
            if core.digest(folder / 'render/slide-01.png') not in seen:
                raise ValueError('Model must view the actual selected iteration render before review/delivery')
            if name == 'review':
                return {'review': core.record_review(self.run, i, self.path(a['path']))}
            required = [self.run / 'inputs' / f'style-reference-{k:02d}.png' for k in (1, 2, 3)]
            if any(core.digest(p) not in seen for p in required) or not any(e['type'] == 'pdf_view' for e in events):
                raise ValueError('Model must observe all three references and input PDF pixels before delivery')
            out = core.deliver(self.run, i, self.root / 'delivery', self.path(a['caption']))
            return {'delivery': out, 'selected_by': 'model', 'human_acceptance': 'pending'}
        raise ValueError('Unknown tool')


def prepare(workspace, inputs, model):
    w = Path(workspace).resolve()
    source = Path(inputs).resolve()
    refs = [source / f'style-reference-{k:02d}.png' for k in (1, 2, 3)]
    for path in [source / 'paper-without-main-figure.pdf', *refs]:
        if not path.is_file():
            raise FileNotFoundError(path)
    expected = source / 'input-hashes.json'
    if expected.exists():
        for name, sha in json.loads(expected.read_text()).items():
            if name.endswith(('.pdf', '.png')) and core.digest(source / name) != sha:
                raise ValueError('Scientific input hash mismatch: ' + name)
    w.mkdir(parents=True, exist_ok=False)
    (w / 'work').mkdir()
    core.prepare(w / 'run', source / 'paper-without-main-figure.pdf', refs,
                 guide_directory=PACKAGE / 'guides', outer_loop='human')
    shutil.copy2(PACKAGE / 'protocol/model.txt', w / 'MODEL.txt')
    dump(w / 'session.json', {'version': VERSION, 'model': model, 'provider': None,
         'dependencies': 'public Python packages and LibreOffice',
         'scientific_inputs': {p.name: core.digest(p) for p in [source / 'paper-without-main-figure.pdf', *refs]},
         'isolation': 'fresh workspace; model context and OS sandbox are separate operator responsibilities'})
    return w


def loop(workspace, config, max_turns):
    s = Session(workspace)
    if (s.root / 'freeze.json').exists():
        raise ValueError('Cannot resume a frozen session')
    provider = create(config)
    path = s.root / 'conversation.json'
    messages = json.loads(path.read_text()) if path.exists() else [
        {'role': 'system', 'text': (s.root / 'MODEL.txt').read_text()},
        {'role': 'user', 'text': 'Read the run guides and inputs, generate the missing main figure and use finish to select it.'}]
    for _ in range(max_turns):
        response = provider.complete(messages, TOOLS)
        s.log({'type': 'model_response', 'provider': config['provider'], 'configured_model': config['model'],
               'response': response})
        messages.append({'role': 'assistant', **response})
        dump(path, messages)
        if not response['calls']:
            messages.append({'role': 'user', 'text': 'Production is not finished. Use tools, or report the specific blocker.'})
            dump(path, messages)
            continue
        for c in response['calls']:
            try:
                result = s.call(c['name'], c['arguments'])
            except Exception as error:
                result = {'error': str(error), 'automatic_repair': False}
            m = {'role': 'tool', 'call_id': c['id'], 'name': c['name'], 'result': result}
            if c.get('provider_call_id'):
                m['provider_call_id'] = c['provider_call_id']
            if result.get('image_path'):
                m['image_path'] = result['image_path']
            messages.append(m)
            # finish froze the conversation checkpoint from BEFORE finish.
            # The complete assistant finish call and result are in events.jsonl.
            if c['name'] == 'finish' and 'error' not in result:
                return result
        dump(path, messages)
    raise RuntimeError('Turn limit reached without model-selected delivery; resumable conversation retained')


def doctor(soffice):
    configure(soffice)
    import pptx, PIL, lxml, xlsxwriter
    binary = os.environ.get('DRAWING_SOFFICE') or shutil.which('soffice') or shutil.which('libreoffice')
    result = {'version': VERSION, 'python': sys.executable, 'python_pptx': pptx.__version__,
              'pymupdf': pymupdf.VersionBind, 'pillow': PIL.__version__, 'lxml': lxml.__version__,
              'xlsxwriter': xlsxwriter.__version__, 'soffice': binary,
              'codex_skill_required': False, 'private_package_required': False}
    if not binary:
        raise RuntimeError('Install public LibreOffice and provide --soffice or PATH')
    result['libreoffice_version'] = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=30).stdout.strip()
    return result


def verify_frozen(workspace):
    w = Path(workspace)
    manifest = json.loads((w / 'freeze.json').read_text())['files']
    errors = [n for n, sha in manifest.items() if not (w / n).is_file() or core.digest(w / n) != sha]
    extras = sorted(str(p.relative_to(w)) for p in w.rglob('*')
                    if p.is_file() and str(p.relative_to(w)) not in {*manifest, 'freeze.json'})
    return {'checked': len(manifest), 'errors': errors, 'unexpected_files': extras}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--soffice', help='Public LibreOffice executable, alternatively DRAWING_SOFFICE')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    sub.add_parser('tools')
    a = sub.add_parser('prepare'); a.add_argument('--workspace', required=True); a.add_argument('--inputs', required=True); a.add_argument('--model', required=True)
    a = sub.add_parser('call'); a.add_argument('--workspace', required=True); a.add_argument('--json', required=True, help='Tool request JSON file; same dispatch used by HTTP loop')
    a = sub.add_parser('run'); a.add_argument('--workspace', required=True); a.add_argument('--config', required=True); a.add_argument('--max-turns', type=int, default=80)
    a = sub.add_parser('verify'); a.add_argument('--workspace', required=True)
    args = p.parse_args(); configure(args.soffice)
    if args.command == 'doctor': result = doctor(args.soffice)
    elif args.command == 'tools': result = TOOLS
    elif args.command == 'prepare': result = {'workspace': str(prepare(args.workspace, args.inputs, args.model))}
    elif args.command == 'call':
        c = json.loads(Path(args.json).read_text()); result = Session(args.workspace).call(c['name'], c['arguments'])
    elif args.command == 'run':
        if (Path(args.workspace) / 'freeze.json').exists():
            raise ValueError('Cannot run or change model settings of a frozen session')
        cfg = json.loads(Path(args.config).read_text())
        settings = Path(args.workspace) / 'session.json'
        data = json.loads(settings.read_text()); data.update({'provider': cfg['provider'], 'model': cfg['model']}); dump(settings, data)
        result = loop(args.workspace, cfg, args.max_turns)
    else:
        result = verify_frozen(args.workspace)
        if result['errors'] or result['unexpected_files']:
            print(json.dumps(result)); raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))
