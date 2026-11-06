"""Offline documentation checks using exact prose and module-local AST routes."""
import ast
from dataclasses import asdict, dataclass
from pathlib import Path
import re

from .phrases import GENERIC_NAMES, NOTEXTGENERATION, TEXTGENERATION

CAUSAL = {'AutoModelForCausalLM', 'GPT2LMHeadModel', 'LlamaForCausalLM',
          'MistralForCausalLM', 'Qwen2ForCausalLM', 'GPTNeoForCausalLM',
          'GPTJForCausalLM', 'OPTForCausalLM'}
EXCLUDED = {'.git', '__pycache__', '.venv', 'venv', 'env', '.env', 'virtualenv'}


def prose(text):
    """Remove backtick fences; inline backticks retain their content."""
    result = []
    fence = None
    for line in text.splitlines(keepends=True):
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence):
                fence = None
            result.append('\n')
        elif match:
            fence = match[1]
            result.append('\n')
        else:
            result.append(line.replace('`', ''))
    return ''.join(result)


def consume(text, phrases):
    text = text.lower()
    hits = []
    for phrase in sorted(phrases, key=len, reverse=True):
        start = text.find(phrase)
        while start >= 0:
            hits.append((start, phrase))
            text = text[:start] + ' ' * len(phrase) + text[start + len(phrase):]
            start = text.find(phrase)
    return text, sorted(hits)


def match_claims(text):
    remaining, negative = consume(prose(text), NOTEXTGENERATION)
    _, positive = consume(remaining, TEXTGENERATION)
    return positive, negative


def evidence(source):
    """Return route labels. No import or repository code is executed."""
    tree = ast.parse(source)
    aliases = {}
    shadowed = {n.name for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name != '*':
                    aliases[item.asname or item.name] = node.module + '.' + item.name
    instances = {}
    clients = {}

    def resolve(node):
        if isinstance(node, ast.Name):
            if node.id in shadowed:
                return ''
            return clients.get(node.id, aliases.get(node.id, ''))
        if isinstance(node, ast.Attribute):
            base = resolve(node.value)
            return base + '.' + node.attr if base else ''
        if isinstance(node, ast.Call):
            return resolve(node.func)
        return ''

    def construction(node):
        if not isinstance(node, ast.Call):
            return None
        path = resolve(node.func)
        bits = path.split('.')
        if bits[-1:] == ['from_pretrained']:
            bits = bits[:-1]
        if not bits:
            return None
        name = bits[-1]
        module = '.'.join(bits[:-1]).lower()
        if module == 'transformers' or module.startswith('transformers.'):
            if name == 'pipeline' and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'text-generation':
                return 'pipeline'
            if name in CAUSAL:
                return 'causal'
        for marker, cls in [('llama_cpp', 'Llama'), ('gpt4all', 'GPT4All'),
                            ('ctransformers', 'AutoModelForCausalLM'), ('vllm', 'LLM')]:
            if marker in module and name == cls:
                return 'local'
        return None

    def instance(node):
        if isinstance(node, ast.Name) and node.id not in shadowed:
            return instances.get(node.id)
        return construction(node)

    # Fixed point permits aliases of constructed instances in any source order.
    assignments = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))]
    for _ in range(len(assignments) + 1):
        changed = False
        for node in assignments:
            kind = instance(node.value)
            client_path = resolve(node.value)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (isinstance(target, ast.Name) and client_path.startswith('openai.')
                        and clients.get(target.id) != client_path):
                    clients[target.id] = client_path
                    changed = True
                if isinstance(target, ast.Name) and kind and instances.get(target.id) != kind:
                    instances[target.id] = kind
                    changed = True
        if not changed:
            break
    routes = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        path = resolve(func)
        bits = path.split('.')
        if bits[0] == 'openai' and 'chat' not in [b.lower() for b in bits]:
            if bits[-2:] in [['completions', 'create'], ['Completion', 'create']]:
                routes.add('legacy-completions')
        if path in {'ollama.generate', 'mlx_lm.generate'}:
            routes.add('single-api')
        if isinstance(func, ast.Attribute):
            kind = instance(func.value)
            if func.attr == 'generate' and kind in {'causal', 'local'}:
                routes.add(kind)
            if func.attr in GENERIC_NAMES and func.attr not in shadowed:
                routes.add('generic')
        elif isinstance(func, ast.Name):
            if func.id not in shadowed and path.split('.')[-1] in GENERIC_NAMES:
                routes.add('generic')
        kind = instance(func)
        if kind in {'pipeline', 'local'}:
            routes.add(kind)
    return sorted(routes)


@dataclass
class Finding:
    rule: str
    severity: str
    path: str
    phrase: str
    verdict: str
    message: str

    def to_dict(self):
        return asdict(self)


def audit_repo(repo, ignore=()):
    root = Path(repo)
    if not root.is_dir():
        raise OSError('Repository is not a directory: ' + str(root))
    decisions = []
    sources = []
    docs = []
    fixtures = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        label = relative.as_posix()
        if any(part in EXCLUDED for part in relative.parts) or any(
                (root.joinpath(*relative.parts[:i]) / 'pyvenv.cfg').is_file()
                for i in range(1, len(relative.parts))):
            continue
        if any(label.startswith(prefix) for prefix in ignore):
            decisions.append(label + ': ignored')
            continue
        if not path.is_file():
            continue
        is_doc = label == 'README.md' or (relative.parts[0] == 'docs' and path.suffix == '.md')
        is_test = 'tests' in relative.parts[:-1]
        if path.suffix == '.py' or is_doc or is_test:
            content = path.read_text(encoding='utf-8')
            decisions.append(label + ': scanned')
            if path.suffix == '.py':
                try:
                    sources.extend(label + ': ' + route for route in evidence(content))
                except SyntaxError as exc:
                    raise ValueError(label + ': invalid Python: ' + str(exc)) from exc
            if is_doc:
                docs.append((label, content))
            elif is_test:
                fixtures.append((label, content))
    findings = []
    documented_positive = False
    for label, content in docs:
        positive, negative = match_claims(content)
        documented_positive |= bool(positive)
        for hits, contradicts, rule in [
            (positive, not sources, 'documented-text-generation-claim-false'),
            (negative, bool(sources), 'documented-no-text-generation-claim-false')]:
            if contradicts:
                for _, phrase in hits:
                    findings.append(Finding(rule, 'HIGH', label, phrase, 'FAIL',
                        'Documentation claim conflicts with detected source evidence: ' + phrase))
    if not sources and not documented_positive:
        for label, content in fixtures:
            for _, phrase in match_claims(content)[0]:
                findings.append(Finding('documented-text-generation-claim-false', 'MEDIUM',
                    label, phrase, 'FAIL', 'Claim occurs only in a test fixture: ' + phrase))
    return findings, sources, decisions
