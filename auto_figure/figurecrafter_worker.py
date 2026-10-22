"""Run the frozen FigureCrafter harness using the existing authenticated Codex bridge."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT / 'figurecrafter'))
from harness.standalone import prepare, verify_frozen, Session, TOOLS
from harness.model_led_drawing import inventory, figure_contract
from auto_figure.codex_bridge import invoke
from auto_figure.write_boundary import restrict_writes
from auto_table.codex_runner import Job


def validate(workspace):
    manifest = json.loads((ROOT / 'framework-manifest.json').read_text())
    for name, sha in manifest['files'].items():
        if hashlib.sha256((ROOT / 'figurecrafter' / name).read_bytes()).hexdigest() != sha:
            raise ValueError('Pinned FigureCrafter source changed: ' + name)
    checked = verify_frozen(workspace)
    if checked['errors'] or checked['unexpected_files']:
        raise ValueError('FigureCrafter freeze verification failed: ' + json.dumps(checked))
    delivery = workspace / 'delivery'
    for name in ('main-figure.pptx', 'main-figure.pdf', 'main-figure.png', 'figure-caption.md', 'visual-review.md'):
        if not (delivery / name).is_file():
            raise ValueError('Missing frozen delivery: ' + name)
    geometry = figure_contract(delivery / 'main-figure.pptx', {'aspect_ratio': [16, 9], 'slide_count': 1})
    native = inventory(delivery / 'main-figure.pptx')
    def flatten(shapes):
        for shape in shapes:
            yield shape
            yield from flatten(shape.get('children', []))
    shapes = list(flatten(native['slides'][0]))
    if not any(s.get('text', '').strip() for s in shapes) or not any('PICTURE' not in s['type'] and 'GROUP' not in s['type'] and not s.get('text') for s in shapes):
        raise ValueError('Editable text and native diagram geometry are required; raster wrappers cannot pass.')
    return {'freeze': checked, 'geometry': geometry, 'native_objects': native,
            'backend': 'FigureCrafter', 'version': '2.5.1',
            'framework_manifest_sha256': hashlib.sha256((ROOT / 'framework-manifest.json').read_bytes()).hexdigest()}


def main():
    inputs, dest, config_file, logs = map(Path, sys.argv[1:])
    config = json.loads(config_file.read_text())
    workspace = dest / 'workspace'
    if not workspace.exists():
        prepare(workspace, inputs, config['model'] or 'configured Codex model')
        shutil.copy2(inputs / 'request.md', workspace / 'work/request.md')
    os.environ['FIGURECRAFTER_NESTED_WORKER'] = '1'
    boundary = restrict_writes([dest, logs, ROOT.parent / '.cache/figurecrafter',
                                ROOT.parent / 'assets/tmp/auto_figure', ROOT.parent / '.cache/fc-ipc', ROOT.parent / '.cache/codex'])
    (dest / 'write-boundary.json').write_text(json.dumps(boundary, indent=2))
    if not (workspace / 'freeze.json').exists():
        session = Session(workspace)
        schema = ROOT / 'prompts/drawing-action.schema.json'
        conversation_file = workspace / 'conversation.json'
        history = json.loads(conversation_file.read_text()) if conversation_file.exists() else []
        if history:
            history.append({'role':'host', 'message':'Resuming this drawing workspace. Inspect the retained history and current artifacts, identify the unfinished step, and continue using the tools. Historical failures do not establish that the runtime is currently repaired. If execute is necessary, preserve old iterations and inspect the NEW actual pixels before review/finish.'})
        tools = json.dumps(TOOLS, ensure_ascii=False)
        # Initial scientific context is provided directly, not through model shell commands.
        guides = '\n\n'.join(p.name + '\n' + p.read_text() for p in (workspace / 'run').glob('*.md'))
        core_prompt = (workspace / 'MODEL.txt').read_text() + '\n' + guides
        core_prompt += '\nAUTHOR REQUEST:\n' + (workspace / 'work/request.md').read_text()
        core_prompt += """\nYou operate the FigureCrafter tools by returning structured calls, not by invoking Codex tools.
All scientific understanding, geometry, authoring code, revisions and selection remain yours.
Return calls as name plus arguments_json (a JSON-encoded arguments object).
You may batch read/write tools, but must wait for returned pixels before review or finish.
Builder uses public python-pptx and saves candidate.pptx in sys.argv[1].
Use installed fonts such as Liberation Sans/Serif; inspect the actual output.
Use read_text and write_file paths relative to this workspace, as described in MODEL.txt.
Actual returned images are attached on the next turn, labeled in order. Observe all three
references and input PDF pixels, selected full render AND publication preview, then review.
A crop comes from the original input image in the hypothetical method; do not invent measurements.
Finish only after concrete pixel review. Do not create fake records or frozen manifests.
If blocked, return a specific message and no calls. No outer evolution or other projects.
"""
        core_prompt += '\nTOOL SCHEMAS:\n' + tools
        for turn in range(80):
            # Tool images persist in the model context through labeled actual attachments.
            image_paths = []
            for item in history:
                path = item.get('result', {}).get('image_path')
                if path and path not in image_paths:
                    image_paths.append(path)
            images = image_paths[-12:]
            prompt = core_prompt + '\nCONVERSATION / TOOL RESULTS:\n' + json.dumps(history, ensure_ascii=False)
            prompt += '\nACTUAL IMAGE ATTACHMENTS IN ORDER:\n' + json.dumps(images, ensure_ascii=False)
            index = len(list(logs.glob('drawing-turn-*.log'))) + 1
            response = invoke(prompt, schema, workspace, logs, f'drawing-turn-{index:03d}', Job(), images=images, config=config)
            history.append({'role':'model', 'response':response})
            if not response.get('calls'):
                conversation_file.write_text(json.dumps(history,ensure_ascii=False,indent=2))
                raise RuntimeError('Drawing model reported a blocker: ' + response.get('message',''))
            unseen_pixels = False
            for call in response['calls']:
                name = call['name']
                try:
                    args = json.loads(call['arguments_json'])
                    if unseen_pixels and name in {'review','finish'}:
                        raise ValueError('Wait for the actual returned image attachments before review/finish.')
                    # Save before a possible finish; nothing may mutate a frozen workspace.
                    conversation_file.write_text(json.dumps(history,ensure_ascii=False,indent=2))
                    result = session.call(name, args)
                except Exception as error:
                    result = {'error':str(error), 'automatic_repair':False}
                history.append({'role':'tool','name':name,'result':result})
                unseen_pixels = unseen_pixels or bool(result.get('image_path'))
                if name=='finish' and 'error' not in result:
                    break
            if (workspace / 'freeze.json').exists():
                break
            conversation_file.write_text(json.dumps(history,ensure_ascii=False,indent=2))
        else:
            raise RuntimeError('Drawing turn limit reached; resumable history retained')
    report = validate(workspace)
    (dest / 'native-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    delivery = workspace / 'delivery'
    result = {k: str(delivery / n) for k, n in {'pptx': 'main-figure.pptx', 'pdf': 'main-figure.pdf',
              'png': 'main-figure.png', 'caption': 'figure-caption.md'}.items()}
    result.update(validation=str(dest / 'native-validation.json'), freeze=str(workspace / 'freeze.json'))
    (dest / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print('Frozen FigureCrafter native delivery verified.')


if __name__ == '__main__':
    main()
