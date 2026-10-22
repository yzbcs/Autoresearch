"""Public HTTP adapters. No model SDK or vendor agent runtime is required.

The canonical conversation contains text, images, tool calls and tool results.
Each model chooses its own calls; these adapters only translate wire formats.
"""
import base64
import json
import os
from pathlib import Path
import urllib.request
import urllib.error


def data_url(path):
    data = base64.b64encode(Path(path).read_bytes()).decode('ascii')
    return 'data:image/png;base64,' + data


def post(url, payload, headers, timeout=180):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                    headers={'Content-Type': 'application/json', **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Do not echo request URLs, headers, credentials or arbitrary server bodies.
        raise RuntimeError(f'Model endpoint returned HTTP {error.code}; check local configuration') from None


class OpenAICompatible:
    """Chat-completions format, including vision and function tools.

    Intended for compatible GPT/Qwen/DeepSeek/local gateways. Model capabilities
    and a real model ID must be supplied by the operator; no alias guessing.
    """
    def __init__(self, config):
        self.config = config

    def payload(self, messages, tools):
        wire = []
        pending_images = []
        for m in messages:
            if m['role'] != 'tool' and pending_images:
                wire.append({'role': 'user', 'content': pending_images})
                pending_images = []
            if m['role'] == 'tool':
                wire.append({'role': 'tool', 'tool_call_id': m['call_id'],
                             'content': json.dumps(m['result'], ensure_ascii=False)})
                if m.get('image_path'):
                    pending_images.extend([
                        {'type': 'text', 'text': 'Actual pixels returned by ' + m['name']},
                        {'type': 'image_url', 'image_url': {'url': data_url(m['image_path'])}}])
            elif m.get('calls'):
                wire.append({'role': 'assistant', 'content': m.get('text') or None,
                             'tool_calls': [{'id': c['id'], 'type': 'function', 'function': {
                                 'name': c['name'], 'arguments': json.dumps(c['arguments'])}}
                                            for c in m['calls']]})
            else:
                wire.append({'role': m['role'], 'content': m.get('text', '')})
            if m['role'] == 'assistant' and m.get('provider_reasoning') is not None:
                # Compatible thinking-mode services may require this verbatim
                # across tool turns. It is provider data, not framework reasoning.
                wire[-1]['reasoning_content'] = m['provider_reasoning']
        if pending_images:
            wire.append({'role': 'user', 'content': pending_images})
        return {**self.config.get('request_options', {}), 'model': self.config['model'],
                'messages': wire, 'tools': [{'type': 'function', 'function': t} for t in tools],
                'tool_choice': 'auto', 'stream': False}

    def complete(self, messages, tools):
        key = os.environ.get(self.config.get('api_key_env', 'MODEL_API_KEY'), '')
        if not key and self.config.get('require_key', True):
            raise RuntimeError('Configured API key environment variable is empty')
        raw = post(self.config['endpoint'], self.payload(messages, tools),
                   {'Authorization': 'Bearer ' + key} if key else {},
                   self.config.get('timeout_seconds', 180))
        m = raw['choices'][0]['message']
        return {'text': m.get('content') or '', 'calls': [
            {'id': c['id'], 'name': c['function']['name'],
             'arguments': json.loads(c['function']['arguments'])} for c in m.get('tool_calls', [])],
            'provider_reasoning': m.get('reasoning_content'),
            'usage': raw.get('usage'), 'reported_model': raw.get('model')}


class Gemini:
    """Gemini generateContent REST format; preserves thought signatures."""
    def __init__(self, config):
        self.config = config

    def payload(self, messages, tools):
        system = '\n'.join(m['text'] for m in messages if m['role'] == 'system')
        contents = []
        for m in messages:
            if m['role'] == 'system':
                continue
            role = 'model' if m['role'] == 'assistant' else 'user'
            if m.get('provider_parts'):
                parts = m['provider_parts']
            elif m['role'] == 'tool':
                parts = [{'functionResponse': {'name': m['name'], 'response': m['result']}}]
                if m.get('provider_call_id'):
                    parts[0]['functionResponse']['id'] = m['provider_call_id']
                if m.get('image_path'):
                    parts.append({'inlineData': {'mimeType': 'image/png',
                                  'data': data_url(m['image_path']).split(',', 1)[1]}})
            else:
                parts = []
                if m.get('text'):
                    parts.append({'text': m['text']})
                parts.extend({'functionCall': {'name': c['name'], 'args': c['arguments']}}
                             for c in m.get('calls', []))
            if contents and contents[-1]['role'] == role:
                contents[-1]['parts'].extend(parts)
            else:
                contents.append({'role': role, 'parts': parts})
        declarations = []
        for t in tools:
            d = {'name': t['name'], 'description': t['description']}
            if t['parameters'].get('properties'):
                # Full JSON Schema is distinct from Gemini's OpenAPI Schema.
                d['parametersJsonSchema'] = t['parameters']
            declarations.append(d)
        return {**self.config.get('request_options', {}),
                'systemInstruction': {'parts': [{'text': system}]}, 'contents': contents,
                'tools': [{'functionDeclarations': declarations}]}

    def complete(self, messages, tools):
        key = os.environ.get(self.config.get('api_key_env', 'GEMINI_API_KEY'))
        if not key:
            raise RuntimeError('Configured API key environment variable is empty')
        raw = post(self.config['endpoint'], self.payload(messages, tools),
                   {'x-goog-api-key': key}, self.config.get('timeout_seconds', 180))
        parts = raw['candidates'][0]['content']['parts']
        return {'text': '\n'.join(p['text'] for p in parts if 'text' in p),
                'calls': [{'id': p['functionCall'].get('id', f'gemini-{i}'),
                           'provider_call_id': p['functionCall'].get('id'), 'name': p['functionCall']['name'],
                           'arguments': p['functionCall'].get('args', {})}
                          for i, p in enumerate(parts) if 'functionCall' in p],
                'provider_parts': parts, 'usage': raw.get('usageMetadata'),
                'reported_model': raw.get('modelVersion')}


def create(config):
    return {'openai-compatible': OpenAICompatible, 'gemini': Gemini}[config['provider']](config)
