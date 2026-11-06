"""Command-line entry point."""
import argparse
import json
import sys
from . import __version__
from .audit import audit_repo


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(prog='text-generation-claim-audit')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    command = sub.add_parser('audit', help='Check documentation against Python source')
    command.add_argument('repo', nargs='?', default='.')
    command.add_argument('--json', action='store_true')
    command.add_argument('--verbose', action='store_true')
    command.add_argument('--ignore', action='append', nargs='+', default=[])
    command.add_argument('--fail-on', choices=['high', 'medium'], default='high')
    args = parser.parse_args(argv)
    try:
        findings, sources, decisions = audit_repo(args.repo, [p for group in args.ignore for p in group])
    except (OSError, ValueError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 1
    failed = any(f.severity == 'HIGH' or args.fail_on == 'medium' for f in findings)
    if args.verbose:
        print('Scope: root README.md, docs/**/*.md, tests/** and Python sources in ' + args.repo, file=sys.stderr)
        for decision in decisions:
            print(decision, file=sys.stderr)
        for source in sources:
            print('Evidence: ' + source, file=sys.stderr)
    if args.json:
        print(json.dumps({'verdict': 'FAIL' if failed else 'PASS',
                          'message': 'Threshold exceeded' if failed else 'No findings at the selected threshold',
                          'findings': [f.to_dict() for f in findings]}, indent=2))
    else:
        print('FAIL' if failed else 'PASS')
        for finding in findings:
            print('{} {} {}: {}'.format(finding.severity, finding.rule, finding.path, finding.message))
    return 2 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
