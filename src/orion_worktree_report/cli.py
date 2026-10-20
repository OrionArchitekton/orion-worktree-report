"""The installed CLI is the supported seam."""
import argparse
import os
import sys
from . import __version__
from .report import failure, render, scan


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, allow_abbrev=False)

    def error(self, message):
        raise ValueError('invalid_invocation')


def main():
    p = Parser(prog='orion-worktree-report')
    p.add_argument('--json', action='store_true')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('version')
    s = sub.add_parser('scan')
    s.add_argument('--repo', action='append', required=True)
    try:
        a = p.parse_args()
    except ValueError:
        result = failure('invalid_invocation', 2)
    else:
        try:
            result = execute(a)
        except Exception:
            result = failure('internal_error', 70)
    try:
        text, code = render(result, '--json' in sys.argv[1:])
    except Exception:
        text, code = render(failure('internal_error', 70), '--json' in sys.argv[1:])
    try:
        raw = text.encode('utf-8')
        while raw:
            written = os.write(sys.stdout.fileno(), raw)
            if written <= 0:
                return 74
            raw = raw[written:]
    except OSError:
        return 74
    return code


def execute(a):
    if a.command == 'version':
        result = {'interface_version': 1, 'package_version': __version__, 'command': 'version',
                  'authority': 'none', 'capabilities': ['inventory.v1', 'dirty-path-overlaps.v1', 'coverage.v1'], 'exit': 0}
    else:
        result = scan(a.repo)
    return result
