"""Fixed vocabulary oracles, route boundaries, prose rules and CLI integration."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from text_generation_claim_audit import __version__
from text_generation_claim_audit.audit import evidence, match_claims, audit_repo, prose
from text_generation_claim_audit.phrases import TEXTGENERATION, NOTEXTGENERATION, GENERIC_NAMES
from text_generation_claim_audit.__main__ import main

EXPECTED_POSITIVE = ['text generation', 'text-generation', 'textgeneration', 'generate text', 'generates text', 'generating text', 'generate textual content', 'text generation support', 'supports text generation', 'text generation capability', 'text generation feature', 'text generation pipeline', 'text generation system', 'text generation tool', 'text generation framework', 'text generation library', 'text generation api', 'text generation model', 'text generation models', 'text generation engine', 'text generation module', 'text generation function', 'text generation functionality', 'text generation workflow', 'text generation method', 'text generation approach', 'text generation service', 'text generation results', 'text generation performance', 'text generation task', 'text generation tasks', 'text generation algorithm', 'text generation algorithms', 'text generation configuration', 'text generation script', 'text generation mode', 'generative text', 'generate natural language', 'generates natural language', 'natural language generation', 'natural-language generation', 'nlg', 'language generation', 'language-generation', 'text completion', 'text-completion', 'complete text', 'completes text', 'ai-generated text', 'ai generated text']
EXPECTED_NEGATIVE = ['does not generate text', 'do not generate text', "doesn't generate text", "don't generate text", 'no text generation', 'without text generation', 'never generates text', 'does not support text generation', 'text generation not supported', 'text generation unsupported', 'no text generation support', 'lacks text generation', 'missing text generation', 'text generation disabled', 'no text generation model', 'without text generation support', 'does not provide text generation', 'no automatic text generation', 'text generation not available', 'no text generation capability', 'does not generate natural language', 'without a text generation model', 'does not perform text generation', 'never performs text generation']
EXPECTED_GENERIC = ['generate_text', 'text_generate', 'generate_completion', 'complete_text', 'generate_natural_language', 'natural_language_generation', 'generate_language', 'text_completion', 'continue_text', 'sample_text', 'write_text', 'compose_text', 'produce_text', 'create_text', 'generate_paragraph', 'generate_sentence', 'generate_story', 'generate_content', 'text_gen', 'generate_nlg', 'nlg_generate', 'generate_textual_content', 'autocomplete_text', 'predict_next_tokens']


def put(root, name, content):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as stream:
        stream.write(content)


class VocabularyTests(unittest.TestCase):
    def test_positive_oracle(self):
        self.assertEqual(TEXTGENERATION, EXPECTED_POSITIVE)
        self.assertEqual(len(TEXTGENERATION), 50)

    def test_negative_oracle(self):
        self.assertEqual(NOTEXTGENERATION, EXPECTED_NEGATIVE)
        self.assertEqual(len(NOTEXTGENERATION), 24)

    def test_generic_oracle(self):
        self.assertEqual(GENERIC_NAMES, EXPECTED_GENERIC)
        self.assertEqual(len(GENERIC_NAMES), 24)

    def test_every_positive(self):
        for phrase in EXPECTED_POSITIVE:
            with self.subTest(phrase=phrase):
                self.assertEqual(match_claims(phrase.upper())[0], [(0, phrase)])

    def test_every_negative(self):
        for phrase in EXPECTED_NEGATIVE:
            with self.subTest(phrase=phrase):
                positive, negative = match_claims(phrase)
                self.assertEqual(positive, [])
                self.assertEqual(negative, [(0, phrase)])

    def test_longest(self):
        self.assertEqual(match_claims('text generation model')[0], [(0, 'text generation model')])
        self.assertEqual(match_claims('generate text')[0], [(0, 'generate text')])
        self.assertEqual(len(match_claims('text generation models; text generation')[0]), 2)

    def test_file_collision(self):
        self.assertEqual(match_claims('we generate text files from the database')[0], [(3, 'generate text')])

    def test_fence(self):
        self.assertEqual(match_claims('```py\ntext generation\n```\n')[0], [])
        self.assertEqual(match_claims('~~~\ntext generation\n~~~')[0], [])

    def test_inline(self):
        self.assertEqual(match_claims('`text generation`')[0], [(0, 'text generation')])

    def test_no_normalization(self):
        self.assertEqual(match_claims('generate-text')[0], [])

    def test_substring(self):
        self.assertEqual(match_claims('xxnlgxx')[0], [(2, 'nlg')])


POSITIVE_ROUTES = [
    'import transformers as tf\ng = tf.pipeline("text-generation")\ng("hi")',
    'from transformers import pipeline as p\np("text-generation")("hi")',
    'from transformers import AutoModelForCausalLM as M\nm = M.from_pretrained("x")\nm.generate()',
    'import transformers as t\nt.GPT2LMHeadModel().generate()',
    'from transformers import LlamaForCausalLM\nm=LlamaForCausalLM()\nm.generate()',
    'from transformers import MistralForCausalLM as M\nM.from_pretrained("x").generate()',
    'import openai as o\nc=o.OpenAI()\nc.completions.create(prompt="x")',
    'from openai import OpenAI as O\nO().completions.create()',
    'import openai\nopenai.Completion.create()',
    'from openai import Completion as C\nC.create()',
    'from llama_cpp import Llama as L\nx=L()\nx("x")',
    'from gpt4all import GPT4All\nx=GPT4All("x")\nx.generate("hi")',
    'from ctransformers import AutoModelForCausalLM as M\nx=M.from_pretrained("x")\nx("hi")',
    'import vllm as v\nv.LLM("x").generate("hi")',
    'from llama_cpp import Llama\nLlama()("x")',
    'import ollama as o\no.generate(model="x")',
    'from ollama import generate as g\ng()',
    'import mlx_lm as m\nm.generate()',
    'from mlx_lm import generate as g\ng()',
    'unrelated.generate_text("hi")',
    'from custom import generate_text as g\ng("hi")',
]

REJECTIONS = [
    'import transformers, openai, llama_cpp, gpt4all, ctransformers, vllm, ollama, mlx_lm',
    'import transformers as t\nt.pipeline("text2text-generation")("x")',
    'import openai\nc=openai.OpenAI()\nc.chat.completions.create()',
    'import openai\nopenai.ChatCompletion.create()',
    'import ollama\nollama.chat()',
    'from transformers import AutoModelForCausalLM as M\nx=M.from_pretrained("x")',
    'from transformers import pipeline\nx=pipeline("text-generation")',
    'from llama_cpp import Llama\nx=Llama()',
    'from gpt4all import GPT4All\nx=GPT4All()',
    'from ctransformers import AutoModelForCausalLM\nx=AutoModelForCausalLM()',
    'from vllm import LLM\nx=LLM()',
    'image_model.generate()',
    'unbound.generate()',
    'from jinja2 import Template\nTemplate("x").render()',
    'from string import Template\nTemplate("$x").substitute(x="a")',
    'speech.synthesize("hi")',
    'images.generate()',
    'video.generate()',
    '"""text generation"""\n# generate text\nx="text generation"',
    'from custom import generate_text\ngenerate_text',
    'generate_text()',
    'import subprocess\nsubprocess.run(["ollama", "generate"])',
    'from custom import generate_text\ndef generate_text(): pass\ngenerate_text()',
    'from llama_cpp import Llama\nclass Llama: pass\nx=Llama()\nx("x")',
    'from transformers import pipeline\ndef pipeline(*a): pass\npipeline("text-generation")("x")',
    'from transformers import AutoModelForCausalLM as M\nclass M: pass\nM().generate()',
    'import ollama as o\ndef o(): pass\no.generate()',
]


class RouteTests(unittest.TestCase):
    def test_positive_routes(self):
        for source in POSITIVE_ROUTES:
            with self.subTest(source=source):
                self.assertTrue(evidence(source))

    def test_rejections(self):
        for source in REJECTIONS:
            with self.subTest(source=source):
                self.assertEqual(evidence(source), [])

    def test_other_tasks(self):
        for task in ['summarization', 'translation', 'text-classification', 'sentiment-analysis',
                     'question-answering', 'fill-mask', 'zero-shot-classification']:
            with self.subTest(task=task):
                self.assertEqual(evidence('from transformers import pipeline\npipeline(%r)("x")' % task), [])

    def test_all_causal_classes(self):
        for cls in ['AutoModelForCausalLM', 'GPT2LMHeadModel', 'LlamaForCausalLM', 'MistralForCausalLM',
                    'Qwen2ForCausalLM', 'GPTNeoForCausalLM', 'GPTJForCausalLM', 'OPTForCausalLM']:
            with self.subTest(cls=cls):
                self.assertTrue(evidence('from transformers import %s as M\nM().generate()' % cls))

    def test_all_generic_names(self):
        for name in EXPECTED_GENERIC:
            with self.subTest(name=name):
                self.assertEqual(evidence('obj.%s()' % name), ['generic'])
                self.assertEqual(evidence('from custom import %s as g\ng()' % name), ['generic'])
                self.assertEqual(evidence('def %s(): pass\nobj.%s()' % (name, name)), [])

    def test_runtime_case_insensitive_module(self):
        self.assertTrue(evidence('from vendor.LLAMA_CPP import Llama\nLlama()()'))

    def test_unrelated_completion(self):
        self.assertEqual(evidence('client.completions.create()'), [])

    def test_instance_alias(self):
        self.assertTrue(evidence('from transformers import pipeline\na=pipeline("text-generation")\nb=a\nb()'))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['audit', str(self.root)] + list(args))
        return code, out.getvalue(), err.getvalue()

    def test_good(self):
        put(self.root, 'README.md', 'text generation')
        put(self.root, 'app.py', 'import ollama\nollama.generate()')
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(audit_repo(self.root)[0], [])

    def test_bad(self):
        put(self.root, 'README.md', 'TEXT GENERATION')
        code, out, _ = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn('HIGH documented-text-generation-claim-false', out)

    def test_denial(self):
        put(self.root, 'README.md', 'does not generate text')
        put(self.root, 'app.py', 'import ollama\nollama.generate()')
        code, out, _ = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn('HIGH documented-no-text-generation-claim-false', out)

    def test_denial_without_source(self):
        put(self.root, 'README.md', 'does not generate text')
        self.assertEqual(audit_repo(self.root)[0], [])

    def test_test_only(self):
        put(self.root, 'tests/fixture.md', 'text generation')
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn('MEDIUM', out)
        self.assertEqual(self.run_cli('--fail-on', 'medium')[0], 2)

    def test_no_claim(self):
        put(self.root, 'README.md', 'Utilities for files.')
        self.assertEqual(self.run_cli()[0], 0)

    def test_json(self):
        put(self.root, 'README.md', 'text generation')
        code, out, _ = self.run_cli('--json')
        self.assertEqual(code, 2)
        result = json.loads(out)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertTrue(result['message'])
        self.assertEqual(result['findings'][0]['verdict'], 'FAIL')
        self.assertTrue(result['findings'][0]['message'])

    def test_ignore(self):
        put(self.root, 'docs/draft.md', 'text generation')
        self.assertEqual(self.run_cli('--ignore', 'docs/')[0], 0)
        put(self.root, 'README.md', 'text generation')
        self.assertEqual(self.run_cli('--ignore', 'docs/', '--ignore', 'README')[0], 0)

    def test_ignore_multiple_prefixes(self):
        put(self.root, 'docs/draft.md', 'text generation')
        put(self.root, 'README.md', 'text generation')
        self.assertEqual(self.run_cli('--ignore', 'docs/', 'README')[0], 0)

    def test_verbose(self):
        put(self.root, 'README.md', 'Utilities')
        code, _, err = self.run_cli('--verbose')
        self.assertEqual(code, 0)
        self.assertIn('Scope:', err)
        self.assertIn('README.md: scanned', err)

    def test_split_modules(self):
        put(self.root, 'README.md', 'text generation')
        put(self.root, 'a.py', 'from transformers import pipeline\ng=pipeline("text-generation")')
        put(self.root, 'b.py', 'g("hi")')
        self.assertEqual(self.run_cli()[0], 2)

    def test_excluded_directories(self):
        put(self.root, 'README.md', 'text generation')
        for directory in ['.git', '__pycache__', '.venv', 'venv', 'custom_env']:
            put(self.root, directory + '/evidence.py', 'import ollama\nollama.generate()')
        put(self.root, 'custom_env/pyvenv.cfg', '')
        self.assertEqual(self.run_cli()[0], 2)

    def test_io_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['audit', str(self.root / 'missing')]), 1)

    def test_syntax_error(self):
        put(self.root, 'bad.py', 'def bad(')
        self.assertEqual(self.run_cli()[0], 1)

    def test_usage(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                main(['audit', '--fail-on', 'low'])
        self.assertEqual(exc.exception.code, 1)

    def test_version(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exc:
                main(['--version'])
        self.assertEqual(exc.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), '0.1.0')
        self.assertEqual(__version__, '0.1.0')

    def test_readme_self_audit(self):
        readme = Path(__file__).resolve().parents[1] / 'README.md'
        content = readme.read_text(encoding='utf-8')
        self.assertEqual(match_claims(content), ([], []))
        self.assertNotIn('nlg', prose(content).lower())
        put(self.root, 'README.md', content)
        self.assertEqual(self.run_cli()[0], 0)

    def test_scope(self):
        put(self.root, 'notes.md', 'text generation')
        put(self.root, 'docs/nested/reference.md', 'text generation')
        findings, _, _ = audit_repo(self.root)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].path, 'docs/nested/reference.md')

    def test_default_repo(self):
        import os
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['audit']), 0)
        finally:
            os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
